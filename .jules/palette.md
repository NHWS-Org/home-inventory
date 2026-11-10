# Palette's Journal

## 2026-11-09 - Accessible password visibility toggle pattern
**Learning:** When adding password visibility toggle buttons inside inputs, inputs require right padding (e.g. `pr-10`) so text never clips behind the button, and icon-only toggle buttons require descriptive, localized Italian `aria-label` and `title` attributes that update dynamically with visibility state (e.g., "Mostra password" / "Nascondi password") alongside keyboard focus rings (`focus-visible:ring-2 focus-visible:ring-blue-500`).
**Action:** When implementing password fields in authentication and settings forms, consistently wrap inputs with `relative`, provide `pr-10`, include dynamic `aria-label`/`title`, and keep `type="button"` on the toggle to prevent unwanted form submissions.
