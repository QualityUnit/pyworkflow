"""
Transient Workflow - Async Sleep

This example demonstrates sleep() behavior in transient mode.
- Uses asyncio.sleep() under the hood (blocks workflow)
- No workflow suspension (unlike durable mode)
- Simple delay mechanism
- Perfect for rate limiting and delays

Run: python examples/local/transient/03_sleep.py 2>/dev/null
"""

import asyncio
from datetime import datetime

from pyworkflow import (
    configure,
    reset_config,
    sleep,
    start,
    step,
    workflow,
)


# --- Steps ---
@step()
async def start_task(task_id: str) -> dict:
    """Start a task."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"  [{timestamp}] Starting task {task_id}...")
    return {"task_id": task_id, "status": "started"}


@step()
async def process_task(task: dict) -> dict:
    """Process the task."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"  [{timestamp}] Processing task {task['task_id']}...")
    return {**task, "status": "processed"}


@step()
async def complete_task(task: dict) -> dict:
    """Complete the task."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"  [{timestamp}] Completing task {task['task_id']}...")
    return {**task, "status": "completed"}


# --- Workflows ---
@workflow(durable=False, tags=["local", "transient"])
async def delayed_workflow(task_id: str, delay_seconds: int) -> dict:
    """Workflow with sleep delay."""
    task = await start_task(task_id)

    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"  [{timestamp}] Sleeping for {delay_seconds} seconds...")
    await sleep(f"{delay_seconds}s")  # Uses asyncio.sleep() in transient mode

    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"  [{timestamp}] Woke up from sleep!")

    task = await process_task(task)
    task = await complete_task(task)
    return task


@workflow(durable=False, tags=["local", "transient"])
async def rate_limited_workflow(task_id: str) -> dict:
    """Workflow demonstrating rate limiting pattern."""
    task = await start_task(task_id)

    # Simulate rate limiting between API calls
    print("  Rate limiting: waiting 2 seconds before next API call...")
    await sleep("2s")

    task = await process_task(task)

    # Another rate limit delay
    print("  Rate limiting: waiting 2 seconds before final call...")
    await sleep("2s")

    task = await complete_task(task)
    return task


async def main():
    # Configure for transient mode
    reset_config()
    configure(default_durable=False)

    print("=== Transient Workflow - Async Sleep ===\n")

    # Example 1: Basic sleep
    print("Example 1: Basic sleep (3 seconds)\n")
    start_time = datetime.now()

    run_id = await start(delayed_workflow, "task-001", 3)

    end_time = datetime.now()
    elapsed = (end_time - start_time).total_seconds()

    print(f"\nWorkflow completed: {run_id}")
    print(f"Total time: {elapsed:.1f} seconds")

    # Example 2: Rate limiting
    print("\n" + "=" * 60)
    print("\nExample 2: Rate limiting with multiple sleeps\n")
    start_time = datetime.now()

    run_id = await start(rate_limited_workflow, "task-002")

    end_time = datetime.now()
    elapsed = (end_time - start_time).total_seconds()

    print(f"\nWorkflow completed: {run_id}")
    print(f"Total time: {elapsed:.1f} seconds")

    print("\n=== Sleep Behavior in Transient Mode ===")
    print("✓ Uses asyncio.sleep() (blocks the workflow)")
    print("✓ No workflow suspension (process keeps running)")
    print("✓ No resource release during sleep")
    print("✓ Perfect for short delays and rate limiting")

    print("\n=== Sleep Format Support ===")
    print('sleep("5s")     - 5 seconds')
    print('sleep("2m")     - 2 minutes')
    print('sleep("1h")     - 1 hour')
    print("sleep(30)       - 30 seconds (int)")
    print("sleep(timedelta(seconds=10)) - 10 seconds")

    print("\n=== Difference from Durable Mode ===")
    print("Transient: sleep() blocks using asyncio.sleep()")
    print("Durable:   sleep() suspends workflow, can resume later")
    print("\nFor long-running workflows with suspension:")
    print("  See examples/local/durable/04_long_running.py")


if __name__ == "__main__":
    asyncio.run(main())
