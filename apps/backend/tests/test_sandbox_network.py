"""Project images built from `.hex/Dockerfile`, and the install network: no route out except an
allowlist proxy that reaches package registries only. Docker tests use the real daemon."""

import asyncio
import json
import socket
import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.db.models import CheckResult, HandoffRow
from app.mcp_server.tools import ToolError, WorkspaceTools
from app.missions.runner import DEPENDENCY_FILES, dependency_fingerprint
from app.sandbox import egress_proxy
from app.sandbox.contract import RunContract
from app.sandbox.image import (
    DockerfileError,
    check_dockerfile,
    ensure_project_image,
    image_tag,
)
from app.sandbox.profile import load_profile
from app.sandbox.runner import (
    DEFAULT_INSTALL_HOSTS,
    docker_available,
    docker_command,
    run_check,
)
from app.workspace import git
from tests.conftest import ScriptedAdapter, use_adapter
from tests.test_mission_runner import Script, approve, finish, load, new_mission
from tests.test_run_contract import repo_with

needs_docker = pytest.mark.skipif(not docker_available()[0], reason="Docker unavailable")
IMAGES = ["node:22-alpine", "python:3.11-slim"]
DOCKERFILE = "FROM node:22-alpine\nRUN mkdir /opt/tool && echo built-ok > /opt/tool/marker\n"

# Asks the proxy named in HTTPS_PROXY for a tunnel to argv[2], or connects straight to it.
PROBE_JS = """const net = require('net')
const [mode, target] = process.argv.slice(2)
const done = (text) => { console.log(text); process.exit(0) }
setTimeout(() => done('timeout'), 8000)
if (mode === 'proxy') {
  const proxy = new URL(process.env.HTTPS_PROXY)
  const socket = net.connect(Number(proxy.port), proxy.hostname, () =>
    socket.write(`CONNECT ${target} HTTP/1.1\\r\\nHost: ${target}\\r\\n\\r\\n`))
  socket.on('data', (d) => done(d.toString().split('\\r\\n')[0]))
  socket.on('error', (e) => done('error ' + e.code))
} else {
  const [host, port] = target.split(':')
  const socket = net.connect(Number(port), host, () => done('connected'))
  socket.on('error', (e) => done('error ' + e.code))
}
"""


def internet() -> bool:
    try:
        socket.create_connection(("registry.npmjs.org", 443), timeout=5).close()
    except OSError:
        return False
    return True


# ---------- the proxy's rules (no Docker) ----------


def test_the_allowlist_matches_hosts_and_their_subdomains_only() -> None:
    allow = ["registry.npmjs.org", "pypi.org"]

    assert egress_proxy.host_allowed("registry.npmjs.org", allow)
    assert egress_proxy.host_allowed("Files.PyPI.org.", allow)
    assert not egress_proxy.host_allowed("evilpypi.org", allow)
    assert not egress_proxy.host_allowed("registry.npmjs.org.evil.com", allow)
    assert not egress_proxy.host_allowed("example.com", allow)
    for private in ("127.0.0.1", "10.1.2.3", "192.168.0.4", "169.254.169.254", "::1", "172.16.0.9"):
        assert not egress_proxy.public_address(private)
    assert egress_proxy.public_address("104.16.1.35")
    assert not egress_proxy.public_address("not-an-address")


async def ask(port: int, request: bytes) -> str:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(request)
    await writer.drain()
    line = (await asyncio.wait_for(reader.readline(), 10)).decode().strip()
    writer.close()
    return line


async def test_the_proxy_refuses_everything_but_an_allowed_public_host_on_443() -> None:
    server = await asyncio.start_server(
        egress_proxy.make_handler(["registry.npmjs.org", "localhost"]), "127.0.0.1", 0
    )
    port = server.sockets[0].getsockname()[1]
    async with server:
        assert (await ask(port, b"CONNECT example.com:443 HTTP/1.1\r\n\r\n")).startswith(
            "HTTP/1.1 403"
        )
        assert (await ask(port, b"CONNECT registry.npmjs.org:80 HTTP/1.1\r\n\r\n")).startswith(
            "HTTP/1.1 403"
        )
        assert (await ask(port, b"GET http://registry.npmjs.org/ HTTP/1.1\r\n\r\n")).startswith(
            "HTTP/1.1 405"
        )
        # An allowed name that resolves to an internal address is still refused.
        assert (await ask(port, b"CONNECT localhost:443 HTTP/1.1\r\n\r\n")).startswith(
            "HTTP/1.1 403"
        )
        assert (await ask(port, b"CONNECT 127.0.0.1:443 HTTP/1.1\r\n\r\n")).startswith(
            "HTTP/1.1 403"
        )


