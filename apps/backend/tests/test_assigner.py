"""The Auto assigner: requirements, presets, fallbacks, escalation, and honesty about what is
not known. Pure functions over catalog entries; the numbers below are test data, not claims
about any real model."""

from decimal import Decimal

import pytest

from app.catalog.assigner import assign
from app.catalog.profiles import Tiers
from app.catalog.requirements import load_requirements
from app.catalog.service import CatalogEntry

REQ = load_requirements()


def entry(
    connection: str,
    model: str,
    tiers: tuple[int, int, int, int] | None,  # reasoning, coding, ui, tool_use
    price: tuple[str, str] | None = ("1", "5"),
    *,
    context: int | None = 200_000,
    local: bool = False,
    tool_call: bool | None = True,
    deprecated: bool = False,
    access: str = "unknown",
    calls: int = 0,
    ok_calls: int = 0,
    latency: int | None = None,
    tpm: int | None = None,
) -> CatalogEntry:
    return CatalogEntry(
        connection_id=f"id-{connection}",
        connection_name=connection,
        provider_type="custom",
        model=model,
        name=model,
        local=local,
        context_window=context,
        max_output=None,
        input_per_mtok=Decimal(price[0]) if price else None,
        output_per_mtok=Decimal(price[1]) if price else None,
        tool_call=tool_call,
        reasoning=None,
        structured_output=None,
        deprecated=deprecated,
        tiers=Tiers(reasoning=tiers[0], coding=tiers[1], ui=tiers[2], tool_use=tiers[3])
        if tiers
        else None,
        edit_format="search_replace" if tiers else None,
        quirks=[],
        in_models_dev=price is not None,
        has_profile=tiers is not None,
        free=model.endswith(":free") or local,
        access=access,  # type: ignore[arg-type]
        calls=calls,
        ok_calls=ok_calls,
        median_latency_ms=latency,
        tpm_limit=tpm,
    )


# A user with three providers (cf. PRD §10.4): a frontier model, a cheaper strong coder, a
# cheap fast model, and a model that is good at UI.
TOP = entry("Anthropic", "top", (5, 5, 5, 5), ("15", "75"))
STRONG = entry("Anthropic", "strong", (4, 5, 4, 5), ("3", "15"))
FAST = entry("Anthropic", "fast", (3, 3, 3, 4), ("0.5", "2.5"))
DESIGN = entry("OpenRouter", "design", (4, 4, 5, 4), ("1.25", "10"))
CHEAP = entry("NVIDIA", "cheap", (3, 4, 1, 3), ("0.2", "0.8"))
ALL = [TOP, STRONG, FAST, DESIGN, CHEAP]


def one(persona: str, entries: list[CatalogEntry], preset: str = "balanced"):
    [proposal] = assign([persona], entries, preset, REQ)  # type: ignore[arg-type]
    return proposal


def model_of(proposal) -> str | None:
    return proposal.primary.model if proposal.primary else None


def test_balanced_spends_on_critical_roles_and_saves_on_the_rest() -> None:
    chosen = {p.persona_id: model_of(p) for p in assign(list(REQ.roles), ALL, "balanced", REQ)}

    assert chosen["pm"] == "top" and chosen["security"] == "top"  # strongest reasoning
    assert chosen["backend"] == "design"  # cheapest with coding >= 4 and tool use >= 4
    assert chosen["frontend"] == "design"
    assert chosen["designer"] == "design"  # the only one with UI >= 4 that is cheap enough
    assert (
        chosen["qa"] == "cheap"
    )  # cheapest with reasoning >= 3 and tool use >= 3 (3,_,_,3 qualifies)
    assert chosen["researcher"] == "cheap"  # cheapest with tool use >= 2
    assert chosen["devops"] == "cheap"
    assert chosen["code-reviewer"] == "design"  # not critical: cheapest meeting reasoning/coding 4
    assert chosen["data"] == "cheap"


