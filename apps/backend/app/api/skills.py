"""The skill registry (PRD §11.2): what skills exist, where they come from, and who has them."""

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.agents.persona import all_personas
from app.api.deps import SettingsDep
from app.skills import github
from app.skills.registry import NAME_PATTERN, SkillRegistry

router = APIRouter(prefix="/skills", tags=["skills"])


class SkillOut(BaseModel):
    name: str
    description: str
    source: str  # builtin | user
    version: str  # name@<hash prefix>: recorded on every handoff
    files: list[str]
    personas: list[str]  # personas that list it
    # Where an installed skill came from: {url, commit, installed_at}; None if you wrote it.
    origin: dict[str, str] | None = None


class SkillsOut(BaseModel):
    skills: list[SkillOut]
    # Skill folders that failed validation, with the reason; they are never offered to agents.
    problems: dict[str, str]


@router.get("", response_model=SkillsOut)
async def list_skills(settings: SettingsDep) -> SkillsOut:
    user_dir = settings.data_dir / "skills"
    skills, problems = SkillRegistry(user_dir).load()
    owners: dict[str, list[str]] = {}
    for persona in all_personas().values():
        for name in persona.skills:
            owners.setdefault(name, []).append(persona.id)
    return SkillsOut(
        skills=[
            SkillOut(
                name=s.name,
                description=s.description,
                source=s.source,
                version=s.version,
                files=list(s.files),
                personas=owners.get(s.name, []),
                origin=github.origin_of(user_dir, s.name) if s.source == "user" else None,
            )
            for s in skills.values()
        ],
        problems=problems,
    )


class SkillDetail(SkillOut):
    body: str  # the instructions, exactly what an agent loads


@router.get("/{name}", response_model=SkillDetail)
async def get_skill(name: str, settings: SettingsDep) -> SkillDetail:
    user_dir = settings.data_dir / "skills"
    skills = SkillRegistry(user_dir).all()
    skill = skills.get(name)
    if skill is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "skill not found")
    return SkillDetail(
        name=skill.name,
        description=skill.description,
        source=skill.source,
        version=skill.version,
        files=list(skill.files),
        personas=sorted(p.id for p in all_personas().values() if name in p.skills),
        origin=github.origin_of(user_dir, name) if skill.source == "user" else None,
        body=skill.body,
    )


# ---------- skills from GitHub (PRD §11.2) ----------


class GithubUrl(BaseModel):
    url: str = Field(min_length=10, max_length=300)


class GithubInstall(GithubUrl):
    commit: str  # the commit the preview showed
    hash: str  # the content hash the preview showed
    replace: bool = False


class PreviewOut(BaseModel):
    name: str
    description: str
    body: str  # the full instructions, exactly what an agent would load
    files: list[str]
    version: str
    hash: str
    url: str
    commit: str  # the skill is pinned to this commit
    # Why the text may be trying to steer an AI (empty if nothing was found).
    signals: list[str]
    # "user" or "builtin" if a skill with this name exists: installing replaces/overrides it.
    exists: str | None
    # Roughly what loading the skill adds to an agent's request (4 characters a token).
    approx_tokens: int


async def _fetch(request: Request, url: str, commit: str | None = None) -> github.Fetched:
    client = github.GithubClient(getattr(request.app.state, "github_transport", None))
    try:
        return await github.fetch(client, url, commit)
    except github.GithubError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    finally:
        await client.aclose()


@router.post("/github/preview", response_model=PreviewOut)
async def preview_github_skill(
    body: GithubUrl, request: Request, settings: SettingsDep
) -> PreviewOut:
    """Fetch a skill from GitHub and show it, pinned to a commit. Nothing is stored."""
    fetched = await _fetch(request, body.url)
    existing = SkillRegistry(settings.data_dir / "skills").all().get(fetched.name)
    return PreviewOut(
        name=fetched.name,
        description=fetched.description,
        body=fetched.body,
        files=sorted(r for r in fetched.files if r != "SKILL.md"),
        version=fetched.version,
        hash=fetched.hash,
        url=fetched.source.url,
        commit=fetched.commit,
        signals=list(fetched.signals),
        exists=existing.source if existing else None,
        approx_tokens=len(fetched.body) // 4,
    )


@router.post("/github/install", response_model=SkillOut, status_code=status.HTTP_201_CREATED)
async def install_github_skill(
    body: GithubInstall, request: Request, settings: SettingsDep
) -> SkillOut:
    """Install what the preview showed: the same commit, and only if its content is unchanged."""
    fetched = await _fetch(request, body.url, body.commit)
    if fetched.hash != body.hash:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "the skill is not what the preview showed: preview it again"
        )
    user_dir = settings.data_dir / "skills"
    try:
        github.install(user_dir, fetched, replace=body.replace)
    except github.GithubError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    skill = SkillRegistry(user_dir).get(fetched.name)
    return SkillOut(
        name=skill.name,
        description=skill.description,
        source=skill.source,
        version=skill.version,
        files=list(skill.files),
        personas=sorted(p.id for p in all_personas().values() if skill.name in p.skills),
        origin=github.origin_of(user_dir, skill.name),
    )


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(name: str, settings: SettingsDep) -> Response:
    """Remove one of your skills (a built-in skill cannot be removed). If it replaced a
    built-in skill, the built-in one comes back."""
    user_dir = settings.data_dir / "skills"
    if not NAME_PATTERN.match(name) or not (user_dir / name).is_dir():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "you have no skill with that name")
    holders = sorted(p.id for p in all_personas().values() if name in p.skills)
    if holders and name not in SkillRegistry().all():  # nothing would stand in for it
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"it is still used by: {', '.join(holders)}; remove it from them first",
        )
    github.remove(user_dir, name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
