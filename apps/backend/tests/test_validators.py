"""Validators at the end of a milestone: scrutiny (sandbox checks + one review per feature) and
security (a deterministic secret scan + a review), the gate they form, findings going back to the
builder, and what happens when a validator cannot do its job. Missions run for real (see
test_mission_runner); only the models are scripted."""

import json
import re
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.agents.roles import ReviewFinding, ReviewResult
from app.context.redact import find_secrets
from app.db.models import HandoffRow, Milestone, ValidatorReportRow
from app.events.log import list_events
from app.missions.models import Finding
from app.missions.validators import (
    VALIDATORS,
    _findings_from,
    _verdict,
    added_lines,
    changed_files,
)
from app.providers.base import Completion, LLMRequest, ProviderError
from app.sandbox.runner import docker_available
from tests.conftest import ScriptedAdapter, use_adapter
from tests.test_mission_runner import (
    GOOD,
    PLAN,
    Script,
    approve,
    finish,
    load,
    needs,
    new_mission,
)
from tests.test_run_contract import repo_with
from tests.test_run_workflow import TODOS_JS

needs_docker = pytest.mark.skipif(not docker_available()[0], reason="Docker unavailable")
SECRET = "sk-abcdefghijklmnopqrstuvwxyz123456"

DIFF = """diff --git a/src/auth.js b/src/auth.js
new file mode 100644
--- /dev/null
+++ b/src/auth.js
@@ -0,0 +1,3 @@
+const a = 1
+const key = "sk-abcdefghijklmnopqrstuvwxyz123456"
+module.exports = { a }
diff --git a/src/app.js b/src/app.js
--- a/src/app.js
+++ b/src/app.js
@@ -4,2 +4,3 @@ function main() {
 keep
-old
+new
 keep
"""


def test_the_diff_parser_finds_added_lines_with_their_numbers() -> None:
    assert added_lines(DIFF) == [
        ("src/auth.js", 1, "const a = 1"),
        ("src/auth.js", 2, f'const key = "{SECRET}"'),
        ("src/auth.js", 3, "module.exports = { a }"),
        ("src/app.js", 5, "new"),  # context line 4, removed line, then the added line
    ]
    assert changed_files(DIFF) == ["src/auth.js", "src/app.js"]


def test_secret_kinds_are_named_without_repeating_the_secret() -> None:
    assert find_secrets(f'const key = "{SECRET}"') == ["a provider API key"]
    assert find_secrets("ghp_abcdefghijklmnopqrstuvwxyz0123") == ["a GitHub token"]
    assert find_secrets("AKIAABCDEFGHIJKLMNOP") == ["an AWS access key"]
    assert find_secrets("API_KEY=hunter2hunter2") == ["a hard-coded secret value"]
    assert find_secrets("const total = items.length") == []


def test_a_request_for_changes_can_never_be_lost_and_unavailable_never_passes() -> None:
    asked = ReviewResult(verdict="changes_requested", summary="Handle the empty title.")
    minor = ReviewResult(
        verdict="changes_requested",
        findings=[ReviewFinding(file="a.js", line=3, severity="minor", message="style")],
    )
    clean = ReviewResult(verdict="approved")

    from_summary = _findings_from(asked, "todo-model")
    assert [(f.severity, f.feature_id, f.message) for f in from_summary] == [
        ("major", "todo-model", "Handle the empty title.")
    ]
    assert [f.severity for f in _findings_from(minor, None)] == ["minor", "major"]
    assert _findings_from(clean, None) == []

    assert _verdict([Finding(severity="major", message="x")], unavailable=False) == "fail"
    assert _verdict([Finding(severity="major", message="x")], unavailable=True) == "fail"
    assert _verdict([Finding(severity="minor", message="x")], unavailable=False) == "pass"
    assert _verdict([], unavailable=True) == "needs_user"  # could not check: never a pass
    assert _verdict([], unavailable=False) == "pass"


# ---------- missions with validators ----------


