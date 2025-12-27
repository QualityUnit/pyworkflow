"""FastAPI application factory."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.rest import router as api_router


def _initialize_pyworkflow() -> None:
    """Initialize pyworkflow configuration and discover workflows.

    Priority:
    1. If pyworkflow_config_path is set, load from that path (includes discovery)
    2. Otherwise, load from pyworkflow.config.yaml in cwd and discover workflows
    """
    import pyworkflow

    if settings.pyworkflow_config_path:
        # configure_from_yaml automatically discovers workflows
        pyworkflow.configure_from_yaml(settings.pyworkflow_config_path)
    else:
        # Load config without discovery, then discover from cwd config
        pyworkflow.get_config()
        # Discover workflows from pyworkflow.config.yaml in cwd
        pyworkflow.discover_workflows()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler.

    Startup: Initialize pyworkflow configuration
    Shutdown: (cleanup if needed in future)
    """
    # Startup
    _initialize_pyworkflow()

    # Reset cached storage instance to ensure fresh initialization
    from app.dependencies.storage import get_storage, reset_storage_cache

    reset_storage_cache()

    # Initialize and connect storage backend
    storage = await get_storage()
    if hasattr(storage, "connect"):
        await storage.connect()
    if hasattr(storage, "initialize"):
        await storage.initialize()

    yield

    # Shutdown - disconnect storage
    if hasattr(storage, "disconnect"):
        await storage.disconnect()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="PyWorkflow Dashboard API",
        description="REST API for monitoring PyWorkflow workflows",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API routes
    app.include_router(api_router)

    return app


app = create_app()
