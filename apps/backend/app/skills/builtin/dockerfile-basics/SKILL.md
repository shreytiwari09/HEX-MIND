---
name: dockerfile-basics
description: Write a small `.hex/Dockerfile` that the sandbox accepts.
---

# Dockerfile for the sandbox

The sandbox builds `.hex/Dockerfile` with no network and an empty build context, so:

- Base it on an allowed image only (`FROM node:22-alpine` or `FROM python:3.11-slim`).
- Do not use `COPY` of project files or `ADD`; the project is mounted at `/work` when checks run.
- No `# syntax=` line and no `RUN --mount`, `--network` or `--security`.
- `RUN` is for things that need no network: setting environment, creating folders, small scripts.
  Dependencies are installed by the contract's `install` check (the only step with network, and
  only to package registries), not in the Dockerfile.
- Checks run as a non-root user with a read-only root filesystem and a writable `/tmp`; set
  `ENV HOME=/tmp` style variables rather than writing into `/`.
- Keep it to a few lines; an unchanged file is never rebuilt.
