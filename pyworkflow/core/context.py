"""
Workflow execution context management.

The context stores the current execution state and provides access to:
- Workflow run metadata
- Event log for replay
- Cached step results
- Hook results
- Current execution mode (normal vs replay)
"""

from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional, Set

from pyworkflow.core.exceptions import ContextError
from pyworkflow.engine.events import Event


# Thread-safe context variable for current workflow execution
_current_context: ContextVar[Optional["WorkflowContext"]] = ContextVar(
    "workflow_context", default=None
)


@dataclass
class WorkflowContext:
    """
    Execution context for a workflow run.

    The context is created when a workflow starts and maintains state
    throughout execution and replay.
    """

    # Workflow identification
    run_id: str
    workflow_name: str

    # Storage backend for event logging
    storage: Any  # StorageBackend (avoid circular import)

    # Event log and replay state
    event_log: List[Event] = field(default_factory=list)
    is_replaying: bool = False
    replay_index: int = 0

    # Cached results from completed steps (for replay)
    step_results: Dict[str, Any] = field(default_factory=dict)

    # Completed sleeps (for replay)
    completed_sleeps: Set[str] = field(default_factory=set)

    # Pending operations
    pending_sleeps: Dict[str, datetime] = field(default_factory=dict)  # sleep_id -> resume_at
    pending_hooks: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Hook results (from webhooks)
    hook_results: Dict[str, Any] = field(default_factory=dict)

    # Timing information
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    current_step_id: Optional[str] = None
    current_attempt: int = 1

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def should_execute_step(self, step_id: str) -> bool:
        """
        Determine if a step should execute or use cached result.

        During replay, steps that have already completed return cached results.
        New steps (not in event log) are executed normally.

        Args:
            step_id: Unique step identifier

        Returns:
            True if step should execute, False if cached result should be used
        """
        return step_id not in self.step_results

    def get_step_result(self, step_id: str) -> Any:
        """
        Get cached result for a step.

        Args:
            step_id: Step identifier

        Returns:
            Cached result

        Raises:
            KeyError: If step result not found
        """
        return self.step_results[step_id]

    def cache_step_result(self, step_id: str, result: Any) -> None:
        """
        Cache a step result for replay.

        Args:
            step_id: Step identifier
            result: Result to cache
        """
        self.step_results[step_id] = result

    def has_hook_result(self, hook_id: str) -> bool:
        """Check if a hook has received data."""
        return hook_id in self.hook_results

    def get_hook_result(self, hook_id: str) -> Any:
        """
        Get result from a hook.

        Args:
            hook_id: Hook identifier

        Returns:
            Hook payload

        Raises:
            KeyError: If hook result not found
        """
        return self.hook_results[hook_id]

    def cache_hook_result(self, hook_id: str, payload: Any) -> None:
        """
        Cache a hook result.

        Args:
            hook_id: Hook identifier
            payload: Webhook payload
        """
        self.hook_results[hook_id] = payload
        # Remove from pending
        self.pending_hooks.pop(hook_id, None)

    def should_execute_sleep(self, sleep_id: str) -> bool:
        """
        Determine if a sleep should execute or has already completed.

        During replay, sleeps that have already completed are skipped.

        Args:
            sleep_id: Unique sleep identifier

        Returns:
            True if sleep should execute, False if already completed
        """
        return sleep_id not in self.completed_sleeps

    def add_pending_sleep(self, sleep_id: str, resume_at: datetime) -> None:
        """
        Mark a sleep as pending.

        Args:
            sleep_id: Sleep identifier
            resume_at: When the sleep should resume
        """
        self.pending_sleeps[sleep_id] = resume_at

    def mark_sleep_completed(self, sleep_id: str) -> None:
        """
        Mark a sleep as completed.

        Args:
            sleep_id: Sleep identifier
        """
        self.completed_sleeps.add(sleep_id)
        self.pending_sleeps.pop(sleep_id, None)

    def is_sleep_completed(self, sleep_id: str) -> bool:
        """
        Check if a sleep has completed.

        Args:
            sleep_id: Sleep identifier

        Returns:
            True if sleep completed
        """
        return sleep_id in self.completed_sleeps

    def add_pending_hook(self, hook_id: str, hook_data: Dict[str, Any]) -> None:
        """Mark a hook as pending."""
        self.pending_hooks[hook_id] = hook_data

    def __enter__(self) -> "WorkflowContext":
        """Context manager entry - set as current context."""
        _current_context.set(self)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit - clear current context."""
        _current_context.set(None)


def get_current_context() -> WorkflowContext:
    """
    Get the current workflow execution context.

    This function can be called from anywhere within a workflow or step
    to access the execution context.

    Returns:
        Current WorkflowContext

    Raises:
        ContextError: If called outside a workflow context

    Example:
        @workflow
        async def my_workflow():
            ctx = get_current_context()
            print(f"Running workflow: {ctx.run_id}")
    """
    ctx = _current_context.get()
    if ctx is None:
        raise ContextError(
            "No workflow context available. This function must be called "
            "within a workflow or step execution."
        )
    return ctx


def set_current_context(context: Optional[WorkflowContext]) -> None:
    """
    Set the current workflow context.

    This is typically called by the workflow executor, not user code.

    Args:
        context: WorkflowContext to set as current, or None to clear
    """
    _current_context.set(context)


def has_current_context() -> bool:
    """
    Check if a workflow context is currently available.

    Returns:
        True if context is available, False otherwise
    """
    return _current_context.get() is not None
