"""
Durable Workflow with File Storage

FileStorageBackend persists workflow state to the filesystem.
- Data survives process restarts
- Good for development and single-machine deployments
- Human-readable JSON files

Run: python examples/durable/example_file.py 2>/dev/null
"""

import asyncio
import tempfile

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
from pyworkflow.storage import FileStorageBackend


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


@workflow(durable=True)
async def order_workflow(order_id: str, amount: float) -> dict:
    order = await process_order(order_id)
    order = await charge_payment(order, amount)
    await sleep("1s")  # Suspends workflow, resume with resume(run_id)
    order = await send_notification(order)
    return order


async def main():
    # Use temp directory (use a real path for persistence across restarts)
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = FileStorageBackend(base_path=tmpdir)

        reset_config()
        configure(storage=storage, default_durable=True)

        # Run workflow (will suspend at sleep)
        run_id = await start(order_workflow, "order_123", 99.99)
        print(f"Workflow started: {run_id}")

        # Check status
        run = await get_workflow_run(run_id)
        print(f"Status: {run.status.value}")

        # Show events
        events = await get_workflow_events(run_id)
        print(f"\nEvents ({len(events)}):")
        for event in events:
            print(f"  {event.sequence}: {event.type.value}")

        # Show stored files
        import os
        print(f"\nStored files:")
        for root, dirs, files in os.walk(tmpdir):
            # Skip hidden directories
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                path = os.path.join(root, f)
                print(f"  {os.path.relpath(path, tmpdir)}")


if __name__ == "__main__":
    asyncio.run(main())
