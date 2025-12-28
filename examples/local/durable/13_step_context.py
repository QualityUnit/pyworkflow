"""
Durable Workflow - Step Context Example

This example demonstrates how to use StepContext to share typed data
between workflows and steps during distributed execution.

Key concepts:
- Define a custom context class extending StepContext
- Set context in workflow code with set_step_context()
- Read context in steps with get_step_context()
- Context is read-only in steps (prevents race conditions)
- Context survives workflow suspension and replay

Run: python examples/local/durable/13_step_context.py 2>/dev/null
"""

import asyncio

from pyworkflow import (
    StepContext,
    configure,
    get_step_context,
    get_workflow_events,
    get_workflow_run,
    has_step_context,
    reset_config,
    set_step_context,
    sleep,
    start,
    step,
    workflow,
)
from pyworkflow.storage import InMemoryStorageBackend


# --- Define Custom Context ---
class OrderContext(StepContext):
    """
    Custom context for order processing workflows.

    StepContext is immutable (frozen) - use with_updates() to create
    new instances with modified values.
    """

    workspace_id: str = ""
    user_id: str = ""
    order_id: str = ""
    priority: str = "normal"
    correlation_id: str = ""


# --- Steps ---
@step()
async def validate_order(order_id: str) -> dict:
    """
    Validate the order - demonstrates reading context in a step.

    Context is read-only in steps to prevent race conditions when
    multiple steps execute in parallel.
    """
    # Read context (read-only)
    ctx = get_step_context()
    print(f"  [validate] Workspace: {ctx.workspace_id}")
    print(f"  [validate] User: {ctx.user_id}")
    print(f"  [validate] Priority: {ctx.priority}")
    print(f"  [validate] Correlation ID: {ctx.correlation_id}")

    # Simulate validation
    print(f"  [validate] Validating order {order_id}...")
    return {"order_id": order_id, "valid": True}


@step()
async def process_payment(order: dict, amount: float) -> dict:
    """Process payment - shows context is available in all steps."""
    ctx = get_step_context()
    print(f"  [payment] Processing for user {ctx.user_id} in workspace {ctx.workspace_id}")
    print(f"  [payment] Charging ${amount:.2f}...")
    return {**order, "paid": True, "amount": amount}


@step()
async def send_notification(order: dict) -> dict:
    """Send notification - shows optional context access."""
    # Check if context is available before accessing
    if has_step_context():
        ctx = get_step_context()
        print(f"  [notify] Sending to user {ctx.user_id}")
        print(f"  [notify] Correlation ID for tracing: {ctx.correlation_id}")
    else:
        print("  [notify] No context available")

    print(f"  [notify] Order {order['order_id']} completed!")
    return {**order, "notified": True}


# --- Workflow ---
@workflow(durable=True, tags=["local", "durable", "step-context"], context_class=OrderContext)
async def order_workflow_with_context(
    order_id: str, amount: float, user_id: str, workspace_id: str
) -> dict:
    """
    Order processing workflow with step context.

    The context_class parameter tells the workflow to use OrderContext
    for step context. This enables type-safe context access in steps.
    """
    # Initialize context at the start of the workflow
    ctx = OrderContext(
        workspace_id=workspace_id,
        user_id=user_id,
        order_id=order_id,
        priority="high" if amount > 100 else "normal",
        correlation_id=f"corr-{order_id}-{user_id}",
    )
    await set_step_context(ctx)
    print(f"  Context initialized: {ctx.to_dict()}")

    # Steps can now read the context
    order = await validate_order(order_id)
    order = await process_payment(order, amount)

    # Context can be updated in workflow code (not in steps)
    ctx = get_step_context()
    ctx = ctx.with_updates(priority="completed")
    await set_step_context(ctx)
    print(f"  Context updated: priority -> {ctx.priority}")

    order = await send_notification(order)
    return order


@workflow(durable=True, tags=["local", "step-context"], context_class=OrderContext)
async def order_workflow_with_sleep(order_id: str, user_id: str, workspace_id: str) -> dict:
    """
    Demonstrates context persistence across workflow suspension.

    After sleep, the workflow resumes and context is automatically
    restored from the event log.
    """
    # Initialize context
    ctx = OrderContext(
        workspace_id=workspace_id,
        user_id=user_id,
        order_id=order_id,
        correlation_id=f"sleep-test-{order_id}",
    )
    await set_step_context(ctx)
    print(f"  Initial context: {ctx.to_dict()}")

    # First step
    order = await validate_order(order_id)

    # Simulate waiting (context is persisted)
    print("  Sleeping for 1 second...")
    await sleep("1s")

    # After resume, context is automatically restored
    restored_ctx = get_step_context()
    print(f"  Context after sleep: {restored_ctx.to_dict()}")
    assert restored_ctx.order_id == order_id, "Context should be restored after sleep"

    order = await send_notification(order)
    return order


async def main():
    # Configure with InMemoryStorageBackend
    reset_config()
    storage = InMemoryStorageBackend()
    configure(storage=storage, default_durable=True)

    print("=== Durable Workflow - Step Context Example ===\n")

    # Example 1: Basic context usage
    print("--- Example 1: Basic Step Context ---")
    run_id = await start(
        order_workflow_with_context,
        order_id="order-456",
        amount=149.99,
        user_id="user-789",
        workspace_id="ws-123",
    )
    print(f"\nWorkflow completed: {run_id}")

    run = await get_workflow_run(run_id)
    print(f"Status: {run.status.value}")
    print(f"Result: {run.result}")

    # Check stored context
    print(f"Stored context: {run.context}")

    # Inspect events for CONTEXT_UPDATED
    events = await get_workflow_events(run_id)
    context_events = [e for e in events if e.type.value == "context.updated"]
    print(f"Context update events: {len(context_events)}")

    # Example 2: Context with sleep (persistence test)
    print("\n--- Example 2: Context Persistence Across Sleep ---")
    run_id_2 = await start(
        order_workflow_with_sleep,
        order_id="order-sleep-test",
        user_id="user-sleep",
        workspace_id="ws-sleep",
    )
    print(f"\nWorkflow completed: {run_id_2}")

    run_2 = await get_workflow_run(run_id_2)
    print(f"Status: {run_2.status.value}")

    print("\n=== Key Takeaways ===")
    print("✓ StepContext provides typed, immutable context")
    print("✓ set_step_context() persists context to storage")
    print("✓ get_step_context() reads context (read-only in steps)")
    print("✓ Context survives sleep/suspension via event replay")
    print("✓ Use with_updates() to create new context instances")
    print("✓ Context is ideal for cross-cutting concerns (user_id, workspace_id, etc.)")


if __name__ == "__main__":
    asyncio.run(main())
