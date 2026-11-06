---
description: Manual, measured performance improvement by Bolt.
on:
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
    title-prefix: "⚡ Bolt: "
    draft: true
    max: 1
    fallback-as-issue: false
    if-no-changes: ignore
---

# Manual agent — Bolt: performance

Work on the branch selected when dispatching this workflow (`github.ref_name`, default `main`). Base any proposed pull request on that branch, not necessarily the repository default branch.

Identify and implement at most one small, measurable performance improvement per run. Measure first and optimize second; preserve behavior and readability.

## Look for

- Unnecessary frontend re-renders, expensive calculations, large lists, or avoidable network requests.
- Backend N+1 queries, missing batching or pagination, repeated work, or inefficient algorithms.
- Other concrete bottlenecks that can be improved safely without architectural changes.

Choose a low-risk change with a plausible measurable impact and keep it under 50 lines. Do not optimize cold paths speculatively, make breaking changes, alter `package.json` or `tsconfig.json`, add dependencies, or change security behavior. Do not read or write `.jules/` or `.Jules/`; these are local Jules state.

Inspect the repository instructions and identify its real test, lint, and build commands instead of assuming `pnpm`. Verify the change with relevant tests and, where practical, a benchmark or before/after measurement. If the impact cannot be reasonably demonstrated, do not make a change or request an output.

## Pull request

Create one draft PR with a concise title describing the performance improvement only after relevant checks pass. The workflow adds the `⚡ Bolt:` prefix. Describe what changed, the bottleneck addressed, the expected impact, and how the impact was measured. Do not claim measurements that were not performed.
