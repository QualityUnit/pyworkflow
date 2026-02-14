"""Tests for token usage tracking."""

from unittest.mock import MagicMock

import pytest

langchain_core = pytest.importorskip("langchain_core")

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from pyworkflow_agents.token_tracking import TokenUsage, TokenUsageTracker


class TestTokenUsage:
    def test_default_values(self):
        usage = TokenUsage()
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.total_tokens == 0
        assert usage.model is None

    def test_add(self):
        a = TokenUsage(input_tokens=10, output_tokens=20, total_tokens=30, model="gpt-4")
        b = TokenUsage(input_tokens=5, output_tokens=15, total_tokens=20)
        result = a + b
        assert result.input_tokens == 15
        assert result.output_tokens == 35
        assert result.total_tokens == 50
        assert result.model == "gpt-4"

    def test_add_preserves_other_model_when_self_none(self):
        a = TokenUsage(input_tokens=10, output_tokens=20, total_tokens=30)
        b = TokenUsage(input_tokens=5, output_tokens=15, total_tokens=20, model="claude-3")
        result = a + b
        assert result.model == "claude-3"

    def test_iadd(self):
        a = TokenUsage(input_tokens=10, output_tokens=20, total_tokens=30, model="gpt-4")
        b = TokenUsage(input_tokens=5, output_tokens=15, total_tokens=20)
        a += b
        assert a.input_tokens == 15
        assert a.output_tokens == 35
        assert a.total_tokens == 50
        assert a.model == "gpt-4"

    def test_iadd_preserves_existing_model(self):
        a = TokenUsage(input_tokens=1, output_tokens=2, total_tokens=3, model="gpt-4")
        b = TokenUsage(input_tokens=1, output_tokens=2, total_tokens=3, model="claude-3")
        a += b
        assert a.model == "gpt-4"

    def test_iadd_sets_model_when_none(self):
        a = TokenUsage(input_tokens=1, output_tokens=2, total_tokens=3)
        b = TokenUsage(input_tokens=1, output_tokens=2, total_tokens=3, model="claude-3")
        a += b
        assert a.model == "claude-3"

    def test_from_message_with_usage_metadata(self):
        msg = AIMessage(content="hello")
        msg.usage_metadata = {
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
        }
        usage = TokenUsage.from_message(msg)
        assert usage.input_tokens == 100
        assert usage.output_tokens == 50
        assert usage.total_tokens == 150

    def test_from_message_without_usage_metadata(self):
        msg = AIMessage(content="hello")
        msg.usage_metadata = None
        usage = TokenUsage.from_message(msg)
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.total_tokens == 0

    def test_to_dict(self):
        usage = TokenUsage(input_tokens=10, output_tokens=20, total_tokens=30, model="gpt-4")
        d = usage.to_dict()
        assert d == {
            "input_tokens": 10,
            "output_tokens": 20,
            "total_tokens": 30,
            "model": "gpt-4",
        }

    def test_to_dict_without_model(self):
        usage = TokenUsage(input_tokens=10, output_tokens=20, total_tokens=30)
        d = usage.to_dict()
        assert d == {
            "input_tokens": 10,
            "output_tokens": 20,
            "total_tokens": 30,
        }
        assert "model" not in d


class TestTokenUsageTracker:
    def test_initial_state(self):
        tracker = TokenUsageTracker()
        assert tracker.total_usage.input_tokens == 0
        assert tracker.total_usage.output_tokens == 0
        assert tracker.total_usage.total_tokens == 0
        assert tracker.call_usages == []

    def test_on_llm_end_openai_format(self):
        tracker = TokenUsageTracker()
        response = LLMResult(
            generations=[],
            llm_output={
                "token_usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                },
                "model_name": "gpt-4",
            },
        )
        tracker.on_llm_end(response)
        assert tracker.total_usage.input_tokens == 100
        assert tracker.total_usage.output_tokens == 50
        assert tracker.total_usage.total_tokens == 150
        assert tracker.total_usage.model == "gpt-4"
        assert len(tracker.call_usages) == 1

    def test_on_llm_end_anthropic_format(self):
        tracker = TokenUsageTracker()
        response = LLMResult(
            generations=[],
            llm_output={
                "usage": {
                    "input_tokens": 200,
                    "output_tokens": 80,
                },
                "model": "claude-3-opus",
            },
        )
        tracker.on_llm_end(response)
        assert tracker.total_usage.input_tokens == 200
        assert tracker.total_usage.output_tokens == 80
        assert tracker.total_usage.total_tokens == 280
        assert tracker.total_usage.model == "claude-3-opus"
        assert len(tracker.call_usages) == 1

    def test_on_llm_end_fallback_to_generation_metadata(self):
        tracker = TokenUsageTracker()
        msg = AIMessage(content="hello")
        msg.usage_metadata = {
            "input_tokens": 50,
            "output_tokens": 25,
            "total_tokens": 75,
        }
        gen = ChatGeneration(message=msg)
        response = LLMResult(generations=[[gen]], llm_output=None)
        tracker.on_llm_end(response)
        assert tracker.total_usage.input_tokens == 50
        assert tracker.total_usage.output_tokens == 25
        assert tracker.total_usage.total_tokens == 75
        assert len(tracker.call_usages) == 1

    def test_accumulates_across_multiple_calls(self):
        tracker = TokenUsageTracker()

        for i in range(3):
            response = LLMResult(
                generations=[],
                llm_output={
                    "token_usage": {
                        "prompt_tokens": 10 * (i + 1),
                        "completion_tokens": 5 * (i + 1),
                        "total_tokens": 15 * (i + 1),
                    },
                },
            )
            tracker.on_llm_end(response)

        assert len(tracker.call_usages) == 3
        # 10+20+30 = 60
        assert tracker.total_usage.input_tokens == 60
        # 5+10+15 = 30
        assert tracker.total_usage.output_tokens == 30
        # 15+30+45 = 90
        assert tracker.total_usage.total_tokens == 90

    def test_reset(self):
        tracker = TokenUsageTracker()
        response = LLMResult(
            generations=[],
            llm_output={
                "token_usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                },
            },
        )
        tracker.on_llm_end(response)
        assert tracker.total_usage.total_tokens == 150
        assert len(tracker.call_usages) == 1

        tracker.reset()
        assert tracker.total_usage.input_tokens == 0
        assert tracker.total_usage.output_tokens == 0
        assert tracker.total_usage.total_tokens == 0
        assert tracker.call_usages == []

    def test_empty_generations_no_crash(self):
        tracker = TokenUsageTracker()
        response = LLMResult(generations=[[]], llm_output=None)
        tracker.on_llm_end(response)
        assert tracker.total_usage.total_tokens == 0
        assert tracker.call_usages == []

    def test_no_llm_output_no_generations(self):
        tracker = TokenUsageTracker()
        response = LLMResult(generations=[], llm_output=None)
        tracker.on_llm_end(response)
        assert tracker.total_usage.total_tokens == 0
        assert tracker.call_usages == []
