#!/usr/bin/env python3
"""Submit a job to the Lab queue.

Usage::

    # From a JSON file
    python -m lab.cli.submit_job job.json

    # Inline
    python -m lab.cli.submit_job --type build --command "make all" --risk low

    # With routing
    python -m lab.cli.submit_job --type test --command "pytest" --caps test,build
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from .. import config as cfg
from ..models import LabJob, TaskSpec, Policy, Routing, RiskLevel
from ..queue import LabQueue
from ..registry import Registry


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit a job to the Lab queue")
    parser.add_argument("file", nargs="?", help="Path to a job JSON file")
    parser.add_argument("--type", dest="task_type", default="agent_run", help="Task type")
    parser.add_argument("--command", default="echo 'no command'", help="Shell command to run")
    parser.add_argument("--risk", default="low", choices=["low", "medium", "high"])
    parser.add_argument("--max-cost", type=float, default=2.0, help="Max cost in GBP")
    parser.add_argument("--max-runtime", type=int, default=60, help="Max runtime in minutes")
    parser.add_argument("--approval", action="store_true", help="Require human approval")
    parser.add_argument("--caps", default="", help="Comma-separated preferred capabilities")
    parser.add_argument("--allow-nodes", default="", help="Comma-separated allowed worker IDs")
    parser.add_argument("--deny-nodes", default="", help="Comma-separated denied worker IDs")
    parser.add_argument("--submitted-by", default="operator")
    parser.add_argument("--id", default=None, help="Explicit job ID")
    args = parser.parse_args()

    cfg.ensure_lab_dirs()
    registry = Registry(cfg.REGISTRY_DB)
    queue = LabQueue(registry)

    if args.file:
        job = LabJob.from_file(Path(args.file))
    else:
        job_id = args.id or f"{args.task_type}-{uuid.uuid4().hex[:8]}"
        caps = [c.strip() for c in args.caps.split(",") if c.strip()]
        allow = [n.strip() for n in args.allow_nodes.split(",") if n.strip()]
        deny = [n.strip() for n in args.deny_nodes.split(",") if n.strip()]

        job = LabJob(
            job_id=job_id,
            task=TaskSpec(type=args.task_type, command=args.command),
            submitted_by=args.submitted_by,
            policy=Policy(
                risk_level=RiskLevel(args.risk),
                requires_approval=args.approval,
                max_cost_gbp=args.max_cost,
                max_runtime_minutes=args.max_runtime,
            ),
            routing=Routing(
                preferred_capabilities=caps,
                allow_nodes=allow,
                deny_nodes=deny,
            ),
        )

    submitted = queue.submit(job)
    print(json.dumps(submitted.to_dict(), indent=2))


if __name__ == "__main__":
    main()
