#!/usr/bin/env python3
"""List jobs in the Lab registry.

Usage::

    python -m lab.cli.list_jobs
    python -m lab.cli.list_jobs --status running
    python -m lab.cli.list_jobs --id abc123
"""

from __future__ import annotations

import argparse
import json
import sys

from .. import config as cfg
from ..registry import Registry


def main() -> None:
    parser = argparse.ArgumentParser(description="List Lab jobs")
    parser.add_argument("--status", default=None, help="Filter by status")
    parser.add_argument("--id", default=None, help="Show a single job by ID")
    parser.add_argument("--cost-today", action="store_true", help="Show today's total cost")
    args = parser.parse_args()

    registry = Registry(cfg.REGISTRY_DB)

    if args.cost_today:
        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cost = registry.daily_cost(today)
        print(f"Total cost today ({today}): £{cost:.4f}")
        return

    if args.id:
        row = registry.get(args.id)
        if row is None:
            print(f"error: job {args.id} not found", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(row, indent=2, default=str))
        return

    rows = registry.list_all(status=args.status)
    if not rows:
        print("No jobs found.")
        return

    # Table output
    fmt = "{:<16} {:<12} {:<14} {:<12} {:<22}"
    print(fmt.format("JOB_ID", "STATUS", "TYPE", "WORKER", "CREATED"))
    print("-" * 78)
    for r in rows:
        print(
            fmt.format(
                r["job_id"][:16],
                r["status"],
                (r["task_type"] or "")[:14],
                (r["worker_id"] or "-")[:12],
                (r["created_at"] or "")[:22],
            )
        )
    print(f"\n{len(rows)} job(s)")


if __name__ == "__main__":
    main()
