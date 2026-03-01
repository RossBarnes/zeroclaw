"""Data models matching job_schema.json."""

from __future__ import annotations

import enum
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"  # requires approval


class RiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class TaskSpec:
    type: str  # agent_run, build, test, lint, summarise, embeddings
    command: str
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)


@dataclass
class Policy:
    risk_level: RiskLevel = RiskLevel.LOW
    requires_approval: bool = False
    max_cost_gbp: float = 2.0
    max_runtime_minutes: int = 60


@dataclass
class Routing:
    preferred_capabilities: list[str] = field(default_factory=list)
    allow_nodes: list[str] = field(default_factory=list)
    deny_nodes: list[str] = field(default_factory=list)


@dataclass
class LabJob:
    """Full job envelope matching job_schema.json."""

    job_id: str
    task: TaskSpec
    created_at: str = ""
    submitted_by: str = "operator"
    repo_url: str = ""
    repo_ref: str = ""
    policy: Policy = field(default_factory=Policy)
    routing: Routing = field(default_factory=Routing)
    status: JobStatus = JobStatus.PENDING
    worker_id: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    cost_estimate: float | None = None
    artefact_path: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = _now_iso()

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["policy"]["risk_level"] = self.policy.risk_level.value
        d["task"]["type"] = self.task.type
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LabJob:
        task_raw = data.get("task", {})
        task = TaskSpec(
            type=task_raw.get("type", "agent_run"),
            command=task_raw.get("command", ""),
            inputs=task_raw.get("inputs", []),
            outputs=task_raw.get("outputs", []),
        )
        policy_raw = data.get("policy", {})
        policy = Policy(
            risk_level=RiskLevel(policy_raw.get("risk_level", "low")),
            requires_approval=policy_raw.get("requires_approval", False),
            max_cost_gbp=policy_raw.get("max_cost_gbp", 2.0),
            max_runtime_minutes=policy_raw.get("max_runtime_minutes", 60),
        )
        routing_raw = data.get("routing", {})
        routing = Routing(
            preferred_capabilities=routing_raw.get("preferred_capabilities", []),
            allow_nodes=routing_raw.get("allow_nodes", []),
            deny_nodes=routing_raw.get("deny_nodes", []),
        )
        repo = data.get("repo", {})
        return cls(
            job_id=data.get("job_id", uuid.uuid4().hex[:12]),
            task=task,
            created_at=data.get("created_at", ""),
            submitted_by=data.get("submitted_by", "operator"),
            repo_url=repo.get("url", ""),
            repo_ref=repo.get("ref", ""),
            policy=policy,
            routing=routing,
            status=JobStatus(data.get("status", "pending")),
            worker_id=data.get("worker_id"),
            start_time=data.get("start_time"),
            end_time=data.get("end_time"),
            cost_estimate=data.get("cost_estimate"),
            artefact_path=data.get("artefact_path"),
            error=data.get("error"),
        )

    @classmethod
    def from_file(cls, path: Path) -> LabJob:
        with open(path) as f:
            return cls.from_dict(json.load(f))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