def test_best_picks_the_strongest_model_for_every_role() -> None:
    chosen = {p.persona_id: model_of(p) for p in assign(list(REQ.roles), ALL, "best", REQ)}

    assert set(chosen.values()) == {"top"}


def test_cheapest_picks_the_lowest_cost_model_that_still_qualifies() -> None:
    chosen = {p.persona_id: model_of(p) for p in assign(list(REQ.roles), ALL, "cheapest", REQ)}

    assert chosen["pm"] == "top"  # nothing cheaper reaches reasoning 5
    assert chosen["backend"] == "design" and chosen["qa"] == "cheap"
    assert chosen["researcher"] == "cheap"


def test_private_uses_local_models_only_even_when_a_cloud_model_is_better() -> None:
    local = entry("Ollama", "local-coder", (3, 4, 1, 4), None, local=True)
    local_weak = entry("Ollama", "local-small", (2, 2, 1, 2), None, local=True)

    pm = one("pm", [TOP, local, local_weak], "private")
    backend = one("backend", [TOP, local, local_weak], "private")

    assert model_of(backend) == "local-coder" and backend.verified
    assert "local, no API cost" in backend.reason
    # Nothing local is good enough for PM: the best local model is used, and it says so.
    assert model_of(pm) == "local-coder" and pm.verified is False
    assert "unverified" in pm.reason
    assert all(f.model.startswith("local") for f in pm.fallbacks + backend.fallbacks)
    assert one("pm", [TOP, STRONG], "private").primary is None  # no local model at all


def test_a_model_without_a_profile_is_never_assumed_to_qualify() -> None:
    mystery = entry("Custom", "mystery", None, ("0.1", "0.1"))

    only = one("backend", [mystery])
    mixed = one("backend", [mystery, STRONG])

    assert model_of(only) == "mystery" and only.verified is False
    assert only.reason.startswith("unverified: none of your models is profiled to meet")
    assert "coding ≥4, tool use ≥4" in only.reason
    assert model_of(mixed) == "strong" and mixed.verified is True  # the proven one wins


def test_unknown_prices_are_sorted_after_known_ones_and_called_unknown() -> None:
    unpriced = entry("Custom", "unpriced", (4, 5, 4, 5), None)
    cheap = entry("Custom", "priced", (4, 5, 4, 5), ("9", "9"))

    chosen = one("backend", [unpriced, cheap], "cheapest")
    only = one("backend", [unpriced], "cheapest")

    assert model_of(chosen) == "priced"
    assert "price unknown" in only.reason and "$" not in only.reason


def test_models_that_cannot_do_the_job_are_excluded() -> None:
    no_tools = entry("A", "no-tools", (5, 5, 5, 5), ("0.1", "0.1"), tool_call=False)
    old = entry("A", "old", (5, 5, 5, 5), ("0.1", "0.1"), deprecated=True)
    short = entry("A", "short-context", (5, 5, 5, 5), ("0.1", "0.1"), context=32_000)
    blind = entry("A", "unknown-context", (5, 5, 5, 5), ("0.1", "0.1"), context=None)

    pm = one("pm", [no_tools, old, short, blind, TOP])
    backend = one("backend", [no_tools, old, STRONG])

    assert model_of(pm) == "top"  # PM needs >= 128k context, and an unknown window cannot prove it
    assert model_of(backend) == "strong"
    assert one("pm", [no_tools, old]).primary is None


def test_fallbacks_prefer_another_connection_and_stop_at_two() -> None:
    proposal = one("backend", ALL, "best")

    names = [(f.connection_name, f.model) for f in proposal.fallbacks]
    assert len(names) == 2 and len(set(names)) == 2
    assert names[0][0] != "Anthropic"  # a different provider comes first
    assert proposal.primary.model not in [f.model for f in proposal.fallbacks]
    assert one("backend", [STRONG]).fallbacks == []


