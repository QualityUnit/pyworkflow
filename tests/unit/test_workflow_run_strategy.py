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
from pyworkflow.config import configure, reset_config
from pyworkflow.context import LocalContext, set_context
from pyworkflow.context.aws import AWSContext
from pyworkflow.context.mock import MockContext
from pyworkflow.core.exceptions import EventLimitExceededError, SuspensionSignal
from pyworkflow.core.registry import _registry
from pyworkflow.core.step import step
from pyworkflow.core.strategy import (
    DEFAULT_WORKFLOW_RUN_STRATEGY,
    WorkflowRunStrategy,
    coerce_workflow_run_strategy,
    resolve_workflow_run_strategy,
)
from pyworkflow.core.workflow import execute_workflow_with_context, workflow
from pyworkflow.engine.events import EventType
from pyworkflow.primitives.hooks import hook
from pyworkflow.primitives.resume_hook import resume_hook
from pyworkflow.serialization.encoder import serialize_args, serialize_kwargs
from pyworkflow.storage.file import FileStorageBackend
from pyworkflow.storage.memory import InMemoryStorageBackend
from pyworkflow.storage.schemas import RunStatus, WorkflowRun


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


class TestStrategyResolution:
    """resolve_workflow_run_strategy is the single place None is handled:
    requested > declared > default, and it never returns None."""

    def test_requested_member_wins_over_declaration(self):
        assert (
            resolve_workflow_run_strategy(
                WorkflowRunStrategy.ONE_THREAD, WorkflowRunStrategy.DISTRIBUTED
            )
            is WorkflowRunStrategy.ONE_THREAD
        )

    def test_requested_str_wins_over_declaration(self):
        assert (
            resolve_workflow_run_strategy("one_thread", WorkflowRunStrategy.DISTRIBUTED)
            is WorkflowRunStrategy.ONE_THREAD
        )

    def test_none_falls_back_to_declaration(self):
        assert (
            resolve_workflow_run_strategy(None, WorkflowRunStrategy.ONE_THREAD)
            is WorkflowRunStrategy.ONE_THREAD
        )

    def test_nothing_falls_back_to_default(self):
        assert resolve_workflow_run_strategy(None, None) is DEFAULT_WORKFLOW_RUN_STRATEGY
        assert resolve_workflow_run_strategy(None) is DEFAULT_WORKFLOW_RUN_STRATEGY

    def test_unknown_str_falls_back_to_declaration_then_default(self):
        assert (
            resolve_workflow_run_strategy("teleportation", WorkflowRunStrategy.ONE_THREAD)
            is WorkflowRunStrategy.ONE_THREAD
        )
        assert resolve_workflow_run_strategy("teleportation") is DEFAULT_WORKFLOW_RUN_STRATEGY

    @pytest.mark.parametrize("requested", [None, "one_thread", WorkflowRunStrategy.DISTRIBUTED])
    def test_never_returns_none(self, requested):
        assert isinstance(resolve_workflow_run_strategy(requested), WorkflowRunStrategy)


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
            workflow_run_strategy=resolve_workflow_run_strategy(
                None, _registry.get_workflow("ees_resolve_declared").workflow_run_strategy
            ),
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
        """A resume resolves the str read out of input_kwargs at its entry point
        and hands the running context a member."""
        seen: list[WorkflowRunStrategy] = []

        @workflow(name="ees_resolve_from_str")
        async def plain_wf():
            from pyworkflow.context import get_context

            seen.append(get_context().workflow_run_strategy)
            return "ok"

        meta = _registry.get_workflow("ees_resolve_from_str")
        assert meta is not None
        await execute_workflow_with_context(
            workflow_func=plain_wf,
            run_id="run_resolve_from_str",
            workflow_name="ees_resolve_from_str",
            storage=FileStorageBackend(base_path=str(tmp_path)),
            args=(),
            kwargs={},
            workflow_run_strategy=resolve_workflow_run_strategy(
                WorkflowRunStrategy.ONE_THREAD.value, meta.workflow_run_strategy
            ),
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


class TestOneThreadEventPersistence:
    """ONE_THREAD drops STEP_STARTED but keeps STEP_COMPLETED.

    STEP_STARTED only feeds the in-progress tracking that guards re-dispatch,
    and a ONE_THREAD run never dispatches. STEP_COMPLETED is what replay reads
    to skip a step that already ran, so dropping it would re-execute every step
    completed before a suspension — re-emitting its side effects and re-charging
    its cost on every resume.
    """

    @pytest.mark.asyncio
    async def test_one_thread_records_only_completion(self, tmp_path):
        @step(name="ees_events_one_thread")
        async def a_step():
            return "ok"

        ctx = _celery_ctx(tmp_path, "run_ev_one", WorkflowRunStrategy.ONE_THREAD)
        set_context(ctx)
        try:
            await a_step()
        finally:
            set_context(None)

        types = [e.type for e in await ctx.storage.get_events("run_ev_one")]
        assert EventType.STEP_COMPLETED in types
        assert EventType.STEP_STARTED not in types

    @pytest.mark.asyncio
    async def test_distributed_force_local_records_both(self, tmp_path):
        """The DISTRIBUTED path is untouched: a force_local step still records
        both events, which test_force_local.py also pins."""

        @step(name="ees_events_distributed", force_local=True)
        async def a_step():
            return "ok"

        ctx = _celery_ctx(tmp_path, "run_ev_dist", WorkflowRunStrategy.DISTRIBUTED)
        set_context(ctx)
        try:
            await a_step()
        finally:
            set_context(None)

        types = [e.type for e in await ctx.storage.get_events("run_ev_dist")]
        assert EventType.STEP_COMPLETED in types
        assert EventType.STEP_STARTED in types

    @pytest.mark.asyncio
    async def test_step_before_a_hook_is_not_re_executed_on_resume(self, tmp_path):
        """The reason STEP_COMPLETED survives ONE_THREAD. A hook suspends the
        run; on resume the step that already completed must not run again."""
        runs: list[str] = []

        @step(name="ees_pre_hook_step")
        async def pre_hook_step():
            runs.append("ran")
            return "value"

        @workflow(name="ees_hook_wf", workflow_run_strategy=WorkflowRunStrategy.ONE_THREAD)
        async def hook_wf():
            value = await pre_hook_step()
            await hook("ees_ask", timeout="1h")
            return value

        storage = FileStorageBackend(base_path=str(tmp_path))
        with pytest.raises(SuspensionSignal):
            await execute_workflow_with_context(
                workflow_func=hook_wf,
                run_id="run_hook_once",
                workflow_name="ees_hook_wf",
                storage=storage,
                args=(),
                kwargs={},
                runtime="celery",
                workflow_run_strategy=resolve_workflow_run_strategy(
                    None, _registry.get_workflow("ees_hook_wf").workflow_run_strategy
                ),
            )
        assert runs == ["ran"]

        events = await storage.get_events("run_hook_once")
        hook_id = next(e.data["hook_id"] for e in events if e.type == EventType.HOOK_CREATED)
        await resume_hook(f"run_hook_once:{hook_id}", {"answer": 1}, storage=storage)

        result = await execute_workflow_with_context(
            workflow_func=hook_wf,
            run_id="run_hook_once",
            workflow_name="ees_hook_wf",
            storage=storage,
            args=(),
            kwargs={},
            event_log=await storage.get_events("run_hook_once"),
            runtime="celery",
            workflow_run_strategy=resolve_workflow_run_strategy(
                None, _registry.get_workflow("ees_hook_wf").workflow_run_strategy
            ),
        )

        assert result == "value"
        assert runs == ["ran"], "the step before the hook re-executed on resume"


class TestOneThreadRunawayGuard:
    """ONE_THREAD keeps a runaway guard even though it records no STEP_STARTED.

    ``validate_event_limits`` counts the journal, so skipping the event skips the
    guard with it. ``count_inline_step`` replaces it from memory.
    """

    @pytest.fixture(autouse=True)
    def reset_config_fixture(self):
        reset_config()
        yield
        reset_config()

    @pytest.mark.asyncio
    async def test_inline_steps_hit_the_hard_limit(self, tmp_path):
        configure(event_hard_limit=3)

        @step(name="ees_guarded", force_local=False)
        async def guarded_step(index: int):
            return index

        set_context(_celery_ctx(tmp_path, "run_guard", WorkflowRunStrategy.ONE_THREAD))
        try:
            assert await guarded_step(0) == 0
            assert await guarded_step(1) == 1

            with pytest.raises(EventLimitExceededError) as exc_info:
                await guarded_step(2)
        finally:
            set_context(None)

        assert exc_info.value.limit == 3
        assert exc_info.value.run_id == "run_guard"

    @pytest.mark.asyncio
    async def test_guard_counts_steps_from_earlier_passes(self, tmp_path):
        """The guard has to mean "steps in this run", not "steps in this pass".

        A run that suspends repeatedly gets a fresh context each time; if the
        counter restarted with it, a runaway loop would never trip the limit.
        """
        configure(event_hard_limit=3)

        @step(name="ees_guard_replayed", force_local=False)
        async def guarded_step(index: int):
            return index

        storage = FileStorageBackend(base_path=str(tmp_path))
        first = _celery_ctx(tmp_path, "run_guard_replay", WorkflowRunStrategy.ONE_THREAD)
        set_context(first)
        try:
            await guarded_step(0)
            await guarded_step(1)
        finally:
            set_context(None)

        # Resume: a new context replaying the two completed steps
        resumed = LocalContext(
            run_id="run_guard_replay",
            workflow_name="test_workflow",
            storage=storage,
            event_log=await storage.get_events("run_guard_replay"),
        )
        resumed._runtime = "celery"
        resumed._workflow_run_strategy = WorkflowRunStrategy.ONE_THREAD

        set_context(resumed)
        try:
            with pytest.raises(EventLimitExceededError):
                await guarded_step(2)
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_guard_stays_clear_below_the_limit(self, tmp_path):
        configure(event_hard_limit=50)

        @step(name="ees_unguarded", force_local=False)
        async def cheap_step(index: int):
            return index

        set_context(_celery_ctx(tmp_path, "run_no_guard", WorkflowRunStrategy.ONE_THREAD))
        try:
            for i in range(10):
                assert await cheap_step(i) == i
        finally:
            set_context(None)


class TestContinueAsNewCarriesStrategy:
    """A continuation must not silently fall back to DISTRIBUTED."""

    @pytest.mark.asyncio
    async def test_strategy_reaches_the_new_run(self):
        from pyworkflow.celery import tasks as celery_tasks

        @workflow(name="ees_can_strategy")
        async def continued_wf():
            return "ok"

        meta = _registry.get_workflow("ees_can_strategy")
        storage = InMemoryStorageBackend()
        await storage.create_run(
            WorkflowRun(
                run_id="run_can_old",
                workflow_name="ees_can_strategy",
                status=RunStatus.RUNNING,
            )
        )

        with patch.object(celery_tasks, "start_workflow_task") as mock_task:
            await celery_tasks._handle_continue_as_new_celery(
                current_run_id="run_can_old",
                workflow_meta=meta,
                storage=storage,
                storage_config=None,
                new_args=(),
                new_kwargs={},
                workflow_run_strategy=WorkflowRunStrategy.ONE_THREAD,
            )

        _, call_kwargs = mock_task.delay.call_args
        assert call_kwargs["workflow_run_strategy"] == WorkflowRunStrategy.ONE_THREAD.value

    @pytest.mark.asyncio
    async def test_undeclared_run_continues_with_the_default(self):
        """The caller resolves at its entry point; the continuation is sent
        the concrete default, never None."""
        from pyworkflow.celery import tasks as celery_tasks

        @workflow(name="ees_can_undeclared")
        async def continued_wf():
            return "ok"

        meta = _registry.get_workflow("ees_can_undeclared")
        storage = InMemoryStorageBackend()
        await storage.create_run(
            WorkflowRun(
                run_id="run_can_none",
                workflow_name="ees_can_undeclared",
                status=RunStatus.RUNNING,
            )
        )

        with patch.object(celery_tasks, "start_workflow_task") as mock_task:
            await celery_tasks._handle_continue_as_new_celery(
                current_run_id="run_can_none",
                workflow_meta=meta,
                storage=storage,
                storage_config=None,
                new_args=(),
                new_kwargs={},
                workflow_run_strategy=resolve_workflow_run_strategy(
                    None, meta.workflow_run_strategy
                ),
            )

        _, call_kwargs = mock_task.delay.call_args
        assert call_kwargs["workflow_run_strategy"] == DEFAULT_WORKFLOW_RUN_STRATEGY.value


class TestLocalRuntimeResumeIgnoresServiceKwargs:
    """A run started on Celery carries service kwargs in input_kwargs.

    They are not workflow parameters: handing them to the workflow function
    raises TypeError. The Celery resume path pops them; the local one has to too.
    """

    @pytest.mark.asyncio
    async def test_resume_does_not_pass_service_kwargs_to_the_workflow(self):
        from pyworkflow.runtime.local import LocalRuntime

        @workflow(name="ees_local_resume")
        async def resumable_wf(value: str):
            return value

        storage = InMemoryStorageBackend()
        await storage.create_run(
            WorkflowRun(
                run_id="run_local_resume",
                workflow_name="ees_local_resume",
                status=RunStatus.SUSPENDED,
                input_args=serialize_args(),
                input_kwargs=serialize_kwargs(
                    value="carried",
                    _tracing_config=None,
                    _workflow_run_strategy=WorkflowRunStrategy.ONE_THREAD.value,
                ),
            )
        )

        result = await LocalRuntime().resume_workflow("run_local_resume", storage=storage)

        assert result == "carried"
