"""Job queue worker.

A worker polls the pending directory, claims a job atomically,
executes the user-supplied callback, writes artefacts, and logs
every lifecycle transition in structured JSON.
"""

from __future__ import annotations

import json
import signal
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from .log import RunLogger
from .models import Job, JobStatus
from .queue import JobQueue
from .registry import Registry

# Type alias for the function a worker calls to "do the work".
# Receives (job, artefact_dir) and returns an optional cost estimate.
JobHandler = Callable[[Job, Path], float | None]


class Worker:
    """Single-threaded worker that claims and executes jobs."""

    def __init__(
        self,
        root: Path,
        handler: JobHandler,
        *,
        worker_id: str | None = None,
        poll_interval: float = 2.0,
    ) -> None:
        self._root = root
        self._handler = handler
        self._worker_id = worker_id or f"w-{uuid.uuid4().hex[:8]}"
        self._poll_interval = poll_interval
        self._running = True

        db_path = root / "registry.db"
        log_path = root / "logs" / "runs.jsonl"

        self._registry = Registry(db_path)
        self._queue = JobQueue(root, self._registry)
        self._logger = RunLogger(log_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def worker_id(self) -> str:
        return self._worker_id

    def run_once(self) -> bool:
        """Claim and execute a single job.  Returns True if a job was processed."""
        job = self._queue.claim(self._worker_id)
        if job is None:
            return False
        self._execute(job)
        return True

    def run_forever(self) -> None:
        """Poll for jobs until interrupted.

        On startup, recovers any jobs left in ``claimed/`` from a
        previous crash.
        """
        self._install_signal_handlers()
        recovered = self._queue.recover()
        if recovered:
            for jid in recovered:
                self._logger.log(
                    event="recovered",
                    job_id=jid,
                    worker_id=self._worker_id,
                    status=JobStatus.PENDING.value,
                )
            _info(f"recovered {len(recovered)} stale job(s)")

        _info(f"worker {self._worker_id} polling {self._root / 'pending'}")
        while self._running:
            if not self.run_once():
                time.sleep(self._poll_interval)

        _info(f"worker {self._worker_id} shutting down")

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def _execute(self, job: Job) -> None:
        art_dir = Path(job.artefact_path) if job.artefact_path else self._queue.artefacts_dir / job.job_id

        self._logger.log(
            event="started",
            job_id=job.job_id,
            worker_id=self._worker_id,
            status=JobStatus.RUNNING.value,
        )
        job.status = JobStatus.RUNNING
        self._registry.upsert(job)

        _info(f"running {job.job_id}")

        try:
            cost = self._handler(job, art_dir)
            self._queue.complete(job, cost_estimate=cost)
            self._logger.log(
                event="completed",
                job_id=job.job_id,
                worker_id=self._worker_id,
                status=JobStatus.COMPLETED.value,
                cost_estimate=cost,
                artefact_path=str(art_dir),
            )
            # Write a manifest of artefacts produced.
            _write_manifest(art_dir, job)
            _info(f"completed {job.job_id}")
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            self._queue.fail(job, error_msg)
            self._logger.log(
                event="failed",
                job_id=job.job_id,
                worker_id=self._worker_id,
                status=JobStatus.FAILED.value,
                error=error_msg,
            )
            _err(f"failed {job.job_id}: {error_msg}")

    # ------------------------------------------------------------------
    # Signal handling for graceful shutdown
    # ------------------------------------------------------------------

    def _install_signal_handlers(self) -> None:
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum: int, _frame: Any) -> None:
        _info(f"received signal {signum}, finishing current job then exiting")
        self._running = False


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _write_manifest(art_dir: Path, job: Job) -> None:
    """Write a JSON manifest listing artefact files."""
    files = [
        str(p.relative_to(art_dir))
        for p in sorted(art_dir.rglob("*"))
        if p.is_file() and p.name != "manifest.json"
    ]
    manifest = {
        "job_id": job.job_id,
        "worker_id": job.worker_id,
        "artefact_count": len(files),
        "files": files,
    }
    with open(art_dir / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)


def _info(msg: str) -> None:
    print(f":: {msg}", file=sys.stderr)


def _err(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
