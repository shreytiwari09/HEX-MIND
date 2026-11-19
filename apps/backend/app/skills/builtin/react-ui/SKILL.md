---
name: react-ui
description: Build React components that are small, typed and testable.
---

# React UI

- One component per file; props are typed; components render from props and state, and side
  effects (fetching, storage) live in hooks or small functions.
- Keep state as close as possible to where it is used; lift it only when two components need it.
- Derive values during render instead of copying them into state.
- Lists need stable keys (ids, not array indexes); controlled inputs have a value and an onChange.
- Handle loading, empty and error states in the component, not later.
- Use semantic elements and labels (see the `accessibility` skill) and the project's design tokens.
- Test with Testing Library: query by role and label, and assert what the user sees.
