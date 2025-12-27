"""Storage dependency for FastAPI."""

from app.config import settings
from pyworkflow import get_storage as pyworkflow_get_storage
from pyworkflow.storage.base import StorageBackend
from pyworkflow.storage.file import FileStorageBackend
from pyworkflow.storage.memory import InMemoryStorageBackend

_storage_instance: StorageBackend | None = None


def reset_storage_cache() -> None:
    """Reset the cached storage instance.

    Called during application startup to ensure fresh initialization
    after pyworkflow configuration is loaded.
    """
    global _storage_instance
    _storage_instance = None


async def get_storage() -> StorageBackend:
    """Get or create the storage backend instance.

    First tries to get storage from pyworkflow configuration.
    Falls back to creating based on dashboard settings.
    """
    global _storage_instance

    if _storage_instance is None:
        # Try to get from pyworkflow config first
        storage = pyworkflow_get_storage()

        if storage is None:
            # Create based on dashboard config
            if settings.storage_type == "file":
                storage = FileStorageBackend(settings.storage_path)
            elif settings.storage_type == "sqlite":
                from pyworkflow.storage.sqlite import SQLiteStorageBackend

                db_path = f"{settings.storage_path}/pyworkflow.db"
                storage = SQLiteStorageBackend(db_path)
            elif settings.storage_type == "memory":
                storage = InMemoryStorageBackend()
            else:
                raise ValueError(f"Unknown storage type: {settings.storage_type}")

        _storage_instance = storage

    return _storage_instance
