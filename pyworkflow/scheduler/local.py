"""
Local scheduler for PyWorkflow.

Provides a polling-based scheduler that runs in the same process as your application.
This is the local runtime equivalent of Celery Beat.
"""

import asyncio
from datetime import UTC, datetime

from loguru import logger

from pyworkflow.primitives.schedule import trigger_schedule
from pyworkflow.storage.base import StorageBackend
from pyworkflow.storage.schemas import OverlapPolicy, Schedule
from pyworkflow.utils.schedule import calculate_next_run_time


class LocalScheduler:
    """
    Local scheduler that polls storage for due schedules.

    This is the local runtime equivalent of Celery Beat. It polls storage
    for schedules that are due and triggers them using the configured runtime.

    Usage:
        from pyworkflow.scheduler import LocalScheduler
        from pyworkflow.storage import InMemoryStorageBackend

        storage = InMemoryStorageBackend()
        scheduler = LocalScheduler(storage=storage, poll_interval=5.0)

        # Run forever
        await scheduler.run()

        # Or run for a specific duration
        await scheduler.run(duration=60.0)  # Run for 60 seconds

    Example with CLI:
        pyworkflow scheduler run --poll-interval 5

    Args:
        storage: Storage backend to use. If None, uses configured storage.
        poll_interval: Seconds between storage polls (default: 5.0)
    """

    def __init__(
        self,
        storage: StorageBackend | None = None,
        poll_interval: float = 5.0,
    ):
        """
        Initialize the local scheduler.

        Args:
            storage: Storage backend to use. If None, uses configured storage.
            poll_interval: Seconds between storage polls (default: 5.0)
        """
        self._storage = storage
        self.poll_interval = poll_interval
        self._running = False
        self._start_time: datetime | None = None

    @property
    def storage(self) -> StorageBackend:
        """Get the storage backend, resolving from config if needed."""
        if self._storage is None:
            from pyworkflow.config import get_config

            config = get_config()
            if config.storage is None:
                raise ValueError(
                    "Storage backend required. Configure storage or pass to constructor."
                )
            self._storage = config.storage
        return self._storage

    async def run(self, duration: float | None = None) -> None:
        """
        Run the scheduler loop.

        Args:
            duration: Optional duration in seconds to run. If None, runs forever.
        """
        self._running = True
        self._start_time = datetime.now(UTC)

        logger.info(
            "Local scheduler started",
            poll_interval=self.poll_interval,
            duration=duration,
        )

        try:
            while self._running:
                # Check duration limit
                if duration is not None:
                    elapsed = (datetime.now(UTC) - self._start_time).total_seconds()
                    if elapsed >= duration:
                        logger.info("Scheduler duration limit reached")
                        break

                try:
                    await self._tick()
                except Exception as e:
                    logger.error(f"Scheduler tick failed: {e}")

                await asyncio.sleep(self.poll_interval)
        finally:
            self._running = False
            logger.info("Local scheduler stopped")

    async def _tick(self) -> None:
        """Process due schedules in a single tick."""
        now = datetime.now(UTC)
        due_schedules = await self.storage.get_due_schedules(now)

        if due_schedules:
            logger.debug(f"Found {len(due_schedules)} due schedule(s)")

        for schedule in due_schedules:
            await self._process_schedule(schedule, now)

    async def _process_schedule(self, schedule: Schedule, now: datetime) -> None:
        """
        Process a single due schedule.

        Args:
            schedule: The schedule to process
            now: Current timestamp
        """
        # Check overlap policy
        should_run, reason = await self._check_overlap_policy(schedule)

        if not should_run:
            logger.info(
                f"Skipping schedule: {reason}",
                schedule_id=schedule.schedule_id,
            )
            schedule.skipped_runs += 1
            schedule.next_run_time = calculate_next_run_time(schedule.spec, last_run=now, now=now)
            await self.storage.update_schedule(schedule)
            return

        # Trigger the schedule (uses runtime-agnostic start())
        try:
            logger.info(
                "Triggering schedule",
                schedule_id=schedule.schedule_id,
                workflow_name=schedule.workflow_name,
            )
            run_id = await trigger_schedule(schedule.schedule_id, storage=self.storage)
            logger.info(
                "Schedule triggered successfully",
                schedule_id=schedule.schedule_id,
                run_id=run_id,
            )
        except Exception as e:
            logger.error(
                "Failed to trigger schedule",
                schedule_id=schedule.schedule_id,
                error=str(e),
            )
            # Update failed runs count
            schedule.failed_runs += 1
            schedule.next_run_time = calculate_next_run_time(schedule.spec, last_run=now, now=now)
            await self.storage.update_schedule(schedule)

    async def _check_overlap_policy(self, schedule: Schedule) -> tuple[bool, str]:
        """
        Check if schedule should run based on overlap policy.

        Args:
            schedule: The schedule to check

        Returns:
            Tuple of (should_run, reason if not running)
        """
        # No running workflows = always run
        if not schedule.running_run_ids:
            return True, ""

        policy = schedule.overlap_policy

        if policy == OverlapPolicy.SKIP:
            return False, "previous run still active (SKIP policy)"

        elif policy == OverlapPolicy.ALLOW_ALL:
            return True, ""

        elif policy == OverlapPolicy.BUFFER_ONE:
            if schedule.buffered_count >= 1:
                return False, "already buffered one run (BUFFER_ONE policy)"
            schedule.buffered_count += 1
            return True, ""

        elif policy == OverlapPolicy.BUFFER_ALL:
            schedule.buffered_count += 1
            return True, ""

        elif policy == OverlapPolicy.CANCEL_OTHER:
            # Cancel running workflows before starting new one
            from pyworkflow.engine.executor import cancel_workflow

            for run_id in list(schedule.running_run_ids):
                try:
                    await cancel_workflow(run_id)
                    logger.info(
                        "Cancelled previous run",
                        schedule_id=schedule.schedule_id,
                        run_id=run_id,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to cancel previous run",
                        schedule_id=schedule.schedule_id,
                        run_id=run_id,
                        error=str(e),
                    )
            return True, ""

        # Default: allow
        return True, ""

    def stop(self) -> None:
        """Stop the scheduler gracefully."""
        logger.info("Stopping local scheduler...")
        self._running = False

    @property
    def is_running(self) -> bool:
        """Check if the scheduler is currently running."""
        return self._running

    async def tick_once(self) -> int:
        """
        Process due schedules once (useful for testing).

        Returns:
            Number of schedules processed
        """
        now = datetime.now(UTC)
        due_schedules = await self.storage.get_due_schedules(now)

        for schedule in due_schedules:
            await self._process_schedule(schedule, now)

        return len(due_schedules)
