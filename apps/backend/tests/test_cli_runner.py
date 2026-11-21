"""Running a command-line project from the chat (PRD D78)."""

import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.chat.service import run_arguments
from app.preview.cli_runner import CliPlan, cli_plan, container_script, with_arguments
from app.sandbox.runner import docker_available

needs_docker = pytest.mark.skipif(not docker_available()[0], reason="Docker unavailable")

CALC_JS = """'use strict';
const ops = { '+': (a, b) => a + b, '-': (a, b) => a - b, '*': (a, b) => a * b,
              '/': (a, b) => a / b };
const [a, op, b] = process.argv.slice(2);
if (!op) { console.error('Usage: node index.js <number> <operator> <number>'); process.exit(1); }
console.log(ops[op](Number(a), Number(b)));
"""


def calculator(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    package = {"name": "calc", "main": "index.js", "scripts": {"start": "node index.js"}}
    (root / "package.json").write_text(json.dumps(package))
    (root / "index.js").write_text(CALC_JS)
    return root


def test_a_command_line_calculator_gets_a_plan_and_a_web_app_does_not(tmp_path: Path) -> None:
    plan = cli_plan(calculator(tmp_path / "calc"))
    assert plan == CliPlan(image="node:22-alpine", command="node index.js", install=None)

    web = tmp_path / "web"
    web.mkdir()
    (web / "app.py").write_text("import streamlit as st\n")
    assert cli_plan(web) is None  # it gets a link instead
    assert cli_plan(tmp_path / "web" / "..") is None  # nothing says how to run it


def test_python_programs_install_their_requirements_inside_the_container(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("print('hi')\n")
    (tmp_path / "requirements.txt").write_text("rich==13.0.0\n")

    plan = cli_plan(tmp_path)
    assert plan is not None and plan.image == "python:3.11-slim"

    script = container_script(plan, "--name Ada")
    assert "pip install -q -r requirements.txt" in script
    assert script.endswith("/tmp/venv/bin/python main.py --name Ada </dev/null")


def test_the_arguments_are_quoted_so_the_shell_reads_none_of_them() -> None:
    assert with_arguments("node index.js", "2 * 3") == "node index.js 2 '*' 3"
    assert with_arguments("node index.js", "1; rm -rf /") == "node index.js '1;' rm -rf /"
    assert with_arguments("node index.js", "$(whoami)") == "node index.js '$(whoami)'"
    assert with_arguments("npm start", "2 + 3") == "npm start --silent -- 2 + 3"
    assert with_arguments("node index.js", "") == "node index.js"


@pytest.mark.parametrize(
    ("message", "args"),
    [("run 2 + 3", "2 + 3"), ("Run 10 / 4", "10 / 4"), ("run it", "it"),
     ("how do I run it", None), ("run\n2", None)],
)  # fmt: skip
def test_run_with_arguments_is_recognised(message: str, args: str | None) -> None:
    assert run_arguments(message) == args


@needs_docker
async def test_run_in_chat_runs_the_calculator_in_the_sandbox_without_a_model_call(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    from app.db.models import LLMCall

    folder = calculator(tmp_path / "calc")
    proj = (await client.post("/api/projects", json={"workspace_path": str(folder)})).json()
    chat = (await client.post(f"/api/projects/{proj['id']}/conversations", json={})).json()
    send = f"/api/conversations/{chat['id']}/messages"

    sums = (await client.post(send, json={"content": "run 2 * 3", "mode": "auto"})).json()
    plain = (await client.post(send, json={"content": "run it", "mode": "auto"})).json()

    message = sums["assistant_message"]
    assert message["metadata"] == {"kind": "app", "status": "ran", "exit_code": 0}
    assert "```\n6\n```" in message["content"]
    usage = plain["assistant_message"]
    assert usage["metadata"]["exit_code"] == 1 and "Usage: node index.js" in usage["content"]
    assert "run 2 + 3" in usage["content"]  # says how to try other input
    async with app.state.sessionmaker() as session:
        assert list(await session.scalars(select(LLMCall))) == []
