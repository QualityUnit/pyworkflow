"""
Integration tests for list_runs keyset pagination and summary projection (issue #482).

Run against a real SQLite database so we exercise the actual SQL (row-value cursor comparison,
ORDER BY created_at DESC, run_id DESC, and the summary column projection) rather than mocks.
"""

from datetime import UTC, datetime

import pytest

from pyworkflow.storage.schemas import RunStatus, WorkflowRun
from pyworkflow.storage.sqlite import SQLiteStorageBackend


@pytest.fixture
async def storage(tmp_path):
    """Real SQLite backend backed by a temp file."""
    backend = SQLiteStorageBackend(db_path=str(tmp_path / "runs.db"))
    await backend.connect()
    yield backend
    await backend.disconnect()


async def _make_run(storage, run_id: str, created_at: datetime, **kwargs) -> None:
    run = WorkflowRun(
        run_id=run_id,
        workflow_name="wf",
        status=RunStatus.COMPLETED,
        created_at=created_at,
        updated_at=created_at,
        **kwargs,
    )
    await storage.create_run(run)


@pytest.mark.asyncio
async def test_list_runs_keyset_pagination_handles_tied_created_at(storage):
    """Rows sharing one created_at must each appear exactly once across cursor pages.

    The old `created_at < cursor.created_at` predicate skipped/duplicated rows on ties; the keyset
    `(created_at, run_id)` predicate must page through all of them.
    """
    ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    # Five runs, all with the SAME created_at — the pathological tie case.
    run_ids = {f"run_{i}" for i in range(5)}
    for run_id in run_ids:
        await _make_run(storage, run_id, ts)

    seen: list[str] = []
    cursor = None
    for _ in range(10):  # generous upper bound; should terminate well before this
        runs, cursor = await storage.list_runs(limit=2, cursor=cursor)
        seen.extend(r.run_id for r in runs)
        if cursor is None:
            break

    assert sorted(seen) == sorted(run_ids)  # every row exactly once, no skips/dupes
    assert len(seen) == len(set(seen))


@pytest.mark.asyncio
async def test_list_runs_returns_summary_without_heavy_payload(storage):
    """list_runs omits the heavy payload columns; they come back as defaults, error survives."""
    ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    await _make_run(
        storage,
        "run_heavy",
        ts,
        input_args='["big"]',
        input_kwargs='{"k": "v"}',
        result='{"r": 1}',
        error="boom",
        context={"meta": "data"},
    )

    runs, _ = await storage.list_runs(limit=10)

    assert len(runs) == 1
    summary = runs[0]
    # Heavy payload columns are not fetched -> placeholder defaults.
    assert summary.input_args == "[]"
    assert summary.input_kwargs == "{}"
    assert summary.result is None
    assert summary.context == {}
    # Lightweight fields used by the list view survive.
    assert summary.error == "boom"
    assert summary.status == RunStatus.COMPLETED

    # get_run still returns the full payload.
    full = await storage.get_run("run_heavy")
    assert full.input_args == '["big"]'
    assert full.result == '{"r": 1}'
    assert full.context == {"meta": "data"}