def test_escalation_is_one_step_stronger_and_absent_when_already_the_best() -> None:
    cheap_backend = one("backend", ALL)  # balanced: the cheapest qualifier
    best = one("backend", ALL, "best")

    assert model_of(cheap_backend) == "design"
    assert cheap_backend.escalate.model == "top"  # the strongest model for coding and tool use
    assert best.escalate is None  # already the strongest
    # A model that is not stronger is never "escalation".
    twin = entry("Other", "twin", (4, 4, 5, 4), ("2", "2"))
    assert one("designer", [DESIGN, twin]).escalate is None


def test_every_reason_is_built_from_facts() -> None:
    backend = one("backend", ALL)
    pm = one("pm", ALL)

    assert backend.reason == (
        "cheapest model meeting coding ≥4, tool use ≥4: design on OpenRouter "
        "($1.25 in / $10 out per Mtok)"
    )
    assert pm.reason == (
        "strongest for reasoning and tool use among your models meeting reasoning ≥5, "
        "tool use ≥4, context ≥128k: top on Anthropic ($15 in / $75 out per Mtok)"
    )


def test_nothing_connected_or_nothing_defined_is_explained() -> None:
    none = one("backend", [])
    unknown_role = assign(["wizard"], ALL, "balanced", REQ)[0]

    assert none.primary is None and "add a connection" in none.reason
    assert unknown_role.primary is None and "no requirements" in unknown_role.reason


def test_the_same_inputs_always_give_the_same_answer() -> None:
    first = assign(list(REQ.roles), ALL, "balanced", REQ)
    second = assign(list(REQ.roles), list(reversed(ALL)), "balanced", REQ)

    assert [(p.persona_id, model_of(p), [f.model for f in p.fallbacks]) for p in first] == [
        (p.persona_id, model_of(p), [f.model for f in p.fallbacks]) for p in second
    ]


@pytest.mark.parametrize("persona", sorted(REQ.roles))
def test_every_persona_has_requirements_that_a_strong_model_meets(persona: str) -> None:
    assert one(persona, [TOP]).verified is True


# ---------- what the user's account can actually use (live run, PRD D69) ----------
# Auto picked `claude-fable-5` on a Token Harbor key with no paid plan for most of the team: the
# strongest profile, an unknown price, and never used on that account.


def test_a_model_the_provider_refused_is_never_picked() -> None:
    refused = entry("Harbor", "claude", (5, 5, 5, 5), None, access="refused")
    works = entry("Groq", "oss", (4, 4, 3, 4), ("0.15", "0.6"), access="works")

    for persona in ("pm", "backend", "researcher"):
        proposal = one(persona, [refused, works], "best")
        assert model_of(proposal) == "oss"
        assert all(p.model != "claude" for p in proposal.fallbacks)


def test_an_unknown_price_never_used_on_this_account_comes_after_models_known_to_work() -> None:
    untried = entry("Harbor", "claude", (5, 5, 5, 5), None)  # price unknown, never called
    works = entry("NVIDIA", "glm", (4, 4, 3, 4), None, access="works")
    free = entry("Harbor", "deepseek:free", (4, 4, 3, 4), None)

    for preset in ("balanced", "best", "cheapest"):
        proposal = one("pm", [untried, works, free], preset)
        assert model_of(proposal) in ("glm", "deepseek:free")
        assert "may need a paid plan" not in proposal.reason  # the pick itself is reachable
    # still a fallback, so it can be tried after the ones known to work
    assert "claude" in [p.model for p in one("pm", [untried, works]).fallbacks]
    # and still picked when it is all there is, saying so
    alone = one("pm", [untried])
    assert model_of(alone) == "claude" and "may need a paid plan" in alone.reason


def test_a_free_model_counts_as_costing_nothing() -> None:
    free = entry("Harbor", "deepseek:free", (3, 4, 1, 4), None)
    paid = entry("Groq", "oss", (3, 4, 1, 4), ("0.15", "0.6"), access="works")

    proposal = one("backend", [paid, free], "cheapest")

    assert model_of(proposal) == "deepseek:free" and "free" in proposal.reason


# ---------- measured limits, speed and failures (live runs, PRD D71) ----------
from app.catalog.measured import RoleLoad  # noqa: E402

