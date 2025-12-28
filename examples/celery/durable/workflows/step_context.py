"""
Celery Durable Workflow - Step Context Example

This example demonstrates how to use StepContext to share typed data
between workflows and steps during distributed Celery execution.

Key concepts:
- Define a custom context class extending StepContext
- Set context in workflow code with set_step_context()
- Read context in steps with get_step_context() (read-only)
- Context is automatically serialized and passed to Celery workers
- Context survives workflow suspension and replay

Prerequisites:
    1. Start Redis: docker run -d -p 6379:6379 redis:7-alpine
    2. Start worker: pyworkflow --module examples.celery.durable.workflows.step_context worker run

Run with CLI:
    pyworkflow --module examples.celery.durable.workflows.step_context workflows run \
        order_workflow_with_context \
        --arg order_id=order-123 --arg amount=149.99 \
        --arg user_id=user-456 --arg workspace_id=ws-789

Check status:
    pyworkflow runs list
    pyworkflow runs status <run_id>
    pyworkflow runs logs <run_id>
"""

from pyworkflow import (
    StepContext,
    get_step_context,
    has_step_context,
    set_step_context,
    step,
    workflow,
)


# --- Define Custom Context ---
class OrderContext(StepContext):
    """
    Custom context for order processing workflows.

    This context is automatically:
    - Serialized and passed to Celery workers
    - Persisted to storage for durability
    - Replayed from events on workflow resumption

    StepContext is immutable - use with_updates() to modify.
    """

    workspace_id: str = ""
    user_id: str = ""
    order_id: str = ""
    priority: str = "normal"
    correlation_id: str = ""
    feature_flags: dict[str, bool] = {}


class CustomerContext(StepContext):
    """Example context with nested types."""

    customer_id: str = ""
    email: str = ""
    tier: str = "standard"  # standard, premium, enterprise
    metadata: dict[str, str] = {}


# --- Steps with Context Access ---
@step(name="ctx_validate_order")
async def validate_order(order_id: str) -> dict:
    """
    Validate the order - reads context from Celery worker.

    The context is automatically loaded on the worker before
    step execution. It's read-only to prevent race conditions.
    """
    ctx = get_step_context()
    print("[Step:validate] Running on Celery worker")
    print(f"[Step:validate] Workspace: {ctx.workspace_id}")
    print(f"[Step:validate] User: {ctx.user_id}")
    print(f"[Step:validate] Priority: {ctx.priority}")
    print(f"[Step:validate] Correlation ID: {ctx.correlation_id}")

    # Simulate validation logic
    print(f"[Step:validate] Validating order {order_id}...")
    return {"order_id": order_id, "valid": True}


@step(name="ctx_process_payment")
async def process_payment(order: dict, amount: float) -> dict:
    """Process payment - demonstrates context in payment step."""
    ctx = get_step_context()
    print(f"[Step:payment] Processing for user {ctx.user_id}")
    print(f"[Step:payment] Workspace: {ctx.workspace_id}")
    print(f"[Step:payment] Amount: ${amount:.2f}")

    # Check feature flags from context
    if ctx.feature_flags.get("fast_processing"):
        print("[Step:payment] Fast processing enabled!")

    return {**order, "paid": True, "amount": amount}


@step(name="ctx_send_notification")
async def send_notification(order: dict) -> dict:
    """Send notification - shows optional context access pattern."""
    if has_step_context():
        ctx = get_step_context()
        print(f"[Step:notify] Sending to user {ctx.user_id}")
        print(f"[Step:notify] Correlation ID: {ctx.correlation_id}")
    else:
        print("[Step:notify] No context available (fallback mode)")

    print(f"[Step:notify] Order {order['order_id']} completed!")
    return {**order, "notified": True}


@step(name="ctx_premium_processing")
async def premium_processing(order: dict) -> dict:
    """Demonstrate context-based conditional logic."""
    ctx = get_step_context()

    if ctx.priority == "high":
        print("[Step:premium] High priority order - expedited processing")
        order["expedited"] = True
    else:
        print("[Step:premium] Standard processing")
        order["expedited"] = False

    return order


# --- Workflows ---
@workflow(tags=["celery", "durable", "step-context"], context_class=OrderContext)
async def order_workflow_with_context(
    order_id: str, amount: float, user_id: str, workspace_id: str
) -> dict:
    """
    Order processing workflow with step context.

    The context_class parameter enables typed context access in steps.
    Context is serialized and passed to each Celery worker.
    """
    # Initialize context at workflow start
    ctx = OrderContext(
        workspace_id=workspace_id,
        user_id=user_id,
        order_id=order_id,
        priority="high" if amount > 100 else "normal",
        correlation_id=f"corr-{order_id}-{user_id}",
        feature_flags={"fast_processing": amount > 200},
    )
    await set_step_context(ctx)
    print(f"[Workflow] Context initialized: workspace={workspace_id}, user={user_id}")

    # Each step receives the context on its Celery worker
    order = await validate_order(order_id)
    order = await process_payment(order, amount)
    order = await premium_processing(order)

    # Update context in workflow (not in steps!)
    ctx = get_step_context()
    ctx = ctx.with_updates(priority="completed")
    await set_step_context(ctx)
    print(f"[Workflow] Context updated: priority={ctx.priority}")

    order = await send_notification(order)
    return order


