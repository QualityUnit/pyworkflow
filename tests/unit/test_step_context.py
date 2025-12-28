"""
Unit tests for StepContext - step-level context access for distributed execution.

Tests cover:
- StepContext base class (immutability, with_updates, serialization)
- Context accessors (get_step_context, set_step_context, has_step_context)
- Read-only enforcement in steps
- Context class registration
- Internal API functions
"""

import pytest
from pydantic import ValidationError

from pyworkflow.context.step_context import (
    StepContext,
    _reset_step_context,
    _reset_step_context_class,
    _reset_step_context_readonly,
    _set_step_context_class,
    _set_step_context_internal,
    _set_step_context_readonly,
    get_step_context,
    get_step_context_class,
    has_step_context,
    set_step_context,
)


# Test context subclass
class OrderContext(StepContext):
    """Example context for testing."""

    workspace_id: str = ""
    user_id: str = ""
    order_id: str = ""
    tags: list[str] = []


@pytest.fixture(autouse=True)
def reset_context_vars():
    """Reset all context variables before and after each test."""
    # Reset before test
    token1 = _set_step_context_internal(None)
    token2 = _set_step_context_readonly(False)
    token3 = _set_step_context_class(None)

    yield

    # Reset after test
    _reset_step_context(token1)
    _reset_step_context_readonly(token2)
    _reset_step_context_class(token3)


class TestStepContextClass:
    """Test the StepContext base class."""

    def test_create_context_with_defaults(self):
        """Test creating context with default values."""
        ctx = OrderContext()

        assert ctx.workspace_id == ""
        assert ctx.user_id == ""
        assert ctx.order_id == ""
        assert ctx.tags == []

    def test_create_context_with_values(self):
        """Test creating context with explicit values."""
        ctx = OrderContext(
            workspace_id="ws-123", user_id="user-456", order_id="order-789", tags=["priority"]
        )

        assert ctx.workspace_id == "ws-123"
        assert ctx.user_id == "user-456"
        assert ctx.order_id == "order-789"
        assert ctx.tags == ["priority"]

    def test_context_is_frozen(self):
        """Test that context is immutable (frozen)."""
        ctx = OrderContext(workspace_id="ws-123")

        with pytest.raises(ValidationError):
            ctx.workspace_id = "ws-456"  # type: ignore[misc]

    def test_context_forbids_extra_fields(self):
        """Test that extra fields are not allowed."""
        with pytest.raises(ValidationError):
            OrderContext(workspace_id="ws-123", unknown_field="value")  # type: ignore[call-arg]

    def test_with_updates_creates_new_instance(self):
        """Test that with_updates creates a new context instance."""
        ctx1 = OrderContext(workspace_id="ws-123", user_id="user-456")
        ctx2 = ctx1.with_updates(workspace_id="ws-789")

        # Original unchanged
        assert ctx1.workspace_id == "ws-123"
        assert ctx1.user_id == "user-456"

        # New instance with updated value
        assert ctx2.workspace_id == "ws-789"
        assert ctx2.user_id == "user-456"  # Preserved

        # Different instances
        assert ctx1 is not ctx2

    def test_with_updates_multiple_fields(self):
        """Test updating multiple fields at once."""
        ctx1 = OrderContext(workspace_id="ws-123", user_id="user-456", order_id="order-789")
        ctx2 = ctx1.with_updates(user_id="user-new", order_id="order-new")

        assert ctx2.workspace_id == "ws-123"  # Unchanged
        assert ctx2.user_id == "user-new"
        assert ctx2.order_id == "order-new"

    def test_to_dict(self):
        """Test serializing context to dictionary."""
        ctx = OrderContext(workspace_id="ws-123", user_id="user-456", tags=["a", "b"])

        data = ctx.to_dict()

        assert data == {
            "workspace_id": "ws-123",
            "user_id": "user-456",
            "order_id": "",
            "tags": ["a", "b"],
        }

    def test_from_dict(self):
        """Test deserializing context from dictionary."""
        data = {"workspace_id": "ws-123", "user_id": "user-456", "order_id": "", "tags": []}

        ctx = OrderContext.from_dict(data)

        assert ctx.workspace_id == "ws-123"
        assert ctx.user_id == "user-456"

    def test_from_dict_with_extra_fields_ignored(self):
        """Test that from_dict handles extra fields gracefully."""
        # Note: with extra="forbid", this should fail
        data = {"workspace_id": "ws-123", "extra_field": "value"}

        with pytest.raises(ValidationError):
            OrderContext.from_dict(data)

    def test_roundtrip_serialization(self):
        """Test that to_dict/from_dict roundtrip preserves data."""
        original = OrderContext(
            workspace_id="ws-123",
            user_id="user-456",
            order_id="order-789",
            tags=["priority", "vip"],
        )

        data = original.to_dict()
        restored = OrderContext.from_dict(data)

        assert restored == original


