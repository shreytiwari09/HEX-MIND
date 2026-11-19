"""The mission folder: `.hex/mission/` in the mission worktree (PRD §9.2).

Agents read and write these plain files and git versions them with the code. Postgres holds the
scheduling state; this module renders it. `features.json` is always written from database
state, never read back as the source of truth.
"""

import json
import os
from pathlib import Path
from typing import Any

from app.missions.models import Handoff, MissionContext, ValidatorReport


def mission_dir(worktree: Path) -> Path:
    return MissionContext(worktree=worktree, workspace=worktree).mission_dir


def render_features_json(mission_id: str, milestones: list[dict[str, Any]]) -> dict[str, Any]:
    """The PRD §9.3 shape. Each milestone dict has id, title, status, validators and features;
    each feature dict has the §9.3 fields (plus description and target_files)."""
    return {"mission_id": mission_id, "milestones": milestones}


def write_features_json(worktree: Path, document: dict[str, Any]) -> Path:
    path = mission_dir(worktree) / "features.json"
    _atomic_write(path, json.dumps(document, indent=2) + "\n")
    return path


def append_handoff(worktree: Path, handoff: Handoff) -> Path:
    """One line per worker run in `handoffs.jsonl`."""
    path = mission_dir(worktree) / "handoffs.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as file:
        file.write(handoff.model_dump_json() + "\n")
    return path


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(text.encode("utf-8"))  # bytes: no newline translation on Windows
    os.replace(tmp, path)


def write_validator_report(worktree: Path, report: ValidatorReport, round_no: int) -> Path:
    """One JSON report per validator per milestone round in `validator-reports/`."""
    name = f"{report.milestone_id}-{report.validator}-r{round_no}.json"
    path = mission_dir(worktree) / "validator-reports" / name
    _atomic_write(path, report.model_dump_json(indent=2) + "\n")
    return path


def render_validation_contract(criteria: list[dict]) -> str:  # type: ignore[type-arg]
    """The validation contract as the markdown QA reads (PRD §9.7), grouped by feature."""
    lines = ["# Validation contract", ""]
    groups: dict[str, list[dict]] = {}  # type: ignore[type-arg]
    for criterion in criteria:
        groups.setdefault(criterion.get("feature") or "(whole mission)", []).append(criterion)
    for feature, items in groups.items():
        lines += [f"## {feature}", ""]
        lines += [f"- {c['id']}: {c['text']}   [{c['how']}]" for c in items]
        lines.append("")
    return "\n".join(lines)


def write_validation_contract(worktree: Path, criteria: list[dict]) -> Path:  # type: ignore[type-arg]
    path = mission_dir(worktree) / "validation-contract.md"
    _atomic_write(path, render_validation_contract(criteria))
    return path


def write_prd(worktree: Path, prd: str) -> Path:
    """The PM's plain-language PRD for this mission (PRD §9.2 `prd.md`)."""
    path = mission_dir(worktree) / "prd.md"
    _atomic_write(path, prd.rstrip() + "\n")
    return path
