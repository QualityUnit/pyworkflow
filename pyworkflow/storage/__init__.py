"""
Storage backends for PyWorkflow.

Provides different storage implementations for workflow state persistence.
"""

from pyworkflow.storage.base import StorageBackend
from pyworkflow.storage.config import config_to_storage, storage_to_config
from pyworkflow.storage.file import FileStorageBackend
from pyworkflow.storage.memory import InMemoryStorageBackend
from pyworkflow.storage.schemas import (
    Hook,
    HookStatus,
    RunStatus,
    StepExecution,
    StepStatus,
    WorkflowRun,
)

# SQLite backend - optional import (requires sqlite3 in Python build)
try:
    from pyworkflow.storage.sqlite import SQLiteStorageBackend
except ImportError:
    SQLiteStorageBackend = None  # type: ignore

# PostgreSQL backend - optional import (requires asyncpg)
try:
    from pyworkflow.storage.postgres import PostgresStorageBackend
except ImportError:
    PostgresStorageBackend = None  # type: ignore

# DynamoDB backend - optional import (requires aiobotocore)
try:
    from pyworkflow.storage.dynamodb import DynamoDBStorageBackend
except ImportError:
    DynamoDBStorageBackend = None  # type: ignore

# Cassandra backend - optional import (requires cassandra-driver)
try:
    from pyworkflow.storage.cassandra import CassandraStorageBackend
except ImportError:
    CassandraStorageBackend = None  # type: ignore

# MySQL backend - optional import (requires aiomysql)
try:
    from pyworkflow.storage.mysql import MySQLStorageBackend
except ImportError:
    MySQLStorageBackend = None  # type: ignore

__all__ = [
    "StorageBackend",
    "FileStorageBackend",
    "InMemoryStorageBackend",
    "SQLiteStorageBackend",
    "PostgresStorageBackend",
    "DynamoDBStorageBackend",
    "CassandraStorageBackend",
    "MySQLStorageBackend",
    "WorkflowRun",
    "StepExecution",
    "Hook",
    "RunStatus",
    "StepStatus",
    "HookStatus",
    # Config utilities
    "storage_to_config",
    "config_to_storage",
]
