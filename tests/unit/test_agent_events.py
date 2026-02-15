"""
Unit tests for agent event types, creation helpers, and replay integration.
"""

import pytest

from pyworkflow.context import LocalContext
from pyworkflow.engine.events import (
    Event,
    EventType,
    create_agent_approval_received_event,
    create_agent_approval_requested_event,
    create_agent_completed_event,
    create_agent_error_event,
    create_agent_llm_call_event,
    create_agent_llm_response_event,
    create_agent_paused_event,
    create_agent_response_event,
    create_agent_resumed_event,
    create_agent_started_event,
    create_agent_tool_call_event,
    create_agent_tool_result_event,
)
from pyworkflow.engine.replay import EventReplayer, replay_events
from pyworkflow.storage.file import FileStorageBackend


class TestAgentEventTypes:
    """Test that all agent event type enum values exist with correct string values."""

    def test_agent_started_event_type(self):
        assert EventType.AGENT_STARTED.value == "agent.started"

    def test_agent_llm_call_event_type(self):
        assert EventType.AGENT_LLM_CALL.value == "agent.llm_call"

    def test_agent_llm_response_event_type(self):
        assert EventType.AGENT_LLM_RESPONSE.value == "agent.llm_response"

    def test_agent_tool_call_event_type(self):
        assert EventType.AGENT_TOOL_CALL.value == "agent.tool_call"

    def test_agent_tool_result_event_type(self):
        assert EventType.AGENT_TOOL_RESULT.value == "agent.tool_result"

    def test_agent_response_event_type(self):
        assert EventType.AGENT_RESPONSE.value == "agent.response"

    def test_agent_completed_event_type(self):
        assert EventType.AGENT_COMPLETED.value == "agent.completed"

    def test_agent_error_event_type(self):
        assert EventType.AGENT_ERROR.value == "agent.error"

    def test_agent_handoff_event_type(self):
        assert EventType.AGENT_HANDOFF.value == "agent.handoff"

    def test_memory_stored_event_type(self):
        assert EventType.MEMORY_STORED.value == "memory.stored"

    def test_memory_retrieved_event_type(self):
        assert EventType.MEMORY_RETRIEVED.value == "memory.retrieved"

    def test_memory_compacted_event_type(self):
        assert EventType.MEMORY_COMPACTED.value == "memory.compacted"

    def test_agent_paused_event_type(self):
        assert EventType.AGENT_PAUSED.value == "agent.paused"

    def test_agent_resumed_event_type(self):
        assert EventType.AGENT_RESUMED.value == "agent.resumed"

    def test_agent_approval_requested_event_type(self):
        assert EventType.AGENT_APPROVAL_REQUESTED.value == "agent.approval_requested"

    def test_agent_approval_received_event_type(self):
        assert EventType.AGENT_APPROVAL_RECEIVED.value == "agent.approval_received"

    def test_all_agent_and_memory_event_types_exist(self):
        """Verify all agent/memory enum values are accessible."""
        event_types = [
            EventType.AGENT_STARTED,
            EventType.AGENT_LLM_CALL,
            EventType.AGENT_LLM_RESPONSE,
            EventType.AGENT_TOOL_CALL,
            EventType.AGENT_TOOL_RESULT,
            EventType.AGENT_RESPONSE,
            EventType.AGENT_COMPLETED,
            EventType.AGENT_ERROR,
            EventType.AGENT_PAUSED,
            EventType.AGENT_RESUMED,
            EventType.AGENT_APPROVAL_REQUESTED,
            EventType.AGENT_APPROVAL_RECEIVED,
            EventType.AGENT_HANDOFF,
            EventType.MEMORY_STORED,
            EventType.MEMORY_RETRIEVED,
            EventType.MEMORY_COMPACTED,
        ]
        assert len(event_types) == 16
        # All should be unique
        assert len(set(et.value for et in event_types)) == 16


