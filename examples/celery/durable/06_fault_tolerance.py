"""
Celery Durable Workflow - Fault Tolerance Example

This example demonstrates automatic recovery from worker failures for durable workflows.

Key features:
- Automatic recovery when workers crash mid-execution
- Event replay continues from the last completed step
- Configurable recovery attempts limit
- WORKFLOW_INTERRUPTED events recorded for auditing

When a worker crashes:
1. The task is automatically requeued (task_reject_on_worker_lost=True)
2. Another worker detects the RUNNING workflow and initiates recovery
3. WORKFLOW_INTERRUPTED event is recorded
4. Events are replayed to restore state
5. Workflow continues from the last checkpoint

Prerequisites:
    1. Start Redis: docker run -d -p 6379:6379 redis:7-alpine
    2. Start worker: pyworkflow --module examples.celery.durable.06_fault_tolerance worker run

Run with CLI:
    pyworkflow --module examples.celery.durable.06_fault_tolerance workflows run data_pipeline \
        --arg data_id=data-123

To test fault tolerance:
    1. Start the workflow
    2. While it's running, kill the worker (Ctrl+C)
    3. Start a new worker
    4. Watch the workflow recover and continue from the last completed step

Check status:
    pyworkflow runs list
    pyworkflow runs status <run_id>
    pyworkflow runs logs <run_id>  # Will show WORKFLOW_INTERRUPTED events
"""

import asyncio

from pyworkflow import sleep, step, workflow


@step()
async def fetch_data(data_id: str) -> dict:
    """Fetch data from external source."""
    print(f"[Step 1] Fetching data for {data_id}...")
    await asyncio.sleep(2)  # Simulate network delay
    return {"data_id": data_id, "records": 1000, "fetched": True}


@step()
async def validate_data(data: dict) -> dict:
    """Validate the fetched data."""
    print(f"[Step 2] Validating {data['records']} records...")
    await asyncio.sleep(2)  # Simulate validation time
    return {**data, "valid_records": 950, "validated": True}


@step()
async def transform_data(data: dict) -> dict:
    """Transform data for processing."""
    print(f"[Step 3] Transforming {data['valid_records']} records...")
    await asyncio.sleep(3)  # Simulate CPU-intensive work
    return {**data, "transformed_records": 950, "transformed": True}


@step()
async def load_data(data: dict) -> dict:
    """Load transformed data into destination."""
    print(f"[Step 4] Loading {data['transformed_records']} records...")
    await asyncio.sleep(2)  # Simulate database writes
    return {**data, "loaded": True}


@step()
async def send_notification(data: dict) -> dict:
    """Send completion notification."""
    print(f"[Step 5] Sending notification for {data['data_id']}...")
    return {**data, "notified": True}


@workflow(
    recover_on_worker_loss=True,  # Enable automatic recovery (default for durable)
    max_recovery_attempts=5,  # Allow up to 5 recovery attempts
    tags=["celery", "durable"],
)
async def data_pipeline(data_id: str) -> dict:
    """
    Data processing pipeline with fault tolerance.

    This workflow demonstrates automatic recovery from worker failures:

    1. Fetch data from external source
    2. Validate the data
    3. Transform data for processing
    4. Load into destination
    5. Send completion notification

    If a worker crashes during any step:
    - The workflow will be automatically recovered by another worker
    - Already completed steps will be skipped (results from event replay)
    - Execution continues from where it left off
    - Up to 5 recovery attempts are allowed

    Test fault tolerance:
    - Kill the worker during step 3 (transform_data) which takes longest
    - Start a new worker and watch it recover
    """
    print(f"\n{'=' * 60}")
    print(f"Starting data pipeline for {data_id}")
    print(f"{'=' * 60}\n")

    data = await fetch_data(data_id)
    print(f"  -> Fetch complete: {data['records']} records\n")

    print("  [Sleeping 10s before validation - kill worker now to test recovery!]")
    await sleep("10s")

    data = await validate_data(data)
    print(f"  -> Validation complete: {data['valid_records']} valid records\n")

    print("  [Sleeping 10s before transform - kill worker now to test recovery!]")
    await sleep("10s")

    data = await transform_data(data)
    print(f"  -> Transform complete: {data['transformed_records']} records\n")

    print("  [Sleeping 10s before load - kill worker now to test recovery!]")
    await sleep("10s")

    data = await load_data(data)
    print("  -> Load complete\n")

    data = await send_notification(data)
    print("  -> Notification sent\n")

    print(f"{'=' * 60}")
    print("Pipeline completed successfully!")
    print(f"{'=' * 60}\n")

    return data


@workflow(
    recover_on_worker_loss=False,  # Disable recovery for this workflow
    max_recovery_attempts=0,
    tags=["celery", "durable"],
)
async def critical_pipeline(data_id: str) -> dict:
    """
    Critical pipeline that should NOT auto-recover.

    Some workflows should fail completely on worker loss rather than
    recover, for example when:
    - Steps have side effects that can't be safely repeated
    - Human intervention is required after failures
    - The workflow interacts with non-idempotent external systems

    If a worker crashes during this workflow:
    - The workflow will be marked as FAILED
    - No automatic recovery will be attempted
    - Manual intervention is required

    Usage:
        pyworkflow workflows run critical_pipeline --arg data_id=critical-001
    """
    print(f"[Critical] Processing {data_id} - NO AUTO-RECOVERY")

    data = await fetch_data(data_id)
    data = await validate_data(data)
    data = await transform_data(data)

    print(f"[Critical] Completed {data_id}")
    return data


async def main() -> None:
    """Run the fault tolerance example."""
    import argparse

    import pyworkflow

    parser = argparse.ArgumentParser(description="Data Pipeline with Fault Tolerance")
    parser.add_argument("--data-id", default="data-123", help="Data ID to process")
    parser.add_argument(
        "--critical",
        action="store_true",
        help="Run the critical pipeline (no auto-recovery)",
    )
    args = parser.parse_args()

    if args.critical:
        print(f"Starting CRITICAL pipeline for {args.data_id}...")
        print("NOTE: This workflow will NOT auto-recover from worker failures")
        run_id = await pyworkflow.start(critical_pipeline, args.data_id)
    else:
        print(f"Starting data pipeline for {args.data_id}...")
        print("NOTE: This workflow WILL auto-recover from worker failures")
        print("      Kill the worker during execution to test recovery")
        run_id = await pyworkflow.start(data_pipeline, args.data_id)

    print(f"\nWorkflow started with run_id: {run_id}")
    print("\nMonitor with:")
    print(f"  pyworkflow runs status {run_id}")
    print(f"  pyworkflow runs logs {run_id}")


if __name__ == "__main__":
    asyncio.run(main())
