"""Settings for Advanced research (PRD D62): the search key. It goes straight to the OS key store
and is never returned; every response says only whether a key is set."""

from fastapi import APIRouter, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, SecretStr, field_validator

from app.api.deps import ServicesDep
from app.providers.secrets import KeyStoreError
from app.research.search import SEARCH_KEY_REF, SearchError, TavilySearch, search_key

router = APIRouter(prefix="/research", tags=["research"])


class SearchKeyIn(BaseModel):
    api_key: SecretStr

    @field_validator("api_key")
    @classmethod
    def _not_blank(cls, value: SecretStr) -> SecretStr:
        text = value.get_secret_value().strip()
        if not text:
            raise ValueError("the key is empty")
        return SecretStr(text)


class SearchStatus(BaseModel):
    provider: str = "tavily"
    configured: bool
    source: str | None = None  # "keychain", "env" (the .env file) or None


class SearchTest(BaseModel):
    ok: bool
    error: str | None
    credits: float | None


def _store_failed(exc: KeyStoreError) -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))


async def _status(services: ServicesDep) -> SearchStatus:
    try:
        key, source = await search_key(services.keystore, services.settings.tavily_api_key)
    except SearchError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from None
    return SearchStatus(configured=key is not None, source=source)


@router.get("/search", response_model=SearchStatus)
async def search_status(services: ServicesDep) -> SearchStatus:
    return await _status(services)


@router.put("/search/key", response_model=SearchStatus)
async def set_search_key(body: SearchKeyIn, services: ServicesDep) -> SearchStatus:
    if services.keystore is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "no key store is available")
    try:
        await run_in_threadpool(
            services.keystore.set, SEARCH_KEY_REF, body.api_key.get_secret_value()
        )
    except KeyStoreError as exc:
        raise _store_failed(exc) from None
    return await _status(services)


@router.delete("/search/key", response_model=SearchStatus)
async def delete_search_key(services: ServicesDep) -> SearchStatus:
    if services.keystore is not None:
        try:
            await run_in_threadpool(services.keystore.delete, SEARCH_KEY_REF)
        except KeyStoreError as exc:
            raise _store_failed(exc) from None
    return await _status(services)  # a key in .env, if any, is not ours to remove


@router.post("/search/test", response_model=SearchTest)
async def test_search(services: ServicesDep) -> SearchTest:
    """One real search for a single result: it costs Tavily's credits (usually one)."""
    try:
        result = await TavilySearch(
            services.keystore,
            client=services.research_http,
            env_key=services.settings.tavily_api_key,
        ).search("hello world", max_results=1)
    except SearchError as exc:
        return SearchTest(ok=False, error=str(exc), credits=None)
    return SearchTest(ok=True, error=None, credits=result.credits)
