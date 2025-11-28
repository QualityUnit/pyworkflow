"""
PyWorkflow Distributed Example

This example demonstrates PyWorkflow's distributed execution capabilities.

Prerequisites:
    1. Start Redis: docker run -d -p 6379:6379 redis:7-alpine
    2. Start Celery worker: celery -A pyworkflow.celery.app worker --loglevel=info
    3. Start Celery beat: celery -A pyworkflow.celery.app beat --loglevel=info

All workflows in PyWorkflow execute in distributed mode across Celery workers,
enabling horizontal scaling and automatic sleep resumption.
"""

from pyworkflow import (
    configure_logging,
    sleep,
    start,
    step,
    workflow,
)


@step()
async def fetch_data(source: str) -> dict:
    """Fetch data from a source (runs on any Celery worker)."""
    print(f"📥 Fetching data from: {source}")
    await asyncio.sleep(0.5)  # Simulate API call
    return {"source": source, "data": f"Data from {source}", "count": 100}


@step()
async def process_data(data: dict) -> dict:
    """Process the fetched data (runs on any Celery worker)."""
    print(f"⚙️  Processing data from: {data['source']}")
    await asyncio.sleep(0.3)
    return {
        **data,
        "processed": True,
        "result": data["data"].upper(),
    }


@step()
async def save_results(data: dict) -> str:
    """Save processed results (runs on any Celery worker)."""
    print(f"💾 Saving results for: {data['source']}")
    await asyncio.sleep(0.2)
    return f"Saved: {data['result']}"


@workflow(name="distributed_data_pipeline")
async def data_pipeline(source: str) -> dict:
    """
    A distributed data processing pipeline.

    This workflow executes across multiple Celery workers:
    - Steps can run on different machines
    - Sleep triggers automatic resumption
    - Fault tolerance through event sourcing
    """
    print(f"\n{'='*60}")
    print(f"🚀 Starting distributed pipeline for: {source}")
    print(f"{'='*60}\n")

    # Step 1: Fetch data (can run on worker A)
    data = await fetch_data(source)
    print(f"✓ Step 1 complete\n")

    # Step 2: Wait before processing (demonstrates automatic resumption)
    print("⏳ Waiting 3 seconds...")
    await sleep("3s")
    print("✓ Sleep complete - workflow auto-resumed!\n")

    # Step 3: Process data (can run on worker B)
    processed = await process_data(data)
    print(f"✓ Step 2 complete\n")

    # Step 4: Save results (can run on worker C)
    saved = await save_results(processed)
    print(f"✓ Step 3 complete\n")

    result = {
        "pipeline": "distributed_data_pipeline",
        "source": source,
        "saved": saved,
        "status": "completed",
    }

    print(f"{'='*60}")
    print(f"✅ Distributed pipeline completed!")
    print(f"{'='*60}\n")

    return result


def main():
    """Run the distributed example."""
    configure_logging(level="WARNING", show_context=False)

    print("\n" + "="*60)
    print("PyWorkflow - Distributed Execution Example")
    print("="*60)
    print("\n✅ Starting workflow in distributed mode")
    print("   Execution happens across Celery workers\n")

    # Start workflow - executes on Celery workers
    run_id = start(
        data_pipeline,
        source="api.example.com",
        # Optional: Use Redis storage for distributed environment
        # storage_config={"type": "redis", "host": "localhost"}
    )

    print(f"\n📋 Workflow Run ID: {run_id}")
    print("🔄 Workflow is running on Celery workers...")
    print("   Check the Celery worker logs to see step execution!")
    print("\n💡 Tip: The workflow will automatically resume after sleep periods")
    print("   thanks to Celery Beat scheduling.\n")

    print("="*60 + "\n")


if __name__ == "__main__":
    main()
