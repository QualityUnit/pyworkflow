"""
Unit tests for the storage migration framework.

Tests for Migration dataclass, MigrationRegistry, and MigrationRunner base class.
"""

from datetime import UTC, datetime

import pytest

from pyworkflow.storage.migrations.base import (
    AppliedMigration,
    Migration,
    MigrationRegistry,
    MigrationRunner,
)


class TestMigration:
    """Test Migration dataclass."""

    def test_create_migration_with_sql(self):
        """Test creating a migration with SQL."""
        migration = Migration(
            version=1,
            description="Create users table",
            up_sql="CREATE TABLE users (id INT PRIMARY KEY)",
            down_sql="DROP TABLE users",
        )

        assert migration.version == 1
        assert migration.description == "Create users table"
        assert migration.up_sql == "CREATE TABLE users (id INT PRIMARY KEY)"
        assert migration.down_sql == "DROP TABLE users"
        assert migration.up_func is None

    def test_create_migration_with_function(self):
        """Test creating a migration with a Python function."""

        async def migrate(conn):
            pass

        migration = Migration(
            version=2,
            description="Complex migration",
            up_func=migrate,
        )

        assert migration.version == 2
        assert migration.up_sql is None
        assert migration.up_func is migrate

    def test_migration_requires_up_sql_or_func(self):
        """Test that migration requires either up_sql or up_func."""
        with pytest.raises(ValueError, match="must have either up_sql or up_func"):
            Migration(
                version=1,
                description="Invalid migration",
            )

    def test_migration_version_must_be_positive(self):
        """Test that migration version must be >= 1."""
        with pytest.raises(ValueError, match="version must be >= 1"):
            Migration(
                version=0,
                description="Invalid version",
                up_sql="SELECT 1",
            )

        with pytest.raises(ValueError, match="version must be >= 1"):
            Migration(
                version=-1,
                description="Negative version",
                up_sql="SELECT 1",
            )


class TestMigrationRegistry:
    """Test MigrationRegistry."""

    def test_register_migration(self):
        """Test registering a migration."""
        registry = MigrationRegistry()
        migration = Migration(version=1, description="Test", up_sql="SELECT 1")

        registry.register(migration)

        assert registry.get(1) == migration

    def test_register_duplicate_version_raises(self):
        """Test that registering duplicate version raises error."""
        registry = MigrationRegistry()
        migration1 = Migration(version=1, description="First", up_sql="SELECT 1")
        migration2 = Migration(version=1, description="Duplicate", up_sql="SELECT 2")

        registry.register(migration1)

        with pytest.raises(ValueError, match="version 1 already registered"):
            registry.register(migration2)

    def test_get_all_returns_sorted_migrations(self):
        """Test that get_all returns migrations sorted by version."""
        registry = MigrationRegistry()

        # Register in random order
        registry.register(Migration(version=3, description="Third", up_sql="SELECT 3"))
        registry.register(Migration(version=1, description="First", up_sql="SELECT 1"))
        registry.register(Migration(version=2, description="Second", up_sql="SELECT 2"))

        migrations = registry.get_all()

        assert len(migrations) == 3
        assert [m.version for m in migrations] == [1, 2, 3]

    def test_get_pending_returns_newer_migrations(self):
        """Test that get_pending returns migrations newer than current version."""
        registry = MigrationRegistry()

        registry.register(Migration(version=1, description="V1", up_sql="SELECT 1"))
        registry.register(Migration(version=2, description="V2", up_sql="SELECT 2"))
        registry.register(Migration(version=3, description="V3", up_sql="SELECT 3"))

        # Current version is 1, should return V2 and V3
        pending = registry.get_pending(1)

        assert len(pending) == 2
        assert [m.version for m in pending] == [2, 3]

    def test_get_pending_with_fresh_database(self):
        """Test get_pending with current_version=0 (fresh database)."""
        registry = MigrationRegistry()

        registry.register(Migration(version=1, description="V1", up_sql="SELECT 1"))
        registry.register(Migration(version=2, description="V2", up_sql="SELECT 2"))

        pending = registry.get_pending(0)

        assert len(pending) == 2
        assert [m.version for m in pending] == [1, 2]

    def test_get_pending_with_fully_migrated_database(self):
        """Test get_pending when database is fully migrated."""
        registry = MigrationRegistry()

        registry.register(Migration(version=1, description="V1", up_sql="SELECT 1"))
        registry.register(Migration(version=2, description="V2", up_sql="SELECT 2"))

        pending = registry.get_pending(2)

        assert len(pending) == 0

    def test_get_latest_version(self):
        """Test getting the latest registered version."""
        registry = MigrationRegistry()

        assert registry.get_latest_version() == 0  # Empty registry

        registry.register(Migration(version=1, description="V1", up_sql="SELECT 1"))
        assert registry.get_latest_version() == 1

        registry.register(Migration(version=5, description="V5", up_sql="SELECT 5"))
        assert registry.get_latest_version() == 5

    def test_get_nonexistent_migration(self):
        """Test getting a migration that doesn't exist."""
        registry = MigrationRegistry()

        assert registry.get(999) is None


