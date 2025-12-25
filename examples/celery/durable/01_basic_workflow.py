"""
Celery Durable Workflow - Basic Example

This example demonstrates a simple event-sourced workflow running on Celery workers.
- 3-step order processing workflow
- Distributed execution across workers
- Events recorded for each step

Prerequisites:
    1. Start Redis: docker run -d -p 6379:6379 redis:7-alpine
    2. Start worker: pyworkflow --module examples.celery.durable.01_basic_workflow worker run

Run with CLI:
    pyworkflow --module examples.celery.durable.01_basic_workflow workflows run order_workflow \
        --arg order_id=order-123 --arg amount=99.99

Check status:
    pyworkflow runs list
    pyworkflow runs status <run_id>
    pyworkflow runs logs <run_id>
"""

from pyworkflow import step, workflow


@step(name="basic_validate_order")
async def validate_order(order_id: str) -> dict:
    """Validate the order exists and is processable."""
    print(f"[Step] Validating order {order_id}...")
    return {"order_id": order_id, "valid": True}


@step(name="basic_process_payment")
async def process_payment(order: dict, amount: float) -> dict:
    """Process payment for the order."""
    print(f"[Step] Processing payment ${amount:.2f} for {order['order_id']}...")
    return {**order, "paid": True, "amount": amount}


@step()
async def send_confirmation(order: dict) -> dict:
    """Send order confirmation email."""
    print(f"[Step] Sending confirmation for {order['order_id']}...")
    return {**order, "confirmed": True}


@workflow(tags=["celery", "durable"])
async def order_workflow(order_id: str, amount: float) -> dict:
    """
    Complete order processing workflow.

    Steps:
    1. Validate the order
    2. Process payment
    3. Send confirmation

    Each step runs on Celery workers and is recorded as an event.
    """
    order = await validate_order(order_id)
    order = await process_payment(order, amount)
    order = await send_confirmation(order)
    return order


async def main() -> None:
    """Run the order workflow example."""
    import argparse

    import pyworkflow

    parser = argparse.ArgumentParser(description="Order Processing Workflow")
    parser.add_argument("--order-id", default="order-123", help="Order ID to process")
    parser.add_argument("--amount", type=float, default=99.99, help="Order amount")
    args = parser.parse_args()

    # Configuration is automatically loaded from pyworkflow.config.yaml
    # which sets runtime=celery and creates storage backend
    print(f"Starting order workflow for {args.order_id} (${args.amount:.2f})...")
    run_id = await pyworkflow.start(order_workflow, args.order_id, args.amount)
    print(f"Workflow started with run_id: {run_id}")
    print(f"\nCheck status: pyworkflow runs status {run_id}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
