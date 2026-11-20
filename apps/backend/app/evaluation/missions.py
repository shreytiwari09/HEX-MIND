"""The mission benchmark (PRD §15.1): small full apps built from an idea, each with a fixed plan,
hidden acceptance tests and a known-good reference solution.

    python -m app.evaluation.missions validate   # every hidden test fails on the empty project
                                                 # and passes on the reference solution

A benchmark mission starts from the **fixed plan** in `app.yaml`, not from a PM conversation: that
keeps runs comparable, so a difference between two conditions comes from how the team works and
not from what the PM happened to ask. (The PM's own quality is measured by its own runs.) The
hidden tests are copied in only to grade, after the mission, and never into an agent's reach.
The apps are plain CommonJS libraries tested with `node --test`: browser (Playwright) tests are
deferred with Playwright itself (PRD §21 D41).
"""

import argparse
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.evaluation import benchmarks
from app.missions.models import MissionPlan
from app.sandbox.runner import CheckOutcome

BENCH_DIR = Path(__file__).with_name("mission_benchmark")
SEED_DIR = BENCH_DIR / "seed"
# Bump when an app, a plan or a hidden test changes: results of different versions do not compare.
BENCHMARK_VERSION = "m2"  # m1 had three apps; m2 adds habit-tracker and inventory


@dataclass(frozen=True)
class MissionApp:
    id: str
    idea: str
    plan: dict[str, Any]

    @property
    def directory(self) -> Path:
        return BENCH_DIR / "apps" / self.id

    @property
    def acceptance_test(self) -> Path:
        return self.directory / "acceptance.test.js"

    def reference_dirs(self) -> tuple[Path, ...]:
        """The reference solution, one folder per feature, in the plan's order."""
        return tuple(
            self.directory / "reference" / feature["id"]
            for milestone in self.plan["milestones"]
            for feature in milestone["features"]
        )

    def feature_ids(self) -> list[str]:
        return [f["id"] for m in self.plan["milestones"] for f in m["features"]]


def load_apps() -> list[MissionApp]:
    apps = []
    for path in sorted((BENCH_DIR / "apps").glob("*/app.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        MissionPlan.model_validate(data["plan"])  # the plan must be one the app accepts
        apps.append(MissionApp(id=data["id"], idea=data["idea"], plan=data["plan"]))
    ids = [a.id for a in apps]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate mission benchmark ids")
    return apps


def get_app(app_id: str) -> MissionApp:
    for app in load_apps():
        if app.id == app_id:
            return app
    raise KeyError(f"unknown mission benchmark app '{app_id}'")


def prepare_workspace(dest: Path, app: MissionApp | None = None) -> Path:
    """The empty project (with the reference solution overlaid when `app` is given)."""
    overlays = app.reference_dirs() if app is not None else ()
    return benchmarks.prepare_workspace(dest, seed=SEED_DIR, overlays=overlays)


def grade(project_dir: Path, app: MissionApp, *, timeout_s: int = 120) -> CheckOutcome:
    return benchmarks.grade_file(project_dir, app.acceptance_test, app.id, timeout_s=timeout_s)


def validate() -> list[str]:
    """Problems with the benchmark; empty means every hidden test discriminates."""
    problems = []
    for app in load_apps():
        with tempfile.TemporaryDirectory() as tmp:
            empty = prepare_workspace(Path(tmp) / "empty")
            solved = prepare_workspace(Path(tmp) / "solved", app)
            on_empty = grade(empty, app)
            on_reference = grade(solved, app)
        if on_empty.exit_code is None or on_reference.exit_code is None:
            problems.append(f"{app.id}: sandbox error {on_empty.error or on_reference.error}")
        elif benchmarks.passed(on_empty):
            problems.append(f"{app.id}: the hidden tests pass on the empty project")
        elif not benchmarks.passed(on_reference):
            problems.append(f"{app.id}: the reference fails:\n{on_reference.output_tail[-800:]}")
    return problems


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="python -m app.evaluation.missions")
    parser.add_argument("command", choices=["validate"])
    parser.parse_args()
    issues = validate()
    print("\n".join(issues) if issues else f"all {len(load_apps())} mission apps valid")
    raise SystemExit(1 if issues else 0)
