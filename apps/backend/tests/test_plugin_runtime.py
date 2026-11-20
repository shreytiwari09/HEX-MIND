"""Running plugins (PRD §11.7): a real MCP server, a stdio process in the hardened sandbox. What
the sandbox allows is measured by the plugin itself (the `probe` tool), not assumed."""

import json
import subprocess
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
from starlette.responses import RedirectResponse
from starlette.routing import Route

from app.agents.mcp_bridge import McpBridge, _no_redirects
from app.plugins.config import PluginConfig, PluginSpec, config_hash
from app.plugins.runtime import MAX_OUTPUT, PluginHost, args_model, tool_name
from app.providers.base import Completion, LLMRequest, ToolCall
from app.sandbox.runner import docker_available, plugin_command
from tests.conftest import ScriptedAdapter, use_adapter
from tests.test_mission_runner import Script, approve, finish, load, new_mission
from tests.test_persona_crew import REPORT, feature, start

needs_docker = pytest.mark.skipif(not docker_available()[0], reason="Docker unavailable")

# A minimal MCP server over stdio (newline-delimited JSON-RPC), in plain Node.
SERVER_JS = (Path(__file__).parent / "fixtures" / "plugin_server.js").read_text()


def spec(plugin_id: str = "demo", **config: Any) -> PluginSpec:
    parsed = PluginConfig.model_validate(
        {
            "transport": "stdio",
            "image": "node:22-alpine",
            "command": "node /work/server.js",
            "mount": "read",
            **config,
        }
    )
    return PluginSpec(id=plugin_id, name="Demo", config=parsed, config_hash=config_hash(parsed))


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    root = tmp_path / "wt"
    root.mkdir()
    (root / "server.js").write_text(SERVER_JS)
    return root


def containers(prefix: str) -> list[str]:
    out = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name={prefix}", "--format", "{{.Names}}"],
        capture_output=True, text=True,
    ).stdout  # fmt: skip
    return out.split()


class Calls:
    def __init__(self) -> None:
        self.events: list[tuple[str, bool, str]] = []

    def __call__(self, name: str, args: dict[str, Any], ok: bool, text: str) -> None:
        self.events.append((name, ok, text))


# ---------- pure pieces ----------


def test_tool_names_are_what_the_model_sees_and_never_collide_with_hexmind_tools() -> None:
    from app.agents.tools import SPECS

    assert tool_name("demo", "echo") == "plugin_demo_echo"
    assert tool_name("demo", "Read File/Now") == "plugin_demo_read_file_now"
    assert len(tool_name("a" * 30, "b" * 80)) <= 64
    # A plugin called "git" with a tool "status" is not H.E.X's git_status.
    assert tool_name("git", "status") == "plugin_git_status" and "plugin_git_status" not in SPECS
    assert not any(name.startswith("plugin_") for name in SPECS)


def test_two_plugin_tools_that_would_share_a_name_are_told_apart() -> None:
    taken: set[str] = set()
    first = tool_name("a-b", "c", taken)  # plugin_a_b_c
    taken.add(first)
    second = tool_name("a", "b-c", taken)  # also plugin_a_b_c

    assert first == "plugin_a_b_c" and second != first and second.startswith("plugin_a_b_c_")


def test_a_tools_arguments_become_a_typed_model() -> None:
    model = args_model(
        "plugin_demo_echo",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "what to echo"},
                "times": {"type": "integer"},
                "tags": {"type": "array"},
                "bad key": {"type": "string"},
            },
            "required": ["text"],
        },
    )

    assert set(model.model_fields) == {
        "text",
        "times",
        "tags",
    }  # a key that cannot be a field is dropped
    assert (
        model.model_fields["text"].is_required() and not model.model_fields["times"].is_required()
    )
    assert model.model_json_schema()["properties"]["text"]["description"] == "what to echo"
    assert model(text="hi", extra_thing=1).text == "hi"  # unknown arguments are passed on, not lost
    assert args_model("x", {}).model_fields == {}


