---
name: secrets-hygiene
description: Keep keys and tokens out of code, logs and version control.
---

# Secrets hygiene

- Secrets come from the environment or the OS keychain, never from source files, examples or tests.
- `.env` files are in `.gitignore`; commit a `.env.example` with names and no values.
- Never print or log a secret, a header that carries one, or a full request body that might.
- Look for patterns in diffs: `sk-...`, `AKIA...`, `ghp_...`, private key blocks, JWTs, and
  long random strings assigned to names like `key`, `token`, `secret`, `password`.
- A secret that was committed is compromised: say it must be rotated, not just deleted.
