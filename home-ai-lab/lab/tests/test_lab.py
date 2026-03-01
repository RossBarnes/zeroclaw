"""Tests for the Home AI Lab system.

All tests override LAB_ROOT via monkeypatch so nothing touches /Volumes/Lab.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

# We need to patch config paths before importing anything else.
import lab.config as _cfg


@pytest.fixture(autouse=True)
def _lab_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect all Lab paths to a temp directory for every test."""
    root = tmp_path / "Lab"
    monkeypatch.setattr(_cfg, "LAB_ROOT", root)
    monkeypatch.setattr(_cfg, "QUEUE_DIR", root / "queue")
    monkeypatch.setattr(_cfg, "INBOX_DIR", root / "queue" / "inbox")
    monkeypatch.setattr(_cfg, "CLAIMED_DIR", root / "queue" / "claimed")
    monkeypatch.setattr(_cfg, "DONE_DIR", root / "queue" / "done")
    monkeypatch.setattr(_cfg, "FAILED_DIR", root / "queue" / "failed")
    monkeypatch.setattr(_cfg, "ARTEFACTS_DIR", root / "artefacts")
    monkeypatch.setattr(_cfg, "LOGS_DIR", root / "logs")
    monkeypatch.setattr(_cfg, "INDEX_DIR", root / "index")
    monkeypatch.setattr(_cfg, "REGISTRY_DB", root / "index" / "jobs.sqlite")
    monkeypatch.setattr(_cfg, "COSTS_FILE", root / "index" / "costs.json")
    monkeypatch.setattr(_cfg, "HEARTBEATS_DIR", root / "workers" / "heartbeats")
    monkeypatch.setattr(
        _cfg,
        "ALL_DIRS",
        [
            root / "queue" / "inbox",
            root / "queue" / "claimed",
            root / "queue" / "done",
            root / "queue" / "failed",
            root / "artefacts",
            root / "logs",
            root / "index",
            root / "workers" / "heartbeats",
        ],
    )
    _cfg.ensure_lab_dirs()
    return root


from lab.models import LabJob, TaskSpec, Policy, Routing, JobStatus, RiskLevel
from lab.registry import Registry
from lab.queue import LabQueue
from lab.log import JobLogger
from lab.heartbeat import Heartbeat
from lab.worker import LabWorker


# ------------------------------------------------------------------
# Models
# ------------------------------------------------------------------


class TestModels:
    def test_round_trip(self) -> None:
        job = LabJob(
            job_id="test-1",
            task=TaskSpec(type="build", command="make"),
            policy=Policy(risk_level=RiskLevel.MEDIUM, max_cost_gbp=5.0),
        )
        d = job.to_dict()
        assert d["policy"]["risk_level"] == "medium"
        rebuilt = LabJob.from_dict(d)
        assert rebuilt.job_id == "test-1"
        assert rebuilt.policy.max_cost_gbp == 5.0

    def test_from_file(self, tmp_path: Path) -> None:
        data = {
            "job_id": "file-1",
            "task": {"type": "test", "command": "pytest"},
        }
        f = tmp_path / "file-1.json"
        f.write_text(json.dumps(data))
        job = LabJob.from_file(f)
        assert job.job_id == "file-1"
        assert job.task.command == "pytest"


# ------------------------------------------------------------------
# Registry
# ------------------------------------------------------------------


class TestRegistry:
    def test_upsert_and_get(self, _lab_root: Path) -> None:
        reg = Registry(_cfg.REGISTRY_DB)
        job = LabJob(job_id="r1", task=TaskSpec(type="test", command="echo"))
        reg.upsert(job)
        row = reg.get("r1")
        assert row is not None
        assert row["status"] == "pending"
        assert row["task_type"] == "test"

    def test_daily_cost(self, _lab_root: Path) -> None:
        reg = Registry(_cfg.REGISTRY_DB)
        job = LabJob(job_id="c1", task=TaskSpec(type="test", command="x"), cost_estimate=1.5)
        job.created_at = "2026-03-01T10:00:00Z"
        reg.upsert(job)
        assert reg.daily_cost("2026-03-01") == 1.5
        assert reg.daily_cost("2026-03-02") == 0.0

    def test_recover_stale(self, _lab_root: Path) -> None:
        reg = Registry(_cfg.REGISTRY_DB)
        job = LabJob(job_id="s1", task=TaskSpec(type="x", command="x"), status=JobStatus.RUNNING)
        reg.upsert(job)
        recovered = reg.recover_stale()
        assert "s1" in recovered
        assert reg.get("s1")["status"] == "pending"


# ------------------------------------------------------------------
# Queue
# ------------------------------------------------------------------


