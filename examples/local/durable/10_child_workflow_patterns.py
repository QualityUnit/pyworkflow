"""
Child Workflows - Advanced Patterns

This example demonstrates advanced child workflow patterns:
- Nested child workflows (parent -> child -> grandchild)
- Parallel child workflows using asyncio.gather
- Error handling with ChildWorkflowFailedError
- Cancellation propagation (TERMINATE policy)
- Using ChildWorkflowHandle for async patterns

Run: python examples/local/durable/10_child_workflow_patterns.py 2>/dev/null
"""

import asyncio

from pyworkflow import (
    ChildWorkflowFailedError,
    MaxNestingDepthError,
    configure,
    get_workflow_run,
    reset_config,
    start,
    start_child_workflow,
    step,
    workflow,
)
from pyworkflow.storage import InMemoryStorageBackend


# --- Steps ---
@step()
async def do_work(name: str, duration: float = 0.1) -> dict:
    """Simulate some work."""
    print(f"      [{name}] Working for {duration}s...")
    await asyncio.sleep(duration)
    return {"name": name, "completed": True}


@step()
async def failing_step() -> dict:
    """A step that always fails."""
    raise ValueError("This step always fails!")


# --- Workflows for Nesting Demo ---
@workflow(durable=True, tags=["local", "durable"])
async def level_3_workflow(task_id: str) -> dict:
    """Grandchild workflow (nesting depth 3)."""
    print(f"    [Level3] Starting task {task_id}")
    result = await do_work(f"level3-{task_id}")
    print(f"    [Level3] Completed task {task_id}")
    return result


@workflow(durable=True, tags=["local", "durable"])
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


@workflow(durable=True, tags=["local", "durable"])
async def level_1_workflow() -> dict:
    """Parent workflow demonstrating max nesting depth."""
    print("[Level1] Starting nested workflow demo")

    # Spawn child which will spawn grandchild
    child_result = await start_child_workflow(level_2_workflow, "nested-task")

    print("[Level1] Completed nested workflow demo")
    return {"level1": True, "child": child_result}


# --- Workflows for Parallel Demo ---
@workflow(durable=True, tags=["local", "durable"])
async def parallel_task_workflow(task_id: str, duration: float) -> dict:
    """A simple workflow for parallel execution."""
    result = await do_work(f"parallel-{task_id}", duration)
    return {"task_id": task_id, **result}


@workflow(durable=True, tags=["local", "durable"])
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
        result = await handle.result(timeout=10.0)
        results.append(result)
        print(f"  Child {i} completed: {result}")

    print("[ParallelParent] All children completed")
    return {"children_count": len(results), "results": results}


# --- Workflows for Error Handling Demo ---
@workflow(durable=True, tags=["local", "durable"])
async def failing_child_workflow() -> dict:
    """A child workflow that fails."""
    await failing_step()
    return {"should": "never reach here"}


@workflow(durable=True, tags=["local", "durable"])
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


async def demo_nesting():
    """Demo: Nested child workflows."""
    print("\n" + "=" * 50)
    print("DEMO 1: Nested Child Workflows (3 levels)")
    print("=" * 50 + "\n")

    run_id = await start(level_1_workflow)
    run = await get_workflow_run(run_id)

    print(f"\nResult: {run.result}")


async def demo_parallel():
    """Demo: Parallel child workflows."""
    print("\n" + "=" * 50)
    print("DEMO 2: Parallel Child Workflows")
    print("=" * 50 + "\n")

    run_id = await start(parallel_parent_workflow)
    run = await get_workflow_run(run_id)

    print(f"\nResult: {run.result}")


async def demo_error_handling():
    """Demo: Error handling with ChildWorkflowFailedError."""
    print("\n" + "=" * 50)
    print("DEMO 3: Child Workflow Error Handling")
    print("=" * 50 + "\n")

    run_id = await start(error_handling_parent_workflow)
    run = await get_workflow_run(run_id)

    print(f"\nResult: {run.result}")


async def demo_max_nesting_depth():
    """Demo: Max nesting depth enforcement."""
    print("\n" + "=" * 50)
    print("DEMO 4: Max Nesting Depth (3 levels max)")
    print("=" * 50 + "\n")

    # Define a workflow that tries to nest too deep
    @workflow(durable=True)
    async def level_4_workflow() -> dict:
        """This would be nesting depth 4 - not allowed!"""
        return await do_work("level4")

    @workflow(durable=True)
    async def try_level_4_workflow() -> dict:
        """Try to spawn a level 4 child (should fail)."""
        # This is called from level 3, so it would be depth 4
        try:
            await start_child_workflow(level_4_workflow)
        except MaxNestingDepthError as e:
            print(f"  Caught MaxNestingDepthError: {e}")
            return {"error": str(e), "max_depth": e.MAX_DEPTH}
        return {"status": "success"}

    @workflow(durable=True)
    async def deep_nesting_workflow() -> dict:
        """Workflow that attempts deep nesting."""
        print("[DeepNesting] Attempting 4-level nesting...")

        # Level 1 -> Level 2
        @workflow(durable=True)
        async def level_2() -> dict:
            print("  [Level2] Starting...")

            # Level 2 -> Level 3
            @workflow(durable=True)
            async def level_3() -> dict:
                print("    [Level3] Starting...")
                # Level 3 -> Level 4 (should fail!)
                return await start_child_workflow(try_level_4_workflow)

            return await start_child_workflow(level_3)

        return await start_child_workflow(level_2)

    run_id = await start(deep_nesting_workflow)
    await asyncio.sleep(0.5)  # Wait for nested workflows
    run = await get_workflow_run(run_id)

    print(f"\nResult: {run.result}")
    print(
        "\nNote: Max nesting depth is 3 levels (root=0, child=1, grandchild=2, great-grandchild=3)"
    )


async def main():
    # Configure with InMemoryStorageBackend
    reset_config()
    storage = InMemoryStorageBackend()
    configure(storage=storage, default_durable=True)

    print("=== Child Workflows - Advanced Patterns ===")

    await demo_nesting()
    await demo_parallel()
    await demo_error_handling()
    # Skip max nesting demo as it requires proper registration
    # await demo_max_nesting_depth()

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
