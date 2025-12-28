"""
Data models for workflow runs, steps, hooks, and related entities.

These schemas define the structure of data stored in various storage backends.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class RunStatus(Enum):
    """Workflow run execution status."""

    PENDING = "pending"
    RUNNING = "running"
    SUSPENDED = "suspended"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"  # Recoverable infrastructure failure (worker loss)
    CANCELLED = "cancelled"
    CONTINUED_AS_NEW = "continued_as_new"  # Workflow continued with fresh history


class StepStatus(Enum):
    """Step execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


class HookStatus(Enum):
    """Hook/webhook status."""

    PENDING = "pending"
    RECEIVED = "received"
    EXPIRED = "expired"
    DISPOSED = "disposed"


class OverlapPolicy(Enum):
    """How to handle overlapping schedule executions."""

    SKIP = "skip"  # Skip if previous run still active
    BUFFER_ONE = "buffer_one"  # Buffer at most one pending execution
    BUFFER_ALL = "buffer_all"  # Buffer all pending executions
    CANCEL_OTHER = "cancel_other"  # Cancel previous run and start new
    ALLOW_ALL = "allow_all"  # Allow concurrent executions


class ScheduleStatus(Enum):
    """Schedule lifecycle status."""

    ACTIVE = "active"
    PAUSED = "paused"
    DELETED = "deleted"


