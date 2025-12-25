"""
Custom Celery Beat scheduler for PyWorkflow schedules.

This scheduler integrates with PyWorkflow's storage backend to dynamically
load and execute scheduled workflows without requiring Beat to be restarted
when schedules change.

Usage:
    celery -A pyworkflow.celery.app beat \\
        --scheduler pyworkflow.celery.scheduler:PyWorkflowScheduler \\
        --loglevel INFO

The scheduler:
1. Polls storage for due schedules every sync_interval seconds
2. Creates Celery tasks for each due schedule
3. Handles overlap policies
4. Updates schedule metadata after runs
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

from celery.beat import Scheduler
from loguru import logger

from pyworkflow.storage.base import StorageBackend
from pyworkflow.storage.config import config_to_storage
from pyworkflow.storage.schemas import OverlapPolicy, Schedule


class PyWorkflowScheduler(Scheduler):
    """
    Custom Celery Beat scheduler that reads schedules from PyWorkflow storage.

    This scheduler:
    1. Polls storage for due schedules every sync_interval
    2. Creates Celery tasks for each due schedule
    3. Handles overlap policies (skip, buffer, cancel, allow)
    4. Updates schedule metadata after runs

    Configuration:
        The scheduler reads configuration from environment variables:
        - PYWORKFLOW_STORAGE_BACKEND: Storage backend type (file, memory)
        - PYWORKFLOW_STORAGE_PATH: Path for file storage backend

    Example:
        celery -A pyworkflow.celery.app beat \\
            --scheduler pyworkflow.celery.scheduler:PyWorkflowScheduler
    """

    #: How often to check for due schedules (seconds)
    sync_interval = 5.0

    def __init__(self, *args: Any, storage_config: dict[str, Any] | None = None, **kwargs: Any):
        """
        Initialize the scheduler.

        Args:
            storage_config: Storage backend configuration dict
        """
        super().__init__(*args, **kwargs)
        self._storage_config = storage_config
        self._storage: StorageBackend | None = None
        self._last_schedule_check: datetime | None = None
        self._initialized = False

    def setup_schedule(self) -> None:
        """Initialize the scheduler."""
        super().setup_schedule()

        # Activate any @scheduled_workflow decorated functions
        self._activate_decorated_schedules()

        logger.info("PyWorkflow scheduler initialized")
        self._initialized = True

    def _activate_decorated_schedules(self) -> None:
        """Activate all @scheduled_workflow decorated functions."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._do_activate_schedules())
            finally:
                loop.close()
        except Exception as e:
            logger.error(f"Error activating decorated schedules: {e}")

    async def _do_activate_schedules(self) -> None:
        """Actually activate the decorated schedules."""
        from pyworkflow.core.scheduled import activate_scheduled_workflows

        storage = self._get_storage()
        if storage is None:
            logger.warning("Storage not configured, cannot activate decorated schedules")
            return

        try:
            schedule_ids = await activate_scheduled_workflows(storage=storage)
            if schedule_ids:
                logger.info(f"Activated {len(schedule_ids)} decorated schedule(s): {schedule_ids}")
            else:
                logger.debug("No decorated schedules to activate")
        except Exception as e:
            logger.error(f"Failed to activate decorated schedules: {e}")

    def tick(self) -> float:
        """
        Called by Celery Beat on each tick.

        Checks for due schedules and triggers them.

        Returns:
            Seconds until next tick
        """
        # Call parent tick to handle existing celery beat entries
        remaining = super().tick()

        # Check for due schedules
        now = datetime.now(UTC)
        if (
            self._last_schedule_check is None
            or (now - self._last_schedule_check).total_seconds() >= self.sync_interval
        ):
            self._sync_schedules()
            self._last_schedule_check = now

        # Return the smaller of the two intervals
        return min(remaining, self.sync_interval)

    def _sync_schedules(self) -> None:
        """Sync schedules from storage and trigger due ones."""
        try:
            # Run async code in sync context
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._process_due_schedules())
            finally:
                loop.close()
        except Exception as e:
            logger.error(f"Error syncing schedules: {e}")

    async def _process_due_schedules(self) -> None:
        """Process all schedules that are due to run."""
        from pyworkflow.celery.tasks import execute_scheduled_workflow_task
        from pyworkflow.utils.schedule import calculate_next_run_time

        storage = self._get_storage()
        if storage is None:
            logger.warning("Storage not configured, skipping schedule sync")
            return

        now = datetime.now(UTC)

        try:
            due_schedules = await storage.get_due_schedules(now)
        except Exception as e:
            logger.error(f"Failed to get due schedules: {e}")
            return

        for schedule in due_schedules:
            try:
                should_run, reason = await self._check_overlap_policy(schedule, storage)

                if should_run:
                    # Calculate next run time before triggering
                    next_run_time = calculate_next_run_time(
                        schedule.spec,
                        last_run=schedule.next_run_time,
                        now=now,
                    )

                    # Update next_run_time immediately to prevent duplicate triggers
                    schedule.next_run_time = next_run_time
                    schedule.updated_at = datetime.now(UTC)
                    await storage.update_schedule(schedule)

                    # Trigger the scheduled workflow task
                    execute_scheduled_workflow_task.apply_async(
                        kwargs={
                            "schedule_id": schedule.schedule_id,
                            "scheduled_time": schedule.next_run_time.isoformat()
                            if schedule.next_run_time
                            else now.isoformat(),
                            "storage_config": self._storage_config,
                        },
                        queue="pyworkflow.schedules",
                    )

                    logger.info(
                        f"Triggered scheduled workflow: {schedule.workflow_name}",
                        schedule_id=schedule.schedule_id,
                        next_run=next_run_time.isoformat() if next_run_time else None,
                    )
                else:
                    # Record skip and update next run time
                    schedule.skipped_runs += 1
                    next_run_time = calculate_next_run_time(
                        schedule.spec,
                        last_run=schedule.next_run_time,
                        now=now,
                    )
                    schedule.next_run_time = next_run_time
                    schedule.updated_at = datetime.now(UTC)
                    await storage.update_schedule(schedule)

                    logger.info(
                        f"Skipped scheduled workflow: {schedule.workflow_name} ({reason})",
                        schedule_id=schedule.schedule_id,
                    )

            except Exception as e:
                logger.error(
                    f"Error processing schedule {schedule.schedule_id}: {e}",
                )

    async def _check_overlap_policy(
        self,
        schedule: Schedule,
        storage: StorageBackend,
    ) -> tuple[bool, str | None]:
        """
        Check if schedule should run based on overlap policy.

        Args:
            schedule: The schedule to check
            storage: Storage backend

        Returns:
            Tuple of (should_run, reason_if_not)
        """
        # No running runs means we can always run
        if not schedule.running_run_ids:
            return True, None

        policy = schedule.overlap_policy

        if policy == OverlapPolicy.ALLOW_ALL:
            return True, None

        elif policy == OverlapPolicy.SKIP:
            return False, "Previous run still active (SKIP policy)"

        elif policy == OverlapPolicy.BUFFER_ONE:
            if schedule.buffered_count >= 1:
                return False, "Buffer full (BUFFER_ONE policy)"
            # Increment buffer count
            schedule.buffered_count += 1
            await storage.update_schedule(schedule)
            return True, None

        elif policy == OverlapPolicy.BUFFER_ALL:
            # Always allow, buffered_count tracks pending runs
            schedule.buffered_count += 1
            await storage.update_schedule(schedule)
            return True, None

        elif policy == OverlapPolicy.CANCEL_OTHER:
            # Cancel running runs
            from pyworkflow.primitives.cancel import cancel_workflow

            for run_id in schedule.running_run_ids:
                try:
                    await cancel_workflow(
                        run_id,
                        reason="Cancelled by CANCEL_OTHER overlap policy",
                        storage=storage,
                    )
                except Exception as e:
                    logger.warning(f"Failed to cancel run {run_id}: {e}")

            # Clear the running runs list
            schedule.running_run_ids = []
            await storage.update_schedule(schedule)
            return True, None

        # Default: allow
        return True, None

    def _get_storage(self) -> StorageBackend | None:
        """Get or create the storage backend."""
        if self._storage is not None:
            return self._storage

        # Try to get storage config from environment or defaults
        if self._storage_config:
            self._storage = config_to_storage(self._storage_config)
            return self._storage

        # Try default file storage
        import os

        storage_type = os.getenv("PYWORKFLOW_STORAGE_BACKEND", "file")
        storage_path = os.getenv("PYWORKFLOW_STORAGE_PATH", "./pyworkflow_data")

        if storage_type == "file":
            from pyworkflow.storage.file import FileStorageBackend

            self._storage = FileStorageBackend(storage_path)
        elif storage_type == "memory":
            from pyworkflow.storage.memory import InMemoryStorageBackend

            self._storage = InMemoryStorageBackend()
        else:
            logger.warning(f"Unknown storage type: {storage_type}")
            return None

        return self._storage

    @property
    def info(self) -> str:
        """Return scheduler info string."""
        return f"PyWorkflowScheduler (sync_interval={self.sync_interval}s)"
