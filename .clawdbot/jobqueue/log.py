"""Structured JSON run logger.

Appends one JSON object per line (JSONL) to a log file.
Each entry captures the full lifecycle of a single job run.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class RunLogger:
    """Append-only structured logger writing JSONL to disk."""

    def __init__(self, log_path: Path) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._path = log_path

    def log(
        self,
        *,
        event: str,
        job_id: str,
        worker_id: str | None = None,
        status: str | None = None,
        error: str | None = None,
        cost_estimate: float | None = None,
        artefact_path: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Write a single structured log entry."""
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "job_id": job_id,
        }
        if worker_id is not None:
            entry["worker_id"] = worker_id
        if status is not None:
            entry["status"] = status
        if error is not None:
            entry["error"] = error
        if cost_estimate is not None:
            entry["cost_estimate"] = cost_estimate
        if artefact_path is not None:
            entry["artefact_path"] = artefact_path
        if extra:
            entry["extra"] = extra

        line = json.dumps(entry, separators=(",", ":")) + "\n"

        # Atomic append: open in append mode — writes below PIPE_BUF
        # (typically 4096+ bytes) are atomic on POSIX.
        fd = os.open(str(self._path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line.encode())
        finally:
            os.close(fd)

    def read_all(self) -> list[dict[str, Any]]:
        """Read every log entry (for inspection / testing)."""
        if not self._path.exists():
            return []
        entries = []
        with open(self._path) as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries
