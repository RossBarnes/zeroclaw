# Definition of Done (v1)

A task is considered **done** when all of the following are true:

## Required

1. **PR exists** — An open pull request targeting the base branch.
2. **CI checks green** — At minimum: lint (`cargo fmt`, `clippy`), typecheck, and
   unit tests (if present) must pass.
3. **No merge conflicts** — The PR branch is up to date with the base branch, or
   GitHub reports no conflicts.

## Conditional

4. **UI screenshot required** — If the PR modifies files matching any of:
   - `ui/**`
   - `components/**`
   - `*.tsx`
   - `*.css`

   Then the PR body must contain a line starting with `Screenshot:`.

## Status Mapping

| Condition | Status |
|---|---|
| PR exists, CI pending | `pr_open` |
| PR exists, CI green, no conflicts, screenshot (if needed) | `done` |
| PR exists, CI failing | `failed` |
| PR exists, merge conflicts | `blocked` |
| No PR, agent still running | `running` |
| `gh` CLI not authenticated | `blocked` |
