"""
Unit tests for the WorkflowRunStrategy execution strategy.

Tests that:
- DISTRIBUTED is the default, so existing runs keep dispatching
- ONE_THREAD runs every step inline even on the Celery runtime
- force_local still opts a single step out of the DISTRIBUTED default
- the strategy resolves start() > @workflow > DISTRIBUTED
- the strategy survives Celery transport as its serialised str value
"""

from unittest.mock import AsyncMock, patch

import pytest

from pyworkflow.aws.context import AWSWorkflowContext
from pyworkflow.context import LocalContext, set_context
from pyworkflow.context.aws import AWSContext
from pyworkflow.context.mock import MockContext
from pyworkflow.core.exceptions import SuspensionSignal
from pyworkflow.core.registry import _registry
from pyworkflow.core.step import step
from pyworkflow.core.strategy import (
    DEFAULT_WORKFLOW_RUN_STRATEGY,
    WorkflowRunStrategy,
    coerce_workflow_run_strategy,
)
from pyworkflow.core.workflow import execute_workflow_with_context, workflow
from pyworkflow.storage.file import FileStorageBackend


def _celery_ctx(tmp_path, run_id: str, strategy: WorkflowRunStrategy) -> LocalContext:
    """A durable context that believes it runs on Celery, on the given strategy."""
    ctx = LocalContext(
        run_id=run_id,
        workflow_name="test_workflow",
        storage=FileStorageBackend(base_path=str(tmp_path)),
    )
    ctx._runtime = "celery"
    ctx._storage_config = {"backend": "file", "base_path": str(tmp_path)}
    ctx._workflow_run_strategy = strategy
    return ctx


class TestStrategyDefaults:
    """The strategy defaults to DISTRIBUTED so nothing changes for existing runs."""

    def test_default_is_distributed(self):
        assert DEFAULT_WORKFLOW_RUN_STRATEGY is WorkflowRunStrategy.DISTRIBUTED

    def test_context_defaults_to_distributed(self):
        ctx = LocalContext(run_id="ctx_default", workflow_name="w", durable=False)
        assert ctx.workflow_run_strategy is WorkflowRunStrategy.DISTRIBUTED

    @pytest.mark.parametrize(
        "context_class",
        [MockContext, AWSContext, AWSWorkflowContext],
    )
    def test_every_context_answers_the_strategy(self, context_class):
        """The @step decorator reads ctx.workflow_run_strategy off whatever
        WorkflowContext is active, so every subclass has to answer it. Declaring
        it only on LocalContext raised AttributeError on the others, exactly as
        ctx.runtime would if it were not on the base."""
        assert hasattr(context_class, "workflow_run_strategy")
        assert context_class.workflow_run_strategy.fget(None) is WorkflowRunStrategy.DISTRIBUTED

    def test_workflow_without_strategy_declares_none(self):
        @workflow(name="ees_undeclared")
        async def undeclared():
            return "ok"

        meta = _registry.get_workflow("ees_undeclared")
        assert meta is not None
        assert meta.workflow_run_strategy is None
        assert undeclared.__workflow_run_strategy__ is None


class TestStrategyRegistration:
    """@workflow(workflow_run_strategy=...) reaches the registry and the wrapper."""

    def test_declared_strategy_is_registered(self):
        @workflow(name="ees_declared", workflow_run_strategy=WorkflowRunStrategy.ONE_THREAD)
        async def declared():
            return "ok"

        meta = _registry.get_workflow("ees_declared")
        assert meta is not None
        assert meta.workflow_run_strategy is WorkflowRunStrategy.ONE_THREAD
        assert declared.__workflow_run_strategy__ is WorkflowRunStrategy.ONE_THREAD


class TestStrategyCoercion:
    """The strategy travels over Celery as a str and is rebuilt on the far side."""

    def test_str_value_round_trips(self):
        for member in WorkflowRunStrategy:
            assert coerce_workflow_run_strategy(member.value) is member

    def test_member_passes_through(self):
        assert (
            coerce_workflow_run_strategy(WorkflowRunStrategy.ONE_THREAD)
            is WorkflowRunStrategy.ONE_THREAD
        )

    def test_none_stays_none(self):
        assert coerce_workflow_run_strategy(None) is None

    def test_unknown_value_falls_back_to_none(self):
        # A newer producer naming a strategy this worker does not know must not
        # kill the run; it falls back to the resolution chain's next source.
        assert coerce_workflow_run_strategy("teleportation") is None


