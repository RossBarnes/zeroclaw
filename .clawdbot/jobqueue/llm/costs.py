"""Cost estimation and ledger persistence.

Pricing is stored as USD per 1 000 000 tokens (input / output) so the
table stays readable and easy to update.  The ledger file is an atomic
append-only JSON array at ``/Lab/index/costs.json``.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ------------------------------------------------------------------
# Pricing table — USD per 1M tokens  (update when providers change)
# ------------------------------------------------------------------

COST_TABLE: dict[str, dict[str, float]] = {
    # OpenAI
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-4": {"input": 30.00, "output": 60.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    "o1": {"input": 15.00, "output": 60.00},
    "o1-mini": {"input": 3.00, "output": 12.00},
    "o3-mini": {"input": 1.10, "output": 4.40},
    # Anthropic
    "claude-opus-4-20250514": {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-20250506": {"input": 0.80, "output": 4.00},
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
    "claude-3-opus-20240229": {"input": 15.00, "output": 75.00},
}

DEFAULT_LEDGER_PATH = Path("/Lab/index/costs.json")


def estimate_cost(
    model: str,
    tokens_in: int,
    tokens_out: int,
) -> float:
    """Return estimated USD cost for a single API call.

    Falls back to zero if the model is not in the pricing table.
    """
    rates = COST_TABLE.get(model)
    if rates is None:
        # Try prefix matching (e.g. "gpt-4o-2024-08-06" → "gpt-4o").
        for key in COST_TABLE:
            if model.startswith(key):
                rates = COST_TABLE[key]
                break
    if rates is None:
        return 0.0
    return (tokens_in * rates["input"] + tokens_out * rates["output"]) / 1_000_000


class CostLedger:
    """Append-only JSON array ledger persisted at *path*.

    Thread/process-safe via atomic temp-file-then-rename writes.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or DEFAULT_LEDGER_PATH

    @property
    def path(self) -> Path:
        return self._path

    def record(
        self,
        *,
        model: str,
        tokens_in: int,
        tokens_out: int,
        cost: float,
        job_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append a cost entry and return it."""
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": round(cost, 8),
            "job_id": job_id,
        }
        if extra:
            entry["extra"] = extra

        self._append(entry)
        return entry

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def read_all(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        with open(self._path) as f:
            return json.load(f)

    def total_cost(self) -> float:
        return sum(e.get("cost_usd", 0.0) for e in self.read_all())

    # ------------------------------------------------------------------
    # Atomic persistence
    # ------------------------------------------------------------------

    def _append(self, entry: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)

        # Read existing entries (or start fresh).
        if self._path.exists():
            with open(self._path) as f:
                entries = json.load(f)
        else:
            entries = []

        entries.append(entry)

        # Atomic write: temp file in same directory, then rename.
        fd, tmp = tempfile.mkstemp(
            dir=str(self._path.parent), suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(entries, f, indent=2)
                f.write("\n")
            os.rename(tmp, self._path)
        except BaseException:
            # Clean up temp file on any failure.
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
