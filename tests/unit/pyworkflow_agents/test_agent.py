"""Tests for pyworkflow_agents.agent — @tool_calling_agent decorator, Agent base class, and tool-calling loop."""

import pytest

lc = pytest.importorskip("langchain_core")

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage  # noqa: E402

from pyworkflow_agents.agent import AgentResult, Agent, agent, run_agent_loop  # noqa: E402
from pyworkflow_agents.agent import DEFAULT_SYSTEM_PROMPT, tool_calling_agent, run_tool_calling_loop  # noqa: E402
from pyworkflow_agents.exceptions import AgentPause  # noqa: E402
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
        return self  # return self for simplicity

    async def ainvoke(self, messages, config=None):
        response = self._responses[self._call_count]
        self._call_count += 1
        return response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _simple_response(content="The answer is 42"):
    """AIMessage with no tool calls."""
    return AIMessage(content=content)


def _tool_call_response(tool_name="my_tool", args=None, call_id="call_1"):
    """AIMessage with a single tool call."""
    return AIMessage(
        content="",
        tool_calls=[{"name": tool_name, "args": args or {"x": 1}, "id": call_id}],
    )


def _make_registry_with_tool():
    """Create a ToolRegistry with a simple tool for testing."""
    from langchain_core.tools import StructuredTool

    def my_tool(x: int) -> str:
        """A test tool."""
        return f"result_{x}"

    tool = StructuredTool.from_function(my_tool, name="my_tool", description="A test tool")
    registry = ToolRegistry()
    registry.register(tool)
    return registry


def _make_error_registry():
    """Create a ToolRegistry with a tool that raises an error."""
    from langchain_core.tools import StructuredTool

    def error_tool(x: int) -> str:
        """A tool that fails."""
        raise ValueError("tool exploded")

    tool = StructuredTool.from_function(error_tool, name="error_tool", description="A tool that fails")
    registry = ToolRegistry()
    registry.register(tool)
    return registry


# ---------------------------------------------------------------------------
# @tool_calling_agent decorator tests
# ---------------------------------------------------------------------------


class TestToolCallingAgentDecorator:
    """Tests for the @tool_calling_agent decorator."""

    def test_creates_callable_with_agent_attribute(self):
        """@tool_calling_agent creates callable with __agent__ attribute set to True."""
        model = MockModel([_simple_response()])

        @tool_calling_agent(model=model)
        async def my_agent(query: str):
            return query

        assert my_agent.__agent__ is True

    def test_uses_docstring_as_system_prompt(self):
        """@tool_calling_agent uses docstring as system_prompt when none provided."""
        model = MockModel([_simple_response()])

        @tool_calling_agent(model=model)
        async def my_agent(query: str):
            """You are a helpful assistant."""
            return query

        assert my_agent.__agent_system_prompt__ == "You are a helpful assistant."

    def test_raises_value_error_when_no_model(self):
        """@tool_calling_agent raises ValueError when no model provided."""

        @tool_calling_agent
        async def my_agent(query: str):
            return query

        with pytest.raises(ValueError, match="has no model"):
            import asyncio
            asyncio.get_event_loop().run_until_complete(my_agent("test"))

    @pytest.mark.asyncio
    async def test_model_override_at_call_time(self):
        """_model= runtime override works."""
        model = MockModel([_simple_response("override response")])

        @tool_calling_agent
        async def my_agent(query: str):
            return query

        result = await my_agent("test", _model=model)
        assert result.content == "override response"

    @pytest.mark.asyncio
    async def test_decorator_with_parentheses_no_args(self):
        """@tool_calling_agent() with empty parens works."""
        model = MockModel([_simple_response()])

        @tool_calling_agent(model=model)
        async def my_agent(query: str):
            return query

        result = await my_agent("test")
        assert result.content == "The answer is 42"

    def test_metadata_attributes_set(self):
        """@tool_calling_agent sets metadata attributes on the wrapper."""
        model = MockModel([_simple_response()])

        @tool_calling_agent(model=model, max_iterations=5, name="custom_name")
        async def my_agent(query: str):
            return query

        assert my_agent.__agent__ is True
        assert my_agent.__agent_name__ == "custom_name"
        assert my_agent.__agent_model__ is model
        assert my_agent.__agent_max_iterations__ == 5


