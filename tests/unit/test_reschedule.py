"""
Unit tests for the SIGTERM handoff (pyworkflow/celery/reschedule.py).

SIGTERM must run Celery's soft + cold shutdown (wait for running tasks, then
terminate them and let the broker redeliver each one once), not re-enqueue
copies while the original keeps running (#733). The end-to-end behaviour is
covered by tests/integration/test_reschedule_e2e.py.
"""

import threading
from unittest.mock import MagicMock, patch

import pytest
from celery.apps import worker as celery_worker
from celery.concurrency.prefork import TaskPool

from pyworkflow.celery import reschedule


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("PYWORKFLOW_RESCHEDULE_ON_SIGTERM", raising=False)
    monkeypatch.delenv("PYWORKFLOW_SOFT_SHUTDOWN_TIMEOUT", raising=False)
    monkeypatch.setattr(celery_worker, "REMAP_SIGTERM", None)
    monkeypatch.setattr(reschedule, "_is_worker_stopping", lambda: False)


def _prefork_worker() -> MagicMock:
    worker = MagicMock()
    worker.pool = MagicMock(spec=TaskPool)
    return worker


class TestSoftShutdownConfig:
    def test_default_timeout(self):
        assert reschedule.soft_shutdown_config() == {
            "worker_soft_shutdown_timeout": reschedule.DEFAULT_SOFT_SHUTDOWN_TIMEOUT
        }

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("45", 45.0), ("2.5", 2.5), ("0", 0.0), ("-3", 0.0), (" 7 ", 7.0)],
    )
    def test_timeout_from_env(self, monkeypatch, raw, expected):
        monkeypatch.setenv("PYWORKFLOW_SOFT_SHUTDOWN_TIMEOUT", raw)
        assert reschedule.soft_shutdown_timeout() == expected

    def test_invalid_timeout_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("PYWORKFLOW_SOFT_SHUTDOWN_TIMEOUT", "soon")
        assert reschedule.soft_shutdown_timeout() == reschedule.DEFAULT_SOFT_SHUTDOWN_TIMEOUT

    @pytest.mark.parametrize("value", ["0", "false", "no", "FALSE", " No "])
    def test_disabled_leaves_celery_defaults(self, monkeypatch, value):
        monkeypatch.setenv("PYWORKFLOW_RESCHEDULE_ON_SIGTERM", value)
        assert reschedule.soft_shutdown_config() == {}

    def test_app_gets_soft_shutdown_timeout(self, monkeypatch):
        from pyworkflow.celery.app import create_celery_app

        monkeypatch.setenv("PYWORKFLOW_SOFT_SHUTDOWN_TIMEOUT", "12")
        app = create_celery_app(broker_url="memory://")
        assert app.conf.worker_soft_shutdown_timeout == 12.0


class TestConnectionLossConfig:
    """A broker reconnect redelivers unacked messages; the originals must stop."""

    def test_cancels_running_tasks_on_connection_loss_by_default(self, monkeypatch):
        from pyworkflow.celery.app import create_celery_app

        monkeypatch.delenv("PYWORKFLOW_CANCEL_TASKS_ON_CONNECTION_LOSS", raising=False)
        app = create_celery_app(broker_url="memory://")
        assert app.conf.worker_cancel_long_running_tasks_on_connection_loss is True

    @pytest.mark.parametrize("value", ["0", "false", "no"])
    def test_opt_out(self, monkeypatch, value):
        monkeypatch.setenv("PYWORKFLOW_CANCEL_TASKS_ON_CONNECTION_LOSS", value)
        assert reschedule.connection_loss_config() == {
            "worker_cancel_long_running_tasks_on_connection_loss": False
        }


