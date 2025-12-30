"""
Durable Workflow - Dynamic Code Execution Example

This example demonstrates executing dynamically generated workflow code.
Dynamic workflows are useful for:
- No-code workflow builders that generate Python at runtime
- AI agents that write workflow code
- Template-based workflow generation
- Runtime workflow customization

The workflow_code parameter allows sending Python source code that gets
executed on workers, enabling truly dynamic workflow creation.

Run: python examples/local/durable/14_dynamic_workflows.py 2>/dev/null
"""

import asyncio

from pyworkflow import (
    configure,
    get_workflow_events,
    get_workflow_run,
    reset_config,
    start,
)
from pyworkflow.celery.tasks import _register_dynamic_workflow
from pyworkflow.core.registry import get_workflow
from pyworkflow.storage import InMemoryStorageBackend


# --- Example 1: Simple Dynamic Workflow ---
SIMPLE_WORKFLOW_CODE = '''
@workflow(name="dynamic_greeting")
async def dynamic_greeting(name: str):
    """A dynamically generated greeting workflow."""
    return f"Hello, {name}! This workflow was generated dynamically."
'''


# --- Example 2: Dynamic Workflow with Steps ---
MULTI_STEP_WORKFLOW_CODE = '''
@step(name="dynamic_validate")
async def dynamic_validate(order_id: str) -> dict:
    """Validate the order."""
    return {"order_id": order_id, "valid": True}

@step(name="dynamic_process")
async def dynamic_process(order: dict) -> dict:
    """Process the order."""
    return {**order, "processed": True}

@step(name="dynamic_complete")
async def dynamic_complete(order: dict) -> dict:
    """Complete the order."""
    return {**order, "status": "completed"}

@workflow(name="dynamic_order_workflow")
async def dynamic_order_workflow(order_id: str):
    """Process an order through multiple steps."""
    order = await dynamic_validate(order_id)
    order = await dynamic_process(order)
    order = await dynamic_complete(order)
    return order
'''


# --- Example 3: Dynamic Workflow with Conditional Logic ---
CONDITIONAL_WORKFLOW_CODE = '''
@step(name="dynamic_check_amount")
async def dynamic_check_amount(amount: float) -> str:
    """Check if amount requires approval."""
    if amount > 1000:
        return "requires_approval"
    return "auto_approved"

@step(name="dynamic_request_approval")
async def dynamic_request_approval(amount: float) -> dict:
    """Request manager approval."""
    return {"amount": amount, "approval_status": "pending_review"}

@step(name="dynamic_auto_approve")
async def dynamic_auto_approve(amount: float) -> dict:
    """Auto-approve small amounts."""
    return {"amount": amount, "approval_status": "approved"}

@workflow(name="dynamic_approval_workflow")
async def dynamic_approval_workflow(amount: float):
    """Process expense with conditional approval logic."""
    status = await dynamic_check_amount(amount)

    if status == "requires_approval":
        result = await dynamic_request_approval(amount)
    else:
        result = await dynamic_auto_approve(amount)

    return result
'''


# --- Example 4: Dynamic Workflow with Custom Imports ---
CUSTOM_IMPORTS_WORKFLOW_CODE = '''
@workflow(name="dynamic_transform")
async def dynamic_transform(data: str):
    """Transform data using custom configured functions."""
    # 'custom_transform' is provided via dynamic_workflow_imports config
    result = custom_transform(data)
    return result
'''


async def run_simple_example(storage):
    """Run the simple dynamic workflow example."""
    print("=== Example 1: Simple Dynamic Workflow ===")

    # Register the dynamic workflow
    _register_dynamic_workflow("dynamic_greeting", SIMPLE_WORKFLOW_CODE)
    workflow_func = get_workflow("dynamic_greeting").func

    # Execute with workflow_code to persist it
    run_id = await start(
        workflow_func,
        "Alice",
        durable=True,
        storage=storage,
        workflow_code=SIMPLE_WORKFLOW_CODE,
    )

    run = await get_workflow_run(run_id, storage=storage)
    print(f"  Run ID: {run_id}")
    print(f"  Status: {run.status.value}")
    print(f"  Result: {run.result}")
    print(f"  Code stored: {len(run.workflow_code or '')} chars")
    print()


