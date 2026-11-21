"""What this account has measured about each model and each role, from its own call log (D71).

Nothing here is guessed: speed and success come from `llm_calls`; a model's per-minute and per-day
token limits come from the provider's own refusal text (Groq: "(TPM): Limit 8000"), the only
place they are stated without a separate call. A model's calls through the built-in `.env`
providers count for connections of the same provider type, because the limits belong to the
account and the model, not to how the app reached them.
"""

import re
import statistics
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Connection, LLMCall

WINDOW = 3000  # the latest calls looked at
_TPM = re.compile(r"\(TPM\): Limit (\d+)|tokens per minute[^0-9]{0,40}Limit (\d+)", re.I)
_TPD = re.compile(r"\(TPD\): Limit (\d+)|tokens per day[^0-9]{0,40}Limit (\d+)", re.I)

# Before any role has run, its load is taken from the first live missions (2026-11-21, D71):
# typical and largest input tokens of one request.
DEFAULT_LOADS: dict[str, tuple[int, int]] = {
    "pm": (3400, 6000),
    "backend": (3000, 6000),
    "frontend": (3000, 6000),
    "devops": (2700, 5000),
    "designer": (3000, 6000),
    "data": (3000, 6000),
    "qa": (2500, 4000),
    "code-reviewer": (1500, 3000),
    "security": (1500, 3000),
    "researcher": (4600, 11000),
}


@dataclass(frozen=True)
class ModelStats:
    calls: int
    ok: int
    median_latency_ms: int | None
    tpm_limit: int | None
    tpd_limit: int | None

    @property
    def success_rate(self) -> float | None:
        return self.ok / self.calls if self.calls else None


@dataclass(frozen=True)
class RoleLoad:
    typical: int  # median input tokens of one request
    peak: int  # the largest seen
    measured: bool  # False: the defaults above


def _limit(pattern: re.Pattern[str], text: str | None) -> int | None:
    match = pattern.search(text or "")
    if not match:
        return None
    return int(next(g for g in match.groups() if g))


async def model_stats(session: AsyncSession) -> dict[tuple[str, str], ModelStats]:
    """(provider type or built-in provider name, model) -> what was measured."""
    rows = await session.execute(
        select(
            LLMCall.provider,
            Connection.provider_type,
            LLMCall.model,
            LLMCall.error,
            LLMCall.latency_ms,
        )
        .outerjoin(Connection, Connection.id == LLMCall.connection_id)
        .where(LLMCall.replayed.is_(False))
        .order_by(LLMCall.created_at.desc())
        .limit(WINDOW)
    )
    grouped: dict[tuple[str, str], list[tuple[str | None, int]]] = {}
    for provider, provider_type, model, error, latency in rows:
        kind = provider_type or provider
        grouped.setdefault((kind, model), []).append((error, latency))
    out: dict[tuple[str, str], ModelStats] = {}
    for key, calls in grouped.items():
        ok_latencies = [latency for error, latency in calls if error is None]
        tpm = next((v for e, _ in calls if (v := _limit(_TPM, e))), None)
        tpd = next((v for e, _ in calls if (v := _limit(_TPD, e))), None)
        out[key] = ModelStats(
            calls=len(calls),
            ok=len(ok_latencies),
            median_latency_ms=int(statistics.median(ok_latencies)) if ok_latencies else None,
            tpm_limit=tpm,
            tpd_limit=tpd,
        )
    return out


async def role_loads(session: AsyncSession) -> dict[str, RoleLoad]:
    """persona -> its typical and largest request, measured when it has run, else a default."""
    rows = await session.execute(
        select(LLMCall.persona_id, LLMCall.input_tokens)
        .where(LLMCall.persona_id.is_not(None), LLMCall.input_tokens.is_not(None))
        .order_by(LLMCall.created_at.desc())
        .limit(WINDOW)
    )
    sizes: dict[str, list[int]] = {}
    for persona, tokens in rows:
        sizes.setdefault(persona, []).append(tokens)
    loads = {
        persona: RoleLoad(typical, peak, measured=False)
        for persona, (typical, peak) in DEFAULT_LOADS.items()
    }
    for persona, values in sizes.items():
        if len(values) >= 3:  # a couple of calls say little
            loads[persona] = RoleLoad(int(statistics.median(values)), max(values), measured=True)
    return loads
