"""Starting a project that has no .hex/project.json (PRD D78)."""

import json
from pathlib import Path

import pytest

from app.preview.app_runner import AppError, AppRunner
from app.preview.guess import NotAWebApp, guess_contract


def write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    return root


def test_a_streamlit_app_is_started_with_streamlit_in_a_venv(tmp_path: Path) -> None:
    write(tmp_path, {"app.py": "import streamlit as st\nst.title('Calc')\n",
                     "requirements.txt": "streamlit==1.40.0\n"})  # fmt: skip

    contract = guess_contract(tmp_path)

    assert contract.port == 8501 and contract.image == "python:3.11-slim"
    assert contract.install and "-r requirements.txt" in contract.install
    assert contract.start and "streamlit run app.py" in contract.start
    assert "--server.address 0.0.0.0" in contract.start


def test_a_streamlit_file_in_src_without_requirements_still_runs(tmp_path: Path) -> None:
    write(tmp_path, {"src/calc_app.py": "from streamlit import title\n"})

    contract = guess_contract(tmp_path)

    assert contract.start and "streamlit run src/calc_app.py" in contract.start
    assert contract.install and contract.install.endswith("pip install -q streamlit")


@pytest.mark.parametrize(
    ("files", "start", "port"),
    [
        ({"main.py": "from fastapi import FastAPI\napp = FastAPI()\n"}, "uvicorn main:app", 8000),
        ({"src/web.py": "from flask import Flask\napp = Flask(__name__)\n"},
         "flask --app src.web run", 5000),
        ({"package.json": json.dumps({"scripts": {"start": "node server.js"},
                                      "dependencies": {"express": "4"}})}, "npm start", 3000),
        ({"package.json": json.dumps({"main": "srv.js"}),
          "srv.js": "require('http').createServer(() => {}).listen(3000)"}, "node srv.js", 3000),
        ({"package.json": json.dumps({"devDependencies": {"vite": "5"}})}, "npx vite", 5173),
        ({"package.json": json.dumps({"dependencies": {"next": "14"}})}, "npx next dev", 3000),
        ({"index.html": "<h1>Calc</h1>"}, "python -m http.server", 8000),
    ],
)  # fmt: skip
def test_common_web_apps_are_recognised(tmp_path: Path, files, start: str, port: int) -> None:
    contract = guess_contract(write(tmp_path, files))

    assert contract.start and start in contract.start and contract.port == port


def test_a_command_line_calculator_says_how_to_run_it_instead_of_a_missing_file(
    tmp_path: Path,
) -> None:
    write(tmp_path, {
        "package.json": json.dumps({"scripts": {"start": "node index.js"}}),
        "index.js": "console.log(require('./src/calc').add(1, 2))\n",
        "src/calc.js": "exports.add = (a, b) => a + b\n",
        "node_modules/express/server.js": "app.listen(3000)",  # dependencies are not the app
    })  # fmt: skip

    with pytest.raises(NotAWebApp) as caught:
        guess_contract(tmp_path)
    with pytest.raises(AppError) as from_runner:
        AppRunner(["node:22-alpine"]).prepare("p", tmp_path)

    for message in (str(caught.value), str(from_runner.value)):
        assert "command-line program, not a web app" in message
        assert "`node index.js`" in message and "project.json" not in message


def test_an_empty_folder_is_not_a_web_app(tmp_path: Path) -> None:
    with pytest.raises(NotAWebApp, match="no page to open"):
        guess_contract(tmp_path)
