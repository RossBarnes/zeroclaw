# GEO2 URL e2e pipeline
Add/extend end-to-end tests from URL ingest through generated artifacts.

Requirements:
- Add deterministic E2E fixture for URL ingest to authority/bias/inclusion outputs
- Verify crawl metadata and manifests are preserved
- Keep runtime bounded and test network fully mocked

Acceptance:
- E2E suite includes URL ingest pipeline case
- Tests stable and deterministic
