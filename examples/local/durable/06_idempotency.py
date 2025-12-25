"""
Durable Workflow - Idempotency

This example demonstrates idempotency key usage to prevent duplicate workflow execution.
- Same workflow called twice with same idempotency_key
- Second call returns same run_id without re-execution
- Prevents duplicate orders, payments, etc.
- Uses FileStorageBackend for persistence

Run: python examples/local/durable/06_idempotency.py 2>/dev/null
"""

import asyncio
import tempfile

from pyworkflow import (
    configure,
    get_workflow_run,
    reset_config,
    start,
    step,
    workflow,
)
from pyworkflow.storage import FileStorageBackend

# Execution counter to track step calls
execution_count = 0


# --- Steps ---
@step()
async def create_order(order_id: str, amount: float) -> dict:
    """Create a new order."""
    global execution_count
    execution_count += 1

    print(f"  Creating order {order_id} for ${amount:.2f}...")
    print(f"  (Execution count: {execution_count})")

    return {"order_id": order_id, "amount": amount, "status": "created"}


@step()
async def charge_customer(order: dict) -> dict:
    """Charge the customer."""
    print(f"  Charging customer ${order['amount']:.2f}...")
    return {**order, "charged": True}


@step()
async def send_confirmation(order: dict) -> dict:
    """Send order confirmation."""
    print(f"  Sending confirmation for order {order['order_id']}...")
    return {**order, "confirmed": True}


# --- Workflow ---
@workflow(durable=True, tags=["local", "durable"])
async def order_workflow(order_id: str, amount: float) -> dict:
    """Complete order workflow (must be idempotent)."""
    order = await create_order(order_id, amount)
    order = await charge_customer(order)
    order = await send_confirmation(order)
    return order


async def main():
    global execution_count

    # Use temp directory (use real path for production)
    with tempfile.TemporaryDirectory() as tmpdir:
        print("=== Durable Workflow - Idempotency ===\n")

        # Configure with FileStorageBackend (for persistence)
        reset_config()
        storage = FileStorageBackend(base_path=tmpdir)
        configure(storage=storage, default_durable=True)

        # Reset execution count
        execution_count = 0

        # First call with idempotency key
        print("First call: Creating order with idempotency_key='order-unique-123'...\n")
        run_id_1 = await start(
            order_workflow, "order-unique-123", 99.99, idempotency_key="order-unique-123"
        )

        run_1 = await get_workflow_run(run_id_1)
        print("\nFirst call completed:")
        print(f"  Run ID: {run_id_1}")
        print(f"  Status: {run_1.status.value}")
        print(f"  Result: {run_1.result}")
        print(f"  Execution count: {execution_count}")

        # Second call with SAME idempotency key
        print("\n" + "=" * 60)
        print("\nSecond call: Same idempotency_key='order-unique-123'...\n")
        run_id_2 = await start(
            order_workflow, "order-unique-123", 99.99, idempotency_key="order-unique-123"
        )

        run_2 = await get_workflow_run(run_id_2)
        print("\nSecond call result:")
        print(f"  Run ID: {run_id_2}")
        print(f"  Status: {run_2.status.value}")
        print(f"  Result: {run_2.result}")
        print(f"  Execution count: {execution_count} (not incremented!)")

        # Verify they're the same
        print("\n" + "=" * 60)
        print("\n=== Verification ===")
        print(f"run_id_1 == run_id_2: {run_id_1 == run_id_2}")
        print(f"Workflow re-executed: {execution_count > 1}")

        if run_id_1 == run_id_2:
            print("\n✓ SUCCESS: Same run_id returned, workflow NOT re-executed!")
        else:
            print("\n✗ UNEXPECTED: Different run_id, workflow was re-executed!")

        # Third call with DIFFERENT idempotency key
        print("\n" + "=" * 60)
        print("\nThird call: Different idempotency_key='order-unique-456'...\n")
        run_id_3 = await start(
            order_workflow, "order-unique-456", 149.99, idempotency_key="order-unique-456"
        )

        run_3 = await get_workflow_run(run_id_3)
        print("\nThird call result:")
        print(f"  Run ID: {run_id_3}")
        print(f"  Status: {run_3.status.value}")
        print(f"  Execution count: {execution_count} (incremented!)")

        print("\n=== Use Cases ===")
        print("✓ Prevent duplicate orders from retry logic")
        print("✓ Ensure exactly-once payment processing")
        print("✓ Handle duplicate webhook deliveries")
        print("✓ Guarantee idempotent API endpoints")

        print("\n=== Key Takeaways ===")
        print("✓ Same idempotency_key returns same run_id")
        print("✓ Workflow NOT re-executed on duplicate key")
        print("✓ Different keys create new workflow executions")
        print("✓ Critical for financial transactions and critical workflows")
        print("✓ Works across process restarts (persisted to storage)")


if __name__ == "__main__":
    asyncio.run(main())