class TestGetStepContext:
    """Test get_step_context() function."""

    def test_get_context_raises_when_not_set(self):
        """Test that get_step_context raises when no context is set."""
        with pytest.raises(RuntimeError, match="No step context available"):
            get_step_context()

    def test_get_context_returns_set_context(self):
        """Test that get_step_context returns the set context."""
        ctx = OrderContext(workspace_id="ws-123")
        _set_step_context_internal(ctx)

        result = get_step_context()

        assert result is ctx
        assert result.workspace_id == "ws-123"


class TestSetStepContext:
    """Test set_step_context() function."""

    @pytest.mark.asyncio
    async def test_set_context_stores_context(self):
        """Test that set_step_context stores the context."""
        ctx = OrderContext(workspace_id="ws-123")

        await set_step_context(ctx)

        assert has_step_context()
        assert get_step_context() is ctx

    @pytest.mark.asyncio
    async def test_set_context_raises_in_readonly_mode(self):
        """Test that set_step_context raises when in read-only mode."""
        _set_step_context_readonly(True)
        ctx = OrderContext(workspace_id="ws-123")

        with pytest.raises(RuntimeError, match="Cannot modify step context within a step"):
            await set_step_context(ctx)

    @pytest.mark.asyncio
    async def test_set_context_raises_for_non_step_context(self):
        """Test that set_step_context raises for non-StepContext types."""
        with pytest.raises(TypeError, match="Expected StepContext instance"):
            await set_step_context({"workspace_id": "ws-123"})  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_set_context_replaces_previous_context(self):
        """Test that setting context replaces the previous one."""
        ctx1 = OrderContext(workspace_id="ws-123")
        ctx2 = OrderContext(workspace_id="ws-456")

        await set_step_context(ctx1)
        assert get_step_context().workspace_id == "ws-123"

        await set_step_context(ctx2)
        assert get_step_context().workspace_id == "ws-456"


class TestHasStepContext:
    """Test has_step_context() function."""

    def test_has_context_false_when_not_set(self):
        """Test has_step_context returns False when no context is set."""
        assert has_step_context() is False

    def test_has_context_true_when_set(self):
        """Test has_step_context returns True when context is set."""
        ctx = OrderContext(workspace_id="ws-123")
        _set_step_context_internal(ctx)

        assert has_step_context() is True


class TestStepContextClassRegistration:
    """Test context class registration."""

    def test_get_context_class_returns_none_by_default(self):
        """Test get_step_context_class returns None when not registered."""
        assert get_step_context_class() is None

    def test_get_context_class_returns_registered_class(self):
        """Test get_step_context_class returns the registered class."""
        _set_step_context_class(OrderContext)

        result = get_step_context_class()

        assert result is OrderContext

    def test_context_class_can_be_reset(self):
        """Test that context class can be reset."""
        token = _set_step_context_class(OrderContext)
        assert get_step_context_class() is OrderContext

        _reset_step_context_class(token)
        assert get_step_context_class() is None


class TestReadonlyMode:
    """Test read-only mode enforcement."""

    @pytest.mark.asyncio
    async def test_readonly_mode_prevents_set_context(self):
        """Test that readonly mode prevents setting context."""
        ctx = OrderContext(workspace_id="ws-123")
        _set_step_context_internal(ctx)

        # Enable readonly mode (simulating step execution)
        _set_step_context_readonly(True)

        # Should be able to read
        result = get_step_context()
        assert result.workspace_id == "ws-123"

        # But not write
        new_ctx = ctx.with_updates(workspace_id="ws-456")
        with pytest.raises(RuntimeError, match="Cannot modify step context"):
            await set_step_context(new_ctx)

    @pytest.mark.asyncio
    async def test_readonly_mode_can_be_reset(self):
        """Test that readonly mode can be disabled."""
        ctx = OrderContext(workspace_id="ws-123")

        # Enable and then disable readonly
        token = _set_step_context_readonly(True)
        _reset_step_context_readonly(token)

        # Should be able to set context now
        await set_step_context(ctx)
        assert get_step_context() is ctx


