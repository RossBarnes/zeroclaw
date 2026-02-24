# Task: geo2-url-crawl-ingestion-2

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

# GEO2 URL Crawl Ingestion
Implement URL ingestion and crawl capability so GEO2 can fetch and process content from a provided URL.

Requirements:
- Add API/backend path to accept a URL input
- Implement safe crawl/fetch flow with domain + protocol validation
- Respect reasonable timeout, size limits, and deterministic error handling
- Extract normalized text/content payload for downstream GEO2 processing
- Add tests for happy path and key failures (invalid URL, timeout, blocked domain, oversized response)

Security constraints:
- Do not broaden execution permissions
- Keep network behavior explicit and bounded
- Fail fast on unsafe/unsupported URL states

Acceptance criteria:
- URL ingestion endpoint/tool works end-to-end
- Crawl results are observable in platform workflow/logs
- Tests pass for key failure modes and normal flow