def plan_with_validators(validators: list[str] | None = None) -> dict[str, Any]:
    plan = json.loads(json.dumps(PLAN))
    for milestone in plan["milestones"]:
        milestone["validators"] = (
            validators if validators is not None else ["code-reviewer", "security"]
        )
    return plan


class Validators:
    """Plays the Coder personas (Script) and the reviewers. `feature_reviews[title]` and
    `security` are lists of ReviewResult JSON dicts, used in order; the last one repeats."""

    def __init__(self, script: Script) -> None:
        self.script = script
        self.feature_reviews: dict[str, list[dict[str, Any]]] = {}
        self.security: list[dict[str, Any]] = []
        self.outage = False
        self.seen: list[str] = []

    def _next(
        self, options: list[dict[str, Any]], key: str, counts: dict[str, int]
    ) -> dict[str, Any]:
        index = counts.get(key, 0)
        counts[key] = index + 1
        return options[min(index, len(options) - 1)] if options else {"verdict": "approved"}

    counts: dict[str, int]

    def __call__(self, request: LLMRequest) -> Completion:
        if request.purpose != "reviewer":
            return self.script(request)
        if self.outage:
            raise ProviderError("model unavailable", retryable=False)
        prompt = "\n".join(m.content or "" for m in request.messages)
        counts = self.__dict__.setdefault("counts", {})
        if "for security problems" in prompt:
            self.seen.append("security")
            verdict = self._next(self.security, "security", counts)
        else:
            title = re.search(r'for the task "(.+?)"', prompt).group(1)  # type: ignore[union-attr]
            self.seen.append(f"review:{title}")
            verdict = self._next(self.feature_reviews.get(title, []), title, counts)
        return Completion(content=json.dumps({"summary": "", "findings": [], **verdict}))


def request_changes(
    message: str, file: str = "src/todos.js", severity: str = "major"
) -> dict[str, Any]:
    return {
        "verdict": "changes_requested",
        "summary": message,
        "findings": [{"file": file, "line": 1, "severity": severity, "message": message}],
    }


async def reports(app: FastAPI, mission_id: str) -> list[ValidatorReportRow]:
    async with app.state.sessionmaker() as session:
        return list(
            await session.scalars(
                select(ValidatorReportRow).order_by(ValidatorReportRow.created_at)
            )
        )


async def milestone_statuses(app: FastAPI) -> dict[str, str]:
    async with app.state.sessionmaker() as session:
        return {m.key: m.status for m in await session.scalars(select(Milestone))}


