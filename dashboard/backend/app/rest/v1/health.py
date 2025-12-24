"""Health check endpoint."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.dependencies import get_storage
from pyworkflow.storage.base import StorageBackend

router = APIRouter()


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    storage_healthy: bool


@router.get("/health", response_model=HealthResponse)
async def health_check(
    storage: StorageBackend = Depends(get_storage),
) -> HealthResponse:
    """Check API and storage health.

    Returns:
        HealthResponse with status information.
    """
    storage_healthy = await storage.health_check()

    return HealthResponse(
        status="healthy" if storage_healthy else "degraded",
        storage_healthy=storage_healthy,
    )
