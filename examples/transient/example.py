"""
Transient Workflow Example

Transient mode (durable=False) executes workflows directly without persistence.
- No storage required
- Fast execution
- Retries work inline
- Sleep uses asyncio.sleep directly
- No crash recovery

Run: python examples/transient/example.py 2>/dev/null
"""

import asyncio

from pyworkflow import (
    FatalError,
    configure,
    reset_config,
    sleep,
    start,
    step,
    workflow,
)


# --- Configuration ---
reset_config()
configure(default_durable=False)


# --- Steps ---
@step()
async def process_order(order_id: str) -> dict:
    return {"order_id": order_id, "status": "processed"}


attempt_count = 0

@step(max_retries=3, retry_delay=1)
async def call_flaky_api(order: dict) -> dict:
    """Simulates unreliable API - fails twice then succeeds."""
    global attempt_count
    attempt_count += 1
    if attempt_count < 3:
        raise Exception(f"API timeout (attempt {attempt_count})")
    return {**order, "api_response": "success"}


@step()
async def charge_payment(order: dict, amount: float) -> dict:
    return {**order, "charged": amount}


@step()
async def validate_input(value: int) -> int:
    if value < 0:
        raise FatalError("Negative values not allowed")
    return value


# --- Workflows ---
@workflow(durable=False)
async def order_workflow(order_id: str, amount: float) -> dict:
    order = await process_order(order_id)
    order = await call_flaky_api(order)  # Will retry on failure
    await sleep("1s")  # Uses asyncio.sleep directly
    order = await charge_payment(order, amount)
    return order


@workflow(durable=False)
async def validation_workflow(value: int) -> int:
    return await validate_input(value)


async def main():
    # Workflow with retries and sleep
    print("Running order workflow (with retries)...")
    run_id = await start(order_workflow, "order_123", 99.99)
    print(f"Completed: {run_id}")

    # FatalError stops immediately
    print("\nRunning validation with invalid input...")
    try:
        await start(validation_workflow, -5)
    except FatalError as e:
        print(f"Failed as expected: {e}")


if __name__ == "__main__":
    asyncio.run(main())
