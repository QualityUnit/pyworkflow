"""
Database schema migration framework for PyWorkflow storage backends.

This module provides a migration framework that allows storage backends to
evolve their schema over time while maintaining backward compatibility with
existing databases.
"""

from pyworkflow.storage.migrations.base import (
    Migration,
    MigrationRegistry,
    MigrationRunner,
)

__all__ = ["Migration", "MigrationRegistry", "MigrationRunner"]
