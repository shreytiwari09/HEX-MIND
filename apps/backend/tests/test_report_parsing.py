"""A worker's final report is read even when a model echoes the shape of the format it was shown.

Live run (2026-11-21): free DeepSeek answered every list field as
`{"title": "Implemented", "type": "array", "items": [...]}`, copying the JSON schema the prompt
showed, so 3 attempts with passing tests all failed on the report alone.
"""

import json
from pathlib import Path

import pytest

from app.agents.build import feature_prompt
from app.agents.persona import get_persona
from app.agents.roles import OutputError, parse_json_output
from app.missions.models import AgentReport, Feature, MissionContext


def test_a_report_in_the_schema_shape_is_unwrapped() -> None:
    raw = json.dumps(
        {
            "implemented": {"title": "Implemented", "type": "array", "items": ["src/calc.js"]},
            "left_undone": {"title": "Left Undone", "type": "array", "items": []},
            "issues_found": {"type": "array", "items": ["port was 0"]},
            "procedures_followed": {"title": "Procedures Followed", "value": True},
            "notes_for_next": ["none"],
        }
    )

    report = parse_json_output(raw, AgentReport)

    assert report.implemented == ["src/calc.js"] and report.left_undone == []
    assert report.issues_found == ["port was 0"] and report.procedures_followed is True
    assert report.notes_for_next == ["none"]


def test_a_plain_report_is_read_as_before() -> None:
    raw = 'Done.\n```json\n{"implemented": ["a"], "procedures_followed": false}\n```'

    report = parse_json_output(raw, AgentReport)

    assert report.implemented == ["a"] and report.procedures_followed is False


@pytest.mark.parametrize(
    "raw",
    [
        '{"implemented": {"title": "Implemented", "type": "array"}, "procedures_followed": true}',
        '{"implemented": {"items": "not a list"}, "procedures_followed": true}',
        '{"implemented": ["a"]}',  # procedures_followed missing
        "no json here",
    ],
)
def test_what_cannot_be_read_still_fails(raw: str) -> None:
    with pytest.raises(OutputError):
        parse_json_output(raw, AgentReport)


def test_the_builder_is_shown_an_example_report_not_a_schema(tmp_path: Path) -> None:
    feature = Feature(
        id="calc",
        title="Calculator",
        persona="backend",
        description="Add two numbers.",
        expected_behavior=["add(2, 3) returns 5"],
    )
    prompt = feature_prompt(
        get_persona("backend"), feature, MissionContext(worktree=tmp_path, workspace=tmp_path)
    )
    tail = prompt[prompt.index("Your final answer") :]

    assert '"implemented": [' in tail and '"procedures_followed": true' in tail
    assert '"title"' not in tail and '"items"' not in tail and '"type"' not in tail
