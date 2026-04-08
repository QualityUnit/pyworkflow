"""
StreamStepContext for on_signal callbacks.

Provides status information and management APIs (resume, cancel)
for stream steps processing signals.
"""

from loguru import logger


class StreamStepContext:
    """
    Context provided to on_signal callbacks in stream steps.

    Provides:
    - Step status information
    - resume() to trigger lifecycle function re-execution
    - cancel() to terminate the step
    """

    def __init__(
        self,
        status: str,
        run_id: str,
        stream_id: str,
        storage: object | None = None,
    ) -> None:
        self.status = status
        self.run_id = run_id
        self.stream_id = stream_id
        self._storage = storage
        self._should_resume = False
        self._cancelled = False
        self._cancel_reason: str | None = None
        self._terminate_requested = False
        self._suspend_requested = False
        self._suspend_reason: str | None = None
        self._suspend_resume_signals: list[str] | None = None

    async def resume(self) -> None:
        """
        Resume the step's lifecycle function.

        The signal that triggered this on_signal callback will be
        available via get_current_signal() in the lifecycle function.
        """
        self._should_resume = True
        logger.debug(
            "Stream step resume requested",
            run_id=self.run_id,
            stream_id=self.stream_id,
        )

    async def cancel(self, reason: str | None = None) -> None:
        """
        Cancel the stream step.

        Args:
            reason: Optional reason for cancellation
        """
        self._cancelled = True
        self._cancel_reason = reason
        logger.info(
            "Stream step cancel requested",
            run_id=self.run_id,
            stream_id=self.stream_id,
            reason=reason,
        )

    async def terminate(self) -> None:
        """Mark the step as permanently terminated (no further invocations)."""
        self._terminate_requested = True

    async def suspend(
        self,
        reason: str,
        resume_signals: list[str] | None = None,
    ) -> None:
        """Mark the step as suspended until an external resume condition."""
        self._suspend_requested = True
        self._suspend_reason = reason
        self._suspend_resume_signals = list(resume_signals) if resume_signals else None

    @property
    def terminate_requested(self) -> bool:
        return self._terminate_requested

    @property
    def suspend_requested(self) -> bool:
        return self._suspend_requested

    @property
    def suspend_reason(self) -> str | None:
        return self._suspend_reason

    @property
    def suspend_resume_signals(self) -> list[str] | None:
        return self._suspend_resume_signals

    @property
    def should_resume(self) -> bool:
        """Whether resume() was called during on_signal processing."""
        return self._should_resume

    @property
    def is_cancelled(self) -> bool:
        """Whether cancel() was called during on_signal processing."""
        return self._cancelled

    @property
    def cancel_reason(self) -> str | None:
        """Reason for cancellation, if any."""
        return self._cancel_reason
