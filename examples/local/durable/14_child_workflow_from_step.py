"""
Durable Workflow - Starting Child Workflows from Steps

This example demonstrates how to call start_child_workflow() from within a @step
function. This is useful when a step needs to delegate work to another workflow,
similar to the "run agent" pattern where one agent/flow spawns another.

Key concepts:
- Steps can call start_child_workflow() with wait_for_completion=False (fire-and-forget)
- wait_for_completion=True is NOT supported from steps (steps cannot suspend)
- The returned ChildWorkflowHandle lets you track or cancel the child later
- The workflow context (storage, run_id) is available inside steps automatically

Real-world use case:
    A data processing step that spawns a specialized sub-workflow to handle
    a particular data format, similar to FlowHunt's "Run Agent" step which
    starts child flows from within a step.

Run: python examples/local/durable/14_child_workflow_from_step.py 2>/dev/null
"""

import asyncio

from pyworkflow import (
    ChildWorkflowHandle,
    configure,
    get_workflow_run,
    reset_config,
    start,
    start_child_workflow,
    step,
    workflow,
)
from pyworkflow.storage import InMemoryStorageBackend


# --- Child Workflows ---
@workflow(durable=True, tags=["local", "durable"])
async def enrichment_workflow(record_id: str, source: str) -> dict:
    """Child workflow that enriches a data record from an external source."""
    result = await fetch_external_data(record_id, source)
    result = await transform_data(result)
    return result


@workflow(durable=True, tags=["local", "durable"])
async def notification_workflow(recipient: str, message: str) -> dict:
    """Child workflow that sends a notification."""
    return await send_notification(recipient, message)


# --- Steps ---
@step()
async def fetch_external_data(record_id: str, source: str) -> dict:
    """Simulate fetching data from an external API."""
    print(f"    [fetch] Fetching {record_id} from {source}...")
    return {"record_id": record_id, "source": source, "data": {"value": 42}}


@step()
async def transform_data(record: dict) -> dict:
    """Transform the fetched data."""
    print(f"    [transform] Transforming record {record['record_id']}...")
    return {**record, "transformed": True}


@step()
async def send_notification(recipient: str, message: str) -> dict:
    """Send a notification."""
    print(f"    [notify] Sending to {recipient}: {message}")
    return {"recipient": recipient, "message": message, "sent": True}


@step()
async def process_record(record_id: str) -> dict:
    """
    Process a data record - spawns a child workflow from within the step.

    This demonstrates the fire-and-forget pattern: the step starts a child
    workflow and returns immediately with a handle. The child runs independently.

    This is similar to FlowHunt's RunAgent step which starts child flows
    to delegate work to specialized agents.
    """
    print(f"  [process_record] Processing record {record_id}")

    # Fire-and-forget: start a child workflow from within this step.
    # Only wait_for_completion=False is supported from steps.
    handle: ChildWorkflowHandle = await start_child_workflow(
        enrichment_workflow,
        record_id,
        "api_v2",
        wait_for_completion=False,
    )
    print(f"  [process_record] Started enrichment child: {handle.child_run_id}")

    return {
        "record_id": record_id,
        "status": "enrichment_started",
        "enrichment_run_id": handle.child_run_id,
    }


@step()
async def process_with_notification(record_id: str, email: str) -> dict:
    """
    Process a record and also fire off a notification workflow.

    Demonstrates starting multiple child workflows from a single step.
    """
    print(f"  [process_with_notify] Processing {record_id}, notifying {email}")

    # Start enrichment child workflow
    enrich_handle: ChildWorkflowHandle = await start_child_workflow(
        enrichment_workflow,
        record_id,
        "api_v3",
        wait_for_completion=False,
    )

    # Start notification child workflow
    notify_handle: ChildWorkflowHandle = await start_child_workflow(
        notification_workflow,
        email,
        f"Processing started for {record_id}",
        wait_for_completion=False,
    )

    return {
        "record_id": record_id,
        "enrichment_run_id": enrich_handle.child_run_id,
        "notification_run_id": notify_handle.child_run_id,
        "status": "children_started",
    }


