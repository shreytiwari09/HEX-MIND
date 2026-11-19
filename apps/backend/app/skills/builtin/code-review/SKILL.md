---
name: code-review
description: Review a diff for correctness, tests and maintainability; cite evidence.
---

# Code review

- Read the feature's expected behaviour first, then the diff; decide whether the code does it.
- Report only what you can point at: file, line and what is wrong. No file and line, no finding.
- Severity: `critical` breaks the feature or loses data; `major` is a bug or a missing test for
  stated behaviour; `minor` is a maintainability issue; `info` is a note. Only critical and major
  send the work back.
- Check: wrong results on the unhappy path, missing input checks, tests that cannot fail, dead or
  duplicated code, names that mislead.
- Do not report style preferences the project's formatter already settles.
- If the checks passed but the tests do not exercise the behaviour, that is a finding.
- Say "approved" only when you looked for problems and found none; never approve without reading.
