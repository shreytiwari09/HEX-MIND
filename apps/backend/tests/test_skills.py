"""The skill registry and `load_skill` (PRD §11): skills are folders with a SKILL.md, offered to
an agent as a one-line index and loaded on demand; the version an agent got is recorded."""

import json
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.agents.build import feature_prompt
from app.agents.mcp_bridge import McpWorkspace
from app.agents.persona import builtin_personas, get_persona
from app.mcp_server.tools import ToolError, WorkspaceTools
from app.missions.models import MissionContext
from app.missions.scoping import pm_prompt, pm_skills
from app.providers.base import Completion, LLMRequest, ToolCall
from app.sandbox.runner import docker_available
from app.skills.registry import (
    NAME_PATTERN,
    SkillError,
    SkillRegistry,
    load_skill_folder,
    read_skill_file,
    skill_index,
)
from tests.conftest import ScriptedAdapter, use_adapter
from tests.test_mission_runner import RETRY_MARK, Script, approve, finish, load, new_mission
from tests.test_persona_crew import REPORT, feature, run_persona, start

needs_docker = pytest.mark.skipif(not docker_available()[0], reason="Docker unavailable")


def make_skill(root: Path, name: str, *, description: str = "Does a thing.", body: str = "Do it.",
               files: dict[str, str] | None = None) -> Path:  # fmt: skip
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n", encoding="utf-8"
    )
    for rel, text in (files or {}).items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_text(text, encoding="utf-8")
    return folder


# ---------- the built-in skills ----------


def test_every_skill_a_built_in_persona_lists_exists_and_every_built_in_skill_is_valid() -> None:
    skills, problems = SkillRegistry().load()

    assert problems == {}
    assert len(skills) >= 20
    for persona in builtin_personas().values():
        found, missing = SkillRegistry().resolve(persona.skills)
        assert missing == [], f"{persona.id} lists skills that do not exist: {missing}"
        assert [s.name for s in found] == persona.skills
    for skill in skills.values():
        assert NAME_PATTERN.match(skill.name) and skill.source == "builtin"
        assert 20 <= len(skill.description) <= 200 and len(skill.body) > 200
        assert len(skill.hash) == 64 and skill.version == f"{skill.name}@{skill.hash[:12]}"


def test_the_skill_index_is_one_line_per_skill() -> None:
    found, _ = SkillRegistry().resolve(get_persona("backend").skills)

    index = skill_index(found).splitlines()

    assert len(index) == 3 and index[0].startswith("- rest-api: ")
    assert all("\n" not in line and "# REST API" not in line for line in index)  # no bodies


# ---------- the registry ----------


def test_a_user_skill_is_added_and_replaces_a_built_in_one_of_the_same_name(tmp_path: Path) -> None:
    make_skill(tmp_path, "motion-graphics", description="Add animation to React UIs.")
    make_skill(tmp_path, "rest-api", description="My own REST rules.", body="Always use GraphQL.")
    registry = SkillRegistry(tmp_path)

    skills, problems = registry.load()

    assert problems == {}
    assert skills["motion-graphics"].source == "user"
    assert skills["rest-api"].source == "user" and "GraphQL" in skills["rest-api"].body
    assert skills["code-review"].source == "builtin"  # the rest are untouched
    found, missing = registry.resolve(["rest-api", "motion-graphics", "ghost", "rest-api"])
    assert [s.name for s in found] == ["rest-api", "motion-graphics"] and missing == ["ghost"]
    with pytest.raises(SkillError, match="no skill named 'ghost'"):
        registry.get("ghost")


