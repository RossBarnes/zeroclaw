# GEO2 bias payload consumer integration
Integrate new bias payload contract fields into downstream consumers.

Requirements:
- Ensure run/graph/validation paths consume source/rationale/trace fields safely
- Add compatibility guards for missing optional fields
- Update docs/examples where consumer expectations changed
- Add integration tests for producer->consumer contract

Acceptance:
- Consumer paths handle new payload shape without regressions
- Integration tests pass
