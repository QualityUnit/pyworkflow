"""
Durable Workflow - Event Log Deep Dive

This example demonstrates detailed event sourcing inspection.
- Multiple workflows to show different event sequences
- Deep dive into event structure (sequence, type, timestamp, data)
- Understanding event types and their meaning
- Event replay concepts

Run: python examples/local/durable/05_event_log.py 2>/dev/null
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
async def step_a(value: int) -> int:
    """Simple step that doubles the value."""
    return value * 2


@step()
async def step_b(value: int) -> int:
    """Simple step that adds 10."""
    return value + 10


@step()
async def step_c(value: int) -> int:
    """Simple step that subtracts 5."""
    return value - 5


# --- Workflows ---
@workflow(durable=True, tags=["local", "durable"])
async def simple_workflow(value: int) -> int:
    """Simple 2-step workflow."""
    result = await step_a(value)
    result = await step_b(result)
    return result


@workflow(durable=True, tags=["local", "durable"])
async def complex_workflow(value: int) -> int:
    """More complex 3-step workflow."""
    result = await step_a(value)
    result = await step_b(result)
    result = await step_c(result)
    return result


def print_event_details(event, index: int):
    """Pretty print event details."""
    print(f"\nEvent #{index + 1}:")
    print(f"  Sequence: {event.sequence}")
    print(f"  Type: {event.type.value}")
    print(f"  Timestamp: {event.timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}")

    if event.data:
        print("  Data:")
        for key, value in event.data.items():
            # Format value nicely
            if isinstance(value, str) and len(value) > 50:
                value = value[:50] + "..."
            print(f"    {key}: {value}")


async def main():
    # Configure with InMemoryStorageBackend
    reset_config()
    storage = InMemoryStorageBackend()
    configure(storage=storage, default_durable=True)

    print("=== Durable Workflow - Event Log Deep Dive ===\n")

    # Run first workflow
    print("Running simple_workflow(5)...\n")
    run_id_1 = await start(simple_workflow, 5)

    run = await get_workflow_run(run_id_1)
    print(f"Result: {run.result}")
    print(f"Status: {run.status.value}")

    # Inspect events
    events = await get_workflow_events(run_id_1)
    print(f"\n=== Event Log for simple_workflow ({len(events)} events) ===")

    for i, event in enumerate(events):
        print_event_details(event, i)

    # Run second workflow
    print("\n" + "=" * 60)
    print("\nRunning complex_workflow(10)...\n")
    run_id_2 = await start(complex_workflow, 10)

    run = await get_workflow_run(run_id_2)
    print(f"Result: {run.result}")
    print(f"Status: {run.status.value}")

    # Inspect events
    events = await get_workflow_events(run_id_2)
    print(f"\n=== Event Log for complex_workflow ({len(events)} events) ===")

    for i, event in enumerate(events):
        print_event_details(event, i)

    # Event type summary
    print("\n" + "=" * 60)
    print("\n=== Event Types Explained ===")
    print("workflow_started   - Workflow execution begins")
    print("step_completed     - Step successfully executed (result cached)")
    print("step_failed        - Step failed (will retry if configured)")
    print("sleep_started      - Workflow suspended (sleep begins)")
    print("sleep_completed    - Workflow resumed (sleep ends)")
    print("workflow_completed - Workflow finished successfully")
    print("workflow_failed    - Workflow failed permanently")

    print("\n=== Event Replay Concepts ===")
    print("✓ Events are immutable - never modified, only appended")
    print("✓ On crash/restart, events replayed to restore state")
    print("✓ step_completed events: result cached, step not re-executed")
    print("✓ Sequence numbers ensure deterministic ordering")
    print("✓ Timestamps enable time-travel debugging")

    print("\n=== Key Takeaways ===")
    print("✓ Every state change recorded as an event")
    print("✓ Events contain sequence, type, timestamp, and data")
    print("✓ Event log enables crash recovery via replay")
    print("✓ Complete audit trail for compliance and debugging")


if __name__ == "__main__":
    asyncio.run(main())