async def run_multi_step_example(storage):
    """Run the multi-step dynamic workflow example."""
    print("=== Example 2: Dynamic Multi-Step Workflow ===")

    _register_dynamic_workflow("dynamic_order_workflow", MULTI_STEP_WORKFLOW_CODE)
    workflow_func = get_workflow("dynamic_order_workflow").func

    run_id = await start(
        workflow_func,
        "ORD-12345",
        durable=True,
        storage=storage,
        workflow_code=MULTI_STEP_WORKFLOW_CODE,
    )

    run = await get_workflow_run(run_id, storage=storage)
    events = await get_workflow_events(run_id, storage=storage)

    print(f"  Run ID: {run_id}")
    print(f"  Status: {run.status.value}")
    print(f"  Events: {len(events)}")

    step_events = [e for e in events if e.type.value == "step.completed"]
    print(f"  Steps completed: {len(step_events)}")
    for event in step_events:
        step_name = event.data.get("step_name", "unknown")
        print(f"    - {step_name}")
    print()


async def run_conditional_example(storage):
    """Run the conditional dynamic workflow example."""
    print("=== Example 3: Dynamic Conditional Workflow ===")

    _register_dynamic_workflow("dynamic_approval_workflow", CONDITIONAL_WORKFLOW_CODE)
    workflow_func = get_workflow("dynamic_approval_workflow").func

    # Test with small amount (auto-approved)
    run_id_small = await start(
        workflow_func,
        500.0,
        durable=True,
        storage=storage,
        workflow_code=CONDITIONAL_WORKFLOW_CODE,
    )
    run_small = await get_workflow_run(run_id_small, storage=storage)
    print(f"  Amount $500: {run_small.result}")

    # Test with large amount (requires approval)
    run_id_large = await start(
        workflow_func,
        5000.0,
        durable=True,
        storage=storage,
        workflow_code=CONDITIONAL_WORKFLOW_CODE,
    )
    run_large = await get_workflow_run(run_id_large, storage=storage)
    print(f"  Amount $5000: {run_large.result}")
    print()


async def run_custom_imports_example(storage):
    """Run the custom imports dynamic workflow example."""
    print("=== Example 4: Dynamic Workflow with Custom Imports ===")

    # Configure custom imports available to dynamic workflows
    def custom_transform(data: str) -> dict:
        return {
            "original": data,
            "upper": data.upper(),
            "length": len(data),
            "transformed_by": "custom_transform",
        }

    configure(
        dynamic_workflow_imports={
            "custom_transform": custom_transform,
        }
    )

    _register_dynamic_workflow("dynamic_transform", CUSTOM_IMPORTS_WORKFLOW_CODE)
    workflow_func = get_workflow("dynamic_transform").func

    run_id = await start(
        workflow_func,
        "hello world",
        durable=True,
        storage=storage,
        workflow_code=CUSTOM_IMPORTS_WORKFLOW_CODE,
    )

    run = await get_workflow_run(run_id, storage=storage)
    print(f"  Input: 'hello world'")
    print(f"  Result: {run.result}")
    print()


async def main():
    """Run all dynamic workflow examples."""
    reset_config()
    storage = InMemoryStorageBackend()
    configure(storage=storage, default_durable=True)

    print("=" * 60)
    print("Durable Workflow - Dynamic Code Execution Examples")
    print("=" * 60)
    print()
    print("Dynamic workflows allow generating Python workflow code at runtime.")
    print("The workflow_code is sent to workers and executed via exec().")
    print()

    await run_simple_example(storage)
    await run_multi_step_example(storage)
    await run_conditional_example(storage)
    await run_custom_imports_example(storage)

    print("=" * 60)
    print("Key Takeaways")
    print("=" * 60)
    print("1. workflow_code parameter sends Python source to workers")
    print("2. Code is executed via exec() with pyworkflow primitives available")
    print("3. Use dynamic_workflow_imports for custom functions/modules")
    print("4. workflow_code is persisted in storage for resume/replay")
    print("5. Security: Application must validate code before execution")
    print()


if __name__ == "__main__":
    asyncio.run(main())