class TestAgentEventCreationHelpers:
    """Test all 8 agent event creation helpers produce valid Event objects."""

    def test_create_agent_started_event(self):
        event = create_agent_started_event(
            run_id="run_1",
            agent_id="agent_abc",
            agent_name="test_agent",
            model="gpt-4",
            tools=["tool_a", "tool_b"],
            system_prompt="You are a helpful assistant.",
            input_text="Hello, agent!",
        )
        assert isinstance(event, Event)
        assert event.type == EventType.AGENT_STARTED
        assert event.run_id == "run_1"
        assert event.data["agent_id"] == "agent_abc"
        assert event.data["agent_name"] == "test_agent"
        assert event.data["model"] == "gpt-4"
        assert event.data["tools"] == ["tool_a", "tool_b"]
        assert event.data["system_prompt"] == "You are a helpful assistant."
        assert event.data["input_text"] == "Hello, agent!"
        assert "started_at" in event.data

    def test_create_agent_llm_call_event(self):
        messages = [{"role": "user", "content": "Hello"}]
        event = create_agent_llm_call_event(
            run_id="run_1",
            agent_id="agent_abc",
            iteration=1,
            messages=messages,
            model="gpt-4",
            tools=["tool_a"],
        )
        assert isinstance(event, Event)
        assert event.type == EventType.AGENT_LLM_CALL
        assert event.run_id == "run_1"
        assert event.data["agent_id"] == "agent_abc"
        assert event.data["iteration"] == 1
        assert event.data["messages"] == messages
        assert event.data["model"] == "gpt-4"
        assert event.data["tools"] == ["tool_a"]

    def test_create_agent_llm_response_event(self):
        tool_calls = [{"id": "tc_1", "name": "tool_a", "args": {"x": 1}}]
        token_usage = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
        event = create_agent_llm_response_event(
            run_id="run_1",
            agent_id="agent_abc",
            iteration=1,
            response_content="I will call tool_a.",
            tool_calls=tool_calls,
            token_usage=token_usage,
            model="gpt-4",
        )
        assert isinstance(event, Event)
        assert event.type == EventType.AGENT_LLM_RESPONSE
        assert event.run_id == "run_1"
        assert event.data["agent_id"] == "agent_abc"
        assert event.data["iteration"] == 1
        assert event.data["response_content"] == "I will call tool_a."
        assert event.data["tool_calls"] == tool_calls
        assert event.data["token_usage"] == token_usage
        assert event.data["model"] == "gpt-4"

    def test_create_agent_llm_response_event_no_tool_calls(self):
        event = create_agent_llm_response_event(
            run_id="run_1",
            agent_id="agent_abc",
            iteration=2,
            response_content="Final answer.",
            tool_calls=None,
            token_usage=None,
            model="gpt-4",
        )
        assert event.data["tool_calls"] is None
        assert event.data["token_usage"] is None

    def test_create_agent_tool_call_event(self):
        event = create_agent_tool_call_event(
            run_id="run_1",
            agent_id="agent_abc",
            iteration=1,
            tool_call_id="tc_1",
            tool_name="search",
            tool_args={"query": "test"},
        )
        assert isinstance(event, Event)
        assert event.type == EventType.AGENT_TOOL_CALL
        assert event.run_id == "run_1"
        assert event.data["agent_id"] == "agent_abc"
        assert event.data["iteration"] == 1
        assert event.data["tool_call_id"] == "tc_1"
        assert event.data["tool_name"] == "search"
        assert event.data["tool_args"] == {"query": "test"}

    def test_create_agent_tool_result_event(self):
        event = create_agent_tool_result_event(
            run_id="run_1",
            agent_id="agent_abc",
            iteration=1,
            tool_call_id="tc_1",
            tool_name="search",
            result={"results": ["a", "b"]},
            is_error=False,
            duration_ms=123.45,
        )
        assert isinstance(event, Event)
        assert event.type == EventType.AGENT_TOOL_RESULT
        assert event.run_id == "run_1"
        assert event.data["agent_id"] == "agent_abc"
        assert event.data["iteration"] == 1
        assert event.data["tool_call_id"] == "tc_1"
        assert event.data["tool_name"] == "search"
        assert event.data["result"] == {"results": ["a", "b"]}
        assert event.data["is_error"] is False
        assert event.data["duration_ms"] == 123.45

    def test_create_agent_tool_result_event_error(self):
        event = create_agent_tool_result_event(
            run_id="run_1",
            agent_id="agent_abc",
            iteration=1,
            tool_call_id="tc_2",
            tool_name="failing_tool",
            result="Error: connection refused",
            is_error=True,
            duration_ms=50.0,
        )
        assert event.data["is_error"] is True
        assert event.data["result"] == "Error: connection refused"

    def test_create_agent_response_event(self):
        event = create_agent_response_event(
            run_id="run_1",
            agent_id="agent_abc",
            iteration=3,
            content="Here is the final answer.",
        )
        assert isinstance(event, Event)
        assert event.type == EventType.AGENT_RESPONSE
        assert event.run_id == "run_1"
        assert event.data["agent_id"] == "agent_abc"
        assert event.data["iteration"] == 3
        assert event.data["content"] == "Here is the final answer."

    def test_create_agent_completed_event(self):
        token_usage = {"prompt_tokens": 500, "completion_tokens": 200, "total_tokens": 700}
        event = create_agent_completed_event(
            run_id="run_1",
            agent_id="agent_abc",
            result_content="Task completed successfully.",
            total_iterations=3,
            total_tool_calls=5,
            token_usage=token_usage,
            finish_reason="stop",
        )
        assert isinstance(event, Event)
        assert event.type == EventType.AGENT_COMPLETED
        assert event.run_id == "run_1"
        assert event.data["agent_id"] == "agent_abc"
        assert event.data["result_content"] == "Task completed successfully."
        assert event.data["total_iterations"] == 3
        assert event.data["total_tool_calls"] == 5
        assert event.data["token_usage"] == token_usage
        assert event.data["finish_reason"] == "stop"
        assert "completed_at" in event.data

    def test_create_agent_error_event(self):
        event = create_agent_error_event(
            run_id="run_1",
            agent_id="agent_abc",
            error="API rate limit exceeded",
            error_type="RateLimitError",
            iteration=2,
            traceback="Traceback (most recent call last):\n  ...",
        )
        assert isinstance(event, Event)
        assert event.type == EventType.AGENT_ERROR
        assert event.run_id == "run_1"
        assert event.data["agent_id"] == "agent_abc"
        assert event.data["error"] == "API rate limit exceeded"
        assert event.data["error_type"] == "RateLimitError"
        assert event.data["iteration"] == 2
        assert event.data["traceback"] == "Traceback (most recent call last):\n  ..."

    def test_create_agent_error_event_no_traceback(self):
        event = create_agent_error_event(
            run_id="run_1",
            agent_id="agent_abc",
            error="Unknown error",
            error_type="Exception",
            iteration=1,
        )
        assert event.data["traceback"] is None


