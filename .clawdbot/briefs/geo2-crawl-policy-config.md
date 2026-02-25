# GEO2 crawl policy config
Add configurable crawl safety policy for URL ingestion.

Requirements:
- Introduce allow/block domain policy config support
- Preserve secure defaults for localhost/internal/private targets
- Add deterministic validation + clear errors
- Add tests for allowlist, blocklist, and default behavior

Acceptance:
- URL ingest uses config policy consistently
- Tests cover policy permutations
