"""Testing a connection: can this key reach this provider, and which models does it see?
(PRD §10.2: "When it's added, H.E.X tests it and lists the models it can reach.")

Error text is built here from status codes and exception types only. Provider response bodies
are never copied into it: some providers echo part of a rejected key.
"""

import re
import time
from ipaddress import ip_address
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel

from app.providers.anthropic import ANTHROPIC_VERSION
from app.providers.presets import ProviderPreset

_HEADER_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,63}$")
_SECRET_HEADER = re.compile(r"auth|key|token|secret|cookie|password", re.IGNORECASE)
_LOOPBACK_NAMES = {"localhost"}
MAX_MODELS = 2000


class ProbeResult(BaseModel):
    ok: bool
    error: str | None = None
    models: list[str] = []
    latency_ms: int = 0
    # The provider said the key is not valid (as opposed to the provider being unreachable).
    auth_rejected: bool = False


def is_loopback(host: str) -> bool:
    if host.lower() in _LOOPBACK_NAMES:
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def validate_base_url(url: str, *, has_key: bool) -> str:
    """A normalised base URL, or ValueError. A key is never sent over plain http to a remote
    host, and a URL cannot carry credentials."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("the base URL must start with http:// or https:// and name a host")
    if parts.username or parts.password:
        raise ValueError("the base URL must not contain a username or password")
    if parts.query or parts.fragment:
        raise ValueError("the base URL must not contain a query or fragment")
    if has_key and parts.scheme == "http" and not is_loopback(parts.hostname):
        raise ValueError("an API key must not be sent over plain http to a remote host: use https")
    return url.strip().rstrip("/")


def validate_headers(headers: dict[str, str]) -> dict[str, str]:
    """Extra headers are stored in the database, so they must not carry secrets."""
    if len(headers) > 10:
        raise ValueError("at most 10 extra headers")
    for name, value in headers.items():
        if not _HEADER_NAME.match(name):
            raise ValueError(f"{name!r} is not a valid header name")
        if _SECRET_HEADER.search(name):
            raise ValueError(
                f"the header {name!r} looks like a credential: keys belong in the key store"
            )
        if len(value) > 256 or "\n" in value or "\r" in value:
            raise ValueError(f"the value of header {name!r} is not valid")
    return dict(headers)


def _request(
    preset: ProviderPreset, base_url: str, api_key: str | None, extra: dict[str, str]
) -> tuple[str, dict[str, str], dict[str, str] | None]:
    headers = dict(extra)
    params: dict[str, str] | None = None
    if preset.adapter == "anthropic":
        headers["anthropic-version"] = ANTHROPIC_VERSION
        if api_key:
            headers["x-api-key"] = api_key
        return f"{base_url}/v1/models", headers, {"limit": "1000"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if preset.adapter == "ollama":
        return f"{base_url}/api/tags", headers, params
    return f"{base_url}/models", headers, params


def _model_ids(preset: ProviderPreset, payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return []
    if preset.adapter == "ollama":
        items = [m.get("name") for m in payload.get("models", []) if isinstance(m, dict)]
    else:
        # Google's list prefixes ids with "models/".
        items = [
            str(m.get("id", "")).removeprefix("models/")
            for m in payload.get("data", [])
            if isinstance(m, dict)
        ]
    return sorted({str(i) for i in items if i})[:MAX_MODELS]


async def probe(
    preset: ProviderPreset,
    base_url: str,
    api_key: str | None,
    extra_headers: dict[str, str],
    http: httpx.AsyncClient,
) -> ProbeResult:
    url, headers, params = _request(preset, base_url, api_key, extra_headers)
    started = time.perf_counter()

    def elapsed() -> int:
        return round((time.perf_counter() - started) * 1000)

    try:
        response = await http.get(url, headers=headers, params=params, follow_redirects=False)
    except httpx.TimeoutException:
        return ProbeResult(
            ok=False, error="the provider did not answer in time", latency_ms=elapsed()
        )
    except httpx.HTTPError as exc:
        return ProbeResult(
            ok=False,
            error=f"could not connect ({type(exc).__name__}): check the base URL",
            latency_ms=elapsed(),
        )
    status = response.status_code
    if status in (401, 403):
        return ProbeResult(
            ok=False,
            error="the provider rejected the key",
            latency_ms=elapsed(),
            auth_rejected=True,
        )
    if status == 404:
        return ProbeResult(
            ok=False, error="the provider has no model list at this URL: check the base URL",
            latency_ms=elapsed(),
        )  # fmt: skip
    if status == 429:
        return ProbeResult(
            ok=False, error="the provider is rate limiting right now: try again shortly",
            latency_ms=elapsed(),
        )  # fmt: skip
    if status != 200:
        return ProbeResult(
            ok=False, error=f"the provider answered HTTP {status}", latency_ms=elapsed()
        )
    try:
        models = _model_ids(preset, response.json())
    except ValueError:
        return ProbeResult(
            ok=False, error="the provider's answer was not a model list", latency_ms=elapsed()
        )
    return ProbeResult(ok=True, models=models, latency_ms=elapsed())
