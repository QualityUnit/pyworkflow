"""
Celery Durable Workflow - Using sleep() Inside Steps

This example demonstrates how sleep() behaves when called from within a @step
function during distributed Celery execution. Inside a step, sleep() falls back
to asyncio.sleep() rather than suspending the workflow durably.

Key concepts:
- sleep() inside a step uses asyncio.sleep() (non-durable, blocks the worker)
- The Celery worker holds the task slot during the delay
- Useful for rate limiting, backoff, and short delays within step execution
- Duration format strings ("5s", "2m") work the same way

When to use sleep() in a step:
- Rate limiting between API calls within a single step
- Polling with backoff (e.g., check job status every N seconds)
- Brief pauses between batch operations

When NOT to use sleep() in a step:
- Long delays (minutes/hours) - use workflow-level sleep instead
- Waiting for external events - use hooks at the workflow level

Prerequisites:
    1. Start Redis: docker run -d -p 6379:6379 redis:7-alpine
    2. Start worker: pyworkflow --module examples.celery.durable.workflows.sleep_in_step worker run

Run with CLI:
    pyworkflow --module examples.celery.durable.workflows.sleep_in_step workflows run \
        rate_limited_workflow --arg endpoint=https://api.example.com/data

    pyworkflow --module examples.celery.durable.workflows.sleep_in_step workflows run \
        polling_workflow --arg job_id=job-abc-123

    pyworkflow --module examples.celery.durable.workflows.sleep_in_step workflows run \
        batch_workflow

Check status:
    pyworkflow runs list
    pyworkflow runs status <run_id>
    pyworkflow runs logs <run_id>
"""

from pyworkflow import (
    sleep,
    step,
    workflow,
)


# --- Steps ---
@step(name="sleep_step_rate_limited_api")
async def rate_limited_api_call(endpoint: str, batch: list[str]) -> dict:
    """
    Make API calls with rate limiting between each request.

    Uses sleep() for rate limiting. Inside a step, sleep() falls back to
    asyncio.sleep() on the Celery worker. The worker holds the task slot
    during the delay.
    """
    results = []
    for i, item in enumerate(batch):
        # Simulate API call
        print(f"[Step:api] API call to {endpoint}: {item}")
        results.append({"item": item, "status": "ok"})

        # Rate limit: wait between API calls (except after the last one)
        if i < len(batch) - 1:
            print("[Step:api] Rate limiting: sleeping 1s...")
            await sleep("1s")  # Uses asyncio.sleep() inside a step

    return {"endpoint": endpoint, "results": results, "count": len(results)}


@step(name="sleep_step_poll_job")
async def poll_job_status(job_id: str) -> dict:
    """
    Poll for job completion with exponential backoff.

    Demonstrates using sleep() for polling intervals within a step.
    The delay doubles on each attempt (0.5s, 1s, 2s, 4s...).
    """
    max_attempts = 4
    base_delay = 0.5

    for attempt in range(1, max_attempts + 1):
        # Simulate checking job status
        is_done = attempt >= 3  # Completes on 3rd attempt
        status = "completed" if is_done else "running"
        print(f"[Step:poll] Attempt {attempt}/{max_attempts}: {status}")

        if is_done:
            return {"job_id": job_id, "status": "completed", "attempts": attempt}

        # Exponential backoff using sleep()
        delay = base_delay * (2 ** (attempt - 1))
        print(f"[Step:poll] Backing off: sleeping {delay}s...")
        await sleep(delay)

    return {"job_id": job_id, "status": "timeout", "attempts": max_attempts}


@step(name="sleep_step_batch_processor")
async def batch_processor(items: list[str]) -> dict:
    """
    Process items in batches with a pause between each batch.

    Demonstrates using sleep() for pacing batch operations on the worker.
    """
    batch_size = 2
    processed = []

    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        print(f"[Step:batch] Processing batch {i // batch_size + 1}: {batch}")
        processed.extend(batch)

        # Pause between batches (except after last batch)
        if i + batch_size < len(items):
            print("[Step:batch] Pausing 1s between batches...")
            await sleep("1s")

    return {"processed": processed, "total": len(processed)}


# --- Workflows ---
@workflow(tags=["celery", "durable"])
async def rate_limited_workflow(endpoint: str) -> dict:
    """Workflow that makes rate-limited API calls within a step."""
    print(f"[Workflow:rate_limit] Starting API calls to {endpoint}")
    result = await rate_limited_api_call(
        endpoint,
        ["item-A", "item-B", "item-C"],
    )
    print(f"[Workflow:rate_limit] Completed: {result['count']} calls made")
    return result


@workflow(tags=["celery", "durable"])
async def polling_workflow(job_id: str) -> dict:
    """Workflow that polls for job completion with backoff."""
    print(f"[Workflow:poll] Starting to poll job {job_id}")
    result = await poll_job_status(job_id)
    print(f"[Workflow:poll] Final: {result['status']} after {result['attempts']} attempts")
    return result


@workflow(tags=["celery", "durable"])
async def batch_workflow() -> dict:
    """Workflow that processes items in batches with pauses."""
    print("[Workflow:batch] Starting batch processing")
    items = ["doc-1", "doc-2", "doc-3", "doc-4", "doc-5"]
    result = await batch_processor(items)
    print(f"[Workflow:batch] Processed {result['total']} items")
    return result


# --- Main for direct execution ---
async def main() -> None:
    """Run the sleep-in-step example."""
    import argparse
    import asyncio

    import pyworkflow
    from pyworkflow import get_workflow_run

    parser = argparse.ArgumentParser(description="Sleep in Step Example")
    parser.add_argument(
        "--demo",
        choices=["rate_limit", "poll", "batch", "all"],
        default="all",
        help="Which demo to run",
    )
    args = parser.parse_args()

    demos = []
    if args.demo in ("rate_limit", "all"):
        demos.append(
            (
                "Rate-Limited API Calls",
                rate_limited_workflow,
                {"endpoint": "https://api.example.com/data"},
            )
        )
    if args.demo in ("poll", "all"):
        demos.append(
            (
                "Polling with Exponential Backoff",
                polling_workflow,
                {"job_id": "job-abc-123"},
            )
        )
    if args.demo in ("batch", "all"):
        demos.append(
            (
                "Batch Processing with Pauses",
                batch_workflow,
                {},
            )
        )

    for demo_name, workflow_func, kwargs in demos:
        print(f"\n{'=' * 50}")
        print(f"DEMO: {demo_name}")
        print("=" * 50 + "\n")

        run_id = await pyworkflow.start(workflow_func, **kwargs)
        print(f"Workflow started: {run_id}")

        # Poll for completion
        for _ in range(30):
            await asyncio.sleep(1)
            run = await get_workflow_run(run_id)
            if run.status.value in ("completed", "failed", "cancelled"):
                print(f"Status: {run.status.value}")
                if run.result:
                    print(f"Result: {run.result}")
                if run.error:
                    print(f"Error: {run.error}")
                break
        else:
            print("Timeout waiting for workflow completion")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
