"""
Event types and schemas for event sourcing.

All workflow state changes are recorded as events in an append-only log.
Events enable deterministic replay for fault tolerance and resumption.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


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
    WORKFLOW_CONTINUED_AS_NEW = "workflow.continued_as_new"  # Workflow continued with fresh history

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

    # Context events
    CONTEXT_UPDATED = "context.updated"

    # Child workflow events
    CHILD_WORKFLOW_STARTED = "child_workflow.started"
    CHILD_WORKFLOW_COMPLETED = "child_workflow.completed"
    CHILD_WORKFLOW_FAILED = "child_workflow.failed"
    CHILD_WORKFLOW_CANCELLED = "child_workflow.cancelled"

    # Schedule events
    SCHEDULE_CREATED = "schedule.created"
    SCHEDULE_UPDATED = "schedule.updated"
    SCHEDULE_PAUSED = "schedule.paused"
    SCHEDULE_RESUMED = "schedule.resumed"
    SCHEDULE_DELETED = "schedule.deleted"
    SCHEDULE_TRIGGERED = "schedule.triggered"
    SCHEDULE_SKIPPED = "schedule.skipped"
    SCHEDULE_BACKFILL_STARTED = "schedule.backfill_started"
    SCHEDULE_BACKFILL_COMPLETED = "schedule.backfill_completed"


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
    data: dict[str, Any] = field(default_factory=dict)
    sequence: int | None = None  # Assigned by storage layer

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
    metadata: dict[str, Any] | None = None,
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


def create_workflow_completed_event(run_id: str, result: Any, workflow_name: str) -> Event:
    """Create a workflow completed event."""
    return Event(
        run_id=run_id,
        type=EventType.WORKFLOW_COMPLETED,
        data={"result": result, "workflow_name": workflow_name},
    )


def create_workflow_failed_event(
    run_id: str, error: str, error_type: str, traceback: str | None = None
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


def create_workflow_continued_as_new_event(
    run_id: str,
    new_run_id: str,
    args: str,
    kwargs: str,
    reason: str | None = None,
) -> Event:
    """
    Create a workflow continued as new event.

    This event is recorded when a workflow completes by calling
    continue_as_new(), indicating this run is complete and a new
    run has been started with fresh event history.

    Args:
        run_id: The current workflow run ID
        new_run_id: The new workflow run ID
        args: Serialized positional arguments for new workflow
        kwargs: Serialized keyword arguments for new workflow
        reason: Optional reason for continuation

    Returns:
        Event: The workflow continued as new event
    """
    return Event(
        run_id=run_id,
        type=EventType.WORKFLOW_CONTINUED_AS_NEW,
        data={
            "new_run_id": new_run_id,
            "args": args,
            "kwargs": kwargs,
            "reason": reason,
            "continued_at": datetime.now(UTC).isoformat(),
        },
    )


def create_workflow_interrupted_event(
    run_id: str,
    reason: str,
    worker_id: str | None = None,
    last_event_sequence: int | None = None,
    error: str | None = None,
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


def create_step_completed_event(run_id: str, step_id: str, result: Any, step_name: str) -> Event:
    """Create a step completed event."""
    return Event(
        run_id=run_id,
        type=EventType.STEP_COMPLETED,
        data={
            "step_id": step_id,
            "result": result,
            "step_name": step_name,
        },
    )


def create_step_failed_event(
    run_id: str,
    step_id: str,
    error: str,
    error_type: str,
    is_retryable: bool,
    attempt: int,
    traceback: str | None = None,
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
    retry_after: str | None = None,
    error: str | None = None,
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
    name: str | None = None,
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
    expires_at: datetime | None = None,
    name: str | None = None,
    hook_name: str | None = None,
    timeout_seconds: int | None = None,
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
    reason: str | None = None,
    requested_by: str | None = None,
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
    reason: str | None = None,
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
    reason: str | None = None,
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


def create_context_updated_event(
    run_id: str,
    context_data: dict[str, Any],
) -> Event:
    """
    Create a context updated event.

    This event is recorded when set_step_context() is called in workflow code.
    It captures the full context state for deterministic replay.

    Args:
        run_id: The workflow run ID
        context_data: The serialized context data (from StepContext.to_dict())

    Returns:
        Event: The context updated event
    """
    return Event(
        run_id=run_id,
        type=EventType.CONTEXT_UPDATED,
        data={
            "context": context_data,
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )


# Child workflow event creation helpers


def create_child_workflow_started_event(
    run_id: str,
    child_id: str,
    child_run_id: str,
    child_workflow_name: str,
    args: Any,
    kwargs: Any,
    wait_for_completion: bool,
) -> Event:
    """
    Create a child workflow started event.

    This event is recorded in the parent workflow's event log when a child
    workflow is spawned.

    Args:
        run_id: The parent workflow run ID
        child_id: Deterministic child identifier (for replay)
        child_run_id: The child workflow's unique run ID
        child_workflow_name: The name of the child workflow
        args: Serialized positional arguments for child workflow
        kwargs: Serialized keyword arguments for child workflow
        wait_for_completion: Whether parent is waiting for child to complete

    Returns:
        Event: The child workflow started event
    """
    return Event(
        run_id=run_id,
        type=EventType.CHILD_WORKFLOW_STARTED,
        data={
            "child_id": child_id,
            "child_run_id": child_run_id,
            "child_workflow_name": child_workflow_name,
            "args": args,
            "kwargs": kwargs,
            "wait_for_completion": wait_for_completion,
            "started_at": datetime.now(UTC).isoformat(),
        },
    )


def create_child_workflow_completed_event(
    run_id: str,
    child_id: str,
    child_run_id: str,
    result: Any,
) -> Event:
    """
    Create a child workflow completed event.

    This event is recorded in the parent workflow's event log when a child
    workflow completes successfully.

    Args:
        run_id: The parent workflow run ID
        child_id: Deterministic child identifier (for replay)
        child_run_id: The child workflow's run ID
        result: Serialized result from the child workflow

    Returns:
        Event: The child workflow completed event
    """
    return Event(
        run_id=run_id,
        type=EventType.CHILD_WORKFLOW_COMPLETED,
        data={
            "child_id": child_id,
            "child_run_id": child_run_id,
            "result": result,
            "completed_at": datetime.now(UTC).isoformat(),
        },
    )


def create_child_workflow_failed_event(
    run_id: str,
    child_id: str,
    child_run_id: str,
    error: str,
    error_type: str,
) -> Event:
    """
    Create a child workflow failed event.

    This event is recorded in the parent workflow's event log when a child
    workflow fails.

    Args:
        run_id: The parent workflow run ID
        child_id: Deterministic child identifier (for replay)
        child_run_id: The child workflow's run ID
        error: Error message from the child workflow
        error_type: The exception type that caused the failure

    Returns:
        Event: The child workflow failed event
    """
    return Event(
        run_id=run_id,
        type=EventType.CHILD_WORKFLOW_FAILED,
        data={
            "child_id": child_id,
            "child_run_id": child_run_id,
            "error": error,
            "error_type": error_type,
            "failed_at": datetime.now(UTC).isoformat(),
        },
    )


def create_child_workflow_cancelled_event(
    run_id: str,
    child_id: str,
    child_run_id: str,
    reason: str | None = None,
) -> Event:
    """
    Create a child workflow cancelled event.

    This event is recorded in the parent workflow's event log when a child
    workflow is cancelled (typically due to parent completion or explicit cancel).

    Args:
        run_id: The parent workflow run ID
        child_id: Deterministic child identifier (for replay)
        child_run_id: The child workflow's run ID
        reason: Optional reason for cancellation

    Returns:
        Event: The child workflow cancelled event
    """
    return Event(
        run_id=run_id,
        type=EventType.CHILD_WORKFLOW_CANCELLED,
        data={
            "child_id": child_id,
            "child_run_id": child_run_id,
            "reason": reason,
            "cancelled_at": datetime.now(UTC).isoformat(),
        },
    )


# Schedule event creation helpers


def create_schedule_created_event(
    run_id: str,
    schedule_id: str,
    workflow_name: str,
    spec: dict[str, Any],
    overlap_policy: str,
) -> Event:
    """
    Create a schedule created event.

    This event is recorded when a new schedule is created.

    Args:
        run_id: The run ID (use schedule_id for schedule-level events)
        schedule_id: The schedule identifier
        workflow_name: Name of the workflow being scheduled
        spec: The schedule specification (as dict)
        overlap_policy: The overlap policy for the schedule

    Returns:
        Event: The schedule created event
    """
    return Event(
        run_id=run_id,
        type=EventType.SCHEDULE_CREATED,
        data={
            "schedule_id": schedule_id,
            "workflow_name": workflow_name,
            "spec": spec,
            "overlap_policy": overlap_policy,
            "created_at": datetime.now(UTC).isoformat(),
        },
    )


def create_schedule_triggered_event(
    run_id: str,
    schedule_id: str,
    scheduled_time: datetime,
    actual_time: datetime,
    workflow_run_id: str,
) -> Event:
    """
    Create a schedule triggered event.

    This event is recorded when a schedule triggers a workflow execution.

    Args:
        run_id: The workflow run ID being created
        schedule_id: The schedule identifier
        scheduled_time: The time the schedule was supposed to trigger
        actual_time: The actual time the trigger occurred
        workflow_run_id: The ID of the workflow run being created

    Returns:
        Event: The schedule triggered event
    """
    return Event(
        run_id=run_id,
        type=EventType.SCHEDULE_TRIGGERED,
        data={
            "schedule_id": schedule_id,
            "scheduled_time": scheduled_time.isoformat(),
            "actual_time": actual_time.isoformat(),
            "workflow_run_id": workflow_run_id,
        },
    )


def create_schedule_skipped_event(
    run_id: str,
    schedule_id: str,
    reason: str,
    scheduled_time: datetime,
    overlap_policy: str | None = None,
) -> Event:
    """
    Create a schedule skipped event.

    This event is recorded when a scheduled execution is skipped,
    typically due to overlap policy or schedule being paused.

    Args:
        run_id: The run ID (use schedule_id for schedule-level events)
        schedule_id: The schedule identifier
        reason: The reason for skipping
        scheduled_time: The time the schedule was supposed to trigger
        overlap_policy: The overlap policy that caused the skip

    Returns:
        Event: The schedule skipped event
    """
    return Event(
        run_id=run_id,
        type=EventType.SCHEDULE_SKIPPED,
        data={
            "schedule_id": schedule_id,
            "reason": reason,
            "scheduled_time": scheduled_time.isoformat(),
            "overlap_policy": overlap_policy,
            "skipped_at": datetime.now(UTC).isoformat(),
        },
    )


def create_schedule_paused_event(
    run_id: str,
    schedule_id: str,
    reason: str | None = None,
) -> Event:
    """
    Create a schedule paused event.

    Args:
        run_id: The run ID (use schedule_id for schedule-level events)
        schedule_id: The schedule identifier
        reason: Optional reason for pausing

    Returns:
        Event: The schedule paused event
    """
    return Event(
        run_id=run_id,
        type=EventType.SCHEDULE_PAUSED,
        data={
            "schedule_id": schedule_id,
            "reason": reason,
            "paused_at": datetime.now(UTC).isoformat(),
        },
    )


def create_schedule_resumed_event(
    run_id: str,
    schedule_id: str,
    next_run_time: datetime | None = None,
) -> Event:
    """
    Create a schedule resumed event.

    Args:
        run_id: The run ID (use schedule_id for schedule-level events)
        schedule_id: The schedule identifier
        next_run_time: The next scheduled run time after resumption

    Returns:
        Event: The schedule resumed event
    """
    return Event(
        run_id=run_id,
        type=EventType.SCHEDULE_RESUMED,
        data={
            "schedule_id": schedule_id,
            "next_run_time": next_run_time.isoformat() if next_run_time else None,
            "resumed_at": datetime.now(UTC).isoformat(),
        },
    )


def create_schedule_deleted_event(
    run_id: str,
    schedule_id: str,
    reason: str | None = None,
) -> Event:
    """
    Create a schedule deleted event.

    Args:
        run_id: The run ID (use schedule_id for schedule-level events)
        schedule_id: The schedule identifier
        reason: Optional reason for deletion

    Returns:
        Event: The schedule deleted event
    """
    return Event(
        run_id=run_id,
        type=EventType.SCHEDULE_DELETED,
        data={
            "schedule_id": schedule_id,
            "reason": reason,
            "deleted_at": datetime.now(UTC).isoformat(),
        },
    )


def create_schedule_backfill_started_event(
    run_id: str,
    schedule_id: str,
    start_time: datetime,
    end_time: datetime,
    expected_runs: int,
) -> Event:
    """
    Create a schedule backfill started event.

    Args:
        run_id: The run ID (use schedule_id for schedule-level events)
        schedule_id: The schedule identifier
        start_time: Start of the backfill period
        end_time: End of the backfill period
        expected_runs: Expected number of runs to create

    Returns:
        Event: The schedule backfill started event
    """
    return Event(
        run_id=run_id,
        type=EventType.SCHEDULE_BACKFILL_STARTED,
        data={
            "schedule_id": schedule_id,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "expected_runs": expected_runs,
            "started_at": datetime.now(UTC).isoformat(),
        },
    )


def create_schedule_backfill_completed_event(
    run_id: str,
    schedule_id: str,
    runs_created: int,
    run_ids: list[str],
) -> Event:
    """
    Create a schedule backfill completed event.

    Args:
        run_id: The run ID (use schedule_id for schedule-level events)
        schedule_id: The schedule identifier
        runs_created: Number of runs actually created
        run_ids: List of created run IDs

    Returns:
        Event: The schedule backfill completed event
    """
    return Event(
        run_id=run_id,
        type=EventType.SCHEDULE_BACKFILL_COMPLETED,
        data={
            "schedule_id": schedule_id,
            "runs_created": runs_created,
            "run_ids": run_ids,
            "completed_at": datetime.now(UTC).isoformat(),
        },
    )