@dataclass
class WorkflowRun:
    """
    Represents a workflow execution run.

    This is the primary entity tracking workflow execution state.
    """

    run_id: str
    workflow_name: str
    status: RunStatus
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # Input/output
    input_args: str = "{}"  # JSON serialized list
    input_kwargs: str = "{}"  # JSON serialized dict
    result: str | None = None  # JSON serialized result
    error: str | None = None  # Error message if failed

    # Configuration
    idempotency_key: str | None = None
    max_duration: str | None = None  # e.g., "1h", "30m"
    context: dict[str, Any] = field(default_factory=dict)  # Step context data

    # Recovery tracking for fault tolerance
    recovery_attempts: int = 0  # Number of recovery attempts after worker failures
    max_recovery_attempts: int = 3  # Maximum recovery attempts allowed
    recover_on_worker_loss: bool = True  # Whether to auto-recover on worker failure

    # Child workflow tracking
    parent_run_id: str | None = None  # Link to parent workflow (None if root)
    nesting_depth: int = 0  # 0=root, 1=child, 2=grandchild (max 3)

    # Continue-as-new chain tracking
    continued_from_run_id: str | None = None  # Previous run in chain
    continued_to_run_id: str | None = None  # Next run in chain

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "run_id": self.run_id,
            "workflow_name": self.workflow_name,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "input_args": self.input_args,
            "input_kwargs": self.input_kwargs,
            "result": self.result,
            "error": self.error,
            "idempotency_key": self.idempotency_key,
            "max_duration": self.max_duration,
            "context": self.context,
            "recovery_attempts": self.recovery_attempts,
            "max_recovery_attempts": self.max_recovery_attempts,
            "recover_on_worker_loss": self.recover_on_worker_loss,
            "parent_run_id": self.parent_run_id,
            "nesting_depth": self.nesting_depth,
            "continued_from_run_id": self.continued_from_run_id,
            "continued_to_run_id": self.continued_to_run_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowRun":
        """Create from dictionary."""
        return cls(
            run_id=data["run_id"],
            workflow_name=data["workflow_name"],
            status=RunStatus(data["status"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            started_at=(
                datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None
            ),
            completed_at=(
                datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None
            ),
            input_args=data.get("input_args", "{}"),
            input_kwargs=data.get("input_kwargs", "{}"),
            result=data.get("result"),
            error=data.get("error"),
            idempotency_key=data.get("idempotency_key"),
            max_duration=data.get("max_duration"),
            # Support both 'context' and legacy 'metadata' key for backward compatibility
            context=data.get("context", data.get("metadata", {})),
            recovery_attempts=data.get("recovery_attempts", 0),
            max_recovery_attempts=data.get("max_recovery_attempts", 3),
            recover_on_worker_loss=data.get("recover_on_worker_loss", True),
            parent_run_id=data.get("parent_run_id"),
            nesting_depth=data.get("nesting_depth", 0),
            continued_from_run_id=data.get("continued_from_run_id"),
            continued_to_run_id=data.get("continued_to_run_id"),
        )


@dataclass
class StepExecution:
    """
    Represents a step execution within a workflow.

    Steps are isolated units of work that can be retried independently.
    """

    step_id: str
    run_id: str
    step_name: str
    status: StepStatus

    # Execution tracking
    attempt: int = 1
    max_retries: int = 3
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # Input/output
    input_args: str = "{}"  # JSON serialized list
    input_kwargs: str = "{}"  # JSON serialized dict
    result: str | None = None  # JSON serialized result
    error: str | None = None  # Error message if failed

    # Retry configuration
    retry_after: datetime | None = None
    retry_delay: str | None = None  # e.g., "exponential", "10s"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "step_id": self.step_id,
            "run_id": self.run_id,
            "step_name": self.step_name,
            "status": self.status.value,
            "attempt": self.attempt,
            "max_retries": self.max_retries,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "input_args": self.input_args,
            "input_kwargs": self.input_kwargs,
            "result": self.result,
            "error": self.error,
            "retry_after": self.retry_after.isoformat() if self.retry_after else None,
            "retry_delay": self.retry_delay,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StepExecution":
        """Create from dictionary."""
        return cls(
            step_id=data["step_id"],
            run_id=data["run_id"],
            step_name=data["step_name"],
            status=StepStatus(data["status"]),
            attempt=data.get("attempt", 1),
            max_retries=data.get("max_retries", 3),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            started_at=(
                datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None
            ),
            completed_at=(
                datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None
            ),
            input_args=data.get("input_args", "{}"),
            input_kwargs=data.get("input_kwargs", "{}"),
            result=data.get("result"),
            error=data.get("error"),
            retry_after=(
                datetime.fromisoformat(data["retry_after"]) if data.get("retry_after") else None
            ),
            retry_delay=data.get("retry_delay"),
        )


@dataclass
class Hook:
    """
    Represents a webhook/hook for external event integration.

    Hooks allow workflows to suspend and wait for external data.
    """

    hook_id: str
    run_id: str
    token: str
    url: str = ""  # Optional webhook URL
    status: HookStatus = HookStatus.PENDING

    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    received_at: datetime | None = None
    expires_at: datetime | None = None

    # Data
    payload: str | None = None  # JSON serialized payload from webhook
    name: str | None = None  # Optional human-readable name
    payload_schema: str | None = None  # JSON schema for payload validation (from Pydantic)

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "hook_id": self.hook_id,
            "run_id": self.run_id,
            "url": self.url,
            "token": self.token,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "payload": self.payload,
            "name": self.name,
            "payload_schema": self.payload_schema,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Hook":
        """Create from dictionary."""
        return cls(
            hook_id=data["hook_id"],
            run_id=data["run_id"],
            token=data["token"],
            url=data.get("url", ""),
            status=HookStatus(data["status"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            received_at=(
                datetime.fromisoformat(data["received_at"]) if data.get("received_at") else None
            ),
            expires_at=(
                datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None
            ),
            payload=data.get("payload"),
            name=data.get("name"),
            payload_schema=data.get("payload_schema"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class CalendarSpec:
    """
    Specification for calendar-based scheduling.

    Defines specific times when a schedule should trigger based on
    calendar components (hour, minute, day of week, etc.).
    """

    second: int = 0
    minute: int = 0
    hour: int = 0
    day_of_month: int | None = None  # 1-31
    month: int | None = None  # 1-12
    day_of_week: int | None = None  # 0=Monday, 6=Sunday (ISO weekday)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "second": self.second,
            "minute": self.minute,
            "hour": self.hour,
            "day_of_month": self.day_of_month,
            "month": self.month,
            "day_of_week": self.day_of_week,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CalendarSpec":
        """Create from dictionary."""
        return cls(
            second=data.get("second", 0),
            minute=data.get("minute", 0),
            hour=data.get("hour", 0),
            day_of_month=data.get("day_of_month"),
            month=data.get("month"),
            day_of_week=data.get("day_of_week"),
        )


@dataclass
class ScheduleSpec:
    """
    Specification for when a schedule should trigger.

    Supports three types of scheduling:
    - cron: Standard cron expression (e.g., "0 9 * * *" for 9 AM daily)
    - interval: Simple interval (e.g., "5m", "1h", "24h")
    - calendar: List of specific calendar times

    Only one of cron, interval, or calendar should be specified.
    """

    cron: str | None = None  # Cron expression
    interval: str | None = None  # Interval string (e.g., "5m", "1h")
    calendar: list[CalendarSpec] | None = None  # Calendar-based specs
    timezone: str = "UTC"  # Timezone for schedule
    start_at: datetime | None = None  # When to start scheduling
    end_at: datetime | None = None  # When to stop scheduling
    jitter: str | None = None  # Random delay to add (e.g., "30s")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "cron": self.cron,
            "interval": self.interval,
            "calendar": [c.to_dict() for c in self.calendar] if self.calendar else None,
            "timezone": self.timezone,
            "start_at": self.start_at.isoformat() if self.start_at else None,
            "end_at": self.end_at.isoformat() if self.end_at else None,
            "jitter": self.jitter,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScheduleSpec":
        """Create from dictionary."""
        calendar = None
        if data.get("calendar"):
            calendar = [CalendarSpec.from_dict(c) for c in data["calendar"]]
        return cls(
            cron=data.get("cron"),
            interval=data.get("interval"),
            calendar=calendar,
            timezone=data.get("timezone", "UTC"),
            start_at=(datetime.fromisoformat(data["start_at"]) if data.get("start_at") else None),
            end_at=(datetime.fromisoformat(data["end_at"]) if data.get("end_at") else None),
            jitter=data.get("jitter"),
        )


@dataclass
class Schedule:
    """
    Represents a workflow schedule.

    Schedules define when and how often a workflow should be automatically
    triggered. They support cron expressions, intervals, and calendar-based
    scheduling with configurable overlap policies.
    """

    schedule_id: str
    workflow_name: str
    spec: ScheduleSpec
    status: ScheduleStatus = ScheduleStatus.ACTIVE
    args: str = "[]"  # JSON serialized list
    kwargs: str = "{}"  # JSON serialized dict
    overlap_policy: OverlapPolicy = OverlapPolicy.SKIP

    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None
    last_run_at: datetime | None = None
    next_run_time: datetime | None = None

    # Execution tracking
    last_run_id: str | None = None
    running_run_ids: list[str] = field(default_factory=list)
    buffered_count: int = 0

    # Statistics
    total_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    skipped_runs: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "schedule_id": self.schedule_id,
            "workflow_name": self.workflow_name,
            "spec": self.spec.to_dict(),
            "status": self.status.value,
            "args": self.args,
            "kwargs": self.kwargs,
            "overlap_policy": self.overlap_policy.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "next_run_time": self.next_run_time.isoformat() if self.next_run_time else None,
            "last_run_id": self.last_run_id,
            "running_run_ids": self.running_run_ids,
            "buffered_count": self.buffered_count,
            "total_runs": self.total_runs,
            "successful_runs": self.successful_runs,
            "failed_runs": self.failed_runs,
            "skipped_runs": self.skipped_runs,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Schedule":
        """Create from dictionary."""
        return cls(
            schedule_id=data["schedule_id"],
            workflow_name=data["workflow_name"],
            spec=ScheduleSpec.from_dict(data["spec"]),
            status=ScheduleStatus(data.get("status", "active")),
            args=data.get("args", "[]"),
            kwargs=data.get("kwargs", "{}"),
            overlap_policy=OverlapPolicy(data.get("overlap_policy", "skip")),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=(
                datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None
            ),
            last_run_at=(
                datetime.fromisoformat(data["last_run_at"]) if data.get("last_run_at") else None
            ),
            next_run_time=(
                datetime.fromisoformat(data["next_run_time"]) if data.get("next_run_time") else None
            ),
            last_run_id=data.get("last_run_id"),
            running_run_ids=data.get("running_run_ids", []),
            buffered_count=data.get("buffered_count", 0),
            total_runs=data.get("total_runs", 0),
            successful_runs=data.get("successful_runs", 0),
            failed_runs=data.get("failed_runs", 0),
            skipped_runs=data.get("skipped_runs", 0),
        )