@needs_docker
async def test_validators_check_every_milestone_and_a_pass_means_the_milestone_passed(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    play = Validators(Script())
    use_adapter(app, ScriptedAdapter(play))
    mission = await new_mission(client, repo, plan_with_validators())

    await approve(client, mission)
    await finish(app)

    row, _, run = await load(app, mission["id"])
    assert row.status == "completed"
    assert await milestone_statuses(app) == {"m1-model": "passed", "m2-filter": "passed"}
    stored = await reports(app, mission["id"])
    assert sorted((r.data["milestone_id"], r.validator, r.verdict) for r in stored) == [
        ("m1-model", "code-reviewer", "pass"),
        ("m1-model", "security", "pass"),
        ("m2-filter", "code-reviewer", "pass"),
        ("m2-filter", "security", "pass"),
    ]
    scrutiny = next(r for r in stored if r.validator == "code-reviewer" and r.round == 1)
    # The commands in the report are what the sandbox really ran.
    assert [(c["command"], c["exit_code"]) for c in scrutiny.data["commands"]] == [
        ("node --test", 0)
    ]
    assert {s for s in play.seen} == {"review:Todo model", "review:Filter helper", "security"}
    async with app.state.sessionmaker() as session:
        events = await list_events(session, run.id)
    assert [e.type for e in events].count("validator_started") == 4
    reported = [e.payload for e in events if e.type == "validator_reported"]
    assert len(reported) == 4 and {p["verdict"] for p in reported} == {"pass"}
    folder = Path(run.worktree_path or "") / ".hex" / "mission" / "validator-reports"
    assert sorted(p.name for p in folder.iterdir()) == [
        "m1-model-code-reviewer-r1.json",
        "m1-model-security-r1.json",
        "m2-filter-code-reviewer-r1.json",
        "m2-filter-security-r1.json",
    ]
    listed = (await client.get(f"/api/missions/{mission['id']}/validation")).json()
    assert len(listed) == 4
    assert {(r["milestone_id"], r["validator"], r["verdict"]) for r in listed} == {
        ("m1-model", "code-reviewer", "pass"),
        ("m1-model", "security", "pass"),
        ("m2-filter", "code-reviewer", "pass"),
        ("m2-filter", "security", "pass"),
    }
    assert (
        await client.get("/api/missions/00000000-0000-0000-0000-000000000000/validation")
    ).status_code == 404


@needs_docker
async def test_findings_go_back_to_the_builder_and_the_milestone_is_checked_again(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    script = Script(
        {
            ("Todo model", 0): GOOD["Todo model"],
            ("Todo model", 1): [("src/todos.js", TODOS_JS + "// empty titles are rejected\n")],
            ("Filter helper", 0): GOOD["Filter helper"],
        }
    )
    play = Validators(script)
    play.feature_reviews["Todo model"] = [
        request_changes("addTodo accepts an empty title"),
        {"verdict": "approved"},
    ]
    use_adapter(app, ScriptedAdapter(play))
    mission = await new_mission(client, repo, plan_with_validators(["code-reviewer"]))

    await approve(client, mission)
    await finish(app)

    row, features, _ = await load(app, mission["id"])
    assert row.status == "completed" and await milestone_statuses(app) == {
        "m1-model": "passed",
        "m2-filter": "passed",
    }
    rework = script.prompts["Todo model"][-1]
    assert "A validator found problems with this feature" in rework
    assert "[code-reviewer, major] src/todos.js:1: addTodo accepts an empty title" in rework
    first, second = [
        r for r in await reports(app, mission["id"]) if r.data["milestone_id"] == "m1-model"
    ]
    assert (first.round, first.verdict, second.round, second.verdict) == (1, "fail", 2, "pass")
    assert first.data["findings"][0]["feature_id"] == "todo-model"
    async with app.state.sessionmaker() as session:
        handoffs = list(await session.scalars(select(HandoffRow)))
    assert len(handoffs) == 3  # todo-model built, reworked after validation, then filter-helper
    assert features["todo-model"].attempts == 1  # the rework counted as a fresh attempt


@needs_docker
async def test_a_committed_secret_is_found_without_a_model_and_is_never_repeated(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    leaky = [
        ("src/todos.js", TODOS_JS),
        ("src/todos.test.js", GOOD["Todo model"][1][1]),
        ("src/config.js", f'const key = "{SECRET}"\nmodule.exports = key\n'),
    ]
    script = Script(
        {
            ("Todo model", 0): leaky,
            ("Todo model", 1): [("src/config.js", "module.exports = process.env.API_KEY\n")],
            ("Filter helper", 0): GOOD["Filter helper"],
        }
    )
    play = Validators(script)  # the security model approves: the scan alone must catch it
    use_adapter(app, ScriptedAdapter(play))
    mission = await new_mission(client, repo, plan_with_validators(["security"]))

    await approve(client, mission)
    await finish(app)

    assert (await load(app, mission["id"]))[0].status == "completed"
    first = next(r for r in await reports(app, mission["id"]) if r.round == 1)
    assert first.verdict == "fail"
    [secret] = [f for f in first.data["findings"] if f["severity"] == "critical"]
    assert (secret["file"], secret["line"]) == ("src/config.js", 1)
    assert "a provider API key" in secret["message"]
    assert SECRET not in json.dumps(first.data)  # the report never repeats the secret
    assert "src/config.js:1" in script.prompts["Todo model"][-1]
    assert SECRET not in script.prompts["Todo model"][-1]


@needs_docker
async def test_a_failing_project_check_is_evidence_from_the_sandbox_and_two_failed_rounds_ask_you(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    contract = {"stack": "x", "image": "node:22-alpine", "test": "node --test", "lint": "exit 3"}
    root = repo_with(tmp_path, contract)
    script = Script(  # the rework changes a file, but lint (`exit 3`) cannot be fixed by it
        {
            ("Todo model", 0): GOOD["Todo model"],
            ("Todo model", 1): [("src/todos.js", TODOS_JS + "// tried to fix lint\n")],
            ("Filter helper", 0): GOOD["Filter helper"],
        }
    )
    use_adapter(app, ScriptedAdapter(Validators(script)))
    mission = await new_mission(client, root, plan_with_validators(["code-reviewer"]))

    await approve(client, mission)
    await finish(app)

    row, _, _ = await load(app, mission["id"])
    assert row.status == "needs_user"
    assert (await milestone_statuses(app))["m1-model"] == "failed"
    rounds = [r for r in await reports(app, mission["id"]) if r.data["milestone_id"] == "m1-model"]
    assert [(r.round, r.verdict) for r in rounds] == [(1, "fail"), (2, "fail")]
    lint = next(c for c in rounds[0].data["commands"] if c["command"] == "exit 3")
    assert lint["exit_code"] == 3
    finding = rounds[0].data["findings"][0]
    assert (finding["severity"], finding["message"]) == ("major", "The `lint` check failed.")
    [need] = await needs(app, mission["id"])
    assert need.kind == "milestone_failed" and need.options == ["retry", "accept", "stop"]
    assert need.evidence["milestone_id"] == "m1-model"
    assert any("lint" in f for f in need.evidence["findings"])

    # Accepting goes on without calling the milestone passed.
    contract["lint"] = "true"
    answer = await client.post(f"/api/needs/{need.id}/answer", json={"action": "accept"})
    assert answer.json()["status"] == "running"
    await finish(app)
    assert (await load(app, mission["id"]))[0].status == "needs_user"  # m2 fails the same lint
    assert (await milestone_statuses(app))["m1-model"] == "accepted"


@needs_docker
async def test_a_validator_that_cannot_run_is_never_a_pass_and_retry_checks_again(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    play = Validators(Script())
    play.outage = True
    use_adapter(app, ScriptedAdapter(play))
    mission = await new_mission(client, repo, plan_with_validators(["code-reviewer", "security"]))

    await approve(client, mission)
    await finish(app)

    row, _, _ = await load(app, mission["id"])
    assert row.status == "needs_user"
    assert (await milestone_statuses(app))["m1-model"] == "completed"  # not "passed"
    stored = await reports(app, mission["id"])
    assert {r.verdict for r in stored} == {"needs_user"}  # no fabricated pass
    [need] = await needs(app, mission["id"])
    assert need.kind == "validator_unavailable" and "Nothing was marked as passing" in need.summary
    messages = [f["message"] for r in stored for f in r.data["findings"]]
    assert any("unavailable" in m for m in messages)

    play.outage = False  # the provider is back
    await client.post(f"/api/needs/{need.id}/answer", json={"action": "retry"})
    await finish(app)

    assert (await load(app, mission["id"]))[0].status == "completed"
    assert await milestone_statuses(app) == {"m1-model": "passed", "m2-filter": "passed"}


@needs_docker
async def test_a_validator_the_build_does_not_have_does_not_block_or_pass_a_milestone(
    app: FastAPI, client: httpx.AsyncClient, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delitem(VALIDATORS, "qa")  # as if QA were not built
    use_adapter(app, ScriptedAdapter(Validators(Script())))
    mission = await new_mission(client, repo, plan_with_validators(["qa"]))

    await approve(client, mission)
    await finish(app)

    assert (await load(app, mission["id"]))[0].status == "completed"
    assert set((await milestone_statuses(app)).values()) == {"completed"}  # never "passed"
    assert await reports(app, mission["id"]) == []
