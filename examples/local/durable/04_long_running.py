"""
Durable Workflow - Long Running with Sleep

This example demonstrates workflow suspension and resumption with sleep().
- Workflow suspends during sleep (releases resources)
- Can be resumed after sleep completes
- Uses FileStorageBackend for persistence across process restarts
- Demonstrates manual resumption pattern

IMPORTANT: Manual resumption (await resume(run_id)) is ONLY for local development/CI.
In production, use Celery runtime for automatic scheduled resumption.
See examples/celery/ for production-ready distributed execution.

Run: python examples/local/durable/04_long_running.py 2>/dev/null
"""

import asyncio
import tempfile

from pyworkflow import (
    configure,
    get_workflow_run,
    reset_config,
    resume,
    sleep,
    start,
    step,
    workflow,
)
from pyworkflow.storage import FileStorageBackend


# --- Steps ---
@step()
async def prepare_batch(batch_id: str) -> dict:
    """Prepare the batch for processing."""
    print(f"  Preparing batch {batch_id}...")
    return {"batch_id": batch_id, "status": "prepared"}


@step()
async def process_batch(batch: dict) -> dict:
    """Process the batch after sleep completes."""
    print(f"  Processing batch {batch['batch_id']}...")
    return {**batch, "status": "processed", "items": 1000}


@step()
async def finalize_batch(batch: dict) -> dict:
    """Finalize the batch."""
    print(f"  Finalizing batch {batch['batch_id']}...")
    return {**batch, "status": "completed"}


# --- Workflow ---
@workflow(durable=True, tags=["local", "durable"])
async def batch_workflow(batch_id: str) -> dict:
    """Long-running batch processing workflow with sleep."""
    batch = await prepare_batch(batch_id)

    print("  Sleeping for 5 seconds (workflow will suspend)...")
    await sleep("5s")  # Suspends workflow here

    print("  Resuming after sleep...")
    batch = await process_batch(batch)
    batch = await finalize_batch(batch)
    return batch


async def main():
    # Use temp directory (use real path like "./workflow_data" for production)
    with tempfile.TemporaryDirectory() as tmpdir:
        print("=== Durable Workflow - Long Running ===\n")

        # Configure with FileStorageBackend (for persistence)
        reset_config()
        storage = FileStorageBackend(base_path=tmpdir)
        configure(storage=storage, default_durable=True)

        print("Starting batch workflow...\n")

        # Start workflow
        run_id = await start(batch_workflow, "batch-001")

        # Check status after start
        run = await get_workflow_run(run_id)
        print(f"\nWorkflow status after sleep: {run.status.value}")

        if run.status.value == "suspended":
            print("Workflow is suspended (waiting for sleep to complete)")

            # Wait for sleep duration, then resume
            print("\nWaiting 5 seconds for sleep to complete...")
            await asyncio.sleep(5)

            print(f"Resuming workflow {run_id}...\n")
            result = await resume(run_id)

            print("\nWorkflow completed!")
            print(f"Result: {result}")
        else:
            # Workflow already completed (sleep was short enough)
            print("Workflow completed without suspension")
            print(f"Result: {run.result}")

        # Final status check
        run = await get_workflow_run(run_id)
        print(f"\nFinal status: {run.status.value}")

        print("\n=== Key Takeaways ===")
        print("✓ Workflow suspends during sleep() (releases resources)")
        print("✓ FileStorageBackend persists state during suspension")
        print("✓ Can resume after sleep completes (even after process restart)")
        print("✓ Perfect for rate limiting, scheduled tasks, waiting for events")
        print("\nℹ  For production: use real storage path, implement auto-resume logic")


if __name__ == "__main__":
    asyncio.run(main())
