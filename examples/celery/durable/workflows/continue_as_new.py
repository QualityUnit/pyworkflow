"""
Durable Workflow (Celery) - Continue-As-New

This example demonstrates continue_as_new() with Celery workers:
- Polling workflows that need fresh event history
- Batch processing with continuation
- Tracking workflow chains across distributed workers

Prerequisites:
1. Redis running: docker run -d -p 6379:6379 redis
2. Start Celery worker:
   celery -A pyworkflow.celery.tasks worker -Q pyworkflow.workflows,pyworkflow.steps,pyworkflow.schedules -l info

Run: python examples/celery/durable/11_continue_as_new.py
"""

import asyncio

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
    total_items = 50  # Simulate 50 total items
    if offset >= total_items:
        return []
    end = min(offset + batch_size, total_items)
    items = list(range(offset, end))
    print(f"  [Step] Fetched items {offset} to {end - 1}")
    await asyncio.sleep(0.1)  # Simulate I/O
    return items


@step(name="continue_process_item")
async def process_item(item: int) -> dict:
    """Process a single item."""
    await asyncio.sleep(0.05)  # Simulate work
    return {"item": item, "processed": True}


@step()
async def poll_for_messages(cursor: str | None) -> tuple[str | None, list]:
    """Poll message queue for new messages."""
    # Simulate message queue polling
    await asyncio.sleep(0.1)

    if cursor is None:
        return "msg_batch_1", [{"id": 1, "type": "order"}, {"id": 2, "type": "payment"}]
    elif cursor == "msg_batch_1":
        return "msg_batch_2", [{"id": 3, "type": "shipment"}]
    elif cursor == "msg_batch_2":
        return "msg_batch_3", [{"id": 4, "type": "notification"}]
    else:
        return None, []  # No more messages


@step()
async def handle_message(message: dict) -> dict:
    """Handle a single message."""
    await asyncio.sleep(0.05)
    return {"message_id": message["id"], "handled": True}


# --- Batch Processing Workflow ---
@workflow(durable=True, tags=["celery", "durable"])
async def batch_processor(offset: int = 0, batch_size: int = 10) -> str:
    """
    Process items in batches using continue_as_new.

    Each batch runs as a separate workflow execution with fresh
    event history, preventing unbounded history growth.

    This pattern is ideal for:
    - ETL pipelines processing millions of records
    - Data migration jobs
    - Bulk update operations
    """
    print(f"\n  [Batch] Starting at offset {offset}")

    items = await fetch_batch(offset, batch_size)

    if not items:
        return f"Batch processing complete! Total items: {offset}"

    # Process items
    for item in items:
        await process_item(item)

    print(f"  [Batch] Processed {len(items)} items")

    # Continue with next batch
    continue_as_new(offset=offset + batch_size, batch_size=batch_size)


# --- Message Consumer Workflow ---
@workflow(durable=True, tags=["celery", "durable"])
async def message_consumer(cursor: str | None = None, messages_processed: int = 0) -> str:
    """
    Consume messages from a queue, continuing as new after each batch.

    This pattern is useful for:
    - Queue consumers that run indefinitely
    - Event stream processors
    - Real-time data ingestion
    """
    print(f"\n  [Consumer] Polling with cursor: {cursor}")

    # Poll for messages
    new_cursor, messages = await poll_for_messages(cursor)

    if not messages and new_cursor is None:
        return f"Consumer complete! Processed {messages_processed} messages"

    # Handle each message
    count = 0
    for message in messages:
        await handle_message(message)
        count += 1

    total = messages_processed + count
    print(f"  [Consumer] Handled {count} messages (total: {total})")

    # Continue with new cursor
    continue_as_new(cursor=new_cursor, messages_processed=total)


# --- Recurring Task Workflow ---
@workflow(durable=True, tags=["celery", "durable"])
async def recurring_report(iteration: int = 1, max_iterations: int = 3) -> str:
    """
    Generate reports on a schedule, continuing as new for each iteration.

    This demonstrates a pattern for:
    - Daily/weekly reports
    - Scheduled cleanup tasks
    - Periodic sync operations

    In production, you might add sleep() between iterations.
    """
    print(f"\n  [Report] Generating report #{iteration}")

    # Simulate report generation
    await asyncio.sleep(0.1)
    print(f"  [Report] Report #{iteration} complete")

    if iteration >= max_iterations:
        return f"All {max_iterations} reports generated!"

    # Continue with next iteration
    continue_as_new(iteration=iteration + 1, max_iterations=max_iterations)


async def run_examples():
    """Run all continue-as-new examples."""
    print("\n=== Continue-As-New Examples (Celery) ===\n")

    # Example 1: Batch Processing
    print("--- Example 1: Batch Processing ---")
    print("Processing 50 items in batches of 10...")

    run_id = await start(batch_processor, offset=0, batch_size=10)
    print(f"Started workflow: {run_id}")

    # Wait for completion (in production, use webhooks or polling)
    print("Waiting for completion...")
    await asyncio.sleep(5)

    # Check the chain
    from pyworkflow import get_storage

    storage = get_storage()
    chain = await get_workflow_chain(run_id, storage=storage)
    print(f"\nWorkflow chain has {len(chain)} runs:")
    for i, run in enumerate(chain):
        marker = "  <- started here" if run.run_id == run_id else ""
        print(f"  {i + 1}. {run.run_id[:20]}... [{run.status.value}]{marker}")

    # Example 2: Message Consumer
    print("\n--- Example 2: Message Consumer ---")
    print("Consuming messages until queue is empty...")

    run_id2 = await start(message_consumer)
    print(f"Started workflow: {run_id2}")

    await asyncio.sleep(3)

    chain2 = await get_workflow_chain(run_id2, storage=storage)
    print(f"\nConsumer chain has {len(chain2)} runs")
    if chain2:
        final = chain2[-1]
        if final.result:
            print(f"Final result: {final.result}")

    # Example 3: Recurring Task
    print("\n--- Example 3: Recurring Report ---")
    print("Running 3 report iterations...")

    run_id3 = await start(recurring_report)
    print(f"Started workflow: {run_id3}")

    await asyncio.sleep(2)

    chain3 = await get_workflow_chain(run_id3, storage=storage)
    print(f"\nReport chain has {len(chain3)} runs")

    # Summary
    print("\n=== Summary ===")
    print(f"  Batch processor: {len(chain)} workflow executions")
    print(f"  Message consumer: {len(chain2)} workflow executions")
    print(f"  Recurring report: {len(chain3)} workflow executions")


def main():
    """Configure and run examples."""
    print("Configuring PyWorkflow with Celery runtime...")

    # Reset any existing config
    reset_config()

    # Configure storage
    storage = FileStorageBackend(base_path=".workflow_data")

    # Configure pyworkflow
    configure(
        storage=storage,
        default_runtime="celery",
        default_durable=True,
    )

    print("Configuration complete!")
    print("\nMake sure Celery worker is running:")
    print(
        "  celery -A pyworkflow.celery.tasks worker -Q pyworkflow.workflows,pyworkflow.steps,pyworkflow.schedules -l info\n"
    )

    # Run examples
    asyncio.run(run_examples())

    print("\n=== Key Takeaways ===")
    print("  - continue_as_new() works across distributed Celery workers")
    print("  - Each continuation is a new Celery task execution")
    print("  - Event history is reset, preventing unbounded growth")
    print("  - Chains can be tracked with get_workflow_chain()")
    print("  - Useful for long-running polling, batch processing, recurring tasks")


if __name__ == "__main__":
    main()
