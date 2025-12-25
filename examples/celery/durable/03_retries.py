"""
Celery Durable Workflow - Retry Handling

This example demonstrates automatic retry handling on Celery workers.
- Steps can specify max_retries and retry_delay
- RetryableError triggers automatic retry with backoff
- FatalError stops workflow immediately (no retry)

Prerequisites:
    1. Start Redis: docker run -d -p 6379:6379 redis:7-alpine
    2. Start worker: pyworkflow --module examples.celery.durable.03_retries worker run

Run with CLI:
    pyworkflow --module examples.celery.durable.03_retries workflows run retry_demo_workflow \
        --arg endpoint=/api/data

The workflow has a 30% failure rate - run multiple times to see retry behavior.

Check status:
    pyworkflow runs list
    pyworkflow runs logs <run_id> --filter failed
"""

import random

from pyworkflow import step, workflow
from pyworkflow.core.exceptions import FatalError, RetryableError


@step(max_retries=3)
async def flaky_api_call(endpoint: str) -> dict:
    """
    Simulate a flaky API call that may fail.

    - 30% chance of RetryableError (will retry)
    - 10% chance of FatalError (will not retry)
    - 60% chance of success
    """
    print(f"[Step] Calling API: {endpoint}...")

    roll = random.random()

    if roll < 0.3:
        print("[Step] API temporarily unavailable, will retry...")
        raise RetryableError("API temporarily unavailable", retry_after="5s")

    if roll < 0.4:
        print("[Step] API returned invalid response, fatal error...")
        raise FatalError("API returned invalid response - cannot retry")

    print("[Step] API call successful!")
    return {"endpoint": endpoint, "status": "success", "data": {"value": 42}}


@step()
async def process_response(response: dict) -> dict:
    """Process the API response."""
    print(f"[Step] Processing response from {response['endpoint']}...")
    return {**response, "processed": True}


@workflow(tags=["celery", "durable"])
async def retry_demo_workflow(endpoint: str) -> dict:
    """
    Workflow demonstrating automatic retry handling.

    The flaky_api_call step has:
    - 30% failure rate with RetryableError (auto-retry)
    - 10% failure rate with FatalError (no retry)
    - 60% success rate

    Retries happen automatically with exponential backoff on workers.
    """
    response = await flaky_api_call(endpoint)
    result = await process_response(response)
    return {"message": "API call and processing succeeded", **result}


async def main() -> None:
    """Run the retry demo workflow example."""
    import argparse

    import pyworkflow

    parser = argparse.ArgumentParser(description="Retry Handling Demo Workflow")
    parser.add_argument("--endpoint", default="/api/data", help="API endpoint to call")
    args = parser.parse_args()

    # Configuration is automatically loaded from pyworkflow.config.yaml
    print(f"Starting retry demo workflow for endpoint {args.endpoint}...")
    print("(30% chance of retry, 10% chance of fatal error, 60% success)")
    run_id = await pyworkflow.start(retry_demo_workflow, args.endpoint)
    print(f"Workflow started with run_id: {run_id}")
    print(f"\nCheck status: pyworkflow runs status {run_id}")
    print(f"View logs: pyworkflow runs logs {run_id}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
