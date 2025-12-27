"""
Celery Durable Workflow - Cancellation

This example demonstrates graceful workflow cancellation with Celery:
- Cancel running or suspended workflows via CLI
- Handle CancellationError for cleanup
- Use shield() to protect critical operations

================================================================================
PREREQUISITES
================================================================================

1. Start Redis:
   docker run -d -p 6379:6379 redis:7-alpine

2. Start the Celery worker (in a separate terminal):
   pyworkflow --module examples.celery.durable.08_cancellation worker run

================================================================================
HOW TO RUN AND CANCEL
================================================================================

STEP 1: Start the workflow (it will sleep for 60 seconds):

   pyworkflow --module examples.celery.durable.08_cancellation workflows run \
       cancellable_order_workflow --arg order_id=order-123

   Output: Workflow started: run_abc123def456...

STEP 2: Check the status (should be "suspended" during sleep):

   pyworkflow runs status <run_id>
   pyworkflow runs list --status suspended

STEP 3: Cancel the workflow while it's sleeping:

   pyworkflow runs cancel <run_id> --reason "Customer cancelled"

   Or wait for cancellation to complete:

   pyworkflow runs cancel <run_id> --wait --reason "Customer cancelled"

STEP 4: Check the worker logs - you should see:
   - [Workflow] Cancellation detected!
   - [Cleanup] Releasing inventory...
   - [Cleanup] Refunding payment...

STEP 5: Verify the final status:

   pyworkflow runs status <run_id>
   pyworkflow runs logs <run_id> --filter cancel

================================================================================
KEY POINTS
================================================================================

- Cancellation is CHECKPOINT-BASED: happens before steps, during sleep/hook
- If a step is already running, cancellation waits until it completes
- Use shield() to protect cleanup code from cancellation
- Catch CancellationError to perform compensation logic

================================================================================
"""

import asyncio

from loguru import logger

from pyworkflow import (
    CancellationError,
    get_context,
    shield,
    sleep,
    step,
    workflow,
)


# --- Steps (prefixed to avoid naming conflicts with other examples) ---
@step()
async def cancel_demo_reserve_inventory(order_id: str) -> dict:
    """Reserve inventory for order."""
    logger.info(f"[Step] Reserving inventory for order {order_id}...")
    await asyncio.sleep(1)  # Simulate API call
    logger.info(f"[Step] Inventory reserved for {order_id}")
    return {"order_id": order_id, "inventory_reserved": True}


@step()
async def cancel_demo_charge_payment(order: dict) -> dict:
    """Charge payment for order."""
    logger.info(f"[Step] Charging payment for order {order['order_id']}...")
    await asyncio.sleep(1)  # Simulate payment processing
    logger.info(f"[Step] Payment charged for {order['order_id']}")
    return {**order, "payment_charged": True}


@step()
async def cancel_demo_create_shipment(order: dict) -> dict:
    """Create shipment for order."""
    logger.info(f"[Step] Creating shipment for order {order['order_id']}...")
    await asyncio.sleep(1)  # Simulate shipment creation
    logger.info(f"[Step] Shipment created for {order['order_id']}")
    return {**order, "shipment_created": True}


@step()
async def cancel_demo_release_inventory(order_id: str) -> None:
    """Release previously reserved inventory (compensation)."""
    logger.warning(f"[Cleanup] Releasing inventory for order {order_id}...")
    await asyncio.sleep(0.5)
    logger.warning(f"[Cleanup] Inventory released for {order_id}")


@step()
async def cancel_demo_refund_payment(order_id: str) -> None:
    """Refund charged payment (compensation)."""
    logger.warning(f"[Cleanup] Refunding payment for order {order_id}...")
    await asyncio.sleep(0.5)
    logger.warning(f"[Cleanup] Payment refunded for {order_id}")


