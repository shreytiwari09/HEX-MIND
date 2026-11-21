"""Work out how to start a project that has no `.hex/project.json` (PRD D78).

Projects made before the run contract, or opened from elsewhere, still deserve a link. This looks
only at the project's own files (package.json, requirements, the source) and recognises the common
cases: Streamlit, FastAPI, Flask, a Node web server, Vite, Next.js and a plain HTML page. Anything
else is treated as a command-line program: there is no page to open, and the message says how to
run it in a terminal instead of naming a missing file.
"""

import json
import re
from pathlib import Path

from app.sandbox.contract import RunContract

PYTHON_IMAGE = "python:3.11-slim"
NODE_IMAGE = "node:22-alpine"
NODE_SERVERS = {"express", "fastify", "koa", "hono", "@nestjs/core", "http-server", "serve"}
_LISTENS = re.compile(r"\.listen\(|createServer\(")
_SKIP = {"node_modules", ".venv", "venv", ".git", "tests", "test", "dist", "build"}


class NotAWebApp(ValueError):
    """The project runs in a terminal, not a browser. The message says how to run it."""


def _sources(root: Path, suffixes: tuple[str, ...]) -> list[Path]:
    """Source files at the top level and one folder down (src/, app/ …), never dependencies."""
    found = [p for p in sorted(root.iterdir()) if p.is_file() and p.suffix in suffixes]
    for folder in sorted(root.iterdir()):
        if folder.is_dir() and folder.name not in _SKIP and not folder.name.startswith("."):
            found += [p for p in sorted(folder.iterdir()) if p.is_file() and p.suffix in suffixes]
    return found


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:200_000]
    except OSError:
        return ""


def _python_install(root: Path, packages: str) -> str:
    setup = "python -m venv .venv && .venv/bin/pip install -q"
    if (root / "requirements.txt").is_file():
        return f"{setup} -r requirements.txt"
    return f"{setup} {packages}"


def _python(root: Path) -> RunContract | None:
    for path in _sources(root, (".py",)):
        text, rel = _read(path), path.relative_to(root).as_posix()
        module = rel[:-3].replace("/", ".")
        if re.search(r"^\s*(import streamlit|from streamlit)", text, re.M):
            return RunContract(
                stack="python + streamlit", image=PYTHON_IMAGE,
                install=_python_install(root, "streamlit"),
                start=f".venv/bin/streamlit run {rel} --server.port 8501 "
                "--server.address 0.0.0.0 --server.headless true",
                port=8501,
            )  # fmt: skip
        if re.search(r"^app\s*=\s*FastAPI\(", text, re.M):
            return RunContract(
                stack="python + fastapi", image=PYTHON_IMAGE,
                install=_python_install(root, "fastapi uvicorn"),
                start=f".venv/bin/uvicorn {module}:app --host 0.0.0.0 --port 8000", port=8000,
            )  # fmt: skip
        if re.search(r"^app\s*=\s*Flask\(", text, re.M):
            return RunContract(
                stack="python + flask", image=PYTHON_IMAGE,
                install=_python_install(root, "flask"),
                start=f".venv/bin/flask --app {module} run --host 0.0.0.0 --port 5000", port=5000,
            )  # fmt: skip
    return None


def _node(root: Path) -> RunContract | None:
    try:
        package = json.loads(_read(root / "package.json"))
    except ValueError:
        return None
    if not isinstance(package, dict):
        return None
    scripts = package.get("scripts") or {}
    deps = {**(package.get("dependencies") or {}), **(package.get("devDependencies") or {})}
    install = "npm install" if deps else None
    if "next" in deps:
        start = "npx next dev -H 0.0.0.0 -p 3000"
        return RunContract(stack="node + next", image=NODE_IMAGE, install=install, start=start,
                           port=3000)  # fmt: skip
    if "vite" in deps:
        start = "npx vite --host 0.0.0.0 --port 5173"
        return RunContract(stack="node + vite", image=NODE_IMAGE, install=install, start=start,
                           port=5173)  # fmt: skip
    listens = bool(NODE_SERVERS & deps.keys()) or any(
        _LISTENS.search(_read(p)) for p in _sources(root, (".js", ".mjs", ".cjs", ".ts"))
    )
    if not listens:
        return None
    start = "npm start" if scripts.get("start") else f"node {package.get('main') or 'index.js'}"
    return RunContract(stack="node", image=NODE_IMAGE, install=install, start=start, port=3000)


def _static(root: Path) -> RunContract | None:
    if (root / "index.html").is_file() and not (root / "package.json").exists():
        return RunContract(
            stack="static html", image=PYTHON_IMAGE,
            start="python -m http.server 8000 --bind 0.0.0.0", port=8000,
        )  # fmt: skip
    return None


def terminal_command(root: Path) -> str | None:
    """How a person runs this program in a terminal, when the files say."""
    try:
        package = (
            json.loads(_read(root / "package.json")) if (root / "package.json").is_file() else None
        )
    except ValueError:
        package = None
    if isinstance(package, dict):
        if (package.get("scripts") or {}).get("start"):
            return str(package["scripts"]["start"])
        return f"node {package.get('main') or 'index.js'}"
    for name in ("main.py", "app.py", "cli.py", "__main__.py"):
        if (root / name).is_file():
            return f"python {name}"
    return None


def not_a_web_app_message(root: Path, start: str | None = None) -> str:
    command = start or terminal_command(root)
    how = f" Run it in a terminal from the project folder: `{command}`." if command else ""
    return (
        "this is a command-line program, not a web app, so there is no page to open in a browser."
        f"{how} If you want a page to click on, ask for a web version (for example "
        '"add a Streamlit page" or "add a simple HTML page").'
    )


def guess_contract(root: Path) -> RunContract:
    """A run contract worked out from the files. Raises NotAWebApp when there is no page."""
    for guess in (_python, _node, _static):
        contract = guess(root)
        if contract is not None:
            return contract
    raise NotAWebApp(not_a_web_app_message(root))
