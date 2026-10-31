"""Regression coverage for dashboard startup without a PyWorkflow config file."""

import pytest

import pyworkflow


@pytest.mark.asyncio
async def test_default_startup_has_healthy_file_storage(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PYWORKFLOW_STORAGE_TYPE", raising=False)
    monkeypatch.delenv("PYWORKFLOW_STORAGE_BACKEND", raising=False)
    pyworkflow.reset_config()

    from app.dependencies.storage import get_storage, reset_storage_cache
    from app.server import create_app

    from pyworkflow.storage.file import FileStorageBackend

    app = create_app()
    try:
        async with app.router.lifespan_context(app):
            storage = await get_storage()
            assert isinstance(storage, FileStorageBackend)
            assert await storage.health_check()
    finally:
        reset_storage_cache()
        pyworkflow.reset_config()


@pytest.mark.asyncio
async def test_configured_storage_takes_precedence():
    from app.dependencies.storage import get_storage, reset_storage_cache

    from pyworkflow.storage.memory import InMemoryStorageBackend

    storage = InMemoryStorageBackend()
    reset_storage_cache()
    pyworkflow.configure(storage=storage)
    try:
        assert await get_storage() is storage
    finally:
        reset_storage_cache()
        pyworkflow.reset_config()
