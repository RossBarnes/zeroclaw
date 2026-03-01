# Home AI Lab (Ross)

## Goal
Build a small private AI lab across multiple always-on Macs. I want controlled automation, high output per £, minimal redundancy, and one unified output system (no local silos). Agents and outputs must be accessible from every machine.

## Machines
See lab_inventory.yaml.

## Topology (v1)
- Core node (M4 Mac mini with 2TB SSD): orchestration + shared /Lab volume + job index + monitoring
- Primary worker (other M4 Mac mini 16GB): main compute worker + local inference sandbox
- Interactive console (M2 Mac mini): operator console for job submission, approvals, and monitoring; may act as secondary worker
- iMacs: additional worker pool with capability labels (test/lint/summarise/embeddings), always-on.

## Non-negotiables
- All job outputs go to the shared Lab volume only
- Artefacts are immutable per job_id (no overwrites)
- Each job emits structured logs (JSONL)
- Each job is registered in a local SQLite job registry
- Orchestration is simple: directory queue + worker polling is acceptable for v1
- Hard budget controls for cloud calls; log cost per job

## Shared Lab Volume
The core node exports a shared volume mounted on all Macs at the same mountpoint:
- /Volumes/Lab (preferred)
Everything below assumes /Volumes/Lab exists.

## Deliverables (v1)
1) Directory-based job queue with atomic job claiming
2) Worker daemon (macOS launchd) that polls queue and runs jobs
3) Job registry (SQLite) tracking status, timings, worker_id, artefact path, and cost metadata
4) Cost logging wrapper for OpenAI + Claude API calls (JSONL + optional aggregation)
5) Minimal status endpoint/dashboard (FastAPI ok) showing workers and jobs

## Policy
- Concurrency limits per machine
- "Risk level" gate: risky jobs require human approval flag
- Cloud spend limit per day and per job
