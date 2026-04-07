"""
Background signal delivery consumer.

Polls for undelivered signals and dispatches them to subscribed stream steps.
Can run as an asyncio loop or integrated with Celery beat.
"""

import asyncio
import contextlib
from typing import Any

from loguru import logger


class StreamConsumer:
    """
    Background consumer that polls for pending signals and dispatches them.

    Ensures signals are delivered even if they arrive while a step is
    being processed (missed during the synchronous dispatch in emit()).
    """

    def __init__(
        self,
        storage: Any,
        poll_interval: float = 1.0,
    ) -> None:
        """
        Initialize the stream consumer.

        Args:
            storage: Storage backend
            poll_interval: Seconds between poll cycles
        """
        self._storage = storage
        self._poll_interval = poll_interval
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the consumer loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Stream consumer started", poll_interval=self._poll_interval)

    async def stop(self) -> None:
        """Stop the consumer loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("Stream consumer stopped")

    async def _poll_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            try:
                await self._process_pending_signals()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Stream consumer error: {e}")

            try:
                await self._process_scheduled_signals()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scheduled signal consumer error: {e}")

            await asyncio.sleep(self._poll_interval)

    async def _process_scheduled_signals(self) -> None:
        """Scan for due scheduled signals and emit them."""
        from datetime import UTC, datetime

        from pyworkflow.streams.emit import emit

        fetch = getattr(self._storage, "fetch_due_scheduled_signals", None)
        mark = getattr(self._storage, "mark_scheduled_signal_delivered", None)
        if fetch is None or mark is None:
            return  # backend doesn't support scheduled signals

        try:
            due = await fetch(datetime.now(UTC))
        except NotImplementedError:
            return

        for row in due:
            try:
                await emit(
                    stream_id=row["stream_id"],
                    signal_type=row["signal_type"],
                    payload=row.get("payload") or {},
                    storage=self._storage,
                    metadata=row.get("metadata") or {},
                    stream_run_id=row.get("stream_run_id"),
                )
            except Exception as e:  # noqa: BLE001
                logger.error(f"Failed to emit scheduled signal {row.get('id')}: {e}")
                continue
            try:
                await mark(row["id"])
            except Exception as e:  # noqa: BLE001
                logger.error(f"Failed to mark scheduled signal delivered: {e}")

    async def _process_pending_signals(self) -> None:
        """Process any pending signals for subscribed steps."""
        from pyworkflow.streams.dispatcher import dispatch_signal
        from pyworkflow.streams.signal import Signal

        # Get all active streams
        streams = getattr(self._storage, "_streams", {})

        for stream_id in list(streams.keys()):
            # Get all active subscriptions for this stream
            subscriptions = []
            if hasattr(self._storage, "_subscriptions"):
                for (sid, _), sub in self._storage._subscriptions.items():
                    if sid == stream_id and sub["status"] == "waiting":
                        subscriptions.append(sub)

            if not subscriptions:
                continue

            # Get pending signals for each subscription
            for sub in subscriptions:
                step_run_id = sub["step_run_id"]
                pending = await self._storage.get_pending_signals(stream_id, step_run_id)

                for sig_data in pending:
                    signal = Signal(
                        signal_id=sig_data["signal_id"],
                        stream_id=sig_data["stream_id"],
                        signal_type=sig_data["signal_type"],
                        payload=sig_data["payload"],
                        sequence=sig_data.get("sequence"),
                        source_run_id=sig_data.get("source_run_id"),
                        metadata=sig_data.get("metadata", {}),
                    )
                    await dispatch_signal(signal, self._storage)

    @property
    def is_running(self) -> bool:
        """Whether the consumer is currently running."""
        return self._running


async def poll_once(storage: Any) -> int:
    """
    Run a single poll cycle. Useful for testing or one-shot processing.

    Args:
        storage: Storage backend

    Returns:
        Number of signals processed
    """
    consumer = StreamConsumer(storage)
    await consumer._process_pending_signals()
    return 0  # Consumer doesn't track count currently