class TestMigrationRunner:
    """Test MigrationRunner abstract base class."""

    @pytest.fixture
    def mock_runner(self):
        """Create a mock migration runner for testing."""

        class MockRunner(MigrationRunner):
            def __init__(self):
                self.registry = MigrationRegistry()
                self.ensure_called = False
                self.current_version = 0
                self.has_existing_schema = False
                self.applied_migrations: list[int] = []
                self.baseline_recorded = False

            async def ensure_schema_versions_table(self):
                self.ensure_called = True

            async def get_current_version(self):
                return self.current_version

            async def detect_existing_schema(self):
                return self.has_existing_schema

            async def record_baseline_version(self, version: int, description: str):
                self.baseline_recorded = True
                self.current_version = version

            async def apply_migration(self, migration):
                self.applied_migrations.append(migration.version)
                self.current_version = migration.version

        return MockRunner()

    @pytest.mark.asyncio
    async def test_run_migrations_on_fresh_database(self, mock_runner):
        """Test running migrations on a fresh database."""
        mock_runner.registry.register(Migration(version=1, description="V1", up_sql="SELECT 1"))
        mock_runner.registry.register(Migration(version=2, description="V2", up_sql="SELECT 2"))

        applied = await mock_runner.run_migrations()

        assert mock_runner.ensure_called
        assert len(applied) == 2
        assert [a.version for a in applied] == [1, 2]
        assert mock_runner.applied_migrations == [1, 2]

    @pytest.mark.asyncio
    async def test_run_migrations_detects_existing_schema(self, mock_runner):
        """Test that existing schema is detected and baseline recorded."""
        mock_runner.registry.register(Migration(version=1, description="V1", up_sql="SELECT 1"))
        mock_runner.registry.register(Migration(version=2, description="V2", up_sql="SELECT 2"))
        mock_runner.has_existing_schema = True
        mock_runner.current_version = 0  # No version recorded yet

        applied = await mock_runner.run_migrations()

        # Should record baseline V1, then apply V2
        assert mock_runner.baseline_recorded
        assert len(applied) == 1  # Only V2 was actually applied
        assert applied[0].version == 2
        assert mock_runner.applied_migrations == [2]

    @pytest.mark.asyncio
    async def test_run_migrations_skips_already_applied(self, mock_runner):
        """Test that already-applied migrations are skipped."""
        mock_runner.registry.register(Migration(version=1, description="V1", up_sql="SELECT 1"))
        mock_runner.registry.register(Migration(version=2, description="V2", up_sql="SELECT 2"))
        mock_runner.registry.register(Migration(version=3, description="V3", up_sql="SELECT 3"))
        mock_runner.current_version = 2  # V1 and V2 already applied

        applied = await mock_runner.run_migrations()

        assert len(applied) == 1
        assert applied[0].version == 3
        assert mock_runner.applied_migrations == [3]

    @pytest.mark.asyncio
    async def test_run_migrations_with_no_pending(self, mock_runner):
        """Test running migrations when database is up to date."""
        mock_runner.registry.register(Migration(version=1, description="V1", up_sql="SELECT 1"))
        mock_runner.current_version = 1

        applied = await mock_runner.run_migrations()

        assert len(applied) == 0
        assert mock_runner.applied_migrations == []


class TestAppliedMigration:
    """Test AppliedMigration dataclass."""

    def test_create_applied_migration(self):
        """Test creating an AppliedMigration record."""
        now = datetime.now(UTC)
        applied = AppliedMigration(
            version=1,
            applied_at=now,
            description="Test migration",
        )

        assert applied.version == 1
        assert applied.applied_at == now
        assert applied.description == "Test migration"


class TestGlobalRegistry:
    """Test global migration registry functions."""

    def test_global_registry_has_builtin_migrations(self):
        """Test that the global registry has the built-in migrations."""
        from pyworkflow.storage.migrations.base import get_global_registry

        registry = get_global_registry()

        # Should have V1 and V2 migrations
        assert registry.get(1) is not None
        assert registry.get(2) is not None
        assert registry.get(1).description == "Baseline: original schema"
        assert "step_id" in registry.get(2).description.lower()
