"""
Basic PyWorkflow Example

This example demonstrates the fundamental concepts of PyWorkflow:
- Defining workflows with @workflow decorator
- Creating steps with @step decorator
- Distributed execution across Celery workers
- Using sleep for delays with automatic resumption
- Error handling and retries

Prerequisites:
    1. Start Redis: docker run -d -p 6379:6379 redis:7-alpine
    2. Start Celery worker: celery -A pyworkflow.celery.app worker --loglevel=info
    3. Start Celery Beat: celery -A pyworkflow.celery.app beat --loglevel=info

Or use Docker Compose:
    docker-compose up -d
"""

import asyncio

from pyworkflow import (
    FatalError,
    RetryableError,
    configure_logging,
    sleep,
    start,
    step,
    workflow,
)


@step(max_retries=3, retry_delay="exponential")
async def fetch_user_data(user_id: int) -> dict:
    """
    Fetch user data from an external API.

    This step demonstrates:
    - Automatic retry on failure
    - Exponential backoff retry strategy
    """
    print(f"Fetching data for user {user_id}")

    # Simulate API call
    await asyncio.sleep(0.5)

    # Simulate occasional failures for demonstration
    import random

    if random.random() < 0.3:  # 30% chance of failure
        raise RetryableError("API temporarily unavailable")

    return {
        "user_id": user_id,
        "name": "Alice Johnson",
        "email": "alice@example.com",
        "credits": 100,
    }


@step()
async def validate_user(user_data: dict) -> dict:
    """
    Validate user data.

    This step demonstrates:
    - Simple step without custom retry configuration
    - Fatal errors (non-retriable)
    """
    print(f"Validating user {user_data['name']}")

    if user_data["credits"] < 0:
        # Fatal error - won't retry
        raise FatalError("User has negative credits")

    return user_data


@step()
async def process_payment(user_data: dict, amount: float) -> dict:
    """
    Process payment for the user.

    This step demonstrates:
    - Working with multiple arguments
    - Returning structured data
    """
    print(f"Processing payment of ${amount} for {user_data['name']}")

    # Simulate payment processing
    await asyncio.sleep(0.3)

    new_credits = user_data["credits"] - amount
    return {
        **user_data,
        "credits": new_credits,
        "last_payment": amount,
    }


@step()
async def send_confirmation(user_data: dict) -> str:
    """Send confirmation email to user."""
    print(f"Sending confirmation to {user_data['email']}")

    # Simulate email sending
    await asyncio.sleep(0.2)

    return f"Confirmation sent to {user_data['email']}"


@workflow(name="user_order_workflow", max_duration="1h")
async def process_user_order(user_id: int, amount: float) -> dict:
    """
    Process a user order workflow.

    This workflow demonstrates:
    - Sequential step execution
    - Passing data between steps
    - Using sleep for delays
    - Deterministic execution (same inputs = same outputs)

    Args:
        user_id: User identifier
        amount: Payment amount

    Returns:
        Final workflow result with user data and confirmation
    """
    print(f"\n=== Starting order workflow for user {user_id} ===\n")

    # Step 1: Fetch user data
    user_data = await fetch_user_data(user_id)
    print(f"✓ Fetched user data: {user_data['name']}")

    # Step 2: Validate user
    validated_user = await validate_user(user_data)
    print(f"✓ User validated")

    # Step 3: Wait before processing payment (simulate rate limiting)
    print(f"Waiting 2 seconds before payment...")
    await sleep("2s")
    print(f"✓ Wait completed")

    # Step 4: Process payment
    payment_result = await process_payment(validated_user, amount)
    print(f"✓ Payment processed. New credits: {payment_result['credits']}")

    # Step 5: Send confirmation
    confirmation = await send_confirmation(payment_result)
    print(f"✓ {confirmation}")

    result = {
        "user": payment_result,
        "confirmation": confirmation,
        "status": "completed",
    }

    print(f"\n=== Order workflow completed ===\n")
    return result


def main():
    """Run the example workflow."""
    # Configure logging
    configure_logging(level="INFO", show_context=False)

    print("=" * 60)
    print("PyWorkflow - Distributed Workflow Example")
    print("=" * 60)
    print("\n✅ This workflow executes across Celery workers")
    print("   Steps can run on different machines")
    print("   Sleep automatically resumes via Celery Beat\n")

    # Start the workflow - executes on Celery workers
    print("1. Starting workflow...")
    run_id = start(
        process_user_order,
        user_id=12345,
        amount=25.0,
        idempotency_key="order-12345-unique",
    )

    print(f"\n✓ Workflow started with run_id: {run_id}")
    print("🔄 Workflow is running on Celery workers...")
    print("   Check the Celery worker logs to see:")
    print("   - Step execution across workers")
    print("   - Automatic retry on failures")
    print("   - Automatic resumption after 2-second sleep")

    print("\n" + "=" * 60)
    print("Workflow submitted! Monitor via Celery worker logs.")
    print("=" * 60)


if __name__ == "__main__":
    main()
