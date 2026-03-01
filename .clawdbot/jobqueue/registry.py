"""SQLite-backed job registry.

Provides durable, restart-safe tracking of every job that passes through
the queue.  Uses WAL mode for safe concurrent reads and atomic writes.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .models import Job, JobStatus

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS jobs (
    job_id         TEXT PRIMARY KEY,
    status         TEXT NOT NULL DEFAULT 'pending',
    worker_id      TEXT,
    start_time     TEXT,
    end_time       TEXT,
    cost_estimate  REAL,
    artefact_path  TEXT,
    payload        TEXT,
    error          TEXT,
    metadata       TEXT
);
"""


class Registry:
    """Thin wrapper around a SQLite database for job state."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._conn = sqlite3.connect(
            str(db_path),
            isolation_level="DEFERRED",
            check_same_thread=False,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def upsert(self, job: Job) -> None:
        """Insert or fully replace a job record."""
        import json

        self._conn.execute(
            """\
            INSERT INTO jobs
                (job_id, status, worker_id, start_time, end_time,
                 cost_estimate, artefact_path, payload, error, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                status        = excluded.status,
                worker_id     = excluded.worker_id,
                start_time    = excluded.start_time,
                end_time      = excluded.end_time,
                cost_estimate = excluded.cost_estimate,
                artefact_path = excluded.artefact_path,
                payload       = excluded.payload,
                error         = excluded.error,
                metadata      = excluded.metadata
            """,
            (
                job.job_id,
                job.status.value,
                job.worker_id,
                job.start_time,
                job.end_time,
                job.cost_estimate,
                job.artefact_path,
                json.dumps(job.payload),
                job.error,
                json.dumps(job.metadata),
            ),
        )
        self._conn.commit()

    def set_status(self, job_id: str, status: JobStatus) -> None:
        self._conn.execute(
            "UPDATE jobs SET status = ? WHERE job_id = ?",
            (status.value, job_id),
        )
        self._conn.commit()

    def update_fields(self, job_id: str, **fields: Any) -> None:
        """Update arbitrary columns on a job row."""
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values())
        vals.append(job_id)
        self._conn.execute(
            f"UPDATE jobs SET {cols} WHERE job_id = ?",  # noqa: S608
            vals,
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get(self, job_id: str) -> dict[str, Any] | None:
        cur = self._conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_dict(cur.description, row)

    def list_by_status(self, status: JobStatus) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT * FROM jobs WHERE status = ? ORDER BY start_time",
            (status.value,),
        )
        return [self._row_to_dict(cur.description, r) for r in cur.fetchall()]

    def list_all(self) -> list[dict[str, Any]]:
        cur = self._conn.execute("SELECT * FROM jobs ORDER BY start_time")
        return [self._row_to_dict(cur.description, r) for r in cur.fetchall()]

    def recover_stale(self) -> list[str]:
        """Find jobs stuck in 'claimed' or 'running' (worker likely died).

        Marks them back to 'pending' so they can be re-claimed.
        Returns the list of recovered job_ids.
        """
        cur = self._conn.execute(
            "SELECT job_id FROM jobs WHERE status IN (?, ?)",
            (JobStatus.CLAIMED.value, JobStatus.RUNNING.value),
        )
        ids = [r[0] for r in cur.fetchall()]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            self._conn.execute(
                f"UPDATE jobs SET status = ?, worker_id = NULL "  # noqa: S608
                f"WHERE job_id IN ({placeholders})",
                [JobStatus.PENDING.value, *ids],
            )
            self._conn.commit()
        return ids

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_dict(
        description: tuple[tuple[str, ...], ...] | Any,
        row: tuple[Any, ...],
    ) -> dict[str, Any]:
        return {col[0]: val for col, val in zip(description, row)}

    def close(self) -> None:
        self._conn.close()
