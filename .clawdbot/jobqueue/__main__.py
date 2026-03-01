"""CLI entry point for the job queue.

Usage::

    python -m clawdbot.jobqueue submit  '{"task": "build widget"}'
    python -m clawdbot.jobqueue submit  path/to/job.json
    python -m clawdbot.jobqueue worker  [--poll 2]
    python -m clawdbot.jobqueue status  [<job_id>]
    python -m clawdbot.jobqueue recover
    python -m clawdbot.jobqueue list    [--status pending]

All data lives under JOBQUEUE_ROOT (default: ./.clawdbot/jobqueue_data).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .log import RunLogger
from .models import Job, JobStatus
from .queue import JobQueue
from .registry import Registry
from .worker import Worker


def _default_root() -> Path:
    return Path(
        __import__("os").environ.get(
            "JOBQUEUE_ROOT",
            str(Path.cwd() / ".clawdbot" / "jobqueue_data"),
        )
    )


# ------------------------------------------------------------------
# Sub-commands
# ------------------------------------------------------------------


def cmd_submit(args: argparse.Namespace) -> None:
    root = Path(args.root)
    reg = Registry(root / "registry.db")
    queue = JobQueue(root, reg)

    source = args.payload
    # Detect whether argument is a file path or inline JSON.
    p = Path(source)
    if p.exists() and p.suffix == ".json":
        with open(p) as f:
            payload = json.load(f)
    else:
        payload = json.loads(source)

    job = queue.submit(payload, job_id=args.id)
    print(json.dumps(job.to_dict(), indent=2))


def cmd_worker(args: argparse.Namespace) -> None:
    root = Path(args.root)

    def default_handler(job: Job, art_dir: Path) -> float | None:
        """Execute the ``command`` field from the job payload, if present."""
        cmd = job.payload.get("command")
        if cmd is None:
            # No command — just mark done.
            return None
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            cwd=str(art_dir),
        )
        # Persist stdout / stderr as artefacts.
        if result.stdout:
            (art_dir / "stdout.txt").write_text(result.stdout)
        if result.stderr:
            (art_dir / "stderr.txt").write_text(result.stderr)
        if result.returncode != 0:
            raise RuntimeError(
                f"command exited {result.returncode}: {result.stderr[:500]}"
            )
        return None

    worker = Worker(
        root,
        default_handler,
        worker_id=args.worker_id,
        poll_interval=args.poll,
    )
    worker.run_forever()


def cmd_status(args: argparse.Namespace) -> None:
    root = Path(args.root)
    reg = Registry(root / "registry.db")

    if args.job_id:
        row = reg.get(args.job_id)
        if row is None:
            print(f"error: job {args.job_id} not found", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(row, indent=2, default=str))
    else:
        for row in reg.list_all():
            print(json.dumps(row, default=str))


def cmd_list(args: argparse.Namespace) -> None:
    root = Path(args.root)
    reg = Registry(root / "registry.db")

    if args.status:
        try:
            status = JobStatus(args.status)
        except ValueError:
            print(f"error: unknown status '{args.status}'", file=sys.stderr)
            sys.exit(1)
        rows = reg.list_by_status(status)
    else:
        rows = reg.list_all()

    for row in rows:
        print(json.dumps(row, default=str))


def cmd_recover(args: argparse.Namespace) -> None:
    root = Path(args.root)
    reg = Registry(root / "registry.db")
    queue = JobQueue(root, reg)
    recovered = queue.recover()
    if recovered:
        print(f"recovered {len(recovered)} job(s): {', '.join(recovered)}")
    else:
        print("nothing to recover")


def cmd_logs(args: argparse.Namespace) -> None:
    root = Path(args.root)
    logger = RunLogger(root / "logs" / "runs.jsonl")
    entries = logger.read_all()

    if args.job_id:
        entries = [e for e in entries if e.get("job_id") == args.job_id]

    for entry in entries[-args.tail :]:
        print(json.dumps(entry, default=str))


# ------------------------------------------------------------------
# Argument parser
# ------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jobqueue",
        description="Lightweight file-based job queue with SQLite registry.",
    )
    parser.add_argument(
        "--root",
        default=str(_default_root()),
        help="Queue data directory (default: $JOBQUEUE_ROOT or .clawdbot/jobqueue_data)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # submit
    p_sub = sub.add_parser("submit", help="Submit a new job")
    p_sub.add_argument("payload", help="Inline JSON string or path to a .json file")
    p_sub.add_argument("--id", default=None, help="Explicit job ID (auto-generated if omitted)")

    # worker
    p_work = sub.add_parser("worker", help="Start a worker loop")
    p_work.add_argument("--worker-id", default=None, help="Worker identifier")
    p_work.add_argument("--poll", type=float, default=2.0, help="Poll interval in seconds")

    # status
    p_stat = sub.add_parser("status", help="Show status of a job or all jobs")
    p_stat.add_argument("job_id", nargs="?", default=None, help="Job ID (omit for all)")

    # list
    p_list = sub.add_parser("list", help="List jobs, optionally filtered by status")
    p_list.add_argument("--status", default=None, help="Filter by status")

    # recover
    sub.add_parser("recover", help="Recover stale claimed/running jobs")

    # logs
    p_logs = sub.add_parser("logs", help="Show structured run logs")
    p_logs.add_argument("--job-id", default=None, help="Filter by job ID")
    p_logs.add_argument("--tail", type=int, default=50, help="Show last N entries")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "submit": cmd_submit,
        "worker": cmd_worker,
        "status": cmd_status,
        "list": cmd_list,
        "recover": cmd_recover,
        "logs": cmd_logs,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
