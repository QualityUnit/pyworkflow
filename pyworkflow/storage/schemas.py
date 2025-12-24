"""
Data models for workflow runs, steps, hooks, and related entities.

These schemas define the structure of data stored in various storage backends.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Dict, Optional


class RunStatus(Enum):
    """Workflow run execution status."""

    PENDING = "pending"
    RUNNING = "running"
    SUSPENDED = "suspended"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"  # Recoverable infrastructure failure (worker loss)
    CANCELLED = "cancelled"


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
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Input/output
    input_args: str = "{}"  # JSON serialized list
    input_kwargs: str = "{}"  # JSON serialized dict
    result: Optional[str] = None  # JSON serialized result
    error: Optional[str] = None  # Error message if failed

    # Configuration
    idempotency_key: Optional[str] = None
    max_duration: Optional[str] = None  # e.g., "1h", "30m"
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Recovery tracking for fault tolerance
    recovery_attempts: int = 0  # Number of recovery attempts after worker failures
    max_recovery_attempts: int = 3  # Maximum recovery attempts allowed
    recover_on_worker_loss: bool = True  # Whether to auto-recover on worker failure

    def to_dict(self) -> Dict[str, Any]:
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
            "metadata": self.metadata,
            "recovery_attempts": self.recovery_attempts,
            "max_recovery_attempts": self.max_recovery_attempts,
            "recover_on_worker_loss": self.recover_on_worker_loss,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowRun":
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
                datetime.fromisoformat(data["completed_at"])
                if data.get("completed_at")
                else None
            ),
            input_args=data.get("input_args", "{}"),
            input_kwargs=data.get("input_kwargs", "{}"),
            result=data.get("result"),
            error=data.get("error"),
            idempotency_key=data.get("idempotency_key"),
            max_duration=data.get("max_duration"),
            metadata=data.get("metadata", {}),
            recovery_attempts=data.get("recovery_attempts", 0),
            max_recovery_attempts=data.get("max_recovery_attempts", 3),
            recover_on_worker_loss=data.get("recover_on_worker_loss", True),
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
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Input/output
    input_args: str = "{}"  # JSON serialized list
    input_kwargs: str = "{}"  # JSON serialized dict
    result: Optional[str] = None  # JSON serialized result
    error: Optional[str] = None  # Error message if failed

    # Retry configuration
    retry_after: Optional[datetime] = None
    retry_delay: Optional[str] = None  # e.g., "exponential", "10s"

    def to_dict(self) -> Dict[str, Any]:
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
    def from_dict(cls, data: Dict[str, Any]) -> "StepExecution":
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
                datetime.fromisoformat(data["completed_at"])
                if data.get("completed_at")
                else None
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
    received_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    # Data
    payload: Optional[str] = None  # JSON serialized payload from webhook
    name: Optional[str] = None  # Optional human-readable name

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
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
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Hook":
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
            metadata=data.get("metadata", {}),
        )