# ---------- how the container is run (no Docker) ----------


def test_checks_have_no_network_unless_an_install_is_pointed_at_the_proxy(tmp_path: Path) -> None:
    plain = docker_command(image="i", worktree=tmp_path, command="true", container_name="c")
    assert plain[plain.index("--network") + 1] == "none"
    assert not any("PROXY" in part.upper() for part in plain)

    install = docker_command(
        image="i", worktree=tmp_path, command="true", container_name="c",
        network="hexmind-install", proxy="hexmind-egress-1",
    )  # fmt: skip
    assert install[install.index("--network") + 1] == "hexmind-install"
    assert "--env=HTTPS_PROXY=http://hexmind-egress-1:3128" in install
    for hardening in ("--read-only", "--cap-drop", "no-new-privileges", "--user"):
        assert hardening in install
    assert "registry.npmjs.org" in DEFAULT_INSTALL_HOSTS


def test_only_the_install_check_gets_the_allowlist_and_only_when_the_contract_says_so(
    tmp_path: Path,
) -> None:
    contract = {"stack": "x", "image": "node:22-alpine", "install": "npm ci", "test": "node --test"}
    for network, expected in (({}, "allowlist"), ({"network": {"install": "none"}}, "none")):
        (tmp_path / ".hex").mkdir(exist_ok=True)
        (tmp_path / ".hex" / "project.json").write_text(json.dumps({**contract, **network}))
        profile = load_profile(tmp_path, tmp_path, IMAGES)
        assert profile.network_for("install") == expected
        assert profile.network_for("test") == "none"
        assert profile.network_for("start") == "none"
    assert RunContract(stack="x").network.test == "none"


# ---------- which Dockerfiles are accepted (no Docker) ----------


def test_a_dockerfile_may_only_use_allowed_bases_and_nothing_from_the_host() -> None:
    assert check_dockerfile(DOCKERFILE, IMAGES) == ["node:22-alpine"]
    multi = "FROM node:22-alpine AS deps\nRUN true\nFROM deps\nUSER node\nCOPY --from=deps /a /b\n"
    assert check_dockerfile(multi, IMAGES) == ["node:22-alpine"]  # a stage is not a new base
    continued = "FROM node:22-alpine\nRUN echo a \\\n  && echo b\n"
    assert check_dockerfile(continued, IMAGES) == ["node:22-alpine"]

    bad = {
        "FROM ubuntu:24.04\n": "not allowed",
        "FROM node:22-alpine\nFROM evil/image\n": "'evil/image' is not allowed",
        "# syntax=evil/frontend\nFROM node:22-alpine\n": "syntax",
        "FROM node:22-alpine\nADD https://x.test/a /a\n": "ADD is not allowed",
        "FROM node:22-alpine\nCOPY . /app\n": "COPY of local files",
        "FROM node:22-alpine\nRUN --mount=type=bind,target=/x true\n": "--mount",
        "FROM node:22-alpine\nRUN --network=host true\n": "--network",
        "RUN true\n": "no FROM",
        "": "no FROM",
    }
    for text, message in bad.items():
        with pytest.raises(DockerfileError, match=message):
            check_dockerfile(text, IMAGES)
    assert image_tag(DOCKERFILE) == image_tag(DOCKERFILE) != image_tag(DOCKERFILE + "\n# x")


def test_a_missing_or_oversized_dockerfile_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(DockerfileError, match="does not exist"):
        ensure_project_image(tmp_path, IMAGES)
    (tmp_path / ".hex").mkdir()
    (tmp_path / ".hex" / "Dockerfile").write_text("FROM node:22-alpine\n" + "# x\n" * 6000)
    with pytest.raises(DockerfileError, match="larger than"):
        ensure_project_image(tmp_path, IMAGES)


