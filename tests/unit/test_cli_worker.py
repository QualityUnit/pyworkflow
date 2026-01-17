"""
Unit tests for CLI worker commands.
"""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from pyworkflow.cli.commands.worker import worker


class TestRunWorkerCommand:
    """Tests for the run_worker CLI command."""

    @pytest.fixture
    def runner(self):
        """Create a CLI test runner."""
        return CliRunner()

    @pytest.fixture
    def mock_celery_app(self):
        """Mock the Celery app creation and worker_main."""
        with patch("pyworkflow.celery.app.create_celery_app") as mock_create:
            mock_app = MagicMock()
            mock_create.return_value = mock_app
            yield mock_app

    @pytest.fixture
    def mock_discovery(self):
        """Mock workflow discovery."""
        with patch("pyworkflow.cli.utils.discovery.discover_workflows") as mock:
            yield mock

    @pytest.fixture
    def mock_list_functions(self):
        """Mock list_workflows and list_steps."""
        with patch("pyworkflow.list_workflows") as mock_workflows, patch(
            "pyworkflow.list_steps"
        ) as mock_steps:
            mock_workflows.return_value = {}
            mock_steps.return_value = {}
            yield mock_workflows, mock_steps

    def test_default_queues(self, runner, mock_celery_app, mock_discovery, mock_list_functions):
        """Default invocation uses all PyWorkflow queues."""
        runner.invoke(worker, ["run"], obj={"config": {}, "module": None})

        # Check worker_main was called
        mock_celery_app.worker_main.assert_called_once()
        args = mock_celery_app.worker_main.call_args[1]["argv"]

        # Verify default queues are included
        queue_arg = next(arg for arg in args if arg.startswith("--queues="))
        assert "pyworkflow.default" in queue_arg
        assert "pyworkflow.workflows" in queue_arg
        assert "pyworkflow.steps" in queue_arg
        assert "pyworkflow.schedules" in queue_arg

    def test_workflow_queue_flag(
        self, runner, mock_celery_app, mock_discovery, mock_list_functions
    ):
        """--workflow flag selects only workflows queue."""
        runner.invoke(worker, ["run", "--workflow"], obj={"config": {}, "module": None})

        mock_celery_app.worker_main.assert_called_once()
        args = mock_celery_app.worker_main.call_args[1]["argv"]

        queue_arg = next(arg for arg in args if arg.startswith("--queues="))
        assert queue_arg == "--queues=pyworkflow.workflows"

    def test_step_queue_flag(self, runner, mock_celery_app, mock_discovery, mock_list_functions):
        """--step flag selects only steps queue."""
        runner.invoke(worker, ["run", "--step"], obj={"config": {}, "module": None})

        mock_celery_app.worker_main.assert_called_once()
        args = mock_celery_app.worker_main.call_args[1]["argv"]

        queue_arg = next(arg for arg in args if arg.startswith("--queues="))
        assert queue_arg == "--queues=pyworkflow.steps"

    def test_schedule_queue_flag(
        self, runner, mock_celery_app, mock_discovery, mock_list_functions
    ):
        """--schedule flag selects only schedules queue."""
        runner.invoke(worker, ["run", "--schedule"], obj={"config": {}, "module": None})

        mock_celery_app.worker_main.assert_called_once()
        args = mock_celery_app.worker_main.call_args[1]["argv"]

        queue_arg = next(arg for arg in args if arg.startswith("--queues="))
        assert queue_arg == "--queues=pyworkflow.schedules"

    def test_multiple_queue_flags(
        self, runner, mock_celery_app, mock_discovery, mock_list_functions
    ):
        """Multiple queue flags can be combined."""
        runner.invoke(
            worker, ["run", "--workflow", "--step"], obj={"config": {}, "module": None}
        )

        mock_celery_app.worker_main.assert_called_once()
        args = mock_celery_app.worker_main.call_args[1]["argv"]

        queue_arg = next(arg for arg in args if arg.startswith("--queues="))
        assert "pyworkflow.workflows" in queue_arg
        assert "pyworkflow.steps" in queue_arg

    def test_autoscale_option(self, runner, mock_celery_app, mock_discovery, mock_list_functions):
        """--autoscale option is passed to Celery."""
        runner.invoke(
            worker, ["run", "--autoscale", "2,10"], obj={"config": {}, "module": None}
        )

        mock_celery_app.worker_main.assert_called_once()
        args = mock_celery_app.worker_main.call_args[1]["argv"]

        assert "--autoscale=2,10" in args

    def test_max_tasks_per_child_option(
        self, runner, mock_celery_app, mock_discovery, mock_list_functions
    ):
        """--max-tasks-per-child option is passed to Celery."""
        runner.invoke(
            worker, ["run", "--max-tasks-per-child", "100"], obj={"config": {}, "module": None}
        )

        mock_celery_app.worker_main.assert_called_once()
        args = mock_celery_app.worker_main.call_args[1]["argv"]

        assert "--max-tasks-per-child=100" in args

    def test_prefetch_multiplier_option(
        self, runner, mock_celery_app, mock_discovery, mock_list_functions
    ):
        """--prefetch-multiplier option is passed to Celery."""
        runner.invoke(
            worker, ["run", "--prefetch-multiplier", "4"], obj={"config": {}, "module": None}
        )

        mock_celery_app.worker_main.assert_called_once()
        args = mock_celery_app.worker_main.call_args[1]["argv"]

        assert "--prefetch-multiplier=4" in args

    def test_time_limit_option(self, runner, mock_celery_app, mock_discovery, mock_list_functions):
        """--time-limit option is passed to Celery."""
        runner.invoke(
            worker, ["run", "--time-limit", "300"], obj={"config": {}, "module": None}
        )

        mock_celery_app.worker_main.assert_called_once()
        args = mock_celery_app.worker_main.call_args[1]["argv"]

        assert "--time-limit=300.0" in args

    def test_soft_time_limit_option(
        self, runner, mock_celery_app, mock_discovery, mock_list_functions
    ):
        """--soft-time-limit option is passed to Celery."""
        runner.invoke(
            worker, ["run", "--soft-time-limit", "250"], obj={"config": {}, "module": None}
        )

        mock_celery_app.worker_main.assert_called_once()
        args = mock_celery_app.worker_main.call_args[1]["argv"]

        assert "--soft-time-limit=250.0" in args

    def test_extra_args_passed_through(
        self, runner, mock_celery_app, mock_discovery, mock_list_functions
    ):
        """Extra args after -- are passed to Celery."""
        runner.invoke(
            worker,
            ["run", "--", "--max-memory-per-child=200000", "--without-heartbeat"],
            obj={"config": {}, "module": None},
        )

        mock_celery_app.worker_main.assert_called_once()
        args = mock_celery_app.worker_main.call_args[1]["argv"]

        assert "--max-memory-per-child=200000" in args
        assert "--without-heartbeat" in args

    def test_combined_options_and_extra_args(
        self, runner, mock_celery_app, mock_discovery, mock_list_functions
    ):
        """PyWorkflow options and extra args can be combined."""
        runner.invoke(
            worker,
            ["run", "--step", "--autoscale", "2,8", "--", "--max-memory-per-child=150000"],
            obj={"config": {}, "module": None},
        )

        mock_celery_app.worker_main.assert_called_once()
        args = mock_celery_app.worker_main.call_args[1]["argv"]

        # Check PyWorkflow options
        queue_arg = next(arg for arg in args if arg.startswith("--queues="))
        assert queue_arg == "--queues=pyworkflow.steps"
        assert "--autoscale=2,8" in args

        # Check extra args
        assert "--max-memory-per-child=150000" in args

    def test_concurrency_option(
        self, runner, mock_celery_app, mock_discovery, mock_list_functions
    ):
        """--concurrency option is passed to Celery."""
        runner.invoke(
            worker, ["run", "--concurrency", "4"], obj={"config": {}, "module": None}
        )

        mock_celery_app.worker_main.assert_called_once()
        args = mock_celery_app.worker_main.call_args[1]["argv"]

        assert "--concurrency=4" in args

    def test_loglevel_option(self, runner, mock_celery_app, mock_discovery, mock_list_functions):
        """--loglevel option is passed to Celery in uppercase."""
        runner.invoke(
            worker, ["run", "--loglevel", "debug"], obj={"config": {}, "module": None}
        )

        mock_celery_app.worker_main.assert_called_once()
        args = mock_celery_app.worker_main.call_args[1]["argv"]

        assert "--loglevel=DEBUG" in args

    def test_pool_option(self, runner, mock_celery_app, mock_discovery, mock_list_functions):
        """--pool option is passed to Celery."""
        runner.invoke(
            worker, ["run", "--pool", "solo"], obj={"config": {}, "module": None}
        )

        mock_celery_app.worker_main.assert_called_once()
        args = mock_celery_app.worker_main.call_args[1]["argv"]

        assert "--pool=solo" in args

    def test_hostname_option(self, runner, mock_celery_app, mock_discovery, mock_list_functions):
        """--hostname option is passed to Celery."""
        runner.invoke(
            worker, ["run", "--hostname", "my-worker@host"], obj={"config": {}, "module": None}
        )

        mock_celery_app.worker_main.assert_called_once()
        args = mock_celery_app.worker_main.call_args[1]["argv"]

        assert "--hostname=my-worker@host" in args

    def test_beat_option(self, runner, mock_celery_app, mock_discovery, mock_list_functions):
        """--beat option adds beat and scheduler args."""
        runner.invoke(worker, ["run", "--beat"], obj={"config": {}, "module": None})

        mock_celery_app.worker_main.assert_called_once()
        args = mock_celery_app.worker_main.call_args[1]["argv"]

        assert "--beat" in args
        assert "--scheduler=pyworkflow.celery.scheduler:PyWorkflowScheduler" in args

    def test_queues_always_added(
        self, runner, mock_celery_app, mock_discovery, mock_list_functions
    ):
        """PyWorkflow queues are always added even when extra args are present."""
        runner.invoke(
            worker,
            ["run", "--", "--max-memory-per-child=200000"],
            obj={"config": {}, "module": None},
        )

        mock_celery_app.worker_main.assert_called_once()
        args = mock_celery_app.worker_main.call_args[1]["argv"]

        # Verify queues are still added
        queue_arg = next(arg for arg in args if arg.startswith("--queues="))
        assert "pyworkflow.default" in queue_arg
        assert "pyworkflow.workflows" in queue_arg
        assert "pyworkflow.steps" in queue_arg
        assert "pyworkflow.schedules" in queue_arg
