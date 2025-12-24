"""
Shield - Protection from cancellation.

The shield() context manager allows critical sections of code to run
to completion even when cancellation has been requested. Use it for
cleanup operations, compensating transactions, or any code that must
complete to maintain consistency.

Note:
    Cancellation in PyWorkflow is checkpoint-based. It is checked:
    - Before each step execution
    - Before sleep suspension
    - Before hook suspension

    Cancellation does NOT interrupt a step mid-execution. If a step takes
    a long time, cancellation will only be detected after it completes.
    For cooperative cancellation within long-running steps, call
    ``ctx.check_cancellation()`` periodically.

Example:
    @workflow
    async def order_workflow(order_id: str):
        try:
            await reserve_inventory()
            await charge_payment()
            await ship_order()
        except CancellationError:
            # Critical cleanup - must complete even if cancelled
            async with shield():
                await release_inventory()
                await refund_payment()
            raise  # Re-raise after cleanup
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from loguru import logger


@asynccontextmanager
async def shield() -> AsyncIterator[None]:
    """
    Context manager that prevents cancellation within its scope.

    While inside a shield() block, cancellation checks will not raise
    CancellationError. The cancellation request is preserved and will
    take effect after exiting the shield scope.

    Use for:
    - Critical cleanup operations
    - Compensating transactions
    - Database commits
    - Any code that must complete for consistency

    Example:
        async with shield():
            # This code will complete even if cancellation was requested
            await critical_cleanup()

    Warning:
        Don't use shield for long-running operations as it defeats
        the purpose of graceful cancellation.

    Yields:
        None - the shield scope
    """
    from pyworkflow.context import get_context, has_context

    if not has_context():
        # No workflow context - shield has no effect
        yield
        return

    ctx = get_context()

    # Save previous state and block cancellation
    previous_blocked = ctx._cancellation_blocked  # type: ignore[attr-defined]
    ctx._cancellation_blocked = True  # type: ignore[attr-defined]

    logger.debug(
        "Entered shield scope - cancellation blocked",
        run_id=ctx.run_id,
    )

    try:
        yield
    finally:
        # Restore previous state
        ctx._cancellation_blocked = previous_blocked  # type: ignore[attr-defined]

        logger.debug(
            "Exited shield scope - cancellation restored",
            run_id=ctx.run_id,
            cancellation_requested=ctx.is_cancellation_requested(),
        )
