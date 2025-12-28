"""
Step Context - User-defined context accessible from steps during distributed execution.

StepContext provides a type-safe, immutable context that can be accessed from steps
running on remote Celery workers. Unlike WorkflowContext which is process-local,
StepContext is serialized and passed to workers.

Key design decisions:
- **Immutable in steps**: Steps can only read context, not mutate it. This prevents
  race conditions when multiple steps execute in parallel.
- **Mutable in workflow**: Workflow code can update context via set_step_context().
  Updates are recorded as CONTEXT_UPDATED events for deterministic replay.
- **User-extensible**: Users subclass StepContext to define their own typed fields.

Usage:
    from pyworkflow.context import StepContext, get_step_context, set_step_context

    # Define custom context
    class OrderContext(StepContext):
        workspace_id: str = ""
        user_id: str = ""
        order_id: str = ""

    @workflow(context_class=OrderContext)
    async def process_order(order_id: str, user_id: str):
        # Initialize context in workflow
        ctx = OrderContext(order_id=order_id, user_id=user_id)
        await set_step_context(ctx)  # Note: async call

        # Update context (creates new immutable instance)
        ctx = get_step_context()
        ctx = ctx.with_updates(workspace_id="ws-123")
        await set_step_context(ctx)

        result = await validate_order()
        return result

    @step
    async def validate_order():
        # Read-only access in steps
        ctx = get_step_context()
        print(f"Validating order {ctx.order_id}")

        # This would raise RuntimeError - context is read-only in steps:
        # set_step_context(ctx.with_updates(workspace_id="new"))

        return {"valid": True}
"""

from contextvars import ContextVar, Token
from typing import Any, Self

from pydantic import BaseModel, ConfigDict


class StepContext(BaseModel):
    """
    Base class for user-defined step context.

    StepContext is immutable (frozen) to prevent accidental mutation.
    Use with_updates() to create a new context with modified values.

    The context is automatically:
    - Persisted to storage when set_step_context() is called in workflow code
    - Loaded from storage when a step executes on a Celery worker
    - Replayed from CONTEXT_UPDATED events during workflow resumption

    Example:
        class FlowContext(StepContext):
            workspace_id: str = ""
            user_id: str = ""
            attachments: list[str] = []

        @workflow(context_class=FlowContext)
        async def my_workflow():
            ctx = FlowContext(workspace_id="ws-123")
            set_step_context(ctx)
            ...
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    def with_updates(self: Self, **kwargs: Any) -> Self:
        """
        Create a new context with updated values.

        Since StepContext is immutable, this creates a new instance
        with the specified fields updated.

        Args:
            **kwargs: Fields to update

        Returns:
            New StepContext instance with updated values

        Example:
            ctx = ctx.with_updates(workspace_id="ws-456", user_id="user-789")
        """
        return self.model_copy(update=kwargs)

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize context to dictionary for storage.

        Returns:
            Dictionary representation of the context
        """
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """
        Deserialize context from storage.

        Args:
            data: Dictionary representation of the context

        Returns:
            StepContext instance
        """
        return cls.model_validate(data)


# ---------------------------------------------------------------------------
# Context Variables
# ---------------------------------------------------------------------------

# Current step context (may be None if not set)
_step_context: ContextVar[StepContext | None] = ContextVar("step_context", default=None)

# Whether context is read-only (True when executing inside a step)
_step_context_readonly: ContextVar[bool] = ContextVar("step_context_readonly", default=False)

# The context class registered with the workflow (for deserialization)
_step_context_class: ContextVar[type[StepContext] | None] = ContextVar(
    "step_context_class", default=None
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_step_context() -> StepContext:
    """
    Get the current step context.

    This function can be called from both workflow code and step code.
    In step code, the context is read-only.

    Returns:
        Current StepContext instance

    Raises:
        RuntimeError: If no step context is available

    Example:
        @step
        async def my_step():
            ctx = get_step_context()
            print(f"Working in workspace: {ctx.workspace_id}")
    """
    ctx = _step_context.get()
    if ctx is None:
        raise RuntimeError(
            "No step context available. "
            "Ensure the workflow is decorated with @workflow(context_class=YourContext) "
            "and set_step_context() was called."
        )
    return ctx


async def set_step_context(ctx: StepContext) -> None:
    """
    Set the current step context and persist to storage.

    This function can only be called from workflow code, not from within steps.
    When called, the context is persisted to storage and a CONTEXT_UPDATED event
    is recorded for deterministic replay.

    Args:
        ctx: The StepContext instance to set

    Raises:
        RuntimeError: If called from within a step (read-only mode)
        TypeError: If ctx is not a StepContext instance

    Example:
        @workflow(context_class=OrderContext)
        async def my_workflow():
            ctx = OrderContext(order_id="123")
            await set_step_context(ctx)  # OK - in workflow code

            await my_step()  # Step cannot call set_step_context()
    """
    if _step_context_readonly.get():
        raise RuntimeError(
            "Cannot modify step context within a step. "
            "Context is read-only during step execution to prevent race conditions. "
            "Return data from the step and update context in workflow code instead."
        )

    if not isinstance(ctx, StepContext):
        raise TypeError(f"Expected StepContext instance, got {type(ctx).__name__}")

    # Set the context in the contextvar
    _step_context.set(ctx)

    # Persist to storage if we're in a durable workflow
    from pyworkflow.context import get_context, has_context

    if has_context():
        workflow_ctx = get_context()
        if workflow_ctx.is_durable and workflow_ctx.storage is not None:
            from pyworkflow.engine.events import create_context_updated_event

            # Record CONTEXT_UPDATED event for replay
            event = create_context_updated_event(
                run_id=workflow_ctx.run_id,
                context_data=ctx.to_dict(),
            )
            await workflow_ctx.storage.record_event(event)

            # Update the WorkflowRun.context field
            await workflow_ctx.storage.update_run_context(workflow_ctx.run_id, ctx.to_dict())


def has_step_context() -> bool:
    """
    Check if step context is available.

    Returns:
        True if step context is set, False otherwise
    """
    return _step_context.get() is not None


def get_step_context_class() -> type[StepContext] | None:
    """
    Get the registered step context class for the current workflow.

    Returns:
        The StepContext subclass, or None if not registered
    """
    return _step_context_class.get()


# ---------------------------------------------------------------------------
# Internal API (for framework use)
# ---------------------------------------------------------------------------


def _set_step_context_internal(ctx: StepContext | None) -> Token[StepContext | None]:
    """
    Internal: Set step context without readonly check.

    Used by the framework when loading context on workers.
    """
    return _step_context.set(ctx)


def _reset_step_context(token: Token[StepContext | None]) -> None:
    """
    Internal: Reset step context to previous value.
    """
    _step_context.reset(token)


def _set_step_context_readonly(readonly: bool) -> Token[bool]:
    """
    Internal: Set readonly mode for step execution.
    """
    return _step_context_readonly.set(readonly)


def _reset_step_context_readonly(token: Token[bool]) -> None:
    """
    Internal: Reset readonly mode.
    """
    _step_context_readonly.reset(token)


def _set_step_context_class(cls: type[StepContext] | None) -> Token[type[StepContext] | None]:
    """
    Internal: Set the context class for deserialization.
    """
    return _step_context_class.set(cls)


def _reset_step_context_class(token: Token[type[StepContext] | None]) -> None:
    """
    Internal: Reset context class.
    """
    _step_context_class.reset(token)
