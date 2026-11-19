---
name: testing-backend
description: Write fast, deterministic tests for backend logic and endpoints.
---

# Backend testing

- Test behaviour from the feature's expected behaviour, one test per statement, named after it.
- Put logic in plain functions and test those directly; test endpoints for status codes, bodies
  and error shapes, not for implementation details.
- Each test sets up its own data and cleans up; tests never depend on order or on the network.
- Cover the unhappy paths: bad input, missing records, duplicates, not signed in.
- Use the project's own test runner (see the `test` check) and keep the whole suite under a few
  seconds. Run the `test` check before you finish and fix what fails; a test that ran zero
  cases does not count.
