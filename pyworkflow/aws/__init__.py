"""
AWS Durable Lambda Functions integration for PyWorkflow.

This module provides integration with AWS Lambda Durable Functions,
allowing PyWorkflow workflows to run on AWS Lambda with automatic
checkpointing, durability, and cost-free sleep/wait operations.

Quick Start:
    ```python
    from pyworkflow import workflow, step
    from pyworkflow.aws import aws_workflow_handler, AWSWorkflowContext

    @step
    async def process_order(order_id: str) -> dict:
        return {"order_id": order_id, "status": "processed"}

    @aws_workflow_handler
    @workflow
    async def order_workflow(ctx: AWSWorkflowContext, order_id: str):
        # Execute step with automatic checkpointing
        result = await process_order(order_id)

        # Sleep without compute charges
        ctx.sleep(300)  # 5 minutes

        return result

    # Export Lambda handler
    handler = order_workflow
    ```

Installation:
    pip install pyworkflow[aws]

Features:
    - Automatic checkpointing via AWS Durable Execution SDK
    - Cost-free waits using context.wait()
    - Support for both sync and async workflows
    - Local testing with mock context
"""

from pyworkflow.aws.context import (
    AWSWorkflowContext,
    get_aws_context,
    has_aws_context,
)
from pyworkflow.aws.handler import aws_workflow_handler, create_lambda_handler
from pyworkflow.aws.testing import (
    MockCallback,
    MockDurableContext,
    MockDuration,
    create_test_handler,
)

__all__ = [
    # Context
    "AWSWorkflowContext",
    "get_aws_context",
    "has_aws_context",
    # Handler
    "aws_workflow_handler",
    "create_lambda_handler",
    # Testing
    "MockDurableContext",
    "MockDuration",
    "MockCallback",
    "create_test_handler",
]
