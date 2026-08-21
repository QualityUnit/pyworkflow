"""Execution strategy for a workflow run.

Controls whether the engine dispatches each step to a Celery step worker or
runs every step inline in the workflow task. See :class:`WorkflowRunStrategy`.
"""

from enum import Enum


class WorkflowRunStrategy(Enum):
    """How a workflow run executes its steps.

    ``DISTRIBUTED`` is the default and the historical behaviour: on the Celery
    runtime every step is dispatched to a step worker, which suspends the
    workflow and replays it from the event log on resume. A step declaring
    ``force_local=True`` still opts out and runs inline.

    ``ONE_THREAD`` runs every step inline in the workflow task, so a run
    completes in a single pass with no broker round trip and no replay between
    steps. ``force_local`` becomes redundant under it: the whole run is already
    local.

    The trade is durability granularity against latency. Under ``DISTRIBUTED`` a
    lost worker resumes from the last completed step; under ``ONE_THREAD`` the
    run restarts from its last suspension point. Prefer ``ONE_THREAD`` for short
    runs whose steps are cheap, where per-step dispatch costs more than the work
    it distributes.
    """

    DISTRIBUTED = "distributed"
    ONE_THREAD = "one_thread"


DEFAULT_WORKFLOW_RUN_STRATEGY = WorkflowRunStrategy.DISTRIBUTED
"""Strategy applied when neither ``start()`` nor ``@workflow`` names one."""


def coerce_workflow_run_strategy(
    value: "WorkflowRunStrategy | str | None",
) -> WorkflowRunStrategy | None:
    """Normalise a strategy that may arrive as its serialised ``str`` value.

    Enum members do not survive Celery transport, so the strategy travels as
    ``WorkflowRunStrategy.value`` and is rebuilt on the far side. An unknown
    value falls back to ``None`` rather than raising: a run must not die because
    a newer producer named a strategy this worker does not know yet.
    """
    if value is None or isinstance(value, WorkflowRunStrategy):
        return value
    try:
        return WorkflowRunStrategy(value)
    except ValueError:
        return None
