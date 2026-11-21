"""Make a built project a normal repository someone can push, run and grow (PRD D84).

On the user's click (never on its own), H.E.X adds the standard files a small project has and
H.E.X's agents do not always write, built only from what the project itself says:

- `.env.example`: the names of the settings the code reads (no values), so nobody commits keys;
- `.github/workflows/ci.yml`: install and test on every push, from the run contract's commands;
- `.github/dependabot.yml`: weekly dependency update pull requests;
- `.streamlit/config.toml` for Streamlit apps, `.gitignore` entries that keep secrets out;
- README sections on developing and deploying, appended only if missing.

Existing files are never overwritten. The changes are one commit the user can revert.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.sandbox.contract import RunContract, load_contract
from app.workspace import git

_ENV_PATTERNS = (
    re.compile(r"""os\.environ(?:\.get)?\(\s*['"]([A-Z][A-Z0-9_]{1,63})['"]"""),
    re.compile(r"""os\.environ\[\s*['"]([A-Z][A-Z0-9_]{1,63})['"]\s*\]"""),
    re.compile(r"""os\.getenv\(\s*['"]([A-Z][A-Z0-9_]{1,63})['"]"""),
    re.compile(r"""st\.secrets\[\s*['"]([A-Za-z][A-Za-z0-9_]{1,63})['"]\s*\]"""),
    re.compile(r"""process\.env\.([A-Z][A-Z0-9_]{1,63})"""),
    re.compile(r"""import\.meta\.env\.([A-Z][A-Z0-9_]{1,63})"""),
)
_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "dist", "build", ".hex", "__pycache__"}
_GITIGNORE_NEEDED = [".env", ".env.*", "!.env.example", ".venv/", "node_modules/", "__pycache__/",
                     ".streamlit/secrets.toml", "dist/"]  # fmt: skip
_IGNORED_ENV = {"PORT", "HOST", "NODE_ENV", "PATH", "HOME", "CI"}


@dataclass
class Prepared:
    stack: str
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    commit: str | None = None


