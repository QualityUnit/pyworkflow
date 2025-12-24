"""REST API routes."""

from fastapi import APIRouter

from app.rest.v1 import router as v1_router

router = APIRouter()
router.include_router(v1_router, prefix="/api/v1")
