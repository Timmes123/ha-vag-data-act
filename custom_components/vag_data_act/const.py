"""Constants for the VAG EU Data Act integration (no Home Assistant imports)."""

from __future__ import annotations

DOMAIN = "vag_data_act"

PORTAL_BASE_URL = "https://eu-data-act.drivesomethinggreater.com"
IDENTITY_BASE_URL = "https://identity.vwgroup.io"
OIDC_AUTHORIZE_URL = f"{IDENTITY_BASE_URL}/oidc/v1/authorize"
OIDC_REDIRECT_URI = f"{PORTAL_BASE_URL}/login"
OIDC_SCOPE = "openid cars profile"
CALLBACK_LOGIN_PATH = "/services/callbacklogin"

VEHICLES_PATH = "/proxy_api/consent/me/vehicles"
RELATION_PATH = "/proxy_api/vum/v2/users/me/relations/{vin}"
METADATA_PATH = "/proxy_api/euda-apim/datarequest/vehicles/{vin}/metadata/partial"
LIST_PATH = "/proxy_api/euda-apim/datadelivery/vehicles/{vin}/{identifier}/list"
DOWNLOAD_PATH = "/proxy_api/euda-apim/datadelivery/vehicles/{vin}/{identifier}/download"
NO_CONTENT_SUFFIX = "_no_content_found.zip"

# OIDC client ids per brand (evcc vehicle/vw/eudataact/types.go, ioBroker.vw-connect).
BRANDS: dict[str, tuple[str, str]] = {
    "CUPRA": ("f85e5b69-e3b2-43aa-9c0d-1b7d0e0b576f@apps_vw-dilab_com", "CUPRA"),
    "SEAT": ("f85e5b69-e3b2-43aa-9c0d-1b7d0e0b576f@apps_vw-dilab_com", "SEAT"),
    "VOLKSWAGEN": (
        "9b58543e-1c15-4193-91d5-8a14145bebb0@apps_vw-dilab_com",
        "VOLKSWAGEN_PASSENGER_CARS",
    ),
    "AUDI": ("cc29b87a-5e9a-4362-aecf-5adea6b01bbb@apps_vw-dilab_com", "AUDI"),
    "SKODA": ("3ea88bf9-1d4e-4a68-b3ad-4098c1f1d246@apps_vw-dilab_com", "SKODA"),
}

DEFAULT_BRAND = "CUPRA"
DEFAULT_COUNTRY = "de"
DEFAULT_LANGUAGE = "de"

CONF_BRAND = "brand"
CONF_COUNTRY = "country"
CONF_LANGUAGE = "language"
CONF_VIN = "vin"
CONF_NICKNAME = "nickname"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_SCAN_INTERVAL_MINUTES = 15
MIN_SCAN_INTERVAL_MINUTES = 5
MAX_OUTAGE_BACKOFF_MINUTES = 120

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)

LOGIN_STATUS_OK = "ok"
LOGIN_STATUS_AUTH_FAILED = "auth_failed"
LOGIN_STATUS_CONSENT_REQUIRED = "consent_required"
LOGIN_STATUS_PORTAL_ERROR = "portal_error"
LOGIN_STATUS_UNKNOWN = "unknown"

ISSUE_AUTH_FAILED = "auth_failed"
ISSUE_CONSENT_REQUIRED = "consent_required"

SERVICE_REFRESH_NOW = "refresh_now"
SERVICE_SCAN_DATASETS = "scan_datasets"
