"""
Base classes for the database migration framework.

Provides Migration dataclass, MigrationRegistry for tracking migrations,
and MigrationRunner abstract base class for backend-specific implementations.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable


@dataclass
class Migration:
    """
    Represents a database schema migration.

    Attributes:
        version: Integer version number (must be unique and sequential)
        description: Human-readable description of what the migration does
        up_sql: SQL to apply the migration (can be None for Python-based migrations)
        down_sql: SQL to rollback the migration (optional, for future use)
        up_func: Optional Python function for complex migrations (receives connection)
    """

    version: int
    description: str
    up_sql: str | None = None
    down_sql: str | None = None
    up_func: Callable[[Any], Any] | None = None

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("Migration version must be >= 1")
        if not self.up_sql and not self.up_func:
            raise ValueError("Migration must have either up_sql or up_func")


@dataclass
class AppliedMigration:
    """
    Record of an applied migration.

    Attributes:
        version: Migration version number
        applied_at: When the migration was applied
        description: Description of the migration
    """

    version: int
    applied_at: datetime
    description: str


class MigrationRegistry:
    """
    Registry for managing and tracking migrations.

    Maintains an ordered list of migrations and provides methods to
    get pending migrations based on the current database version.
    """

    def __init__(self) -> None:
        self._migrations: dict[int, Migration] = {}

    def register(self, migration: Migration) -> None:
        """
        Register a migration.

        Args:
            migration: Migration to register

        Raises:
            ValueError: If a migration with the same version already exists
        """
        if migration.version in self._migrations:
            raise ValueError(f"Migration version {migration.version} already registered")
        self._migrations[migration.version] = migration

    def get_all(self) -> list[Migration]:
        """
        Get all registered migrations, ordered by version.

        Returns:
            List of migrations sorted by version ascending
        """
        return [self._migrations[v] for v in sorted(self._migrations.keys())]

    def get_pending(self, current_version: int) -> list[Migration]:
        """
        Get migrations that need to be applied.

        Args:
            current_version: Current schema version (0 if fresh database)

        Returns:
            List of migrations with version > current_version, sorted ascending
        """
        return [
            self._migrations[v]
            for v in sorted(self._migrations.keys())
            if v > current_version
        ]

    def get_latest_version(self) -> int:
        """
        Get the latest migration version.

        Returns:
            Highest registered version, or 0 if no migrations
        """
        return max(self._migrations.keys()) if self._migrations else 0

    def get(self, version: int) -> Migration | None:
        """
        Get a specific migration by version.

        Args:
            version: Migration version number

        Returns:
            Migration if found, None otherwise
        """
        return self._migrations.get(version)


# Global migration registry for SQL backends
_global_registry = MigrationRegistry()


def get_global_registry() -> MigrationRegistry:
    """Get the global migration registry."""
    return _global_registry


def register_migration(migration: Migration) -> None:
    """Register a migration in the global registry."""
    _global_registry.register(migration)


class MigrationRunner(ABC):
    """
    Abstract base class for running migrations on a storage backend.

    Subclasses must implement the backend-specific methods for:
    - Ensuring the schema_versions table exists
    - Getting the current schema version
    - Applying individual migrations
    - Detecting existing schemas (for backward compatibility)
    """

    def __init__(self, registry: MigrationRegistry | None = None) -> None:
        """
        Initialize the migration runner.

        Args:
            registry: Migration registry to use (defaults to global registry)
        """
        self.registry = registry or get_global_registry()

    @abstractmethod
    async def ensure_schema_versions_table(self) -> None:
        """
        Create the schema_versions table if it doesn't exist.

        The table should have:
        - version: INTEGER PRIMARY KEY
        - applied_at: TIMESTAMP NOT NULL
        - description: TEXT
        """
        pass

    @abstractmethod
    async def get_current_version(self) -> int:
        """
        Get the current schema version from the database.

        Returns:
            Current version (highest applied), or 0 if no migrations applied
        """
        pass

    @abstractmethod
    async def apply_migration(self, migration: Migration) -> None:
        """
        Apply a single migration.

        This should:
        1. Execute the migration SQL/function in a transaction
        2. Record the migration in schema_versions
        3. Rollback on failure

        Args:
            migration: Migration to apply

        Raises:
            Exception: If migration fails
        """
        pass

    @abstractmethod
    async def detect_existing_schema(self) -> bool:
        """
        Detect if the database has an existing schema (pre-versioning).

        This is used for backward compatibility with databases created
        before the migration framework was added. If tables exist but
        no schema_versions table, we assume it's a V1 schema.

        Returns:
            True if existing schema detected, False if fresh database
        """
        pass

    @abstractmethod
    async def record_baseline_version(self, version: int, description: str) -> None:
        """
        Record a baseline version without running migrations.

        Used when detecting an existing schema to mark it as a known version.

        Args:
            version: Version number to record
            description: Description of the baseline
        """
        pass

    async def run_migrations(self) -> list[AppliedMigration]:
        """
        Run all pending migrations.

        This is the main entry point for the migration runner. It:
        1. Ensures the schema_versions table exists
        2. Detects existing schemas and records baseline if needed
        3. Applies all pending migrations in order

        Returns:
            List of applied migrations

        Raises:
            Exception: If any migration fails (partial migrations are rolled back)
        """
        # Ensure we have a schema_versions table
        await self.ensure_schema_versions_table()

        # Get current version
        current_version = await self.get_current_version()

        # If no migrations recorded, check for existing schema
        if current_version == 0:
            has_existing_schema = await self.detect_existing_schema()
            if has_existing_schema:
                # Database has tables but no version tracking
                # Assume it's at V1 (original schema)
                await self.record_baseline_version(1, "Baseline: original schema")
                current_version = 1

        # Get and apply pending migrations
        pending = self.registry.get_pending(current_version)
        applied: list[AppliedMigration] = []

        for migration in pending:
            await self.apply_migration(migration)
            applied.append(
                AppliedMigration(
                    version=migration.version,
                    applied_at=datetime.now(UTC),
                    description=migration.description,
                )
            )

        return applied


# =============================================================================
# Migration Definitions
# =============================================================================

# Version 1: Baseline schema (represents the original schema before versioning)
# This is auto-detected for existing databases

_v1_migration = Migration(
    version=1,
    description="Baseline: original schema",
    up_sql="SELECT 1",  # No-op, baseline is detected not applied
)
register_migration(_v1_migration)


# Version 2: Add step_id column to events table for optimized queries
# The actual SQL is backend-specific, but we define the Python function here
# to handle the backfill logic

_v2_migration = Migration(
    version=2,
    description="Add step_id column to events table for optimized has_event() queries",
    # SQL is None because each backend has different syntax
    # The up_func will be set by each backend's runner
    up_sql="SELECT 1",  # Placeholder, actual migration is in backend runners
)
register_migration(_v2_migration)
