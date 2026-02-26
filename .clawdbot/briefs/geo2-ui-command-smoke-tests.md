# GEO2 UI command + smoke tests
Harden and finish the GEO2 UI surface exposed by recent frontend work.

Requirements:
- Ensure a stable CLI entrypoint for UI serving/preview
- Add smoke tests for UI API summary endpoint behavior
- Validate default run handling and error paths
- Keep implementation deterministic and lightweight

Acceptance:
- UI CLI command works from clean checkout
- New tests pass locally and in CI
- No unrelated refactors
