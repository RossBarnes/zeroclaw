#!/usr/bin/env python3
"""Tail a job's structured log.

Usage::

    python -m lab.cli.tail_log <job_id>
    python -m lab.cli.tail_log <job_id> --follow
    python -m lab.cli.tail_log <job_id> --last 20
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .. import config as cfg


def main() -> None:
    parser = argparse.ArgumentParser(description="Tail a job's JSONL log")
    parser.add_argument("job_id", help="Job ID to tail")
    parser.add_argument("--last", type=int, default=0, help="Show last N entries (0=all)")
    parser.add_argument("--follow", "-f", action="store_true", help="Follow log output")
    args = parser.parse_args()

    log_path = cfg.LOGS_DIR / f"{args.job_id}.jsonl"
    if not log_path.exists():
        print(f"error: no log file for job {args.job_id}", file=sys.stderr)
        sys.exit(1)

    if args.follow:
        _follow(log_path)
    else:
        _dump(log_path, args.last)


def _dump(path: Path, last: int) -> None:
    with open(path) as f:
        lines = [l.strip() for l in f if l.strip()]
    if last > 0:
        lines = lines[-last:]
    for line in lines:
        entry = json.loads(line)
        _pretty(entry)


def _follow(path: Path) -> None:
    """Tail -f style follower."""
    with open(path) as f:
        # Jump to end
        f.seek(0, 2)
        try:
            while True:
                line = f.readline()
                if line:
                    _pretty(json.loads(line.strip()))
                else:
                    time.sleep(0.5)
        except KeyboardInterrupt:
            pass


def _pretty(entry: dict) -> None:
    ts = entry.get("timestamp", "")[:19]
    event = entry.get("event", "?")
    worker = entry.get("worker_id", "")
    error = entry.get("error", "")
    parts = [ts, event]
    if worker:
        parts.append(f"worker={worker}")
    if error:
        parts.append(f"err={error}")
    # Show any extra keys
    skip = {"timestamp", "job_id", "event", "worker_id", "error"}
    extras = {k: v for k, v in entry.items() if k not in skip}
    if extras:
        parts.append(json.dumps(extras, separators=(",", ":")))
    print(" | ".join(parts))


if __name__ == "__main__":
    main()