# ---------------------------------------------------------------------------
# Backward compatibility: @agent alias tests
# ---------------------------------------------------------------------------


class TestAgentDecoratorAlias:
    """Tests that the backward-compatible @agent alias works identically."""

    def test_agent_alias_is_tool_calling_agent(self):
        """The `agent` alias points to `tool_calling_agent`."""
        assert agent is tool_calling_agent

    def test_run_agent_loop_alias_is_run_tool_calling_loop(self):
        """The `run_agent_loop` alias points to `run_tool_calling_loop`."""
        assert run_agent_loop is run_tool_calling_loop

    @pytest.mark.asyncio
    async def test_agent_alias_works(self):
        """@agent alias produces a working decorated agent."""
        model = MockModel([_simple_response("alias works")])

        @agent(model=model)
        async def my_agent(query: str):
            return query

        result = await my_agent("test")
        assert result.content == "alias works"


# ---------------------------------------------------------------------------
# run_tool_calling_loop tests
# ---------------------------------------------------------------------------


class TestRunToolCallingLoop:
    """Tests for the tool-calling agent loop."""

    @pytest.mark.asyncio
    async def test_no_tool_calls_returns_after_first_call(self):
        """Loop with no tool_calls returns after first LLM call (finish_reason='stop')."""
        model = MockModel([_simple_response("hello")])
        result = await run_tool_calling_loop(
            model=model,
            input="test",
            record_events=False,
        )
        assert result.content == "hello"
        assert result.finish_reason == "stop"
        assert result.iterations == 1
        assert result.tool_calls_made == 0

    @pytest.mark.asyncio
    async def test_tool_calls_execute_and_loop(self):
        """Loop with tool_calls executes tools and loops."""
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
        assert result.finish_reason == "stop"
        assert result.iterations == 2
        assert result.tool_calls_made == 1

    @pytest.mark.asyncio
    async def test_max_iterations_reached(self):
        """Loop respects max_iterations and returns finish_reason='max_iterations'."""
        registry = _make_registry_with_tool()
        model = MockModel([
            _tool_call_response("my_tool", {"x": 1}, "call_1"),
            _tool_call_response("my_tool", {"x": 2}, "call_2"),
            _tool_call_response("my_tool", {"x": 3}, "call_3"),
        ])
        result = await run_tool_calling_loop(
            model=model,
            input="test",
            tools=registry,
            max_iterations=2,
            record_events=False,
        )
        assert result.finish_reason == "max_iterations"
        assert result.iterations == 2

    @pytest.mark.asyncio
    async def test_tool_execution_error_continues(self):
        """Loop handles tool execution errors (tool returns error, loop continues)."""
        registry = _make_error_registry()
        model = MockModel([
            _tool_call_response("error_tool", {"x": 1}, "call_err"),
            _simple_response("recovered"),
        ])
        result = await run_tool_calling_loop(
            model=model,
            input="test",
            tools=registry,
            record_events=False,
        )
        assert result.content == "recovered"
        assert result.finish_reason == "stop"
        # Check that ToolMessage with error was appended
        tool_messages = [m for m in result.messages if isinstance(m, ToolMessage)]
        assert len(tool_messages) == 1
        assert "Error:" in tool_messages[0].content

    @pytest.mark.asyncio
    async def test_works_without_tools(self):
        """Agent works without tools (empty tools list)."""
        model = MockModel([_simple_response("no tools needed")])
        result = await run_tool_calling_loop(
            model=model,
            input="test",
            tools=None,
            record_events=False,
        )
        assert result.content == "no tools needed"
        assert result.tool_calls_made == 0

    @pytest.mark.asyncio
    async def test_works_with_tool_registry(self):
        """Agent works with ToolRegistry."""
        registry = _make_registry_with_tool()
        model = MockModel([
            _tool_call_response("my_tool", {"x": 5}, "call_5"),
            _simple_response("used registry"),
        ])
        result = await run_tool_calling_loop(
            model=model,
            input="test",
            tools=registry,
            record_events=False,
        )
        assert result.content == "used registry"
        assert result.tool_calls_made == 1

    @pytest.mark.asyncio
    async def test_system_prompt_added_to_messages(self):
        """System prompt is prepended as SystemMessage."""
        model = MockModel([_simple_response("ok")])
        result = await run_tool_calling_loop(
            model=model,
            input="test",
            system_prompt="You are helpful.",
            record_events=False,
        )
        # The first message should be SystemMessage
        assert isinstance(result.messages[0], SystemMessage)
        assert result.messages[0].content == "You are helpful."

    @pytest.mark.asyncio
    async def test_default_system_prompt_used_when_none_provided(self):
        """DEFAULT_SYSTEM_PROMPT is used when no system_prompt is given."""
        model = MockModel([_simple_response("ok")])
        result = await run_tool_calling_loop(
            model=model,
            input="test",
            record_events=False,
        )
        assert isinstance(result.messages[0], SystemMessage)
        assert result.messages[0].content == DEFAULT_SYSTEM_PROMPT

    @pytest.mark.asyncio
    async def test_message_ordering_with_tool_calls(self):
        """AI response with tool_calls is appended BEFORE ToolMessages."""
        registry = _make_registry_with_tool()
        model = MockModel([
            _tool_call_response("my_tool", {"x": 1}, "call_1"),
            _simple_response("final"),
        ])
        result = await run_tool_calling_loop(
            model=model,
            input="test",
            tools=registry,
            record_events=False,
        )
        # Find the AIMessage with tool_calls and the ToolMessage
        ai_with_tools_idx = None
        tool_msg_idx = None
        for i, m in enumerate(result.messages):
            if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
                ai_with_tools_idx = i
            if isinstance(m, ToolMessage):
                tool_msg_idx = i
                break
        assert ai_with_tools_idx is not None
        assert tool_msg_idx is not None
        assert ai_with_tools_idx < tool_msg_idx