class TestInstallSigtermHandoff:
    def test_installs_cold_shutdown_handler_on_sigterm(self):
        worker = _prefork_worker()
        with patch.object(celery_worker, "install_worker_term_hard_handler") as install:
            assert reschedule.install_sigterm_handoff(worker) is True
        install.assert_called_once_with(worker, sig="SIGTERM", callback=reschedule._on_sigterm)

    def test_disabled_keeps_warm_shutdown(self, monkeypatch):
        monkeypatch.setenv("PYWORKFLOW_RESCHEDULE_ON_SIGTERM", "0")
        with patch.object(celery_worker, "install_worker_term_hard_handler") as install:
            assert reschedule.install_sigterm_handoff(_prefork_worker()) is False
        install.assert_not_called()

    def test_remap_sigterm_already_handled_by_celery(self, monkeypatch):
        monkeypatch.setattr(celery_worker, "REMAP_SIGTERM", "SIGQUIT")
        with patch.object(celery_worker, "install_worker_term_hard_handler") as install:
            assert reschedule.install_sigterm_handoff(_prefork_worker()) is False
        install.assert_not_called()

    def test_non_prefork_pool_is_skipped(self):
        worker = MagicMock()
        worker.pool = object()
        with patch.object(celery_worker, "install_worker_term_hard_handler") as install:
            assert reschedule.install_sigterm_handoff(worker) is False
        install.assert_not_called()

    def test_not_reinstalled_once_shutting_down(self, monkeypatch):
        # worker_ready fires again on a consumer restart; it must not undo the
        # second-SIGTERM handler installed by _on_sigterm.
        monkeypatch.setattr(reschedule, "_is_worker_stopping", lambda: True)
        with patch.object(celery_worker, "install_worker_term_hard_handler") as install:
            assert reschedule.install_sigterm_handoff(_prefork_worker()) is False
        install.assert_not_called()

    @pytest.mark.parametrize("missing", ["on_cold_shutdown", "during_soft_shutdown"])
    def test_celery_without_soft_shutdown_keeps_warm_shutdown(self, monkeypatch, missing):
        # pyproject allows Celery >= 5.3; soft shutdown only exists from 5.5.
        monkeypatch.delattr(celery_worker, missing)
        with patch.object(celery_worker, "install_worker_term_hard_handler") as install:
            assert reschedule.install_sigterm_handoff(_prefork_worker()) is False
        install.assert_not_called()

    def test_off_main_thread_is_skipped(self):
        results = []
        with patch.object(celery_worker, "install_worker_term_hard_handler") as install:
            t = threading.Thread(
                target=lambda: results.append(reschedule.install_sigterm_handoff(_prefork_worker()))
            )
            t.start()
            t.join()
        assert results == [False]
        install.assert_not_called()

    def test_install_errors_are_contained(self):
        with patch.object(
            celery_worker, "install_worker_term_hard_handler", side_effect=RuntimeError("boom")
        ):
            assert reschedule.install_sigterm_handoff(_prefork_worker()) is False

    def test_none_worker(self):
        assert reschedule.install_sigterm_handoff(None) is False


class TestOnSigterm:
    def test_runs_cold_shutdown_and_guards_second_sigterm(self):
        worker = _prefork_worker()
        worker.app.conf.worker_soft_shutdown_timeout = 20.0
        calls = []
        with (
            patch.object(
                celery_worker,
                "install_worker_term_hard_handler",
                side_effect=lambda *_a, **kw: calls.append(("install", kw)),
            ),
            patch.object(
                celery_worker, "on_cold_shutdown", side_effect=lambda w: calls.append(("cold", w))
            ),
        ):
            reschedule._on_sigterm(worker)

        # The second-SIGTERM guard goes in before the (blocking) soft wait starts.
        assert calls == [
            ("install", {"sig": "SIGTERM", "callback": celery_worker.during_soft_shutdown}),
            ("cold", worker),
        ]


def test_worker_ready_installs_handoff_on_controller():
    from pyworkflow.celery.app import on_worker_ready

    consumer = MagicMock()
    with patch.object(reschedule, "install_sigterm_handoff") as install:
        on_worker_ready(sender=consumer)
    install.assert_called_once_with(consumer.controller)
