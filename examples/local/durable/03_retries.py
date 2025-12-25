"""
Durable Workflow - Automatic Retries with Suspension

This example demonstrates automatic retry behavior with workflow suspension/resumption.
- Simulates flaky external API (fails 2x, succeeds on 3rd try)
- Workflow suspends between retry attempts
- Retry events recorded in event log for audit trail
- Demonstrates manual resume after each retry delay

IMPORTANT: Manual resumption (await resume(run_id)) is ONLY for local development/CI.
In production, use Celery runtime for automatic scheduled resumption.
See examples/celery/ for production-ready distributed execution.

Run: python examples/local/durable/03_retries.py 2>/dev/null
"""

import asyncio

from pyworkflow import (
    configure,
    get_workflow_events,
    get_workflow_run,
    reset_config,
    resume,
    start,
    step,
    workflow,
)
from pyworkflow.storage import InMemoryStorageBackend

# Simulate API call counter
attempt_count = 0


# --- Steps ---
@step()
async def validate_order(order_id: str) -> dict:
    """Validate the order."""
    print(f"  Validating order {order_id}...")
    return {"order_id": order_id, "valid": True}


@step(max_retries=3, retry_delay=1)
async def call_flaky_api(order: dict) -> dict:
    """Simulate unreliable external API - fails twice then succeeds."""
    global attempt_count
    attempt_count += 1

    print(f"  Calling external API (attempt {attempt_count})...")

    if attempt_count < 3:
        # Simulate temporary failure
        raise Exception(f"API timeout - connection refused (attempt {attempt_count})")

    # Third attempt succeeds
    print(f"  ✓ API call successful on attempt {attempt_count}!")
    return {**order, "api_response": "payment_approved", "attempts": attempt_count}


@step()
async def finalize_order(order: dict) -> dict:
    """Finalize the order after successful API call."""
    print(f"  Finalizing order {order['order_id']}...")
    return {**order, "finalized": True}


# --- Workflow ---
@workflow(durable=True, tags=["local", "durable"])
async def order_workflow(order_id: str) -> dict:
    """Complete order processing with retry logic."""
    order = await validate_order(order_id)
    order = await call_flaky_api(order)  # Will retry on failure
    order = await finalize_order(order)
    return order


async def main():
    global attempt_count

    # Configure with InMemoryStorageBackend
    reset_config()
    storage = InMemoryStorageBackend()
    configure(storage=storage, default_durable=True)

    print("=== Durable Workflow - Automatic Retries with Suspension ===\n")
    print("Simulating flaky API (fails 2x, succeeds on 3rd try)...\n")

    # Reset counter
    attempt_count = 0

    # Start workflow
    print("Starting workflow...")
    run_id = await start(order_workflow, "order-789")

    # Check status after first attempt
    run = await get_workflow_run(run_id)
    print(f"\nStatus after attempt 1: {run.status.value}")

    if run.status.value == "suspended":
        print("→ Workflow suspended for retry (waiting 1 second...)")

        # Show events so far
        events = await get_workflow_events(run_id)
        print(f"\n=== Event Log (After Attempt 1) - {len(events)} events ===")
        for event in events:
            event_type = event.type.value
            attempt = event.data.get("attempt", "?")
            print(f"  {event.sequence}: {event_type} (attempt={attempt})")
            if event_type == "step_retrying":
                next_attempt = event.data.get("attempt")
                print(f"     → Will retry as attempt {next_attempt}")

        # Wait for retry delay and resume
        await asyncio.sleep(1.5)
        print("\nResuming workflow for attempt 2...")
        await resume(run_id)

        # Check status again
        run = await get_workflow_run(run_id)
        print(f"Status after attempt 2: {run.status.value}")

        if run.status.value == "suspended":
            print("→ Workflow suspended for retry again (waiting 1 second...)")

            # Wait and resume for attempt 3
            await asyncio.sleep(1.5)
            print("\nResuming workflow for attempt 3...")
            result = await resume(run_id)

            print("\n✓ Workflow completed successfully!")
            print(f"Result: {result}")

    # Final status
    run = await get_workflow_run(run_id)
    print(f"\nFinal status: {run.status.value}")

    # Show complete event log
    events = await get_workflow_events(run_id)
    print(f"\n=== Complete Event Log ({len(events)} events) ===")

    for event in events:
        event_type = event.type.value
        attempt = event.data.get("attempt", "")
        step_name = event.data.get("step_name", "")

        if attempt:
            print(f"  {event.sequence}: {event_type} (attempt={attempt}, step={step_name})")
        else:
            print(f"  {event.sequence}: {event_type}")

        if event_type == "step_failed":
            error = event.data.get("error", "")[:50]
            print(f"     Error: {error}...")
        elif event_type == "step_retrying":
            retry_after = event.data.get("retry_after")
            resume_at = event.data.get("resume_at", "")[:19]
            print(f"     Retry after: {retry_after}s, resume at: {resume_at}")

    print("\n=== Key Takeaways ===")
    print("✓ Workflow suspends between retry attempts (releases resources)")
    print("✓ Each retry requires manual resume() or automatic Celery scheduling")
    print("✓ Event log shows STEP_FAILED + STEP_RETRYING for each retry")
    print("✓ Resume restores state via event replay and continues from retry")
    print("✓ max_retries=3, retry_delay=1 (1 initial + 3 retries = 4 total attempts)")
    print(f"✓ Total attempts in this run: {attempt_count}")


if __name__ == "__main__":
    asyncio.run(main())
