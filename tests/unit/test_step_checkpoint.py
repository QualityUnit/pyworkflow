"""Tests for step checkpoint and step hook primitives."""

import pytest

from pyworkflow.primitives.step_checkpoint import (
    delete_step_checkpoint,
    load_step_checkpoint,
    reset_step_execution_context,
    save_step_checkpoint,
    set_step_execution_context,
)
from pyworkflow.storage.memory import InMemoryStorageBackend


@pytest.fixture
def storage():
    """Create a fresh storage backend."""
    return InMemoryStorageBackend()


class TestStepCheckpoint:
    """Tests for save/load/delete step checkpoint."""

    @pytest.mark.asyncio
    async def test_save_and_load(self, storage):
        """Should save and load checkpoint data."""
        tokens = set_step_execution_context("run_1:step_1", storage)
        try:
            await save_step_checkpoint({"state": "active", "count": 42})
            data = await load_step_checkpoint()
            assert data == {"state": "active", "count": 42}
        finally:
            reset_step_execution_context(tokens)

    @pytest.mark.asyncio
    async def test_load_no_checkpoint(self, storage):
        """Should return None when no checkpoint exists."""
        tokens = set_step_execution_context("run_1:step_1", storage)
        try:
            data = await load_step_checkpoint()
            assert data is None
        finally:
            reset_step_execution_context(tokens)

    @pytest.mark.asyncio
    async def test_overwrite(self, storage):
        """Should overwrite existing checkpoint."""
        tokens = set_step_execution_context("run_1:step_1", storage)
        try:
            await save_step_checkpoint({"version": 1})
            await save_step_checkpoint({"version": 2})
            data = await load_step_checkpoint()
            assert data == {"version": 2}
        finally:
            reset_step_execution_context(tokens)

    @pytest.mark.asyncio
    async def test_delete(self, storage):
        """Should delete checkpoint."""
        tokens = set_step_execution_context("run_1:step_1", storage)
        try:
            await save_step_checkpoint({"data": True})
            await delete_step_checkpoint()
            data = await load_step_checkpoint()
            assert data is None
        finally:
            reset_step_execution_context(tokens)

    @pytest.mark.asyncio
    async def test_isolated_by_step_id(self, storage):
        """Different step IDs should have separate checkpoints."""
        tokens1 = set_step_execution_context("run_1:step_1", storage)
        try:
            await save_step_checkpoint({"step": 1})
        finally:
            reset_step_execution_context(tokens1)

        tokens2 = set_step_execution_context("run_1:step_2", storage)
        try:
            await save_step_checkpoint({"step": 2})
        finally:
            reset_step_execution_context(tokens2)

        # Verify isolation
        tokens1 = set_step_execution_context("run_1:step_1", storage)
        try:
            data = await load_step_checkpoint()
            assert data == {"step": 1}
        finally:
            reset_step_execution_context(tokens1)

    @pytest.mark.asyncio
    async def test_no_context_raises(self):
        """Should raise RuntimeError without step context."""
        with pytest.raises(RuntimeError, match="must be called within"):
            await save_step_checkpoint({"data": True})

        with pytest.raises(RuntimeError, match="must be called within"):
            await load_step_checkpoint()

        with pytest.raises(RuntimeError, match="must be called within"):
            await delete_step_checkpoint()
