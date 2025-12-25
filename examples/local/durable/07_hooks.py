"""
Durable Workflow - Hooks Example

This example demonstrates the hooks feature for waiting on external events:
- Using hook() to suspend workflow and wait for external input
- Using define_hook() for typed hooks with Pydantic validation
- Using resume_hook() to deliver payloads from external systems
- Composite tokens (run_id:hook_id) for self-describing tokens
- on_created callback for receiving the generated token

Run: python examples/local/durable/07_hooks.py 2>/dev/null
"""

import asyncio

from pydantic import BaseModel

from pyworkflow import (
    configure,
    define_hook,
    get_workflow_events,
    get_workflow_run,
    hook,
    reset_config,
    resume,
    resume_hook,
    start,
    step,
    workflow,
)
from pyworkflow.storage import InMemoryStorageBackend

# Global storage reference for resumption
_storage = None

# Store tokens received from on_created callback
_captured_tokens = {}


# --- Pydantic models for typed hooks ---
class ApprovalPayload(BaseModel):
    """Typed payload for approval hook."""

    approved: bool
    reviewer: str
    comments: str | None = None


# Create typed hook
approval_hook = define_hook("approval", ApprovalPayload)


# --- Steps ---
@step()
async def prepare_order(order_id: str) -> dict:
    """Prepare the order for review."""
    print(f"  Preparing order {order_id}...")
    return {"order_id": order_id, "status": "pending_approval"}


@step()
async def fulfill_order(order: dict) -> dict:
    """Fulfill the approved order."""
    print(f"  Fulfilling order {order['order_id']}...")
    return {**order, "status": "fulfilled"}


@step()
async def cancel_order(order: dict, reason: str) -> dict:
    """Cancel the rejected order."""
    print(f"  Cancelling order {order['order_id']}: {reason}")
    return {**order, "status": "cancelled", "reason": reason}


# --- Workflow with simple hook ---
@workflow(durable=True, name="simple_hook_workflow", tags=["local", "durable"])
async def simple_hook_workflow(order_id: str) -> dict:
    """
    Workflow using simple hook() with untyped payload.

    Demonstrates basic hook usage with auto-generated composite token.
    Token format: run_id:hook_id (e.g., "run_abc123:hook_simple_approval_1")
    """
    order = await prepare_order(order_id)

    async def capture_token(token: str):
        """Capture the generated token for later use."""
        _captured_tokens[order_id] = token
        print(f"  Hook created with token: {token}")

    # Wait for external approval using simple hook
    # Token is auto-generated in composite format: run_id:hook_id
    approval = await hook(
        "simple_approval",
        timeout="24h",  # Expire after 24 hours
        on_created=capture_token,
    )

    if approval.get("approved"):
        return await fulfill_order(order)
    else:
        return await cancel_order(order, approval.get("reason", "Rejected"))


# --- Workflow with typed hook ---
@workflow(durable=True, name="typed_hook_workflow", tags=["local", "durable"])
async def typed_hook_workflow(order_id: str) -> dict:
    """
    Workflow using define_hook() for type-safe payloads.

    Demonstrates typed hooks with Pydantic validation.
    """
    order = await prepare_order(order_id)

    async def capture_typed_token(token: str):
        """Capture the generated token for later use."""
        _captured_tokens[f"typed:{order_id}"] = token
        print(f"  Typed hook created with token: {token}")

    # Wait for typed approval - payload is validated against ApprovalPayload
    approval: ApprovalPayload = await approval_hook(
        on_created=capture_typed_token,
    )

    print(f"  Received: approved={approval.approved}, reviewer={approval.reviewer}")

    if approval.approved:
        return await fulfill_order(order)
    else:
        return await cancel_order(order, approval.comments or "No reason given")


# --- Workflow with on_created callback ---
@workflow(durable=True, name="callback_hook_workflow", tags=["local", "durable"])
async def callback_hook_workflow(order_id: str) -> dict:
    """
    Workflow demonstrating on_created callback.

    The callback is invoked when the hook is created,
    allowing you to notify external systems with the token.
    Token format is composite: run_id:hook_id
    """
    order = await prepare_order(order_id)

    async def on_hook_created(token: str):
        # In real scenarios, you would notify external systems here
        # e.g., send email, update database, register webhook URL
        _captured_tokens[f"callback:{order_id}"] = token
        print(f"  Hook created! Token: {token}")
        print(f"  External system can POST to: /webhook/{token}")

    # Wait for approval with on_created callback
    approval = await hook(
        "callback_approval",
        on_created=on_hook_created,
    )

    if approval.get("approved"):
        return await fulfill_order(order)
    else:
        return await cancel_order(order, approval.get("reason", "Rejected"))


