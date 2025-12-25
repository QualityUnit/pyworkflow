"""Workflow run endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.controllers.run_controller import RunController
from app.dependencies import get_storage
from app.schemas.event import EventListResponse
from app.schemas.hook import HookListResponse
from app.schemas.run import RunDetailResponse, RunListResponse, StartRunRequest, StartRunResponse
from app.schemas.step import StepListResponse
from pyworkflow.storage.base import StorageBackend

router = APIRouter()

@router.get("", response_model=RunListResponse)
async def list_runs(
    workflow_name: str | None = Query(None, description="Filter by workflow name"),
    status: str | None = Query(
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


@router.post("", response_model=StartRunResponse, status_code=201)
async def start_run(
        request: StartRunRequest,
        storage: StorageBackend = Depends(get_storage),
) -> StartRunResponse:
    """Start a new workflow run.

    Args:
        request: Start run request with workflow name and kwargs.
        storage: Storage backend (injected).

    Returns:
        StartRunResponse with run_id and workflow_name.

    Raises:
        HTTPException: 404 if workflow not found, 400 for validation errors.
    """
    controller = RunController(storage)
    try:
        return await controller.start_run(request)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


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
