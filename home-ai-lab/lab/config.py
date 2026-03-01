"""Lab path configuration and constants.

All paths are derived from a single ``LAB_ROOT`` which defaults to
``/Volumes/Lab`` but can be overridden via the ``LAB_ROOT`` environment
variable (useful for development and testing).
"""

from __future__ import annotations

import os
from pathlib import Path

LAB_ROOT = Path(os.environ.get("LAB_ROOT", "/Volumes/Lab"))

# Queue directories
QUEUE_DIR = LAB_ROOT / "queue"
INBOX_DIR = QUEUE_DIR / "inbox"
CLAIMED_DIR = QUEUE_DIR / "claimed"
DONE_DIR = QUEUE_DIR / "done"
FAILED_DIR = QUEUE_DIR / "failed"

# Output directories
ARTEFACTS_DIR = LAB_ROOT / "artefacts"
LOGS_DIR = LAB_ROOT / "logs"

# Index (registry + cost)
INDEX_DIR = LAB_ROOT / "index"
REGISTRY_DB = INDEX_DIR / "jobs.sqlite"
COSTS_FILE = INDEX_DIR / "costs.json"

# Workers
HEARTBEATS_DIR = LAB_ROOT / "workers" / "heartbeats"

# All directories that must exist at startup
ALL_DIRS = [
    INBOX_DIR,
    CLAIMED_DIR,
    DONE_DIR,
    FAILED_DIR,
    ARTEFACTS_DIR,
    LOGS_DIR,
    INDEX_DIR,
    HEARTBEATS_DIR,
]


def ensure_lab_dirs() -> None:
    """Create every required Lab directory if it doesn't exist."""
    for d in ALL_DIRS:
        d.mkdir(parents=True, exist_ok=True)