def _sources(root: Path) -> list[Path]:
    found: list[Path] = []
    for path in root.rglob("*"):
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_file() and path.suffix in {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
            found.append(path)
    return found[:2000]


def env_names(root: Path) -> list[str]:
    """Setting names the code reads from the environment, sorted, without the usual ones."""
    names: set[str] = set()
    for path in _sources(root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:300_000]
        except OSError:
            continue
        for pattern in _ENV_PATTERNS:
            names.update(pattern.findall(text))
    return sorted(names - _IGNORED_ENV)


def stack_of(root: Path, contract: RunContract | None) -> str:
    """'streamlit', 'python', 'node' or 'unknown'."""
    described = (contract.stack if contract else "").lower()
    if "streamlit" in described or (root / ".streamlit").is_dir():
        return "streamlit"
    if (root / "package.json").is_file() or "node" in described:
        return "node"
    if (
        (root / "requirements.txt").is_file()
        or (root / "pyproject.toml").is_file()
        or "python" in described
    ):
        return "python"
    return "unknown"


def _plain(command: str) -> str:
    """A run-contract command as CI runs it: no local virtual environment."""
    command = re.sub(r"python3?\s+-m\s+venv\s+\S+\s*&&\s*", "", command)
    return re.sub(r"(?:\./)?\.?venv/bin/", "", command).strip()


def ci_workflow(stack: str, contract: RunContract | None, root: Path) -> str | None:
    install = _plain(contract.install) if contract and contract.install else None
    test = _plain(contract.test) if contract and contract.test else None
    if stack in ("streamlit", "python"):
        version = "3.11"
        if contract and contract.image and (m := re.search(r"python:(\d+\.\d+)", contract.image)):
            version = m.group(1)
        install = install or (
            "pip install -r requirements.txt"
            if (root / "requirements.txt").is_file()
            else "pip install ."
        )
        test = test or "python -m pytest"
        return f"""name: CI

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "{version}"
          cache: pip
      - name: Install
        run: {install}
      - name: Test
        run: {test}
"""
    if stack == "node":
        version = "22"
        if contract and contract.image and (m := re.search(r"node:(\d+)", contract.image)):
            version = m.group(1)
        lock = (root / "package-lock.json").is_file()
        install = install or ("npm ci" if lock else "npm install")
        if install == "npm install" and lock:
            install = "npm ci"
        test = test or "npm test"
        cache = "\n          cache: npm" if lock else ""
        return f"""name: CI

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "{version}"{cache}
      - name: Install
        run: {install}
      - name: Build
        run: npm run build --if-present
      - name: Test
        run: {test}
"""
    return None


def dependabot(stack: str) -> str | None:
    ecosystem = {"streamlit": "pip", "python": "pip", "node": "npm"}.get(stack)
    if not ecosystem:
        return None
    return f"""version: 2
updates:
  - package-ecosystem: "{ecosystem}"
    directory: "/"
    schedule:
      interval: "weekly"
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
"""


def env_example(names: list[str]) -> str:
    lines = ["# Settings this app reads. Copy to .env and fill in; never commit .env.", ""]
    lines += [f"{name}=" for name in names] or ["# (this app reads no settings yet)"]
    return "\n".join(lines) + "\n"


DEPLOY = {
    "streamlit": """## Deploy

The simplest free option is **Streamlit Community Cloud**:

1. Push this repository to GitHub.
2. Go to <https://share.streamlit.io>, choose **Create app**, pick this repository and `app.py`.
3. If the app needs keys, paste them under **Advanced settings → Secrets** (never in the code).

Other options: any host that runs a Python container (for example Google Cloud Run) with
`streamlit run app.py --server.port $PORT --server.address 0.0.0.0`.
""",
    "python": """## Deploy

Run it on a host that runs Python apps, for example Render or Google Cloud Run
(`gcloud run deploy --source .`). Set the settings from `.env.example` as environment variables
in the host's dashboard; never commit `.env`.
""",
    "node": """## Deploy

A static or front-end app deploys for free on **Netlify**, **Vercel** or **Cloudflare Pages**:
import this repository, keep the build command (`npm run build`) and the output folder the
tool shows. A Node server can run on Render or Google Cloud Run. Set the settings from
`.env.example` in the host's dashboard; never commit `.env`.
""",
}

DEVELOP = {
    "python": """## Developing

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
python -m pytest                 # run the tests before every commit
```

- Make each change on its own branch, and open a pull request: CI runs the tests on GitHub.
- Keep keys in `.env` (see `.env.example`); it is ignored by git.
- Update a dependency by changing its version in `requirements.txt`, then run the tests.
""",
    "node": """## Developing

```bash
npm install
npm test                         # run the tests before every commit
```

- Make each change on its own branch, and open a pull request: CI runs the tests on GitHub.
- Keep keys in `.env` (see `.env.example`); it is ignored by git.
- Update dependencies with `npm outdated` and `npm update`, then run the tests.
""",
}


def _write_new(root: Path, rel: str, text: str, done: Prepared) -> None:
    path = root / rel
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    done.created.append(rel)


def prepare(root: Path) -> Prepared:
    """Add the missing standard files and commit them. Raises git.GitError if `root` is not a
    git repository."""
    try:
        contract = load_contract(root)
    except ValueError:
        contract = None
    stack = stack_of(root, contract)
    done = Prepared(stack=stack)

    _write_new(root, ".env.example", env_example(env_names(root)), done)
    if workflow := ci_workflow(stack, contract, root):
        _write_new(root, ".github/workflows/ci.yml", workflow, done)
    if bot := dependabot(stack):
        _write_new(root, ".github/dependabot.yml", bot, done)
    if stack == "streamlit":
        _write_new(
            root,
            ".streamlit/config.toml",
            '[server]\nheadless = true\n\n[theme]\nbase = "light"\n',
            done,
        )

    gitignore = root / ".gitignore"
    have = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.is_file() else []
    missing = [line for line in _GITIGNORE_NEEDED if line not in have]
    if missing:
        text = "\n".join(have).rstrip("\n")
        gitignore.write_text(
            (text + "\n\n" if text else "")
            + "# Added by H.E.X Mind: keep secrets and installs out of git\n"
            + "\n".join(missing)
            + "\n",
            encoding="utf-8",
        )
        (done.updated if have else done.created).append(".gitignore")

    readme = root / "README.md"
    kind = "python" if stack in ("streamlit", "python") else stack
    text = readme.read_text(encoding="utf-8") if readme.is_file() else f"# {root.name}\n"
    additions = []
    if kind in DEVELOP and "## Developing" not in text:
        additions.append(DEVELOP[kind])
    if stack in DEPLOY and "## Deploy" not in text:
        additions.append(DEPLOY[stack])
    if additions:
        readme.write_text(text.rstrip("\n") + "\n\n" + "\n".join(additions), encoding="utf-8")
        (done.updated if readme.is_file() and text != f"# {root.name}\n" else done.created).append(
            "README.md"
        )

    changed = done.created + done.updated
    if changed:
        done.commit = git.commit_paths(root, changed, "Prepare the project for GitHub (H.E.X Mind)")
    return done


def as_json(done: Prepared) -> str:
    return json.dumps(done.__dict__)
