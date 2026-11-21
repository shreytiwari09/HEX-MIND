"""Run profile checks in a locked-down Docker container (plan §7).

Generated code is untrusted: no network (except an `install` check, which may only reach
package registries through an allowlist proxy), CPU/memory/PID/time limits, read-only root
filesystem, all capabilities dropped, non-root user, only the worktree mounted. If Docker is
unavailable the check fails; it never falls back to running on the host.

Blocking (subprocess) so it works under any event loop; call it from a thread pool.
"""

import re
import subprocess
import time
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

OUTPUT_TAIL_CHARS = 4000
NetworkMode = Literal["none", "allowlist"]
# Where installs may reach: package registries only (PRD §12.7).
DEFAULT_INSTALL_HOSTS = (
    "registry.npmjs.org",
    "registry.yarnpkg.com",
    "pypi.org",
    "files.pythonhosted.org",
    "index.crates.io",
    "static.crates.io",
    "proxy.golang.org",
    "sum.golang.org",
)
INSTALL_NETWORK = "hexmind-install"  # a Docker --internal network: no route out
# Installs (npm, pip) download and build: a Python app with Streamlit took longer than the 120 s
# every other check gets (live run, D77).
INSTALL_TIMEOUT_S = 600
ACCEPTANCE_TESTS = "tests/acceptance"  # QA's tests (PRD §8.5)


def timeout_for(name: str, default_s: int) -> int:
    return max(default_s, INSTALL_TIMEOUT_S) if name == "install" else default_s


TAG_PREFIX = "hexmind-project"  # images built from a project's .hex/Dockerfile
PROXY_IMAGE = "python:3.11-slim"
PROXY_PORT = 3128
PROXY_SCRIPT = Path(__file__).with_name("egress_proxy.py")


@dataclass(frozen=True)
class CheckOutcome:
    name: str
    exit_code: int | None  # None: did not run to completion (timeout / sandbox error)
    duration_ms: int
    output_tail: str
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


def hardening_flags(*, memory: str, pids: str, tmp_size: str = "256m") -> list[str]:
    """What every sandbox container gets, for checks and for plugins alike: resource limits, a
    read-only root filesystem, no capabilities, no privilege escalation, a non-root user."""
    return [
        "--cpus", "1",
        "--memory", memory,
        "--pids-limit", pids,
        "--read-only",
        "--tmpfs", f"/tmp:rw,size={tmp_size}",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--user", "1000:1000",
        "--env", "HOME=/tmp",
    ]  # fmt: skip


def plugin_command(
    *,
    image: str,
    command: str,
    container_name: str,
    worktree: Path | None,
    writable: bool,
    network: str = "none",
    proxy: str | None = None,
) -> list[str]:
    """A plugin's MCP server as a stdio process in the sandbox: `docker run -i`, the same
    hardening as a check, the worktree mounted only when the plugin was configured to see it
    (read-only unless it may write), and no network except through the allowlist proxy."""
    proxy_env = (
        [f"--env={name}=http://{proxy}:{PROXY_PORT}" for name in _PROXY_ENV] if proxy else []
    )
    mount = (
        ["--mount", f"type=bind,source={worktree.resolve()},target=/work"
         + ("" if writable else ",readonly"), "--workdir", "/work"]
        if worktree is not None
        else ["--workdir", "/tmp"]
    )  # fmt: skip
    return [
        "docker", "run", "-i", "--rm",
        "--name", container_name,
        "--network", network,
        *hardening_flags(memory="512m", pids="128"),
        *proxy_env,
        *mount,
        image,
        "sh", "-c", command,
    ]  # fmt: skip


def docker_command(
    *,
    image: str,
    worktree: Path,
    command: str,
    container_name: str,
    network: str = "none",
    proxy: str | None = None,
    hide: Sequence[str] = (),
) -> list[str]:
    """`network` is "none" or the name of the internal network whose only way out is `proxy`
    (the name of the proxy container), which the tools in the container are pointed at.
    `hide`: folders (relative to the worktree) covered by an empty one for this run."""
    proxy_env = (
        [f"--env={name}=http://{proxy}:{PROXY_PORT}" for name in _PROXY_ENV] if proxy else []
    )
    hidden = [
        flag
        for rel in hide
        for flag in ("--mount", f"type=tmpfs,target=/work/{rel.strip('/')},tmpfs-size=1m")
    ]
    return [
        "docker", "run", "--rm",
        "--name", container_name,
        "--network", network,
        *hardening_flags(memory="1g", pids="256"),
        "--env", "CI=1",
        *proxy_env,
        "--mount", f"type=bind,source={worktree.resolve()},target=/work",
        *hidden,
        "--workdir", "/work",
        image,
        "sh", "-c", command,
    ]  # fmt: skip


