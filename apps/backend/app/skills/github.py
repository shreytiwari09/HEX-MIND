"""Fetching a skill from GitHub (PRD §11.2): pinned to a commit and shown before it is enabled.

    https://github.com/owner/repo                    a skill at the repo root
    https://github.com/owner/repo/tree/<ref>/<path>  a skill in a folder
                                                     (<ref>: a branch, tag or commit)

Only public repositories on github.com, through its API (never a git clone, never code run):

  1. the ref is resolved to a **commit SHA**, so what is fetched can never change afterwards;
  2. the folder is read from that commit's tree: regular files only (no symlinks, no submodules),
     with limits on the number and size of files;
  3. the result goes through the same validation as every skill (`load_skill_folder`) and the
     injection screening, and is shown to the user as a **preview**: nothing is stored;
  4. **install** fetches the same commit again and refuses unless the content hash equals the one
     the user was shown.

A skill is text: it is never executed, and agents get it only as untrusted guidance. The skill
lives in the user's skills folder with a record of where it came from.
"""

import base64
import json
import re
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.guardrails.injection import screen
from app.skills.registry import (
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_SKILL_MD_BYTES,
    NAME_PATTERN,
    SkillError,
    load_skill_folder,
)

API = "https://api.github.com"
MAX_TOTAL_BYTES = 500_000
MAX_REQUESTS = 40
_SEGMENT = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
SOURCES_DIR = ".sources"  # inside the user skills folder; dot-folders are never read as skills


class GithubError(ValueError):
    """The skill cannot be fetched; the message says why."""


@dataclass(frozen=True)
class Source:
    owner: str
    repo: str
    ref: str | None  # None: the repository's default branch
    path: str  # folder inside the repo, "" for the root

    @property
    def url(self) -> str:
        base = f"https://github.com/{self.owner}/{self.repo}"
        return f"{base}/tree/{self.ref}/{self.path}".rstrip("/") if self.ref else base


@dataclass(frozen=True)
class Fetched:
    """A skill as fetched at one commit, validated and ready to preview or install."""

    source: Source
    commit: str
    name: str
    description: str
    body: str
    hash: str
    version: str
    files: dict[str, bytes]  # everything in the folder, SKILL.md included
    signals: tuple[str, ...] = field(default=())  # injection screening of the text


def parse_url(url: str) -> Source:
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.username:
        raise GithubError("use a https://github.com/owner/repo address")
    if parsed.port is not None or parsed.query or parsed.fragment:
        raise GithubError("use a plain https://github.com/owner/repo address")
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        raise GithubError("the address needs an owner and a repository")
    owner, repo, rest = parts[0], parts[1].removesuffix(".git"), parts[2:]
    if not (_SEGMENT.match(owner) and _SEGMENT.match(repo)):
        raise GithubError("the owner or repository name is not valid")
    if not rest:
        return Source(owner, repo, None, "")
    if rest[0] != "tree" or len(rest) < 2:
        raise GithubError("use the repository address, or a /tree/<branch>/<folder> address")
    ref, folder = rest[1], rest[2:]
    if not _SEGMENT.match(ref) or any(not _SEGMENT.match(p) or p in (".", "..") for p in folder):
        raise GithubError("the branch or folder in the address is not valid")
    return Source(owner, repo, ref, "/".join(folder))


