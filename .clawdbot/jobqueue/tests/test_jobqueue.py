"""Tests for the job queue system.

All tests use ``tmp_path`` so nothing touches the real filesystem.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Adjust import path — the package lives in .clawdbot/jobqueue.
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from jobqueue.models import Job, JobStatus
from jobqueue.registry import Registry
from jobqueue.queue import JobQueue
from jobqueue.log import RunLogger
from jobqueue.worker import Worker


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    return tmp_path / "queue"


@pytest.fixture()
def registry(root: Path) -> Registry:
    return Registry(root / "registry.db")


@pytest.fixture()
def queue(root: Path, registry: Registry) -> JobQueue:
    return JobQueue(root, registry)


# ------------------------------------------------------------------
# Models
# ------------------------------------------------------------------


class TestJob:
    def test_from_file(self, tmp_path: Path) -> None:
        f = tmp_path / "abc123.json"
        f.write_text(json.dumps({"task": "build"}))
        job = Job.from_file(f)
        assert job.job_id == "abc123"
        assert job.payload == {"task": "build"}
        assert job.status == JobStatus.PENDING

    def test_from_file_with_explicit_id(self, tmp_path: Path) -> None:
        f = tmp_path / "whatever.json"
        f.write_text(json.dumps({"job_id": "custom-id", "x": 1}))
        job = Job.from_file(f)
        assert job.job_id == "custom-id"
        assert "job_id" not in job.payload

    def test_to_dict_round_trip(self) -> None:
        job = Job(job_id="j1", payload={"a": 1}, status=JobStatus.RUNNING)
        d = job.to_dict()
        assert d["status"] == "running"
        assert d["job_id"] == "j1"


# ------------------------------------------------------------------
# Registry
# ------------------------------------------------------------------


class TestRegistry:
    def test_upsert_and_get(self, registry: Registry) -> None:
        job = Job(job_id="r1", payload={"k": "v"})
        registry.upsert(job)
        row = registry.get("r1")
        assert row is not None
        assert row["status"] == "pending"

    def test_set_status(self, registry: Registry) -> None:
        job = Job(job_id="r2", payload={})
        registry.upsert(job)
        registry.set_status("r2", JobStatus.RUNNING)
        assert registry.get("r2")["status"] == "running"

    def test_list_by_status(self, registry: Registry) -> None:
        for i, status in enumerate([JobStatus.PENDING, JobStatus.RUNNING, JobStatus.PENDING]):
            registry.upsert(Job(job_id=f"l{i}", payload={}, status=status))
        assert len(registry.list_by_status(JobStatus.PENDING)) == 2
        assert len(registry.list_by_status(JobStatus.RUNNING)) == 1

    def test_recover_stale(self, registry: Registry) -> None:
        registry.upsert(Job(job_id="s1", payload={}, status=JobStatus.RUNNING))
        registry.upsert(Job(job_id="s2", payload={}, status=JobStatus.CLAIMED))
        registry.upsert(Job(job_id="s3", payload={}, status=JobStatus.COMPLETED))
        recovered = registry.recover_stale()
        assert set(recovered) == {"s1", "s2"}
        assert registry.get("s1")["status"] == "pending"
        assert registry.get("s3")["status"] == "completed"

    def test_get_missing_returns_none(self, registry: Registry) -> None:
        assert registry.get("nonexistent") is None


# ------------------------------------------------------------------
# Queue
# ------------------------------------------------------------------


class TestQueue:
    def test_submit_creates_pending_file(self, queue: JobQueue, root: Path) -> None:
        job = queue.submit({"task": "test"}, job_id="q1")
        assert job.job_id == "q1"
        assert (root / "pending" / "q1.json").exists()

    def test_submit_duplicate_raises(self, queue: JobQueue) -> None:
        queue.submit({"a": 1}, job_id="dup")
        with pytest.raises(FileExistsError):
            queue.submit({"a": 2}, job_id="dup")

    def test_claim_moves_file_atomically(self, queue: JobQueue, root: Path) -> None:
        queue.submit({"x": 1}, job_id="c1")
        job = queue.claim("worker-a")
        assert job is not None
        assert job.job_id == "c1"
        assert job.worker_id == "worker-a"
        assert not (root / "pending" / "c1.json").exists()
        assert (root / "claimed" / "c1.json").exists()

    def test_claim_empty_returns_none(self, queue: JobQueue) -> None:
        assert queue.claim("worker-a") is None

    def test_complete_archives_to_done(self, queue: JobQueue, root: Path) -> None:
        queue.submit({"x": 1}, job_id="d1")
        job = queue.claim("worker-a")
        queue.complete(job, cost_estimate=0.05)
        assert (root / "done" / "d1.json").exists()
        assert not (root / "claimed" / "d1.json").exists()

    def test_fail_archives_to_failed(self, queue: JobQueue, root: Path) -> None:
        queue.submit({"x": 1}, job_id="f1")
        job = queue.claim("worker-a")
        queue.fail(job, "something broke")
        assert (root / "failed" / "f1.json").exists()
        assert job.error == "something broke"

    def test_recover_moves_claimed_back(self, queue: JobQueue, root: Path) -> None:
        queue.submit({"x": 1}, job_id="rv1")
        queue.claim("worker-a")
        # Simulate crash — file is in claimed/.
        recovered = queue.recover()
        assert "rv1" in recovered
        assert (root / "pending" / "rv1.json").exists()

    def test_fifo_ordering(self, queue: JobQueue) -> None:
        """Jobs should be claimed in submission order (oldest first)."""
        import time

        for i in range(3):
            queue.submit({"seq": i}, job_id=f"ord{i}")
            time.sleep(0.05)  # Ensure distinct mtime.
        ids = []
        while True:
            job = queue.claim("worker-a")
            if job is None:
                break
            ids.append(job.job_id)
        assert ids == ["ord0", "ord1", "ord2"]

    def test_pending_count(self, queue: JobQueue) -> None:
        assert queue.pending_count() == 0
        queue.submit({"a": 1}, job_id="pc1")
        queue.submit({"a": 2}, job_id="pc2")
        assert queue.pending_count() == 2


# ------------------------------------------------------------------
# Logger
# ------------------------------------------------------------------


class TestRunLogger:
    def test_log_and_read(self, tmp_path: Path) -> None:
        logger = RunLogger(tmp_path / "logs" / "runs.jsonl")
        logger.log(event="started", job_id="lg1", worker_id="w1")
        logger.log(event="completed", job_id="lg1", worker_id="w1", cost_estimate=0.1)
        entries = logger.read_all()
        assert len(entries) == 2
        assert entries[0]["event"] == "started"
        assert entries[1]["cost_estimate"] == 0.1

    def test_read_empty(self, tmp_path: Path) -> None:
        logger = RunLogger(tmp_path / "empty.jsonl")
        assert logger.read_all() == []


# ------------------------------------------------------------------
# Worker
# ------------------------------------------------------------------


class TestWorker:
    def test_run_once_no_jobs(self, root: Path) -> None:
        worker = Worker(root, lambda j, d: None, worker_id="test-w")
        assert worker.run_once() is False

    def test_run_once_executes_handler(self, root: Path) -> None:
        reg = Registry(root / "registry.db")
        queue = JobQueue(root, reg)
        queue.submit({"value": 42}, job_id="w1")

        results = []

        def handler(job: Job, art_dir: Path) -> float | None:
            results.append(job.payload["value"])
            (art_dir / "output.txt").write_text("done")
            return 0.01

        worker = Worker(root, handler, worker_id="test-w")
        assert worker.run_once() is True
        assert results == [42]

        # Verify artefact was written.
        art = root / "artefacts" / "w1" / "output.txt"
        assert art.exists()
        assert art.read_text() == "done"

        # Verify manifest was created.
        manifest = root / "artefacts" / "w1" / "manifest.json"
        assert manifest.exists()

        # Verify registry shows completed.
        row = reg.get("w1")
        assert row["status"] == "completed"
        assert row["cost_estimate"] == 0.01

    def test_run_once_handler_failure(self, root: Path) -> None:
        reg = Registry(root / "registry.db")
        queue = JobQueue(root, reg)
        queue.submit({"bad": True}, job_id="fail1")

        def bad_handler(job: Job, art_dir: Path) -> float | None:
            raise ValueError("intentional test error")

        worker = Worker(root, bad_handler, worker_id="test-w")
        assert worker.run_once() is True

        row = reg.get("fail1")
        assert row["status"] == "failed"
        assert "intentional test error" in row["error"]

        # Verify structured log captured the failure.
        log = RunLogger(root / "logs" / "runs.jsonl")
        entries = log.read_all()
        fail_entries = [e for e in entries if e["event"] == "failed"]
        assert len(fail_entries) == 1
