"""
ChildWorkflowHandle for fire-and-forget child workflow pattern.

When start_child_workflow() is called with wait_for_completion=False,
it returns a handle that can be used to query status, get results, or cancel.
"""

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pyworkflow.core.exceptions import ChildWorkflowFailedError
from pyworkflow.storage.schemas import RunStatus

if TYPE_CHECKING:
    from pyworkflow.storage.base import StorageBackend


@dataclass
class ChildWorkflowHandle:
    """
    Handle for a child workflow that was started without waiting.

    Provides methods to query status, await completion, or cancel
    the child workflow.

    Attributes:
        child_id: Deterministic child identifier (for replay)
        child_run_id: The child workflow's unique run ID
        child_workflow_name: The name of the child workflow
        parent_run_id: The parent workflow's run ID

    Example:
        # Fire-and-forget pattern
        handle = await start_child_workflow(
            my_workflow,
            arg1, arg2,
            wait_for_completion=False
        )

        # Do other work...
        await do_other_work()

        # Later, check status or get result
        status = await handle.get_status()
        if status == RunStatus.COMPLETED:
            result = await handle.result()

        # Or cancel if needed
        await handle.cancel()
    """

    child_id: str
    child_run_id: str
    child_workflow_name: str
    parent_run_id: str
    _storage: "StorageBackend"

    async def get_status(self) -> RunStatus:
        """
        Get current status of the child workflow.

        Returns:
            Current RunStatus of the child workflow

        Raises:
            ValueError: If child workflow not found
        """
        run = await self._storage.get_run(self.child_run_id)
        if run is None:
            raise ValueError(f"Child workflow {self.child_run_id} not found")
        return run.status

    async def result(self, timeout: float | None = None) -> Any:
        """
        Wait for child workflow to complete and return result.

        Polls the storage for child completion. For long timeouts,
        consider using a hook-based approach instead.

        Args:
            timeout: Maximum seconds to wait (None = wait forever)

        Returns:
            The child workflow's result

        Raises:
            ChildWorkflowFailedError: If child failed or was cancelled
            TimeoutError: If timeout exceeded
            ValueError: If child workflow not found
        """
        from pyworkflow.serialization.decoder import deserialize

        poll_interval = 0.5
        elapsed = 0.0

        while True:
            run = await self._storage.get_run(self.child_run_id)
            if run is None:
                raise ValueError(f"Child workflow {self.child_run_id} not found")

            if run.status == RunStatus.COMPLETED:
                return deserialize(run.result) if run.result else None

            if run.status == RunStatus.FAILED:
                raise ChildWorkflowFailedError(
                    child_run_id=self.child_run_id,
                    child_workflow_name=self.child_workflow_name,
                    error=run.error or "Unknown error",
                    error_type="Unknown",
                )

            if run.status == RunStatus.CANCELLED:
                raise ChildWorkflowFailedError(
                    child_run_id=self.child_run_id,
                    child_workflow_name=self.child_workflow_name,
                    error="Child workflow was cancelled",
                    error_type="CancellationError",
                )

            if timeout is not None and elapsed >= timeout:
                raise TimeoutError(
                    f"Child workflow {self.child_run_id} did not complete within {timeout}s"
                )

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

    async def cancel(self, reason: str | None = None) -> bool:
        """
        Request cancellation of the child workflow.

        Args:
            reason: Optional cancellation reason

        Returns:
            True if cancellation was initiated, False if already terminal
        """
        from pyworkflow.engine.executor import cancel_workflow

        return await cancel_workflow(
            run_id=self.child_run_id,
            reason=reason,
            storage=self._storage,
        )

    async def is_running(self) -> bool:
        """
        Check if child workflow is still running.

        Returns:
            True if running or suspended, False if terminal
        """
        status = await self.get_status()
        return status in {RunStatus.PENDING, RunStatus.RUNNING, RunStatus.SUSPENDED}

    async def is_terminal(self) -> bool:
        """
        Check if child workflow has reached a terminal state.

        Returns:
            True if completed, failed, or cancelled
        """
        status = await self.get_status()
        return status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}

    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"ChildWorkflowHandle("
            f"child_id={self.child_id!r}, "
            f"child_run_id={self.child_run_id!r}, "
            f"child_workflow_name={self.child_workflow_name!r})"
        )
