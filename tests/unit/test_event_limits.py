"""Unit tests for event limit validation."""

import warnings

import pytest
from loguru import logger

from pyworkflow.config import configure, get_config, reset_config
from pyworkflow.context import LocalContext, set_context
from pyworkflow.core.exceptions import EventLimitExceededError
from pyworkflow.engine.events import create_step_completed_event
from pyworkflow.storage.memory import InMemoryStorageBackend


@pytest.fixture
def capture_logs():
    """Fixture to capture loguru logs for testing."""
    captured = []

    def sink(message):
        captured.append(str(message))

    handler_id = logger.add(sink, format="{message}", level="WARNING")
    yield captured
    logger.remove(handler_id)


class TestEventLimitValidation:
    """Test event limit validation."""

    @pytest.fixture(autouse=True)
    def reset_config_fixture(self):
        """Reset config before and after each test."""
        reset_config()
        yield
        reset_config()

    @pytest.mark.asyncio
    async def test_hard_limit_raises_error(self):
        """Test that exceeding hard limit raises EventLimitExceededError."""
        # Configure with low limits for testing
        configure(event_hard_limit=10)

        storage = InMemoryStorageBackend()
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
            durable=True,
        )

        # Add events to reach hard limit
        for i in range(10):
            event = create_step_completed_event(
                run_id="test_run", step_id=f"step_{i}", result="test", step_name="test_step"
            )
            await storage.record_event(event)

        # Validation should raise
        with pytest.raises(EventLimitExceededError) as exc_info:
            await ctx.validate_event_limits()

        assert exc_info.value.event_count == 10
        assert exc_info.value.limit == 10
        assert exc_info.value.run_id == "test_run"

    @pytest.mark.asyncio
    async def test_hard_limit_message(self):
        """Test that EventLimitExceededError has correct message."""
        configure(event_hard_limit=5)

        storage = InMemoryStorageBackend()
        ctx = LocalContext(
            run_id="my_run",
            workflow_name="test_workflow",
            storage=storage,
            durable=True,
        )

        # Add events to reach hard limit
        for i in range(5):
            event = create_step_completed_event(
                run_id="my_run", step_id=f"step_{i}", result="test", step_name="test_step"
            )
            await storage.record_event(event)

        with pytest.raises(EventLimitExceededError) as exc_info:
            await ctx.validate_event_limits()

        assert "my_run" in str(exc_info.value)
        assert "5 >= 5" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_soft_limit_logs_warning(self, capture_logs):
        """Test that reaching soft limit logs warning."""
        configure(event_soft_limit=5, event_hard_limit=100)

        storage = InMemoryStorageBackend()
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
            durable=True,
        )

        # Add events to reach soft limit
        for i in range(5):
            event = create_step_completed_event(
                run_id="test_run", step_id=f"step_{i}", result="test", step_name="test_step"
            )
            await storage.record_event(event)

        # Validation should log warning
        await ctx.validate_event_limits()

        # Check captured logs
        log_text = "\n".join(capture_logs)
        assert "approaching event limit" in log_text
        assert "5/100" in log_text

    @pytest.mark.asyncio
    async def test_below_soft_limit_no_warning(self, capture_logs):
        """Test that below soft limit does not log warning."""
        configure(event_soft_limit=10, event_hard_limit=100)

        storage = InMemoryStorageBackend()
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
            durable=True,
        )

        # Add events below soft limit
        for i in range(5):
            event = create_step_completed_event(
                run_id="test_run", step_id=f"step_{i}", result="test", step_name="test_step"
            )
            await storage.record_event(event)

        # Validation should not log warning
        await ctx.validate_event_limits()

        # Check captured logs
        log_text = "\n".join(capture_logs)
        assert "approaching event limit" not in log_text

    @pytest.mark.asyncio
    async def test_warning_interval(self, capture_logs):
        """Test warnings are logged every N events after soft limit."""
        configure(event_soft_limit=5, event_hard_limit=100, event_warning_interval=3)

        storage = InMemoryStorageBackend()
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
            durable=True,
        )
        set_context(ctx)

        try:
            # Add 5 events (soft limit)
            for i in range(5):
                event = create_step_completed_event(
                    run_id="test_run", step_id=f"step_{i}", result="test", step_name="test_step"
                )
                await storage.record_event(event)

            # First validation - should warn (at 5)
            await ctx.validate_event_limits()
            log_text = "\n".join(capture_logs)
            assert "approaching event limit" in log_text
            assert "5/100" in log_text

            # Clear captured logs
            capture_logs.clear()

            # Add 2 more events (not at interval yet - 7 events total)
            for i in range(5, 7):
                event = create_step_completed_event(
                    run_id="test_run", step_id=f"step_{i}", result="test", step_name="test_step"
                )
                await storage.record_event(event)

            # Validation should NOT warn (7 < 5 + 3 = 8)
            await ctx.validate_event_limits()
            log_text = "\n".join(capture_logs)
            assert "approaching event limit" not in log_text

            # Add 1 more (now at 8 events, should warn because 8 >= 5 + 3)
            event = create_step_completed_event(
                run_id="test_run", step_id="step_7", result="test", step_name="test_step"
            )
            await storage.record_event(event)

            await ctx.validate_event_limits()
            log_text = "\n".join(capture_logs)
            assert "approaching event limit" in log_text
            assert "8/100" in log_text
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_transient_mode_skips_validation(self):
        """Test that transient mode skips validation."""
        configure(event_hard_limit=1)  # Very low limit

        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            durable=False,  # Transient mode
        )

        # Should not raise even though we would be over the limit
        await ctx.validate_event_limits()  # No error

    @pytest.mark.asyncio
    async def test_no_storage_skips_validation(self):
        """Test that missing storage skips validation."""
        configure(event_hard_limit=1)  # Very low limit

        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,  # No storage
            durable=True,
        )

        # Should not raise - no storage means validation is skipped
        await ctx.validate_event_limits()  # No error

    def test_configure_warns_on_limit_change(self):
        """Test that configure() warns when modifying event limits."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            configure(event_hard_limit=100000)

            assert len(w) == 1
            assert "not recommended" in str(w[0].message)
            assert "event_hard_limit" in str(w[0].message)

    def test_configure_warns_on_multiple_limit_changes(self):
        """Test that configure() warns when modifying multiple event limits."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            configure(event_soft_limit=5000, event_hard_limit=100000)

            assert len(w) == 1
            assert "not recommended" in str(w[0].message)
            # Both should be mentioned
            assert "event_hard_limit" in str(w[0].message)
            assert "event_soft_limit" in str(w[0].message)

    def test_configure_no_warning_for_other_options(self):
        """Test that configure() doesn't warn for non-limit options."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            configure(default_retries=5)

            # No warnings for non-limit options
            assert len(w) == 0


class TestEventLimitDefaults:
    """Test default event limit values."""

    @pytest.fixture(autouse=True)
    def reset_config_fixture(self):
        """Reset config before and after each test."""
        reset_config()
        yield
        reset_config()

    def test_default_soft_limit(self):
        """Test default soft limit is 10,000."""
        config = get_config()
        assert config.event_soft_limit == 10_000

    def test_default_hard_limit(self):
        """Test default hard limit is 50,000."""
        config = get_config()
        assert config.event_hard_limit == 50_000

    def test_default_warning_interval(self):
        """Test default warning interval is 100."""
        config = get_config()
        assert config.event_warning_interval == 100


class TestEventLimitExceededError:
    """Test EventLimitExceededError exception."""

    def test_exception_attributes(self):
        """Test that exception has correct attributes."""
        error = EventLimitExceededError(
            run_id="run_123",
            event_count=50000,
            limit=50000,
        )

        assert error.run_id == "run_123"
        assert error.event_count == 50000
        assert error.limit == 50000

    def test_exception_inherits_from_fatal_error(self):
        """Test that EventLimitExceededError inherits from FatalError."""
        from pyworkflow.core.exceptions import FatalError

        error = EventLimitExceededError(
            run_id="run_123",
            event_count=50000,
            limit=50000,
        )

        assert isinstance(error, FatalError)
