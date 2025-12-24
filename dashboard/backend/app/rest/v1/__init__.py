"""V1 API routes."""

from fastapi import APIRouter

from app.rest.v1.health import router as health_router
from app.rest.v1.runs import router as runs_router
from app.rest.v1.workflows import router as workflows_router

router = APIRouter()
router.include_router(health_router, tags=["health"])
router.include_router(workflows_router, prefix="/workflows", tags=["workflows"])
router.include_router(runs_router, prefix="/runs", tags=["runs"])
