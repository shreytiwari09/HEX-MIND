"""The provider types a connection can be (PRD §10.1).

A preset gives each type its default base URL and tells the code which adapter speaks to it.
Most providers speak the OpenAI chat-completions format; Anthropic has its own, and Ollama has
a native API. A `custom` connection is any OpenAI-compatible endpoint the user names.

The base URLs are the providers' documented public endpoints; the connection test is what
proves one works for a given key, and a user can always override a URL.
"""

from dataclasses import dataclass
from typing import Literal

from app.providers.openai_compat import GEMINI_BASE_URL, GROQ_BASE_URL

AdapterKind = Literal["openai_compat", "anthropic", "ollama"]


@dataclass(frozen=True)
class ProviderPreset:
    type: str
    label: str
    adapter: AdapterKind
    base_url: str | None  # None: the user must give one
    requires_key: bool = True
    # Google's OpenAI-compatible endpoint needs thought signatures replayed on tool calls.
    thought_signatures: bool = False
    local: bool = False  # runs on the user's machine: nothing leaves it (privacy mode "local")


_PRESET_LIST = [
    ProviderPreset("openrouter", "OpenRouter", "openai_compat", "https://openrouter.ai/api/v1"),
    ProviderPreset("anthropic", "Anthropic", "anthropic", "https://api.anthropic.com"),
    ProviderPreset("openai", "OpenAI", "openai_compat", "https://api.openai.com/v1"),
    ProviderPreset(
        "google", "Google Gemini", "openai_compat", GEMINI_BASE_URL, thought_signatures=True
    ),
    ProviderPreset("nvidia", "NVIDIA", "openai_compat", "https://integrate.api.nvidia.com/v1"),
    ProviderPreset("deepseek", "DeepSeek", "openai_compat", "https://api.deepseek.com/v1"),
    ProviderPreset("glm", "Zhipu GLM", "openai_compat", "https://open.bigmodel.cn/api/paas/v4"),
    ProviderPreset("moonshot", "Moonshot", "openai_compat", "https://api.moonshot.ai/v1"),
    ProviderPreset("groq", "Groq", "openai_compat", GROQ_BASE_URL),
    ProviderPreset("mistral", "Mistral", "openai_compat", "https://api.mistral.ai/v1"),
    ProviderPreset("xai", "xAI", "openai_compat", "https://api.x.ai/v1"),
    ProviderPreset(
        "ollama",
        "Ollama (local)",
        "ollama",
        "http://127.0.0.1:11434",
        requires_key=False,
        local=True,
    ),
    ProviderPreset(
        "lmstudio",
        "LM Studio (local)",
        "openai_compat",
        "http://127.0.0.1:1234/v1",
        requires_key=False,
        local=True,
    ),
    ProviderPreset("custom", "Custom (OpenAI-compatible URL)", "openai_compat", None),
]

PRESETS: dict[str, ProviderPreset] = {p.type: p for p in _PRESET_LIST}


def preset_for(provider_type: str) -> ProviderPreset:
    try:
        return PRESETS[provider_type]
    except KeyError:
        raise ValueError(f"unknown provider type {provider_type!r}") from None
