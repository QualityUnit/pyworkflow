"""
Unit tests for Citus distributed PostgreSQL storage backend.

These tests verify CitusStorageBackend initialization, config round-trips,
and env-var loading. They do NOT require a live Citus/PostgreSQL instance.
For integration tests with a real Citus cluster, see tests/integration/.
"""

import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Skip all tests if asyncpg is not installed
pytest.importorskip("asyncpg")

from pyworkflow.storage.citus import CitusStorageBackend, CitusMigrationRunner
from pyworkflow.storage.config import _create_storage_backend, config_to_storage, storage_to_config


@pytest.fixture
def mock_citus_backend():
    """Create a CitusStorageBackend with a mocked pool for testing."""
    backend = CitusStorageBackend()
    mock_pool = MagicMock()
    mock_conn = AsyncMock()

    @asynccontextmanager
    async def mock_acquire():
        yield mock_conn

    mock_pool.acquire = mock_acquire
    backend._pool = mock_pool
    return backend, mock_conn


class TestCitusStorageBackendInit:
    """Test CitusStorageBackend initialization."""

    def test_init_defaults(self):
        """Test default initialization parameters."""
        backend = CitusStorageBackend()
        assert backend.dsn is None
        assert backend.host == "localhost"
        assert backend.port == 5432
        assert backend.user == "pyworkflow"
        assert backend.password == ""
        assert backend.database == "pyworkflow"
        assert backend._pool is None
        assert backend._initialized is False

    def test_init_with_dsn(self):
        """Test initialization with a DSN connection string."""
        dsn = "postgresql://user:pass@citus-coordinator:5432/pyworkflow"
        backend = CitusStorageBackend(dsn=dsn)
        assert backend.dsn == dsn
        assert backend._pool is None

    def test_init_with_individual_params(self):
        """Test initialization with individual connection parameters."""
        backend = CitusStorageBackend(
            host="citus-coordinator",
            port=5433,
            user="citususer",
            password="secret",
            database="wf",
        )
        assert backend.dsn is None
        assert backend.host == "citus-coordinator"
        assert backend.port == 5433
        assert backend.user == "citususer"
        assert backend.password == "secret"
        assert backend.database == "wf"

    def test_inherits_postgres_backend(self):
        """CitusStorageBackend must inherit from PostgresStorageBackend."""
        from pyworkflow.storage.postgres import PostgresStorageBackend

        backend = CitusStorageBackend()
        assert isinstance(backend, PostgresStorageBackend)

    def test_build_dsn(self):
        """Test DSN construction from individual params."""
        backend = CitusStorageBackend(
            host="coordinator",
            port=5432,
            user="admin",
            password="pass",
            database="db",
        )
        dsn = backend._build_dsn()
        assert "coordinator" in dsn
        assert "admin" in dsn
        assert "db" in dsn


class TestCitusMigrationRunner:
    """Test CitusMigrationRunner."""

    def test_inherits_postgres_runner(self):
        """CitusMigrationRunner must inherit from PostgresMigrationRunner."""
        from pyworkflow.storage.postgres import PostgresMigrationRunner

        pool = MagicMock()
        runner = CitusMigrationRunner(pool)
        assert isinstance(runner, PostgresMigrationRunner)


class TestStorageToConfig:
    """Test storage_to_config() serialization for CitusStorageBackend."""

    def test_citus_backend_produces_citus_type(self):
        """storage_to_config returns type='citus' for CitusStorageBackend."""
        backend = CitusStorageBackend(
            host="citus-host",
            port=5432,
            user="user",
            password="pass",
            database="db",
        )
        config = storage_to_config(backend)
        assert config is not None
        assert config["type"] == "citus"

    def test_citus_backend_with_dsn(self):
        """storage_to_config preserves DSN for CitusStorageBackend."""
        dsn = "postgresql://user:pass@coordinator/db"
        backend = CitusStorageBackend(dsn=dsn)
        config = storage_to_config(backend)
        assert config is not None
        assert config["type"] == "citus"
        assert config["dsn"] == dsn

    def test_citus_config_round_trip_individual_params(self):
        """Round-trip: CitusStorageBackend → config dict → CitusStorageBackend."""
        original = CitusStorageBackend(
            host="citus-host",
            port=5432,
            user="wf",
            password="secret",
            database="wfdb",
        )
        config = storage_to_config(original)
        assert config is not None
        assert config["type"] == "citus"
        assert config["host"] == "citus-host"
        assert config["user"] == "wf"
        assert config["database"] == "wfdb"


