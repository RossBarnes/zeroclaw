# Task: geo2-bias-payloads-2

## Problem Statement

Implement the technical brief exactly as specified.

## Acceptance Criteria

- [ ] All requirements in the brief are implemented
- [ ] Non-goals in the brief are respected
- [ ] Any assumptions are documented in the PR body

## Definition of Done

See: .clawdbot/policies/definition-of-done.md

- [ ] PR exists targeting origin/main
- [ ] CI checks pass
- [ ] No merge conflicts
- [ ] Screenshot included (if UI changes)

## File Scope

(fill based on the brief before coding)

## Technical Brief

# GEO2 Bias Payload Definitions
Define and implement bias payload schemas + initial design contract for GEO2.

Requirements:
- Define explicit bias payload structures (types/interfaces/schema)
- Include payload fields for source, confidence, rationale, and trace metadata
- Document expected producer/consumer contract and validation rules
- Add schema validation and clear error messages for invalid payloads
- Add tests for valid and invalid payload examples

Design goals:
- Keep payloads minimal, explicit, and extensible
- Avoid speculative fields without immediate consumers
- Prioritize deterministic behavior and backwards-compatible evolution notes

Acceptance criteria:
- Bias payload schemas are implemented in-code
- Validation enforced where payloads enter processing pipeline
- Tests cover positive/negative payload cases
