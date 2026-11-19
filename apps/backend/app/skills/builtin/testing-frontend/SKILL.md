---
name: testing-frontend
description: Test the UI through what the user sees and does.
---

# Frontend testing

- Use the project's test runner with Testing Library: render, interact with `fireEvent` or the
  user-event library, and assert on text, roles and labels.
- Test behaviour, not implementation: no assertions on component internals or class names.
- Mock only the network boundary (the API client); use real components and logic otherwise.
- Cover: initial render, the main interaction, an error state, and an empty state.
- Keep tests independent and fast; wait for async results with `findBy...`, not timeouts.
- Run the `test` check before you finish and fix what fails.
