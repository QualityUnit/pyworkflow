"""
Resume hook primitive for external event delivery.

Allows external systems to deliver payloads to suspended workflows.
Uses events for idempotency checks (no separate hook storage needed).
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from pyworkflow.core.exceptions import (
    HookAlreadyReceivedError,
    HookExpiredError,
    HookNotFoundError,
    InvalidTokenError,
)
from pyworkflow.engine.events import EventType
from pyworkflow.storage.base import StorageBackend

# Token format separator
HOOK_TOKEN_SEPARATOR = ":"


def parse_hook_token(token: str) -> tuple[str, str]:
    """
    Parse a composite hook token into run_id and hook_id.

    Args:
        token: Composite token in format "run_id:hook_id"

    Returns:
        Tuple of (run_id, hook_id)

    Raises:
        InvalidTokenError: If token format is invalid
    """
    parts = token.split(HOOK_TOKEN_SEPARATOR, 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise InvalidTokenError(f"Invalid token format: {token}")
    return parts[0], parts[1]


def create_hook_token(run_id: str, hook_id: str) -> str:
    """
    Create a composite hook token from run_id and hook_id.

    Args:
        run_id: The workflow run ID
        hook_id: The hook ID

    Returns:
        Composite token in format "run_id:hook_id"
    """
    return f"{run_id}{HOOK_TOKEN_SEPARATOR}{hook_id}"


@dataclass
class ResumeResult:
    """Result of a resume_hook operation."""

    run_id: str
    hook_id: str
    status: str  # "resumed", "already_received", "expired", "not_found"

    def __repr__(self) -> str:
        return f"ResumeResult(run_id={self.run_id!r}, hook_id={self.hook_id!r}, status={self.status!r})"


async def resume_hook(
    token: str,
    payload: Any,
    *,
    storage: StorageBackend | None = None,
) -> ResumeResult:
    """
    Resume a suspended workflow with a payload.

    This function is called by external systems (webhooks, APIs, etc.)
    to deliver data to a waiting workflow.

    Idempotency is checked via events:
    - HOOK_CREATED event must exist for the hook_id
    - HOOK_RECEIVED event must not exist (would mean already resumed)

    Args:
        token: The hook token (composite format: run_id:hook_id)
        payload: Data to send to the workflow
        storage: Storage backend. If None, uses the configured default.

    Returns:
        ResumeResult with run_id, hook_id, and status

    Raises:
        InvalidTokenError: If the token format is invalid
        HookNotFoundError: If no hook exists with the given token
        HookExpiredError: If the hook has expired
        HookAlreadyReceivedError: If the hook was already resumed

    Examples:
        # In a FastAPI endpoint
        @app.post("/webhook/{token}")
        async def handle_webhook(token: str, payload: dict):
            result = await resume_hook(token, payload)
            return {"run_id": result.run_id, "status": result.status}

        # With explicit storage
        result = await resume_hook(
            token="run_abc123:hook_approval_1",
            payload={"approved": True},
            storage=my_storage,
        )
    """
    # Get storage backend
    if storage is None:
        from pyworkflow import get_storage

        storage = get_storage()

    if storage is None:
        raise RuntimeError(
            "No storage backend configured. "
            "Either pass storage parameter or call pyworkflow.configure(storage=...)"
        )

    # Parse token to get run_id and hook_id
    run_id, hook_id = parse_hook_token(token)

    # Get all events for this run to check hook status
    events = await storage.get_events(run_id)

    # Find HOOK_CREATED event for this hook_id
    hook_created_event = None
    hook_received_event = None

    for event in events:
        if event.type == EventType.HOOK_CREATED:
            if event.data.get("hook_id") == hook_id:
                hook_created_event = event
        elif event.type == EventType.HOOK_RECEIVED and event.data.get("hook_id") == hook_id:
            hook_received_event = event

    # Check if hook was created
    if hook_created_event is None:
        logger.warning(f"Hook not found: {hook_id} (run_id={run_id})")
        raise HookNotFoundError(token)

    # Check if already received (idempotency check)
    if hook_received_event is not None:
        logger.warning(f"Hook already received: {hook_id}")
        raise HookAlreadyReceivedError(hook_id)

    # Check expiration
    expires_at_str = hook_created_event.data.get("expires_at")
    if expires_at_str:
        expires_at = datetime.fromisoformat(expires_at_str)
        if datetime.now(UTC) > expires_at:
            logger.warning(f"Hook expired: {hook_id}")
            raise HookExpiredError(hook_id)

    logger.info(
        f"Resuming hook: {hook_id}",
        run_id=run_id,
        hook_id=hook_id,
    )

    # Record HOOK_RECEIVED event (this is the idempotency marker and payload store)
    from pyworkflow.engine.events import create_hook_received_event
    from pyworkflow.serialization.encoder import serialize
    from pyworkflow.storage.schemas import HookStatus

    serialized_payload = serialize(payload)

    event = create_hook_received_event(
        run_id=run_id,
        hook_id=hook_id,
        payload=serialized_payload,
    )
    await storage.record_event(event)

    # Update hook status in storage
    await storage.update_hook_status(
        hook_id=hook_id,
        status=HookStatus.RECEIVED,
        payload=serialized_payload,
    )

    # Schedule workflow resumption via configured runtime
    from pyworkflow.config import get_config
    from pyworkflow.runtime import get_runtime

    config = get_config()
    runtime = get_runtime(config.default_runtime)

    try:
        await runtime.schedule_resume(run_id, storage)
    except Exception as e:
        logger.warning(
            f"Failed to schedule workflow resumption: {e}",
            run_id=run_id,
            hook_id=hook_id,
        )

    return ResumeResult(
        run_id=run_id,
        hook_id=hook_id,
        status="resumed",
    )
