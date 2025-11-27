"""
Simple PyWorkflow Example - Guaranteed Success

A minimal example showing a successful workflow execution.
"""

import asyncio

from pyworkflow import configure_logging, sleep, start, step, workflow


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

    # Step 2: Add a small delay
    print("⏳ Waiting 1 second...")
    await sleep("1s")
    print("✓ Wait complete\n")

    # Step 3: Process the greeting
    processed = await process_data(greeting)
    print(f"✓ Step 2 complete: Processed = {processed['processed']}\n")

    # Step 4: Save the result
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


async def main():
    """Run the simple example."""
    # Configure logging (minimal output)
    configure_logging(level="WARNING", show_context=False)

    print("\n" + "="*60)
    print("PyWorkflow - Simple Example")
    print("="*60)

    # Start the workflow
    run_id = await start(greeting_workflow, name="Alice")

    print(f"\n📋 Workflow Run ID: {run_id}")
    print("\n" + "="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