@workflow(tags=["celery", "step-context"], context_class=OrderContext)
async def parallel_steps_with_context(order_id: str, user_id: str, workspace_id: str) -> dict:
    """
    Demonstrates context with parallel step execution.

    All parallel steps receive the same context snapshot.
    Since context is read-only in steps, there are no race conditions.
    """
    import asyncio

    # Initialize context
    ctx = OrderContext(
        workspace_id=workspace_id,
        user_id=user_id,
        order_id=order_id,
        correlation_id=f"parallel-{order_id}",
    )
    await set_step_context(ctx)
    print("[Workflow] Running parallel steps with context")

    # All steps execute in parallel - each gets the same context
    results = await asyncio.gather(
        validate_order(order_id),
        fetch_user_preferences(user_id),
        check_inventory(order_id),
    )

    order, preferences, inventory = results
    return {
        "order": order,
        "preferences": preferences,
        "inventory": inventory,
    }


@step(name="ctx_fetch_preferences")
async def fetch_user_preferences(user_id: str) -> dict:
    """Fetch user preferences - parallel step."""
    ctx = get_step_context()
    print(f"[Step:preferences] Fetching for user {user_id}")
    print(f"[Step:preferences] Workspace: {ctx.workspace_id}")
    return {"user_id": user_id, "theme": "dark", "notifications": True}


@step(name="ctx_check_inventory")
async def check_inventory(order_id: str) -> dict:
    """Check inventory - parallel step."""
    ctx = get_step_context()
    print(f"[Step:inventory] Checking for order {order_id}")
    print(f"[Step:inventory] Correlation: {ctx.correlation_id}")
    return {"order_id": order_id, "in_stock": True, "quantity": 5}


@workflow(tags=["celery", "step-context"], context_class=CustomerContext)
async def customer_workflow(customer_id: str, email: str, tier: str = "standard") -> dict:
    """
    Example workflow with CustomerContext.

    Shows how different workflows can use different context classes.
    """
    ctx = CustomerContext(
        customer_id=customer_id,
        email=email,
        tier=tier,
        metadata={"source": "api", "version": "2.0"},
    )
    await set_step_context(ctx)
    print(f"[Workflow] Customer context: {ctx.to_dict()}")

    result = await process_customer_request(customer_id)
    return result


@step(name="ctx_process_customer")
async def process_customer_request(customer_id: str) -> dict:
    """Process customer request with tier-based logic."""
    ctx = get_step_context()
    print(f"[Step:customer] Processing customer {customer_id}")
    print(f"[Step:customer] Tier: {ctx.tier}")
    print(f"[Step:customer] Email: {ctx.email}")

    # Tier-based processing
    if ctx.tier == "enterprise":
        print("[Step:customer] Enterprise tier - priority support")
        return {"customer_id": customer_id, "support_level": "priority"}
    elif ctx.tier == "premium":
        print("[Step:customer] Premium tier - enhanced support")
        return {"customer_id": customer_id, "support_level": "enhanced"}
    else:
        print("[Step:customer] Standard tier - regular support")
        return {"customer_id": customer_id, "support_level": "standard"}


# --- Main for direct execution ---
async def main() -> None:
    """Run the step context workflow example."""
    import argparse

    import pyworkflow

    parser = argparse.ArgumentParser(description="Step Context Workflow Example")
    parser.add_argument("--order-id", default="order-ctx-123", help="Order ID")
    parser.add_argument("--amount", type=float, default=149.99, help="Order amount")
    parser.add_argument("--user-id", default="user-456", help="User ID")
    parser.add_argument("--workspace-id", default="ws-789", help="Workspace ID")
    parser.add_argument("--parallel", action="store_true", help="Run parallel steps example")
    args = parser.parse_args()

    if args.parallel:
        print("Starting parallel workflow with context...")
        run_id = await pyworkflow.start(
            parallel_steps_with_context,
            order_id=args.order_id,
            user_id=args.user_id,
            workspace_id=args.workspace_id,
        )
    else:
        print("Starting order workflow with context...")
        run_id = await pyworkflow.start(
            order_workflow_with_context,
            order_id=args.order_id,
            amount=args.amount,
            user_id=args.user_id,
            workspace_id=args.workspace_id,
        )

    print(f"Workflow started with run_id: {run_id}")
    print(f"\nCheck status: pyworkflow runs status {run_id}")
    print(f"View logs: pyworkflow runs logs {run_id}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