class TestOneThreadSkipsDispatch:
    """ONE_THREAD runs steps inline even where DISTRIBUTED would dispatch."""

    @pytest.mark.asyncio
    async def test_one_thread_runs_regular_step_inline(self, tmp_path):
        executed = False

        @step(name="ees_one_thread_inline", force_local=False)
        async def regular_step():
            nonlocal executed
            executed = True
            return "inline_result"

        set_context(_celery_ctx(tmp_path, "run_one_thread", WorkflowRunStrategy.ONE_THREAD))
        try:
            assert await regular_step() == "inline_result"
            assert executed is True
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_distributed_still_dispatches_regular_step(self, tmp_path):
        @step(name="ees_distributed_dispatch", force_local=False)
        async def regular_step():
            return "should_not_reach"

        set_context(_celery_ctx(tmp_path, "run_distributed", WorkflowRunStrategy.DISTRIBUTED))
        try:
            with (
                patch(
                    "pyworkflow.core.step._dispatch_step_to_celery",
                    new_callable=AsyncMock,
                    side_effect=SuspensionSignal(reason="step_dispatch:test", step_id="test"),
                ),
                pytest.raises(SuspensionSignal),
            ):
                await regular_step()
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_force_local_still_opts_out_under_distributed(self, tmp_path):
        """The per-step override keeps working; ONE_THREAD did not replace it."""
        executed = False

        @step(name="ees_force_local_under_distributed", force_local=True)
        async def local_step():
            nonlocal executed
            executed = True
            return "inline_result"

        set_context(_celery_ctx(tmp_path, "run_fl_dist", WorkflowRunStrategy.DISTRIBUTED))
        try:
            assert await local_step() == "inline_result"
            assert executed is True
        finally:
            set_context(None)


class TestStrategyResolutionOrder:
    """start() beats @workflow, which beats the DISTRIBUTED default."""

    @pytest.mark.asyncio
    async def test_declared_strategy_reaches_the_running_context(self, tmp_path):
        seen: list[WorkflowRunStrategy] = []

        @workflow(
            name="ees_resolve_declared",
            workflow_run_strategy=WorkflowRunStrategy.ONE_THREAD,
        )
        async def declared_wf():
            from pyworkflow.context import get_context

            seen.append(get_context().workflow_run_strategy)
            return "ok"

        await execute_workflow_with_context(
            workflow_func=declared_wf,
            run_id="run_resolve_declared",
            workflow_name="ees_resolve_declared",
            storage=FileStorageBackend(base_path=str(tmp_path)),
            args=(),
            kwargs={},
        )
        assert seen == [WorkflowRunStrategy.ONE_THREAD]

    @pytest.mark.asyncio
    async def test_start_argument_overrides_the_declaration(self, tmp_path):
        seen: list[WorkflowRunStrategy] = []

        @workflow(
            name="ees_resolve_override",
            workflow_run_strategy=WorkflowRunStrategy.ONE_THREAD,
        )
        async def declared_wf():
            from pyworkflow.context import get_context

            seen.append(get_context().workflow_run_strategy)
            return "ok"

        await execute_workflow_with_context(
            workflow_func=declared_wf,
            run_id="run_resolve_override",
            workflow_name="ees_resolve_override",
            storage=FileStorageBackend(base_path=str(tmp_path)),
            args=(),
            kwargs={},
            workflow_run_strategy=WorkflowRunStrategy.DISTRIBUTED,
        )
        assert seen == [WorkflowRunStrategy.DISTRIBUTED]

    @pytest.mark.asyncio
    async def test_serialised_value_from_a_persisted_run_resolves(self, tmp_path):
        """A resume hands back the str value read out of input_kwargs."""
        seen: list[WorkflowRunStrategy] = []

        @workflow(name="ees_resolve_from_str")
        async def plain_wf():
            from pyworkflow.context import get_context

            seen.append(get_context().workflow_run_strategy)
            return "ok"

        await execute_workflow_with_context(
            workflow_func=plain_wf,
            run_id="run_resolve_from_str",
            workflow_name="ees_resolve_from_str",
            storage=FileStorageBackend(base_path=str(tmp_path)),
            args=(),
            kwargs={},
            workflow_run_strategy=WorkflowRunStrategy.ONE_THREAD.value,
        )
        assert seen == [WorkflowRunStrategy.ONE_THREAD]

    @pytest.mark.asyncio
    async def test_undeclared_workflow_falls_back_to_distributed(self, tmp_path):
        seen: list[WorkflowRunStrategy] = []

        @workflow(name="ees_resolve_fallback")
        async def plain_wf():
            from pyworkflow.context import get_context

            seen.append(get_context().workflow_run_strategy)
            return "ok"

        await execute_workflow_with_context(
            workflow_func=plain_wf,
            run_id="run_resolve_fallback",
            workflow_name="ees_resolve_fallback",
            storage=FileStorageBackend(base_path=str(tmp_path)),
            args=(),
            kwargs={},
        )
        assert seen == [WorkflowRunStrategy.DISTRIBUTED]
