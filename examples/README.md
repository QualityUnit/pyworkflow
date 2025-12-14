# PyWorkflow Examples

Two paradigms for workflow execution:

## Transient Mode (`transient/`)

Fast, in-memory execution without persistence.

```bash
python examples/transient/example.py 2>/dev/null
```

**Characteristics:**
- No storage required
- Direct execution
- `sleep()` uses `asyncio.sleep`
- Retries work normally
- No crash recovery

**Use cases:** Scripts, CLI tools, testing, short-lived operations

## Durable Mode (`durable/`)

Event-sourced execution with persistence and recovery.

### Storage Backends

**In-Memory** (testing, ephemeral):
```bash
python examples/durable/example_memory.py 2>/dev/null
```

**File-based** (development, single-machine):
```bash
python examples/durable/example_file.py 2>/dev/null
```

**Characteristics:**
- Requires storage backend
- Events recorded for each step
- `sleep()` suspends workflow, resume with `resume(run_id)`
- Crash recovery via event replay
- Idempotency keys prevent duplicates

**Use cases:** Payment processing, order fulfillment, long-running jobs

## Quick Reference

```python
from pyworkflow import workflow, step, start, configure
from pyworkflow.storage import InMemoryStorageBackend, FileStorageBackend

# Transient (no storage)
configure(default_durable=False)
await start(my_workflow, arg)

# Durable with in-memory storage
configure(storage=InMemoryStorageBackend(), default_durable=True)
await start(my_workflow, arg)

# Durable with file storage
configure(storage=FileStorageBackend("./data"), default_durable=True)
await start(my_workflow, arg, idempotency_key="unique_id")
```
