"""Directory-based job queue with atomic claiming.

Jobs land in ``inbox/`` as JSON files.  Workers claim by renaming to
``claimed/<job_id>__<worker_id>.json`` — the rename is atomic on POSIX
and prevents two workers from grabbing the same job even over SMB.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import config as cfg
from .models import LabJob, JobStatus, RiskLevel
from .registry import Registry


class LabQueue:
    """Manages the Lab queue directories and registry."""

    def __init__(self, registry: Registry) -> None:
        cfg.ensure_lab_dirs()
        self._registry = registry

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------

    def submit(self, job: LabJob) -> LabJob:
        """Write a job JSON file into inbox/ and register it."""
        dest = cfg.INBOX_DIR / f"{job.job_id}.json"
        if dest.exists():
            raise FileExistsError(f"Job already exists: {dest}")

        # Atomic write
        tmp = dest.with_suffix(".tmp")
        with open(tmp, "w") as f:
            f.write(job.to_json())
        os.rename(tmp, dest)

        self._registry.upsert(job)
        return job

    # ------------------------------------------------------------------
    # Claim (atomic)
    # ------------------------------------------------------------------

    def claim(
        self,
        worker_id: str,
        capabilities: list[str] | None = None,
    ) -> LabJob | None:
        """Atomically claim the oldest inbox job this worker can handle.

        If *capabilities* is given, only jobs whose
        ``routing.preferred_capabilities`` intersect (or are empty) are
        considered.
        """
        candidates = sorted(
            cfg.INBOX_DIR.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
        )

        for candidate in candidates:
            # Read first, check routing, then attempt atomic rename.
            try:
                job = LabJob.from_file(candidate)
            except (json.JSONDecodeError, KeyError):
                continue

            # Routing filter
            if not self._matches_routing(job, worker_id, capabilities):
                continue

            # Policy gate: high-risk + requires_approval blocks claiming.
            if job.policy.requires_approval and job.policy.risk_level == RiskLevel.HIGH:
                job.status = JobStatus.BLOCKED
                self._registry.upsert(job)
                continue

            claimed_name = f"{job.job_id}__{worker_id}.json"
            claimed_path = cfg.CLAIMED_DIR / claimed_name
            try:
                os.rename(candidate, claimed_path)
            except FileNotFoundError:
                continue  # another worker beat us

            job.status = JobStatus.CLAIMED
            job.worker_id = worker_id
            job.start_time = _now_iso()

            art_dir = cfg.ARTEFACTS_DIR / job.job_id
            art_dir.mkdir(parents=True, exist_ok=True)
            job.artefact_path = str(art_dir)

            self._registry.upsert(job)
            return job

        return None

    # ------------------------------------------------------------------
    # Complete / Fail
    # ------------------------------------------------------------------

    def complete(self, job: LabJob, *, cost_estimate: float | None = None) -> None:
        job.status = JobStatus.COMPLETED
        job.end_time = _now_iso()
        job.cost_estimate = cost_estimate
        self._registry.upsert(job)
        self._move_claimed(job, cfg.DONE_DIR)

    def fail(self, job: LabJob, error: str) -> None:
        job.status = JobStatus.FAILED
        job.end_time = _now_iso()
        job.error = error
        self._registry.upsert(job)
        self._move_claimed(job, cfg.FAILED_DIR)

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------

    def recover(self) -> list[str]:
        """Move claimed files back to inbox and reset DB rows."""
        recovered: list[str] = []
        for path in cfg.CLAIMED_DIR.glob("*.json"):
            # filename: <job_id>__<worker_id>.json
            job_id = path.stem.split("__")[0]
            dest = cfg.INBOX_DIR / f"{job_id}.json"
            os.rename(path, dest)
            recovered.append(job_id)
        db_recovered = self._registry.recover_stale()
        return list(dict.fromkeys(recovered + db_recovered))

    def pending_count(self) -> int:
        return len(list(cfg.INBOX_DIR.glob("*.json")))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _matches_routing(
        job: LabJob,
        worker_id: str,
        capabilities: list[str] | None,
    ) -> bool:
        r = job.routing
        if r.deny_nodes and worker_id in r.deny_nodes:
            return False
        if r.allow_nodes and worker_id not in r.allow_nodes:
            return False
        if r.preferred_capabilities and capabilities is not None:
            if not set(r.preferred_capabilities) & set(capabilities):
                return False
        return True

    @staticmethod
    def _move_claimed(job: LabJob, dest_dir: Path) -> None:
        if not job.worker_id:
            return
        src_name = f"{job.job_id}__{job.worker_id}.json"
        src = cfg.CLAIMED_DIR / src_name
        if src.exists():
            shutil.move(str(src), str(dest_dir / f"{job.job_id}.json"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
