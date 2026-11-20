"""Builds the ProviderRouter from settings. Shared by the backend and the crew A2A service, so
both route, retry, fall back and log model calls identically."""

from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.providers.cache import ResponseCache
from app.providers.ollama import OllamaAdapter
from app.providers.openai_compat import GEMINI_BASE_URL, GROQ_BASE_URL, OpenAICompatAdapter
from app.providers.pricing import Pricing
from app.providers.routed import RouteExecutor
from app.providers.router import ProviderRouter
from app.providers.secrets import KeyStore

if TYPE_CHECKING:
    from app.catalog.service import CatalogService


def build_providers(
    settings: Settings,
    sessionmaker: async_sessionmaker[AsyncSession],
    keystore: KeyStore | None = None,
    catalog: "CatalogService | None" = None,
) -> tuple[ProviderRouter, list[Any]]:
    """Returns the router and its adapters (which the caller closes on shutdown). With a key
    store, calls that carry a persona route are served from the user's connections."""
    ollama = OllamaAdapter(
        settings.ollama_url,
        settings.ollama_model,
        num_ctx=settings.ollama_num_ctx,
        timeout_s=settings.ollama_timeout_s,
    )
    pricing = Pricing.load()
    if catalog is not None:
        pricing.fallback = catalog.price
    hosted = [
        OpenAICompatAdapter(
            name="groq",
            base_url=GROQ_BASE_URL,
            api_key=settings.groq_api_key.get_secret_value() if settings.groq_api_key else None,
            model=settings.groq_model,
            pricing=pricing,
        ),
        OpenAICompatAdapter(
            name="gemini",
            base_url=GEMINI_BASE_URL,
            api_key=settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None,
            model=settings.gemini_model,
            pricing=pricing,
            requires_thought_signatures=True,
        ),
    ]
    adapters = [ollama, *hosted]
    router = ProviderRouter(
        adapters,
        sessionmaker,
        order=settings.provider_order,
        order_by_complexity=settings.provider_order_by_complexity,
        order_by_purpose=settings.provider_order_by_purpose,
        quota_cooldown_s=settings.quota_cooldown_s,
    )
    router.cache = ResponseCache(sessionmaker, settings.response_cache)
    if keystore is not None:
        executor = RouteExecutor(
            sessionmaker,
            keystore,
            pricing,
            ollama_num_ctx=settings.ollama_num_ctx,
            ollama_timeout_s=settings.ollama_timeout_s,
        )
        router.executor = executor
        adapters.append(executor)  # closed with the others
    return router, adapters
