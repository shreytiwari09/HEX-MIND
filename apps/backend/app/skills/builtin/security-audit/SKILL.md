---
name: security-audit
description: Review a change for security problems an attacker could use.
---

# Security audit

Look at the diff and the dependencies for:

- Injection: queries, shell commands, HTML and templates built from user input.
- Authentication and authorisation: missing checks on a route, weak session handling, trusting
  client-supplied ids or roles.
- Secrets: keys, tokens and passwords in code, config or logs; `.env` files committed.
- Unsafe defaults: open CORS, debug on, verbose errors, missing input limits.
- Dependencies: unpinned or unmaintained packages, install scripts, packages added without need.
- File and network access: path traversal, user-controlled URLs (SSRF), unrestricted uploads.

Report with file, line and a one-line exploit sketch. `critical` is exploitable now; `major` is a
missing control on a sensitive path. Say what you could not check.
