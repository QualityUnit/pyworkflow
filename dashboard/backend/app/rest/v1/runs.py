"""Workflow run endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from pyworkflow.storage.base import StorageBackend

from app.dependencies import get_storage
from app.controllers.run_controller import RunController
from app.schemas.run import RunDetailResponse, RunListResponse
from app.schemas.event import EventListResponse
from app.schemas.step import StepListResponse
from app.schemas.hook import HookListResponse

router = APIRouter()


@router.get("", response_model=RunListResponse)
async def list_runs(
    workflow_name: Optional[str] = Query(None, description="Filter by workflow name"),
    status: Optional[str] = Query(
        None,
        description="Filter by status (pending, running, suspended, completed, failed, interrupted, cancelled)",
    ),
    limit: int = Query(100, ge=1, le=1000, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    storage: StorageBackend = Depends(get_storage),
) -> RunListResponse:
    """List workflow runs with optional filtering.

    Args:
        workflow_name: Filter by workflow name.
        status: Filter by run status.
        limit: Maximum number of results (1-1000).
        offset: Number of results to skip.
        storage: Storage backend (injected).

    Returns:
        RunListResponse with matching runs.
    """
    controller = RunController(storage)
    return await controller.list_runs(
        workflow_name=workflow_name,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get("/{run_id}", response_model=RunDetailResponse)
async def get_run(
    run_id: str,
    storage: StorageBackend = Depends(get_storage),
) -> RunDetailResponse:
    """Get detailed information about a workflow run.

    Args:
        run_id: The run ID.
        storage: Storage backend (injected).

    Returns:
        RunDetailResponse with run details.

    Raises:
        HTTPException: 404 if run not found.
    """
    controller = RunController(storage)
    run = await controller.get_run(run_id)

    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    return run


@router.get("/{run_id}/events", response_model=EventListResponse)
async def get_run_events(
    run_id: str,
    storage: StorageBackend = Depends(get_storage),
) -> EventListResponse:
    """Get all events for a workflow run.

    Args:
        run_id: The run ID.
        storage: Storage backend (injected).

    Returns:
        EventListResponse with run events.
    """
    controller = RunController(storage)

    # Verify run exists
    run = await controller.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    return await controller.get_events(run_id)


@router.get("/{run_id}/steps", response_model=StepListResponse)
async def get_run_steps(
    run_id: str,
    storage: StorageBackend = Depends(get_storage),
) -> StepListResponse:
    """Get all steps for a workflow run.

    Args:
        run_id: The run ID.
        storage: Storage backend (injected).

    Returns:
        StepListResponse with run steps.
    """
    controller = RunController(storage)

    # Verify run exists
    run = await controller.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    return await controller.get_steps(run_id)


@router.get("/{run_id}/hooks", response_model=HookListResponse)
async def get_run_hooks(
    run_id: str,
    storage: StorageBackend = Depends(get_storage),
) -> HookListResponse:
    """Get all hooks for a workflow run.

    Args:
        run_id: The run ID.
        storage: Storage backend (injected).

    Returns:
        HookListResponse with run hooks.
    """
    controller = RunController(storage)

    # Verify run exists
    run = await controller.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    return await controller.get_hooks(run_id)
