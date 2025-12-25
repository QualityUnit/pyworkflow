"""
Durable Workflow - File Storage

This example demonstrates persistent workflow storage using FileStorageBackend.
- Same 3-step workflow as 01_basic_workflow.py
- Data persists to filesystem in workflow_data/ directory
- Human-readable JSON files
- Inspect stored file structure and JSONL event log

Run: python examples/local/durable/02_file_storage.py 2>/dev/null
"""

import asyncio
import json
import os
from pathlib import Path

from pyworkflow import (
    configure,
    get_workflow_events,
    get_workflow_run,
    reset_config,
    start,
    step,
    workflow,
)
from pyworkflow.storage import FileStorageBackend


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
    # Use local directory for persistence (added to .gitignore)
    data_dir = Path(__file__).parent / "workflow_data"
    data_dir.mkdir(exist_ok=True)

    print("=== Durable Workflow - File Storage ===\n")
    print(f"Storage directory: {data_dir}\n")

    # Configure with FileStorageBackend
    reset_config()
    storage = FileStorageBackend(base_path=str(data_dir))
    configure(storage=storage, default_durable=True)

    print("Running order workflow...")

    # Start workflow
    run_id = await start(order_workflow, "order-456", 149.99)
    print(f"\nWorkflow completed: {run_id}\n")

    # Check workflow status
    run = await get_workflow_run(run_id)
    print(f"Status: {run.status.value}")
    print(f"Result: {run.result}")

    # Show events
    events = await get_workflow_events(run_id)
    print(f"\n=== Event Log ({len(events)} events) ===")
    for event in events:
        print(f"  {event.sequence}: {event.type.value}")

    # Show stored files
    print("\n=== Stored Files ===")
    for root, dirs, files in os.walk(data_dir):
        # Skip hidden directories (.locks)
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            path = os.path.join(root, f)
            rel_path = os.path.relpath(path, data_dir)
            size = os.path.getsize(path)
            print(f"  {rel_path} ({size} bytes)")

    # Show JSONL event log contents
    event_log_path = data_dir / "events" / f"{run_id}.jsonl"
    if event_log_path.exists():
        print(f"\n=== Event Log File Contents ({event_log_path.name}) ===")
        with open(event_log_path) as f:
            for i, line in enumerate(f, 1):
                event_data = json.loads(line.strip())
                event_type = event_data.get("type", "unknown")
                print(f"  Line {i}: {event_type}")
                # Show full data for first event
                if i == 1:
                    print(f"    Full data: {json.dumps(event_data, indent=6)}")

    print("\n=== Directory Structure ===")
    print("  runs/       - Workflow run metadata (JSON)")
    print("  events/     - Event log (JSONL, append-only)")
    print("  steps/      - Step execution records (JSON)")
    print("  .locks/     - Internal file locks")

    print("\n=== Key Takeaways ===")
    print("✓ Data persists to filesystem in workflow_data/")
    print("✓ Human-readable JSON format")
    print("✓ JSONL (JSON Lines) for event log (one event per line)")
    print("✓ Survives process restarts")
    print("✓ Good for development and single-machine deployments")
    print(f"\nℹ  Storage persisted at: {data_dir.absolute()}")


if __name__ == "__main__":
    asyncio.run(main())
