---
name: state-and-data-fetching
description: Fetch, cache and update data in the UI without stale or duplicated state.
---

# State and data fetching

- Separate server data (fetched) from UI state (open, selected, draft). Do not mirror server data
  into component state.
- Fetch in one place (a hook or a small client module); components call it and render the result
  with loading, error and success states.
- Always handle failures: show a message and a retry; never leave a spinner running forever.
- After a change, refresh or update the affected data so the screen matches the server.
- Cancel or ignore stale responses when inputs change (race conditions).
- Debounce search as you type; do not fetch on every keystroke.