# ---------- installed dependencies are not part of the work ----------


def test_installed_dependencies_are_never_committed_or_diffed(tmp_path: Path) -> None:
    root = tmp_path / "p"
    root.mkdir()
    (root / "a.js").write_text("1\n")
    git.init_repo(root)
    base = git.head(root)
    (root / "node_modules" / "x").mkdir(parents=True)
    (root / "node_modules" / "x" / "i.js").write_text("module.exports = 1\n")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "m.pyc").write_bytes(b"\0")
    (root / "src.js").write_text("2\n")

    assert [c.path for c in git.diff(root, base)] == ["src.js"]
    git.commit_all(root, "work")
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files"], capture_output=True, text=True, check=True
    ).stdout.split()
    assert "src.js" in tracked
    assert not any(f.startswith(("node_modules", "__pycache__")) for f in tracked)
    assert not git.is_dirty(root)
    git.reset_to(root, base)
    assert (root / "node_modules" / "x" / "i.js").exists()  # a reset keeps installed dependencies


def test_the_dependency_fingerprint_changes_only_when_dependency_files_do(tmp_path: Path) -> None:
    empty = dependency_fingerprint(tmp_path)
    (tmp_path / "src.js").write_text("a")
    assert dependency_fingerprint(tmp_path) == empty
    (tmp_path / "package.json").write_text("{}")
    with_package = dependency_fingerprint(tmp_path)
    assert with_package != empty
    (tmp_path / "package.json").write_text('{"dependencies": {"x": "1"}}')
    assert dependency_fingerprint(tmp_path) != with_package
    assert "package-lock.json" in DEPENDENCY_FILES


# ---------- real Docker ----------


@needs_docker
def test_the_project_image_is_built_from_the_dockerfile_once_and_a_check_runs_in_it(
    tmp_path: Path,
) -> None:
    (tmp_path / ".hex").mkdir()
    (tmp_path / ".hex" / "Dockerfile").write_text(DOCKERFILE + "# a comment only\n")

    first = ensure_project_image(tmp_path, IMAGES)
    again = ensure_project_image(tmp_path, IMAGES)

    assert first.tag == again.tag and again.built is False
    outcome = run_check(
        name="marker", command="cat /opt/tool/marker", image=first.tag, worktree=tmp_path,
        timeout_s=60,
    )  # fmt: skip
    assert (outcome.exit_code, outcome.output_tail.strip()) == (0, "built-ok")


@needs_docker
def test_the_build_has_no_network_and_a_failing_build_says_why(tmp_path: Path) -> None:
    (tmp_path / ".hex").mkdir()
    dockerfile = tmp_path / ".hex" / "Dockerfile"
    dockerfile.write_text(
        "FROM node:22-alpine\nRUN node -e \"require('net').connect(443,'1.1.1.1')"
        ".on('connect',()=>process.exit(0)).on('error',()=>process.exit(7))\"\n"
        "# no route out during the build\n"
    )
    with pytest.raises(DockerfileError, match="the image build failed"):
        ensure_project_image(tmp_path, IMAGES)

    dockerfile.write_text("FROM node:22-alpine\nRUN echo BOOM-MARKER && exit 3\n")
    with pytest.raises(DockerfileError, match="the image build failed") as caught:
        ensure_project_image(tmp_path, IMAGES)
    assert "BOOM-MARKER" in str(caught.value)