_PROXY_ENV = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")


@contextmanager
def egress_proxy(hosts: Sequence[str]) -> Iterator[str]:
    """Start the allowlist proxy and yield its container name. It is on the default network (so
    it can reach out) and on the internal install network (so the install container can reach
    it); nothing else can. Removed on exit."""
    subprocess.run(
        ["docker", "network", "create", "--internal", INSTALL_NETWORK],
        capture_output=True,
        timeout=30,
    )  # fmt: skip  (already existing is fine)
    ensure_image(PROXY_IMAGE)
    name = f"hexmind-egress-{uuid.uuid4().hex[:12]}"
    started = subprocess.run(
        [
            "docker", "run", "-d", "--rm", "--name", name,
            "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", "1000:1000", "--memory", "128m", "--pids-limit", "64",
            "--env", f"ALLOW_HOSTS={','.join(hosts)}", "--env", f"PORT={PROXY_PORT}",
            "--mount", f"type=bind,source={PROXY_SCRIPT},target=/egress_proxy.py,readonly",
            PROXY_IMAGE, "python", "/egress_proxy.py",
        ],
        capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    if started.returncode != 0:
        raise OSError(f"could not start the egress proxy: {started.stderr.strip()[:300]}")
    try:
        subprocess.run(
            ["docker", "network", "connect", INSTALL_NETWORK, name],
            capture_output=True, check=True, timeout=30,
        )  # fmt: skip
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            logs = subprocess.run(["docker", "logs", name], capture_output=True, text=True)
            if "listening" in logs.stdout + logs.stderr:
                break
            time.sleep(0.2)
        else:
            raise OSError("the egress proxy did not start")
        yield name
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=30)


def docker_available() -> tuple[bool, str | None]:
    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True, text=True, timeout=15,
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, result.stderr.strip()[:300] or "docker daemon not reachable"
    return True, None


def ensure_image(image: str) -> None:
    """Pull an allowlisted image if it is not present (outside the sandbox, with network)."""
    present = subprocess.run(
        ["docker", "image", "inspect", image], capture_output=True, timeout=30
    ).returncode == 0  # fmt: skip
    if not present:
        subprocess.run(
            ["docker", "pull", "-q", image], capture_output=True, check=True, timeout=600
        )


def run_check(
    *,
    name: str,
    command: str,
    image: str,
    worktree: Path,
    timeout_s: int,
    network: NetworkMode = "none",
    allow_hosts: Sequence[str] = DEFAULT_INSTALL_HOSTS,
) -> CheckOutcome:
    """Run `command` in the sandbox. `network` is "none" (the default, and always for test and
    start) or "allowlist" (installs: package registries only, through the egress proxy).

    The `test` check runs without QA's acceptance tests (an empty folder covers
    `tests/acceptance`): QA writes them for the whole milestone before its features exist, so a
    plain `pytest` or `node --test` in an early feature would run tests of later ones and could
    never pass (live run, D77). They are run by the `acceptance` check."""
    hide = (ACCEPTANCE_TESTS,) if name == "test" and (worktree / ACCEPTANCE_TESTS).is_dir() else ()
    available, reason = docker_available()
    if not available:
        return CheckOutcome(name, None, 0, "", error=f"sandbox unavailable: {reason}")
    if not image.startswith(f"{TAG_PREFIX}:"):  # a project image is built locally, never pulled
        try:
            ensure_image(image)
        except (subprocess.SubprocessError, OSError) as exc:
            return CheckOutcome(name, None, 0, "", error=f"could not pull {image}: {exc}")

    container = f"hexmind-check-{uuid.uuid4().hex[:12]}"
    started = time.perf_counter()
    try:
        if network == "allowlist":
            with egress_proxy(allow_hosts) as proxy:
                return _run(
                    name,
                    docker_command(
                        image=image, worktree=worktree, command=command,
                        container_name=container, network=INSTALL_NETWORK, proxy=proxy, hide=hide,
                    ),
                    container, timeout_s, started,
                )  # fmt: skip
        argv = docker_command(
            image=image, worktree=worktree, command=command, container_name=container, hide=hide
        )
        return _run(name, argv, container, timeout_s, started)
    except (subprocess.SubprocessError, OSError) as exc:
        return CheckOutcome(name, None, _ms(started), "", error=f"sandbox error: {exc}")


