"""
Celery Durable Workflow - Batch Processing

This example demonstrates batch item processing on Celery workers.
- Fetch items to process
- Process each item (each as a recorded step)
- Aggregate results

Prerequisites:
    1. Start Redis: docker run -d -p 6379:6379 redis:7-alpine
    2. Start worker: pyworkflow --module examples.celery.durable.04_batch_processing worker run

Run with CLI:
    pyworkflow --module examples.celery.durable.04_batch_processing workflows run batch_workflow \
        --arg batch_id=batch-789 --arg limit=5

Check status:
    pyworkflow runs status <run_id>
    pyworkflow runs logs <run_id> --filter step_completed
"""

from pyworkflow import step, workflow


@step()
async def fetch_batch_items(batch_id: str, limit: int = 100) -> list:
    """Fetch items to process in this batch."""
    print(f"[Step] Fetching batch {batch_id} with limit {limit}...")
    # Simulate fetching items from database
    items = [{"id": f"item-{i}", "batch_id": batch_id} for i in range(min(limit, 10))]
    print(f"[Step] Fetched {len(items)} items")
    return items


@step(name="batch_process_item")
async def process_item(item: dict) -> dict:
    """Process a single item."""
    print(f"[Step] Processing item {item['id']}...")
    # Simulate processing
    return {**item, "processed": True, "result": f"processed_{item['id']}"}


@step()
async def aggregate_results(results: list) -> dict:
    """Aggregate processing results."""
    successful = len([r for r in results if r.get("processed")])
    print(f"[Step] Aggregating {len(results)} results ({successful} successful)...")
    return {
        "total": len(results),
        "successful": successful,
        "failed": len(results) - successful,
    }


@workflow(tags=["celery", "durable"])
async def batch_workflow(batch_id: str, limit: int = 100) -> dict:
    """
    Batch processing workflow.

    Steps:
    1. Fetch items to process
    2. Process each item individually
    3. Aggregate and return results

    Each item processing is recorded as a separate step event,
    enabling fine-grained tracking and potential parallel execution.
    """
    items = await fetch_batch_items(batch_id, limit)

    # Process items sequentially (each recorded as step)
    results = []
    for item in items:
        result = await process_item(item)
        results.append(result)

    summary = await aggregate_results(results)
    return {"batch_id": batch_id, **summary}


async def main() -> None:
    """Run the batch processing workflow example."""
    import argparse

    import pyworkflow

    parser = argparse.ArgumentParser(description="Batch Processing Workflow")
    parser.add_argument("--batch-id", default="batch-789", help="Batch ID to process")
    parser.add_argument("--limit", type=int, default=5, help="Maximum items to process")
    args = parser.parse_args()

    # Configuration is automatically loaded from pyworkflow.config.yaml
    print(f"Starting batch workflow for {args.batch_id} (limit: {args.limit})...")
    run_id = await pyworkflow.start(batch_workflow, args.batch_id, args.limit)
    print(f"Workflow started with run_id: {run_id}")
    print(f"\nCheck status: pyworkflow runs status {run_id}")
    print(f"View step logs: pyworkflow runs logs {run_id} --filter step_completed")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
