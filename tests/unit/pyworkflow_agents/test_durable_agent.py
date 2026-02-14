"""Tests for durable agent mode — LLM cache replay and tool calls as steps."""

from unittest.mock import AsyncMock, patch

import pytest

lc = pytest.importorskip("langchain_core")

from langchain_core.messages import AIMessage, ToolMessage  # noqa: E402

from pyworkflow.context import LocalContext  # noqa: E402
from pyworkflow.engine.events import (  # noqa: E402
    EventType,
    create_agent_llm_response_event,
    create_agent_tool_result_event,
)
from pyworkflow.storage.file import FileStorageBackend  # noqa: E402
from pyworkflow_agents.agent.tool_calling.loop import (  # noqa: E402
    _deterministic_agent_id,
    _reconstruct_ai_message,
    _reconstruct_token_usage,
    run_tool_calling_loop,
)
from pyworkflow_agents.token_tracking import TokenUsage  # noqa: E402
from pyworkflow_agents.tools import ToolRegistry  # noqa: E402


# ---------------------------------------------------------------------------
# Mock LLM
# ---------------------------------------------------------------------------


class MockModel:
    """Minimal mock that implements ainvoke and bind_tools for testing."""

    def __init__(self, responses, model_name="mock-model"):
        self._responses = list(responses)
        self._call_count = 0
        self.model_name = model_name

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages, config=None):
        response = self._responses[self._call_count]
        self._call_count += 1
        return response

    @property
    def call_count(self):
        return self._call_count


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _simple_response(content="The answer is 42"):
    return AIMessage(content=content)


def _tool_call_response(tool_name="my_tool", args=None, call_id="call_1"):
    return AIMessage(
        content="",
        tool_calls=[{"name": tool_name, "args": args or {"x": 1}, "id": call_id}],
    )


def _make_registry_with_tool():
    from langchain_core.tools import StructuredTool

    def my_tool(x: int) -> str:
        """A test tool."""
        return f"result_{x}"

    tool = StructuredTool.from_function(my_tool, name="my_tool", description="A test tool")
    registry = ToolRegistry()
    registry.register(tool)
    return registry


def _make_error_registry():
    from langchain_core.tools import StructuredTool

    def error_tool(x: int) -> str:
        """A tool that fails."""
        raise ValueError("tool exploded")

    tool = StructuredTool.from_function(error_tool, name="error_tool", description="A tool that fails")
    registry = ToolRegistry()
    registry.register(tool)
    return registry


def _make_durable_context(tmp_path, run_id="test_run", event_log=None):
    """Create a durable LocalContext with file storage."""
    storage = FileStorageBackend(base_path=str(tmp_path))
    ctx = LocalContext(
        run_id=run_id,
        workflow_name="test_workflow",
        storage=storage,
        durable=True,
        event_log=event_log,
    )
    return ctx, storage


# ---------------------------------------------------------------------------
# Test helper functions
# ---------------------------------------------------------------------------


class TestDeterministicAgentId:
    """Tests for _deterministic_agent_id."""

    def test_same_input_same_id(self):
        id1 = _deterministic_agent_id("my_agent", "hello world")
        id2 = _deterministic_agent_id("my_agent", "hello world")
        assert id1 == id2

    def test_different_input_different_id(self):
        id1 = _deterministic_agent_id("my_agent", "hello")
        id2 = _deterministic_agent_id("my_agent", "goodbye")
        assert id1 != id2

    def test_different_name_different_id(self):
        id1 = _deterministic_agent_id("agent_a", "hello")
        id2 = _deterministic_agent_id("agent_b", "hello")
        assert id1 != id2

    def test_starts_with_agent_prefix(self):
        agent_id = _deterministic_agent_id("test", "input")
        assert agent_id.startswith("agent_")

    def test_deterministic_length(self):
        agent_id = _deterministic_agent_id("test", "input")
        # "agent_" + 12 hex chars
        assert len(agent_id) == 6 + 12


