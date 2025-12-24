"""
AWS Lambda handler wrapper for PyWorkflow workflows.

This module provides a decorator to create AWS Lambda handlers from
PyWorkflow workflow functions.
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar

from loguru import logger

from pyworkflow.context import reset_context, set_context

from .context import AWSWorkflowContext

if TYPE_CHECKING:
    from aws_durable_execution_sdk_python import DurableContext

# Type variable for the workflow function
F = TypeVar("F", bound=Callable[..., Any])


def aws_workflow_handler(workflow_fn: F) -> Callable[[dict[str, Any], Any], Any]:
    """
    Decorator to create AWS Lambda handler from a PyWorkflow workflow.

    This decorator wraps a PyWorkflow workflow function and creates an AWS
    Lambda handler that uses AWS Durable Execution SDK for checkpointing
    and durability.

    The decorated function receives the Lambda event as keyword arguments,
    and has access to an AWSWorkflowContext for step execution and sleeping.

    Note: The AWS SDK is imported lazily - you can define workflows locally
    without the SDK installed, and test them with MockDurableContext.
    The SDK is only required when actually running on AWS Lambda.

    Usage:
        ```python
        from pyworkflow import workflow, step
        from pyworkflow.aws import aws_workflow_handler

        @step
        async def process_data(data: str) -> dict:
            return {"processed": data}

        @aws_workflow_handler
        @workflow
        async def my_workflow(ctx: AWSWorkflowContext, data: str):
            result = await process_data(data)
            ctx.sleep(300)  # Wait 5 minutes
            return result

        # Export as Lambda handler
        handler = my_workflow
        ```

    Args:
        workflow_fn: A PyWorkflow workflow function (sync or async)

    Returns:
        An AWS Lambda handler function (decorated with @durable_execution when SDK available)
    """
    # Get workflow name for logging
    workflow_name = getattr(workflow_fn, "__name__", "unknown_workflow")

    # Try to import AWS SDK - if available, use real decorator
    # If not available, create a wrapper that fails at runtime
    try:
        from aws_durable_execution_sdk_python import durable_execution

        _has_aws_sdk = True
    except ImportError:
        _has_aws_sdk = False

        def durable_execution(f):
            return f  # no-op decorator

    @durable_execution
    @functools.wraps(workflow_fn)
    def lambda_handler(event: dict[str, Any], context: Any) -> Any:
        """
        AWS Lambda handler that executes the PyWorkflow workflow.

        Args:
            event: Lambda event payload (passed as kwargs to workflow)
            context: AWS DurableContext for checkpointing

        Returns:
            The result of the workflow execution
        """
        # Check if SDK is available when actually executing
        if not _has_aws_sdk:
            raise ImportError(
                "aws-durable-execution-sdk-python is required for AWS runtime. "
                "Install it with: pip install pyworkflow[aws]\n"
                "For local testing, use create_test_handler() from pyworkflow.aws.testing"
            )

        logger.info(f"Starting AWS workflow: {workflow_name}", event=event)

        # Create PyWorkflow AWS context adapter
        aws_ctx = AWSWorkflowContext(context)

        # Set the implicit context
        token = set_context(aws_ctx)

        try:
            # Execute the workflow (no longer pass ctx explicitly)
            if asyncio.iscoroutinefunction(workflow_fn):
                # Async workflow - run in event loop
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

                if loop is not None:
                    # Running in async context (unusual for Lambda)
                    import concurrent.futures

                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(asyncio.run, workflow_fn(**event))
                        result = future.result()
                else:
                    # Normal Lambda execution
                    result = asyncio.run(workflow_fn(**event))
            else:
                # Sync workflow - execute directly
                result = workflow_fn(**event)

            logger.info(f"AWS workflow completed: {workflow_name}")
            return result

        except Exception as e:
            logger.error(
                f"AWS workflow failed: {workflow_name}",
                error=str(e),
                exc_info=True,
            )
            raise

        finally:
            # Reset the implicit context
            reset_context(token)
            # Clean up AWS-specific context
            aws_ctx.cleanup()

    # Preserve original function metadata
    lambda_handler.__pyworkflow_workflow__ = workflow_fn
    lambda_handler.__pyworkflow_workflow_name__ = workflow_name

    return lambda_handler


def create_lambda_handler(
    workflow_fn: Callable[..., Any],
) -> Callable[[dict[str, Any], DurableContext], Any]:
    """
    Alternative function-based API to create Lambda handler.

    This is an alternative to the decorator approach for cases where
    decoration at definition time isn't convenient.

    Usage:
        ```python
        @workflow
        async def my_workflow(ctx, data: str):
            return {"result": data}

        handler = create_lambda_handler(my_workflow)
        ```

    Args:
        workflow_fn: A PyWorkflow workflow function

    Returns:
        An AWS Lambda handler function
    """
    return aws_workflow_handler(workflow_fn)