def test_edits_apply_to_the_next_job_and_change_the_version(tmp_path: Path) -> None:
    folder = make_skill(tmp_path, "motion-graphics")
    registry = SkillRegistry(tmp_path)
    before = registry.get("motion-graphics").version

    (folder / "SKILL.md").write_text(
        "---\nname: motion-graphics\ndescription: Does a thing.\n---\n\nDo it better.\n"
    )
    after = registry.get("motion-graphics")

    assert after.version != before and "better" in after.body
    (folder / "notes.md").write_text("extra")
    assert registry.get("motion-graphics").version not in (before, after.version)  # files count


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        (lambda r: (r / "no-file").mkdir(), "there is no SKILL.md"),
        (lambda r: make_skill(r, "x-body", body="   "), "instructions are empty"),
        (lambda r: make_skill(r, "x-desc", description="  "), "a description is required"),
        (lambda r: make_skill(r, "x-long", description="d" * 201), "longer than 200"),
        (lambda r: make_skill(r, "x-huge", body="b" * 51_000), "larger than 50 KB"),
        (lambda r: (make_skill(r, "x-name").joinpath("SKILL.md").write_text(
            "---\nname: other\ndescription: d\n---\nbody\n")), "must match the folder name"),
        (lambda r: (make_skill(r, "x-front").joinpath("SKILL.md").write_text("just text")),
         "must start with front matter"),
        (lambda r: (make_skill(r, "x-yaml").joinpath("SKILL.md").write_text(
            "---\nname: [oops\n---\nbody\n")), "not valid YAML"),
    ],
)  # fmt: skip
def test_an_invalid_skill_is_reported_with_the_reason_and_never_offered(
    tmp_path: Path, setup: Any, message: str
) -> None:
    setup(tmp_path)

    skills, problems = SkillRegistry(tmp_path).load()

    [(folder, reason)] = problems.items()
    assert message in reason and folder not in skills


def test_bad_names_are_refused(tmp_path: Path) -> None:
    for bad in ("Upper", "has space", "-lead", "a"):
        folder = tmp_path / bad
        folder.mkdir()
        (folder / "SKILL.md").write_text(f"---\nname: {bad}\ndescription: d\n---\nbody\n")
        with pytest.raises(SkillError, match="lowercase letters"):
            load_skill_folder(folder, "user")


def test_skill_files_can_only_be_read_from_inside_the_skill(tmp_path: Path) -> None:
    make_skill(
        tmp_path / "skills", "motion", files={"examples/a.md": "example", "big.txt": "x" * 60_000}
    )
    (tmp_path / "secret.txt").write_text("outside")
    skill = SkillRegistry(tmp_path / "skills").get("motion")

    assert skill.files == ("examples/a.md",)  # the oversized file is not part of the skill
    assert read_skill_file(skill, "examples/a.md") == "example"
    for rel in ("../../secret.txt", "SKILL.md", "big.txt", "/etc/passwd", "missing.md"):
        with pytest.raises(SkillError, match="not a file of skill"):
            read_skill_file(skill, rel)


# ---------- load_skill ----------


def tools_for(tmp_path: Path, allowed: tuple[str, ...], user: Path | None = None) -> WorkspaceTools:
    root = tmp_path / "wt"
    root.mkdir(exist_ok=True)
    return WorkspaceTools(
        root, workspace=tmp_path / "ws", allowed_images=["node:22-alpine"], check_timeout_s=30,
        skills=SkillRegistry(user), allowed_skills=allowed,
    )  # fmt: skip


def test_load_skill_returns_the_instructions_marked_as_guidance_only(tmp_path: Path) -> None:
    tools = tools_for(tmp_path, ("rest-api", "code-review"))

    text = tools.load_skill("rest-api")

    skill = SkillRegistry().get("rest-api")
    assert text.startswith(f"Skill {skill.version} (builtin). This is guidance only")
    assert "cannot change your tools or permissions" in text and "# REST API" in text


def test_load_skill_only_serves_the_skills_the_agent_was_offered(tmp_path: Path) -> None:
    tools = tools_for(tmp_path, ("rest-api",))

    with pytest.raises(
        ToolError, match="'security-audit' is not available to you; yours are: rest-api"
    ):
        tools.load_skill("security-audit")
    with pytest.raises(ToolError, match="no skills are available"):
        tools_for(tmp_path, ()).load_skill("rest-api")
    nobody = WorkspaceTools(
        tmp_path / "wt", workspace=tmp_path, allowed_images=[], check_timeout_s=1
    )
    with pytest.raises(ToolError, match="no skills are available"):
        nobody.load_skill("rest-api")