LOADS = {"backend": RoleLoad(3000, 6000, True), "code-reviewer": RoleLoad(1300, 1500, True)}


def loaded(persona: str, entries: list[CatalogEntry], preset: str = "balanced"):
    [proposal] = assign([persona], entries, preset, REQ, LOADS)  # type: ignore[arg-type]
    return proposal


def test_a_model_whose_per_minute_limit_cannot_fit_the_role_is_not_its_first_choice() -> None:
    # Groq's free plan: 8,000 tokens a minute. Two builder requests of up to 6,000 do not fit.
    groq = entry("Groq", "oss", (4, 4, 3, 4), ("0.15", "0.6"), access="works", tpm=8000)
    free = entry("Harbor", "deepseek:free", (3, 4, 1, 4), None, access="works")

    builder = loaded("backend", [groq, free], "best")
    reviewer = loaded("code-reviewer", [groq, free], "best")

    assert model_of(builder) == "deepseek:free" and "oss" in [p.model for p in builder.fallbacks]
    assert model_of(reviewer) == "oss"  # small requests fit, so the stronger model is used
    assert "8,000 tokens a minute" in reviewer.reason


def test_a_model_that_is_very_slow_or_fails_often_here_comes_after_one_that_works() -> None:
    slow = entry("NVIDIA", "glm", (4, 5, 3, 5), None, access="works", calls=4, ok_calls=4,
                 latency=200_000)  # fmt: skip
    flaky = entry("NVIDIA", "kimi", (5, 5, 4, 5), None, access="works", calls=6, ok_calls=2)
    steady = entry("Harbor", "deepseek:free", (3, 4, 1, 4), None, access="works", calls=9,
                   ok_calls=9, latency=4000)  # fmt: skip

    proposal = loaded("backend", [slow, flaky, steady], "best")

    assert model_of(proposal) == "deepseek:free" and "about 4 s" in proposal.reason


def test_equally_good_free_models_are_spread_over_connections() -> None:
    a = entry("Harbor", "deepseek:free", (3, 4, 1, 4), None, access="works")
    b = entry("NVIDIA", "glm:free", (3, 4, 1, 4), None, access="works")

    picks = assign(["backend", "devops", "frontend"], [a, b], "cheapest", REQ, LOADS)  # type: ignore[arg-type]

    assert {p.primary.connection_name for p in picks if p.primary} == {"Harbor", "NVIDIA"}


def test_a_well_rated_model_that_fails_here_loses_to_one_that_works_here() -> None:
    # Live (2026-11-21): GLM met the builder rating but answered 2 of 7 calls, in ~212 s.
    glm = entry("NVIDIA", "glm", (4, 5, 3, 5), None, access="works", calls=7, ok_calls=2,
                latency=212_000)  # fmt: skip
    unrated = entry("Harbor", "deepseek:free", None, None, access="works", calls=33, ok_calls=33,
                    latency=3600)  # fmt: skip

    proposal = loaded("backend", [glm, unrated])

    assert model_of(proposal) == "deepseek:free"
    assert "slow, failing or limited here" in proposal.reason
    assert "glm" in [p.model for p in proposal.fallbacks]  # still a fallback


@pytest.mark.parametrize(
    "model",
    ["openai/gpt-oss-safeguard-20b", "nvidia/nemotron-3.5-content-safety", "nvidia/nv-embedqa-1b",
     "whisper-large-v3", "nvidia/llama-3.1-nemoguard-8b", "jina-reranker-v2", "omni-moderation"],
)  # fmt: skip
def test_models_made_for_another_job_are_never_given_a_role(model: str) -> None:
    special = entry("Groq", model, (5, 5, 5, 5), ("0", "0"), access="works")
    chat = entry("Harbor", "deepseek:free", (3, 4, 1, 4), None, access="works")

    proposal = one("backend", [special, chat], "best")

    assert model_of(proposal) == "deepseek:free" and model not in [
        p.model for p in proposal.fallbacks
    ]
