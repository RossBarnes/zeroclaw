"""Lab worker daemon.

Polls the inbox, claims jobs matching its capabilities, executes
``task.command``, writes artefacts and JSONL logs, enforces policy
limits, and emits heartbeats every 10 seconds.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config as cfg
from .heartbeat import Heartbeat
from .log import JobLogger
from .models import LabJob, JobStatus
from .queue import LabQueue
from .registry import Registry

# Import cost ledger from the jobqueue.llm package (sibling package).
_COST_LEDGER_AVAILABLE = False
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".clawdbot"))
    from jobqueue.llm.costs import CostLedger

    _COST_LEDGER_AVAILABLE = True
except ImportError:
    pass


class LabWorker:
    """Single-threaded worker that claims and executes lab jobs."""

    def __init__(
        self,
        worker_id: str,
        capabilities: list[str] | None = None,
        poll_interval: float = 2.0,
        daily_cost_limit: float = 50.0,
    ) -> None:
        self._worker_id = worker_id
        self._capabilities = capabilities or []
        self._poll_interval = poll_interval
        self._daily_cost_limit = daily_cost_limit
        self._running = True

        self._registry = Registry(cfg.REGISTRY_DB)
        self._queue = LabQueue(self._registry)
        self._heartbeat = Heartbeat(
            worker_id, capabilities=self._capabilities, interval=10.0
        )

    @property
    def worker_id(self) -> str:
        return self._worker_id

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run_forever(self) -> None:
        self._install_signals()
        recovered = self._queue.recover()
        if recovered:
            _info(f"recovered {len(recovered)} stale job(s)")

        self._heartbeat.start()
        _info(f"worker {self._worker_id} started "
              f"[caps={self._capabilities}, poll={self._poll_interval}s]")

        try:
            while self._running:
                if not self._run_once():
                    time.sleep(self._poll_interval)
        finally:
            self._heartbeat.stop()
            _info(f"worker {self._worker_id} stopped")

    def _run_once(self) -> bool:
        job = self._queue.claim(self._worker_id, capabilities=self._capabilities)
        if job is None:
            return False

        # Daily cost check
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        spent = self._registry.daily_cost(today)
        if spent >= self._daily_cost_limit:
            _info(f"daily cost limit reached ({spent:.2f} >= {self._daily_cost_limit})")
            self._queue.fail(job, f"daily cost limit exceeded: {spent:.2f}")
            return True

        self._execute(job)
        return True

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def _execute(self, job: LabJob) -> None:
        logger = JobLogger(job.job_id)
        art_dir = Path(job.artefact_path) if job.artefact_path else cfg.ARTEFACTS_DIR / job.job_id
        art_dir.mkdir(parents=True, exist_ok=True)

        self._heartbeat.set_current_job(job.job_id)
        logger.log("started", worker_id=self._worker_id, command=job.task.command)

        job.status = JobStatus.RUNNING
        self._registry.upsert(job)
        _info(f"running {job.job_id}: {job.task.command[:80]}")

        try:
            # Enforce runtime limit
            timeout = job.policy.max_runtime_minutes * 60

            result = subprocess.run(
                job.task.command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=str(art_dir),
                timeout=timeout,
            )

            # Persist stdout/stderr as artefacts.
            if result.stdout:
                (art_dir / "stdout.txt").write_text(result.stdout)
            if result.stderr:
                (art_dir / "stderr.txt").write_text(result.stderr)

            if result.returncode != 0:
                raise RuntimeError(
                    f"exit code {result.returncode}: {result.stderr[:500]}"
                )

            self._queue.complete(job)
            logger.log("completed", worker_id=self._worker_id)
            _info(f"completed {job.job_id}")

        except subprocess.TimeoutExpired:
            error = f"timed out after {job.policy.max_runtime_minutes} minutes"
            self._queue.fail(job, error)
            logger.log("failed", worker_id=self._worker_id, error=error)
            _err(f"timeout {job.job_id}")

        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self._queue.fail(job, error)
            logger.log("failed", worker_id=self._worker_id, error=error)
            _err(f"failed {job.job_id}: {error}")

        finally:
            self._heartbeat.set_current_job(None)

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def _install_signals(self) -> None:
        signal.signal(signal.SIGINT, self._handle)
        signal.signal(signal.SIGTERM, self._handle)

    def _handle(self, signum: int, _: Any) -> None:
        _info(f"signal {signum}, finishing current job then exiting")
        self._running = False


def _info(msg: str) -> None:
    print(f":: {msg}", file=sys.stderr)


def _err(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
