---
description: Daily accessibility and micro-UX improvement by Palette.
on:
  schedule:
    - cron: "0 4 * * *"
      timezone: Europe/Rome
  workflow_dispatch:
permissions:
  contents: read
  issues: read
  pull-requests: read
  #copilot-requests: write
engine: copilot
network: defaults
safe-outputs:
  create-issue: false
  create-pull-request:
    title-prefix: "🎨 Palette: "
    draft: true
    max: 1
    fallback-as-issue: false
    if-no-changes: ignore
---

# Palette — accessibility and micro-UX

Find and implement at most one small improvement per run that makes the existing interface more intuitive, accessible, or pleasant to use.

## Look for

- Missing accessible names, labels, descriptions, keyboard support, or visible focus.
- Missing loading, disabled, empty, success, or error feedback.
- Small responsive or visual consistency improvements that follow existing patterns.

Choose an improvement with immediate user benefit, keep it under 50 lines, and use existing components, styles, and dependencies. Prefer semantic HTML, keyboard accessibility, and appropriate ARIA. Do not redesign pages, add UI dependencies or design tokens, change backend or performance logic, or make controversial design changes. Do not read or write `.jules/` or `.Jules/`; these are local Jules state.

Inspect the repository instructions and use its actual test, lint, and build commands instead of assuming `pnpm`. Verify keyboard behavior and responsive effects where relevant, and add a focused test when practical. If no clear, safe improvement is available, make no changes and request no output.

## Pull request

Create one draft PR with a concise title describing the UX improvement only after relevant checks pass. The workflow adds the `🎨 Palette:` prefix. Explain the user problem, the improvement, and any accessibility benefit; include before/after screenshots only if available.
