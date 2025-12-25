"""
Transient Workflow - Retry Mechanics

This example demonstrates inline retry behavior in transient mode.
- Shows @step(max_retries=...) in action
- Simulates flaky API (fails 2x, succeeds on 3rd try)
- Retry logic works without event sourcing
- Global counter tracks retry attempts

Run: python examples/local/transient/02_retries.py 2>/dev/null
"""

import asyncio

from pyworkflow import (
    FatalError,
    configure,
    reset_config,
    start,
    step,
    workflow,
)

# Global counter to track API call attempts
attempt_count = 0


# --- Steps ---
@step()
async def validate_request(request_id: str) -> dict:
    """Validate the request."""
    print(f"  Validating request {request_id}...")
    return {"request_id": request_id, "valid": True}


@step(max_retries=3, retry_delay=1)
async def call_flaky_api(request: dict) -> dict:
    """Simulate unreliable external API - fails twice then succeeds."""
    global attempt_count
    attempt_count += 1

    print(f"  Calling external API (attempt {attempt_count})...")

    if attempt_count < 3:
        # Simulate temporary failure
        print("    ✗ API call failed (timeout)")
        raise Exception(f"API timeout - connection refused (attempt {attempt_count})")

    # Third attempt succeeds
    print("    ✓ API call successful!")
    return {**request, "api_response": "success", "attempts": attempt_count}


@step()
async def process_response(request: dict) -> dict:
    """Process the successful API response."""
    print(f"  Processing API response for {request['request_id']}...")
    return {**request, "processed": True}


@step()
async def validate_input(value: int) -> int:
    """Validate input - demonstrates FatalError (no retry)."""
    if value < 0:
        raise FatalError("Negative values not allowed")
    return value


# --- Workflows ---
@workflow(durable=False, tags=["local", "transient"])
async def api_workflow(request_id: str) -> dict:
    """Workflow with automatic retry logic."""
    request = await validate_request(request_id)
    request = await call_flaky_api(request)  # Will retry on failure
    request = await process_response(request)
    return request


@workflow(durable=False, tags=["local", "transient"])
async def validation_workflow(value: int) -> int:
    """Workflow with fatal error (no retry)."""
    return await validate_input(value)


async def main():
    global attempt_count

    # Configure for transient mode
    reset_config()
    configure(default_durable=False)

    print("=== Transient Workflow - Retry Mechanics ===\n")

    # Example 1: Successful retry
    print("Example 1: API call with retries\n")
    attempt_count = 0  # Reset counter

    run_id = await start(api_workflow, "request-123")
    print(f"\nWorkflow completed: {run_id}")
    print(f"Total attempts: {attempt_count}")

    # Example 2: FatalError (no retry)
    print("\n" + "=" * 60)
    print("\nExample 2: FatalError (no retry)\n")

    try:
        await start(validation_workflow, -5)
    except FatalError as e:
        print(f"✗ Workflow failed with FatalError: {e}")
        print("  (No retries attempted)")

    print("\n=== Retry Behavior ===")
    print("✓ max_retries=3 means: 1 initial + 3 retries = 4 total attempts")
    print("✓ retry_delay=1 adds 1 second delay between retries")
    print("✓ Retries happen inline (no event log needed)")
    print("✓ FatalError skips retries and fails immediately")

    print("\n=== Error Types ===")
    print("Exception           - Will retry if max_retries > 0")
    print("FatalError          - Never retries, fails immediately")
    print("RetryableError      - Will retry (same as Exception)")

    print("\n=== Difference from Durable Mode ===")
    print("Transient: Retries happen inline, not recorded")
    print("Durable:   Retries recorded in event log for audit")
    print("\nSee examples/local/durable/03_retries.py for comparison")


if __name__ == "__main__":
    asyncio.run(main())
