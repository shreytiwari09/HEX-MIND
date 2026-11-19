---
name: accessibility
description: Make interfaces usable with a keyboard, a screen reader and low vision.
---

# Accessibility (WCAG 2.2 AA)

- Use real elements: `button` for actions, `a` for navigation, `label` for inputs, headings in order.
- Everything works with the keyboard alone, with a visible focus outline that is never removed.
- Text contrast is at least 4.5:1 (3:1 for large text and UI controls); never use colour alone to
  carry meaning.
- Images that carry information have `alt` text; decorative ones have `alt=""`.
- Announce changes that matter (form errors, async results) with `role="alert"` or `aria-live`.
- Touch targets are at least 24x24 CSS px. Respect `prefers-reduced-motion`.
- Prefer native semantics over ARIA; add ARIA only where no native element fits.
