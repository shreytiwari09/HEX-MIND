import os
from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/backend/app/config.py -> repository root
ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"

REPO_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_DATA_DIR = (
    Path(os.environ["LOCALAPPDATA"]) / "hexmind"
    if os.name == "nt" and "LOCALAPPDATA" in os.environ
    else Path.home() / ".local" / "share" / "hexmind"
)


INSTALLED_APP_ORIGIN = "app://hexmind"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HEXMIND_", env_file=ROOT_ENV_FILE, extra="ignore")

    api_token: str = Field(min_length=16)
    host: str = "127.0.0.1"
    port: int = 8765
    cors_origins: list[str] = ["http://localhost:5173"]

    @field_validator("cors_origins")
    @classmethod
    def _installed_app_origin(cls, value: list[str]) -> list[str]:
        """The installed desktop app serves its screens from app://hexmind (PRD D80); it is
        always allowed, so an older .env listing only the dev server keeps working."""
        return value if INSTALLED_APP_ORIGIN in value else [*value, INSTALLED_APP_ORIGIN]

    database_url: str = "postgresql+asyncpg://hexmind:hexmind@127.0.0.1:5433/hexmind"

    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5-coder:7b"
    # Ollama's default context window is small; prompts carry project context.
    ollama_num_ctx: int = 8192
    # Local generation of a long answer can take minutes on modest hardware.
    ollama_timeout_s: float = 600

    # Hosted providers (OpenAI-compatible APIs). A provider without a key is not used.
    groq_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("HEXMIND_GROQ_API_KEY", "GROQ_API_KEY")
    )
    groq_model: str = "openai/gpt-oss-120b"
    gemini_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("HEXMIND_GEMINI_API_KEY", "GEMINI_API_KEY")
    )
    gemini_model: str = "gemini-3.5-flash"
    # Web search for Advanced research (D62). The key can also be saved in the OS key store,
    # which is tried first.
    tavily_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("HEXMIND_TAVILY_API_KEY", "TAVILY_API_KEY", "TAVILY_KEY"),
    )

    # Provider selection policy: tried in this order, skipping unconfigured or unavailable
    # providers. Optional per-complexity orders ({"low": ["ollama", ...]}) override it.
    provider_order: list[str] = ["groq", "gemini", "ollama"]
    provider_order_by_complexity: dict[str, list[str]] = {}
    # A call's purpose can have its own order. Research reads whole web pages, which are too big
    # for Groq's free per-minute token limit (measured live on 2026-11-21: Groq rejected or
    # rate-limited 4 calls and took 228 s for 19 calls, where Gemini took 37 s for 4), so
    # Gemini goes first; Groq stays a fallback. Providers without a key are skipped.
    provider_order_by_purpose: dict[str, list[str]] = {"research": ["gemini", "groq", "ollama"]}
    # How long a provider is skipped after quota exhaustion (unless it sends Retry-After).
    quota_cooldown_s: float = 300
    # Refresh the models.dev catalog in the background at startup (a plain public GET; no user
    # data is sent). Off, the cached copy is used and the Refresh button still works.
    catalog_auto_refresh: bool = True
    # Where API keys are kept: the OS keychain, or (tests, throwaway sessions) this process only.
    key_store: Literal["keyring", "memory"] = "keyring"
    # Apply also writes the team's working notes (`.hex/mission/`: plan, handoffs, validator
    # reports) into the user's project. Off: they stay with the mission (D83). The run contract
    # (`.hex/project.json`) is always applied.
    apply_mission_files: bool = False
    # Agents use native (structured) tool calls; False falls back to CrewAI's text ReAct.
    native_tool_calling: bool = True

    # Approximate token budget for the context bundle sent with chat/router prompts.
    context_budget_tokens: int = 5000
    # Below this Router confidence, Auto mode asks for clarification instead of editing.
    router_min_confidence: float = 0.6

    # Files larger than this are not opened in the editor.
    max_editor_file_bytes: int = 2 * 1024 * 1024

    # App-owned state outside any workspace: run worktrees, vector store, CrewAI storage.
    data_dir: Path = DEFAULT_DATA_DIR

    # Worker swarm.
    worker_concurrency: int = 2
    # Workers renew their task lease every quarter lease while they work on it.
    task_lease_s: int = 600
    agent_max_iterations: int = 15
    review_max_rounds: int = 2
    # When every provider fails for the Reviewer, retry the review after these pauses (seconds)
    # before giving up: an outage is not a verdict.
    review_retry_delays_s: list[float] = [20.0, 60.0]

    # Sandbox for checks. Only these images may be used, whatever a project profile says.
    sandbox_images: list[str] = ["node:22-alpine", "python:3.11-slim"]
    # Start a completed mission's app (when it has a start command and port) and post the link
    # in the mission's chat (D71).
    app_autorun_after_mission: bool = True
    sandbox_timeout_s: int = 120

    # CrewAI crews served over A2A (python -m app.a2a). The backend starts the service itself
    # unless it is already running or autostart is off (e.g. a separate Cloud Run service).
    crew_service_url: str = "http://127.0.0.1:8766"
    crew_service_autostart: bool = True
    a2a_timeout_s: float = 1800
    # Messaging coordination (PRD §9.8): how often a request that timed out is sent again with the
    # same exchange id (the crew service answers a repeat from the work already done or in flight).
    messaging_resends: int = 2

    # Response cache for replays (PRD §15.2): off, readwrite (use and fill), replay_only (never
    # live).
    response_cache: Literal["off", "readwrite", "replay_only"] = "off"

    # OpenTelemetry: OTLP/HTTP traces endpoint, e.g. http://127.0.0.1:4318/v1/traces.
    otlp_endpoint: str | None = None
    # Keep finished spans in Postgres so traces render offline (sanitised: no prompts or secrets).
    store_traces: bool = True

    # RAG store (ChromaDB). Embeddings come from the local Ollama.
    memory_enabled: bool = True
    embedding_model: str = "nomic-embed-text"
    standards_dir: Path = REPO_ROOT / "docs" / "standards"

    @field_validator("host")
    @classmethod
    def host_must_be_loopback(cls, value: str) -> str:
        if value != "localhost" and not ip_address(value).is_loopback:
            raise ValueError("backend must bind to a loopback address")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # api_token comes from the environment