# ---------------------------------------------------------------------------
# AgentResult tests
# ---------------------------------------------------------------------------


class TestAgentResult:
    """Tests for AgentResult dataclass."""

    def test_fields_populated_correctly(self):
        """AgentResult fields populated correctly."""
        result = AgentResult(
            content="hello",
            messages=[],
            tool_calls_made=3,
            token_usage=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
            iterations=2,
            finish_reason="stop",
            agent_id="agent_test",
        )
        assert result.content == "hello"
        assert result.tool_calls_made == 3
        assert result.iterations == 2
        assert result.finish_reason == "stop"
        assert result.agent_id == "agent_test"

    def test_to_dict(self):
        """to_dict() works correctly."""
        result = AgentResult(
            content="hello",
            messages=[],
            tool_calls_made=3,
            token_usage=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
            iterations=2,
            finish_reason="stop",
            agent_id="agent_test",
        )
        d = result.to_dict()
        assert d["content"] == "hello"
        assert d["tool_calls_made"] == 3
        assert d["iterations"] == 2
        assert d["finish_reason"] == "stop"
        assert d["agent_id"] == "agent_test"
        assert d["token_usage"]["input_tokens"] == 100
        assert d["token_usage"]["output_tokens"] == 50
        assert d["token_usage"]["total_tokens"] == 150
        assert isinstance(d["messages"], list)


# ---------------------------------------------------------------------------
# Agent base class tests
# ---------------------------------------------------------------------------


