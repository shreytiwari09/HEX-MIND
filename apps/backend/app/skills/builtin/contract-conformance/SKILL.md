---
name: contract-conformance
description: Check that code matches the contracts and the validation contract.
---

# Contract conformance

- List the contracts the feature names (API spec, schema, validation criteria `VC-n`).
- For each, find the code that implements it and the test that proves it; a criterion with no
  code or no test is a finding, referenced by its `VC-n` id.
- Compare shapes exactly: paths, methods, field names, types, status codes, error format.
- Extra behaviour the contract does not mention is a note, not a failure; missing or different
  behaviour is a failure.
- Cite the contract line and the code location together so the builder can fix it.
