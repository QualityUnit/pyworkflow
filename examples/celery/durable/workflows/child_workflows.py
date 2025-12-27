"""
Celery Durable Workflow - Child Workflows Basic Example

This example demonstrates how to spawn child workflows from a parent workflow.
- Parent workflow spawns child workflows using start_child_workflow()
- Children have their own run_id and event history
- wait_for_completion=True (default) waits for child to complete
- wait_for_completion=False returns a ChildWorkflowHandle immediately
- TERMINATE policy: when parent completes/fails/cancels, children are cancelled

Prerequisites:
    1. Start Redis: docker run -d -p 6379:6379 redis:7-alpine
    2. Start worker: pyworkflow --module examples.celery.durable.09_child_workflows worker run

Run with CLI:
    pyworkflow --module examples.celery.durable.09_child_workflows workflows run order_fulfillment_workflow \
        --arg order_id=order-456 --arg amount=149.99 --arg customer_email=customer@example.com

Check status:
    pyworkflow runs list
    pyworkflow runs status <run_id>
    pyworkflow runs children <run_id>
"""

from pyworkflow import (
    ChildWorkflowHandle,
    start_child_workflow,
    step,
    workflow,
)


# --- Steps ---
@step(name="child_demo_validate_order")
async def validate_order(order_id: str) -> dict:
    """Validate order details."""
    print(f"    Validating order {order_id}...")
    return {"order_id": order_id, "valid": True}


@step(name="child_demo_process_payment")
async def process_payment(order_id: str, amount: float) -> dict:
    """Process payment for order."""
    print(f"    Processing payment ${amount:.2f} for {order_id}...")
    return {"order_id": order_id, "amount": amount, "paid": True}


@step(name="child_demo_ship_order")
async def ship_order(order_id: str) -> dict:
    """Ship the order."""
    print(f"    Shipping order {order_id}...")
    return {"order_id": order_id, "shipped": True}


@step(name="child_demo_send_email")
async def send_email(recipient: str, subject: str) -> dict:
    """Send an email notification."""
    print(f"    Sending email to {recipient}: {subject}")
    return {"recipient": recipient, "subject": subject, "sent": True}


# --- Child Workflows ---
@workflow(name="child_demo_payment_workflow", tags=["celery", "durable"])
async def payment_workflow(order_id: str, amount: float) -> dict:
    """Child workflow for payment processing."""
    print(f"  [PaymentWorkflow] Starting for order {order_id}")
    result = await process_payment(order_id, amount)
    print(f"  [PaymentWorkflow] Completed for order {order_id}")
    return result


@workflow(name="child_demo_shipping_workflow", tags=["celery", "durable"])
async def shipping_workflow(order_id: str) -> dict:
    """Child workflow for shipping."""
    print(f"  [ShippingWorkflow] Starting for order {order_id}")
    result = await ship_order(order_id)
    print(f"  [ShippingWorkflow] Completed for order {order_id}")
    return result


@workflow(name="child_demo_notification_workflow", tags=["celery", "durable"])
async def notification_workflow(email: str, order_id: str) -> dict:
    """Child workflow for sending notifications."""
    print(f"  [NotificationWorkflow] Starting for {email}")
    result = await send_email(email, f"Order {order_id} update")
    print(f"  [NotificationWorkflow] Completed for {email}")
    return result


# --- Parent Workflow ---
@workflow(tags=["celery", "durable"])
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

    result = {
        "order_id": order_id,
        "status": "fulfilled",
        "payment": payment_result,
        "shipping": shipping_result,
        "notification_run_id": notification_handle.child_run_id,
    }

    print(f"[OrderFulfillment] Completed for order {order_id}")
    return result


async def main() -> None:
    """Run the order fulfillment workflow example."""
    import argparse
    import asyncio

    import pyworkflow
    from pyworkflow import get_workflow_run

    parser = argparse.ArgumentParser(description="Order Fulfillment Workflow with Child Workflows")
    parser.add_argument("--order-id", default="order-456", help="Order ID to process")
    parser.add_argument("--amount", type=float, default=149.99, help="Order amount")
    parser.add_argument("--email", default="customer@example.com", help="Customer email")
    args = parser.parse_args()

    print("=== Child Workflows - Basic Example ===\n")
    print("Running order fulfillment workflow with child workflows...\n")

    # Start parent workflow
    run_id = await pyworkflow.start(
        order_fulfillment_workflow,
        args.order_id,
        args.amount,
        args.email,
    )

    print(f"\nWorkflow started with run_id: {run_id}")
    print("\nCheck status:")
    print(f"  pyworkflow runs status {run_id}")
    print(f"  pyworkflow runs children {run_id}")

    # Poll for completion
    print("\nWaiting for workflow to complete...")
    for _ in range(30):
        await asyncio.sleep(1)
        run = await get_workflow_run(run_id)
        if run.status.value in ("completed", "failed", "cancelled"):
            print(f"\nWorkflow {run.status.value}!")
            if run.result:
                print(f"Result: {run.result}")
            if run.error:
                print(f"Error: {run.error}")
            break
    else:
        print("\nTimeout waiting for workflow completion")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
