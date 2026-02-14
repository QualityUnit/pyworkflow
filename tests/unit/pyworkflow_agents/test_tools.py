"""Tests for pyworkflow_agents.tools — decorator, registry, and dataclasses."""

import pytest

lc = pytest.importorskip("langchain_core")

from langchain_core.tools import BaseTool, StructuredTool  # noqa: E402

from pyworkflow_agents.tools import (  # noqa: E402
    ToolDefinition,
    ToolResult,
    ToolRegistry,
    get_global_registry,
    reset_global_registry,
    tool,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sync_tool(*, register: bool = False) -> StructuredTool:
    @tool(register=register)
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    return add


def _make_async_tool(*, register: bool = False) -> StructuredTool:
    @tool(register=register)
    async def multiply(a: int, b: int) -> int:
        """Multiply two numbers."""
        return a * b

    return multiply


# ---------------------------------------------------------------------------
# @tool decorator
# ---------------------------------------------------------------------------


class TestToolDecorator:
    """Tests 1-6: @tool decorator behavior."""

    def test_creates_structured_tool(self):
        """Test 1: @tool creates a StructuredTool (isinstance BaseTool)."""
        t = _make_sync_tool()
        assert isinstance(t, StructuredTool)
        assert isinstance(t, BaseTool)

    def test_infers_name_from_function(self):
        """Test 2: @tool infers name from function name."""
        t = _make_sync_tool()
        assert t.name == "add"

    def test_uses_provided_name_and_description(self):
        """Test 3: @tool uses provided name/description overrides."""

        @tool(name="custom_name", description="A custom description", register=False)
        def whatever(x: int) -> int:
            return x

        assert whatever.name == "custom_name"
        assert whatever.description == "A custom description"

    def test_handles_async_functions(self):
        """Test 4: @tool handles async functions."""
        t = _make_async_tool()
        assert isinstance(t, StructuredTool)
        assert t.coroutine is not None

    def test_register_true_auto_registers(self):
        """Test 5: @tool(register=True) auto-registers in global registry."""
        reset_global_registry()

        @tool(register=True)
        def greet(name: str) -> str:
            """Greet someone."""
            return f"Hello, {name}!"

        registry = get_global_registry()
        assert "greet" in registry
        assert registry.get("greet") is greet
        reset_global_registry()

    def test_register_false_does_not_register(self):
        """Test 6: @tool(register=False) does not register."""
        reset_global_registry()
        _make_sync_tool(register=False)
        registry = get_global_registry()
        assert "add" not in registry
        reset_global_registry()


# ---------------------------------------------------------------------------
# ToolRegistry
# ---------------------------------------------------------------------------


class TestToolRegistry:
    """Tests 7-13, 18-19: ToolRegistry behavior."""

    def test_register_get_roundtrip(self):
        """Test 7: register/get round-trip."""
        reg = ToolRegistry()
        t = _make_sync_tool()
        reg.register(t)
        assert reg.get("add") is t

    def test_warns_on_duplicate_name(self, caplog):
        """Test 8: warns on duplicate tool names."""
        reg = ToolRegistry()
        t1 = _make_sync_tool()
        t2 = _make_sync_tool()
        reg.register(t1)
        with caplog.at_level("WARNING"):
            reg.register(t2)
        assert "Duplicate tool name" in caplog.text

    def test_get_all_returns_all_tools(self):
        """Test 9: get_all returns all registered tools."""
        reg = ToolRegistry()
        t1 = _make_sync_tool()
        t2 = _make_async_tool()
        reg.register(t1)
        reg.register(t2)
        all_tools = reg.get_all()
        assert len(all_tools) == 2
        names = {t.name for t in all_tools}
        assert names == {"add", "multiply"}

    def test_get_definitions_returns_tool_definitions(self):
        """Test 10: get_definitions returns ToolDefinition objects."""
        reg = ToolRegistry()
        t = _make_sync_tool()
        reg.register(t)
        defs = reg.get_definitions()
        assert len(defs) == 1
        assert isinstance(defs[0], ToolDefinition)
        assert defs[0].name == "add"
        assert isinstance(defs[0].parameters, dict)

    @pytest.mark.asyncio
    async def test_execute_runs_tool_and_returns_result(self):
        """Test 11: execute runs tool and returns ToolResult with timing."""
        reg = ToolRegistry()
        t = _make_sync_tool()
        reg.register(t)
        result = await reg.execute("add", {"a": 2, "b": 3}, tool_call_id="call_1")
        assert isinstance(result, ToolResult)
        assert result.result == "5" or result.result == 5
        assert result.is_error is False
        assert result.error is None
        assert result.duration_ms >= 0
        assert result.tool_call_id == "call_1"

    @pytest.mark.asyncio
    async def test_execute_handles_errors(self):
        """Test 12: execute handles errors, returns ToolResult with is_error=True."""
        reg = ToolRegistry()

        @tool(register=False)
        def failing_tool(x: int) -> int:
            """Always fails."""
            raise ValueError("something broke")

        reg.register(failing_tool)
        result = await reg.execute("failing_tool", {"x": 1})
        assert result.is_error is True
        assert "something broke" in result.error
        assert result.result is None

    @pytest.mark.asyncio
    async def test_execute_raises_key_error_for_unknown_tool(self):
        """Test 13: execute raises KeyError for unknown tool."""
        reg = ToolRegistry()
        with pytest.raises(KeyError, match="not_registered"):
            await reg.execute("not_registered", {})

    def test_len(self):
        """Test 18a: __len__ works."""
        reg = ToolRegistry()
        assert len(reg) == 0
        reg.register(_make_sync_tool())
        assert len(reg) == 1

    def test_contains(self):
        """Test 18b: __contains__ works."""
        reg = ToolRegistry()
        t = _make_sync_tool()
        assert "add" not in reg
        reg.register(t)
        assert "add" in reg

    def test_unregister_removes_tool(self):
        """Test 19: unregister removes a tool."""
        reg = ToolRegistry()
        t = _make_sync_tool()
        reg.register(t)
        assert "add" in reg
        reg.unregister("add")
        assert "add" not in reg
        assert reg.get("add") is None


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


class TestDataclasses:
    """Test 14: ToolResult/ToolDefinition dataclass fields."""

    def test_tool_definition_fields(self):
        td = ToolDefinition(name="foo", description="bar", parameters={"type": "object"})
        assert td.name == "foo"
        assert td.description == "bar"
        assert td.parameters == {"type": "object"}
        d = td.to_dict()
        assert d["name"] == "foo"

    def test_tool_result_fields(self):
        tr = ToolResult(
            tool_name="foo",
            tool_call_id="c1",
            result=42,
            error=None,
            duration_ms=1.5,
            is_error=False,
        )
        assert tr.tool_name == "foo"
        assert tr.tool_call_id == "c1"
        assert tr.result == 42
        assert tr.error is None
        assert tr.duration_ms == 1.5
        assert tr.is_error is False
        d = tr.to_dict()
        assert d["result"] == 42

    def test_tool_result_defaults(self):
        tr = ToolResult(tool_name="x", tool_call_id="", result="ok")
        assert tr.error is None
        assert tr.duration_ms == 0.0
        assert tr.is_error is False


# ---------------------------------------------------------------------------
# BaseTool compatibility
# ---------------------------------------------------------------------------


class TestBaseToolCompatibility:
    """Test 15: Produced tool compatible with BaseTool interface."""

    def test_has_base_tool_attributes(self):
        t = _make_sync_tool()
        assert hasattr(t, "name")
        assert hasattr(t, "description")
        assert hasattr(t, "args")
        assert isinstance(t.name, str)
        assert isinstance(t.description, str)
        assert isinstance(t.args, dict)


# ---------------------------------------------------------------------------
# Global registry
# ---------------------------------------------------------------------------


class TestGlobalRegistry:
    """Tests 16-17: global registry singleton behavior."""

    def test_get_global_registry_returns_singleton(self):
        """Test 16: get_global_registry returns the same instance."""
        reset_global_registry()
        r1 = get_global_registry()
        r2 = get_global_registry()
        assert r1 is r2
        reset_global_registry()

    def test_reset_global_registry_clears_singleton(self):
        """Test 17: reset_global_registry clears singleton."""
        reset_global_registry()
        r1 = get_global_registry()
        r1.register(_make_sync_tool())
        assert len(r1) == 1
        reset_global_registry()
        r2 = get_global_registry()
        assert len(r2) == 0
        assert r1 is not r2
        reset_global_registry()
