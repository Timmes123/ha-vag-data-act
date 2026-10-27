"""aiohttp client for the VW group EU Data Act portal.

Login flow (Auth0 Universal Login, since 2026-10-26; evcc PR #35385 / issue #35377):

1. GET  identity.vwgroup.io/oidc/v1/authorize?client_id=…&redirect_uri=…/login&
        response_type=code&scope=openid cars profile&state={country}__{language}__{BRAND}&
        nonce=<random>&prompt=login            -> 302 /u/login?state=<auth0 state>
2. GET  /u/login?state=…                       -> 200 HTML with hidden input ``state``
3. POST /u/login?state=…  (state, username, password, action=default)
4. Redirect chain: /authorize/resume -> /v2/api/flow-state/post-login -> /continue ->
   /authorize/resume -> portal /login?code=… -> portal /services/callbacklogin?code=…
   (sets the session cookies) -> /content/euda/<c>/<l>/user.html -> /<c>/<l>/user.html.
   Passing ``/services/callbacklogin`` counts as success.
5. Interstitials: terms-and-conditions, consent pages -> ``ConsentRequired``; marketing
   consent (classic ``callback`` param or v2 ``…/marketing-consent/skip``) is skipped.

Data API (TommiG1/HA_VAG-EU-Data-Act, evcc): ``/proxy_api/consent/me/vehicles``,
``…/datarequest/vehicles/<vin>/metadata/partial`` (Identifier),
``…/datadelivery/vehicles/<vin>/<identifier>/list`` (header ``type: partial``),
``…/download`` (headers ``filename``, ``type: partial``).

Error policy: 429/5xx -> ``PortalOutage`` (retry with backoff, no re-login);
401/403 on data calls -> one re-login, then retry.
No Home Assistant imports in this module.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import secrets
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import aiohttp
from yarl import URL

from .const import (
    BRANDS,
    CALLBACK_LOGIN_PATH,
    DEFAULT_BRAND,
    DEFAULT_COUNTRY,
    DEFAULT_LANGUAGE,
    DOWNLOAD_PATH,
    IDENTITY_BASE_URL,
    LIST_PATH,
    METADATA_PATH,
    NO_CONTENT_SUFFIX,
    OIDC_AUTHORIZE_URL,
    OIDC_REDIRECT_URI,
    OIDC_SCOPE,
    PORTAL_BASE_URL,
    RELATION_PATH,
    USER_AGENT,
    VEHICLES_PATH,
)
from .parser import parse_timestamp

_LOGGER = logging.getLogger(__name__)

PORTAL_HOST = urlparse(PORTAL_BASE_URL).netloc
IDENTITY_HOST = urlparse(IDENTITY_BASE_URL).netloc
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
OUTAGE_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_REDIRECTS = 20


# --- errors --------------------------------------------------------------------------


class PortalError(Exception):
    """Base error."""

    def __init__(self, message: str, *, status: int | None = None, url: str | None = None):
        super().__init__(message)
        self.status = status
        self.url = url


class AuthFailed(PortalError):
    """Wrong e-mail/password or the session cannot be established."""


class ConsentRequired(PortalError):
    """Terms/consent interstitial: the user has to open the portal once in a browser."""


class PortalOutage(PortalError):
    """HTTP 429/5xx or a network error: retry later, do not re-authenticate."""


class NotConfigured(PortalError):
    """No continuous data request configured for the vehicle in the portal."""


# --- data structures -----------------------------------------------------------------


@dataclass
class Vehicle:
    vin: str
    nickname: str | None = None
    model: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class DatasetInfo:
    name: str
    created_on: datetime | None
    size: int | None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def has_content(self) -> bool:
        return not self.name.lower().endswith(NO_CONTENT_SUFFIX)


@dataclass
class Dataset:
    """A downloaded and unpacked dataset."""

    zip_name: str
    inner_name: str
    content: bytes
    sha256: str
    zip_size: int


@dataclass
class Hop:
    """One step of the login redirect chain (for DEBUG logging and the trace tool)."""

    method: str
    url: str
    status: int
    location: str | None = None


# --- html helpers --------------------------------------------------------------------


class _FormParser(HTMLParser):
    """Collect the first form's action and its input/button fields."""

    def __init__(self) -> None:
        super().__init__()
        self.action: str | None = None
        self.fields: dict[str, str] = {}
        self.error_code: str | None = None
        self._in_form = False
        self._done = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if a.get("data-error-code") and not self.error_code:
            self.error_code = a["data-error-code"]
        if self._done:
            return
        if tag == "form" and not self._in_form:
            self.action = a.get("action")
            self._in_form = True
        elif tag == "input" and self._in_form and a.get("name"):
            self.fields[a["name"]] = a.get("value") or ""
        elif tag == "button" and self._in_form and a.get("name"):
            if (a.get("type") or "submit") == "submit":
                self.fields.setdefault(a["name"], a.get("value") or "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self._in_form:
            self._in_form = False
            self._done = True


def parse_login_form(html: str) -> _FormParser:
    p = _FormParser()
    p.feed(html)
    return p


def redact_url(url: str) -> str:
    """Hide code/state/token-like query values for logging."""
    parsed = urlparse(url)
    if not parsed.query:
        return url
    q = parse_qs(parsed.query, keep_blank_values=True)
    redacted = {
        k: (["<redacted>"] if k.lower() in {"code", "state", "nonce", "hmac", "relaystate"} else v)
        for k, v in q.items()
    }
    return parsed._replace(query=urlencode(redacted, doseq=True)).geturl()


# --- cookie persistence --------------------------------------------------------------


def cookies_to_list(jar: aiohttp.CookieJar) -> list[dict[str, Any]]:
    """Serialize a cookie jar into JSON-able dicts."""
    out = []
    for morsel in jar:
        out.append(
            {
                "name": morsel.key,
                "value": morsel.value,
                "domain": morsel["domain"],
                "path": morsel["path"] or "/",
                "expires": morsel["expires"],
                "secure": bool(morsel["secure"]),
                "httponly": bool(morsel["httponly"]),
            }
        )
    return out


def cookies_from_list(jar: aiohttp.CookieJar, items: list[dict[str, Any]]) -> int:
    """Restore cookies into a jar. Returns the number of cookies restored."""
    count = 0
    for item in items:
        try:
            cookie: SimpleCookie = SimpleCookie()
            cookie[item["name"]] = item["value"]
            m = cookie[item["name"]]
            domain = item.get("domain") or ""
            m["domain"] = domain
            m["path"] = item.get("path") or "/"
            if item.get("expires"):
                m["expires"] = item["expires"]
            m["secure"] = bool(item.get("secure"))
            m["httponly"] = bool(item.get("httponly"))
            host = domain.lstrip(".") or PORTAL_HOST
            jar.update_cookies(cookie, URL(f"https://{host}/"))
            count += 1
        except KeyError, TypeError, ValueError:
            continue
    return count


# --- client --------------------------------------------------------------------------


class PortalClient:
    """Authenticated client for one portal account (one client per account!)."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        email: str,
        password: str,
        *,
        brand: str = DEFAULT_BRAND,
        country: str = DEFAULT_COUNTRY,
        language: str = DEFAULT_LANGUAGE,
    ) -> None:
        self._session = session
        self._email = email
        self._password = password
        brand_key = brand.upper()
        if brand_key not in BRANDS:
            raise ValueError(f"unknown brand {brand}")
        self._client_id, self._brand_state = BRANDS[brand_key]
        self._country = country.lower()
        self._language = language.lower()
        self._login_lock = asyncio.Lock()
        self._login_generation = 0
        self.logged_in = False
        self.last_login_hops: list[Hop] = []
        self.on_session_changed: Any = None  # async callback after a successful login

    # -- helpers ----------------------------------------------------------------------

    def _headers(self, referer: str | None = None, **extra: str) -> dict[str, str]:
        h = {
            "User-Agent": USER_AGENT,
            "Accept-Language": f"{self._language}-{self._country.upper()},{self._language};q=0.9,en;q=0.8",
            **extra,
        }
        if referer:
            h["Referer"] = referer
        return h

    def authorize_url(self) -> str:
        params = {
            "client_id": self._client_id,
            "redirect_uri": OIDC_REDIRECT_URI,
            "response_type": "code",
            "scope": OIDC_SCOPE,
            "state": f"{self._country}__{self._language}__{self._brand_state}",
            "nonce": secrets.token_urlsafe(32),
            "prompt": "login",
        }
        return f"{OIDC_AUTHORIZE_URL}?{urlencode(params)}"

    async def _follow(
        self,
        method: str,
        url: str,
        *,
        data: dict[str, str] | None = None,
        referer: str | None = None,
        hops: list[Hop],
        stop_at_callback: bool = True,
    ) -> tuple[aiohttp.ClientResponse, str]:
        """Perform a request and follow redirects manually, logging every hop.

        Returns the final response (body not read) and its body text.
        """
        current_url = url
        current_method = method
        body: dict[str, str] | None = data
        for _ in range(MAX_REDIRECTS):
            host = urlparse(current_url).netloc.lower()
            if host not in (PORTAL_HOST, IDENTITY_HOST):
                raise PortalError(f"unexpected redirect host {host}", url=current_url)
            try:
                resp = await self._session.request(
                    current_method,
                    current_url,
                    data=body,
                    headers=self._headers(referer),
                    allow_redirects=False,
                )
            except aiohttp.ClientError as err:
                raise PortalOutage(f"network error at {redact_url(current_url)}: {err}") from err
            location = resp.headers.get("Location")
            hop = Hop(current_method, current_url, resp.status, location)
            hops.append(hop)
            _LOGGER.debug(
                "login hop %s %s -> %s%s",
                hop.method,
                redact_url(hop.url),
                hop.status,
                f" -> {redact_url(location)}" if location else "",
            )
            if resp.status in OUTAGE_STATUSES:
                resp.release()
                raise PortalOutage(
                    f"HTTP {resp.status} at {redact_url(current_url)}",
                    status=resp.status,
                    url=current_url,
                )
            if resp.status in REDIRECT_STATUSES and location:
                next_url = urljoin(current_url, location)
                resp.release()
                if stop_at_callback and _is_portal_callback(current_url):
                    # The callback has set the session cookies; the CMS landing page
                    # is irrelevant (and 4xx/5xx for some locales).
                    return resp, ""
                referer = current_url
                current_url = next_url
                current_method = "GET"
                body = None
                continue
            text = await resp.text(errors="replace")
            return resp, text
        raise PortalError("too many redirects during login", url=current_url)

    # -- login ------------------------------------------------------------------------

    async def async_login(self) -> None:
        """Run the full login, serialized; concurrent callers reuse the first result."""
        generation = self._login_generation
        async with self._login_lock:
            if self._login_generation != generation:
                return  # someone else logged in meanwhile
            await self._do_login()
            self._login_generation += 1
            self.logged_in = True
            if self.on_session_changed is not None:
                await self.on_session_changed()

    async def _do_login(self) -> None:
        hops: list[Hop] = []
        self.last_login_hops = hops
        self._session.cookie_jar.clear()
        _LOGGER.debug("login step 1: authorize")
        resp, html = await self._follow("GET", self.authorize_url(), hops=hops)
        login_url = str(resp.url)
        if resp.status != 200 or "/u/login" not in urlparse(login_url).path:
            raise PortalError(
                f"login step 1 ended at HTTP {resp.status} {redact_url(login_url)}",
                status=resp.status,
                url=login_url,
            )
        form = parse_login_form(html)
        if "state" not in form.fields:
            raise PortalError(
                f"login step 2: Auth0 form without state (fields {sorted(form.fields)})",
                url=login_url,
            )
        _LOGGER.debug("login step 2: form fields %s", sorted(form.fields))
        payload = {
            "state": form.fields["state"],
            "username": self._email,
            "password": self._password,
            "action": form.fields.get("action") or "default",
        }
        _LOGGER.debug("login step 3: POST credentials")
        resp, html = await self._follow(
            "POST", login_url, data=payload, referer=login_url, hops=hops
        )
        await self._judge_landing(resp, html, hops)
        _LOGGER.info("portal login successful for %s", self._email)

    async def _judge_landing(
        self,
        resp: aiohttp.ClientResponse,
        html: str,
        hops: list[Hop],
        *,
        _marketing_skipped: bool = False,
    ) -> None:
        landing = str(resp.url)
        path = urlparse(landing).path
        passed_callback = any(_is_portal_callback(h.url) and h.status < 400 for h in hops)
        if passed_callback:
            _LOGGER.debug("login step 4: passed %s", CALLBACK_LOGIN_PATH)
            return

        # Marketing consent interstitials: skip without consenting.
        if "/consent/marketing/" in path and not _marketing_skipped:
            cb = parse_qs(urlparse(landing).query).get("callback", [""])[0]
            if not cb:
                raise ConsentRequired("marketing consent page without callback", url=landing)
            _LOGGER.debug("login step 4: skipping marketing consent via callback")
            resp, html = await self._follow("GET", urljoin(landing, cb), referer=landing, hops=hops)
            await self._judge_landing(resp, html, hops, _marketing_skipped=True)
            return
        if "/login/ui/marketing-consent" in path and not _marketing_skipped:
            qs = parse_qs(urlparse(landing).query)
            fields = {k: qs.get(k, [""])[0] for k in ("relayState", "state")}
            skip_url = (
                urlparse(landing)._replace(path=path.rstrip("/") + "/skip", query="").geturl()
            )
            _LOGGER.debug("login step 4: skipping marketing consent v2")
            resp, html = await self._follow(
                "POST", skip_url, data=fields, referer=landing, hops=hops
            )
            await self._judge_landing(resp, html, hops, _marketing_skipped=True)
            return

        form = parse_login_form(html)
        if "terms-and-conditions" in path or "/consent" in path or "signin-service" in path:
            raise ConsentRequired(
                "the identity provider requires confirmation in the browser "
                f"(terms/consent) at {redact_url(landing)}",
                status=resp.status,
                url=landing,
            )
        if "/u/login" in path:
            raise AuthFailed(
                f"credentials rejected ({form.error_code or f'HTTP {resp.status}'})",
                status=resp.status,
                url=landing,
            )
        if resp.status >= 400:
            raise PortalError(
                f"login ended with HTTP {resp.status} at {redact_url(landing)}",
                status=resp.status,
                url=landing,
            )
        raise PortalError(f"login did not complete, landed at {redact_url(landing)}", url=landing)

    # -- data calls -------------------------------------------------------------------

    async def _get(
        self,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        allow_404: bool = False,
        _retry: bool = True,
    ) -> tuple[int, bytes]:
        url = f"{PORTAL_BASE_URL}{path}"
        generation = self._login_generation
        if not self.logged_in:
            await self.async_login()
        try:
            async with self._session.get(
                url, headers=self._headers(**(headers or {})), allow_redirects=False
            ) as resp:
                status = resp.status
                body = await resp.read()
        except aiohttp.ClientError as err:
            raise PortalOutage(f"network error for {path}: {err}") from err
        _LOGGER.debug("GET %s -> %s (%d bytes)", path, status, len(body))
        if status in (401, 403) or (status in REDIRECT_STATUSES and _retry):
            # A redirect to the login page means the session is gone as well.
            if not _retry:
                raise AuthFailed(f"session rejected (HTTP {status}) for {path}", status=status)
            self.logged_in = False
            if self._login_generation == generation:
                await self.async_login()
            return await self._get(path, headers=headers, allow_404=allow_404, _retry=False)
        if status in OUTAGE_STATUSES:
            raise PortalOutage(f"HTTP {status} for {path}", status=status, url=url)
        if status == 404 and allow_404:
            return status, body
        if status >= 400:
            raise PortalError(f"HTTP {status} for {path}", status=status, url=url)
        return status, body

    async def _get_json(
        self, path: str, *, headers: dict[str, str] | None = None, allow_404: bool = False
    ) -> Any:
        status, body = await self._get(
            path, headers={"Accept": "application/json", **(headers or {})}, allow_404=allow_404
        )
        if status == 404:
            return None
        try:
            return json.loads(body)
        except ValueError as err:
            raise PortalError(f"invalid JSON from {path}", url=path) from err

    async def async_list_vehicles(self) -> list[Vehicle]:
        data = await self._get_json(f"{VEHICLES_PATH}?viewPosition=FRONT_LEFT")
        items = data.get("vehicles", []) if isinstance(data, dict) else (data or [])
        vehicles: list[Vehicle] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            vin = item.get("vin") or item.get("vehicleIdentificationNumber")
            if not isinstance(vin, str) or len(vin) != 17:
                continue
            vehicles.append(
                Vehicle(
                    vin=vin,
                    nickname=item.get("vehicleNickname")
                    or item.get("nickName")
                    or item.get("nickname"),
                    model=item.get("modelName"),
                    raw=item,
                )
            )
        for v in vehicles:
            try:
                rel = await self._get_json(
                    RELATION_PATH.format(vin=v.vin),
                    headers={"traceid": f"vehicle-relation-{secrets.token_hex(8)}"},
                )
            except PortalError as err:
                _LOGGER.debug("relation lookup for %s failed: %s", v.vin[-4:], err)
                continue
            if isinstance(rel, dict):
                nick = (rel.get("relation") or {}).get("vehicleNickname")
                if nick:
                    v.nickname = nick
        return vehicles

    async def async_get_identifier(self, vin: str) -> str:
        data = await self._get_json(METADATA_PATH.format(vin=vin), allow_404=True)
        identifier = (data or {}).get("Identifier") if isinstance(data, dict) else None
        if not identifier:
            raise NotConfigured("no continuous data request configured in the portal")
        return str(identifier)

    async def async_list_datasets(self, vin: str, identifier: str) -> list[DatasetInfo]:
        data = await self._get_json(
            LIST_PATH.format(vin=vin, identifier=identifier),
            headers={"type": "partial"},
            allow_404=True,
        )
        if data is None:
            return []
        items = data.get("files", []) if isinstance(data, dict) else data
        result: list[DatasetInfo] = []
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                continue
            created = parse_timestamp(str(item.get("createdOn") or "")) or _time_from_name(
                item["name"]
            )
            size = item.get("size")
            result.append(
                DatasetInfo(
                    item["name"],
                    created,
                    int(size) if isinstance(size, (int, float)) else None,
                    item,
                )
            )
        return result

    async def async_download_dataset(self, vin: str, identifier: str, name: str) -> Dataset:
        _, body = await self._get(
            DOWNLOAD_PATH.format(vin=vin, identifier=identifier),
            headers={"filename": name, "type": "partial", "Accept": "*/*"},
        )
        return unpack_dataset(name, body)


def _is_portal_callback(url: str) -> bool:
    p = urlparse(url)
    return p.netloc.lower() == PORTAL_HOST and p.path.startswith(CALLBACK_LOGIN_PATH)


def _time_from_name(name: str) -> datetime | None:
    """``20261027180109_VIN.zip`` -> datetime (UTC)."""
    stamp = name.split("_", 1)[0]
    if len(stamp) == 14 and stamp.isdigit():
        try:
            return datetime.strptime(stamp + "+0000", "%Y%m%d%H%M%S%z")
        except ValueError:
            return None
    return None


def newest_dataset(datasets: list[DatasetInfo]) -> DatasetInfo | None:
    """Pick the newest content dataset by created_on (never by list order)."""
    candidates = [d for d in datasets if d.has_content and d.created_on is not None]
    if not candidates:
        return None
    return max(candidates, key=lambda d: d.created_on)  # type: ignore[arg-type, return-value]


def unpack_dataset(zip_name: str, body: bytes) -> Dataset:
    """Extract the single inner JSON of a dataset ZIP and hash it."""
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            members = [n for n in zf.namelist() if n.lower().endswith(".json")]
            if len(members) != 1:
                raise PortalError(f"{zip_name}: expected one JSON member, got {members}")
            content = zf.read(members[0])
    except zipfile.BadZipFile as err:
        raise PortalError(f"{zip_name}: not a ZIP archive ({len(body)} bytes)") from err
    digest = hashlib.sha256(content).hexdigest()
    _LOGGER.debug(
        "dataset %s -> %s sha256=%s (%d bytes)", zip_name, members[0], digest[:16], len(content)
    )
    return Dataset(zip_name, members[0], content, digest, len(body))