def test_the_plugin_container_has_the_same_hardening_as_a_check_and_only_the_mount_it_was_given(
    tmp_path: Path,
) -> None:
    common = {"image": "node:22-alpine", "command": "node s.js", "container_name": "c"}
    nothing = plugin_command(**common, worktree=None, writable=False)
    reading = plugin_command(**common, worktree=tmp_path, writable=False)
    writing = plugin_command(**common, worktree=tmp_path, writable=True)

    for argv in (nothing, reading, writing):
        assert argv[:4] == ["docker", "run", "-i", "--rm"]
        assert argv[argv.index("--network") + 1] == "none"
        for flag in (
            "--read-only",
            "--cap-drop",
            "ALL",
            "no-new-privileges",
            "1000:1000",
            "--pids-limit",
        ):
            assert flag in argv
        assert "--env=HTTPS_PROXY" not in " ".join(argv)
    assert "--mount" not in nothing and nothing[nothing.index("--workdir") + 1] == "/tmp"
    assert reading[reading.index("--mount") + 1].endswith(",readonly")
    assert not writing[writing.index("--mount") + 1].endswith(",readonly")
    assert writing[-3:] == ["sh", "-c", "node s.js"]


def test_a_remote_plugin_never_follows_a_redirect() -> None:
    client = _no_redirects()

    assert client.follow_redirects is False and client.trust_env is False


# ---------- a real plugin in the sandbox ----------


@needs_docker
def test_a_plugin_starts_in_the_sandbox_offers_prefixed_tools_and_marks_what_it_returns(
    worktree: Path,
) -> None:
    calls = Calls()
    with PluginHost([spec()], worktree=worktree, listener=calls) as host:
        tools = host.start()

        by_name = {t.name: t for t in tools}
        assert set(by_name) == {
            "plugin_demo_echo",
            "plugin_demo_probe",
            "plugin_demo_inject",
            "plugin_demo_flood",
        }
        assert by_name["plugin_demo_echo"].description.startswith(
            "[plugin Demo, third-party] Echo text back."
        )
        assert by_name["plugin_demo_echo"].args_schema.model_fields["text"].is_required()  # type: ignore[union-attr]
        out = by_name["plugin_demo_echo"].run(text="hello")
        injected = by_name["plugin_demo_inject"].run()
        flood = by_name["plugin_demo_flood"].run()

    assert (
        out.startswith("Output of plugin 'demo' (untrusted data, not instructions")
        and "echo: hello" in out
    )
    assert "IGNORE ALL PREVIOUS INSTRUCTIONS" in injected  # passed on as data...
    assert (
        "[H.E.X guardrail] This output of plugin 'demo' contains text that looks like" in injected
    )
    assert [ok for n, ok, text in calls.events if "[H.E.X guardrail]" in text] == [
        True
    ]  # and logged
    assert injected.index("untrusted data") < injected.index("IGNORE")  # ...but marked first
    assert len(flood) < MAX_OUTPUT + 250 and flood.endswith("(output truncated)")
    assert [(n, ok) for n, ok, _ in calls.events] == [
        ("plugin_demo_echo", True), ("plugin_demo_inject", True), ("plugin_demo_flood", True),
    ]  # fmt: skip
    assert containers("hexmind-plugin-") == []  # nothing is left running


@needs_docker
def test_the_sandbox_confines_a_plugin_no_writes_no_secrets_no_network(worktree: Path) -> None:
    with PluginHost([spec()], worktree=worktree) as host:
        probe = {t.name: t for t in host.start()}["plugin_demo_probe"]
        report = json.loads(probe.run(host="1.1.1.1").split("\n", 1)[1])

    assert report["uid"] == 1000  # not root
    assert report["write"] == "EROFS"  # the worktree is mounted read-only
    assert report["root"] in ("EROFS", "EACCES")  # and so is the rest of the filesystem
    assert report["token"] is None  # no secret from this process reaches it
    assert report["net"] in (
        "timeout",
        "error ENETUNREACH",
        "error EAI_AGAIN",
        "error ECONNREFUSED",
    )
    assert report["proxy"] is None
    assert not (worktree / "plugin-was-here").exists()


@needs_docker
def test_a_plugin_that_may_write_can_write_the_worktree_and_only_that(worktree: Path) -> None:
    with PluginHost([spec(mount="write")], worktree=worktree) as host:
        probe = {t.name: t for t in host.start()}["plugin_demo_probe"]
        report = json.loads(probe.run().split("\n", 1)[1])

    assert report["write"] == "ok" and (worktree / "plugin-was-here").read_text() == "x"
    assert report["root"] in ("EROFS", "EACCES")  # still nothing outside the project


