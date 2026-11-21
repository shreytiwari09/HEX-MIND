---
name: feature-decomposition
description: Split a product into milestones and small, checkable features.
---

# Feature decomposition

- Milestones are slices that can be checked on their own: foundation (scaffold, run contract),
  then data or logic, then the UI that uses it. Two to five milestones.
- A feature is one persona's work that can be proven by tests in one sitting: a pure module with
  tests, one endpoint, one screen. If you cannot say how to test it, split it or reword it.
- Order features so each builds only on earlier ones; the first feature of a new project is
  DevOps writing the scaffold and `.hex/project.json`.
- Give every feature `expected_behavior` as observable statements, and the `target_files` you expect.
- Write the validation contract in the user's terms (`VC-1`, `VC-2`, ...), each tied to a feature
  and marked with how it is checked: unit test, api test, browser, typecheck or security review.
- Size the plan to the task: a small task is one or two milestones and one to three features, and a
  module and its tests are one feature. Put `code-reviewer` on every milestone, `security` only where the
  milestone handles logins, secrets, user input, files or the network, and `qa` where there are unit or
  api criteria. Every extra milestone, feature or validator costs many model calls.
