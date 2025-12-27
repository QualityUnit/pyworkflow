"""
Celery Durable Workflow - Child Workflows Advanced Patterns

This example demonstrates advanced child workflow patterns:
- Nested child workflows (parent -> child -> grandchild)
- Parallel child workflows using fire-and-forget + handle.result()
- Error handling with ChildWorkflowFailedError
- Cancellation propagation (TERMINATE policy)
- Using ChildWorkflowHandle for async patterns

Prerequisites:
    1. Start Redis: docker run -d -p 6379:6379 redis:7-alpine
    2. Start worker: pyworkflow --module examples.celery.durable.10_child_workflow_patterns worker run

Run demos with CLI:
    # Nested workflows (3 levels)
    pyworkflow --module examples.celery.durable.10_child_workflow_patterns workflows run level_1_workflow

    # Parallel children
    pyworkflow --module examples.celery.durable.10_child_workflow_patterns workflows run parallel_parent_workflow

    # Error handling
    pyworkflow --module examples.celery.durable.10_child_workflow_patterns workflows run error_handling_parent_workflow

Check status:
    pyworkflow runs list
    pyworkflow runs status <run_id>
    pyworkflow runs children <run_id>
"""

import asyncio

from pyworkflow import (
    ChildWorkflowFailedError,
    MaxNestingDepthError,
    start_child_workflow,
    step,
    workflow,
)


# --- Steps ---
@step(name="patterns_demo_do_work")
async def do_work(name: str, duration: float = 0.1) -> dict:
    """Simulate some work."""
    print(f"      [{name}] Working for {duration}s...")
    await asyncio.sleep(duration)
    return {"name": name, "completed": True}


@step(
    name="patterns_demo_failing_step", max_retries=0
)  # No retries so failure propagates immediately
async def failing_step() -> dict:
    """A step that always fails."""
    raise ValueError("This step always fails!")


# --- Workflows for Nesting Demo ---
@workflow(name="patterns_demo_level_3_workflow", tags=["celery", "durable"])
async def level_3_workflow(task_id: str) -> dict:
    """Grandchild workflow (nesting depth 3)."""
    print(f"    [Level3] Starting task {task_id}")
    result = await do_work(f"level3-{task_id}")
    print(f"    [Level3] Completed task {task_id}")
    return result


@workflow(name="patterns_demo_level_2_workflow", tags=["celery", "durable"])
async def level_2_workflow(task_id: str) -> dict:
    """Child workflow that spawns a grandchild."""
    print(f"  [Level2] Starting task {task_id}")

    # Spawn grandchild (nesting depth 3)
    grandchild_result = await start_child_workflow(
        level_3_workflow,
        task_id,
    )

    print(f"  [Level2] Completed task {task_id}")
    return {"level2": task_id, "grandchild": grandchild_result}


@workflow(name="patterns_demo_level_1_workflow", tags=["celery", "durable"])
async def level_1_workflow() -> dict:
    """Parent workflow demonstrating max nesting depth."""
    print("[Level1] Starting nested workflow demo")

    # Spawn child which will spawn grandchild
    child_result = await start_child_workflow(level_2_workflow, "nested-task")

    print("[Level1] Completed nested workflow demo")
    return {"level1": True, "child": child_result}


# --- Workflows for Parallel Demo ---
@workflow(name="patterns_demo_parallel_task_workflow", tags=["celery", "durable"])
async def parallel_task_workflow(task_id: str, duration: float) -> dict:
    """A simple workflow for parallel execution."""
    result = await do_work(f"parallel-{task_id}", duration)
    return {"task_id": task_id, **result}