class TestConfigToStorage:
    """Test config_to_storage() / _create_storage_backend() for citus type."""

    def test_citus_type_returns_citus_backend(self):
        """_create_storage_backend({'type': 'citus', ...}) returns CitusStorageBackend."""
        config = {
            "type": "citus",
            "host": "coordinator",
            "port": 5432,
            "user": "user",
            "password": "",
            "database": "pyworkflow",
        }
        backend = _create_storage_backend(config)
        assert isinstance(backend, CitusStorageBackend)

    def test_citus_type_with_dsn(self):
        """_create_storage_backend with DSN returns CitusStorageBackend."""
        config = {
            "type": "citus",
            "dsn": "postgresql://user@coordinator/db",
        }
        backend = _create_storage_backend(config)
        assert isinstance(backend, CitusStorageBackend)
        assert backend.dsn == "postgresql://user@coordinator/db"

    def test_config_to_storage_caches_instance(self):
        """config_to_storage() returns the same cached instance for identical config."""
        from pyworkflow.storage.config import clear_storage_cache

        clear_storage_cache()
        config = {
            "type": "citus",
            "host": "coordinator",
            "port": 5432,
            "user": "user",
            "password": "",
            "database": "pyworkflow",
        }
        backend1 = config_to_storage(config)
        backend2 = config_to_storage(config)
        assert backend1 is backend2
        clear_storage_cache()

    def test_citus_config_full_round_trip(self):
        """Full round-trip: CitusStorageBackend → config → CitusStorageBackend."""
        from pyworkflow.storage.config import clear_storage_cache

        clear_storage_cache()
        original = CitusStorageBackend(
            host="citus-coordinator",
            port=5432,
            user="wf",
            password="secret",
            database="wfdb",
        )
        config = storage_to_config(original)
        assert config is not None

        clear_storage_cache()
        restored = _create_storage_backend(config)
        assert isinstance(restored, CitusStorageBackend)
        assert restored.host == "citus-coordinator"
        assert restored.user == "wf"
        assert restored.database == "wfdb"
        clear_storage_cache()


class TestEnvVarConfig:
    """Test PYWORKFLOW_STORAGE_TYPE=citus env var loading."""

    def test_citus_env_var_produces_citus_config(self):
        """PYWORKFLOW_STORAGE_TYPE=citus reads PYWORKFLOW_POSTGRES_* vars."""
        from pyworkflow.config import _load_env_storage_config

        env = {
            "PYWORKFLOW_STORAGE_TYPE": "citus",
            "PYWORKFLOW_POSTGRES_HOST": "citus-host",
            "PYWORKFLOW_POSTGRES_PORT": "5433",
            "PYWORKFLOW_POSTGRES_USER": "citususer",
            "PYWORKFLOW_POSTGRES_PASSWORD": "secret",
            "PYWORKFLOW_POSTGRES_DATABASE": "citusdb",
        }
        with patch.dict(os.environ, env, clear=False):
            config = _load_env_storage_config()

        assert config is not None
        assert config["type"] == "citus"
        assert config["host"] == "citus-host"
        assert config["port"] == 5433
        assert config["user"] == "citususer"
        assert config["password"] == "secret"
        assert config["database"] == "citusdb"

    def test_citus_env_var_defaults(self):
        """PYWORKFLOW_STORAGE_TYPE=citus uses default Postgres vars when not set."""
        from pyworkflow.config import _load_env_storage_config

        # Only set the storage type; rely on defaults for the rest
        env_overrides = {
            "PYWORKFLOW_STORAGE_TYPE": "citus",
        }
        # Ensure Postgres vars are not set
        remove_keys = [
            "PYWORKFLOW_POSTGRES_HOST",
            "PYWORKFLOW_POSTGRES_PORT",
            "PYWORKFLOW_POSTGRES_USER",
            "PYWORKFLOW_POSTGRES_PASSWORD",
            "PYWORKFLOW_POSTGRES_DATABASE",
        ]
        env = {k: v for k, v in os.environ.items() if k not in remove_keys}
        env.update(env_overrides)

        with patch.dict(os.environ, env, clear=True):
            config = _load_env_storage_config()

        assert config is not None
        assert config["type"] == "citus"
        assert config["host"] == "localhost"
        assert config["port"] == 5432
        assert config["user"] == "pyworkflow"
        assert config["database"] == "pyworkflow"

    def test_citus_env_var_creates_citus_backend(self):
        """End-to-end: PYWORKFLOW_STORAGE_TYPE=citus → CitusStorageBackend instance."""
        from pyworkflow.config import _load_env_storage_config
        from pyworkflow.storage.config import _create_storage_backend

        env = {"PYWORKFLOW_STORAGE_TYPE": "citus"}
        with patch.dict(os.environ, env, clear=False):
            storage_config = _load_env_storage_config()

        assert storage_config is not None
        backend = _create_storage_backend(storage_config)
        assert isinstance(backend, CitusStorageBackend)
