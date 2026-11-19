"""The models.dev open catalog: prices, context windows and capabilities (PRD §10.3).

The public catalog is about 7 MB for hundreds of providers. Only the providers our connection
types map to are kept, in a small cache file, so the app works offline and starts fast. Fetching
sends no user data (a plain GET), and a failed refresh keeps the previous cache. A model the
catalog does not know is reported as unknown; nothing is guessed.
"""

import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

URL = "https://models.dev/api.json"
MAX_BYTES = 30_000_000
CACHE_NAME = "models.dev.json"

# Our provider type -> the provider id models.dev uses. Local providers have no API prices.
PROVIDER_IDS: dict[str, str] = {
    "openrouter": "openrouter",
    "anthropic": "anthropic",
    "openai": "openai",
    "google": "google",
    "nvidia": "nvidia",
    "deepseek": "deepseek",
    "glm": "zhipuai",
    "moonshot": "moonshotai",
    "groq": "groq",
    "mistral": "mistral",
    "xai": "xai",
}
_DATE_SUFFIX = re.compile(r"-(?:\d{8}|\d{4}-\d{2}-\d{2}|latest)$")


class CatalogError(RuntimeError):
    pass


class CatalogModel(BaseModel):
    id: str
    name: str
    family: str | None = None
    context_window: int | None = None
    max_output: int | None = None
    input_per_mtok: Decimal | None = None
    output_per_mtok: Decimal | None = None
    cache_read_per_mtok: Decimal | None = None
    tool_call: bool | None = None
    reasoning: bool | None = None
    structured_output: bool | None = None
    open_weights: bool | None = None
    status: str | None = None  # e.g. "deprecated"
    release_date: str | None = None
    input_modalities: list[str] = []


def _money(value: Any) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number >= 0 else None


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def parse_model(raw: dict[str, Any]) -> CatalogModel | None:
    model_id = raw.get("id")
    if not isinstance(model_id, str) or not model_id:
        return None
    cost = raw.get("cost") if isinstance(raw.get("cost"), dict) else {}
    limit = raw.get("limit") if isinstance(raw.get("limit"), dict) else {}
    modalities = raw.get("modalities") if isinstance(raw.get("modalities"), dict) else {}
    return CatalogModel(
        id=model_id,
        name=str(raw.get("name") or model_id),
        family=raw.get("family") if isinstance(raw.get("family"), str) else None,
        context_window=_int(limit.get("context")),
        max_output=_int(limit.get("output")),
        input_per_mtok=_money(cost.get("input")) if "input" in cost else None,
        output_per_mtok=_money(cost.get("output")) if "output" in cost else None,
        cache_read_per_mtok=_money(cost.get("cache_read")) if "cache_read" in cost else None,
        tool_call=_bool(raw.get("tool_call")),
        reasoning=_bool(raw.get("reasoning")),
        structured_output=_bool(raw.get("structured_output")),
        open_weights=_bool(raw.get("open_weights")),
        status=raw.get("status") if isinstance(raw.get("status"), str) else None,
        release_date=raw.get("release_date") if isinstance(raw.get("release_date"), str) else None,
        input_modalities=[m for m in modalities.get("input", []) if isinstance(m, str)],
    )


def parse(payload: Any) -> dict[str, dict[str, CatalogModel]]:
    """models.dev provider id -> model id -> model, for the providers we map. Malformed entries
    are skipped, so one bad row cannot break the catalog."""
    if not isinstance(payload, dict):
        raise CatalogError("the catalog is not a JSON object")
    wanted = set(PROVIDER_IDS.values())
    result: dict[str, dict[str, CatalogModel]] = {}
    for provider_id in wanted:
        models = (payload.get(provider_id) or {}).get("models")
        if not isinstance(models, dict):
            continue
        parsed = {}
        for raw in models.values():
            if isinstance(raw, dict) and (model := parse_model(raw)) is not None:
                parsed[model.id] = model
        result[provider_id] = parsed
    return result


class CatalogData(BaseModel):
    fetched_at: float  # unix time
    models: dict[str, dict[str, CatalogModel]]

    def count(self) -> int:
        return sum(len(m) for m in self.models.values())

    def find(self, provider_type: str, model_id: str) -> CatalogModel | None:
        provider = self.models.get(PROVIDER_IDS.get(provider_type, ""), {})
        for candidate in _candidates(model_id):
            if candidate in provider:
                return provider[candidate]
        return None


def _candidates(model_id: str) -> list[str]:
    """The ids a model may be listed under: as given, without Google's "models/" prefix, and
    without a date or "-latest" suffix."""
    base = model_id.removeprefix("models/")
    options = [model_id, base, _DATE_SUFFIX.sub("", base)]
    return list(dict.fromkeys(options))


def load_cache(directory: Path) -> CatalogData | None:
    path = directory / CACHE_NAME
    try:
        return CatalogData.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None  # missing or damaged: treated as no cache


def save_cache(directory: Path, data: CatalogData) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / (CACHE_NAME + ".tmp")
    temporary.write_text(data.model_dump_json(), encoding="utf-8")
    temporary.replace(directory / CACHE_NAME)


async def fetch(http: httpx.AsyncClient, url: str = URL) -> CatalogData:
    """Download and parse the catalog. Raises CatalogError with a short reason on any problem."""
    try:
        async with http.stream("GET", url, follow_redirects=True) as response:
            if response.status_code != 200:
                raise CatalogError(f"models.dev answered HTTP {response.status_code}")
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise CatalogError("the catalog is larger than expected; refusing to read it")
                chunks.append(chunk)
    except httpx.TimeoutException:
        raise CatalogError("models.dev did not answer in time") from None
    except httpx.HTTPError as exc:
        raise CatalogError(f"could not reach models.dev ({type(exc).__name__})") from None
    try:
        payload = json.loads(b"".join(chunks))
    except ValueError:
        raise CatalogError("models.dev did not return JSON") from None
    models = parse(payload)
    if not any(models.values()):
        raise CatalogError("models.dev returned no models for the providers we support")
    return CatalogData(fetched_at=0.0, models=models)  # the caller stamps the time
