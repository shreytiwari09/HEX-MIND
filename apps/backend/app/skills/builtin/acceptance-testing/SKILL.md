---
name: acceptance-testing
description: Write acceptance tests from the validation contract only.
---

# Acceptance testing

You write tests that judge the work independently of the builders:

- Work from the validation contract (`.hex/mission/validation-contract.md`) and the feature's
  expected behaviour. Do not read the implementation to decide what to test.
- Put every test in `tests/acceptance/`; it is the only place you can write.
- Name each test with the contract id it checks, for example `VC-2.3 sign-up logs the user in`,
  so a failure points at the criterion.
- Test observable behaviour through the public interface (function exports, HTTP endpoints), one
  behaviour per test, with an unhappy-path test where the contract implies one.
- Run the `acceptance` check with `run_check`. Tests may fail until the features exist; fix test
  mistakes, not the product.
- Never weaken a test to make it pass.
