"""
Celery Transient Workflow - Basic Example

This example demonstrates a simple transient workflow running on Celery workers.

Transient workflows:
- Do NOT record events
- Do NOT persist state
- Are simpler and faster
- Best for short-lived, stateless tasks

Prerequisites:
    1. Start Redis: docker run -d -p 6379:6379 redis:7-alpine
    2. Start worker: pyworkflow --module examples.celery.transient.01_basic_workflow worker run

Run with CLI:
    pyworkflow --module examples.celery.transient.01_basic_workflow workflows run quick_task \
        --arg item_id=item-123

Note: Since this is transient, runs list and runs status won't show this workflow.
"""

import asyncio

from pyworkflow import step, workflow


@step(name="transient_process_item")
async def process_item(item_id: str) -> dict:
    """Process a single item."""
    print(f"[Step] Processing item {item_id}...")
    await asyncio.sleep(0.5)  # Simulate quick processing
    return {"item_id": item_id, "processed": True}


@step(name="transient_enrich_item")
async def enrich_item(item: dict) -> dict:
    """Enrich item with additional data."""
    print(f"[Step] Enriching item {item['item_id']}...")
    await asyncio.sleep(0.3)
    return {**item, "enriched": True, "score": 0.95}


@step(name="transient_store_result")
async def store_result(item: dict) -> dict:
    """Store the processed result."""
    print(f"[Step] Storing result for {item['item_id']}...")
    await asyncio.sleep(0.2)
    return {**item, "stored": True}


@workflow(durable=False, tags=["celery", "transient"])  # Transient workflow - no event recording
async def quick_task(item_id: str) -> dict:
    """
    Quick processing task (transient).

    This workflow runs without event recording for maximum performance.
    Ideal for:
    - High-throughput processing
    - Stateless transformations
    - Quick API calls
    - Tasks that can be safely retried from scratch
    """
    print(f"\n[Workflow] Quick task for {item_id}")

    item = await process_item(item_id)
    item = await enrich_item(item)
    item = await store_result(item)

    print(f"[Workflow] Completed: {item}\n")
    return item


async def main() -> None:
    """Run the transient workflow example."""
    import argparse

    import pyworkflow

    parser = argparse.ArgumentParser(description="Quick Processing Task (Transient)")
    parser.add_argument("--item-id", default="item-123", help="Item ID to process")
    args = parser.parse_args()

    print(f"Starting quick task for {args.item_id}...")
    print("NOTE: This is a transient workflow - no events are recorded")
    run_id = await pyworkflow.start(quick_task, args.item_id)
    print(f"Task dispatched with run_id: {run_id}")


if __name__ == "__main__":
    asyncio.run(main())
