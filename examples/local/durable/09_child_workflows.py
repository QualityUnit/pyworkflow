"""
Child Workflows - Basic Example

This example demonstrates how to spawn child workflows from a parent workflow.
- Parent workflow spawns child workflows using start_child_workflow()
- Children have their own run_id and event history
- wait_for_completion=True (default) waits for child to complete
- wait_for_completion=False returns a ChildWorkflowHandle immediately
- TERMINATE policy: when parent completes/fails/cancels, children are cancelled

Run: python examples/local/durable/09_child_workflows.py 2>/dev/null
"""

import asyncio

from pyworkflow import (
    ChildWorkflowHandle,
    configure,
    get_workflow_run,
    reset_config,
    start,
    start_child_workflow,
    step,
    workflow,
)
from pyworkflow.storage import InMemoryStorageBackend


# --- Steps ---
@step()
async def validate_order(order_id: str) -> dict:
    """Validate order details."""
    print(f"    Validating order {order_id}...")
    return {"order_id": order_id, "valid": True}


@step()
async def process_payment(order_id: str, amount: float) -> dict:
    """Process payment for order."""
    print(f"    Processing payment ${amount:.2f} for {order_id}...")
    return {"order_id": order_id, "amount": amount, "paid": True}


@step()
async def ship_order(order_id: str) -> dict:
    """Ship the order."""
    print(f"    Shipping order {order_id}...")
    return {"order_id": order_id, "shipped": True}


@step()
async def send_email(recipient: str, subject: str) -> dict:
    """Send an email notification."""
    print(f"    Sending email to {recipient}: {subject}")
    return {"recipient": recipient, "subject": subject, "sent": True}


# --- Child Workflows ---
@workflow(durable=True, tags=["local", "durable"])
async def payment_workflow(order_id: str, amount: float) -> dict:
    """Child workflow for payment processing."""
    print(f"  [PaymentWorkflow] Starting for order {order_id}")
    result = await process_payment(order_id, amount)
    print(f"  [PaymentWorkflow] Completed for order {order_id}")
    return result


@workflow(durable=True, tags=["local", "durable"])
async def shipping_workflow(order_id: str) -> dict:
    """Child workflow for shipping."""
    print(f"  [ShippingWorkflow] Starting for order {order_id}")
    result = await ship_order(order_id)
    print(f"  [ShippingWorkflow] Completed for order {order_id}")
    return result


@workflow(durable=True, tags=["local", "durable"])
async def notification_workflow(email: str, order_id: str) -> dict:
    """Child workflow for sending notifications."""
    print(f"  [NotificationWorkflow] Starting for {email}")
    result = await send_email(email, f"Order {order_id} update")
    print(f"  [NotificationWorkflow] Completed for {email}")
    return result


# --- Parent Workflow ---
@workflow(durable=True, tags=["local", "durable"])
async def order_fulfillment_workflow(
    order_id: str,
    amount: float,
    customer_email: str,
) -> dict:
    """
    Parent workflow that orchestrates order fulfillment using child workflows.

    This demonstrates:
    1. wait_for_completion=True - Wait for child to complete (default)
    2. wait_for_completion=False - Fire-and-forget with handle
    """
    print(f"[OrderFulfillment] Starting for order {order_id}")

    # Step 1: Validate order (regular step)
    validation = await validate_order(order_id)
    if not validation["valid"]:
        return {"order_id": order_id, "status": "invalid"}

    # Step 2: Process payment via child workflow (wait for completion)
    print("[OrderFulfillment] Starting payment child workflow...")
    payment_result = await start_child_workflow(
        payment_workflow,
        order_id,
        amount,
        wait_for_completion=True,  # Default: wait for child to complete
    )
    print(f"[OrderFulfillment] Payment completed: {payment_result}")

    # Step 3: Ship order via child workflow (wait for completion)
    print("[OrderFulfillment] Starting shipping child workflow...")
    shipping_result = await start_child_workflow(
        shipping_workflow,
        order_id,
        wait_for_completion=True,
    )
    print(f"[OrderFulfillment] Shipping completed: {shipping_result}")

    # Step 4: Send notification via fire-and-forget child workflow
    # This returns immediately with a handle, parent continues
    print("[OrderFulfillment] Starting notification child workflow (fire-and-forget)...")
    notification_handle: ChildWorkflowHandle = await start_child_workflow(
        notification_workflow,
        customer_email,
        order_id,
        wait_for_completion=False,  # Fire-and-forget
    )
    print(f"[OrderFulfillment] Notification child started: {notification_handle.child_run_id}")

    # We can optionally check status or wait for the handle later
    # For now, we'll just let it run in the background

    result = {
        "order_id": order_id,
        "status": "fulfilled",
        "payment": payment_result,
        "shipping": shipping_result,
        "notification_run_id": notification_handle.child_run_id,
    }

    print(f"[OrderFulfillment] Completed for order {order_id}")
    return result


async def main():
    # Configure with InMemoryStorageBackend
    reset_config()
    storage = InMemoryStorageBackend()
    configure(storage=storage, default_durable=True)

    print("=== Child Workflows - Basic Example ===\n")
    print("Running order fulfillment workflow with child workflows...\n")

    # Start parent workflow
    run_id = await start(
        order_fulfillment_workflow,
        "order-456",
        149.99,
        "customer@example.com",
    )

    # Give fire-and-forget child time to complete
    await asyncio.sleep(0.5)

    print("\n=== Workflow Results ===")

    # Check parent workflow
    parent_run = await get_workflow_run(run_id)
    print(f"\nParent Workflow: {run_id}")
    print(f"  Status: {parent_run.status.value}")
    print(f"  Result: {parent_run.result}")

    # List child workflows
    children = await storage.get_children(run_id)
    print(f"\nChild Workflows ({len(children)} total):")
    for child in children:
        print(f"  - {child.run_id}")
        print(f"    Workflow: {child.workflow_name}")
        print(f"    Status: {child.status.value}")
        print(f"    Nesting Depth: {child.nesting_depth}")

    print("\n=== Key Takeaways ===")
    print("1. start_child_workflow() spawns a child with its own run_id")
    print("2. wait_for_completion=True (default) waits for child result")
    print("3. wait_for_completion=False returns a ChildWorkflowHandle")
    print("4. Child workflows have their own event history")
    print("5. TERMINATE policy: children cancelled when parent completes")


if __name__ == "__main__":
    asyncio.run(main())
