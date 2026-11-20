"""Validators: independent checks at the end of a milestone (PRD §8.5, §9.5).

A validator is read-only and returns a `ValidatorReport`. Facts come from the sandbox and git,
not from the model's say-so: the scrutiny validator runs the project's test, typecheck and lint
in the sandbox and has one review subagent per feature; the security validator scans the added
lines for secrets deterministically and asks an ADK reviewer to look at the diff.

A validator that cannot do its job (no provider answered, no valid verdict) reports `needs_user`.
It never reports `pass` for work it did not check.
"""

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from fastapi.concurrency import run_in_threadpool
from google.adk.agents import LlmAgent

from app.agents import roles
from app.agents.adk_llm import HexAdkLlm
from app.agents.persona import get_persona
from app.agents.variants import Variant, apply
from app.context.redact import find_secrets, is_secret_file
from app.missions.models import CommandResult, Finding, ValidatorReport
from app.orchestration.adk import model_error_fallback, run_adk, schema_guard
from app.orchestration.services import Services
from app.providers.assignments import route_for
from app.providers.router import CallContext
from app.sandbox.runner import CheckOutcome, accepted, check_summary
from app.telemetry.hub import TelemetryHub
from app.workspace import git

MAX_DIFF_CHARS = 12_000
OUTPUT_IN_REPORT = 1500
STANDARD_CHECKS = ("test", "typecheck", "lint")
ACCEPTANCE_DIR = "tests/acceptance"
_CONTRACT_ID = re.compile(r"VC-\d+(?:\.\d+)*")
DEPENDENCY_FILES = frozenset(
    {
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "requirements.txt",
        "pyproject.toml",
        "uv.lock",
        "Pipfile",
        "go.mod",
        "Cargo.toml",
        "Gemfile",
        "composer.json",
    }
)


@dataclass(frozen=True)
class FeatureSnap:
    key: str
    title: str
    persona: str
    expected_behavior: list[str]
    commit: str | None  # the feature's checkpoint; None for a skipped feature


@dataclass
class ValidationContext:
    services: Services
    mission_id: object
    run_id: object
    worktree: Path
    telemetry: TelemetryHub
    # The sandbox: run a named check, and read the project's check commands as they are now.
    run_check: Callable[[str], Awaitable[CheckOutcome]]
    load_checks: Callable[[], Awaitable[dict[str, str]]]
    # This milestone's validation-contract criteria, as stored on the mission.
    criteria: list[dict] = field(default_factory=list)  # type: ignore[type-arg]
    acceptance_ready: bool = False
    # The prompt variant the mission runs under: applied to the persona a reviewer is built from,
    # and recorded on its model calls.
    variant: Variant | None = None


def _blocked(errors: list[str]) -> roles.ReviewResult:
    return roles.ReviewResult(
        verdict="blocked", summary="The reviewer did not produce a valid verdict."
    )


async def _ask(
    vc: ValidationContext, *, agent: str, persona_id: str, prompt: str
) -> tuple[roles.ReviewResult, bool]:
    """One ADK review: (verdict, available). `available` is False when no provider produced a
    valid verdict, which a validator must report as needs_user, never as a pass."""
    async with vc.services.sessionmaker() as session:
        route = await route_for(session, persona_id)
    llm = HexAdkLlm(
        router=vc.services.providers,
        ctx=CallContext(
            run_id=vc.run_id,  # type: ignore[arg-type]
            agent_id=agent,
            route=route,
            persona_id=persona_id,
            variant_id=vc.variant.id if vc.variant else None,
        ),
        purpose="reviewer",
        max_tokens=2048,
    )
    name = re.sub(r"\W", "_", agent)
    reviewer = LlmAgent(
        name=name,
        description=f"{persona_id} validator review ({agent}).",
        model=llm,
        instruction=lambda ctx: prompt,
        include_contents="none",
        output_schema=roles.ReviewResult,
        output_key="review",
        after_model_callback=schema_guard(roles.ReviewResult, llm, key="review", fallback=_blocked),
        on_model_error_callback=model_error_fallback(
            roles.ReviewResult, key="review", fallback=_blocked
        ),
    )
    state, _ = await run_adk(
        vc.telemetry.instrument(reviewer, parent="validator"), message=f"Review: {agent}"
    )
    result = roles.ReviewResult.model_validate(state["review"])
    available = state.get("review_schema_status") != "fallback" and result.verdict != "blocked"
    return result, available


