"""
continue_as_new() primitive for workflow continuation.

Allows workflows to terminate current execution and start a new run
with fresh event history. Essential for long-running workflows that
would otherwise accumulate unbounded event history.
"""

from typing import Any, NoReturn

from loguru import logger

from pyworkflow.context import get_context, has_context
from pyworkflow.core.exceptions import ContinueAsNewSignal


def continue_as_new(*args: Any, **kwargs: Any) -> NoReturn:
    """
    Complete current workflow and start a new execution with fresh event history.

    This function never returns - it raises ContinueAsNewSignal which is caught
    by the executor. The current workflow is marked as CONTINUED_AS_NEW and a
    new run is started with the provided arguments.

    At least one argument must be provided - explicit args are required.

    Use this for:
    - Long-running polling loops that would accumulate many events
    - Recurring scheduled tasks (daily reports, weekly cleanup)
    - Any workflow that processes data in batches and needs to continue

    Args:
        *args: Positional arguments for the new workflow execution
        **kwargs: Keyword arguments for the new workflow execution

    Raises:
        ContinueAsNewSignal: Always (this function never returns)
        RuntimeError: If called outside workflow context
        ValueError: If no arguments are provided

    Examples:
        @workflow
        async def polling_workflow(cursor: str | None = None):
            # Process current batch
            new_cursor, items = await fetch_items(cursor)
            for item in items:
                await process_item(item)

            # Continue with new cursor if more items
            if new_cursor:
                continue_as_new(cursor=new_cursor)

            return "done"

        @workflow
        async def daily_report_workflow(date: str):
            await generate_report(date)
            await sleep("24h")

            # Continue with next day
            next_date = get_next_date(date)
            continue_as_new(date=next_date)

        @workflow
        async def batch_processor(offset: int = 0, batch_size: int = 100):
            items = await fetch_batch(offset, batch_size)

            if items:
                for item in items:
                    await process_item(item)
                # Continue with next batch
                continue_as_new(offset=offset + batch_size, batch_size=batch_size)

            return f"Processed {offset} items total"
    """
    if not has_context():
        raise RuntimeError(
            "continue_as_new() must be called within a workflow context. "
            "Make sure you're using the @workflow decorator."
        )

    if not args and not kwargs:
        raise ValueError(
            "continue_as_new() requires at least one argument. "
            "Pass the arguments for the new workflow execution."
        )

    ctx = get_context()

    # Check for cancellation - don't continue if cancelled
    ctx.check_cancellation()

    logger.info(
        "Workflow continuing as new execution",
        run_id=ctx.run_id,
        workflow_name=ctx.workflow_name,
        new_args=args,
        new_kwargs=kwargs,
    )

    raise ContinueAsNewSignal(workflow_args=args, workflow_kwargs=kwargs)