class TestAgentBaseClass:
    """Tests for the Agent ABC."""

    @pytest.mark.asyncio
    async def test_subclass_works(self):
        """Agent base class subclass works (__call__ invokes run_tool_calling_loop)."""
        model = MockModel([_simple_response("from base class")])

        class MyAgent(Agent):
            async def run(self, query: str) -> str:
                return query

        a = MyAgent()
        a.model = model
        result = await a(query="hello")
        assert result.content == "from base class"

    @pytest.mark.asyncio
    async def test_uses_class_docstring_as_system_prompt(self):
        """Agent base class uses class docstring as system_prompt."""
        model = MockModel([_simple_response("ok")])

        class DocAgent(Agent):
            """You are a documentation agent."""
            async def run(self) -> str:
                return "help"

        a = DocAgent()
        a.model = model
        result = await a()
        # System prompt should be the class docstring
        assert isinstance(result.messages[0], SystemMessage)
        assert result.messages[0].content == "You are a documentation agent."

    @pytest.mark.asyncio
    async def test_raises_value_error_when_no_model(self):
        """Agent base class raises ValueError when no model."""

        class NoModelAgent(Agent):
            async def run(self) -> str:
                return "test"

        a = NoModelAgent()
        with pytest.raises(ValueError, match="has no model"):
            await a()

    @pytest.mark.asyncio
    async def test_model_override_at_call_time(self):
        """Agent base class supports _model= override."""
        model = MockModel([_simple_response("override")])

        class MyAgent(Agent):
            async def run(self) -> str:
                return "test"

        a = MyAgent()
        result = await a(_model=model)
        assert result.content == "override"

    @pytest.mark.asyncio
    async def test_get_name_uses_class_name(self):
        """Agent._get_name() returns class name when name is not set."""

        class CustomNamedAgent(Agent):
            async def run(self) -> str:
                return "test"

        a = CustomNamedAgent()
        assert a._get_name() == "CustomNamedAgent"

    @pytest.mark.asyncio
    async def test_get_name_uses_explicit_name(self):
        """Agent._get_name() returns explicit name when set."""

        class MyAgent(Agent):
            name = "explicit_name"
            async def run(self) -> str:
                return "test"

        a = MyAgent()
        assert a._get_name() == "explicit_name"


# ---------------------------------------------------------------------------
# Parallel tool calls tests
# ---------------------------------------------------------------------------


def _multi_tool_call_response(calls):
    """AIMessage with multiple tool calls."""
    return AIMessage(content="", tool_calls=calls)


def _make_multi_registry():
    """Create a ToolRegistry with two tools for parallel testing."""
    from langchain_core.tools import StructuredTool

    def tool_a(x: int) -> str:
        """Tool A."""
        return f"a_{x}"

    def tool_b(y: str) -> str:
        """Tool B."""
        return f"b_{y}"

    ta = StructuredTool.from_function(tool_a, name="tool_a", description="Tool A")
    tb = StructuredTool.from_function(tool_b, name="tool_b", description="Tool B")
    registry = ToolRegistry()
    registry.register(ta)
    registry.register(tb)
    return registry


