#!/usr/bin/env python3
"""Start a Lab worker daemon.

Usage::

    python -m lab.cli.run_worker
    python -m lab.cli.run_worker --id m4-worker --caps agent_runs,build,test
    python -m lab.cli.run_worker --caps summarise,embeddings --poll 5
"""

from __future__ import annotations

import argparse
import platform

from ..worker import LabWorker


def main() -> None:
    parser = argparse.ArgumentParser(description="Start a Lab worker")
    parser.add_argument(
        "--id",
        default=None,
        help="Worker ID (defaults to hostname)",
    )
    parser.add_argument(
        "--caps", "--capabilities",
        default="",
        help="Comma-separated capability labels",
    )
    parser.add_argument("--poll", type=float, default=2.0, help="Poll interval (seconds)")
    parser.add_argument(
        "--daily-limit",
        type=float,
        default=50.0,
        help="Daily cost limit in GBP before refusing jobs",
    )
    args = parser.parse_args()

    worker_id = args.id or platform.node()
    capabilities = [c.strip() for c in args.caps.split(",") if c.strip()]

    worker = LabWorker(
        worker_id=worker_id,
        capabilities=capabilities,
        poll_interval=args.poll,
        daily_cost_limit=args.daily_limit,
    )
    worker.run_forever()


if __name__ == "__main__":
    main()
