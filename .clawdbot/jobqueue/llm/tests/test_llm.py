"""Tests for the LLM client wrapper and cost ledger.

All tests use ``tmp_path`` so nothing touches the real ``/Lab/`` directory.
API calls are mocked — no real keys or network needed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from jobqueue.llm.costs import CostLedger, estimate_cost, COST_TABLE
from jobqueue.llm.client import LLMClient, _is_anthropic


# ------------------------------------------------------------------
# Cost estimation
# ------------------------------------------------------------------


class TestEstimateCost:
    def test_known_model(self) -> None:
        cost = estimate_cost("gpt-4o-mini", tokens_in=1000, tokens_out=500)
        expected = (1000 * 0.15 + 500 * 0.60) / 1_000_000
        assert abs(cost - expected) < 1e-10

    def test_prefix_matching(self) -> None:
        """A model like 'gpt-4o-2024-08-06' should match the 'gpt-4o' entry."""
        cost = estimate_cost("gpt-4o-2024-08-06", tokens_in=1000, tokens_out=500)
        expected = (1000 * 2.50 + 500 * 10.00) / 1_000_000
        assert abs(cost - expected) < 1e-10

    def test_unknown_model_returns_zero(self) -> None:
        assert estimate_cost("unknown-model-xyz", 1000, 1000) == 0.0

    def test_claude_model(self) -> None:
        cost = estimate_cost(
            "claude-sonnet-4-20250514", tokens_in=2000, tokens_out=1000
        )
        expected = (2000 * 3.00 + 1000 * 15.00) / 1_000_000
        assert abs(cost - expected) < 1e-10

    def test_zero_tokens(self) -> None:
        assert estimate_cost("gpt-4o", tokens_in=0, tokens_out=0) == 0.0


# ------------------------------------------------------------------
# Cost ledger
# ------------------------------------------------------------------


class TestCostLedger:
    def test_record_creates_file(self, tmp_path: Path) -> None:
        path = tmp_path / "costs.json"
        ledger = CostLedger(path)
        entry = ledger.record(
            model="gpt-4o-mini",
            tokens_in=100,
            tokens_out=50,
            cost=0.001,
            job_id="j1",
        )
        assert path.exists()
        assert entry["model"] == "gpt-4o-mini"
        assert entry["job_id"] == "j1"

    def test_record_appends(self, tmp_path: Path) -> None:
        path = tmp_path / "costs.json"
        ledger = CostLedger(path)
        ledger.record(model="a", tokens_in=1, tokens_out=1, cost=0.01)
        ledger.record(model="b", tokens_in=2, tokens_out=2, cost=0.02)
        entries = ledger.read_all()
        assert len(entries) == 2
        assert entries[0]["model"] == "a"
        assert entries[1]["model"] == "b"

    def test_total_cost(self, tmp_path: Path) -> None:
        path = tmp_path / "costs.json"
        ledger = CostLedger(path)
        ledger.record(model="x", tokens_in=0, tokens_out=0, cost=1.50)
        ledger.record(model="y", tokens_in=0, tokens_out=0, cost=2.25)
        assert abs(ledger.total_cost() - 3.75) < 1e-10

    def test_read_empty(self, tmp_path: Path) -> None:
        ledger = CostLedger(tmp_path / "nope.json")
        assert ledger.read_all() == []

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        deep = tmp_path / "a" / "b" / "c" / "costs.json"
        ledger = CostLedger(deep)
        ledger.record(model="m", tokens_in=1, tokens_out=1, cost=0.0)
        assert deep.exists()

    def test_atomic_write_preserves_on_reread(self, tmp_path: Path) -> None:
        path = tmp_path / "costs.json"
        ledger = CostLedger(path)
        for i in range(10):
            ledger.record(model=f"m{i}", tokens_in=i, tokens_out=i, cost=float(i))
        entries = ledger.read_all()
        assert len(entries) == 10
        assert all(isinstance(e, dict) for e in entries)


# ------------------------------------------------------------------
# Provider detection
# ------------------------------------------------------------------


class TestProviderDetection:
    def test_anthropic_models(self) -> None:
        assert _is_anthropic("claude-sonnet-4-20250514") is True
        assert _is_anthropic("claude-3-opus-20240229") is True

    def test_openai_models(self) -> None:
        assert _is_anthropic("gpt-4o") is False
        assert _is_anthropic("o1-mini") is False


# ------------------------------------------------------------------
# LLMClient with mocked SDK calls
# ------------------------------------------------------------------


def _mock_openai_response(text: str, prompt_tok: int, comp_tok: int) -> MagicMock:
    """Build a fake OpenAI ChatCompletion response."""
    choice = SimpleNamespace(message=SimpleNamespace(content=text))
    usage = SimpleNamespace(prompt_tokens=prompt_tok, completion_tokens=comp_tok)
    return SimpleNamespace(choices=[choice], usage=usage)


def _mock_anthropic_response(text: str, in_tok: int, out_tok: int) -> MagicMock:
    """Build a fake Anthropic Messages response."""
    block = SimpleNamespace(text=text)
    usage = SimpleNamespace(input_tokens=in_tok, output_tokens=out_tok)
    return SimpleNamespace(content=[block], usage=usage)


class TestLLMClientOpenAI:
    def test_chat_calls_openai_and_logs(self, tmp_path: Path) -> None:
        ledger_path = tmp_path / "costs.json"
        client = LLMClient(
            job_id="test-job",
            ledger_path=ledger_path,
            openai_api_key="sk-test",
        )

        mock_resp = _mock_openai_response("hello world", 10, 5)
        mock_oai = MagicMock()
        mock_oai.chat.completions.create.return_value = mock_resp
        client._openai_client = mock_oai

        result = client.chat(
            "gpt-4o-mini",
            [{"role": "user", "content": "hi"}],
        )

        assert result == "hello world"
        mock_oai.chat.completions.create.assert_called_once()

        # Verify ledger entry.
        entries = client.ledger.read_all()
        assert len(entries) == 1
        e = entries[0]
        assert e["model"] == "gpt-4o-mini"
        assert e["tokens_in"] == 10
        assert e["tokens_out"] == 5
        assert e["job_id"] == "test-job"
        assert e["cost_usd"] > 0

    def test_missing_key_raises(self, tmp_path: Path) -> None:
        client = LLMClient(ledger_path=tmp_path / "c.json")
        with pytest.raises(ValueError, match="OpenAI API key"):
            client.chat("gpt-4o", [{"role": "user", "content": "hi"}])


class TestLLMClientAnthropic:
    def test_chat_calls_anthropic_and_logs(self, tmp_path: Path) -> None:
        ledger_path = tmp_path / "costs.json"
        client = LLMClient(
            job_id="job-claude",
            ledger_path=ledger_path,
            anthropic_api_key="sk-ant-test",
        )

        mock_resp = _mock_anthropic_response("bonjour", 20, 8)
        mock_ant = MagicMock()
        mock_ant.messages.create.return_value = mock_resp
        client._anthropic_client = mock_ant

        result = client.chat(
            "claude-sonnet-4-20250514",
            [
                {"role": "system", "content": "be brief"},
                {"role": "user", "content": "hello"},
            ],
        )

        assert result == "bonjour"

        # System message should be extracted to top-level kwarg.
        call_kwargs = mock_ant.messages.create.call_args
        assert call_kwargs.kwargs.get("system") == "be brief"
        msgs = call_kwargs.kwargs["messages"]
        assert all(m["role"] != "system" for m in msgs)

        # Verify ledger.
        entries = client.ledger.read_all()
        assert len(entries) == 1
        assert entries[0]["model"] == "claude-sonnet-4-20250514"
        assert entries[0]["tokens_in"] == 20
        assert entries[0]["tokens_out"] == 8
        assert entries[0]["job_id"] == "job-claude"

    def test_missing_key_raises(self, tmp_path: Path) -> None:
        client = LLMClient(ledger_path=tmp_path / "c.json")
        with pytest.raises(ValueError, match="Anthropic API key"):
            client.chat("claude-sonnet-4-20250514", [{"role": "user", "content": "hi"}])


class TestLLMClientJobIdOverride:
    def test_per_call_job_id(self, tmp_path: Path) -> None:
        ledger_path = tmp_path / "costs.json"
        client = LLMClient(
            job_id="default-job",
            ledger_path=ledger_path,
            openai_api_key="sk-test",
        )
        mock_resp = _mock_openai_response("ok", 5, 3)
        mock_oai = MagicMock()
        mock_oai.chat.completions.create.return_value = mock_resp
        client._openai_client = mock_oai

        client.chat("gpt-4o-mini", [{"role": "user", "content": "a"}], job_id="override-42")
        entries = client.ledger.read_all()
        assert entries[0]["job_id"] == "override-42"
