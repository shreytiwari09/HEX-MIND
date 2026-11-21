"""The Auto assigner: pick a model for each persona from what the user can reach (PRD §10.4).

For each persona it takes the models that meet the role's minimums (`role_requirements.yaml`)
and chooses by the active preset:

- **balanced:** the strongest model for critical roles (PM, Security), the cheapest one that
  qualifies for the rest.
- **best:** the strongest model for every role.
- **cheapest:** the cheapest model that qualifies for every role.
- **private:** only local models (nothing leaves the machine), chosen like balanced.

Alongside the primary it returns up to two fallbacks (preferring a different connection, so one
provider's outage does not stop the persona) and an escalation model one step stronger, used when
a feature keeps failing. Every choice comes with a one-line reason built only from facts we have.

Quality tiers are curated estimates (see model_profiles.yaml). A model without a profile cannot be
shown to meet a requirement, so it is chosen only as a last resort, and the reason says
"unverified". Nothing is assumed about unknown prices either: such a model is sorted after priced
ones when saving money.

What the user's account can use comes first (PRD D69): a model the provider refused (no plan, bad
key) is never picked, and a model with no known price that has never answered on this account
(an aggregator listing paid models a free account cannot call) comes after every model that is
free, has a known price, or has already worked. A free model (`:free`, local) costs nothing.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from app.catalog.requirements import Requirements, RoleRequirement
from app.catalog.service import CatalogEntry

Preset = Literal["balanced", "best", "cheapest", "private"]
PRESETS: tuple[Preset, ...] = ("balanced", "best", "cheapest", "private")
MAX_FALLBACKS = 2
_CAPABILITY_NAMES = {
    "reasoning": "reasoning",
    "coding": "coding",
    "ui": "UI",
    "tool_use": "tool use",
}
_INF = Decimal("Infinity")


@dataclass(frozen=True)
class Pick:
    connection_id: str
    connection_name: str
    model: str


@dataclass
class Proposal:
    persona_id: str
    primary: Pick | None
    fallbacks: list[Pick] = field(default_factory=list)
    escalate: Pick | None = None
    reason: str = ""
    # False when no connected model is profiled to meet the role's minimums.
    verified: bool = True


def _pick(entry: CatalogEntry) -> Pick:
    return Pick(entry.connection_id, entry.connection_name, entry.model)


def _quality(entry: CatalogEntry, req: RoleRequirement) -> int:
    if entry.tiers is None:
        return 0
    focus = sum(getattr(entry.tiers, name) for name in req.focus)
    overall = sum(getattr(entry.tiers, n) for n in ("reasoning", "coding", "ui", "tool_use"))
    return focus * 10 + overall  # the focus decides; the rest breaks ties


def _reach(entry: CatalogEntry) -> int:
    """0 when the account can be expected to use the model, 1 when nothing shows it can: no known
    price and never answered here."""
    known_price = entry.input_per_mtok is not None and entry.output_per_mtok is not None
    return 0 if entry.free or entry.local or entry.access == "works" or known_price else 1


def _cost(entry: CatalogEntry) -> Decimal | None:
    """USD per million tokens, weighting input 3:1 over output (typical for agent work)."""
    if entry.local or entry.free:
        return Decimal(0)
    if entry.input_per_mtok is None or entry.output_per_mtok is None:
        return None
    return (3 * entry.input_per_mtok + entry.output_per_mtok) / 4


def _meets(entry: CatalogEntry, req: RoleRequirement) -> bool:
    if entry.tiers is None:
        return False
    if any(getattr(entry.tiers, name) < floor for name, floor in req.min.items()):
        return False
    if req.min_context and (entry.context_window is None or entry.context_window < req.min_context):
        return False
    return True


def _by_quality(req: RoleRequirement):
    return lambda e: (_reach(e), -_quality(e, req), _cost(e) if _cost(e) is not None else _INF)


def _by_cost(req: RoleRequirement):
    return lambda e: (_reach(e), _cost(e) if _cost(e) is not None else _INF, -_quality(e, req))


def _money(value: Decimal) -> str:
    text = f"{value:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _price(entry: CatalogEntry) -> str:
    if entry.local:
        return "local, no API cost"
    if entry.free:
        return "free"
    if entry.input_per_mtok is None or entry.output_per_mtok is None:
        return "price unknown"
    return f"${_money(entry.input_per_mtok)} in / ${_money(entry.output_per_mtok)} out per Mtok"


def _need(req: RoleRequirement) -> str:
    parts = [f"{_CAPABILITY_NAMES[name]} ≥{floor}" for name, floor in req.min.items()]
    if req.min_context:
        parts.append(f"context ≥{req.min_context // 1000}k")
    return ", ".join(parts) or "no minimum"


def _focus(req: RoleRequirement) -> str:
    return " and ".join(_CAPABILITY_NAMES[name] for name in req.focus)


def assign(
    persona_ids: list[str],
    entries: list[CatalogEntry],
    preset: Preset,
    requirements: Requirements,
) -> list[Proposal]:
    pool = [
        e
        for e in entries
        if not e.deprecated
        and e.tool_call is not False
        and e.access != "refused"
        and (preset != "private" or e.local)
    ]
    return [_assign_one(pid, pool, preset, requirements) for pid in persona_ids]


def _assign_one(
    persona_id: str, pool: list[CatalogEntry], preset: Preset, requirements: Requirements
) -> Proposal:
    req = requirements.roles.get(persona_id)
    if req is None:
        return Proposal(persona_id, None, reason="no requirements are defined for this persona")
    if not pool:
        return Proposal(
            persona_id,
            None,
            reason="no model can be used: add a connection, test it, and (for the Private "
            "preset) include a local model",
        )

    strict = [e for e in pool if _meets(e, req)]
    # Models the account is known to reach win over ones it may not be able to call at all, even
    # when only the latter are profiled to qualify.
    unreached_only = [e for e in strict if _reach(e)]
    if any(_reach(e) == 0 for e in pool):
        strict = [e for e in strict if _reach(e) == 0]
    quality_first = preset == "best" or (preset in ("balanced", "private") and req.critical)
    key = _by_quality(req) if quality_first else _by_cost(req)

    if strict:
        ranked = sorted(strict, key=key)
        primary = ranked[0]
        how = (
            f"strongest for {_focus(req)} among your models meeting {_need(req)}"
            if quality_first
            else f"cheapest model meeting {_need(req)}"
        )
        verified = True
    else:
        # Nothing is profiled to meet the minimums. Take the best available and say so.
        ranked = sorted(pool, key=_by_quality(req))
        primary = ranked[0]
        how = (
            f"unverified: none of the models your account is known to reach meets {_need(req)} "
            "(stronger ones are not yet used on your account); best available"
            if unreached_only
            else f"unverified: none of your models is profiled to meet {_need(req)}; best available"
        )
        verified = False

    others = [e for e in ranked if e is not primary]
    # A different connection first: one provider's outage should not stop the persona.
    others.sort(key=lambda e: e.connection_id == primary.connection_id)
    fallbacks = [_pick(e) for e in others[:MAX_FALLBACKS]]

    escalate: Pick | None = None
    if verified:
        stronger = [
            e for e in strict if e is not primary and _quality(e, req) > _quality(primary, req)
        ]
        if stronger:
            escalate = _pick(sorted(stronger, key=_by_quality(req))[0])

    reason = f"{how}: {primary.model} on {primary.connection_name} ({_price(primary)})"
    if _reach(primary):
        reason += "; not yet used on your account, so it may need a paid plan"
    return Proposal(persona_id, _pick(primary), fallbacks, escalate, reason, verified)