class TestReconstructAIMessage:
    """Tests for _reconstruct_ai_message."""

    def test_simple_response(self):
        cached = {"response_content": "Hello", "tool_calls": None}
        msg = _reconstruct_ai_message(cached)
        assert isinstance(msg, AIMessage)
        assert msg.content == "Hello"
        assert msg.tool_calls == []

    def test_with_tool_calls(self):
        tool_calls = [{"id": "tc_1", "name": "search", "args": {"q": "test"}}]
        cached = {"response_content": "", "tool_calls": tool_calls}
        msg = _reconstruct_ai_message(cached)
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0]["name"] == "search"
        assert msg.tool_calls[0]["args"] == {"q": "test"}
        assert msg.tool_calls[0]["id"] == "tc_1"

    def test_empty_cached_data(self):
        msg = _reconstruct_ai_message({})
        assert msg.content == ""
        assert msg.tool_calls == []


class TestReconstructTokenUsage:
    """Tests for _reconstruct_token_usage."""

    def test_with_usage(self):
        cached = {
            "token_usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "total_tokens": 150,
            }
        }
        usage = _reconstruct_token_usage(cached)
        assert usage.input_tokens == 100
        assert usage.output_tokens == 50
        assert usage.total_tokens == 150

    def test_without_usage(self):
        usage = _reconstruct_token_usage({})
        assert usage.input_tokens == 0
        assert usage.total_tokens == 0

    def test_none_usage(self):
        usage = _reconstruct_token_usage({"token_usage": None})
        assert usage.total_tokens == 0


# ---------------------------------------------------------------------------
# Standalone mode (no context) — backward compat
# ---------------------------------------------------------------------------


class TestStandaloneMode:
    """Tests that standalone mode (no workflow context) works exactly as before."""

    @pytest.mark.asyncio
    async def test_no_context_works(self):
        """Agent works without any workflow context."""
        model = MockModel([_simple_response("standalone")])
        result = await run_tool_calling_loop(
            model=model,
            input="test",
            record_events=False,
        )
        assert result.content == "standalone"
        assert result.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_tool_calls_work_standalone(self):
        """Tool calls work in standalone mode."""
        registry = _make_registry_with_tool()
        model = MockModel([
            _tool_call_response("my_tool", {"x": 1}, "call_1"),
            _simple_response("done"),
        ])
        result = await run_tool_calling_loop(
            model=model,
            input="test",
            tools=registry,
            record_events=False,
        )
        assert result.content == "done"
        assert result.tool_calls_made == 1


# ---------------------------------------------------------------------------
# Durable mode — LLM cache replay
# ---------------------------------------------------------------------------


