# Canonical Lab Paths (must be shared)

Mountpoint: /Volumes/Lab

```
/Volumes/Lab/
  artefacts/        # immutable per job_id
  logs/             # JSONL logs (job_id scoped)
  datasets/         # versioned datasets
  repos/            # worker clones/checkouts (non-authoritative)
  index/            # registry + cost logs + metadata
  queue/
    inbox/          # new jobs arrive here as .json
    claimed/        # claimed jobs moved here
    done/           # completed jobs moved here
    failed/         # failed jobs moved here
  config/
  workers/
    heartbeats/     # worker heartbeat files
```
