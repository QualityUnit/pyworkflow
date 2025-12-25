"""
Durable Workflow - Cancellation

This example demonstrates graceful workflow cancellation:
- Cancel running or suspended workflows
- Handle CancellationError for cleanup
- Use shield() to protect critical operations
- Checkpoint-based cancellation (not mid-step)

Run: python examples/local/durable/08_cancellation.py 2>/dev/null
"""

import asyncio
import tempfile

from pyworkflow import (
    CancellationError,
    cancel_workflow,
    configure,
    get_workflow_run,
    reset_config,
    shield,
    sleep,
    start,
    step,
    workflow,
)
from pyworkflow.storage import FileStorageBackend


# --- Steps ---
@step()
async def reserve_inventory(order_id: str) -> dict:
    """Reserve inventory for order."""
    print(f"  [Step] Reserving inventory for order {order_id}...")
    await asyncio.sleep(0.1)  # Simulate work
    return {"order_id": order_id, "inventory_reserved": True}


@step()
async def charge_payment(order: dict) -> dict:
    """Charge payment for order."""
    print(f"  [Step] Charging payment for order {order['order_id']}...")
    await asyncio.sleep(0.1)  # Simulate work
    return {**order, "payment_charged": True}


@step()
async def create_shipment(order: dict) -> dict:
    """Create shipment for order."""
    print(f"  [Step] Creating shipment for order {order['order_id']}...")
    await asyncio.sleep(0.1)  # Simulate work
    return {**order, "shipment_created": True}


@step()
async def release_inventory(order_id: str) -> None:
    """Release previously reserved inventory (compensation)."""
    print(f"  [Cleanup] Releasing inventory for order {order_id}...")


@step()
async def refund_payment(order_id: str) -> None:
    """Refund charged payment (compensation)."""
    print(f"  [Cleanup] Refunding payment for order {order_id}...")


# --- Workflow with Cancellation Handling ---
@workflow(durable=True, tags=["local", "durable"])
async def order_workflow(order_id: str) -> dict:
    """
    Order processing workflow with cancellation handling.

    If cancelled:
    - Catches CancellationError
    - Uses shield() to ensure cleanup completes
    - Releases inventory and refunds payment
    """
    try:
        order = await reserve_inventory(order_id)

        # Simulate waiting for approval
        print("  [Workflow] Waiting 5s for approval (can be cancelled here)...")
        await sleep("5s")

        order = await charge_payment(order)

        # Another wait - e.g., for warehouse processing
        print("  [Workflow] Waiting 5s for warehouse (can be cancelled here)...")
        await sleep("5s")

        order = await create_shipment(order)
        return order

    except CancellationError as e:
        print(f"\n  [Workflow] Cancellation detected! Reason: {e.reason}")
        print("  [Workflow] Performing cleanup...")

        # Use shield() to ensure cleanup completes even if cancelled again
        async with shield():
            await release_inventory(order_id)
            await refund_payment(order_id)

        print("  [Workflow] Cleanup complete, re-raising CancellationError")
        raise  # Re-raise to mark workflow as cancelled


async def example_cancel_suspended_workflow(storage):
    """Example 1: Cancel a workflow while it's suspended (sleeping)."""
    print("\n--- Example 1: Cancel Suspended Workflow ---\n")

    # Start workflow
    run_id = await start(order_workflow, "order-001")

    # Check status - should be suspended (sleeping)
    run = await get_workflow_run(run_id)
    print(f"Workflow status: {run.status.value}")

    if run.status.value == "suspended":
        print("\nWorkflow is suspended (sleeping). Cancelling...")

        # Cancel the suspended workflow
        cancelled = await cancel_workflow(
            run_id,
            reason="Customer cancelled order",
            storage=storage,
        )

        print(f"Cancellation initiated: {cancelled}")

        # Check final status
        run = await get_workflow_run(run_id)
        print(f"Final status: {run.status.value}")

    return run_id


async def example_cancel_running_workflow(storage):
    """Example 2: Cancel a running workflow (cancellation at next checkpoint)."""
    print("\n--- Example 2: Cancel Running Workflow ---\n")

    # Define a workflow that we can cancel mid-execution
    @workflow(durable=True)
    async def multi_step_workflow(job_id: str) -> dict:
        try:
            print(f"  [Step 1] Starting job {job_id}...")
            await asyncio.sleep(0.1)

            print("  [Step 2] Processing (cancellation checked here)...")
            # Note: In real scenario, ctx.check_cancellation() would be called
            # by @step decorator before execution
            await asyncio.sleep(0.1)

            print("  [Step 3] Finalizing...")
            return {"job_id": job_id, "status": "done"}

        except CancellationError as e:
            print(f"  [Workflow] Cancelled! Reason: {e.reason}")
            raise

    # Start and immediately cancel (before it completes)
    run_id = await start(multi_step_workflow, "job-002")

    run = await get_workflow_run(run_id)
    print(f"Workflow status: {run.status.value}")

    # If it completed before we could cancel, that's OK
    if run.status.value != "completed":
        print("\nCancelling workflow...")
        cancelled = await cancel_workflow(
            run_id,
            reason="Test cancellation",
            storage=storage,
        )
        print(f"Cancellation initiated: {cancelled}")

    # Check final status
    run = await get_workflow_run(run_id)
    print(f"Final status: {run.status.value}")

    return run_id


async def example_cancel_already_completed(storage):
    """Example 3: Try to cancel an already completed workflow."""
    print("\n--- Example 3: Cancel Completed Workflow ---\n")

    # Create a simple quick workflow
    @workflow(durable=True)
    async def quick_workflow() -> str:
        return "done"

    # Start and complete
    run_id = await start(quick_workflow)
    run = await get_workflow_run(run_id)
    print(f"Workflow status: {run.status.value}")

    # Try to cancel
    print("Attempting to cancel completed workflow...")
    cancelled = await cancel_workflow(run_id, storage=storage)

    print(f"Cancellation result: {cancelled}")
    print("(False means workflow was already in terminal state)")

    return run_id


async def main():
    # Use temp directory
    with tempfile.TemporaryDirectory() as tmpdir:
        print("=== Durable Workflow - Cancellation ===")

        # Configure with FileStorageBackend
        reset_config()
        storage = FileStorageBackend(base_path=tmpdir)
        configure(storage=storage, default_durable=True)

        # Run examples
        await example_cancel_suspended_workflow(storage)
        await example_cancel_running_workflow(storage)
        await example_cancel_already_completed(storage)

        print("\n=== Key Takeaways ===")
        print("  - cancel_workflow() requests graceful cancellation")
        print("  - Suspended workflows are cancelled immediately")
        print("  - Running workflows cancel at next checkpoint (before step/sleep/hook)")
        print("  - Catch CancellationError for cleanup logic")
        print("  - Use shield() to protect critical cleanup operations")
        print("  - Cancellation does NOT interrupt a step mid-execution")


if __name__ == "__main__":
    asyncio.run(main())
