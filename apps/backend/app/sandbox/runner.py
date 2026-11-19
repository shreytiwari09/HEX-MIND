"""Run profile checks in a locked-down Docker container (plan §7).

Generated code is untrusted: no network, CPU/memory/PID/time limits, read-only root
filesystem, all capabilities dropped, non-root user, only the worktree mounted. If Docker is
unavailable the check fails; it never falls back to running on the host.

Blocking (subprocess) so it works under any event loop; call it from a thread pool.
"""

import re
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

OUTPUT_TAIL_CHARS = 4000


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


def docker_command(*, image: str, worktree: Path, command: str, container_name: str) -> list[str]:
    return [
        "docker", "run", "--rm",
        "--name", container_name,
        "--network", "none",
        "--cpus", "1",
        "--memory", "1g",
        "--pids-limit", "256",
        "--read-only",
        "--tmpfs", "/tmp:rw,size=256m",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--user", "1000:1000",
        "--env", "HOME=/tmp",
        "--env", "CI=1",
        "--mount", f"type=bind,source={worktree.resolve()},target=/work",
        "--workdir", "/work",
        image,
        "sh", "-c", command,
    ]  # fmt: skip


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
    *, name: str, command: str, image: str, worktree: Path, timeout_s: int
) -> CheckOutcome:
    available, reason = docker_available()
    if not available:
        return CheckOutcome(name, None, 0, "", error=f"sandbox unavailable: {reason}")
    try:
        ensure_image(image)
    except (subprocess.SubprocessError, OSError) as exc:
        return CheckOutcome(name, None, 0, "", error=f"could not pull {image}: {exc}")

    container = f"hexmind-check-{uuid.uuid4().hex[:12]}"
    argv = docker_command(image=image, worktree=worktree, command=command, container_name=container)
    started = time.perf_counter()
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout_s,
        )  # fmt: skip
    except subprocess.TimeoutExpired as exc:
        subprocess.run(["docker", "kill", container], capture_output=True, timeout=30)
        output = (exc.stdout or "") + (exc.stderr or "")
        if isinstance(output, bytes):
            output = output.decode("utf-8", "replace")
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
_NO_TESTS = re.compile(r"(?m)^(?:\S+\s+)?tests 0\s*$|\bRan 0 tests\b")


def ran_no_tests(check: CheckOutcome) -> bool:
    return bool(_NO_TESTS.search(check.output_tail))


def accepted(check: CheckOutcome) -> bool:
    """A check counts only if it passed *and* actually ran tests; exit 0 with no tests proves
    nothing (`node --test` succeeds in an empty project)."""
    return check.passed and not ran_no_tests(check)


def check_summary(check: CheckOutcome | None) -> str:
    if check is None:
        return "not run"
    if check.exit_code is None:
        return f"{check.name}: did not complete ({check.error})"
    if check.passed and ran_no_tests(check):
        status = "exited 0 but ran NO tests (add *.test.js files using node:test)"
    else:
        status = "passed" if check.passed else f"FAILED (exit {check.exit_code})"
    return f"{check.name}: {status}\n{check.output_tail[-1500:]}"


def check_feedback(check: CheckOutcome) -> str:
    return f"The `{check.name}` check is failing:\n{check_summary(check)}"