def _findings_from(review: roles.ReviewResult, feature_id: str | None) -> list[Finding]:
    """The reviewer's findings, plus a blocking one when it asked for changes without citing any
    (so a request for changes can never be lost)."""
    findings = [
        Finding(
            feature_id=feature_id,
            file=f.file,
            line=f.line,
            severity=f.severity,
            message=f.message,
        )
        for f in review.findings
    ]
    if review.verdict == "changes_requested" and not any(
        f.severity in ("major", "critical") for f in findings
    ):
        findings.append(
            Finding(
                feature_id=feature_id,
                severity="major",
                message=review.summary or "The reviewer requested changes.",
            )
        )
    return findings


def _verdict(findings: list[Finding], unavailable: bool) -> str:
    if any(f.severity in ("major", "critical") for f in findings):
        return "fail"
    return "needs_user" if unavailable else "pass"


def _truncate(diff: str) -> str:
    if len(diff) <= MAX_DIFF_CHARS:
        return diff
    return diff[:MAX_DIFF_CHARS] + "\n… (diff truncated)"


# ---------- scrutiny ----------


async def run_scrutiny(
    vc: ValidationContext, milestone_key: str, features: list[FeatureSnap]
) -> ValidatorReport:
    """Test, typecheck and lint in the sandbox, plus one review per feature."""
    findings: list[Finding] = []
    commands: list[CommandResult] = []
    summaries: list[str] = []
    checks = await vc.load_checks()

    if "test" not in checks:
        findings.append(
            Finding(
                severity="major",
                message="The project defines no `test` check, so nothing shows the milestone "
                "works.",
            )
        )
    for name in STANDARD_CHECKS:
        if name not in checks:
            continue
        outcome = await vc.run_check(name)
        commands.append(
            CommandResult(
                command=checks[name],
                exit_code=outcome.exit_code if outcome.exit_code is not None else -1,
                duration_s=outcome.duration_ms / 1000,
                summary=outcome.output_tail[-OUTPUT_IN_REPORT:],
            )
        )
        summaries.append(check_summary(outcome).splitlines()[0])
        passed = accepted(outcome) if name == "test" else outcome.passed
        if not passed:
            findings.append(
                Finding(
                    severity="critical" if name in ("test", "typecheck") else "major",
                    message=f"The `{name}` check failed"
                    + (" (it ran no tests)." if outcome.passed else "."),
                    evidence=check_summary(outcome),
                )
            )

    reviewed = [f for f in features if f.commit]
    unavailable = False
    results = await asyncio.gather(
        *(_review_feature(vc, f, "; ".join(summaries) or "no checks ran") for f in reviewed)
    )
    for feature, (review, available) in zip(reviewed, results, strict=True):
        findings.extend(_findings_from(review, feature.key))
        unavailable = unavailable or not available
        if not available:
            findings.append(
                Finding(
                    feature_id=feature.key,
                    severity="info",
                    message="The reviewer for this feature was unavailable: it was not reviewed.",
                )
            )
    return ValidatorReport(
        validator="code-reviewer",
        milestone_id=milestone_key,
        verdict=_verdict(findings, unavailable),  # type: ignore[arg-type]
        findings=findings,
        commands=commands,
    )


async def _review_feature(
    vc: ValidationContext, feature: FeatureSnap, check_line: str
) -> tuple[roles.ReviewResult, bool]:
    assert feature.commit is not None
    diff = await run_in_threadpool(git.commit_diff, vc.worktree, feature.commit)
    prompt = roles.reviewer_prompt(
        title=feature.title,
        criteria=feature.expected_behavior,
        diff=_truncate(diff) or "(no changes)",
        check_summary=check_line,
        standards=[],
    )
    return await _ask(vc, agent=f"review-{feature.key}", persona_id="code-reviewer", prompt=prompt)


# ---------- security ----------


def added_lines(diff: str) -> list[tuple[str, int, str]]:
    """(file, line number, text) of every line a unified diff adds."""
    out: list[tuple[str, int, str]] = []
    path, number = "", 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[4:].removeprefix("b/")
        elif line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            number = int(match.group(1)) if match else 0
        elif line.startswith("+"):
            out.append((path, number, line[1:]))
            number += 1
        elif line.startswith(" "):
            number += 1
    return out


def changed_files(diff: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r"^\+\+\+ b/(.+)$", diff, re.MULTILINE)]