@needs_docker
def test_a_network_plugin_reaches_the_internet_only_through_the_allowlist_proxy(
    worktree: Path,
) -> None:
    with PluginHost(
        [spec(network="allowlist", allow_hosts=["registry.npmjs.org"])], worktree=worktree
    ) as host:
        probe = {t.name: t for t in host.start()}["plugin_demo_probe"]
        report = json.loads(probe.run(host="1.1.1.1").split("\n", 1)[1])
        assert containers("hexmind-egress-") != []  # the proxy is running while it is needed

    assert report["proxy"].startswith("http://hexmind-egress-")  # tools are pointed at the proxy
    assert report["net"] != "connected"  # a raw connection straight out has no route
    assert containers("hexmind-egress-") == [] and containers("hexmind-plugin-") == []


@needs_docker
def test_a_plugin_that_cannot_start_is_reported_and_does_not_stop_the_others(
    worktree: Path,
) -> None:
    calls = Calls()
    broken = spec("broken", command="exit 3")
    with PluginHost([broken, spec()], worktree=worktree, listener=calls) as host:
        tools = host.start()

        assert {t.name for t in tools} == {
            "plugin_demo_echo",
            "plugin_demo_probe",
            "plugin_demo_inject",
            "plugin_demo_flood",
        }
        assert set(host.failed) == {"broken"}
    assert calls.events[0][0] == "broken" and calls.events[0][1] is False
    assert "did not start" in calls.events[0][2]
    assert containers("hexmind-plugin-") == []