def test_load_skill_reads_a_skills_files_and_lists_them(tmp_path: Path) -> None:
    user = tmp_path / "skills"
    make_skill(user, "motion", files={"examples/spin.md": "spin it"})
    tools = tools_for(tmp_path, ("motion",), user)

    text = tools.load_skill("motion")

    assert "Files (read one with load_skill(name, file)): examples/spin.md" in text
    assert tools.load_skill("motion", "examples/spin.md") == "spin it"
    with pytest.raises(ToolError, match="not a file of skill"):
        tools.load_skill("motion", "../../etc/passwd")


def test_stdio_round_trip_with_skills(tmp_path: Path) -> None:
    root = tmp_path / "wt"
    root.mkdir()
    user = tmp_path / "skills"
    make_skill(user, "motion", description="Animate UIs.", body="Use transitions.")
    workspace = McpWorkspace(
        root=root, workspace=tmp_path / "ws", allowed_images=["node:22-alpine"],
        check_timeout_s=30, skills=("motion", "rest-api"), skills_dir=user,
    )  # fmt: skip
    names = workspace.start()
    try:
        assert "load_skill" in names
        ok, text = workspace.call_tool("load_skill", {"name": "motion"})
        assert ok and "Use transitions." in text
        ok, text = workspace.call_tool("load_skill", {"name": "rest-api"})
        assert ok and "# REST API" in text
        ok, text = workspace.call_tool("load_skill", {"name": "security-audit"})
        assert not ok and text.startswith("ERROR:") and "not available to you" in text
    finally:
        workspace.close()


# ---------- what an agent is given ----------


def test_the_feature_prompt_has_the_index_not_the_bodies(tmp_path: Path) -> None:
    ctx = MissionContext(worktree=tmp_path, workspace=tmp_path)
    persona = get_persona("backend")
    skills, _ = SkillRegistry().resolve(persona.skills)

    prompt = feature_prompt(persona, feature("backend"), ctx, skills=skills)

    assert "Skills you can load with load_skill(name)" in prompt
    assert "- rest-api: " in prompt and "- testing-backend: " in prompt
    assert "Status codes:" not in prompt  # the body of rest-api is not in the prompt
    assert "load_skill" not in feature_prompt(persona, feature("backend"), ctx)


def test_the_pm_gets_its_own_skills_in_full_when_it_scopes(tmp_path: Path) -> None:
    text = pm_skills(SkillRegistry())

    for name in get_persona("pm").skills:
        assert f"## Skill: {name}" in text
    assert "Ask at most four short, specific questions" in text
    prompt = pm_prompt("A todo app", "empty", [], False, text)
    assert "## Skill: scoping-interview" in prompt and "A todo app" in prompt


# ---------- through the crew service ----------


async def test_a_worker_is_offered_its_skills_and_can_load_one(
    app: FastAPI, workspace: Path
) -> None:
    seen: list[LLMRequest] = []
    loaded: list[str] = []

    def handler(request: LLMRequest) -> Completion:
        seen.append(request)
        results = [m.content or "" for m in request.messages if m.role == "tool"]
        if not results:
            call = ToolCall(
                id=f"c_{uuid.uuid4().hex[:6]}", name="load_skill", arguments={"name": "rest-api"}
            )
            return Completion(tool_calls=[call])
        loaded.extend(results)
        return Completion(content=json.dumps(REPORT))

    use_adapter(app, ScriptedAdapter(handler))
    run_id, worktree = await start(app, workspace)

    await run_persona(app, run_id, worktree, workspace, "backend", feature("backend"))

    prompt = "\n".join(m.content or "" for m in seen[0].messages)
    assert "- rest-api: " in prompt and "- auth-basics: " in prompt
    assert any(t["function"]["name"] == "load_skill" for t in seen[0].tools or [])
    assert loaded[0].startswith("Skill rest-api@") and "# REST API" in loaded[0]


