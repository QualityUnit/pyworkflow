"""
Simple PyWorkflow Example - No Sleep

A minimal example showing distributed workflow execution.

Prerequisites:
    1. Start Redis: docker run -d -p 6379:6379 redis:7-alpine
    2. Start Celery worker: celery -A pyworkflow.celery.app worker --loglevel=info

Or use Docker Compose:
    docker-compose up -d
"""

import asyncio

from pyworkflow import configure_logging, start, step, workflow


@step()
async def greet_user(name: str) -> str:
    """Greet the user."""
    print(f"👋 Greeting user: {name}")
    await asyncio.sleep(0.1)  # Simulate work
    return f"Hello, {name}!"


@step()
async def process_data(greeting: str) -> dict:
    """Process the greeting data."""
    print(f"⚙️  Processing: {greeting}")
    await asyncio.sleep(0.1)
    return {
        "message": greeting,
        "processed": True,
        "timestamp": "2025-11-28",
    }


@step()
async def save_result(data: dict) -> str:
    """Save the result."""
    print(f"💾 Saving result: {data['message']}")
    await asyncio.sleep(0.1)
    return f"Saved: {data['message']}"


@workflow(name="simple_greeting_workflow")
async def greeting_workflow(name: str) -> dict:
    """
    A simple workflow that greets a user and processes the result.

    Args:
        name: User's name

    Returns:
        Final result dictionary
    """
    print(f"\n{'='*60}")
    print(f"🚀 Starting workflow for: {name}")
    print(f"{'='*60}\n")

    # Step 1: Greet the user
    greeting = await greet_user(name)
    print(f"✓ Step 1 complete: {greeting}\n")

    # Step 2: Process the greeting
    processed = await process_data(greeting)
    print(f"✓ Step 2 complete: Processed = {processed['processed']}\n")

    # Step 3: Save the result
    saved = await save_result(processed)
    print(f"✓ Step 3 complete: {saved}\n")

    result = {
        "workflow": "simple_greeting_workflow",
        "input": name,
        "greeting": greeting,
        "saved": saved,
        "status": "completed",
    }

    print(f"{'='*60}")
    print(f"✅ Workflow completed successfully!")
    print(f"{'='*60}\n")

    return result


def main():
    """Run the simple example."""
    # Configure logging (minimal output)
    configure_logging(level="WARNING", show_context=False)

    print("\n" + "="*60)
    print("PyWorkflow - Simple Distributed Example")
    print("="*60)
    print("\n✅ Workflows execute across Celery workers")
    print("   Steps can run on different machines for horizontal scaling\n")

    # Start the workflow - executes on Celery workers
    run_id = start(greeting_workflow, name="Alice")

    print(f"\n📋 Workflow Run ID: {run_id}")
    print("🔄 Workflow is running on Celery workers...")
    print("   Check the Celery worker logs to see step execution!\n")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
