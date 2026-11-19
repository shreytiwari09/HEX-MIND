---
name: escalation-policy
description: Decide when to use a stronger model, re-plan, or ask the user.
---

# Escalation policy

The code sets the limits (retries, budgets); you choose within them:

1. First failure: retry the same persona with the exact findings.
2. Last allowed attempt: use the persona's stronger (escalation) model if it has one.
3. Still failing: re-plan only if the feature was the wrong size or missing a precondition;
   otherwise ask the user (retry, skip, or stop).
- Prefer asking the user over spending the budget on a fourth identical attempt.
- State the cost so far when you ask, and what each option would do.