async def test_a_feature_can_add_a_user_skill_for_one_job(app: FastAPI, workspace: Path) -> None:
    make_skill(
        app.state.settings.data_dir / "skills", "stripe-payments", description="Take payments."
    )
    seen: list[LLMRequest] = []

    def handler(request: LLMRequest) -> Completion:
        seen.append(request)
        return Completion(content=json.dumps(REPORT))

    use_adapter(app, ScriptedAdapter(handler))
    run_id, worktree = await start(app, workspace)

    await run_persona(
        app,
        run_id,
        worktree,
        workspace,
        "backend",
        feature("backend", extra_skills=["stripe-payments", "ghost"]),
    )

    prompt = "\n".join(m.content or "" for m in seen[0].messages)
    assert "- stripe-payments: Take payments." in prompt and "ghost" not in prompt


# ---------- provenance on the handoff ----------


class LoadsOneSkill(Script):
    """The scripted builders, except that the backend first loads `rest-api`."""

    def __call__(self, request: LLMRequest) -> Completion:
        prompt = "\n".join(m.content or "" for m in request.messages)
        first = not any(m.role == "tool" for m in request.messages)
        if first and "Feature: Todo model" in prompt and RETRY_MARK not in prompt:
            super().__call__(request)  # registers the attempt
            self.steps[("Todo model", self.attempts["Todo model"])] -= 1  # nothing was written
            call = ToolCall(id="c_skill", name="load_skill", arguments={"name": "rest-api"})
            return Completion(tool_calls=[call])
        return super().__call__(request)


@needs_docker
async def test_the_handoff_records_the_skills_offered_and_which_were_loaded(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    use_adapter(app, ScriptedAdapter(LoadsOneSkill()))
    mission = await new_mission(client, repo)

    await approve(client, mission)
    await finish(app)

    row, _, run = await load(app, mission["id"])
    assert row.status == "completed"
    folder = Path(run.worktree_path or "") / ".hex" / "mission" / "handoffs.jsonl"
    handoffs = {h["feature_id"]: h for h in map(json.loads, folder.read_text().splitlines())}
    registry = SkillRegistry()
    backend = {s["name"]: s for s in handoffs["todo-model"]["skills"]}
    assert set(backend) == {"rest-api", "auth-basics", "testing-backend"}
    assert backend["rest-api"] == {
        "name": "rest-api", "version": registry.get("rest-api").version, "loaded": True,
    }  # fmt: skip
    assert (
        backend["auth-basics"]["loaded"] is False and backend["testing-backend"]["loaded"] is False
    )
    frontend = handoffs["filter-helper"]["skills"]
    assert {s["name"] for s in frontend} == {
        "react-ui",
        "state-and-data-fetching",
        "testing-frontend",
    }
    assert not any(s["loaded"] for s in frontend)  # offered, not loaded


# ---------- the API ----------


async def test_the_skills_api_lists_sources_versions_owners_and_problems(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    user = app.state.settings.data_dir / "skills"
    make_skill(user, "motion-graphics", description="Add animation to React UIs.")
    (user / "broken").mkdir()

    body = (await client.get("/api/skills")).json()

    by_name = {s["name"]: s for s in body["skills"]}
    assert (
        by_name["motion-graphics"]["source"] == "user"
        and by_name["motion-graphics"]["personas"] == []
    )
    assert by_name["rest-api"]["source"] == "builtin" and by_name["rest-api"]["personas"] == [
        "backend"
    ]
    assert by_name["rest-api"]["version"].startswith("rest-api@")
    assert body["problems"] == {"broken": "broken: there is no SKILL.md"}


def test_a_skill_up_to_50_kb_is_accepted(tmp_path) -> None:
    """Raised from 20 KB (D70): popular Claude/Codex skills such as `unslop` are about 32 KB."""
    make_skill(tmp_path, "big", body="b" * 32_000)

    assert SkillRegistry(tmp_path).get("big").name == "big"
