---
name: design-tokens
description: Define colours, type, spacing and radii once and use them everywhere.
---

# Design tokens

- Define tokens as CSS custom properties on `:root` (colour, type scale, spacing scale, radius,
  shadow, motion duration); components use tokens, never raw values.
- Name by role, not by value: `--surface`, `--text-muted`, `--accent`, not `--grey-200`.
- Provide a dark theme by redefining the same tokens; do not duplicate components.
- Keep a small scale: about 6 type sizes, 8 spacing steps, 3 radii.
- Document the tokens in one file (for example `src/styles/tokens.css`) so the next worker reuses
  them instead of adding new ones.