class TestEventReplayerAgentEvents:
    """Test EventReplayer handling of agent events."""

    @pytest.mark.asyncio
    async def test_replay_agent_llm_response_populates_cache(self, tmp_path):
        """Test that replaying AGENT_LLM_RESPONSE events populates agent_llm_cache."""
        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )

        tool_calls = [{"id": "tc_1", "name": "search", "args": {"q": "test"}}]
        token_usage = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}

        events = [
            create_agent_llm_response_event(
                run_id="test_run",
                agent_id="agent_1",
                iteration=0,
                response_content="I will search for that.",
                tool_calls=tool_calls,
                token_usage=token_usage,
                model="gpt-4",
            ),
            create_agent_llm_response_event(
                run_id="test_run",
                agent_id="agent_1",
                iteration=1,
                response_content="Here is the answer.",
                tool_calls=None,
                token_usage={"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300},
                model="gpt-4",
            ),
        ]

        for i, event in enumerate(events, 1):
            event.sequence = i

        replayer = EventReplayer()
        await replayer.replay(ctx, events)

        # Verify cache populated
        cached_0 = ctx.get_cached_agent_llm_response("agent_1", 0)
        assert cached_0 is not None
        assert cached_0["response_content"] == "I will search for that."
        assert cached_0["tool_calls"] == tool_calls
        assert cached_0["token_usage"] == token_usage
        assert cached_0["model"] == "gpt-4"

        cached_1 = ctx.get_cached_agent_llm_response("agent_1", 1)
        assert cached_1 is not None
        assert cached_1["response_content"] == "Here is the answer."
        assert cached_1["tool_calls"] is None

    @pytest.mark.asyncio
    async def test_replay_agent_tool_result_populates_cache(self, tmp_path):
        """Test that replaying AGENT_TOOL_RESULT events populates agent_tool_cache."""
        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )

        events = [
            create_agent_tool_result_event(
                run_id="test_run",
                agent_id="agent_1",
                iteration=0,
                tool_call_id="tc_1",
                tool_name="search",
                result={"results": ["result_a"]},
                is_error=False,
                duration_ms=200.0,
            ),
            create_agent_tool_result_event(
                run_id="test_run",
                agent_id="agent_1",
                iteration=0,
                tool_call_id="tc_2",
                tool_name="calculate",
                result=42,
                is_error=False,
                duration_ms=50.0,
            ),
        ]

        for i, event in enumerate(events, 1):
            event.sequence = i

        replayer = EventReplayer()
        await replayer.replay(ctx, events)

        # Verify cache populated (enriched dict format)
        assert ctx.has_cached_agent_tool_result("agent_1", 0, "tc_1")
        cached_1 = ctx.get_cached_agent_tool_result("agent_1", 0, "tc_1")
        assert cached_1["result"] == {"results": ["result_a"]}
        assert cached_1["is_error"] is False
        assert cached_1["tool_name"] == "search"
        assert cached_1["duration_ms"] == 200.0

        assert ctx.has_cached_agent_tool_result("agent_1", 0, "tc_2")
        cached_2 = ctx.get_cached_agent_tool_result("agent_1", 0, "tc_2")
        assert cached_2["result"] == 42
        assert cached_2["is_error"] is False
        assert cached_2["tool_name"] == "calculate"
        assert cached_2["duration_ms"] == 50.0

    @pytest.mark.asyncio
    async def test_replay_informational_agent_events_no_crash(self, tmp_path):
        """Test that informational agent events (STARTED, COMPLETED, ERROR, etc.) don't crash during replay."""
        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )

        events = [
            create_agent_started_event(
                run_id="test_run",
                agent_id="agent_1",
                agent_name="test_agent",
                model="gpt-4",
                tools=["search"],
                system_prompt="You are helpful.",
                input_text="Hello",
            ),
            create_agent_llm_call_event(
                run_id="test_run",
                agent_id="agent_1",
                iteration=0,
                messages=[{"role": "user", "content": "Hello"}],
                model="gpt-4",
                tools=["search"],
            ),
            create_agent_tool_call_event(
                run_id="test_run",
                agent_id="agent_1",
                iteration=0,
                tool_call_id="tc_1",
                tool_name="search",
                tool_args={"q": "test"},
            ),
            create_agent_response_event(
                run_id="test_run",
                agent_id="agent_1",
                iteration=1,
                content="Final answer.",
            ),
            create_agent_completed_event(
                run_id="test_run",
                agent_id="agent_1",
                result_content="Done",
                total_iterations=2,
                total_tool_calls=1,
                token_usage={"total_tokens": 300},
                finish_reason="stop",
            ),
            create_agent_error_event(
                run_id="test_run",
                agent_id="agent_2",
                error="Test error",
                error_type="ValueError",
                iteration=0,
            ),
        ]

        for i, event in enumerate(events, 1):
            event.sequence = i

        # This should not raise any exceptions
        replayer = EventReplayer()
        await replayer.replay(ctx, events)

    @pytest.mark.asyncio
    async def test_replay_mixed_agent_and_step_events(self, tmp_path):
        """Test replaying a mix of agent and step events."""
        from pyworkflow.engine.events import create_step_completed_event
        from pyworkflow.serialization.encoder import serialize

        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )

        events = [
            create_step_completed_event(
                run_id="test_run",
                step_id="step_1",
                result=serialize("step_result"),
                step_name="my_step",
            ),
            create_agent_llm_response_event(
                run_id="test_run",
                agent_id="agent_1",
                iteration=0,
                response_content="LLM said this.",
                tool_calls=None,
                token_usage=None,
                model="gpt-4",
            ),
            create_agent_tool_result_event(
                run_id="test_run",
                agent_id="agent_1",
                iteration=0,
                tool_call_id="tc_1",
                tool_name="my_tool",
                result="tool output",
                is_error=False,
                duration_ms=100.0,
            ),
        ]

        for i, event in enumerate(events, 1):
            event.sequence = i

        replayer = EventReplayer()
        await replayer.replay(ctx, events)

        # Step result should be cached
        assert ctx.step_results["step_1"] == "step_result"

        # Agent caches should be populated
        cached = ctx.get_cached_agent_llm_response("agent_1", 0)
        assert cached is not None
        assert cached["response_content"] == "LLM said this."

        cached_tool = ctx.get_cached_agent_tool_result("agent_1", 0, "tc_1")
        assert cached_tool["result"] == "tool output"
        assert cached_tool["is_error"] is False


