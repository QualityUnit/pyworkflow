"""
Durable Workflow - Basic Example

This example demonstrates a simple event-sourced workflow using InMemoryStorageBackend.
- 3-step order processing workflow
- Events recorded for each step
- Event log inspection after completion
- Basic @workflow and @step decorators

Run: python examples/local/durable/01_basic_workflow.py 2>/dev/null
"""

import asyncio

from pyworkflow import (
    configure,
    get_workflow_events,
    get_workflow_run,
    reset_config,
    start,
    step,
    workflow,
)
from pyworkflow.storage import InMemoryStorageBackend


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
@workflow(durable=True, tags=["local", "durable"])
async def order_workflow(order_id: str, amount: float) -> dict:
    """Complete order processing workflow."""
    order = await process_order(order_id)
    order = await charge_payment(order, amount)
    order = await send_notification(order)
    return order


async def main():
    # Configure with InMemoryStorageBackend
    reset_config()
    storage = InMemoryStorageBackend()
    configure(storage=storage, default_durable=True)

    print("=== Durable Workflow - Basic Example ===\n")
    print("Running order workflow...")

    # Start workflow
    run_id = await start(order_workflow, "order-123", 99.99)
    print(f"\nWorkflow completed: {run_id}\n")

    # Check workflow status
    run = await get_workflow_run(run_id)
    print(f"Status: {run.status.value}")
    print(f"Result: {run.result}")

    # Inspect event log
    events = await get_workflow_events(run_id)
    print(f"\n=== Event Log ({len(events)} events) ===")
    for event in events:
        print(f"  {event.sequence}: {event.type.value}")
        if event.type.value == "step_completed":
            step_name = event.data.get("step_name", "unknown")
            print(f"     Step: {step_name}")

    print("\n=== Key Takeaways ===")
    print("✓ Workflow executed with event sourcing")
    print("✓ Each step recorded as an event")
    print("✓ InMemoryStorageBackend used (data lost on exit)")
    print("✓ Try 02_file_storage.py for persistence!")


if __name__ == "__main__":
    asyncio.run(main())
