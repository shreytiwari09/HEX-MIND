"""After a build: make the project a normal repository, and publish it safely (PRD D84)."""

import json
import subprocess
from pathlib import Path

import httpx
import pytest

from app.handoff import prepare as preparing
from app.handoff import publish as publishing
from app.workspace import git


def streamlit_project(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".hex").mkdir()
    (root / ".hex" / "project.json").write_text(json.dumps({
        "stack": "python + streamlit", "image": "python:3.11-slim",
        "install": "python -m venv .venv && .venv/bin/pip install -r requirements.txt",
        "test": ".venv/bin/python -m pytest tests/test_smoke.py",
        "start": ".venv/bin/streamlit run app.py", "port": 8501,
    }))  # fmt: skip
    (root / "app.py").write_text(
        "import os\nimport streamlit as st\nKEY = os.environ.get('WEATHER_API_KEY')\n"
        "token = st.secrets['MAPS_TOKEN']\nport = os.getenv('PORT')\n"
    )
    (root / "requirements.txt").write_text("streamlit==1.40.0\n")
    (root / "README.md").write_text("# Calculator\n\nA calculator.\n")
    (root / ".gitignore").write_text(".venv/\n")
    git.init_repo(root)
    return root


def test_prepare_adds_the_standard_files_from_the_project_itself(tmp_path: Path) -> None:
    root = streamlit_project(tmp_path / "calc")

    done = preparing.prepare(root)

    assert done.stack == "streamlit"
    assert set(done.created) >= {
        ".env.example",
        ".github/workflows/ci.yml",
        ".github/dependabot.yml",
        ".streamlit/config.toml",
    }
    assert set(done.updated) == {".gitignore", "README.md"}
    env = (root / ".env.example").read_text()
    assert (
        "WEATHER_API_KEY=" in env and "MAPS_TOKEN=" in env and "PORT" not in env
    )  # names, no values
    ci = (root / ".github" / "workflows" / "ci.yml").read_text()
    assert 'python-version: "3.11"' in ci
    assert "run: pip install -r requirements.txt" in ci  # CI has no local venv
    assert "run: python -m pytest tests/test_smoke.py" in ci
    assert ".env" in (root / ".gitignore").read_text().splitlines()
    readme = (root / "README.md").read_text()
    assert (
        readme.startswith("# Calculator")
        and "## Developing" in readme
        and "share.streamlit.io" in readme
    )
    # one commit, the user's tree clean
    log = subprocess.run(
        ["git", "log", "-1", "--format=%s"], cwd=root, capture_output=True, text=True
    ).stdout
    assert log.strip() == "Prepare the project for GitHub (H.E.X Mind)"
    assert (
        subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True
        ).stdout
        == ""
    )


def test_prepare_never_overwrites_and_is_safe_to_run_twice(tmp_path: Path) -> None:
    root = streamlit_project(tmp_path / "calc")
    (root / ".env.example").write_text("MINE=1\n")
    git.commit_paths(root, [".env.example"], "mine")

    preparing.prepare(root)
    again = preparing.prepare(root)

    assert (root / ".env.example").read_text() == "MINE=1\n"
    assert again.created == [] and again.updated == [] and again.commit is None


def test_a_node_project_gets_node_ci(tmp_path: Path) -> None:
    root = tmp_path / "web"
    root.mkdir()
    (root / "package.json").write_text(json.dumps({"scripts": {"test": "node --test"}}))
    (root / "package-lock.json").write_text("{}")
    (root / "index.js").write_text("const key = process.env.STRIPE_KEY\n")
    git.init_repo(root)

    done = preparing.prepare(root)

    ci = (root / ".github" / "workflows" / "ci.yml").read_text()
    assert (
        done.stack == "node" and "setup-node" in ci and "run: npm ci" in ci and "cache: npm" in ci
    )
    assert "STRIPE_KEY=" in (root / ".env.example").read_text()


def test_publishing_refuses_tracked_secrets_big_files_and_bad_names(tmp_path: Path) -> None:
    root = streamlit_project(tmp_path / "calc")
    (root / ".env").write_text("WEATHER_API_KEY=abc\n")
    (root / "config.py").write_text("KEY = 'sk-" + "a" * 30 + "'\n")
    git.commit_paths(root, [".env", "config.py"], "oops")

    found = publishing.problems(root)

    assert any(".env looks like a secrets file" in p for p in found)
    assert any("config.py seems to contain a provider API key" in p for p in found)
    assert not any("sk-aaa" in p for p in found)  # never the secret itself
    with pytest.raises(publishing.PublishError, match="letters, numbers"):
        publishing.publish(root, "my repo!", private=True)


def test_publishing_explains_a_missing_or_signed_out_github_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = streamlit_project(tmp_path / "calc")
    monkeypatch.setattr(publishing.shutil, "which", lambda _: None)
    with pytest.raises(publishing.PublishError, match="cli.github.com"):
        publishing.publish(root, "calc")

    monkeypatch.setattr(publishing, "gh_status", lambda: publishing.GhStatus(True, False, None))
    with pytest.raises(publishing.PublishError, match="gh auth login"):
        publishing.publish(root, "calc")


def test_publishing_never_replaces_an_existing_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = streamlit_project(tmp_path / "calc")
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/someone/calc.git"],
        cwd=root,
        check=True,
    )
    monkeypatch.setattr(publishing, "gh_status", lambda: publishing.GhStatus(True, True, "someone"))

    with pytest.raises(publishing.PublishError, match="already has a GitHub remote"):
        publishing.publish(root, "calc")


async def test_the_api_reports_what_is_missing_then_prepares(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    root = streamlit_project(tmp_path / "calc")
    project = (await client.post("/api/projects", json={"workspace_path": str(root)})).json()
    url = f"/api/projects/{project['id']}/handoff"

    before = (await client.get(url)).json()
    assert before["stack"] == "streamlit" and ".github/workflows/ci.yml" in before["missing"]
    assert before["problems"] == [] and before["remote"] is None

    prepared = (await client.post(f"{url}/prepare")).json()
    assert prepared["commit"] and ".env.example" in prepared["created"]
    assert (await client.get(url)).json()["missing"] == []
