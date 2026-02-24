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
