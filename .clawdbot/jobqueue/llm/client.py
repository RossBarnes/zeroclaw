"""Unified LLM client wrapping OpenAI and Anthropic APIs.

Usage::

    from jobqueue.llm import LLMClient

    llm = LLMClient(job_id="task-42")

    # OpenAI
    reply = llm.chat("gpt-4o-mini", [{"role": "user", "content": "hi"}])

    # Claude
    reply = llm.chat("claude-sonnet-4-20250514", [{"role": "user", "content": "hi"}])

Every call records model, tokens, and estimated cost to the cost ledger.
API keys are read from environment variables (``OPENAI_API_KEY``,
``ANTHROPIC_API_KEY``).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .costs import CostLedger, estimate_cost

# Provider detection by model name prefix.
_ANTHROPIC_PREFIXES = ("claude-",)
_OPENAI_PREFIXES = ("gpt-", "o1", "o3", "o4")


def _is_anthropic(model: str) -> bool:
    return any(model.startswith(p) for p in _ANTHROPIC_PREFIXES)


class LLMClient:
    """Thin wrapper that dispatches to OpenAI or Anthropic based on model name."""

    def __init__(
        self,
        *,
        job_id: str | None = None,
        ledger_path: Path | None = None,
        openai_api_key: str | None = None,
        anthropic_api_key: str | None = None,
    ) -> None:
        self._job_id = job_id
        self._ledger = CostLedger(ledger_path)
        self._openai_key = openai_api_key or os.environ.get("OPENAI_API_KEY")
        self._anthropic_key = anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")

        # Lazily initialised SDK clients.
        self._openai_client: Any | None = None
        self._anthropic_client: Any | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        job_id: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Send a chat completion request and return the assistant text.

        Automatically routes to the correct provider based on *model*.
        """
        effective_job_id = job_id or self._job_id

        if _is_anthropic(model):
            text, tokens_in, tokens_out = self._call_anthropic(
                model, messages, max_tokens=max_tokens, temperature=temperature, **kwargs
            )
        else:
            text, tokens_in, tokens_out = self._call_openai(
                model, messages, max_tokens=max_tokens, temperature=temperature, **kwargs
            )

        cost = estimate_cost(model, tokens_in, tokens_out)
        self._ledger.record(
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost=cost,
            job_id=effective_job_id,
        )
        return text

    @property
    def ledger(self) -> CostLedger:
        return self._ledger

    # ------------------------------------------------------------------
    # OpenAI
    # ------------------------------------------------------------------

    def _get_openai(self) -> Any:
        if self._openai_client is None:
            if not self._openai_key:
                raise ValueError(
                    "OpenAI API key required. Set OPENAI_API_KEY or pass openai_api_key."
                )
            from openai import OpenAI

            self._openai_client = OpenAI(api_key=self._openai_key)
        return self._openai_client

    def _call_openai(
        self,
        model: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> tuple[str, int, int]:
        client = self._get_openai()
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            **kwargs,
        )
        text = resp.choices[0].message.content or ""
        usage = resp.usage
        return text, usage.prompt_tokens, usage.completion_tokens

    # ------------------------------------------------------------------
    # Anthropic
    # ------------------------------------------------------------------

    def _get_anthropic(self) -> Any:
        if self._anthropic_client is None:
            if not self._anthropic_key:
                raise ValueError(
                    "Anthropic API key required. Set ANTHROPIC_API_KEY or pass anthropic_api_key."
                )
            from anthropic import Anthropic

            self._anthropic_client = Anthropic(api_key=self._anthropic_key)
        return self._anthropic_client

    def _call_anthropic(
        self,
        model: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> tuple[str, int, int]:
        client = self._get_anthropic()

        # Anthropic requires system message to be a top-level param, not in messages.
        system_text: str | None = None
        filtered: list[dict[str, str]] = []
        for msg in messages:
            if msg["role"] == "system":
                system_text = msg["content"]
            else:
                filtered.append(msg)

        create_kwargs: dict[str, Any] = {
            "model": model,
            "messages": filtered,
            **kwargs,
        }
        if system_text is not None:
            create_kwargs["system"] = system_text

        resp = client.messages.create(**create_kwargs)
        text = resp.content[0].text if resp.content else ""
        return text, resp.usage.input_tokens, resp.usage.output_tokens