class TestInternalAPI:
    """Test internal API functions."""

    def test_set_step_context_internal_bypasses_readonly(self):
        """Test that internal set bypasses readonly check."""
        _set_step_context_readonly(True)
        ctx = OrderContext(workspace_id="ws-123")

        # Internal API should work despite readonly
        _set_step_context_internal(ctx)

        assert get_step_context() is ctx

    def test_reset_step_context_restores_previous_value(self):
        """Test that reset_step_context restores previous value."""
        ctx1 = OrderContext(workspace_id="ws-123")
        ctx2 = OrderContext(workspace_id="ws-456")

        _set_step_context_internal(ctx1)
        token = _set_step_context_internal(ctx2)

        assert get_step_context() is ctx2

        _reset_step_context(token)
        assert get_step_context() is ctx1

    def test_token_based_reset_is_scoped(self):
        """Test that token-based reset is properly scoped."""
        ctx1 = OrderContext(workspace_id="ws-1")
        ctx2 = OrderContext(workspace_id="ws-2")
        ctx3 = OrderContext(workspace_id="ws-3")

        token1 = _set_step_context_internal(ctx1)
        _set_step_context_internal(ctx2)
        token3 = _set_step_context_internal(ctx3)

        # Reset to token3 (ctx2)
        _reset_step_context(token3)
        assert get_step_context().workspace_id == "ws-2"

        # Reset to token1 (None)
        _reset_step_context(token1)
        assert not has_step_context()


class TestStepContextInheritance:
    """Test StepContext subclass behavior."""

    def test_custom_context_inherits_methods(self):
        """Test that custom context inherits all StepContext methods."""

        class CustomContext(StepContext):
            field1: str = ""
            field2: int = 0

        ctx = CustomContext(field1="hello", field2=42)

        # Inherited methods should work
        assert ctx.with_updates(field2=100).field2 == 100
        assert ctx.to_dict() == {"field1": "hello", "field2": 42}
        assert CustomContext.from_dict({"field1": "world", "field2": 99}).field1 == "world"

    def test_nested_context_class(self):
        """Test context with nested Pydantic models."""
        from pydantic import BaseModel

        class Address(BaseModel):
            street: str
            city: str

            model_config = {"frozen": True}

        class CustomerContext(StepContext):
            customer_id: str = ""
            address: Address | None = None

        ctx = CustomerContext(
            customer_id="cust-123", address=Address(street="123 Main St", city="Boston")
        )

        # Serialization should work
        data = ctx.to_dict()
        assert data["address"]["street"] == "123 Main St"

        # Deserialization should work
        restored = CustomerContext.from_dict(data)
        assert restored.address is not None
        assert restored.address.city == "Boston"

    def test_context_with_optional_fields(self):
        """Test context with optional fields."""

        class OptionalContext(StepContext):
            required_field: str
            optional_field: str | None = None

        # Can create without optional
        ctx1 = OptionalContext(required_field="value")
        assert ctx1.optional_field is None

        # Can create with optional
        ctx2 = OptionalContext(required_field="value", optional_field="optional")
        assert ctx2.optional_field == "optional"

        # Roundtrip preserves None
        data = ctx1.to_dict()
        restored = OptionalContext.from_dict(data)
        assert restored.optional_field is None


class TestContextEquality:
    """Test context equality and comparison."""

    def test_contexts_with_same_values_are_equal(self):
        """Test that contexts with same values are equal."""
        ctx1 = OrderContext(workspace_id="ws-123", user_id="user-456")
        ctx2 = OrderContext(workspace_id="ws-123", user_id="user-456")

        assert ctx1 == ctx2

    def test_contexts_with_different_values_are_not_equal(self):
        """Test that contexts with different values are not equal."""
        ctx1 = OrderContext(workspace_id="ws-123")
        ctx2 = OrderContext(workspace_id="ws-456")

        assert ctx1 != ctx2

    def test_context_hash_is_consistent(self):
        """Test that context hash is consistent for equal objects.

        Note: Pydantic models with list/dict fields are not hashable.
        Use contexts with only hashable fields (str, int, etc.) for hashing.
        """

        class HashableContext(StepContext):
            field1: str = ""
            field2: int = 0

        ctx1 = HashableContext(field1="hello", field2=42)
        ctx2 = HashableContext(field1="hello", field2=42)

        # Frozen Pydantic models with hashable fields should be hashable
        assert hash(ctx1) == hash(ctx2)

    def test_context_can_be_used_in_set(self):
        """Test that contexts can be used in sets.

        Note: Pydantic models with list/dict fields are not hashable.
        Use contexts with only hashable fields for set membership.
        """

        class HashableContext(StepContext):
            field1: str = ""

        ctx1 = HashableContext(field1="value-1")
        ctx2 = HashableContext(field1="value-1")  # Same value
        ctx3 = HashableContext(field1="value-2")  # Different value

        context_set = {ctx1, ctx2, ctx3}

        # ctx1 and ctx2 are equal, so set should have 2 items
        assert len(context_set) == 2