class TestParallelToolCalls:
    """Tests for parallel tool execution."""

    @pytest.mark.asyncio
    async def test_parallel_execution_with_multiple_tools(self):
        """Multiple tool calls execute concurrently when parallel_tool_calls=True."""
        registry = _make_multi_registry()
        model = MockModel([
            _multi_tool_call_response([
                {"name": "tool_a", "args": {"x": 1}, "id": "call_a"},
                {"name": "tool_b", "args": {"y": "test"}, "id": "call_b"},
            ]),
            _simple_response("parallel done"),
        ])
        result = await run_tool_calling_loop(
            model=model,
            input="test",
            tools=registry,
            parallel_tool_calls=True,
            record_events=False,
        )
        assert result.content == "parallel done"
        assert result.tool_calls_made == 2

        # Verify ToolMessages for both calls exist
        tool_msgs = [m for m in result.messages if isinstance(m, ToolMessage)]
        assert len(tool_msgs) == 2
        contents = {m.content for m in tool_msgs}
        assert "a_1" in contents
        assert "b_test" in contents

    @pytest.mark.asyncio
    async def test_sequential_execution_when_disabled(self):
        """Tool calls execute sequentially when parallel_tool_calls=False."""
        registry = _make_multi_registry()
        model = MockModel([
            _multi_tool_call_response([
                {"name": "tool_a", "args": {"x": 2}, "id": "call_a"},
                {"name": "tool_b", "args": {"y": "seq"}, "id": "call_b"},
            ]),
            _simple_response("sequential done"),
        ])
        result = await run_tool_calling_loop(
            model=model,
            input="test",
            tools=registry,
            parallel_tool_calls=False,
            record_events=False,
        )
        assert result.content == "sequential done"
        assert result.tool_calls_made == 2

    @pytest.mark.asyncio
    async def test_single_tool_call_stays_sequential(self):
        """Single tool call uses sequential path even with parallel_tool_calls=True."""
        registry = _make_registry_with_tool()
        model = MockModel([
            _tool_call_response("my_tool", {"x": 1}, "call_1"),
            _simple_response("done"),
        ])
        result = await run_tool_calling_loop(
            model=model,
            input="test",
            tools=registry,
            parallel_tool_calls=True,
            record_events=False,
        )
        assert result.content == "done"
        assert result.tool_calls_made == 1

    @pytest.mark.asyncio
    async def test_parallel_handles_tool_errors(self):
        """Parallel execution converts exceptions to error ToolMessages."""
        from langchain_core.tools import StructuredTool

        def failing_tool(x: int) -> str:
            """Fails."""
            raise ValueError("boom")

        def good_tool(x: int) -> str:
            """Works."""
            return f"ok_{x}"

        ft = StructuredTool.from_function(failing_tool, name="failing_tool", description="Fails")
        gt = StructuredTool.from_function(good_tool, name="good_tool", description="Works")
        registry = ToolRegistry()
        registry.register(ft)
        registry.register(gt)

        model = MockModel([
            _multi_tool_call_response([
                {"name": "failing_tool", "args": {"x": 1}, "id": "call_f"},
                {"name": "good_tool", "args": {"x": 2}, "id": "call_g"},
            ]),
            _simple_response("recovered from parallel"),
        ])
        result = await run_tool_calling_loop(
            model=model,
            input="test",
            tools=registry,
            parallel_tool_calls=True,
            record_events=False,
        )
        assert result.content == "recovered from parallel"
        tool_msgs = [m for m in result.messages if isinstance(m, ToolMessage)]
        assert len(tool_msgs) == 2
        error_msgs = [m for m in tool_msgs if "Error:" in m.content]
        assert len(error_msgs) == 1


# ---------------------------------------------------------------------------
# HITL (Human-in-the-Loop) tests
# ---------------------------------------------------------------------------


