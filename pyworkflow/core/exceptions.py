"""
Exception classes for workflow error handling.

PyWorkflow distinguishes between fatal errors (don't retry) and retriable errors
(automatic retry with configurable delay).
"""

from datetime import datetime, timedelta
from typing import Any


class WorkflowError(Exception):
    """Base exception for all workflow-related errors."""

    pass


class FatalError(WorkflowError):
    """
    Non-retriable error that permanently fails the workflow.

    Use FatalError for business logic errors, validation failures, or any error
    where retrying won't help (e.g., insufficient funds, resource not found).

    Example:
        @step
        async def validate_payment(order_id: str):
            order = await get_order(order_id)
            if order.total > customer.balance:
                raise FatalError("Insufficient funds")
    """

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message)
        self.message = message
        self.metadata = kwargs


class CancellationError(WorkflowError):
    """
    Raised when a workflow or step is cancelled.

    Use CancellationError to handle graceful cancellation in workflows.
    Workflows can catch this exception to perform cleanup operations
    before terminating.

    Note:
        CancellationError is raised at checkpoint boundaries (before steps,
        sleeps, hooks), not during step execution. Long-running steps can
        call ``ctx.check_cancellation()`` for cooperative cancellation.

    Example:
        @workflow
        async def order_workflow(order_id: str):
            try:
                await reserve_inventory()
                await charge_payment()
                await ship_order()
            except CancellationError:
                # Cleanup on cancellation
                await release_inventory()
                await refund_payment()
                raise  # Re-raise to mark as cancelled

    Attributes:
        message: Description of the cancellation
        reason: Optional reason for cancellation (e.g., "user_requested", "timeout")
    """

    def __init__(
        self,
        message: str = "Workflow was cancelled",
        reason: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class RetryableError(WorkflowError):
    """
    Retriable error that triggers automatic retry with optional delay.

    Use RetryableError for temporary failures like network errors, rate limits,
    or transient service unavailability.

    Args:
        message: Error description
        retry_after: Delay before retry as:
            - str: Duration string ("30s", "5m", "1h")
            - int: Seconds
            - timedelta: Python timedelta object
            - datetime: Specific time to retry
            - None: Use default/exponential backoff

    Examples:
        # Retry with default delay (exponential backoff)
        raise RetryableError("Network timeout")

        # Retry after specific delay
        raise RetryableError("Rate limited", retry_after="60s")

        # Retry at specific time (from API retry-after header)
        retry_time = datetime.now() + timedelta(seconds=api_retry_after)
        raise RetryableError("API rate limit", retry_after=retry_time)
    """

    def __init__(
        self,
        message: str,
        retry_after: str | int | timedelta | datetime | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.retry_after = retry_after
        self.metadata = kwargs

    def get_retry_delay_seconds(self) -> int | None:
        """
        Get retry delay in seconds.

        Returns:
            Number of seconds to wait before retry, or None for default
        """
        if self.retry_after is None:
            return None

        if isinstance(self.retry_after, int):
            return self.retry_after

        if isinstance(self.retry_after, str):
            return self._parse_duration_string(self.retry_after)

        if isinstance(self.retry_after, timedelta):
            return int(self.retry_after.total_seconds())

        if isinstance(self.retry_after, datetime):
            delta = self.retry_after - datetime.utcnow()
            return max(0, int(delta.total_seconds()))

        return None

    @staticmethod
    def _parse_duration_string(duration: str) -> int:
        """Parse duration string like '30s', '5m', '1h' into seconds."""
        import re

        pattern = r"^(\d+)([smhdw])$"
        match = re.match(pattern, duration.lower())
        if not match:
            raise ValueError(f"Invalid duration format: {duration}")

        value, unit = match.groups()
        value = int(value)

        multipliers = {
            "s": 1,
            "m": 60,
            "h": 3600,
            "d": 86400,
            "w": 604800,
        }

        return value * multipliers[unit]


class SuspensionSignal(Exception):
    """
    Internal signal to suspend workflow execution (not for user use).

    Raised when a workflow hits a suspension point (sleep, hook) to signal
    that it should pause and schedule resumption.

    This is an internal implementation detail and should not be caught or
    raised by user code.
    """

    def __init__(self, reason: str, **data: Any) -> None:
        super().__init__(f"Workflow suspended: {reason}")
        self.reason = reason
        self.data = data


class ContinueAsNewSignal(Exception):
    """
    Internal signal to continue workflow as a new run.

    Raised when workflow calls continue_as_new() to terminate
    current execution and start fresh with new event history.

    This is an internal implementation detail and should not be caught or
    raised by user code.
    """

    def __init__(
        self,
        workflow_args: tuple = (),
        workflow_kwargs: dict[str, Any] | None = None,
    ) -> None:
        super().__init__("Workflow continuing as new execution")
        self.workflow_args = workflow_args
        self.workflow_kwargs = workflow_kwargs or {}


class WorkflowNotFoundError(WorkflowError):
    """Raised when a workflow run cannot be found."""

    def __init__(self, run_id: str) -> None:
        super().__init__(f"Workflow run not found: {run_id}")
        self.run_id = run_id


class WorkflowTimeoutError(WorkflowError):
    """Raised when a workflow exceeds its maximum duration."""

    def __init__(self, run_id: str, max_duration: str) -> None:
        super().__init__(f"Workflow {run_id} exceeded max duration: {max_duration}")
        self.run_id = run_id
        self.max_duration = max_duration


class StepNotFoundError(WorkflowError):
    """Raised when a step cannot be found."""

    def __init__(self, step_id: str) -> None:
        super().__init__(f"Step not found: {step_id}")
        self.step_id = step_id


class HookExpiredError(WorkflowError):
    """Raised when a hook has expired without receiving data."""

    def __init__(self, hook_id: str) -> None:
        super().__init__(f"Hook expired: {hook_id}")
        self.hook_id = hook_id


class InvalidTokenError(WorkflowError):
    """Raised when a hook token is invalid or doesn't match."""

    def __init__(self, hook_id: str) -> None:
        super().__init__(f"Invalid token for hook: {hook_id}")
        self.hook_id = hook_id


class HookNotFoundError(WorkflowError):
    """Raised when a hook cannot be found by token."""

    def __init__(self, token: str) -> None:
        super().__init__(f"Hook not found for token: {token}")
        self.token = token


class HookAlreadyReceivedError(WorkflowError):
    """Raised when attempting to resume a hook that was already resumed."""

    def __init__(self, hook_id: str) -> None:
        super().__init__(f"Hook already received: {hook_id}")
        self.hook_id = hook_id


class EventLimitExceededError(FatalError):
    """
    Raised when workflow exceeds maximum allowed events (hard limit).

    This is a safety mechanism to prevent runaway workflows from consuming
    excessive resources. The default limit is 50,000 events.
    """

    def __init__(self, run_id: str, event_count: int, limit: int) -> None:
        super().__init__(
            f"Workflow {run_id} exceeded maximum event limit: {event_count} >= {limit}"
        )
        self.run_id = run_id
        self.event_count = event_count
        self.limit = limit


class WorkflowAlreadyRunningError(WorkflowError):
    """Raised when attempting to start a workflow that's already running."""

    def __init__(self, run_id: str) -> None:
        super().__init__(f"Workflow already running: {run_id}")
        self.run_id = run_id


class SerializationError(WorkflowError):
    """Raised when data cannot be serialized or deserialized."""

    def __init__(self, message: str, data_type: type | None = None) -> None:
        super().__init__(message)
        self.data_type = data_type


class ContextError(WorkflowError):
    """Raised when workflow context is not available or invalid."""

    pass


class ChildWorkflowError(WorkflowError):
    """Base exception for child workflow errors."""

    pass


class ChildWorkflowFailedError(ChildWorkflowError):
    """
    Raised when a child workflow fails.

    This exception is raised in the parent workflow when a child
    workflow fails and wait_for_completion=True.

    Attributes:
        child_run_id: The failed child's run ID
        child_workflow_name: The failed child's workflow name
        error: The error message from the child
        error_type: The exception type that caused the failure
    """

    def __init__(
        self,
        child_run_id: str,
        child_workflow_name: str,
        error: str,
        error_type: str,
    ) -> None:
        super().__init__(f"Child workflow '{child_workflow_name}' ({child_run_id}) failed: {error}")
        self.child_run_id = child_run_id
        self.child_workflow_name = child_workflow_name
        self.error = error
        self.error_type = error_type


class MaxNestingDepthError(ChildWorkflowError):
    """
    Raised when maximum child workflow nesting depth is exceeded.

    PyWorkflow limits child workflow nesting to 3 levels to prevent
    runaway recursion and maintain reasonable execution complexity.
    """

    MAX_DEPTH = 3

    def __init__(self, current_depth: int) -> None:
        super().__init__(
            f"Maximum nesting depth of {self.MAX_DEPTH} exceeded. "
            f"Current depth: {current_depth}. "
            f"Consider restructuring your workflow to reduce nesting."
        )
        self.current_depth = current_depth
        self.max_depth = self.MAX_DEPTH
