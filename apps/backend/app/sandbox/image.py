"""A project's sandbox image, built from its `.hex/Dockerfile` (PRD §9.6, §12.7).

The Dockerfile is written by an agent, so it is untrusted. It is checked before any build and
built with these limits:

  * every `FROM` must be an allow-listed image (or an earlier stage of the same file), so a
    project cannot pull in an arbitrary base;
  * the build context holds only the Dockerfile: nothing from the user's project or the host is
    reachable, so `COPY`/`ADD` of local files is refused;
  * no network during the build (`--network none`): packages come from the allow-listed base
    image or from the `install` check, which runs through the allowlist proxy;
  * no `# syntax=` directive (it would fetch a build frontend image) and no `RUN --mount` or
    `RUN --network` flags;
  * a size limit and a build timeout.

Images are tagged by the content hash of the Dockerfile, so an unchanged file is never rebuilt.
Blocking (subprocess), like the rest of the sandbox: call it from a thread pool.
"""

import hashlib
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.sandbox.contract import DOCKERFILE_PATH
from app.sandbox.runner import TAG_PREFIX, docker_available, ensure_image

MAX_DOCKERFILE_BYTES = 20_000
BUILD_TIMEOUT_S = 600
_FROM = re.compile(r"^FROM\s+(?:--\S+\s+)*(?P<image>\S+)(?:\s+AS\s+(?P<stage>\S+))?\s*$", re.I)


class DockerfileError(ValueError):
    """The Dockerfile is missing or not allowed; the message says what to change."""


@dataclass(frozen=True)
class ProjectImage:
    tag: str
    built: bool  # False when the cached image was used


def _instructions(text: str) -> list[str]:
    """Logical instructions: comments dropped and `\\` continuations joined."""
    logical: list[str] = []
    current = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not current and (not line or line.startswith("#")):
            continue
        if current and line.startswith("#"):
            continue
        if line.endswith("\\"):
            current += line[:-1].strip() + " "
            continue
        logical.append((current + line).strip())
        current = ""
    if current.strip():
        logical.append(current.strip())
    return logical


def check_dockerfile(text: str, allowed_images: list[str]) -> list[str]:
    """The base images the Dockerfile uses; raises DockerfileError if anything is not allowed."""
    if re.search(r"(?im)^\s*#\s*syntax\s*=", text):
        raise DockerfileError("a `# syntax=` directive is not allowed (it fetches an image)")
    stages: set[str] = set()
    bases: list[str] = []
    for instruction in _instructions(text):
        keyword = instruction.split(None, 1)[0].upper()
        if keyword == "FROM":
            match = _FROM.match(instruction)
            if match is None:
                raise DockerfileError(f"cannot read this line: {instruction[:80]}")
            image = match["image"]
            if image.lower() not in stages:
                if image not in allowed_images:
                    raise DockerfileError(
                        f"base image '{image}' is not allowed; allowed: {', '.join(allowed_images)}"
                    )
                bases.append(image)
            if match["stage"]:
                stages.add(match["stage"].lower())
        elif keyword == "ADD":
            raise DockerfileError("ADD is not allowed: the build has no project files or network")
        elif keyword == "COPY" and not re.search(r"--from=", instruction, re.I):
            raise DockerfileError(
                "COPY of local files is not allowed: the build context holds only the Dockerfile"
            )
        elif keyword == "RUN" and re.search(r"--(?:mount|network|security)\b", instruction):
            raise DockerfileError("RUN --mount, --network and --security are not allowed")
    if not bases:
        raise DockerfileError("the Dockerfile has no FROM line")
    return bases


def image_tag(text: str) -> str:
    return f"{TAG_PREFIX}:{hashlib.sha256(text.encode()).hexdigest()[:16]}"


def ensure_project_image(
    worktree: Path, allowed_images: list[str], *, timeout_s: int = BUILD_TIMEOUT_S
) -> ProjectImage:
    """Build (or find) the image for `.hex/Dockerfile` in `worktree`. Raises DockerfileError for
    a missing or disallowed file, and for a build that fails, with the end of the build output."""
    path = worktree / DOCKERFILE_PATH
    if not path.is_file() or path.is_symlink():
        raise DockerfileError(f"{DOCKERFILE_PATH} does not exist")
    if path.stat().st_size > MAX_DOCKERFILE_BYTES:
        raise DockerfileError(f"{DOCKERFILE_PATH} is larger than {MAX_DOCKERFILE_BYTES // 1000} KB")
    text = path.read_text(encoding="utf-8", errors="replace")
    bases = check_dockerfile(text, allowed_images)
    available, reason = docker_available()
    if not available:
        raise DockerfileError(f"sandbox unavailable: {reason}")

    tag = image_tag(text)
    cached = subprocess.run(["docker", "image", "inspect", tag], capture_output=True, timeout=30)
    if cached.returncode == 0:
        return ProjectImage(tag, built=False)
    try:
        for base in bases:
            ensure_image(base)
        with tempfile.TemporaryDirectory(prefix="hexmind-build-") as context:
            (Path(context) / "Dockerfile").write_text(text, encoding="utf-8")
            result = subprocess.run(
                ["docker", "build", "--network", "none", "--memory", "2g", "-q", "-t", tag]
                + [context],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=timeout_s,
            )  # fmt: skip
    except subprocess.TimeoutExpired:
        raise DockerfileError(f"the image build timed out after {timeout_s}s") from None
    except (subprocess.SubprocessError, OSError) as exc:
        raise DockerfileError(f"could not build the image: {exc}") from None
    if result.returncode != 0:
        tail = (result.stderr or result.stdout).strip()[-1500:]
        raise DockerfileError(f"the image build failed:\n{tail}")
    return ProjectImage(tag, built=True)
