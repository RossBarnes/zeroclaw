"""File-based job queue with atomic POSIX claiming.

Directory layout managed by the queue::

    <root>/
    ├── pending/      # Drop job JSON files here
    ├── claimed/      # Atomically moved when a worker grabs a job
    ├── done/         # Completed jobs archived here
    └── failed/       # Failed jobs moved here

Claiming uses ``os.rename()`` which is atomic on POSIX (macOS / Linux)
when source and destination are on the same filesystem.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .models import Job, JobStatus
from .registry import Registry


class JobQueue:
    """Manages the on-disk job directories and coordinates with the registry."""

    def __init__(self, root: Path, registry: Registry) -> None:
        self._root = root
        self._registry = registry

        # Ensure directory structure exists.
        for subdir in ("pending", "claimed", "done", "failed"):
            (root / subdir).mkdir(parents=True, exist_ok=True)

        # Artefact output lives beside the queue dirs.
        self._artefacts = root / "artefacts"
        self._artefacts.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------

    def submit(self, payload: dict, job_id: str | None = None) -> Job:
        """Write a new job JSON file into ``pending/`` and register it."""
        if job_id is None:
            job_id = uuid.uuid4().hex[:12]

        dest = self._root / "pending" / f"{job_id}.json"
        if dest.exists():
            raise FileExistsError(f"Job file already exists: {dest}")

        # Atomic write: tmp then rename.
        tmp = dest.with_suffix(".tmp")
        data = {**payload, "job_id": job_id}
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.rename(tmp, dest)

        job = Job(job_id=job_id, payload=payload, source_path=str(dest))
        self._registry.upsert(job)
        return job

    # ------------------------------------------------------------------
    # Claim (atomic)
    # ------------------------------------------------------------------

    def claim(self, worker_id: str) -> Job | None:
        """Atomically claim the oldest pending job for *worker_id*.

        Returns ``None`` when the pending directory is empty.
        """
        pending_dir = self._root / "pending"
        # Sort by mtime so oldest job is claimed first.
        candidates = sorted(
            pending_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
        )

        for candidate in candidates:
            claimed_path = self._root / "claimed" / candidate.name
            try:
                os.rename(candidate, claimed_path)
            except FileNotFoundError:
                # Another worker beat us — try the next file.
                continue

            job = Job.from_file(claimed_path)
            job.status = JobStatus.CLAIMED
            job.worker_id = worker_id
            job.start_time = _now_iso()
            job.source_path = str(claimed_path)

            # Prepare artefact directory for this job.
            art_dir = self._artefacts / job.job_id
            art_dir.mkdir(parents=True, exist_ok=True)
            job.artefact_path = str(art_dir)

            self._registry.upsert(job)
            return job

        return None

    # ------------------------------------------------------------------
    # Complete / Fail
    # ------------------------------------------------------------------

    def complete(
        self,
        job: Job,
        *,
        cost_estimate: float | None = None,
    ) -> None:
        """Mark a claimed job as completed and archive its file."""
        job.status = JobStatus.COMPLETED
        job.end_time = _now_iso()
        job.cost_estimate = cost_estimate
        self._registry.upsert(job)
        self._move_job_file(job, "done")

    def fail(self, job: Job, error: str) -> None:
        """Mark a claimed job as failed and archive its file."""
        job.status = JobStatus.FAILED
        job.end_time = _now_iso()
        job.error = error
        self._registry.upsert(job)
        self._move_job_file(job, "failed")

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------

    def recover(self) -> list[str]:
        """Move any files stuck in ``claimed/`` back to ``pending/``.

        Also resets the registry rows.  Returns recovered job ids.
        """
        recovered: list[str] = []
        claimed_dir = self._root / "claimed"
        for path in claimed_dir.glob("*.json"):
            dest = self._root / "pending" / path.name
            os.rename(path, dest)
            recovered.append(path.stem)

        db_recovered = self._registry.recover_stale()
        # Merge both sources (files + DB) for completeness.
        return list(dict.fromkeys(recovered + db_recovered))

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def pending_count(self) -> int:
        return len(list((self._root / "pending").glob("*.json")))

    @property
    def artefacts_dir(self) -> Path:
        return self._artefacts

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _move_job_file(self, job: Job, dest_subdir: str) -> None:
        if job.source_path is None:
            return
        src = Path(job.source_path)
        if not src.exists():
            return
        dest = self._root / dest_subdir / src.name
        shutil.move(str(src), str(dest))
        job.source_path = str(dest)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
