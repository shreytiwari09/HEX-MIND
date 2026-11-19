---
name: relational-schema-design
description: Model data in normalised tables with sensible keys and constraints.
---

# Relational schema design

- One table per entity, a primary key on every table, foreign keys for every relationship.
- Put rules in the database: `NOT NULL`, `UNIQUE`, `CHECK`, and foreign keys with a deliberate
  `ON DELETE` behaviour.
- Use clear names: singular or plural consistently, `created_at` and `updated_at` timestamps,
  `<table>_id` for foreign keys.
- Index columns you filter or join on; do not index everything.
- Store money as integers (cents) or decimals, times in UTC, and enums as constrained text.
- Write the schema and the seed or example rows in one place so tests can build a fresh database.