class TestLocalContextAgentReplay:
    """Test LocalContext._replay_events handles agent events correctly."""

    def test_replay_events_populates_agent_llm_cache(self, tmp_path):
        """Test that _replay_events populates agent_llm_cache during init."""
        storage = FileStorageBackend(base_path=str(tmp_path))

        llm_response_event = create_agent_llm_response_event(
            run_id="test_run",
            agent_id="agent_1",
            iteration=0,
            response_content="Response text",
            tool_calls=[{"id": "tc_1", "name": "tool"}],
            token_usage={"total_tokens": 100},
            model="gpt-4",
        )
        llm_response_event.sequence = 1

        # Create context with events for replay
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
            event_log=[llm_response_event],
        )

        # After init, the cache should be populated
        cached = ctx.get_cached_agent_llm_response("agent_1", 0)
        assert cached is not None
        assert cached["response_content"] == "Response text"
        assert cached["tool_calls"] == [{"id": "tc_1", "name": "tool"}]
        assert cached["token_usage"] == {"total_tokens": 100}
        assert cached["model"] == "gpt-4"

    def test_replay_events_populates_agent_tool_cache(self, tmp_path):
        """Test that _replay_events populates agent_tool_cache during init."""
        storage = FileStorageBackend(base_path=str(tmp_path))

        tool_result_event = create_agent_tool_result_event(
            run_id="test_run",
            agent_id="agent_1",
            iteration=0,
            tool_call_id="tc_1",
            tool_name="search",
            result="search results here",
            is_error=False,
            duration_ms=150.0,
        )
        tool_result_event.sequence = 1

        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
            event_log=[tool_result_event],
        )

        assert ctx.has_cached_agent_tool_result("agent_1", 0, "tc_1")
        cached = ctx.get_cached_agent_tool_result("agent_1", 0, "tc_1")
        assert cached["result"] == "search results here"
        assert cached["is_error"] is False
        assert cached["tool_name"] == "search"
        assert cached["duration_ms"] == 150.0

    def test_replay_events_handles_informational_agent_events(self, tmp_path):
        """Test that _replay_events doesn't crash on informational agent events."""
        storage = FileStorageBackend(base_path=str(tmp_path))

        events = [
            create_agent_started_event(
                run_id="test_run",
                agent_id="agent_1",
                agent_name="test",
                model="gpt-4",
                tools=[],
                system_prompt="",
                input_text="hello",
            ),
            create_agent_completed_event(
                run_id="test_run",
                agent_id="agent_1",
                result_content="done",
                total_iterations=1,
                total_tool_calls=0,
                token_usage=None,
                finish_reason="stop",
            ),
        ]
        for i, event in enumerate(events, 1):
            event.sequence = i

        # Should not raise
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
            event_log=events,
        )
        assert ctx is not None