@workflow(name="patterns_demo_parallel_parent_workflow", tags=["celery", "durable"])
async def parallel_parent_workflow() -> dict:
    """Parent workflow that runs multiple children in parallel."""
    print("[ParallelParent] Starting parallel children demo")

    # Start multiple children with fire-and-forget
    handles = []
    for i in range(3):
        handle = await start_child_workflow(
            parallel_task_workflow,
            f"task-{i}",
            0.1 * (i + 1),  # Different durations
            wait_for_completion=False,
        )
        handles.append(handle)
        print(f"  Started child {i}: {handle.child_run_id}")

    # Wait for all children to complete using handles
    print("[ParallelParent] Waiting for all children...")
    results = []
    for i, handle in enumerate(handles):
        result = await handle.result(timeout=30.0)
        results.append(result)
        print(f"  Child {i} completed: {result}")

    print("[ParallelParent] All children completed")
    return {"children_count": len(results), "results": results}


# --- Workflows for Error Handling Demo ---
@workflow(name="patterns_demo_failing_child_workflow", tags=["celery", "durable"])
async def failing_child_workflow() -> dict:
    """A child workflow that fails."""
    await failing_step()
    return {"should": "never reach here"}


@workflow(name="patterns_demo_error_handling_parent_workflow", tags=["celery", "durable"])
async def error_handling_parent_workflow() -> dict:
    """Parent workflow demonstrating error handling."""
    print("[ErrorParent] Starting error handling demo")

    try:
        # This child will fail
        await start_child_workflow(failing_child_workflow)
    except ChildWorkflowFailedError as e:
        print("[ErrorParent] Caught child failure!")
        print(f"  Child run_id: {e.child_run_id}")
        print(f"  Child workflow: {e.child_workflow_name}")
        print(f"  Error: {e.error}")
        print(f"  Error type: {e.error_type}")
        return {
            "status": "child_failed",
            "error": e.error,
            "child_run_id": e.child_run_id,
        }

    return {"status": "success"}


# --- Workflow for Max Nesting Depth Demo ---
@workflow(name="patterns_demo_try_exceed_max_depth", tags=["celery", "durable"])
async def try_exceed_max_depth() -> dict:
    """Try to exceed max nesting depth (should fail at depth 4)."""
    try:
        # Define a workflow that would be depth 4
        @workflow(name="patterns_demo_level_4_workflow")
        async def level_4_workflow() -> dict:
            return await do_work("level4")

        await start_child_workflow(level_4_workflow)
    except MaxNestingDepthError as e:
        print(f"  Caught MaxNestingDepthError: {e}")
        return {"error": str(e), "max_depth": e.MAX_DEPTH}
    return {"status": "success"}


async def main() -> None:
    """Run the child workflow patterns demos."""
    import argparse

    import pyworkflow
    from pyworkflow import get_workflow_run

    parser = argparse.ArgumentParser(description="Child Workflow Patterns Demo")
    parser.add_argument(
        "--demo",
        choices=["nested", "parallel", "error", "all"],
        default="all",
        help="Which demo to run",
    )
    args = parser.parse_args()

    print("=== Child Workflows - Advanced Patterns ===")

    demos = []
    if args.demo in ("nested", "all"):
        demos.append(("Nested Child Workflows (3 levels)", level_1_workflow))
    if args.demo in ("parallel", "all"):
        demos.append(("Parallel Child Workflows", parallel_parent_workflow))
    if args.demo in ("error", "all"):
        demos.append(("Child Workflow Error Handling", error_handling_parent_workflow))

    for demo_name, workflow_func in demos:
        print(f"\n{'=' * 50}")
        print(f"DEMO: {demo_name}")
        print("=" * 50 + "\n")

        run_id = await pyworkflow.start(workflow_func)
        print(f"\nWorkflow started: {run_id}")

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

    print("\n" + "=" * 50)
    print("=== Key Takeaways ===")
    print("=" * 50)
    print("1. Child workflows can spawn their own children (up to depth 3)")
    print("2. Use wait_for_completion=False + handle.result() for parallel")
    print("3. ChildWorkflowFailedError propagates child failures to parent")
    print("4. MaxNestingDepthError prevents infinite nesting")
    print("5. TERMINATE policy ensures cleanup on parent completion")


if __name__ == "__main__":
    asyncio.run(main())