class TestQueue:
    def test_submit_and_claim(self, _lab_root: Path) -> None:
        reg = Registry(_cfg.REGISTRY_DB)
        q = LabQueue(reg)
        job = LabJob(job_id="q1", task=TaskSpec(type="build", command="make"))
        q.submit(job)
        assert (_cfg.INBOX_DIR / "q1.json").exists()

        claimed = q.claim("w1")
        assert claimed is not None
        assert claimed.job_id == "q1"
        assert claimed.worker_id == "w1"
        assert not (_cfg.INBOX_DIR / "q1.json").exists()

    def test_claim_empty(self, _lab_root: Path) -> None:
        reg = Registry(_cfg.REGISTRY_DB)
        q = LabQueue(reg)
        assert q.claim("w1") is None

    def test_capability_routing(self, _lab_root: Path) -> None:
        reg = Registry(_cfg.REGISTRY_DB)
        q = LabQueue(reg)
        job = LabJob(
            job_id="cap1",
            task=TaskSpec(type="test", command="pytest"),
            routing=Routing(preferred_capabilities=["test"]),
        )
        q.submit(job)

        # Worker without matching caps should not claim.
        assert q.claim("w-summarise", capabilities=["summarise"]) is None
        # Worker with matching caps should claim.
        claimed = q.claim("w-test", capabilities=["test", "lint"])
        assert claimed is not None
        assert claimed.job_id == "cap1"

    def test_deny_node_routing(self, _lab_root: Path) -> None:
        reg = Registry(_cfg.REGISTRY_DB)
        q = LabQueue(reg)
        job = LabJob(
            job_id="deny1",
            task=TaskSpec(type="build", command="make"),
            routing=Routing(deny_nodes=["imac-legacy"]),
        )
        q.submit(job)
        assert q.claim("imac-legacy") is None
        claimed = q.claim("m4-worker")
        assert claimed is not None

    def test_risk_gate_blocks_high_risk(self, _lab_root: Path) -> None:
        reg = Registry(_cfg.REGISTRY_DB)
        q = LabQueue(reg)
        job = LabJob(
            job_id="risky1",
            task=TaskSpec(type="agent_run", command="danger"),
            policy=Policy(risk_level=RiskLevel.HIGH, requires_approval=True),
        )
        q.submit(job)
        # Should not be claimable.
        assert q.claim("w1") is None
        # Should be marked blocked in registry.
        row = reg.get("risky1")
        assert row["status"] == "blocked"

    def test_complete_and_fail(self, _lab_root: Path) -> None:
        reg = Registry(_cfg.REGISTRY_DB)
        q = LabQueue(reg)

        j1 = LabJob(job_id="ok1", task=TaskSpec(type="test", command="echo ok"))
        j2 = LabJob(job_id="bad1", task=TaskSpec(type="test", command="false"))
        q.submit(j1)
        q.submit(j2)

        c1 = q.claim("w1")
        q.complete(c1, cost_estimate=0.01)
        assert (_cfg.DONE_DIR / "ok1.json").exists()

        c2 = q.claim("w1")
        q.fail(c2, "nonzero exit")
        assert (_cfg.FAILED_DIR / "bad1.json").exists()

    def test_recover(self, _lab_root: Path) -> None:
        reg = Registry(_cfg.REGISTRY_DB)
        q = LabQueue(reg)
        job = LabJob(job_id="rec1", task=TaskSpec(type="test", command="x"))
        q.submit(job)
        q.claim("w1")
        recovered = q.recover()
        assert "rec1" in recovered
        assert (_cfg.INBOX_DIR / "rec1.json").exists()

    def test_fifo_ordering(self, _lab_root: Path) -> None:
        reg = Registry(_cfg.REGISTRY_DB)
        q = LabQueue(reg)
        for i in range(3):
            q.submit(LabJob(job_id=f"ord{i}", task=TaskSpec(type="test", command="x")))
            time.sleep(0.05)
        ids = []
        while True:
            c = q.claim("w1")
            if c is None:
                break
            ids.append(c.job_id)
        assert ids == ["ord0", "ord1", "ord2"]


# ------------------------------------------------------------------
# Logger
# ------------------------------------------------------------------


class TestJobLogger:
    def test_log_and_read(self, _lab_root: Path) -> None:
        lg = JobLogger("lg1", log_dir=_cfg.LOGS_DIR)
        lg.log("started", worker_id="w1")
        lg.log("completed", worker_id="w1", cost=0.05)
        entries = lg.read_all()
        assert len(entries) == 2
        assert entries[0]["event"] == "started"


# ------------------------------------------------------------------
# Heartbeat
# ------------------------------------------------------------------


class TestHeartbeat:
    def test_write_once(self, _lab_root: Path) -> None:
        hb = Heartbeat("test-w", capabilities=["test"], heartbeat_dir=_cfg.HEARTBEATS_DIR)
        data = hb.write_once()
        assert data["worker_id"] == "test-w"
        assert "test" in data["capabilities"]
        assert (_cfg.HEARTBEATS_DIR / "test-w.json").exists()

    def test_current_job_tracking(self, _lab_root: Path) -> None:
        hb = Heartbeat("test-w", heartbeat_dir=_cfg.HEARTBEATS_DIR)
        hb.set_current_job("j42")
        data = hb.write_once()
        assert data["current_job"] == "j42"


# ------------------------------------------------------------------
# Worker (single-shot)
# ------------------------------------------------------------------


class TestWorker:
    def test_executes_command(self, _lab_root: Path) -> None:
        reg = Registry(_cfg.REGISTRY_DB)
        q = LabQueue(reg)
        job = LabJob(
            job_id="wk1",
            task=TaskSpec(type="test", command="echo hello-lab"),
        )
        q.submit(job)

        worker = LabWorker("test-w", poll_interval=0.1)
        assert worker._run_once() is True

        row = reg.get("wk1")
        assert row["status"] == "completed"
        # stdout artefact should exist.
        art = _cfg.ARTEFACTS_DIR / "wk1" / "stdout.txt"
        assert art.exists()
        assert "hello-lab" in art.read_text()

    def test_failing_command(self, _lab_root: Path) -> None:
        reg = Registry(_cfg.REGISTRY_DB)
        q = LabQueue(reg)
        job = LabJob(
            job_id="wk2",
            task=TaskSpec(type="test", command="exit 1"),
        )
        q.submit(job)

        worker = LabWorker("test-w", poll_interval=0.1)
        worker._run_once()

        row = reg.get("wk2")
        assert row["status"] == "failed"
        assert "exit code 1" in row["error"]

    def test_no_jobs(self, _lab_root: Path) -> None:
        worker = LabWorker("test-w", poll_interval=0.1)
        assert worker._run_once() is False