def _run(
    name: str, argv: list[str], container: str, timeout_s: int, started: float
) -> CheckOutcome:
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout_s,
        )  # fmt: skip
    except subprocess.TimeoutExpired as exc:
        subprocess.run(["docker", "kill", container], capture_output=True, timeout=30)
        # On a timeout subprocess hands back the partial output as bytes even with text=True,
        # and stdout and stderr may differ in type: decode each before joining (live run, D77).
        output = "".join(
            part.decode("utf-8", "replace") if isinstance(part, bytes) else part
            for part in (exc.stdout or "", exc.stderr or "")
        )
        return CheckOutcome(
            name, None, _ms(started), output[-OUTPUT_TAIL_CHARS:],
            error=f"timed out after {timeout_s}s",
        )  # fmt: skip
    output = (result.stdout + result.stderr)[-OUTPUT_TAIL_CHARS:]
    return CheckOutcome(name, result.returncode, _ms(started), output)


def _ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


# Test runners that found nothing to run: node's TAP ("# tests 0") and spec ("ℹ tests 0")
# reporters, Python's unittest ("Ran 0 tests").
# ... and pytest ("no tests ran", exit 5; "collected 0 items").
_NO_TESTS = re.compile(
    r"(?m)^(?:\S+\s+)?tests 0\s*$|\bRan 0 tests\b|\bno tests ran\b|\bcollected 0 items\b"
)
NO_TESTS_HINT = (
    "ran NO tests: add at least one real test file that the test command finds "
    "(pytest: tests/test_*.py; node: *.test.js)"
)


# What a test runner prints after running at least one test: node's TAP and spec reporters
# ("# tests 3", "ℹ tests 6"), "N passed" (pytest, jest, vitest, cargo), "N passing" (mocha),
# unittest ("Ran 2 tests"), rspec ("3 examples, 0 failures"), phpunit ("OK (3 tests"), and go's
# per-package "ok  pkg  0.01s" (not "ok  pkg  [no test files]").
_TESTS_RAN = re.compile(
    r"(?m)^(?:\S+\s+)?tests [1-9]\d*\s*$"
    r"|\b[1-9]\d* (?:passed|passing)\b"
    r"|\bRan [1-9]\d* tests?\b"
    r"|\b[1-9]\d* examples?, 0 failures\b"
    r"|\bOK \([1-9]\d* tests?\b"
    r"|^ok\s+\S+\s+\(?[\d.]+m?s\)?\s*$"
)


def ran_no_tests(check: CheckOutcome) -> bool:
    return bool(_NO_TESTS.search(check.output_tail))


def shows_tests_ran(check: CheckOutcome) -> bool:
    return bool(_TESTS_RAN.search(check.output_tail))


def accepted(check: CheckOutcome) -> bool:
    """A check counts only if it passed *and* its output shows tests running. Exit 0 alone
    proves nothing: `node --test` succeeds in an empty project, and a builder once set the test
    command to `echo "test passed"`, which can never fail (live run, PRD D68)."""
    return check.passed and not ran_no_tests(check) and shows_tests_ran(check)


def check_summary(check: CheckOutcome | None) -> str:
    if check is None:
        return "not run"
    if check.exit_code is None:
        return f"{check.name}: did not complete ({check.error})"
    if ran_no_tests(check):
        code = "exited 0" if check.passed else f"exited {check.exit_code}"
        status = f"{code} and {NO_TESTS_HINT}"
    elif check.passed and not shows_tests_ran(check):
        status = (
            "exited 0 but its output shows NO tests running: the test command must run a real "
            "test runner (for example `node --test`) on real tests; `echo` or `true` prove nothing"
        )
    else:
        status = "passed" if check.passed else f"FAILED (exit {check.exit_code})"
    return f"{check.name}: {status}\n{check.output_tail[-1500:]}"


def check_feedback(check: CheckOutcome) -> str:
    return f"The `{check.name}` check is failing:\n{check_summary(check)}"
