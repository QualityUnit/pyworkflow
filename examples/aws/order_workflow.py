"""
AWS Durable Lambda Functions - Implicit Context Workflow

This example shows a workflow running on AWS Lambda with
Durable Functions using implicit context. The workflow code
accesses context via get_context().

Deployment:
    1. pip install pyworkflow[aws]
    2. Package and deploy to Lambda
    3. Enable Durable Functions
    4. Handler: order_workflow.handler

Local Testing:
    python examples/aws/order_workflow.py
"""

import asyncio
from typing import Any, Dict

from pyworkflow.context import MockContext, get_context


# =============================================================================
# STEP FUNCTIONS - Pure functions, no decorators
# =============================================================================


async def validate_order(order_id: str) -> Dict[str, Any]:
    """Validate the order exists and is processable."""
    print(f"  [step] Validating order: {order_id}")
    return {
        "order_id": order_id,
        "amount": 99.99,
        "status": "validated",
    }


async def process_payment(order_id: str, amount: float) -> Dict[str, Any]:
    """Process payment through payment gateway."""
    print(f"  [step] Processing payment: ${amount} for {order_id}")
    return {
        "payment_id": f"pay_{order_id}",
        "amount": amount,
        "status": "charged",
    }


async def send_notification(order_id: str, channel: str) -> Dict[str, Any]:
    """Send notification via specified channel."""
    print(f"  [step] Sending {channel} notification for {order_id}")
    return {
        "order_id": order_id,
        "channel": channel,
        "sent": True,
    }


# =============================================================================
# WORKFLOW - Uses implicit context via get_context()
# =============================================================================


async def order_workflow(order_id: str) -> Dict[str, Any]:
    """
    Process an order end-to-end.

    This exact same code runs on:
    - Local (MockContext) - for testing
    - Local (LocalContext) - for development
    - AWS Lambda (AWSContext) - for production

    The context is accessed implicitly via get_context().
    Context handles:
    - Checkpointing (AWS: native, Local: event sourcing)
    - Sleep (AWS: no compute charges, Local: suspend/resume)
    - Parallel execution
    """
    ctx = get_context()

    print(f"[workflow] Starting order processing: {order_id}")

    # Step 1: Validate order
    order = await ctx.run(validate_order, order_id)
    print(f"[workflow] Order validated: {order['status']}")

    # Step 2: Wait before payment (cost-free on AWS!)
    print("[workflow] Waiting before payment...")
    await ctx.sleep(5)

    # Step 3: Process payment
    payment = await ctx.run(process_payment, order_id, order["amount"])
    print(f"[workflow] Payment processed: {payment['status']}")

    # Step 4: Send notifications in parallel
    print("[workflow] Sending notifications...")
    notifications = await ctx.parallel(
        ctx.run(send_notification, order_id, "email"),
        ctx.run(send_notification, order_id, "sms"),
    )

    print(f"[workflow] Order processing complete!")
    return {
        "order_id": order_id,
        "status": "completed",
        "order": order,
        "payment": payment,
        "notifications": notifications,
    }


# =============================================================================
# AWS LAMBDA HANDLER
# =============================================================================

# Try to create AWS handler if SDK is available
try:
    from aws_durable_execution_sdk_python import DurableContext, durable_execution

    from pyworkflow.aws import AWSWorkflowContext
    from pyworkflow.context import set_context, reset_context

    @durable_execution
    def handler(event: Dict[str, Any], context: DurableContext) -> Dict[str, Any]:
        """AWS Lambda entry point."""
        aws_ctx = AWSWorkflowContext(
            aws_context=context,
            run_id=event.get("run_id", "aws_run"),
            workflow_name="order_workflow",
        )
        # Set implicit context
        token = set_context(aws_ctx)
        try:
            return asyncio.run(order_workflow(event["order_id"]))
        finally:
            reset_context(token)
            aws_ctx.cleanup()

except ImportError:
    # AWS SDK not installed - handler will be created for testing below
    handler = None


# =============================================================================
# LOCAL TESTING
# =============================================================================


if __name__ == "__main__":
    print("=" * 70)
    print("AWS Durable Lambda - Local Testing with MockContext")
    print("=" * 70)
    print()
    print("NOTE: Same workflow code runs identically on AWS Lambda.")
    print("The context handles all runtime-specific behavior.")
    print()

    # Test with MockContext using context manager
    async def run_test():
        async with MockContext(skip_sleeps=True) as ctx:
            result = await order_workflow("ORD-AWS-001")

            print()
            print("=" * 70)
            print("Result:")
            print("=" * 70)
            import json
            print(json.dumps(result, indent=2))

            print()
            print("=" * 70)
            print("Test Verification:")
            print("=" * 70)
            print(f"  Steps executed: {ctx.step_count}")
            print(f"  Step names: {ctx.step_names}")
            print(f"  Sleeps: {ctx.sleep_count} (total: {ctx.total_sleep_seconds}s)")

            # Assertions for testing
            ctx.assert_step_called("validate_order")
            ctx.assert_step_called("process_payment")
            ctx.assert_step_called("send_notification", times=2)
            ctx.assert_slept()

            print()
            print("All assertions passed!")

    asyncio.run(run_test())
