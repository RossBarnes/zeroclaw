"""Unified LLM client wrapper with per-call cost tracking.

Supports OpenAI and Anthropic (Claude) APIs behind a single interface.
Every call is logged to ``/Lab/index/costs.json`` with model, tokens,
estimated cost, and the originating job_id.
"""

from .client import LLMClient
from .costs import CostLedger, COST_TABLE

__all__ = [
    "CostLedger",
    "COST_TABLE",
    "LLMClient",
]
