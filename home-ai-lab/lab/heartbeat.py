"""Worker heartbeat writer.

Each worker writes a small JSON file every N seconds to
``/Volumes/Lab/workers/heartbeats/<worker_id>.json``.
Other machines can read these files to build a live worker inventory.
"""

from __future__ import annotations

import json
import os
import platform
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config as cfg


class Heartbeat:
    """Background heartbeat writer."""

    def __init__(
        self,
        worker_id: str,
        capabilities: list[str] | None = None,
        interval: float = 10.0,
        heartbeat_dir: Path | None = None,
    ) -> None:
        self._worker_id = worker_id
        self._capabilities = capabilities or []
        self._interval = interval
        self._dir = heartbeat_dir or cfg.HEARTBEATS_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / f"{worker_id}.json"
        self._timer: threading.Timer | None = None
        self._running = False
        self._current_job: str | None = None

    @property
    def path(self) -> Path:
        return self._path

    def set_current_job(self, job_id: str | None) -> None:
        self._current_job = job_id

    def write_once(self) -> dict[str, Any]:
        """Write a single heartbeat and return the payload."""
        data: dict[str, Any] = {
            "worker_id": self._worker_id,
            "hostname": platform.node(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "capabilities": self._capabilities,
            "current_job": self._current_job,
            "pid": os.getpid(),
        }
        # Atomic write via temp + rename
        fd, tmp = tempfile.mkstemp(dir=str(self._dir), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.rename(tmp, self._path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return data

    def start(self) -> None:
        """Start periodic heartbeat in background thread."""
        self._running = True
        self._tick()

    def stop(self) -> None:
        """Stop the heartbeat loop and remove the heartbeat file."""
        self._running = False
        if self._timer is not None:
            self._timer.cancel()
        try:
            self._path.unlink(missing_ok=True)
        except OSError:
            pass

    def _tick(self) -> None:
        if not self._running:
            return
        self.write_once()
        self._timer = threading.Timer(self._interval, self._tick)
        self._timer.daemon = True
        self._timer.start()
