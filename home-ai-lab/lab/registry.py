"""SQLite job registry at /Volumes/Lab/index/jobs.sqlite.

WAL mode for safe concurrent reads from multiple machines over SMB.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import JobStatus, LabJob

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS jobs (
    job_id              TEXT PRIMARY KEY,
    status              TEXT NOT NULL DEFAULT 'pending',
    task_type           TEXT,
    command             TEXT,
    submitted_by        TEXT,
    worker_id           TEXT,
    risk_level          TEXT,
    requires_approval   INTEGER DEFAULT 0,
    max_cost_gbp        REAL,
    max_runtime_minutes INTEGER,
    created_at          TEXT,
    start_time          TEXT,
    end_time            TEXT,
    cost_estimate       REAL,
    artefact_path       TEXT,
    error               TEXT,
    routing             TEXT,
    payload             TEXT
);
"""


class Registry:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(db_path),
            isolation_level="DEFERRED",
            check_same_thread=False,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def upsert(self, job: LabJob) -> None:
        self._conn.execute(
            """\
            INSERT INTO jobs
                (job_id, status, task_type, command, submitted_by,
                 worker_id, risk_level, requires_approval,
                 max_cost_gbp, max_runtime_minutes,
                 created_at, start_time, end_time,
                 cost_estimate, artefact_path, error,
                 routing, payload)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(job_id) DO UPDATE SET
                status=excluded.status,
                worker_id=excluded.worker_id,
                start_time=excluded.start_time,
                end_time=excluded.end_time,
                cost_estimate=excluded.cost_estimate,
                artefact_path=excluded.artefact_path,
                error=excluded.error
            """,
            (
                job.job_id,
                job.status.value,
                job.task.type,
                job.task.command,
                job.submitted_by,
                job.worker_id,
                job.policy.risk_level.value,
                int(job.policy.requires_approval),
                job.policy.max_cost_gbp,
                job.policy.max_runtime_minutes,
                job.created_at,
                job.start_time,
                job.end_time,
                job.cost_estimate,
                job.artefact_path,
                job.error,
                json.dumps(job.routing.__dict__),
                job.to_json(),
            ),
        )
        self._conn.commit()

    def set_status(self, job_id: str, status: JobStatus, **fields: Any) -> None:
        parts = ["status = ?"]
        vals: list[Any] = [status.value]
        for k, v in fields.items():
            parts.append(f"{k} = ?")
            vals.append(v)
        vals.append(job_id)
        self._conn.execute(
            f"UPDATE jobs SET {', '.join(parts)} WHERE job_id = ?",  # noqa: S608
            vals,
        )
        self._conn.commit()

    def get(self, job_id: str) -> dict[str, Any] | None:
        cur = self._conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return {col[0]: val for col, val in zip(cur.description, row)}

    def list_all(self, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            cur = self._conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY created_at", (status,)
            )
        else:
            cur = self._conn.execute("SELECT * FROM jobs ORDER BY created_at")
        return [{col[0]: val for col, val in zip(cur.description, row)} for row in cur.fetchall()]

    def daily_cost(self, date_prefix: str) -> float:
        """Sum cost_estimate for all jobs whose created_at starts with date_prefix (YYYY-MM-DD)."""
        cur = self._conn.execute(
            "SELECT COALESCE(SUM(cost_estimate), 0) FROM jobs WHERE created_at LIKE ?",
            (f"{date_prefix}%",),
        )
        return cur.fetchone()[0]

    def recover_stale(self) -> list[str]:
        cur = self._conn.execute(
            "SELECT job_id FROM jobs WHERE status IN (?, ?)",
            (JobStatus.CLAIMED.value, JobStatus.RUNNING.value),
        )
        ids = [r[0] for r in cur.fetchall()]
        if ids:
            ph = ",".join("?" for _ in ids)
            self._conn.execute(
                f"UPDATE jobs SET status = ?, worker_id = NULL WHERE job_id IN ({ph})",  # noqa: S608
                [JobStatus.PENDING.value, *ids],
            )
            self._conn.commit()
        return ids

    def close(self) -> None:
        self._conn.close()
