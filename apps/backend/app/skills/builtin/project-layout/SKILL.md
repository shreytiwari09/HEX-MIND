---
name: project-layout
description: Set up a standard folder layout, README, .gitignore and dependency file a person can run locally.
---

# Project layout

The project must be usable by a person on their own computer after Apply, not only in the
sandbox. When you scaffold a project, always create:

- **Source in `src/`** (Python: `src/<package_name>/` with `__init__.py`; Node: `src/`).
  Entry points such as `index.js`, `app.py` or `main.py` may sit at the root when the stack
  expects it (Streamlit: `app.py`).
- **Tests in `tests/`**, named the way the test runner finds them (`test_*.py`, `*.test.js`).
  The setup itself always includes **one small test that passes** (for example
  `tests/test_smoke.py` that imports the package): a feature is done only when the `test` check
  runs at least one test and it passes. QA's tests in `tests/acceptance/` are not run by `test`.
- **A dependency file** listing every package the code imports, with versions:
  Python `requirements.txt` (or `pyproject.toml`), Node `package.json`. Add a lock file when the
  tool makes one (`package-lock.json`). Pin with `==` only: never write `--hash` lines or
  checksums, which you cannot compute and which make the install fail.
- **`.gitignore`** with at least: `.venv/`, `venv/`, `__pycache__/`, `*.pyc`, `node_modules/`,
  `dist/`, `build/`, `.env`, `.env.*`, `.DS_Store`, `.pytest_cache/`, `coverage/`.
- **`README.md`** with: one line on what it is; how to install and run it locally, as copyable
  commands; how to run the tests. For Python, the setup always uses a virtual environment:

  ```bash
  python3 -m venv .venv
  source .venv/bin/activate        # Windows: .venv\Scripts\activate
  pip install -r requirements.txt
  python -m pytest                 # tests
  streamlit run app.py             # or: python main.py
  ```

  For Node: `npm install`, `npm test`, then the start command.

Never create or commit the virtual environment itself (`.venv/`) or `node_modules/`: they are
rebuilt from the dependency file. Never write secrets or real keys into any file; when the app
needs a key, read it from an environment variable and say so in the README.

Keep the layout small: no empty folders, no files the project does not use.