class TestHITLApproval:
    """Tests for human-in-the-loop approval mechanism."""

    @pytest.mark.asyncio
    async def test_approval_required_true_with_handler_approve_all(self):
        """require_approval=True + approval_handler that approves all."""
        registry = _make_registry_with_tool()

        async def approve_all(pending):
            return [{"tool_call_id": p["tool_call_id"], "action": "approve"} for p in pending]

        model = MockModel([
            _tool_call_response("my_tool", {"x": 1}, "call_1"),
            _simple_response("approved done"),
        ])
        result = await run_tool_calling_loop(
            model=model,
            input="test",
            tools=registry,
            require_approval=True,
            approval_handler=approve_all,
            record_events=False,
        )
        assert result.content == "approved done"
        assert result.tool_calls_made == 1
        assert result.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_approval_required_true_with_handler_reject_all(self):
        """require_approval=True + handler rejects all — LLM sees feedback."""
        registry = _make_registry_with_tool()

        async def reject_all(pending):
            return [
                {"tool_call_id": p["tool_call_id"], "action": "reject", "feedback": "Not allowed"}
                for p in pending
            ]

        model = MockModel([
            _tool_call_response("my_tool", {"x": 1}, "call_1"),
            _simple_response("ok understood"),
        ])
        result = await run_tool_calling_loop(
            model=model,
            input="test",
            tools=registry,
            require_approval=True,
            approval_handler=reject_all,
            record_events=False,
        )
        assert result.content == "ok understood"
        assert result.tool_calls_made == 0
        # Check feedback message was injected
        human_msgs = [m for m in result.messages if isinstance(m, HumanMessage)]
        feedback_msgs = [m for m in human_msgs if "rejected" in m.content.lower()]
        assert len(feedback_msgs) == 1

    @pytest.mark.asyncio
    async def test_approval_required_true_no_handler_returns_partial(self):
        """require_approval=True without handler returns approval_required."""
        registry = _make_registry_with_tool()
        model = MockModel([
            _tool_call_response("my_tool", {"x": 1}, "call_1"),
        ])
        result = await run_tool_calling_loop(
            model=model,
            input="test",
            tools=registry,
            require_approval=True,
            record_events=False,
        )
        assert result.finish_reason == "approval_required"
        assert result.pending_tool_calls is not None
        assert len(result.pending_tool_calls) == 1
        assert result.pending_tool_calls[0]["tool_name"] == "my_tool"

    @pytest.mark.asyncio
    async def test_approval_by_tool_name_list(self):
        """require_approval=['my_tool'] filters only named tools."""
        registry = _make_multi_registry()

        approvals_received = []

        async def track_handler(pending):
            approvals_received.extend(pending)
            return [{"tool_call_id": p["tool_call_id"], "action": "approve"} for p in pending]

        model = MockModel([
            _multi_tool_call_response([
                {"name": "tool_a", "args": {"x": 1}, "id": "call_a"},
                {"name": "tool_b", "args": {"y": "test"}, "id": "call_b"},
            ]),
            _simple_response("partial approval done"),
        ])
        result = await run_tool_calling_loop(
            model=model,
            input="test",
            tools=registry,
            require_approval=["tool_a"],
            approval_handler=track_handler,
            record_events=False,
        )
        assert result.content == "partial approval done"
        # Only tool_a should have been sent for approval
        assert len(approvals_received) == 1
        assert approvals_received[0]["tool_name"] == "tool_a"

    @pytest.mark.asyncio
    async def test_approval_by_callable_filter(self):
        """require_approval as callable filters dynamically."""
        registry = _make_registry_with_tool()

        async def approve_all(pending):
            return [{"tool_call_id": p["tool_call_id"], "action": "approve"} for p in pending]

        model = MockModel([
            _tool_call_response("my_tool", {"x": 1}, "call_1"),
            _simple_response("callable filter done"),
        ])
        result = await run_tool_calling_loop(
            model=model,
            input="test",
            tools=registry,
            require_approval=lambda name, args: name == "my_tool",
            approval_handler=approve_all,
            record_events=False,
        )
        assert result.content == "callable filter done"
        assert result.tool_calls_made == 1

    @pytest.mark.asyncio
    async def test_approval_modify_args(self):
        """Handler can modify tool args before execution."""
        registry = _make_registry_with_tool()

        async def modify_handler(pending):
            return [
                {
                    "tool_call_id": p["tool_call_id"],
                    "action": "modify",
                    "modified_args": {"x": 99},
                }
                for p in pending
            ]

        model = MockModel([
            _tool_call_response("my_tool", {"x": 1}, "call_1"),
            _simple_response("modified done"),
        ])
        result = await run_tool_calling_loop(
            model=model,
            input="test",
            tools=registry,
            require_approval=True,
            approval_handler=modify_handler,
            record_events=False,
        )
        assert result.content == "modified done"
        assert result.tool_calls_made == 1
        # Verify the tool was called with modified args (result_99)
        tool_msgs = [m for m in result.messages if isinstance(m, ToolMessage)]
        assert any("result_99" in m.content for m in tool_msgs)

    @pytest.mark.asyncio
    async def test_no_approval_needed_skips_handler(self):
        """When require_approval=None, handler is never called."""
        registry = _make_registry_with_tool()
        handler_called = False

        async def should_not_be_called(pending):
            nonlocal handler_called
            handler_called = True
            return []

        model = MockModel([
            _tool_call_response("my_tool", {"x": 1}, "call_1"),
            _simple_response("no approval"),
        ])
        result = await run_tool_calling_loop(
            model=model,
            input="test",
            tools=registry,
            require_approval=None,
            approval_handler=should_not_be_called,
            record_events=False,
        )
        assert result.content == "no approval"
        assert not handler_called


# ---------------------------------------------------------------------------
# Pause/Resume (on_agent_action) tests
# ---------------------------------------------------------------------------


