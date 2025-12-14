"""
Durable Workflow with In-Memory Storage

InMemoryStorageBackend stores workflow state in memory.
- Data lost when process exits
- Good for testing and ephemeral workloads
- Demonstrates: events, sleep/suspension, idempotency

Run: python examples/durable/example_memory.py 2>/dev/null
"""

import asyncio

from pyworkflow import (
    configure,
    get_workflow_events,
    get_workflow_run,
    reset_config,
    sleep,
    start,
    step,
    workflow,
)
from pyworkflow.storage import InMemoryStorageBackend


# --- Steps ---
@step()
async def process_order(order_id: str) -> dict:
    return {"order_id": order_id, "status": "processed"}


@step()
async def charge_payment(order: dict, amount: float) -> dict:
    return {**order, "charged": amount}


@step()
async def send_notification(order: dict) -> dict:
    return {**order, "notified": True}


# --- Workflows ---
@workflow(durable=True)
async def order_workflow(order_id: str, amount: float) -> dict:
    order = await process_order(order_id)
    order = await charge_payment(order, amount)
    order = await send_notification(order)
    return order


@workflow(durable=True)
async def delayed_workflow(order_id: str) -> dict:
    """Suspends at sleep - resume with resume(run_id)."""
    order = await process_order(order_id)
    await sleep("1h")
    order = await send_notification(order)
    return order


@workflow(durable=True)
async def payment_workflow(payment_id: str, amount: float) -> dict:
    return await charge_payment({"payment_id": payment_id}, amount)


async def main():
    storage = InMemoryStorageBackend()
    reset_config()
    configure(storage=storage, default_durable=True)

    # Run workflow
    run_id = await start(order_workflow, "order_123", 99.99)
    print(f"Workflow completed: {run_id}")

    run = await get_workflow_run(run_id)
    print(f"Status: {run.status.value}")
    print(f"Result: {run.result}")

    # Event log
    events = await get_workflow_events(run_id)
    print(f"\nEvent log ({len(events)} events):")
    for event in events:
        print(f"  {event.sequence}: {event.type.value}")

    # Sleep causes suspension
    sleep_run_id = await start(delayed_workflow, "order_456")
    sleep_run = await get_workflow_run(sleep_run_id)
    print(f"\nDelayed workflow: {sleep_run_id}")
    print(f"Status: {sleep_run.status.value}")

    # Idempotency
    key = "payment_abc_123"
    run_id_1 = await start(payment_workflow, "pay_001", 50.00, idempotency_key=key)
    run_id_2 = await start(payment_workflow, "pay_001", 50.00, idempotency_key=key)
    print(f"\nIdempotency: {run_id_1 == run_id_2}")


if __name__ == "__main__":
    asyncio.run(main())
