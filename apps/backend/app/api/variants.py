"""Prompt and skill variants (PRD §11.5, E5): named configurations to run missions under."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.agents import variants
from app.agents.variants import PersonaOverride
from app.api.deps import SessionDep, SettingsDep
from app.db.models import PromptVariantRow
from app.skills.registry import SkillRegistry

router = APIRouter(prefix="/variants", tags=["variants"])


class VariantIn(BaseModel):
    id: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(default="", max_length=500)
    personas: dict[str, PersonaOverride]


class VariantEditIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    personas: dict[str, PersonaOverride] | None = None


class VariantOut(BaseModel):
    id: str
    name: str
    description: str
    personas: dict[str, PersonaOverride]
    missions: int  # how many missions ran under it
    updated_at: datetime


async def _out(session: SessionDep, row: PromptVariantRow) -> VariantOut:
    await session.refresh(row)  # the database sets updated_at
    variant = variants.to_variant(row)
    return VariantOut(
        id=row.id,
        name=row.name,
        description=row.description,
        personas=variant.personas,
        missions=await variants.missions_using(session, row.id),
        updated_at=row.updated_at,
    )


def _refused(exc: variants.VariantError) -> HTTPException:
    return HTTPException(exc.status_code, str(exc))


@router.get("", response_model=list[VariantOut])
async def list_variants(session: SessionDep) -> list[VariantOut]:
    return [await _out(session, row) for row in await variants.all_rows(session)]


@router.post("", response_model=VariantOut, status_code=status.HTTP_201_CREATED)
async def create_variant(body: VariantIn, session: SessionDep, settings: SettingsDep) -> VariantOut:
    try:
        variants.validate(
            body.id, body.name, body.personas, SkillRegistry(settings.data_dir / "skills")
        )
    except variants.VariantError as exc:
        raise _refused(exc) from None
    if await session.get(PromptVariantRow, body.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"a variant '{body.id}' already exists")
    row = PromptVariantRow(
        id=body.id,
        name=body.name.strip(),
        description=body.description.strip(),
        overrides={k: v.model_dump() for k, v in body.personas.items()},
    )
    session.add(row)
    await session.flush()
    return await _out(session, row)


@router.put("/{variant_id}", response_model=VariantOut)
async def edit_variant(
    variant_id: str, body: VariantEditIn, session: SessionDep, settings: SettingsDep
) -> VariantOut:
    row = await session.get(PromptVariantRow, variant_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "variant not found")
    # A variant that missions already ran under keeps its meaning: change its text and the
    # earlier results no longer say what was run. Copy it to a new id instead.
    if await variants.missions_using(session, variant_id) and body.personas is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "missions already ran under this variant; make a new variant instead of changing it",
        )
    personas = (
        body.personas
        if body.personas is not None
        else {k: PersonaOverride.model_validate(v) for k, v in row.overrides.items()}
    )
    try:
        variants.validate(
            variant_id,
            body.name or row.name,
            personas,
            SkillRegistry(settings.data_dir / "skills"),
        )
    except variants.VariantError as exc:
        raise _refused(exc) from None
    if body.name is not None:
        row.name = body.name.strip()
    if body.description is not None:
        row.description = body.description.strip()
    row.overrides = {k: v.model_dump() for k, v in personas.items()}
    await session.flush()
    return await _out(session, row)


@router.delete("/{variant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_variant(variant_id: str, session: SessionDep) -> Response:
    row = await session.get(PromptVariantRow, variant_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "variant not found")
    if await variants.missions_using(session, variant_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "missions ran under this variant, so it is kept for the record",
        )
    await session.delete(row)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