class TestDurableLLMCacheReplay:
    """Tests for LLM response caching and replay in durable mode."""

    @pytest.mark.asyncio
    async def test_llm_response_cached_on_fresh_call(self, tmp_path):
        """In durable mode, fresh LLM calls are cached in context."""
        ctx, storage = _make_durable_context(tmp_path)
        model = MockModel([_simple_response("fresh response")])

        with patch("pyworkflow_agents.agent.tool_calling.loop._detect_context") as mock_detect:
            mock_detect.return_value = (ctx, True, "test_run")

            result = await run_tool_calling_loop(
                model=model,
                input="test query",
                agent_name="test_agent",
                record_events=False,
            )

        assert result.content == "fresh response"
        assert model.call_count == 1

        # LLM response should be cached in context
        agent_id = _deterministic_agent_id("test_agent", "test query")
        cached = ctx.get_cached_agent_llm_response(agent_id, 0)
        assert cached is not None
        assert cached["response_content"] == "fresh response"

    @pytest.mark.asyncio
    async def test_llm_response_replayed_from_cache(self, tmp_path):
        """In durable mode, cached LLM responses skip the actual LLM call."""
        agent_id = _deterministic_agent_id("test_agent", "test query")

        # Pre-populate the LLM cache
        llm_event = create_agent_llm_response_event(
            run_id="test_run",
            agent_id=agent_id,
            iteration=0,
            response_content="cached response",
            tool_calls=None,
            token_usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            model="mock-model",
        )
        llm_event.sequence = 1

        ctx, storage = _make_durable_context(tmp_path, event_log=[llm_event])

        # Model should NOT be called
        model = MockModel([_simple_response("this should not be returned")])

        with patch("pyworkflow_agents.agent.tool_calling.loop._detect_context") as mock_detect:
            mock_detect.return_value = (ctx, True, "test_run")

            result = await run_tool_calling_loop(
                model=model,
                input="test query",
                agent_id=agent_id,
                agent_name="test_agent",
                record_events=False,
            )

        assert result.content == "cached response"
        assert model.call_count == 0  # LLM was NOT called

    @pytest.mark.asyncio
    async def test_token_usage_from_cache(self, tmp_path):
        """Token usage is reconstructed from cached data."""
        agent_id = _deterministic_agent_id("test_agent", "test")

        llm_event = create_agent_llm_response_event(
            run_id="test_run",
            agent_id=agent_id,
            iteration=0,
            response_content="cached",
            tool_calls=None,
            token_usage={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
            model="mock-model",
        )
        llm_event.sequence = 1

        ctx, _ = _make_durable_context(tmp_path, event_log=[llm_event])
        model = MockModel([])

        with patch("pyworkflow_agents.agent.tool_calling.loop._detect_context") as mock_detect:
            mock_detect.return_value = (ctx, True, "test_run")

            result = await run_tool_calling_loop(
                model=model,
                input="test",
                agent_id=agent_id,
                agent_name="test_agent",
                record_events=False,
            )

        assert result.token_usage.input_tokens == 100
        assert result.token_usage.output_tokens == 50
        assert result.token_usage.total_tokens == 150


# ---------------------------------------------------------------------------
# Durable mode — tool calls as steps
# ---------------------------------------------------------------------------


class TestDurableToolCallsAsSteps:
    """Tests for tool calls recorded as durable steps."""

    @pytest.mark.asyncio
    async def test_step_events_recorded_for_tool_calls(self, tmp_path):
        """In durable mode, tool calls record STEP_STARTED + STEP_COMPLETED events."""
        ctx, storage = _make_durable_context(tmp_path)
        registry = _make_registry_with_tool()
        model = MockModel([
            _tool_call_response("my_tool", {"x": 1}, "call_1"),
            _simple_response("done"),
        ])

        with patch("pyworkflow_agents.agent.tool_calling.loop._detect_context") as mock_detect:
            mock_detect.return_value = (ctx, True, "test_run")

            result = await run_tool_calling_loop(
                model=model,
                input="test",
                agent_name="test_agent",
                tools=registry,
                record_events=False,
            )

        assert result.content == "done"
        assert result.tool_calls_made == 1

        # Check events in storage
        events = await storage.get_events("test_run")
        event_types = [e.type for e in events]

        assert EventType.STEP_STARTED in event_types
        assert EventType.STEP_COMPLETED in event_types
        assert EventType.AGENT_TOOL_CALL in event_types
        assert EventType.AGENT_TOOL_RESULT in event_types

        # Verify step_id format
        step_events = [e for e in events if e.type == EventType.STEP_STARTED]
        assert len(step_events) == 1
        step_id = step_events[0].data["step_id"]
        assert step_id.startswith("agent_tool_")

    @pytest.mark.asyncio
    async def test_tool_result_replayed_from_cache(self, tmp_path):
        """In durable mode, cached tool results skip actual tool execution."""
        agent_id = _deterministic_agent_id("test_agent", "test")

        # Pre-populate both LLM and tool caches
        llm_event = create_agent_llm_response_event(
            run_id="test_run",
            agent_id=agent_id,
            iteration=0,
            response_content="",
            tool_calls=[{"id": "call_1", "name": "my_tool", "args": {"x": 1}}],
            token_usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            model="mock-model",
        )
        llm_event.sequence = 1

        tool_event = create_agent_tool_result_event(
            run_id="test_run",
            agent_id=agent_id,
            iteration=0,
            tool_call_id="call_1",
            tool_name="my_tool",
            result="result_1",
            is_error=False,
            duration_ms=50.0,
        )
        tool_event.sequence = 2

        # Second iteration: final response (no tool calls)
        llm_event_2 = create_agent_llm_response_event(
            run_id="test_run",
            agent_id=agent_id,
            iteration=1,
            response_content="done from cache",
            tool_calls=None,
            token_usage={"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
            model="mock-model",
        )
        llm_event_2.sequence = 3

        ctx, storage = _make_durable_context(
            tmp_path, event_log=[llm_event, tool_event, llm_event_2]
        )

        # Create registry but tool should NOT be executed
        registry = _make_registry_with_tool()
        # Spy on registry.execute
        original_execute = registry.execute
        execute_called = False

        async def spy_execute(*args, **kwargs):
            nonlocal execute_called
            execute_called = True
            return await original_execute(*args, **kwargs)

        registry.execute = spy_execute

        model = MockModel([])  # No LLM calls expected

        with patch("pyworkflow_agents.agent.tool_calling.loop._detect_context") as mock_detect:
            mock_detect.return_value = (ctx, True, "test_run")

            result = await run_tool_calling_loop(
                model=model,
                input="test",
                agent_id=agent_id,
                agent_name="test_agent",
                tools=registry,
                record_events=False,
            )

        assert result.content == "done from cache"
        assert model.call_count == 0
        assert not execute_called  # Tool was NOT executed

    @pytest.mark.asyncio
    async def test_tool_error_recorded_as_step_failed(self, tmp_path):
        """In durable mode, tool errors are recorded as STEP_FAILED events."""
        ctx, storage = _make_durable_context(tmp_path)
        registry = _make_error_registry()
        model = MockModel([
            _tool_call_response("error_tool", {"x": 1}, "call_err"),
            _simple_response("recovered"),
        ])

        with patch("pyworkflow_agents.agent.tool_calling.loop._detect_context") as mock_detect:
            mock_detect.return_value = (ctx, True, "test_run")

            result = await run_tool_calling_loop(
                model=model,
                input="test",
                agent_name="test_agent",
                tools=registry,
                record_events=False,
            )

        assert result.content == "recovered"

        # Check events in storage
        events = await storage.get_events("test_run")
        event_types = [e.type for e in events]

        assert EventType.STEP_STARTED in event_types
        assert EventType.STEP_FAILED in event_types

        # Verify error data
        failed_events = [e for e in events if e.type == EventType.STEP_FAILED]
        assert len(failed_events) == 1
        assert "tool exploded" in failed_events[0].data["error"]

    @pytest.mark.asyncio
    async def test_tool_result_cached_in_step_results(self, tmp_path):
        """Tool results are cached in both agent_tool_cache and step_results."""
        ctx, storage = _make_durable_context(tmp_path)
        registry = _make_registry_with_tool()
        model = MockModel([
            _tool_call_response("my_tool", {"x": 5}, "call_5"),
            _simple_response("done"),
        ])

        with patch("pyworkflow_agents.agent.tool_calling.loop._detect_context") as mock_detect:
            mock_detect.return_value = (ctx, True, "test_run")

            agent_id_val = _deterministic_agent_id("test_agent", "test")
            result = await run_tool_calling_loop(
                model=model,
                input="test",
                agent_id=agent_id_val,
                agent_name="test_agent",
                tools=registry,
                record_events=False,
            )

        # Check agent tool cache
        cached = ctx.get_cached_agent_tool_result(agent_id_val, 0, "call_5")
        assert cached is not None
        assert cached["result"] == "result_5"
        assert cached["is_error"] is False
        assert cached["tool_name"] == "my_tool"

        # Check step_results cache
        step_id = f"agent_tool_{agent_id_val}_0_call_5"
        assert step_id in ctx.step_results
        assert ctx.step_results[step_id] == "result_5"


# ---------------------------------------------------------------------------
# Full replay scenario
# ---------------------------------------------------------------------------


class TestFullReplayScenario:
    """Test complete replay: all iterations cached, nothing re-executed."""

    @pytest.mark.asyncio
    async def test_full_replay_skips_everything(self, tmp_path):
        """When all events are cached, no LLM calls or tool executions happen."""
        agent_id = _deterministic_agent_id("test_agent", "test")

        events = [
            # Iteration 0: LLM returns tool call
            create_agent_llm_response_event(
                run_id="test_run",
                agent_id=agent_id,
                iteration=0,
                response_content="",
                tool_calls=[{"id": "tc_1", "name": "my_tool", "args": {"x": 1}}],
                token_usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                model="mock-model",
            ),
            # Iteration 0: tool result
            create_agent_tool_result_event(
                run_id="test_run",
                agent_id=agent_id,
                iteration=0,
                tool_call_id="tc_1",
                tool_name="my_tool",
                result="result_1",
                is_error=False,
                duration_ms=100.0,
            ),
            # Iteration 1: LLM returns final answer
            create_agent_llm_response_event(
                run_id="test_run",
                agent_id=agent_id,
                iteration=1,
                response_content="The answer is result_1",
                tool_calls=None,
                token_usage={"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
                model="mock-model",
            ),
        ]
        for i, e in enumerate(events, 1):
            e.sequence = i

        ctx, _ = _make_durable_context(tmp_path, event_log=events)

        # No LLM calls expected
        model = MockModel([])

        # Registry with tool — but tool should NOT be executed
        registry = _make_registry_with_tool()
        execute_called = False
        original_execute = registry.execute

        async def spy_execute(*args, **kwargs):
            nonlocal execute_called
            execute_called = True
            return await original_execute(*args, **kwargs)

        registry.execute = spy_execute

        with patch("pyworkflow_agents.agent.tool_calling.loop._detect_context") as mock_detect:
            mock_detect.return_value = (ctx, True, "test_run")

            result = await run_tool_calling_loop(
                model=model,
                input="test",
                agent_id=agent_id,
                agent_name="test_agent",
                tools=registry,
                record_events=False,
            )

        assert result.content == "The answer is result_1"
        assert result.iterations == 2
        assert result.tool_calls_made == 1
        assert model.call_count == 0
        assert not execute_called


# ---------------------------------------------------------------------------
# Partial replay (resume mid-way)
# ---------------------------------------------------------------------------


class TestPartialReplayResumes:
    """Test that partial cache population allows the loop to resume mid-way."""

    @pytest.mark.asyncio
    async def test_partial_replay_resumes_at_correct_point(self, tmp_path):
        """When only first iteration is cached, loop resumes from iteration 1."""
        agent_id = _deterministic_agent_id("test_agent", "test")

        # Only cache iteration 0 (tool call + tool result)
        events = [
            create_agent_llm_response_event(
                run_id="test_run",
                agent_id=agent_id,
                iteration=0,
                response_content="",
                tool_calls=[{"id": "tc_1", "name": "my_tool", "args": {"x": 1}}],
                token_usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                model="mock-model",
            ),
            create_agent_tool_result_event(
                run_id="test_run",
                agent_id=agent_id,
                iteration=0,
                tool_call_id="tc_1",
                tool_name="my_tool",
                result="result_1",
                is_error=False,
                duration_ms=100.0,
            ),
        ]
        for i, e in enumerate(events, 1):
            e.sequence = i

        ctx, storage = _make_durable_context(tmp_path, event_log=events)

        # Model will be called for iteration 1 only
        model = MockModel([_simple_response("resumed answer")])
        registry = _make_registry_with_tool()

        with patch("pyworkflow_agents.agent.tool_calling.loop._detect_context") as mock_detect:
            mock_detect.return_value = (ctx, True, "test_run")

            result = await run_tool_calling_loop(
                model=model,
                input="test",
                agent_id=agent_id,
                agent_name="test_agent",
                tools=registry,
                record_events=False,
            )

        assert result.content == "resumed answer"
        assert result.iterations == 2
        assert model.call_count == 1  # Only iteration 1 called LLM


# ---------------------------------------------------------------------------
# Deterministic agent_id in durable mode
# ---------------------------------------------------------------------------


class TestDeterministicAgentIdInDurableMode:
    """Test that durable mode generates deterministic agent IDs."""

    @pytest.mark.asyncio
    async def test_same_input_same_agent_id(self, tmp_path):
        """Two runs with same input produce same agent_id."""
        ctx, _ = _make_durable_context(tmp_path)
        model = MockModel([_simple_response("ok")])

        agent_ids = []

        for _ in range(2):
            # Reset context for each run
            ctx2, _ = _make_durable_context(tmp_path, run_id="test_run")

            with patch("pyworkflow_agents.agent.tool_calling.loop._detect_context") as mock_detect:
                mock_detect.return_value = (ctx2, True, "test_run")

                # Reset model
                model2 = MockModel([_simple_response("ok")])
                result = await run_tool_calling_loop(
                    model=model2,
                    input="same input",
                    agent_name="my_agent",
                    record_events=False,
                )
                agent_ids.append(result.agent_id)

        assert agent_ids[0] == agent_ids[1]
        assert agent_ids[0].startswith("agent_")
