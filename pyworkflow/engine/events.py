"""
Event types and schemas for event sourcing.

All workflow state changes are recorded as events in an append-only log.
Events enable deterministic replay for fault tolerance and resumption.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Dict, Optional
import uuid


class EventType(Enum):
    """All possible event types in the workflow system."""

    # Workflow lifecycle events
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_FAILED = "workflow.failed"
    WORKFLOW_INTERRUPTED = "workflow.interrupted"  # Infrastructure failure (worker loss)
    WORKFLOW_CANCELLED = "workflow.cancelled"
    WORKFLOW_PAUSED = "workflow.paused"
    WORKFLOW_RESUMED = "workflow.resumed"

    # Step lifecycle events
    STEP_STARTED = "step.started"
    STEP_COMPLETED = "step.completed"
    STEP_FAILED = "step.failed"
    STEP_RETRYING = "step.retrying"
    STEP_CANCELLED = "step.cancelled"

    # Sleep/wait events
    SLEEP_STARTED = "sleep.started"
    SLEEP_COMPLETED = "sleep.completed"

    # Hook/webhook events
    HOOK_CREATED = "hook.created"
    HOOK_RECEIVED = "hook.received"
    HOOK_EXPIRED = "hook.expired"
    HOOK_DISPOSED = "hook.disposed"

    # Cancellation events
    CANCELLATION_REQUESTED = "cancellation.requested"


@dataclass
class Event:
    """
    Base event structure for all workflow events.

    Events are immutable records of state changes, stored in an append-only log.
    The sequence number is assigned by the storage layer to ensure ordering.
    """

    event_id: str = field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:16]}")
    run_id: str = ""
    type: EventType = EventType.WORKFLOW_STARTED
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    data: Dict[str, Any] = field(default_factory=dict)
    sequence: Optional[int] = None  # Assigned by storage layer

    def __post_init__(self) -> None:
        """Validate event after initialization."""
        if not self.run_id:
            raise ValueError("Event must have a run_id")
        if not isinstance(self.type, EventType):
            raise TypeError(f"Event type must be EventType enum, got {type(self.type)}")


# Event creation helpers for common event types

def create_workflow_started_event(
    run_id: str,
    workflow_name: str,
    args: Any,
    kwargs: Any,
    metadata: Optional[Dict[str, Any]] = None,
) -> Event:
    """Create a workflow started event."""
    return Event(
        run_id=run_id,
        type=EventType.WORKFLOW_STARTED,
        data={
            "workflow_name": workflow_name,
            "args": args,
            "kwargs": kwargs,
            "metadata": metadata or {},
        },
    )


def create_workflow_completed_event(run_id: str, result: Any) -> Event:
    """Create a workflow completed event."""
    return Event(
        run_id=run_id,
        type=EventType.WORKFLOW_COMPLETED,
        data={"result": result},
    )


def create_workflow_failed_event(
    run_id: str, error: str, error_type: str, traceback: Optional[str] = None
) -> Event:
    """Create a workflow failed event."""
    return Event(
        run_id=run_id,
        type=EventType.WORKFLOW_FAILED,
        data={
            "error": error,
            "error_type": error_type,
            "traceback": traceback,
        },
    )


def create_workflow_interrupted_event(
    run_id: str,
    reason: str,
    worker_id: Optional[str] = None,
    last_event_sequence: Optional[int] = None,
    error: Optional[str] = None,
    recovery_attempt: int = 1,
    recoverable: bool = True,
) -> Event:
    """
    Create a workflow interrupted event.

    This event is recorded when a workflow is interrupted due to infrastructure
    failures (e.g., worker crash, timeout, signal) rather than application errors.

    Args:
        run_id: The workflow run ID
        reason: Interruption reason (e.g., "worker_lost", "timeout", "signal")
        worker_id: ID of the worker that was handling the task
        last_event_sequence: Sequence number of the last recorded event
        error: Optional error message
        recovery_attempt: Current recovery attempt number
        recoverable: Whether the workflow can be recovered

    Returns:
        Event: The workflow interrupted event
    """
    return Event(
        run_id=run_id,
        type=EventType.WORKFLOW_INTERRUPTED,
        data={
            "reason": reason,
            "worker_id": worker_id,
            "last_event_sequence": last_event_sequence,
            "error": error,
            "recovery_attempt": recovery_attempt,
            "recoverable": recoverable,
        },
    )


def create_step_started_event(
    run_id: str,
    step_id: str,
    step_name: str,
    args: Any,
    kwargs: Any,
    attempt: int = 1,
) -> Event:
    """Create a step started event."""
    return Event(
        run_id=run_id,
        type=EventType.STEP_STARTED,
        data={
            "step_id": step_id,
            "step_name": step_name,
            "args": args,
            "kwargs": kwargs,
            "attempt": attempt,
        },
    )


def create_step_completed_event(run_id: str, step_id: str, result: Any) -> Event:
    """Create a step completed event."""
    return Event(
        run_id=run_id,
        type=EventType.STEP_COMPLETED,
        data={
            "step_id": step_id,
            "result": result,
        },
    )


def create_step_failed_event(
    run_id: str,
    step_id: str,
    error: str,
    error_type: str,
    is_retryable: bool,
    attempt: int,
    traceback: Optional[str] = None,
) -> Event:
    """Create a step failed event."""
    return Event(
        run_id=run_id,
        type=EventType.STEP_FAILED,
        data={
            "step_id": step_id,
            "error": error,
            "error_type": error_type,
            "is_retryable": is_retryable,
            "attempt": attempt,
            "traceback": traceback,
        },
    )


def create_step_retrying_event(
    run_id: str,
    step_id: str,
    attempt: int,
    retry_after: Optional[str] = None,
    error: Optional[str] = None,
) -> Event:
    """Create a step retrying event."""
    return Event(
        run_id=run_id,
        type=EventType.STEP_RETRYING,
        data={
            "step_id": step_id,
            "attempt": attempt,
            "retry_after": retry_after,
            "error": error,
        },
    )


def create_sleep_started_event(
    run_id: str,
    sleep_id: str,
    duration_seconds: int,
    resume_at: datetime,
    name: Optional[str] = None,
) -> Event:
    """Create a sleep started event."""
    return Event(
        run_id=run_id,
        type=EventType.SLEEP_STARTED,
        data={
            "sleep_id": sleep_id,
            "duration_seconds": duration_seconds,
            "resume_at": resume_at.isoformat(),
            "name": name,
        },
    )


def create_sleep_completed_event(run_id: str, sleep_id: str) -> Event:
    """Create a sleep completed event."""
    return Event(
        run_id=run_id,
        type=EventType.SLEEP_COMPLETED,
        data={"sleep_id": sleep_id},
    )


def create_hook_created_event(
    run_id: str,
    hook_id: str,
    token: str = "",
    url: str = "",
    expires_at: Optional[datetime] = None,
    name: Optional[str] = None,
    hook_name: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
) -> Event:
    """
    Create a hook created event.

    Args:
        run_id: Workflow run ID
        hook_id: Unique hook identifier
        token: Security token for resuming the hook
        url: Optional webhook URL
        expires_at: Optional expiration datetime
        name: Optional hook name (alias: hook_name)
        hook_name: Alias for name (for backwards compatibility)
        timeout_seconds: Alternative to expires_at (converted internally)
    """
    # Handle aliases
    actual_name = name or hook_name

    # Convert timeout_seconds to expires_at if provided
    actual_expires_at = expires_at
    if timeout_seconds and not expires_at:
        from datetime import UTC, timedelta
        actual_expires_at = datetime.now(UTC) + timedelta(seconds=timeout_seconds)

    return Event(
        run_id=run_id,
        type=EventType.HOOK_CREATED,
        data={
            "hook_id": hook_id,
            "url": url,
            "token": token,
            "expires_at": actual_expires_at.isoformat() if actual_expires_at else None,
            "name": actual_name,
        },
    )


def create_hook_received_event(run_id: str, hook_id: str, payload: Any) -> Event:
    """Create a hook received event."""
    return Event(
        run_id=run_id,
        type=EventType.HOOK_RECEIVED,
        data={
            "hook_id": hook_id,
            "payload": payload,
        },
    )


def create_hook_expired_event(run_id: str, hook_id: str) -> Event:
    """Create a hook expired event."""
    return Event(
        run_id=run_id,
        type=EventType.HOOK_EXPIRED,
        data={"hook_id": hook_id},
    )


def create_cancellation_requested_event(
    run_id: str,
    reason: Optional[str] = None,
    requested_by: Optional[str] = None,
) -> Event:
    """
    Create a cancellation requested event.

    This event is recorded when cancellation is requested for a workflow.
    It signals that the workflow should terminate gracefully.

    Args:
        run_id: The workflow run ID
        reason: Optional reason for cancellation (e.g., "user_requested", "timeout")
        requested_by: Optional identifier of who/what requested the cancellation

    Returns:
        Event: The cancellation requested event
    """
    return Event(
        run_id=run_id,
        type=EventType.CANCELLATION_REQUESTED,
        data={
            "reason": reason,
            "requested_by": requested_by,
            "requested_at": datetime.now(UTC).isoformat(),
        },
    )


def create_workflow_cancelled_event(
    run_id: str,
    reason: Optional[str] = None,
    cleanup_completed: bool = False,
) -> Event:
    """
    Create a workflow cancelled event.

    This event is recorded when a workflow has been successfully cancelled,
    optionally after cleanup operations have completed.

    Args:
        run_id: The workflow run ID
        reason: Optional reason for cancellation
        cleanup_completed: Whether cleanup operations completed successfully

    Returns:
        Event: The workflow cancelled event
    """
    return Event(
        run_id=run_id,
        type=EventType.WORKFLOW_CANCELLED,
        data={
            "reason": reason,
            "cleanup_completed": cleanup_completed,
            "cancelled_at": datetime.now(UTC).isoformat(),
        },
    )


def create_step_cancelled_event(
    run_id: str,
    step_id: str,
    step_name: str,
    reason: Optional[str] = None,
) -> Event:
    """
    Create a step cancelled event.

    This event is recorded when a step is cancelled, either because the
    workflow was cancelled or the step was explicitly terminated.

    Args:
        run_id: The workflow run ID
        step_id: The unique step identifier
        step_name: The name of the step
        reason: Optional reason for cancellation

    Returns:
        Event: The step cancelled event
    """
    return Event(
        run_id=run_id,
        type=EventType.STEP_CANCELLED,
        data={
            "step_id": step_id,
            "step_name": step_name,
            "reason": reason,
            "cancelled_at": datetime.now(UTC).isoformat(),
        },
    )