class TestLocalContextAgentCacheMethods:
    """Test context cache accessor methods directly."""

    def test_cache_agent_llm_response(self, tmp_path):
        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )

        response = {
            "response_content": "Hello",
            "tool_calls": None,
            "token_usage": {"total_tokens": 50},
            "model": "gpt-4",
        }
        ctx.cache_agent_llm_response("agent_1", 0, response)

        cached = ctx.get_cached_agent_llm_response("agent_1", 0)
        assert cached == response

    def test_get_cached_agent_llm_response_missing(self, tmp_path):
        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )

        assert ctx.get_cached_agent_llm_response("nonexistent", 0) is None

    def test_cache_agent_tool_result(self, tmp_path):
        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )

        ctx.cache_agent_tool_result("agent_1", 0, "tc_1", {"data": "result"})

        assert ctx.has_cached_agent_tool_result("agent_1", 0, "tc_1")
        cached = ctx.get_cached_agent_tool_result("agent_1", 0, "tc_1")
        assert cached["result"] == {"data": "result"}
        assert cached["is_error"] is False
        assert cached["tool_name"] == ""
        assert cached["duration_ms"] == 0

    def test_get_cached_agent_tool_result_missing(self, tmp_path):
        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )

        assert ctx.get_cached_agent_tool_result("agent_1", 0, "tc_nonexistent") is None

    def test_has_cached_agent_tool_result_false(self, tmp_path):
        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )

        assert ctx.has_cached_agent_tool_result("agent_1", 0, "tc_1") is False

    def test_agent_llm_cache_property(self, tmp_path):
        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )

        assert ctx.agent_llm_cache == {}
        ctx.cache_agent_llm_response("agent_1", 0, {"content": "test"})
        assert "agent_1:0" in ctx.agent_llm_cache

    def test_agent_tool_cache_property(self, tmp_path):
        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )

        assert ctx.agent_tool_cache == {}
        ctx.cache_agent_tool_result("agent_1", 0, "tc_1", "result")
        assert "agent_1:0:tc_1" in ctx.agent_tool_cache
        assert ctx.agent_tool_cache["agent_1:0:tc_1"]["result"] == "result"

    def test_multiple_agents_cache_isolation(self, tmp_path):
        """Test that caches for different agents don't interfere."""
        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )

        ctx.cache_agent_llm_response("agent_1", 0, {"content": "agent_1_response"})
        ctx.cache_agent_llm_response("agent_2", 0, {"content": "agent_2_response"})

        assert ctx.get_cached_agent_llm_response("agent_1", 0)["content"] == "agent_1_response"
        assert ctx.get_cached_agent_llm_response("agent_2", 0)["content"] == "agent_2_response"

        ctx.cache_agent_tool_result("agent_1", 0, "tc_1", "result_1")
        ctx.cache_agent_tool_result("agent_2", 0, "tc_1", "result_2")

        assert ctx.get_cached_agent_tool_result("agent_1", 0, "tc_1")["result"] == "result_1"
        assert ctx.get_cached_agent_tool_result("agent_2", 0, "tc_1")["result"] == "result_2"

    def test_multiple_iterations_cache(self, tmp_path):
        """Test that different iterations for the same agent are cached separately."""
        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )

        ctx.cache_agent_llm_response("agent_1", 0, {"content": "iter_0"})
        ctx.cache_agent_llm_response("agent_1", 1, {"content": "iter_1"})
        ctx.cache_agent_llm_response("agent_1", 2, {"content": "iter_2"})

        assert ctx.get_cached_agent_llm_response("agent_1", 0)["content"] == "iter_0"
        assert ctx.get_cached_agent_llm_response("agent_1", 1)["content"] == "iter_1"
        assert ctx.get_cached_agent_llm_response("agent_1", 2)["content"] == "iter_2"


