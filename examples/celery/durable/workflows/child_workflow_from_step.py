"""
Celery Durable Workflow - Starting Child Workflows from Steps

This example demonstrates how to call start_child_workflow() from within a @step
function during distributed Celery execution. This is useful when a step needs to
delegate work to another workflow, similar to the "run agent" pattern.

Key concepts:
- Steps can call start_child_workflow(wait_for_completion=False) to fire-and-forget
- wait_for_completion=True is NOT supported from steps (steps cannot suspend)
- The ChildWorkflowHandle returned lets you track or cancel the child
- Workflow context (storage, run_id) is automatically available in step workers

Real-world use case:
    A data processing step (like FlowHunt's RunAgent) that spawns a specialized
    child workflow to handle sub-tasks, then returns the handle for tracking.

Prerequisites:
    1. Start Redis: docker run -d -p 6379:6379 redis:7-alpine
    2. Start worker: pyworkflow --module examples.celery.durable.workflows.child_workflow_from_step worker run

Run with CLI:
    pyworkflow --module examples.celery.durable.workflows.child_workflow_from_step workflows run \
        data_pipeline_workflow --arg record_id=record-001

    pyworkflow --module examples.celery.durable.workflows.child_workflow_from_step workflows run \
        data_pipeline_with_notifications --arg record_id=record-002 --arg email=user@example.com

Check status:
    pyworkflow runs list
    pyworkflow runs status <run_id>
    pyworkflow runs children <run_id>
"""

from pyworkflow import (
    ChildWorkflowHandle,
    start_child_workflow,
    step,
    workflow,
)


# --- Child Workflows ---
@workflow(name="step_child_enrichment_workflow", tags=["celery", "durable"])
async def enrichment_workflow(record_id: str, source: str) -> dict:
    """Child workflow that enriches a data record from an external source."""
    result = await fetch_external_data(record_id, source)
    result = await transform_data(result)
    return result


@workflow(name="step_child_notification_workflow", tags=["celery", "durable"])
async def notification_workflow(recipient: str, message: str) -> dict:
    """Child workflow that sends a notification."""
    return await send_notification_step(recipient, message)


# --- Steps ---
@step(name="step_child_fetch_external_data")
async def fetch_external_data(record_id: str, source: str) -> dict:
    """Fetch data from an external API."""
    print(f"[Step:fetch] Fetching {record_id} from {source}...")
    return {"record_id": record_id, "source": source, "data": {"value": 42}}


@step(name="step_child_transform_data")
async def transform_data(record: dict) -> dict:
    """Transform the fetched data."""
    print(f"[Step:transform] Transforming record {record['record_id']}...")
    return {**record, "transformed": True}


@step(name="step_child_send_notification")
async def send_notification_step(recipient: str, message: str) -> dict:
    """Send a notification."""
    print(f"[Step:notify] Sending to {recipient}: {message}")
    return {"recipient": recipient, "message": message, "sent": True}


@step(name="step_child_process_record")
async def process_record(record_id: str) -> dict:
    """
    Process a data record - spawns a child workflow from within the step.

    This demonstrates the fire-and-forget pattern: the step starts a child
    workflow and returns immediately with a handle. The child runs on its
    own Celery task independently.

    Similar to FlowHunt's RunAgent step which starts child flows to
    delegate work to specialized agents.
    """
    print(f"[Step:process] Processing record {record_id}")

    # Fire-and-forget: start a child workflow from within this step.
    # Only wait_for_completion=False is supported from steps.
    handle: ChildWorkflowHandle = await start_child_workflow(
        enrichment_workflow,
        record_id,
        "api_v2",
        wait_for_completion=False,
    )
    print(f"[Step:process] Started enrichment child: {handle.child_run_id}")

    return {
        "record_id": record_id,
        "status": "enrichment_started",
        "enrichment_run_id": handle.child_run_id,
    }


@step(name="step_child_process_with_notify")
async def process_with_notification(record_id: str, email: str) -> dict:
    """
    Process a record and fire off a notification workflow.

    Demonstrates starting multiple child workflows from a single step.
    """
    print(f"[Step:process+notify] Processing {record_id}, notifying {email}")

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
@workflow(tags=["celery", "durable"])
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


@workflow(tags=["celery", "durable"])
async def data_pipeline_with_notifications(record_id: str, email: str) -> dict:
    """
    Data pipeline that processes a record and sends notifications.

    The step spawns multiple child workflows (enrichment + notification).
    """
    print(f"[Pipeline+Notify] Starting for record {record_id}")
    result = await process_with_notification(record_id, email)
    print(f"[Pipeline+Notify] Step completed: {result}")
    return result


# --- Main for direct execution ---
async def main() -> None:
    """Run the child workflow from step example."""
    import argparse
    import asyncio

    import pyworkflow
    from pyworkflow import get_workflow_run

    parser = argparse.ArgumentParser(description="Child Workflow from Step Example")
    parser.add_argument("--record-id", default="record-001", help="Record ID")
    parser.add_argument("--email", default=None, help="Email for notification demo")
    args = parser.parse_args()

    if args.email:
        print("Starting data pipeline with notifications...")
        run_id = await pyworkflow.start(
            data_pipeline_with_notifications,
            record_id=args.record_id,
            email=args.email,
        )
    else:
        print("Starting data pipeline...")
        run_id = await pyworkflow.start(
            data_pipeline_workflow,
            record_id=args.record_id,
        )

    print(f"Workflow started with run_id: {run_id}")
    print(f"\nCheck status: pyworkflow runs status {run_id}")
    print(f"View children: pyworkflow runs children {run_id}")

    # Poll for completion
    print("\nWaiting for workflow to complete...")
    for _ in range(30):
        await asyncio.sleep(1)
        run = await get_workflow_run(run_id)
        if run.status.value in ("completed", "failed", "cancelled"):
            print(f"\nWorkflow {run.status.value}!")
            if run.result:
                print(f"Result: {run.result}")
            if run.error:
                print(f"Error: {run.error}")
            break
    else:
        print("\nTimeout waiting for workflow completion")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
