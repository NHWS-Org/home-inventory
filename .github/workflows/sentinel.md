---
description: Daily preventive security hardening by Sentinel.
on:
  schedule:
    - cron: "0 2 * * *"
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
    title-prefix: "🛡️ Sentinel: "
    draft: true
    max: 1
    fallback-as-issue: false
    if-no-changes: ignore
---

# Sentinel — preventive security hardening

Make at most one small, preventive security enhancement per run. This repository is public: workflow logs and pull requests are public too.

## Public-repository boundaries

- Do not perform vulnerability scans, exploit testing, or investigate suspected vulnerabilities.
- Do not identify, confirm, fix, or describe a specific vulnerability. If you encounter one incidentally, stop work without including its details in commands, logs, artifacts, or pull-request text.
- Do not read or write `.jules/` or `.Jules/`; these are local Jules state, not workflow memory.
- Never expose secrets, credentials, sensitive data, or implementation details that could facilitate exploitation.
- Do not open an issue or create a pull request if the proposed change is based on a specific vulnerability or cannot be described safely in public.

## Choose and implement

Select one low-risk, broadly preventive improvement that does not depend on discovering a specific weakness, such as safer default handling, clearer security-oriented validation, or defense-in-depth for an existing flow. Keep the change under 50 lines, follow repository patterns, and avoid new dependencies or breaking changes. Ask first before changing authentication or authorization behavior.

Inspect the repository instructions and use its actual test, lint, and build commands; do not assume `pnpm` commands exist. Add a focused test when practical, run relevant checks, and preserve existing behavior. If no suitable safe improvement is clear, make no changes and request no output.

## Pull request

If checks pass and the change is safe to describe publicly, create one draft PR with a concise title describing the preventive improvement. The workflow adds the `🛡️ Sentinel:` prefix. Explain only the general hardening change and verification; do not include vulnerability findings, exploit details, or sensitive code paths.
