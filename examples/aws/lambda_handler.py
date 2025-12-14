"""
AWS Lambda Handler - Production Ready

This file is what you deploy to AWS Lambda. No mocks, no testing code.
Just the workflow and handler.

Deploy:
    zip deployment.zip lambda_handler.py
    # Include pyworkflow and aws-durable-execution-sdk-python in layer

Handler: lambda_handler.handler
"""

from pyworkflow import workflow
from pyworkflow.context import get_context
from pyworkflow.aws import aws_workflow_handler


async def validate_order(order_id: str) -> dict:
    """Validate order exists and is processable."""
    # Real implementation: check database, inventory, etc.
    return {"order_id": order_id, "amount": 99.99, "valid": True}


async def charge_payment(order_id: str, amount: float) -> dict:
    """Process payment via payment gateway."""
    # Real implementation: Stripe, PayPal, etc.
    return {"payment_id": f"pay_{order_id}", "charged": amount}


async def fulfill_order(order_id: str, payment_id: str) -> dict:
    """Trigger order fulfillment."""
    # Real implementation: notify warehouse, shipping, etc.
    return {"order_id": order_id, "fulfillment_status": "processing"}


@aws_workflow_handler
@workflow()
async def process_order(order_id: str):
    """
    Order processing workflow.

    Uses implicit context - get_context() provides access to AWS context.

    Checkpoints:
    - validate_order result is saved
    - charge_payment result is saved
    - fulfill_order result is saved

    If Lambda times out or crashes, it resumes from last checkpoint.
    """
    ctx = get_context()

    # Validate
    order = await ctx.run(validate_order, order_id)

    # Wait 1 minute before charging (fraud check window)
    await ctx.sleep(60)  # No compute charges during this wait!

    # Charge
    payment = await ctx.run(charge_payment, order_id, order["amount"])

    # Fulfill
    fulfillment = await ctx.run(fulfill_order, order_id, payment["payment_id"])

    return {
        "order_id": order_id,
        "status": "completed",
        "payment": payment,
        "fulfillment": fulfillment,
    }


# AWS Lambda entry point
handler = process_order