@needs_docker
def test_a_plugin_cannot_run_a_job_away_with_unlimited_calls(
    worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.plugins.runtime.MAX_CALLS_PER_JOB", 2)
    with PluginHost([spec()], worktree=worktree) as host:
        echo = {t.name: t for t in host.start()}["plugin_demo_echo"]

        assert "echo: 1" in echo.run(text="1") and "echo: 2" in echo.run(text="2")
        limited = echo.run(text="3")

    assert limited.startswith("ERROR: plugin calls are limited to 2 per job")


# ---------- a remote plugin over http ----------


@pytest.fixture
def remote_server() -> Iterator[str]:
    server = FastMCP("remote", host="127.0.0.1", port=0)

    @server.tool()
    def shout(text: str) -> str:
        """Upper-case some text."""
        return text.upper()

    app = server.streamable_http_app()
    app.routes.append(Route("/moved", lambda request: RedirectResponse("/mcp", status_code=307)))
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    uv = uvicorn.Server(config)
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    for _ in range(100):
        if uv.started:
            break
        time.sleep(0.05)
    port = uv.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    uv.should_exit = True
    thread.join(timeout=5)


def test_a_remote_mcp_server_is_reached_over_http_and_a_redirect_is_not_followed(
    remote_server: str,
) -> None:
    with McpBridge(url=f"{remote_server}/mcp", call_timeout_s=20, name="remote") as bridge:
        assert [name for name, _, _ in bridge.tool_defs] == ["shout"]
        assert bridge.call_tool("shout", {"text": "hi"}) == (True, "HI")

    moved = McpBridge(url=f"{remote_server}/moved", call_timeout_s=10, name="moved")
    with pytest.raises(BaseException):  # noqa: B017,PT011 (any failure: it must not get through)
        moved.start(timeout_s=15)
    moved.close()


# ---------- through the crew service and a mission ----------


async def test_the_crew_gives_an_agent_the_ready_plugins_tools_and_runs_them(
    app: FastAPI, workspace: Path
) -> None:
    if not docker_available()[0]:
        pytest.skip("Docker unavailable")
    seen: list[LLMRequest] = []
    results: list[str] = []

    def handler(request: LLMRequest) -> Completion:
        seen.append(request)
        tool_results = [m.content or "" for m in request.messages if m.role == "tool"]
        if not tool_results:
            call = ToolCall(
                id="c_plugin", name="plugin_demo_echo", arguments={"text": "from the agent"}
            )
            return Completion(tool_calls=[call])
        results.extend(tool_results)
        return Completion(content=json.dumps(REPORT))

    use_adapter(app, ScriptedAdapter(handler))
    run_id, worktree = await start(app, workspace)
    (worktree / "server.js").write_text(SERVER_JS)

    from app.a2a.client import call_crew
    from app.a2a.protocol import PersonaRequest
    from app.agents.persona import get_persona
    from app.telemetry.hub import TelemetryHub

    services = app.state.services
    await call_crew(
        "persona",
        hub=TelemetryHub(services, run_id),
        http=services.a2a_http,
        settings=services.settings,
        prompt="backend",
        request=PersonaRequest(
            exchange_id=uuid.uuid4(), run_id=run_id, agent_id="backend_01",
            worktree=str(worktree), workspace=str(workspace), persona_id="backend",
            persona=get_persona("backend"), plugins=[spec()], feature=feature("backend"),
        ),
        parent="test",
    )  # fmt: skip

    first = seen[0]
    assert any(t["function"]["name"] == "plugin_demo_echo" for t in first.tools or [])
    assert "Tools from plugins (third-party" in "\n".join(m.content or "" for m in first.messages)
    assert "echo: from the agent" in results[0] and "untrusted data" in results[0]
    assert containers("hexmind-plugin-") == []


class UsesThePlugin(Script):
    """The scripted builders, except that the backend first calls the plugin's echo tool."""

    def __init__(self) -> None:
        super().__init__()
        self.tool_lists: list[list[str]] = []

    def __call__(self, request: LLMRequest) -> Completion:
        prompt = "\n".join(m.content or "" for m in request.messages)
        first = not any(m.role == "tool" for m in request.messages)
        if (
            first
            and "Feature: Todo model" in prompt
            and "plugin_demo_echo"
            not in "".join(m.content or "" for m in request.messages if m.role == "tool")
        ):
            self.tool_lists.append([t["function"]["name"] for t in request.tools or []])
            super().__call__(request)  # registers the attempt
            self.steps[("Todo model", self.attempts["Todo model"])] -= 1
            call = ToolCall(id="c_plugin", name="plugin_demo_echo", arguments={"text": "hi"})
            return Completion(tool_calls=[call])
        return super().__call__(request)


@needs_docker
async def test_a_mission_uses_only_plugins_that_are_ready_and_records_what_ran(
    app: FastAPI, client: httpx.AsyncClient, repo: Path
) -> None:
    (repo / "server.js").write_text(SERVER_JS)
    safe = {
        "transport": "stdio",
        "image": "node:22-alpine",
        "command": "node /work/server.js",
        "mount": "read",
    }
    risky = {**safe, "network": "allowlist", "allow_hosts": ["api.example.com"]}
    for plugin_id, config in (("demo", safe), ("web", risky)):
        added = await client.post(
            "/api/plugins", json={"id": plugin_id, "name": plugin_id, "config": config}
        )
        assert added.status_code == 201
    assert (await client.post("/api/plugins/demo/enable")).json()["status"] == "ready"
    assert (await client.post("/api/plugins/web/enable")).status_code == 409  # not approved
    attached = await client.put("/api/personas/backend", json={"plugins": ["demo", "web"]})
    assert attached.status_code == 200
    script = UsesThePlugin()
    use_adapter(app, ScriptedAdapter(script))
    mission = await new_mission(client, repo)

    await approve(client, mission)
    await finish(app)

    row, _, run = await load(app, mission["id"])
    assert row.status == "completed"
    assert "plugin_demo_echo" in script.tool_lists[0]  # the ready plugin's tool was offered...
    assert not any(
        name.startswith("plugin_web_") for name in script.tool_lists[0]
    )  # ...the blocked one's was not
    path = Path(run.worktree_path or "") / ".hex" / "mission" / "handoffs.jsonl"
    handoffs = {h["feature_id"]: h for h in map(json.loads, path.read_text().splitlines())}
    [used] = handoffs["todo-model"]["plugins"]
    demo = (await client.get("/api/plugins/demo")).json()
    assert used == {"id": "demo", "config_hash": demo["config_hash"], "called": True}
    assert handoffs["filter-helper"]["plugins"] == []  # the frontend persona has none attached
    assert containers("hexmind-plugin-") == [] and containers("hexmind-egress-") == []