# --- Parent Workflows ---
@workflow(durable=True, tags=["local", "durable"])
async def data_pipeline_workflow(record_id: str) -> dict:
    """
    Data pipeline that processes a record.

    The process_record step internally starts a child workflow to enrich
    the data asynchronously (fire-and-forget).
    """
    print(f"[Pipeline] Starting for record {record_id}")
    result = await process_record(record_id)
    print(f"[Pipeline] Step completed: {result}")
    return result


@workflow(durable=True, tags=["local", "durable"])
async def data_pipeline_with_notifications(record_id: str, email: str) -> dict:
    """
    Data pipeline that processes a record and sends notifications.

    The step spawns multiple child workflows (enrichment + notification).
    """
    print(f"[Pipeline+Notify] Starting for record {record_id}")
    result = await process_with_notification(record_id, email)
    print(f"[Pipeline+Notify] Step completed: {result}")
    return result


async def main():
    # Configure with InMemoryStorageBackend
    reset_config()
    storage = InMemoryStorageBackend()
    configure(storage=storage, default_durable=True)

    print("=== Starting Child Workflows from Steps ===\n")

    # Example 1: Single child workflow from a step
    print("--- Example 1: Fire-and-Forget Child from Step ---")
    run_id = await start(data_pipeline_workflow, "record-001")

    # Give child workflow time to complete
    await asyncio.sleep(0.5)

    run = await get_workflow_run(run_id)
    print(f"\nParent workflow: {run_id}")
    print(f"  Status: {run.status.value}")
    print(f"  Result: {run.result}")

    # List child workflows spawned by the parent
    # NOTE: In local mode, fire-and-forget children may be cancelled by the
    # TERMINATE policy when the parent completes before the child finishes.
    # In production with Celery, children run on separate workers and complete
    # independently.
    children = await storage.get_children(run_id)
    print(f"\nChild workflows ({len(children)} total):")
    for child in children:
        child_run = await get_workflow_run(child.run_id)
        print(f"  - {child.run_id}")
        print(f"    Workflow: {child.workflow_name}")
        print(f"    Status: {child_run.status.value}")
        if child_run.result:
            print(f"    Result: {child_run.result}")

    # Example 2: Multiple child workflows from a single step
    print("\n--- Example 2: Multiple Children from a Single Step ---")
    run_id_2 = await start(
        data_pipeline_with_notifications,
        "record-002",
        "user@example.com",
    )

    await asyncio.sleep(0.5)

    run_2 = await get_workflow_run(run_id_2)
    print(f"\nParent workflow: {run_id_2}")
    print(f"  Status: {run_2.status.value}")
    print(f"  Result: {run_2.result}")

    children_2 = await storage.get_children(run_id_2)
    print(f"\nChild workflows ({len(children_2)} total):")
    for child in children_2:
        child_run = await get_workflow_run(child.run_id)
        print(f"  - {child.run_id}")
        print(f"    Workflow: {child.workflow_name}")
        print(f"    Status: {child_run.status.value}")

    print("\n=== Key Takeaways ===")
    print("1. Steps can call start_child_workflow(wait_for_completion=False)")
    print("2. The ChildWorkflowHandle allows tracking/cancelling the child")
    print("3. Multiple child workflows can be spawned from a single step")
    print("4. Child workflows have their own run_id and event history")
    print("5. In Celery mode, wait_for_completion=True raises RuntimeError from steps")
    print("6. This pattern is ideal for 'run agent' or 'delegate work' use cases")
    print("\nNote: In local mode, fire-and-forget children may be cancelled by the")
    print("TERMINATE policy when the parent completes. With Celery, children run")
    print("on separate workers and complete independently.")


if __name__ == "__main__":
    asyncio.run(main())