class GithubClient:
    """The few read-only calls to the GitHub API that a skill needs (no token, public repos)."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(
            base_url=API,
            transport=transport,
            timeout=20,
            follow_redirects=False,  # a moved repository must be asked for again, explicitly
            trust_env=False,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "hexmind",
            },
        )
        self._requests = 0

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str) -> dict:  # type: ignore[type-arg]
        self._requests += 1
        if self._requests > MAX_REQUESTS:
            raise GithubError("the skill has too many files to fetch")
        try:
            response = await self._client.get(path)
        except httpx.HTTPError as exc:
            raise GithubError(f"could not reach GitHub: {type(exc).__name__}") from None
        if response.status_code == 200:
            return response.json()  # type: ignore[no-any-return]
        if response.status_code in (301, 302, 307, 308):
            raise GithubError("the repository has moved: use its new address")
        if response.status_code == 404:
            raise GithubError("not found (only public repositories can be used)")
        if response.status_code in (403, 429):
            raise GithubError("GitHub's rate limit was reached; try again in a few minutes")
        raise GithubError(f"GitHub answered {response.status_code}")

    async def commit_of(self, source: Source) -> str:
        ref = source.ref
        if ref is None:
            ref = (await self._get(f"/repos/{source.owner}/{source.repo}"))["default_branch"]
        sha = (await self._get(f"/repos/{source.owner}/{source.repo}/commits/{ref}"))["sha"]
        if not _SHA.match(str(sha)):
            raise GithubError("GitHub did not return a commit")
        return str(sha)

    async def folder(self, source: Source, commit: str) -> dict[str, bytes]:
        """The files directly or deeply under `source.path` at `commit`, keyed by their path
        relative to that folder. Regular files only."""
        tree = await self._get(
            f"/repos/{source.owner}/{source.repo}/git/trees/{commit}?recursive=1"
        )
        if tree.get("truncated"):
            raise GithubError("the repository is too large to read a folder from")
        prefix = f"{source.path}/" if source.path else ""
        chosen: list[tuple[str, str, int]] = []
        total = 0
        for entry in tree.get("tree", []):
            path = str(entry.get("path", ""))
            if not path.startswith(prefix) or entry.get("type") != "blob":
                continue
            if entry.get("mode") not in ("100644", "100755"):
                continue  # symlinks and submodules are never followed
            rel = path[len(prefix) :]
            if not rel or any(p in ("", ".", "..") or p.startswith(".git") for p in rel.split("/")):
                continue
            size = int(entry.get("size", 0))
            if rel != "SKILL.md" and size > MAX_FILE_BYTES:
                continue  # too large to ever be shown: not part of the skill (like on disk)
            if rel == "SKILL.md" and size > MAX_SKILL_MD_BYTES:
                raise GithubError(f"SKILL.md is larger than {MAX_SKILL_MD_BYTES // 1000} KB")
            chosen.append((rel, str(entry["sha"]), size))
            total += size
        if not any(rel == "SKILL.md" for rel, _, _ in chosen):
            where = f"in {source.path}" if source.path else "at the top of the repository"
            raise GithubError(f"there is no SKILL.md {where}")
        if len(chosen) > MAX_FILES + 1 or total > MAX_TOTAL_BYTES:
            raise GithubError(
                f"the folder has more than {MAX_FILES} files or {MAX_TOTAL_BYTES // 1000} KB"
            )
        files: dict[str, bytes] = {}
        for rel, sha, size in chosen:
            blob = await self._get(f"/repos/{source.owner}/{source.repo}/git/blobs/{sha}")
            if blob.get("encoding") != "base64":
                raise GithubError(f"{rel} could not be read")
            data = base64.b64decode(blob.get("content", ""))
            if len(data) != size:
                raise GithubError(f"{rel} did not match its size")
            files[rel] = data
        return files


def validate(source: Source, commit: str, files: dict[str, bytes]) -> Fetched:
    """Check the fetched files as a skill, with the same rules as one on disk."""
    try:
        text = files["SKILL.md"].decode("utf-8")
    except UnicodeDecodeError:
        raise GithubError("SKILL.md is not UTF-8 text") from None
    match = re.search(r"(?m)^name:\s*(\S+)\s*$", text.split("\n---", 2)[0])
    name = match.group(1) if match else ""
    if not NAME_PATTERN.match(name):
        raise GithubError("SKILL.md needs front matter with a name (lowercase letters and dashes)")
    with tempfile.TemporaryDirectory(prefix="hexmind-skill-") as tmp:
        folder = Path(tmp) / name
        write_files(folder, files)
        try:
            skill = load_skill_folder(folder, "user")
        except SkillError as exc:
            raise GithubError(str(exc)) from None
    readable = "\n".join(
        data.decode("utf-8", "replace") for rel, data in files.items() if _is_text(data)
    )
    return Fetched(
        source=source,
        commit=commit,
        name=skill.name,
        description=skill.description,
        body=skill.body,
        hash=skill.hash,
        version=skill.version,
        files=files,
        signals=screen(readable).signals,
    )


def _is_text(data: bytes) -> bool:
    return b"\x00" not in data[:4096]


def write_files(folder: Path, files: dict[str, bytes]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    root = folder.resolve()
    for rel, data in files.items():
        target = (folder / rel).resolve()
        if not target.is_relative_to(root):  # a path that climbs out is never written
            raise GithubError(f"'{rel}' is outside the skill folder")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


async def fetch(client: GithubClient, url: str, commit: str | None = None) -> Fetched:
    """The skill at `url`, at `commit` if given (else the ref's current commit)."""
    source = parse_url(url)
    if commit is not None and not _SHA.match(commit):
        raise GithubError("the commit must be a full 40-character SHA")
    pinned = commit or await client.commit_of(source)
    return validate(source, pinned, await client.folder(source, pinned))


def install(user_dir: Path, fetched: Fetched, *, replace: bool) -> Path:
    """Write the skill into the user's skills folder and record where it came from."""
    target = user_dir / fetched.name
    if target.exists() and not replace:
        raise GithubError(f"you already have a skill named '{fetched.name}'")
    staging = user_dir / f".installing-{fetched.name}"
    if staging.exists():
        _remove(staging)
    write_files(staging, fetched.files)
    if target.exists():
        _remove(target)
    staging.rename(target)
    sources = user_dir / SOURCES_DIR
    sources.mkdir(parents=True, exist_ok=True)
    (sources / f"{fetched.name}.json").write_text(
        json.dumps(
            {
                "url": fetched.source.url,
                "owner": fetched.source.owner,
                "repo": fetched.source.repo,
                "path": fetched.source.path,
                "commit": fetched.commit,
                "hash": fetched.hash,
                "installed_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
        )
    )
    return target


def origin_of(user_dir: Path, name: str) -> dict[str, str] | None:
    """Where an installed skill came from (None for a skill the user wrote or dropped in)."""
    path = user_dir / SOURCES_DIR / f"{name}.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return {k: str(data[k]) for k in ("url", "commit", "installed_at") if k in data}


def remove(user_dir: Path, name: str) -> None:
    folder = user_dir / name
    if not folder.is_dir():
        raise GithubError(f"you have no skill named '{name}'")
    _remove(folder)
    (user_dir / SOURCES_DIR / f"{name}.json").unlink(missing_ok=True)


def _remove(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)
