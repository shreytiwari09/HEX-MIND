---
name: run-contract
description: Write `.hex/project.json`, the file every check and validator reads.
---

# Run contract

`.hex/project.json` is the single source of the project's commands. Write it with these fields:

```json
{
  "stack": "node + vitest",
  "dockerfile": ".hex/Dockerfile",
  "install": "npm ci",
  "build": "npm run build",
  "test": "npm test",
  "typecheck": "npx tsc --noEmit",
  "lint": "npx eslint .",
  "acceptance": "npx vitest run tests/acceptance",
  "start": "npm run dev -- --host 0.0.0.0",
  "port": 5173,
  "healthcheck": "/",
  "network": { "install": "allowlist", "test": "none", "start": "none" }
}
```

- Each command is one line and runs offline after `install` (tests and typecheck have no network).
- Define at least `test`; define `acceptance` so QA's tests can run; leave out checks that do not exist.
- `test` must run a real test runner on real tests (for example `node --test`). A command that cannot fail, such as `echo "test passed"` or `true`, is not accepted: the app only counts a test run whose output shows tests running.
- Use `image` (for example `node:22-alpine`) for a prebuilt image, or `dockerfile` for `.hex/Dockerfile`.
- Check it with `list_checks` and run `test` once before you finish.
- For an app the user opens in a browser, set `start`, `port` and `healthcheck`: the user gets
  a link (`http://localhost:<port>`) from the chat. `start` must listen on `0.0.0.0` (not
  `localhost`) and on `port` (also given as `$PORT`), or the link cannot reach it. Streamlit:
  `"start": ".venv/bin/streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true"`,
  `"port": 8501`, with `"install": "python -m venv .venv && .venv/bin/pip install -r requirements.txt"`
  and `"image": "python:3.11-slim"`. A library or command-line tool has no `start` or `port`.