class TestPauseResume:
    """Tests for on_agent_action callback (pause/resume/steering)."""

    @pytest.mark.asyncio
    async def test_inject_message_via_callback(self):
        """on_agent_action returning str injects HumanMessage."""
        registry = _make_registry_with_tool()
        model = MockModel([
            _tool_call_response("my_tool", {"x": 1}, "call_1"),
            _simple_response("steered response"),
        ])

        async def steer(iteration, response, messages):
            if iteration == 1:
                return "Focus on X instead"
            return None

        result = await run_tool_calling_loop(
            model=model,
            input="test",
            tools=registry,
            on_agent_action=steer,
            record_events=False,
        )
        assert result.content == "steered response"
        # Verify the injected message is in the conversation
        human_msgs = [m for m in result.messages if isinstance(m, HumanMessage)]
        injected = [m for m in human_msgs if m.content == "Focus on X instead"]
        assert len(injected) == 1

    @pytest.mark.asyncio
    async def test_callback_returning_none_continues(self):
        """on_agent_action returning None continues normally."""
        model = MockModel([_simple_response("normal")])

        async def noop(iteration, response, messages):
            return None

        result = await run_tool_calling_loop(
            model=model,
            input="test",
            on_agent_action=noop,
            record_events=False,
        )
        assert result.content == "normal"

    @pytest.mark.asyncio
    async def test_agent_pause_standalone_returns_paused(self):
        """AgentPause in standalone mode returns finish_reason='paused'."""
        registry = _make_registry_with_tool()
        model = MockModel([
            _tool_call_response("my_tool", {"x": 1}, "call_1"),
            _simple_response("should not reach"),
        ])

        async def pause_on_second(iteration, response, messages):
            if iteration == 1:
                return AgentPause(reason="user_pause")
            return None

        result = await run_tool_calling_loop(
            model=model,
            input="test",
            tools=registry,
            on_agent_action=pause_on_second,
            record_events=False,
        )
        assert result.finish_reason == "paused"
        assert result.iterations == 1

    @pytest.mark.asyncio
    async def test_callback_not_called_on_first_iteration(self):
        """on_agent_action is NOT called on iteration 0."""
        callback_calls = []

        async def track_callback(iteration, response, messages):
            callback_calls.append(iteration)
            return None

        registry = _make_registry_with_tool()
        model = MockModel([
            _tool_call_response("my_tool", {"x": 1}, "call_1"),
            _simple_response("done"),
        ])
        result = await run_tool_calling_loop(
            model=model,
            input="test",
            tools=registry,
            on_agent_action=track_callback,
            record_events=False,
        )
        assert result.content == "done"
        # Callback should only be called for iteration 1, not 0
        assert callback_calls == [1]


# ---------------------------------------------------------------------------
# AgentResult new fields tests
# ---------------------------------------------------------------------------


class TestAgentResultNewFields:
    """Tests for new AgentResult fields: pause_token and pending_tool_calls."""

    def test_default_values_are_none(self):
        result = AgentResult(content="test")
        assert result.pause_token is None
        assert result.pending_tool_calls is None

    def test_to_dict_excludes_none_fields(self):
        result = AgentResult(content="test")
        d = result.to_dict()
        assert "pause_token" not in d
        assert "pending_tool_calls" not in d

    def test_to_dict_includes_when_set(self):
        result = AgentResult(
            content="test",
            pause_token="tok_123",
            pending_tool_calls=[{"tool_name": "x"}],
        )
        d = result.to_dict()
        assert d["pause_token"] == "tok_123"
        assert d["pending_tool_calls"] == [{"tool_name": "x"}]


# ---------------------------------------------------------------------------
# AgentPause sentinel tests
# ---------------------------------------------------------------------------


class TestAgentPauseSentinel:
    """Tests for the AgentPause class."""

    def test_default_reason(self):
        pause = AgentPause()
        assert pause.reason == "user_requested"

    def test_custom_reason(self):
        pause = AgentPause(reason="need_input")
        assert pause.reason == "need_input"

    def test_importable_from_top_level(self):
        from pyworkflow_agents import AgentPause as AP
        assert AP is AgentPause
