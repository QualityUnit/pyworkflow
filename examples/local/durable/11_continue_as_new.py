"""
Durable Workflow - Continue-As-New

This example demonstrates continue_as_new() for long-running workflows:
- Polling workflows that need fresh event history
- Batch processing with continuation
- Tracking workflow chains
- Using get_workflow_chain() to view the full history

Run: python examples/local/durable/11_continue_as_new.py 2>/dev/null
"""

import asyncio
import tempfile

from pyworkflow import (
    configure,
    continue_as_new,
    get_workflow_chain,
    reset_config,
    start,
    step,
    workflow,
)
from pyworkflow.storage import FileStorageBackend


# --- Steps ---
@step()
async def fetch_batch(offset: int, batch_size: int) -> list:
    """Fetch a batch of items to process."""
    # Simulate fetching items - returns empty when done
    total_items = 25  # Simulate 25 total items
    if offset >= total_items:
        return []
    end = min(offset + batch_size, total_items)
    items = list(range(offset, end))
    print(f"  [Step] Fetched items {offset} to {end - 1}")
    return items


@step()
async def process_batch_item(item: int) -> dict:
    """Process a single item."""
    await asyncio.sleep(0.01)  # Simulate work
    return {"item": item, "processed": True}


@step()
async def check_for_updates(cursor: str | None) -> tuple[str | None, list]:
    """Check for new updates since cursor."""
    # Simulate polling - returns new cursor and items
    if cursor is None:
        return "cursor_1", [{"id": 1, "data": "first"}]
    elif cursor == "cursor_1":
        return "cursor_2", [{"id": 2, "data": "second"}]
    elif cursor == "cursor_2":
        return "cursor_3", [{"id": 3, "data": "third"}]
    else:
        # No more updates
        return None, []


# --- Example 1: Batch Processing Workflow ---
@workflow(durable=True, tags=["local", "durable"])
async def batch_processor(offset: int = 0, batch_size: int = 10) -> str:
    """
    Process items in batches, continuing as new for each batch.

    This pattern prevents event history from growing unbounded
    when processing large datasets.
    """
    print(f"\n  [Workflow] Processing batch starting at offset {offset}")

    # Fetch batch
    items = await fetch_batch(offset, batch_size)

    if not items:
        # No more items - we're done!
        return f"Completed! Processed {offset} total items"

    # Process each item in this batch
    for item in items:
        await process_batch_item(item)

    print("  [Workflow] Batch complete. Continuing with next batch...")

    # Continue with next batch - fresh event history!
    continue_as_new(offset=offset + batch_size, batch_size=batch_size)


# --- Example 2: Polling Workflow ---
@workflow(durable=True, tags=["local", "durable"])
async def polling_workflow(cursor: str | None = None, poll_count: int = 0) -> str:
    """
    Poll for updates indefinitely, continuing as new to reset history.

    This pattern is useful for:
    - Webhook listeners
    - Queue consumers
    - Real-time sync workflows
    """
    print(f"\n  [Workflow] Poll #{poll_count + 1}, cursor: {cursor}")

    # Check for updates
    new_cursor, updates = await check_for_updates(cursor)

    if updates:
        print(f"  [Workflow] Found {len(updates)} update(s)")
        for update in updates:
            print(f"    - Processing: {update}")

    if new_cursor is None:
        # No more updates - done polling
        return f"Polling complete after {poll_count + 1} polls"

    # Continue polling with new cursor
    print(f"  [Workflow] Continuing with new cursor: {new_cursor}")
    continue_as_new(cursor=new_cursor, poll_count=poll_count + 1)


# --- Example 3: Counter Workflow (Simple Demo) ---
@workflow(durable=True, tags=["local", "durable"])
async def countdown_workflow(count: int) -> str:
    """
    Simple countdown that demonstrates continue_as_new.
    Each continuation has fresh event history.
    """
    print(f"\n  [Workflow] Count: {count}")

    if count <= 0:
        return "Countdown complete!"

    # Continue with decremented count
    continue_as_new(count=count - 1)


async def example_batch_processing(storage):
    """Example 1: Batch processing with continuation."""
    print("\n--- Example 1: Batch Processing ---")
    print("Processing 25 items in batches of 10...")

    # Start batch processor
    run_id = await start(batch_processor, offset=0, batch_size=10)

    # Wait for completion
    await asyncio.sleep(0.5)

    # Get the workflow chain
    chain = await get_workflow_chain(run_id, storage=storage)

    print(f"\n  Workflow chain has {len(chain)} runs:")
    for i, run in enumerate(chain):
        status = run.status.value
        result = run.result if run.result else "-"
        print(f"    {i + 1}. {run.run_id[:20]}... - {status}")
        if "Completed" in str(result):
            print(f"       Result: {result}")

    return run_id


async def example_polling(storage):
    """Example 2: Polling workflow."""
    print("\n--- Example 2: Polling Workflow ---")
    print("Polling for updates until no more available...")

    # Start polling workflow
    run_id = await start(polling_workflow)

    # Wait for completion
    await asyncio.sleep(0.5)

    # Get the workflow chain
    chain = await get_workflow_chain(run_id, storage=storage)

    print(f"\n  Polling chain has {len(chain)} runs")

    # Get final result
    final_run = chain[-1]
    if final_run.result:
        print(f"  Final result: {final_run.result}")

    return run_id


async def example_countdown(storage):
    """Example 3: Simple countdown."""
    print("\n--- Example 3: Countdown ---")
    print("Counting down from 3...")

    # Start countdown
    run_id = await start(countdown_workflow, count=3)

    # Wait for completion
    await asyncio.sleep(0.3)

    # Get the workflow chain
    chain = await get_workflow_chain(run_id, storage=storage)

    print(f"\n  Chain: {' -> '.join(r.run_id[:8] + '...' for r in chain)}")
    print(f"  Total runs: {len(chain)}")

    return run_id


async def example_view_chain_details(storage, run_id: str):
    """Show detailed chain information."""
    print("\n--- Chain Details ---")

    chain = await get_workflow_chain(run_id, storage=storage)

    for i, run in enumerate(chain):
        position = "START" if i == 0 else ("CURRENT" if i == len(chain) - 1 else f"#{i + 1}")
        print(f"\n  [{position}] {run.run_id}")
        print(f"    Status: {run.status.value}")
        print(f"    Continued from: {run.continued_from_run_id or '(none)'}")
        print(f"    Continued to: {run.continued_to_run_id or '(none)'}")


async def main():
    # Use temp directory
    with tempfile.TemporaryDirectory() as tmpdir:
        print("=== Durable Workflow - Continue-As-New ===")

        # Configure with FileStorageBackend
        reset_config()
        storage = FileStorageBackend(base_path=tmpdir)
        configure(storage=storage, default_durable=True)

        # Run examples
        batch_run_id = await example_batch_processing(storage)
        await example_polling(storage)
        await example_countdown(storage)

        # Show detailed chain for batch processing
        await example_view_chain_details(storage, batch_run_id)

        print("\n=== Key Takeaways ===")
        print("  - continue_as_new() completes current run and starts fresh")
        print("  - Each continuation has clean event history")
        print("  - Use for long-running polling, batch processing, recurring tasks")
        print("  - get_workflow_chain() retrieves all runs in the chain")
        print("  - Runs are linked via continued_from_run_id/continued_to_run_id")
        print("  - Requires at least one argument (explicit args required)")


if __name__ == "__main__":
    asyncio.run(main())