async def demo_simple_hook():
    """Demo simple hook workflow."""
    print("\n" + "=" * 50)
    print("Demo 1: Simple Hook with Composite Token")
    print("=" * 50)

    run_id = await start(simple_hook_workflow, "ORDER-001")
    print(f"\nWorkflow started: {run_id}")

    # Check status - should be suspended
    run = await get_workflow_run(run_id)
    print(f"Status: {run.status.value}")

    # Get the token that was captured via on_created callback
    token = _captured_tokens.get("ORDER-001")
    print(f"\nCaptured token: {token}")

    # Simulate external system calling resume_hook with the composite token
    print("\n[External System] Sending approval...")
    result = await resume_hook(
        token=token,
        payload={"approved": True, "approver": "manager@example.com"},
        storage=_storage,
    )
    print(f"Resume result: {result.status}")

    # In local mode without Celery, manually resume the workflow
    await resume(run_id, storage=_storage)

    # Check final status
    run = await get_workflow_run(run_id)
    print(f"\nFinal status: {run.status.value}")
    print(f"Result: {run.result}")


async def demo_typed_hook():
    """Demo typed hook workflow."""
    print("\n" + "=" * 50)
    print("Demo 2: Typed Hook with Pydantic")
    print("=" * 50)

    run_id = await start(typed_hook_workflow, "ORDER-002")
    print(f"\nWorkflow started: {run_id}")

    # Check status - should be suspended
    run = await get_workflow_run(run_id)
    print(f"Status: {run.status.value}")

    # Get the token that was captured via on_created callback
    token = _captured_tokens.get("typed:ORDER-002")
    print(f"\nCaptured token: {token}")

    # Simulate external system calling resume_hook with typed payload
    print("\n[External System] Sending typed approval...")
    result = await resume_hook(
        token=token,
        payload={
            "approved": True,
            "reviewer": "jane.doe@example.com",
            "comments": "Looks good!",
        },
        storage=_storage,
    )
    print(f"Resume result: {result.status}")

    # In local mode without Celery, manually resume the workflow
    await resume(run_id, storage=_storage)

    # Check final status
    run = await get_workflow_run(run_id)
    print(f"\nFinal status: {run.status.value}")
    print(f"Result: {run.result}")


async def demo_rejection():
    """Demo hook rejection flow."""
    print("\n" + "=" * 50)
    print("Demo 3: Rejection Flow")
    print("=" * 50)

    run_id = await start(simple_hook_workflow, "ORDER-003")
    print(f"\nWorkflow started: {run_id}")

    # Get the token that was captured via on_created callback
    token = _captured_tokens.get("ORDER-003")

    # Simulate rejection
    print("\n[External System] Sending rejection...")
    result = await resume_hook(
        token=token,
        payload={"approved": False, "reason": "Insufficient inventory"},
        storage=_storage,
    )
    print(f"Resume result: {result.status}")

    # In local mode without Celery, manually resume the workflow
    await resume(run_id, storage=_storage)

    # Check final status
    run = await get_workflow_run(run_id)
    print(f"\nFinal status: {run.status.value}")
    print(f"Result: {run.result}")


async def demo_event_log():
    """Show the event log for a hook-based workflow."""
    print("\n" + "=" * 50)
    print("Demo 4: Event Log Inspection")
    print("=" * 50)

    run_id = await start(simple_hook_workflow, "ORDER-004")

    # Get the token that was captured via on_created callback
    token = _captured_tokens.get("ORDER-004")

    # Resume hook using captured token
    await resume_hook(
        token=token,
        payload={"approved": True},
        storage=_storage,
    )

    # Resume workflow in local mode
    await resume(run_id, storage=_storage)

    # Inspect event log
    events = await get_workflow_events(run_id)
    print(f"\nEvent Log ({len(events)} events):")
    for event in events:
        print(f"  {event.sequence}: {event.type.value}")
        if "hook" in event.type.value:
            if "hook_id" in event.data:
                print(f"     hook_id: {event.data.get('hook_id', 'N/A')}")
            if "token" in event.data:
                print(f"     token: {event.data.get('token', 'N/A')[:40]}...")


async def main():
    global _storage

    # Configure with InMemoryStorageBackend
    reset_config()
    _storage = InMemoryStorageBackend()
    configure(storage=_storage, default_durable=True)

    print("=== Durable Workflow - Hooks Example ===")
    print("""
This example demonstrates hooks for external event integration:
- hook(): Wait for external events
- define_hook(): Create typed hooks with validation
- resume_hook(): Deliver payloads from external systems
""")

    await demo_simple_hook()
    await demo_typed_hook()
    await demo_rejection()
    await demo_event_log()

    print("\n" + "=" * 50)
    print("Key Takeaways")
    print("=" * 50)
    print("- hook() suspends workflow until resume_hook() is called")
    print("- Tokens are auto-generated in composite format: run_id:hook_id")
    print("- Use on_created callback to capture the token for external systems")
    print("- define_hook() provides type-safe payloads with Pydantic")
    print("- Composite tokens are self-describing (contain run_id)")
    print("- Events record hook creation and reception")


if __name__ == "__main__":
    asyncio.run(main())
