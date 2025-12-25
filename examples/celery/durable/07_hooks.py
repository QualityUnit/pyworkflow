"""
Celery Durable Workflow - Hooks Example

This example demonstrates hooks for waiting on external events with Celery workers:
- Using hook() to suspend workflow and wait for external input
- Using define_hook() for typed hooks with Pydantic validation
- Using CLI commands to list and resume hooks
- Composite tokens (run_id:hook_id) for self-describing tokens

Prerequisites:
    1. Start Redis: docker run -d -p 6379:6379 redis:7-alpine
    2. Start worker: pyworkflow --module examples.celery.durable.07_hooks worker run

Run workflow:
    cd examples/celery/durable
    PYTHONPATH=. pyworkflow --module 07_hooks workflows run approval_workflow --arg order_id=order-123

List pending hooks:
    pyworkflow hooks list --status pending

Resume a hook (interactive):
    pyworkflow hooks resume
    # Step 1: Select the pending hook
    # Step 2: Enter payload values (approved, reviewer, comments)

Resume with explicit payload:
    pyworkflow hooks resume <token> --payload '{"approved": true, "reviewer": "admin@example.com"}'

Check workflow status:
    pyworkflow runs status <run_id>
"""

from pydantic import BaseModel

from pyworkflow import define_hook, hook, step, workflow


# --- Pydantic model for typed hook payload ---
class ApprovalPayload(BaseModel):
    """Typed payload for approval hook.

    This schema is stored with the hook and used by the CLI
    to prompt for field values interactively.
    """

    approved: bool
    reviewer: str
    comments: str | None = None


# Create typed hook - schema is stored for CLI resume
approval_hook = define_hook("manager_approval", ApprovalPayload)


# --- Steps ---
@step()
async def prepare_order(order_id: str) -> dict:
    """Prepare the order for review."""
    print(f"[Step] Preparing order {order_id}...")
    return {"order_id": order_id, "status": "pending_approval"}


@step()
async def fulfill_order(order: dict) -> dict:
    """Fulfill the approved order."""
    print(f"[Step] Fulfilling order {order['order_id']}...")
    return {**order, "status": "fulfilled"}


@step()
async def cancel_order(order: dict, reason: str) -> dict:
    """Cancel the rejected order."""
    print(f"[Step] Cancelling order {order['order_id']}: {reason}")
    return {**order, "status": "cancelled", "reason": reason}


# --- Workflow with simple hook ---
@workflow(name="simple_approval_workflow", tags=["celery", "durable"])
async def simple_approval_workflow(order_id: str) -> dict:
    """
    Workflow using simple hook() with untyped payload.

    The workflow suspends at the hook and waits for external input.
    Use `pyworkflow hooks resume` to send a payload and continue.
    """
    order = await prepare_order(order_id)

    async def on_hook_created(token: str):
        """Called when hook is created - log the token for CLI use."""
        print(f"[Hook] Created with token: {token}")
        print(
            f"[Hook] Resume with: pyworkflow hooks resume {token} --payload '{{\"approved\": true}}'"
        )

    # Wait for external approval
    # Token is auto-generated in composite format: run_id:hook_id
    approval = await hook(
        "simple_approval",
        timeout="24h",  # Expire after 24 hours
        on_created=on_hook_created,
    )

    if approval.get("approved"):
        return await fulfill_order(order)
    else:
        return await cancel_order(order, approval.get("reason", "Rejected"))


# --- Workflow with typed hook ---
@workflow(name="approval_workflow", tags=["celery", "durable"])
async def approval_workflow(order_id: str) -> dict:
    """
    Workflow using define_hook() for type-safe payloads.

    The typed hook stores its Pydantic schema, which the CLI uses
    to prompt for each field interactively during `pyworkflow hooks resume`.

    Run: pyworkflow workflows run approval_workflow --arg order_id=order-123
    Resume: pyworkflow hooks resume (interactive)
    """
    order = await prepare_order(order_id)

    async def on_hook_created(token: str):
        """Called when hook is created - log for CLI use."""
        print(f"[Hook] Typed hook created with token: {token}")
        print("[Hook] Run: pyworkflow hooks resume")
        print(
            f'[Hook] Or:  pyworkflow hooks resume {token} --payload \'{{"approved": true, "reviewer": "admin@example.com"}}\''
        )

    # Wait for typed approval - payload validated against ApprovalPayload
    # CLI will prompt for: approved (bool), reviewer (str), comments (str, optional)
    approval: ApprovalPayload = await approval_hook(
        timeout="7d",  # Expire after 7 days
        on_created=on_hook_created,
    )

    print(
        f"[Workflow] Received approval: approved={approval.approved}, reviewer={approval.reviewer}"
    )

    if approval.approved:
        return await fulfill_order(order)
    else:
        return await cancel_order(order, approval.comments or "No reason given")


# --- Workflow with multiple hooks ---
@workflow(name="multi_approval_workflow", tags=["celery", "durable"])
async def multi_approval_workflow(order_id: str) -> dict:
    """
    Workflow demonstrating sequential hooks for multi-level approval.

    This workflow requires two approvals:
    1. Manager approval
    2. Finance approval (only if amount is significant)
    """
    order = await prepare_order(order_id)

    async def log_token(name: str):
        async def _log(token: str):
            print(f"[Hook] {name} hook created: {token}")

        return _log

    # First approval: Manager
    print("[Workflow] Waiting for manager approval...")
    manager_approval = await hook(
        "manager_approval",
        timeout="24h",
        on_created=await log_token("Manager"),
    )

    if not manager_approval.get("approved"):
        return await cancel_order(
            order, f"Manager rejected: {manager_approval.get('reason', 'No reason')}"
        )

    order["manager_approved"] = True
    order["manager"] = manager_approval.get("approver", "unknown")

    # Second approval: Finance (simulating high-value order check)
    print("[Workflow] Waiting for finance approval...")
    finance_approval = await hook(
        "finance_approval",
        timeout="48h",
        on_created=await log_token("Finance"),
    )

    if not finance_approval.get("approved"):
        return await cancel_order(
            order, f"Finance rejected: {finance_approval.get('reason', 'No reason')}"
        )

    order["finance_approved"] = True
    order["finance_reviewer"] = finance_approval.get("approver", "unknown")

    return await fulfill_order(order)


async def main() -> None:
    """Run the hooks workflow example via CLI."""
    print(__doc__)
    print("\nThis example should be run with Celery workers.")
    print("See the docstring above for CLI commands.")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
