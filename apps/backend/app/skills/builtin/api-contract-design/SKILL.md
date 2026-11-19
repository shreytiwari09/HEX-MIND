---
name: api-contract-design
description: Write the contract builders share before they write code.
---

# API contract design

- Write the contract before the code, in one file the features reference (`contract_refs`).
- For each endpoint: method and path, request body or query (fields and types), response
  (status codes, fields, error shape), and who may call it.
- For modules: exported function names, argument types, return values and thrown errors.
- Keep names identical everywhere (database column, API field, UI prop); mismatches are the most
  common integration bug.
- Version only when you must; prefer adding fields over changing them.
