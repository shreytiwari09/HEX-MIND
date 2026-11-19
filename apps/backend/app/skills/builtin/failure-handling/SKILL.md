---
name: failure-handling
description: Decide what to do when work fails, using the evidence.
---

# Failure handling

- Read the evidence first: the failing check output, the validator finding, the handoff notes.
- A feature that fails its checks goes back to the same persona with the exact output.
- The same failure twice means the instruction or the plan is the problem: reword the feature,
  split it, or add the missing precondition, instead of repeating it.
- A provider outage is not a failure of the work; wait or retry later, and say so.
- Never mark work done that the checks did not accept, and never hide a failure in a summary.
- When you cannot decide, stop and ask the user, with the facts and the options.