async def run_security(
    vc: ValidationContext, milestone_key: str, features: list[FeatureSnap]
) -> ValidatorReport:
    """A deterministic scan for committed secrets and risky files, then an ADK security review."""
    committed = [f for f in features if f.commit]
    findings: list[Finding] = []
    if not committed:
        return ValidatorReport(validator="security", milestone_id=milestone_key, verdict="pass")
    first = committed[0].commit
    assert first is not None
    base = await run_in_threadpool(git.parent_of, vc.worktree, first)
    head = committed[-1].commit
    assert head is not None
    diff = (
        await run_in_threadpool(git.range_diff, vc.worktree, base, head)
        if base
        else await run_in_threadpool(git.commit_diff, vc.worktree, head)
    )
    files = changed_files(diff)

    for path in files:
        if is_secret_file(path):
            findings.append(
                Finding(
                    file=path,
                    severity="critical",
                    message="A file that normally holds secrets was added to the project.",
                )
            )
    for path, number, text in added_lines(diff):
        for kind in find_secrets(text):
            findings.append(
                Finding(
                    file=path,
                    line=number,
                    severity="critical",
                    message=f"The line looks like it contains {kind}. Secrets must not be "
                    "committed: read them from the environment.",
                )
            )
    dependency_files = [p for p in files if Path(p).name in DEPENDENCY_FILES]
    if dependency_files:
        findings.append(
            Finding(
                severity="info",
                message="Dependencies changed in " + ", ".join(dependency_files) + ".",
            )
        )

    persona = apply(get_persona("security"), vc.variant)
    prompt = f"""{persona.instructions.strip()}

Review this diff of the milestone "{milestone_key}" for security problems: injection, broken
authentication or authorization, exposed secrets, unsafe dependencies and unsafe configuration.
Cite the file and line of each problem. Only report real problems.

Files changed: {", ".join(files) or "none"}
Dependency files changed: {", ".join(dependency_files) or "none"}

```diff
{_truncate(diff)}
```

Your final answer must be only a JSON object: {roles.REVIEW_SCHEMA}"""
    review, available = await _ask(
        vc, agent="security-review", persona_id="security", prompt=prompt
    )
    findings.extend(_findings_from(review, None))
    if not available:
        findings.append(
            Finding(
                severity="info",
                message="The security reviewer was unavailable: only the automatic scan ran.",
            )
        )
    return ValidatorReport(
        validator="security",
        milestone_id=milestone_key,
        verdict=_verdict(findings, not available),  # type: ignore[arg-type]
        findings=findings,
    )


# ---------- QA ----------


async def run_qa(
    vc: ValidationContext, milestone_key: str, features: list[FeatureSnap]
) -> ValidatorReport:
    """Run the acceptance tests QA wrote from the validation contract, in the sandbox. Criteria
    that need a browser are reported as not checked (browser testing is not available yet):
    they are never counted as passing."""
    findings: list[Finding] = []
    commands: list[CommandResult] = []
    unavailable = False
    checks = await vc.load_checks()
    acceptance_dir = vc.worktree / ACCEPTANCE_DIR
    has_tests = acceptance_dir.is_dir() and any(p.is_file() for p in acceptance_dir.rglob("*"))

    if not vc.acceptance_ready or not has_tests:
        unavailable = True
        findings.append(
            Finding(
                severity="info",
                message="QA has not written acceptance tests for this milestone, so nothing "
                "was checked against the validation contract.",
            )
        )
    elif "acceptance" not in checks:
        unavailable = True
        findings.append(
            Finding(
                severity="info",
                message="The project defines no `acceptance` check, so the acceptance tests "
                "cannot run. Add one to .hex/project.json.",
            )
        )
    else:
        outcome = await vc.run_check("acceptance")
        commands.append(
            CommandResult(
                command=checks["acceptance"],
                exit_code=outcome.exit_code if outcome.exit_code is not None else -1,
                duration_s=outcome.duration_ms / 1000,
                summary=outcome.output_tail[-OUTPUT_IN_REPORT:],
            )
        )
        if not accepted(outcome):
            refs = list(dict.fromkeys(_CONTRACT_ID.findall(outcome.output_tail)))
            reason = "ran no tests" if outcome.passed else "failed"
            if refs:
                findings.extend(
                    Finding(
                        severity="critical",
                        message=f"The acceptance check {reason} for {ref}.",
                        contract_ref=ref,
                        evidence=check_summary(outcome),
                    )
                    for ref in refs
                )
            else:
                findings.append(
                    Finding(
                        severity="critical",
                        message=f"The acceptance check {reason}.",
                        evidence=check_summary(outcome),
                    )
                )

    unchecked = [c["id"] for c in vc.criteria if c.get("how") == "browser"]
    if unchecked:
        findings.append(
            Finding(
                severity="info",
                message="Not checked (browser testing is not available in this build): "
                + ", ".join(unchecked),
            )
        )
    return ValidatorReport(
        validator="qa",
        milestone_id=milestone_key,
        verdict=_verdict(findings, unavailable),  # type: ignore[arg-type]
        findings=findings,
        commands=commands,
    )


VALIDATORS: dict[str, Callable[..., Awaitable[ValidatorReport]]] = {
    "qa": run_qa,
    "code-reviewer": run_scrutiny,
    "security": run_security,
}
