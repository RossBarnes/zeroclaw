"""Data models for the job queue system."""

from __future__ import annotations

import enum
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


class JobStatus(str, enum.Enum):
    """Lifecycle states for a queued job."""

    PENDING = "pending"
    CLAIMED = "claimed"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Job:
    """A unit of work in the queue.

    The ``payload`` dict is whatever the submitter put in the JSON file.
    Everything else is tracked by the queue / registry.
    """

    job_id: str
    payload: dict[str, Any]
    status: JobStatus = JobStatus.PENDING
    worker_id: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    cost_estimate: float | None = None
    artefact_path: str | None = None
    source_path: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_file(cls, path: Path) -> Job:
        """Load a job from a JSON file on disk.

        The file must contain a JSON object.  If the object has a ``job_id``
        key it is used; otherwise the stem of the filename becomes the id.
        """
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"Job file must contain a JSON object: {path}")
        job_id = data.pop("job_id", path.stem)
        return cls(job_id=str(job_id), payload=data, source_path=str(path))
