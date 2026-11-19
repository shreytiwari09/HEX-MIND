---
name: migrations
description: Change a schema safely with small, ordered, reversible migrations.
---

# Migrations

- One migration per change, numbered in order, never edited after it is applied; fix mistakes
  with a new migration.
- Each migration can run on an empty database and on the previous version.
- Prefer additive changes (add a nullable column, backfill, then add the constraint) over
  rewrites; avoid destructive changes unless the feature asks for them.
- Provide the reverse when it is safe (`down`), and say plainly when it is not.
- Test by creating a database from scratch with all migrations, and check the resulting schema.
