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
- Use `image` (for example `node:22-alpine`) for a prebuilt image, or `dockerfile` for `.hex/Dockerfile`.
- Check it with `list_checks` and run `test` once before you finish.
