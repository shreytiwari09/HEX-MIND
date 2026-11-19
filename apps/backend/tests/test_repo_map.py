"""The repo map in a worker's prompt: what it lists, how it ranks, and what it never shows."""

from pathlib import Path

from app.agents.build import feature_prompt
from app.agents.persona import get_persona
from app.context.repo_map import build_repo_map
from app.missions.models import Feature, Handoff, MissionContext


def write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


APP = {
    "src/todos.js": "function addTodo(list, t) { return [...list, t] }\n"
    "function toggleTodo(list, id) { return list }\n"
    "module.exports = { addTodo, toggleTodo }\n",
    "src/filter.js": "const { addTodo } = require('./todos')\n"
    "export function filterTodos(list, mode) { return list }\n",
    "src/ui/page.tsx": "import { filterTodos } from '../filter'\n"
    "import { addTodo } from '../todos.js'\n"
    "export default function Page() { return null }\n"
    "export const title = 'x'\n",
    "src/todos.test.js": "const { addTodo } = require('./todos')\ntest('a', () => {})\n",
    "README.md": "# Todo\n",
    "package-lock.json": '{"lockfileVersion": 3}\n',
    ".env": "SECRET=1\n",
    "node_modules/dep/index.js": "module.exports = 1\n",
    ".hex/mission/features.json": "{}\n",
}


def test_the_map_lists_files_with_the_names_they_define_and_nothing_secret(tmp_path: Path) -> None:
    root = write(tmp_path / "app", APP)

    text = build_repo_map(root)

    assert "src/todos.js  (addTodo, toggleTodo)" in text
    assert "src/filter.js  (filterTodos)" in text
    assert "src/ui/page.tsx  (Page, title)" in text
    assert "README.md" in text
    for hidden in (".env", "SECRET", "node_modules", ".hex/", "package-lock.json"):
        assert hidden not in text
    assert "return [...list" not in text  # identifiers and paths only, never contents


def test_files_the_feature_names_come_first_then_what_they_import_then_the_most_imported(
    tmp_path: Path,
) -> None:
    root = write(tmp_path / "app", APP)

    default = build_repo_map(root).splitlines()
    focused = build_repo_map(root, focus=["src/ui/page.tsx"]).splitlines()

    # Without a focus the most imported file leads and the test file is last of the code.
    assert default[0].startswith("src/todos.js")
    order = [line.split("  ")[0] for line in default]
    assert order.index("src/todos.test.js") > order.index("src/filter.js")
    # With a focus the named file leads and what it imports follows.
    assert focused[0].startswith("src/ui/page.tsx")
    assert {focused[1].split("  ")[0], focused[2].split("  ")[0]} == {
        "src/filter.js",
        "src/todos.js",
    }


def test_python_imports_rank_too(tmp_path: Path) -> None:
    root = write(
        tmp_path / "py",
        {
            "app/core.py": "def run():\n    pass\nclass Engine:\n    pass\ndef _p():\n    pass\n",
            "app/api.py": "from app.core import run\n\ndef handler():\n    run()\n",
            "app/cli.py": "from app import core\nimport app.api\n\nasync def main():\n    pass\n",
            "tests/test_core.py": "from app.core import run\n\ndef test_run():\n    pass\n",
        },
    )

    lines = build_repo_map(root).splitlines()

    assert lines[0] == "app/core.py  (run, Engine)"  # imported by three files, private name hidden
    assert "app/cli.py  (main)" in lines and lines[-1].startswith("tests/test_core.py")


def test_the_map_stays_within_its_budget_and_says_what_it_left_out(tmp_path: Path) -> None:
    files = {
        f"src/module_{n:03}.js": f"function fn{n}() {{}}\nmodule.exports = {{ fn{n} }}\n"
        for n in range(200)
    }
    root = write(tmp_path / "big", files)

    text = build_repo_map(root, budget_chars=600)

    body, note = text.rsplit("\n", 1)
    assert len(body) <= 600
    assert note.startswith("… and ") and note.endswith("more files (use list_files)")
    assert int(note.split()[2]) == 200 - len(body.splitlines())


def test_an_empty_or_unreadable_project_gives_an_empty_map(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert build_repo_map(empty) == ""
    only_hidden = write(tmp_path / "hidden", {".hex/mission/x.json": "{}", ".env": "A=1"})
    assert build_repo_map(only_hidden) == ""
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "a.js").write_bytes(b"\x00\x01\x02")
    assert build_repo_map(tmp_path / "bin") == "a.js"  # binary: listed, no names


def test_the_feature_prompt_carries_the_map_only_when_there_is_one(tmp_path: Path) -> None:
    feature = Feature(
        id="todo-api",
        title="Todo API",
        persona="backend",
        expected_behavior=["POST /todos creates one"],
    )
    ctx = MissionContext(worktree=tmp_path, workspace=tmp_path, earlier_handoffs=[])
    persona = get_persona("backend")

    with_map = feature_prompt(persona, feature, ctx, repo_map="src/todos.js  (addTodo)")
    without = feature_prompt(persona, feature, ctx)

    assert "Map of the project" in with_map and "src/todos.js  (addTodo)" in with_map
    assert with_map.index("Work from earlier features") < with_map.index("Map of the project")
    assert "Map of the project" not in without


def test_earlier_work_shapes_the_focus(tmp_path: Path) -> None:
    root = write(tmp_path / "app", APP)
    handoff = Handoff(
        feature_id="a",
        persona_id="backend",
        model_used="x:y",
        procedures_followed=True,
        files_changed=["src/filter.js"],
    )

    focus = [f for f in handoff.files_changed]
    lines = build_repo_map(root, focus=focus).splitlines()

    assert lines[0].startswith("src/filter.js")