# ---------------------------------------------------------------------------
# HITL and Pause/Resume event creation helpers
# ---------------------------------------------------------------------------


class TestAgentHITLEventCreation:
    """Test HITL and pause/resume event creation helpers."""

    def test_create_agent_paused_event(self):
        event = create_agent_paused_event(
            run_id="run_1",
            agent_id="agent_abc",
            iteration=3,
            reason="user_requested",
        )
        assert isinstance(event, Event)
        assert event.type == EventType.AGENT_PAUSED
        assert event.run_id == "run_1"
        assert event.data["agent_id"] == "agent_abc"
        assert event.data["iteration"] == 3
        assert event.data["reason"] == "user_requested"
        assert "paused_at" in event.data

    def test_create_agent_resumed_event(self):
        event = create_agent_resumed_event(
            run_id="run_1",
            agent_id="agent_abc",
            iteration=3,
            message="Continue with Y",
        )
        assert isinstance(event, Event)
        assert event.type == EventType.AGENT_RESUMED
        assert event.data["agent_id"] == "agent_abc"
        assert event.data["iteration"] == 3
        assert event.data["message"] == "Continue with Y"
        assert "resumed_at" in event.data

    def test_create_agent_resumed_event_without_message(self):
        event = create_agent_resumed_event(
            run_id="run_1",
            agent_id="agent_abc",
            iteration=3,
        )
        assert event.data["message"] is None

    def test_create_agent_approval_requested_event(self):
        tool_calls = [
            {"tool_call_id": "tc_1", "tool_name": "delete", "tool_args": {"path": "/tmp"}},
        ]
        event = create_agent_approval_requested_event(
            run_id="run_1",
            agent_id="agent_abc",
            iteration=2,
            tool_calls=tool_calls,
        )
        assert isinstance(event, Event)
        assert event.type == EventType.AGENT_APPROVAL_REQUESTED
        assert event.data["tool_calls"] == tool_calls
        assert event.data["agent_id"] == "agent_abc"
        assert event.data["iteration"] == 2
        assert "requested_at" in event.data

    def test_create_agent_approval_received_event(self):
        decisions = [
            {"tool_call_id": "tc_1", "action": "approve"},
            {"tool_call_id": "tc_2", "action": "reject", "feedback": "No"},
        ]
        event = create_agent_approval_received_event(
            run_id="run_1",
            agent_id="agent_abc",
            iteration=2,
            decisions=decisions,
        )
        assert isinstance(event, Event)
        assert event.type == EventType.AGENT_APPROVAL_RECEIVED
        assert event.data["decisions"] == decisions
        assert "received_at" in event.data


class TestReplayHITLEvents:
    """Test that HITL events are handled during replay without errors."""

    @pytest.mark.asyncio
    async def test_replay_hitl_events_no_crash(self, tmp_path):
        """HITL events are pass-through during replay."""
        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )

        events = [
            create_agent_paused_event(
                run_id="test_run", agent_id="a1", iteration=1, reason="pause",
            ),
            create_agent_resumed_event(
                run_id="test_run", agent_id="a1", iteration=1, message="go",
            ),
            create_agent_approval_requested_event(
                run_id="test_run", agent_id="a1", iteration=2,
                tool_calls=[{"tool_call_id": "tc1", "tool_name": "x", "tool_args": {}}],
            ),
            create_agent_approval_received_event(
                run_id="test_run", agent_id="a1", iteration=2,
                decisions=[{"tool_call_id": "tc1", "action": "approve"}],
            ),
        ]
        for i, event in enumerate(events, 1):
            event.sequence = i

        replayer = EventReplayer()
        await replayer.replay(ctx, events)  # Should not raise
