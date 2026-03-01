"""Per-job structured JSONL logger.

Each job gets its own log file at ``/Volumes/Lab/logs/<job_id>.jsonl``.
Writes are atomic via O_APPEND.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config as cfg


class JobLogger:
    """Append-only JSONL logger scoped to a single job."""

    def __init__(self, job_id: str, log_dir: Path | None = None) -> None:
        self._job_id = job_id
        d = log_dir or cfg.LOGS_DIR
        d.mkdir(parents=True, exist_ok=True)
        self._path = d / f"{job_id}.jsonl"

    @property
    def path(self) -> Path:
        return self._path

    def log(self, event: str, **data: Any) -> None:
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "job_id": self._job_id,
            "event": event,
        }
        entry.update(data)
        line = json.dumps(entry, separators=(",", ":")) + "\n"
        fd = os.open(str(self._path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line.encode())
        finally:
            os.close(fd)

    def read_all(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        entries = []
        with open(self._path) as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries
