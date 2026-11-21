"""The skill registry (PRD §11.2, §11.3): skills are folders with a `SKILL.md`.

    my-skill/
      SKILL.md            front matter (name, description), then the instructions
      examples/a.md       optional files the instructions point to

Sources: built-in skills shipped with H.E.X (`skills/builtin/`) and the user's skills folder
(`<data dir>/skills/`). A user skill with the same name as a built-in one replaces it. Each
skill is hashed (SKILL.md and its files), so the exact version an agent was given can be
recorded.

Skills are **untrusted text**: they are only ever shown to a model as guidance (never run), they
cannot grant tools or change permissions, and what they say is bounded by size limits here.
"""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

BUILTIN_DIR = Path(__file__).parent / "builtin"
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
# Raised from 20 KB (D70): popular Claude/Codex skills (e.g. `unslop`) are about 32 KB.
MAX_SKILL_MD_BYTES = 50_000
MAX_FILE_BYTES = 50_000
MAX_FILES = 20
MAX_DESCRIPTION = 200
_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


class SkillError(ValueError):
    """A skill is missing or invalid; the message says what to fix."""


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    source: str  # "builtin" | "user"
    hash: str  # sha256 over SKILL.md and the extra files
    folder: Path
    files: tuple[str, ...] = field(default=())  # extra files, relative to the folder

    @property
    def version(self) -> str:
        return f"{self.name}@{self.hash[:12]}"


def _extra_files(folder: Path) -> list[Path]:
    found = [
        p
        for p in sorted(folder.rglob("*"))
        if p.is_file() and not p.is_symlink() and p.name != "SKILL.md"
    ]
    return found[:MAX_FILES]


def load_skill_folder(folder: Path, source: str) -> Skill:
    """Read and validate one skill folder; raises SkillError."""
    path = folder / "SKILL.md"
    if not path.is_file() or path.is_symlink():
        raise SkillError(f"{folder.name}: there is no SKILL.md")
    if path.stat().st_size > MAX_SKILL_MD_BYTES:
        raise SkillError(f"{folder.name}: SKILL.md is larger than {MAX_SKILL_MD_BYTES // 1000} KB")
    text = path.read_text(encoding="utf-8")
    match = _FRONT_MATTER.match(text)
    if match is None:
        raise SkillError(f"{folder.name}: SKILL.md must start with front matter (--- ... ---)")
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        raise SkillError(f"{folder.name}: the front matter is not valid YAML") from None
    name, description = meta.get("name"), meta.get("description")
    if not isinstance(name, str) or not NAME_PATTERN.match(name):
        raise SkillError(f"{folder.name}: name must be lowercase letters, digits and dashes")
    if name != folder.name:
        raise SkillError(f"{folder.name}: the name '{name}' must match the folder name")
    if not isinstance(description, str) or not description.strip():
        raise SkillError(f"{name}: a description is required")
    description = " ".join(description.split())
    if len(description) > MAX_DESCRIPTION:
        raise SkillError(f"{name}: the description is longer than {MAX_DESCRIPTION} characters")
    body = match.group(2).strip()
    if not body:
        raise SkillError(f"{name}: the instructions are empty")

    digest = hashlib.sha256(text.encode("utf-8"))
    extras: list[str] = []
    for extra in _extra_files(folder):
        if extra.stat().st_size > MAX_FILE_BYTES:
            continue  # too large to ever be shown, so it is not part of the skill
        rel = extra.relative_to(folder).as_posix()
        extras.append(rel)
        digest.update(b"\0" + rel.encode() + b"\0" + extra.read_bytes())
    return Skill(name, description, body, source, digest.hexdigest(), folder, tuple(extras))


def _scan(root: Path, source: str) -> tuple[dict[str, Skill], dict[str, str]]:
    skills: dict[str, Skill] = {}
    problems: dict[str, str] = {}
    if not root.is_dir():
        return skills, problems
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        try:
            skills[folder.name] = load_skill_folder(folder, source)
        except SkillError as exc:
            problems[folder.name] = str(exc)
    return skills, problems


class SkillRegistry:
    """Every skill available now, read fresh from disk so edits apply to the next job."""

    def __init__(self, user_dir: Path | None = None, builtin_dir: Path = BUILTIN_DIR) -> None:
        self.user_dir = user_dir
        self.builtin_dir = builtin_dir

    def load(self) -> tuple[dict[str, Skill], dict[str, str]]:
        """(skills by name, problems by folder name). Skills that fail validation are reported,
        never silently dropped, and never offered to an agent."""
        skills, problems = _scan(self.builtin_dir, "builtin")
        if self.user_dir is not None:
            user, user_problems = _scan(self.user_dir, "user")
            skills.update(user)
            problems.update(user_problems)
        return skills, problems

    def all(self) -> dict[str, Skill]:
        return self.load()[0]

    def get(self, name: str) -> Skill:
        skills = self.all()
        if name not in skills:
            raise SkillError(f"no skill named '{name}'")
        return skills[name]

    def resolve(self, names: list[str]) -> tuple[list[Skill], list[str]]:
        """The skills among `names` that exist (in order, without duplicates) and the names
        that do not."""
        skills = self.all()
        found: list[Skill] = []
        missing: list[str] = []
        for name in dict.fromkeys(names):
            (found.append(skills[name]) if name in skills else missing.append(name))
        return found, missing


def read_skill_file(skill: Skill, rel: str) -> str:
    """One of a skill's extra files, for `load_skill(name, file)`. Only files that are part of the
    skill (listed, inside its folder) can be read."""
    if rel not in skill.files:
        listed = ", ".join(skill.files) or "none"
        raise SkillError(f"'{rel}' is not a file of skill '{skill.name}' (files: {listed})")
    path = (skill.folder / rel).resolve()
    if not path.is_relative_to(skill.folder.resolve()) or path.is_symlink():
        raise SkillError(f"'{rel}' is outside the skill folder")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        raise SkillError(f"'{rel}' is not a UTF-8 text file") from None


def skill_index(skills: list[Skill]) -> str:
    """One line per skill, for an agent's prompt."""
    return "\n".join(f"- {s.name}: {s.description}" for s in skills)
