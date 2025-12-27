"""
Celery Durable Workflow - Idempotency

This example demonstrates idempotent workflow execution.
- Use --idempotency-key to prevent duplicate executions
- Same key returns existing run instead of starting new one
- Critical for payment processing and other sensitive operations

Prerequisites:
    1. Start Redis: docker run -d -p 6379:6379 redis:7-alpine
    2. Start worker: pyworkflow --module examples.celery.durable.05_idempotency worker run

Run with CLI:
    # First run - starts new workflow
    pyworkflow --module examples.celery.durable.05_idempotency workflows run payment_workflow \
        --arg payment_id=pay-123 --arg amount=99.99 \
        --idempotency-key payment-pay-123

    # Second run with same key - returns existing run (no duplicate charge)
    pyworkflow --module examples.celery.durable.05_idempotency workflows run payment_workflow \
        --arg payment_id=pay-123 --arg amount=99.99 \
        --idempotency-key payment-pay-123

Check status:
    pyworkflow runs list
"""

from pyworkflow import step, workflow


@step()
async def validate_payment(payment_id: str, amount: float) -> dict:
    """Validate the payment request."""
    print(f"[Step] Validating payment {payment_id} for ${amount:.2f}...")
    return {"payment_id": payment_id, "amount": amount, "valid": True}


@step()
async def charge_payment(payment: dict) -> dict:
    """
    Charge the payment.

    IMPORTANT: This step should only run once per payment!
    Idempotency keys ensure duplicate requests don't double-charge.
    """
    print(f"[Step] CHARGING payment {payment['payment_id']} for ${payment['amount']:.2f}...")
    print("[Step] (In production, this would call Stripe/PayPal with idempotency key)")
    return {**payment, "charged": True, "transaction_id": f"txn_{payment['payment_id']}"}


@step()
async def send_receipt(payment: dict) -> dict:
    """Send payment receipt."""
    print(f"[Step] Sending receipt for {payment['payment_id']}...")
    return {**payment, "receipt_sent": True}


@workflow(tags=["celery", "durable"])
async def payment_workflow(payment_id: str, amount: float) -> dict:
    """
    Payment processing workflow with idempotency.

    ALWAYS use --idempotency-key when running this workflow to prevent
    duplicate charges. The key should be unique per payment attempt.

    Example keys:
    - payment-{payment_id}
    - order-{order_id}-payment
    - user-{user_id}-{timestamp}

    If a workflow with the same idempotency key already exists:
    - If RUNNING: raises WorkflowAlreadyRunningError
    - If COMPLETED/FAILED/SUSPENDED: returns existing run_id
    """
    payment = await validate_payment(payment_id, amount)
    payment = await charge_payment(payment)
    payment = await send_receipt(payment)
    return payment


async def main() -> None:
    """Run the payment workflow example with idempotency."""
    import argparse

    import pyworkflow

    parser = argparse.ArgumentParser(description="Payment Workflow with Idempotency")
    parser.add_argument("--payment-id", default="pay-123", help="Payment ID")
    parser.add_argument("--amount", type=float, default=99.99, help="Payment amount")
    parser.add_argument("--idempotency-key", help="Idempotency key (recommended)")
    args = parser.parse_args()

    idempotency_key = args.idempotency_key or f"payment-{args.payment_id}"

    # Configuration is automatically loaded from pyworkflow.config.yaml
    print(f"Starting payment workflow for {args.payment_id} (${args.amount:.2f})...")
    print(f"Idempotency key: {idempotency_key}")
    run_id = await pyworkflow.start(
        payment_workflow,
        args.payment_id,
        args.amount,
        idempotency_key=idempotency_key,
    )
    print(f"Workflow started with run_id: {run_id}")
    print(f"\nCheck status: pyworkflow runs status {run_id}")
    print("\nRun again with same --idempotency-key to see duplicate prevention!")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
