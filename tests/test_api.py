"""Login/listing tests against a fake Auth0 + portal served by aiohttp."""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from aiohttp import ClientSession, CookieJar, web
from aiohttp.test_utils import TestServer

from custom_components.vag_data_act import api

LOGIN_HTML = """<html><body><form method="post">
<input type="hidden" name="state" value="{state}">
<input name="username"><input name="password">
<button type="submit" name="action" value="default">Continue</button>
</form></body></html>"""
BAD_HTML = LOGIN_HTML + '<span data-error-code="wrong-email-or-password"></span>'


def _zip(inner: str, payload: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(inner, json.dumps(payload))
    return buf.getvalue()


def make_app(mode: str) -> web.Application:
    app = web.Application()
    calls = {"list": 0}

    async def authorize(request):
        if mode == "outage":
            return web.Response(status=503)
        raise web.HTTPFound("/u/login?state=S1")

    async def login_get(request):
        return web.Response(text=LOGIN_HTML.format(state="S1"), content_type="text/html")

    async def login_post(request):
        form = await request.post()
        assert form["state"] == "S1" and form["action"] == "default"
        if mode == "badpw" or form["password"] != "pw":
            return web.Response(
                status=400, text=BAD_HTML.format(state="S1"), content_type="text/html"
            )
        if mode == "consent":
            raise web.HTTPFound("/terms-and-conditions?x=1")
        raise web.HTTPFound("/authorize/resume?state=S2")

    async def resume(request):
        raise web.HTTPSeeOther("/login?code=C&state=de__de__CUPRA")

    async def portal_login(request):
        raise web.HTTPFound("/services/callbacklogin?code=C")

    async def callback(request):
        resp = web.HTTPFound("/content/euda/de/de/user.html")
        resp.set_cookie("access_token", "tok", httponly=True)
        raise resp

    async def terms(request):
        return web.Response(text="<html>accept terms</html>", content_type="text/html")

    async def vehicles(request):
        if request.cookies.get("access_token") != "tok":
            return web.Response(status=401)
        return web.json_response(
            {"vehicles": [{"vin": "VSSZZZKRXSA000001", "vehicleNickname": "Tavascan"}]}
        )

    async def relation(request):
        return web.json_response({"relation": {"vehicleNickname": "Tavi"}})

    async def metadata(request):
        return web.json_response({"Identifier": "ID-1"})

    async def listing(request):
        calls["list"] += 1
        if request.cookies.get("access_token") != "tok":
            return web.Response(status=401)
        if mode == "list429" and calls["list"] == 1:
            return web.Response(status=429)
        assert request.headers["type"] == "partial"
        return web.json_response(
            [
                {
                    "name": "20261027161054_VSSZZZKRXSA000001.zip",
                    "createdOn": "2026-10-27T16:10:54Z",
                },
                {
                    "name": "20261027200113_VSSZZZKRXSA000001.zip",
                    "createdOn": "2026-10-27T20:01:13Z",
                },
                {"name": "20261027201500_VSSZZZKRXSA000001_no_content_found.zip"},
                {
                    "name": "20261027180109_VSSZZZKRXSA000001.zip",
                    "createdOn": "2026-10-27T18:01:09Z",
                },
            ]
        )

    async def download(request):
        assert request.headers["filename"].endswith(".zip")
        return web.Response(
            body=_zip("VSSZZZKRXSA000001_20261027200113.json", {"vin": "V", "Data": []}),
            content_type="application/zip",
        )

    app.router.add_get("/oidc/v1/authorize", authorize)
    app.router.add_get("/u/login", login_get)
    app.router.add_post("/u/login", login_post)
    app.router.add_get("/authorize/resume", resume)
    app.router.add_get("/login", portal_login)
    app.router.add_get("/services/callbacklogin", callback)
    app.router.add_get("/terms-and-conditions", terms)
    app.router.add_get("/proxy_api/consent/me/vehicles", vehicles)
    app.router.add_get("/proxy_api/vum/v2/users/me/relations/{vin}", relation)
    app.router.add_get("/proxy_api/euda-apim/datarequest/vehicles/{vin}/metadata/partial", metadata)
    app.router.add_get("/proxy_api/euda-apim/datadelivery/vehicles/{vin}/{id}/list", listing)
    app.router.add_get("/proxy_api/euda-apim/datadelivery/vehicles/{vin}/{id}/download", download)
    return app


pytestmark = pytest.mark.enable_socket


@pytest.fixture
async def portal(request, monkeypatch, socket_enabled):
    mode = getattr(request, "param", "ok")
    server = TestServer(make_app(mode))
    await server.start_server()
    base = f"http://{server.host}:{server.port}"
    host = f"{server.host}:{server.port}"
    monkeypatch.setattr(api, "PORTAL_BASE_URL", base)
    monkeypatch.setattr(api, "OIDC_AUTHORIZE_URL", f"{base}/oidc/v1/authorize")
    monkeypatch.setattr(api, "PORTAL_HOST", host)
    monkeypatch.setattr(api, "IDENTITY_HOST", host)
    jar = CookieJar(unsafe=True)
    async with ClientSession(cookie_jar=jar) as session:
        yield api.PortalClient(session, "me@example.com", "pw"), jar
    await server.close()


async def test_login_success_and_listing(portal):
    client, jar = portal
    await client.async_login()
    assert client.logged_in
    paths = [h.url.split(":", 2)[-1].split("/", 1)[1].split("?")[0] for h in client.last_login_hops]
    assert paths == [
        "oidc/v1/authorize",
        "u/login",
        "u/login",
        "authorize/resume",
        "login",
        "services/callbacklogin",
    ]
    assert [c.key for c in jar] == ["access_token"]
    vehicles = await client.async_list_vehicles()
    assert vehicles[0].vin == "VSSZZZKRXSA000001" and vehicles[0].nickname == "Tavi"
    ident = await client.async_get_identifier("VSSZZZKRXSA000001")
    datasets = await client.async_list_datasets("VSSZZZKRXSA000001", ident)
    assert len(datasets) == 4
    newest = api.newest_dataset(datasets)
    assert newest.name == "20261027200113_VSSZZZKRXSA000001.zip"
    ds = await client.async_download_dataset("VSSZZZKRXSA000001", ident, newest.name)
    assert ds.inner_name == "VSSZZZKRXSA000001_20261027200113.json"
    assert len(ds.sha256) == 64
    # cookie round trip
    items = api.cookies_to_list(jar)
    jar2 = CookieJar(unsafe=True)
    assert api.cookies_from_list(jar2, items) == 1


@pytest.mark.parametrize("portal", ["badpw"], indirect=True)
async def test_wrong_password(portal):
    client, _ = portal
    with pytest.raises(api.AuthFailed, match="wrong-email-or-password"):
        await client.async_login()
    assert not client.logged_in


@pytest.mark.parametrize("portal", ["consent"], indirect=True)
async def test_consent_interstitial(portal):
    client, _ = portal
    with pytest.raises(api.ConsentRequired):
        await client.async_login()


@pytest.mark.parametrize("portal", ["outage"], indirect=True)
async def test_outage_during_login(portal):
    client, _ = portal
    with pytest.raises(api.PortalOutage) as exc:
        await client.async_login()
    assert exc.value.status == 503


@pytest.mark.parametrize("portal", ["list429"], indirect=True)
async def test_429_is_outage_without_reauth(portal):
    client, _ = portal
    await client.async_login()
    gen = client._login_generation
    with pytest.raises(api.PortalOutage):
        await client.async_list_datasets("VSSZZZKRXSA000001", "ID-1")
    assert client._login_generation == gen


async def test_401_triggers_single_reauth(portal):
    client, jar = portal
    await client.async_login()
    jar.clear()  # session gone
    datasets = await client.async_list_datasets("VSSZZZKRXSA000001", "ID-1")
    assert len(datasets) == 4
    assert client._login_generation == 2
