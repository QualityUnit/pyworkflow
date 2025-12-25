"""
Transient Workflow - Quick Tasks

This example demonstrates simple transient mode execution.
- Simple 3-step order workflow
- No storage backend required
- Fast, direct execution
- No event recording

Run: python examples/local/transient/01_quick_tasks.py 2>/dev/null
"""

import asyncio

from pyworkflow import (
    configure,
    reset_config,
    start,
    step,
    workflow,
)


# --- Steps ---
@step()
async def process_order(order_id: str) -> dict:
    """Process the order and validate it."""
    print(f"  Processing order {order_id}...")
    return {"order_id": order_id, "status": "processed"}


@step()
async def charge_payment(order: dict, amount: float) -> dict:
    """Charge the payment for the order."""
    print(f"  Charging payment: ${amount:.2f}...")
    return {**order, "charged": amount}


@step()
async def send_notification(order: dict) -> dict:
    """Send order confirmation notification."""
    print(f"  Sending notification for order {order['order_id']}...")
    return {**order, "notified": True}


# --- Workflow ---
@workflow(durable=False, tags=["local", "transient"])
async def order_workflow(order_id: str, amount: float) -> dict:
    """Complete order processing workflow (transient mode)."""
    order = await process_order(order_id)
    order = await charge_payment(order, amount)
    order = await send_notification(order)
    return order


async def main():
    # Configure for transient mode (no storage backend needed)
    reset_config()
    configure(default_durable=False)

    print("=== Transient Workflow - Quick Tasks ===\n")
    print("Running order workflow in transient mode...\n")

    # Start workflow
    run_id = await start(order_workflow, "order-123", 99.99)

    print(f"\nWorkflow completed: {run_id}")

    print("\n=== Key Characteristics ===")
    print("✓ No storage backend required")
    print("✓ Fast execution (no event recording overhead)")
    print("✓ Perfect for scripts and CLI tools")
    print("✓ State lost on process exit (no crash recovery)")

    print("\n=== When to Use Transient Mode ===")
    print("✓ Short-lived workflows (seconds to minutes)")
    print("✓ CLI tools and data processing scripts")
    print("✓ Development and testing")
    print("✓ Tasks where simplicity > durability")

    print("\n=== Comparison with Durable Mode ===")
    print("For crash recovery and persistence, see:")
    print("  examples/local/durable/01_basic_workflow.py")


if __name__ == "__main__":
    asyncio.run(main())