# --- Workflow with Cancellation Handling ---
@workflow(tags=["celery", "durable"])
async def cancellable_order_workflow(order_id: str) -> dict:
    """
    Order processing workflow with cancellation handling.

    Flow:
    1. Reserve inventory
    2. Sleep 60s (waiting for approval) <-- CANCEL HERE
    3. Charge payment
    4. Sleep 60s (waiting for warehouse) <-- OR CANCEL HERE
    5. Create shipment

    If cancelled at any point:
    - CancellationError is raised at the next checkpoint
    - Cleanup logic releases inventory and refunds payment
    - shield() ensures cleanup completes

    To cancel this workflow:
        pyworkflow runs cancel <run_id> --reason "Customer cancelled"
    """
    try:
        logger.info(f"[Workflow] Starting order processing for {order_id}")

        # Step 1: Reserve inventory
        order = await cancel_demo_reserve_inventory(order_id)

        # Sleep - workflow suspends here
        # This is a good time to cancel!
        logger.info("[Workflow] Waiting 60s for customer approval...")
        logger.info("[Workflow] >>> To cancel: pyworkflow runs cancel <run_id> --reason 'test'")
        await sleep("60s")

        # Step 2: Charge payment
        # Cancellation check happens here (before step)
        order = await cancel_demo_charge_payment(order)

        # Another sleep - another opportunity to cancel
        logger.info("[Workflow] Waiting 60s for warehouse processing...")
        logger.info("[Workflow] >>> To cancel: pyworkflow runs cancel <run_id> --reason 'test'")
        await sleep("60s")

        # Step 3: Create shipment
        order = await cancel_demo_create_shipment(order)

        logger.info(f"[Workflow] Order {order_id} completed successfully!")
        return order

    except CancellationError as e:
        # Workflow was cancelled - perform cleanup
        logger.warning(f"[Workflow] Cancellation detected! Reason: {e.reason}")
        logger.warning("[Workflow] Performing compensation/cleanup...")

        # Use shield() to ensure cleanup completes
        # Even if another cancellation is requested, this block will finish
        async with shield():
            await cancel_demo_release_inventory(order_id)
            await cancel_demo_refund_payment(order_id)

        logger.warning("[Workflow] Cleanup complete. Re-raising CancellationError.")
        raise  # Re-raise to mark workflow as CANCELLED


@step()
async def cancel_demo_long_running_step(items: list) -> list:
    """
    Example of cooperative cancellation within a long-running step.

    Since cancellation doesn't interrupt steps mid-execution, use
    ctx.check_cancellation() for responsive cancellation in long loops.
    """
    ctx = get_context()
    results = []

    for i, item in enumerate(items):
        # Check for cancellation periodically
        if i % 10 == 0:
            ctx.check_cancellation()  # Raises CancellationError if cancelled

        # Process item
        await asyncio.sleep(0.1)
        results.append(f"processed_{item}")

    return results


# --- Alternative: Workflow without cleanup ---
@workflow(tags=["celery", "durable"])
async def cancel_demo_simple_workflow(data: str) -> str:
    """
    Simple workflow without explicit cancellation handling.

    If cancelled:
    - CancellationError propagates up
    - Workflow is marked as CANCELLED
    - No cleanup is performed

    This is fine for workflows that don't need compensation logic.
    """
    logger.info(f"[Workflow] Processing: {data}")

    await sleep("60s")  # Cancel during this sleep

    logger.info(f"[Workflow] Done: {data}")
    return f"result_{data}"


async def main() -> None:
    """Run the order workflow example."""
    import argparse

    import pyworkflow

    parser = argparse.ArgumentParser(description="Order Workflow with Cancellation")
    parser.add_argument("--order-id", default="order-123", help="Order ID to process")
    args = parser.parse_args()

    print("=" * 70)
    print("ORDER WORKFLOW WITH CANCELLATION SUPPORT")
    print("=" * 70)
    print()
    print(f"Starting order workflow for {args.order_id}...")
    print("The workflow will sleep for 60 seconds - perfect time to cancel!")
    print()

    run_id = await pyworkflow.start(cancellable_order_workflow, args.order_id)

    print(f"Workflow started with run_id: {run_id}")
    print()
    print("=" * 70)
    print("TO CANCEL THIS WORKFLOW:")
    print("=" * 70)
    print()
    print(f"  pyworkflow runs cancel {run_id} --reason 'Customer cancelled'")
    print()
    print("Or wait for it and see cleanup:")
    print()
    print(f"  pyworkflow runs cancel {run_id} --wait --reason 'Customer cancelled'")
    print()
    print("=" * 70)
    print("CHECK STATUS:")
    print("=" * 70)
    print()
    print(f"  pyworkflow runs status {run_id}")
    print(f"  pyworkflow runs logs {run_id}")
    print(f"  pyworkflow runs logs {run_id} --filter cancel")
    print()


if __name__ == "__main__":
    asyncio.run(main())
