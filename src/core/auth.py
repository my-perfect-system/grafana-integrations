"""Authentication and HTTP client for the Grafana API.

Responsibilities
----------------
* Load Grafana connection config (``GRAFANA_URL`` / ``GRAFANA_TOKEN``) from the
  environment or from ``data/.env``.
* Provide a thin HTTP client (``GrafanaClient``) with bearer-token auth and a
  ``GrafanaError`` for non-2xx responses.
* Validate connectivity/auth via ``check_connection``.
"""

from __future__ import annotations

import os

try:
    import requests
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - resolved via `pip install -r requirements.txt`
    requests = None
    load_dotenv = None

try:
    import urllib3
except ImportError:  # pragma: no cover
    urllib3 = None

from core import settings  # noqa: E402

# ---------------------------------------------------------------------------
# Grafana config (from env or data/.env)
# ---------------------------------------------------------------------------
GRAFANA_URL = os.environ.get("GRAFANA_URL", "")
GRAFANA_TOKEN = os.environ.get("GRAFANA_TOKEN", "")
GRAFANA_VERIFY_SSL = os.environ.get("GRAFANA_VERIFY_SSL", "true").lower() not in (
    "0",
    "false",
    "no",
)
GRAFANA_CA_CERT = os.environ.get("GRAFANA_CA_CERT", "")


class GrafanaError(RuntimeError):
    """Raised when the Grafana API returns a non-2xx status code."""


class GrafanaClient:
    """Thin bearer-token HTTP client for the Grafana API."""

    def __init__(
        self,
        base_url: str,
        token: str,
        verify: bool = True,
        ca_cert: str = "",
        timeout: int = 30,
    ) -> None:
        if requests is None:
            raise GrafanaError(
                "Missing dependency 'requests'. Run: pip install -r requirements.txt"
            )
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )
        if ca_cert:
            self.session.verify = ca_cert
        elif not verify:
            self.session.verify = False
            if urllib3 is not None:
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def get(self, path: str, **kwargs):
        return self.session.get(self._url(path), timeout=self.timeout, **kwargs)

    def post(self, path: str, **kwargs):
        return self.session.post(self._url(path), timeout=self.timeout, **kwargs)

    def put(self, path: str, **kwargs):
        return self.session.put(self._url(path), timeout=self.timeout, **kwargs)

    def delete(self, path: str, **kwargs):
        return self.session.delete(self._url(path), timeout=self.timeout, **kwargs)

    def request_json(self, method: str, path: str, **kwargs):
        """Perform a request and return parsed JSON, raising ``GrafanaError``
        on transport errors or non-2xx responses (with the body included)."""
        try:
            resp = getattr(self.session, method.lower())(
                self._url(path), timeout=self.timeout, **kwargs
            )
        except requests.RequestException as exc:
            raise GrafanaError(f"Request failed: {method} {path}: {exc}") from exc
        if not resp.ok:
            body = resp.text[:1000]
            err = GrafanaError(f"{method} {path} -> HTTP {resp.status_code}: {body}")
            err.status_code = resp.status_code  # type: ignore[attr-defined]
            raise err
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError as exc:
            raise GrafanaError(
                f"{method} {path} returned non-JSON body: {resp.text[:200]}"
            ) from exc


def load_config() -> None:
    """Load config from ``data/.env`` into the module globals.

    Environment variables always take precedence over the ``.env`` file
    (python-dotenv does not override pre-existing values by default). No-op if
    the ``.env`` file is absent.
    """
    global GRAFANA_URL, GRAFANA_TOKEN, GRAFANA_VERIFY_SSL, GRAFANA_CA_CERT

    if load_dotenv is not None:
        load_dotenv(settings.ENV_FILE)

    GRAFANA_URL = os.environ.get("GRAFANA_URL", GRAFANA_URL).rstrip("/")
    GRAFANA_TOKEN = os.environ.get("GRAFANA_TOKEN", GRAFANA_TOKEN)
    GRAFANA_VERIFY_SSL = os.environ.get("GRAFANA_VERIFY_SSL", "true").lower() not in (
        "0",
        "false",
        "no",
    )
    GRAFANA_CA_CERT = os.environ.get("GRAFANA_CA_CERT", "")


def get_client() -> GrafanaClient:
    """Return an authenticated :class:`GrafanaClient`.

    Raises :class:`GrafanaError` if ``GRAFANA_URL`` / ``GRAFANA_TOKEN`` are not
    configured.
    """
    if not GRAFANA_URL or not GRAFANA_TOKEN:
        raise GrafanaError(
            "GRAFANA_URL and GRAFANA_TOKEN must be set (via environment or data/.env). "
            "See data/.env.example."
        )
    return GrafanaClient(
        GRAFANA_URL,
        GRAFANA_TOKEN,
        verify=GRAFANA_VERIFY_SSL,
        ca_cert=GRAFANA_CA_CERT,
    )


def check_connection(client: GrafanaClient) -> dict:
    """Validate connectivity and token, returning a summary dict.

    * ``GET /api/health`` — reachability + server version (unauthenticated).
    * ``GET /api/org`` — current org (validates the bearer token).

    Raises :class:`GrafanaError` on failure.
    """
    health = client.request_json("GET", "/api/health") or {}
    org = client.request_json("GET", "/api/org") or {}
    return {
        "version": health.get("version", "unknown"),
        "database": health.get("database", "unknown"),
        "org_id": org.get("id"),
        "org_name": org.get("name"),
    }