@needs_docker
def test_the_tools_build_the_project_image_for_a_contract_that_names_a_dockerfile(
    tmp_path: Path,
) -> None:
    workspace, worktree = tmp_path / "ws", tmp_path / "wt"
    for folder in (workspace, worktree):
        (folder / ".hex").mkdir(parents=True)
    (worktree / ".hex" / "Dockerfile").write_text(DOCKERFILE)
    (worktree / ".hex" / "project.json").write_text(
        json.dumps(
            {
                "stack": "x",
                "dockerfile": ".hex/Dockerfile",
                "test": "cat /opt/tool/marker",
                "typecheck": "test -x /usr/local/bin/node",
            }
        )
    )
    tools = WorkspaceTools(worktree, workspace=workspace, allowed_images=IMAGES, check_timeout_s=60)

    result = json.loads(tools.run_check("test"))
    assert (result["exit_code"], result["output_tail"].strip()) == (0, "built-ok")
    assert json.loads(tools.run_check("typecheck"))["exit_code"] == 0

    (worktree / ".hex" / "Dockerfile").write_text("FROM ubuntu:24.04\n")
    with pytest.raises(ToolError, match="project image could not be built.*not allowed"):
        tools.run_check("test")


def containers() -> list[str]:
    out = subprocess.run(
        ["docker", "ps", "-a", "--filter", "name=hexmind-egress-", "--format", "{{.Names}}"],
        capture_output=True, text=True,
    ).stdout  # fmt: skip
    return out.split()


@needs_docker
def test_an_install_can_reach_nothing_directly_and_the_proxy_only_lets_registries_through(
    tmp_path: Path,
) -> None:
    (tmp_path / "probe.js").write_text(PROBE_JS)

    def probe(mode: str, target: str, network: str) -> str:
        outcome = run_check(
            name="install", command=f"node probe.js {mode} {target}", image="node:22-alpine",
            worktree=tmp_path, timeout_s=90, network=network,  # type: ignore[arg-type]
        )  # fmt: skip
        assert outcome.exit_code == 0, outcome
        return outcome.output_tail.strip()

    # Straight to the internet: no route, even on the install network.
    assert probe("direct", "1.1.1.1:443", "allowlist").startswith(("error", "timeout"))
    # Through the proxy: an unlisted host is refused, a registry is tunnelled.
    assert probe("proxy", "example.com:443", "allowlist") == "HTTP/1.1 403 Forbidden"
    assert probe("proxy", "registry.npmjs.org:80", "allowlist") == "HTTP/1.1 403 Forbidden"
    if internet():
        assert probe("proxy", "registry.npmjs.org:443", "allowlist") == (
            "HTTP/1.1 200 Connection Established"
        )
    # A normal check has no proxy and no network at all.
    outcome = run_check(
        name="test", command="env | grep -ci proxy; true", image="node:22-alpine",
        worktree=tmp_path, timeout_s=60,
    )  # fmt: skip
    assert outcome.output_tail.strip() == "0"
    assert containers() == []  # the proxy is removed after every install


# ---------- a mission that installs ----------


@needs_docker
async def test_the_runner_installs_once_keeps_dependencies_out_of_the_work_and_reinstalls_on_change(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    contract = {
        "stack": "plain node",
        "image": "node:22-alpine",
        "install": "mkdir -p node_modules/dep && echo 'module.exports = 1' > node_modules/dep/i.js",
        "test": "node --test",
    }
    root = repo_with(tmp_path, contract)
    use_adapter(app, ScriptedAdapter(Script()))
    mission = await new_mission(client, root)

    await approve(client, mission)
    await finish(app)

    row, _, run = await load(app, mission["id"])
    assert row.status == "completed"
    async with app.state.sessionmaker() as session:
        names = [
            c.name
            for c in await session.scalars(
                select(CheckResult)
                .where(CheckResult.run_id == run.id)
                .order_by(CheckResult.created_at)
            )
        ]
        handoffs = list(await session.scalars(select(HandoffRow)))
    # Two features, one install: the dependency files did not change between them.
    assert names.count("install") == 1 and names[0] == "install" and names.count("test") == 2
    assert all(not f.startswith("node_modules") for h in handoffs for f in h.data["files_changed"])
    tracked = git_files(Path(run.worktree_path or ""), row.branch)
    assert not any(path.startswith("node_modules/") for path in tracked)
    assert (Path(run.worktree_path or "") / "node_modules" / "dep" / "i.js").exists()
    assert containers() == []


def git_files(worktree: Path, branch: str) -> list[str]:
    return subprocess.run(
        ["git", "-C", str(worktree), "ls-tree", "-r", "--name-only", branch],
        capture_output=True, text=True, check=True,
    ).stdout.split()  # fmt: skip
