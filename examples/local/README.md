# Local Runtime Examples

The **LocalRuntime** executes workflows in-process within a single Python application. It's perfect for development, testing, and single-machine deployments.

## What is LocalRuntime?

LocalRuntime runs workflows directly in your Python process without requiring external infrastructure like Celery workers or cloud services. It supports both durable (event-sourced) and transient (simple) execution modes.

## When to Use LocalRuntime

**Use LocalRuntime when:**
- Developing and testing workflows locally
- Running workflows on a single machine
- You don't need distributed execution across multiple workers
- Deploying to environments where you control the process lifecycle

**Consider other runtimes when:**
- **CeleryRuntime**: Need to distribute work across multiple workers
- **AWSRuntime**: Building serverless applications on AWS Lambda

## Durable vs Transient Mode

LocalRuntime supports two execution modes:

### Durable Mode (`durable=True`)

Event-sourced execution with persistence and crash recovery.

**How it works:**
1. Every state change recorded as an immutable event
2. Events stored in a storage backend (memory, file, database)
3. On crash/restart, events replayed to restore state
4. Workflows can suspend (sleep, webhooks) and resume later

**Features:**
- ✅ Crash recovery via event replay
- ✅ Workflow suspension/resumption
- ✅ Audit trail (complete event log)
- ✅ Idempotency guarantees
- ✅ Long-running workflows (hours/days)

**Trade-offs:**
- Requires storage backend
- Slightly more complex setup
- Small performance overhead from event recording

**Use cases:**
- Payment processing
- Order fulfillment workflows
- Long-running batch jobs
- Critical workflows requiring audit trails

**Storage backends:**
- `InMemoryStorageBackend` - Fast, data lost on exit (testing)
- `FileStorageBackend` - Persistent JSON files (development)
- Future: Redis, PostgreSQL, SQLite (production)

### Transient Mode (`durable=False`)

Simple, direct execution without persistence.

**How it works:**
1. Workflows execute directly in-process
2. No events recorded
3. Sleep uses `asyncio.sleep()` (blocks)
4. Retries work inline with configurable delays

**Features:**
- ✅ Fast execution (no overhead)
- ✅ Simple setup (no storage required)
- ✅ Perfect for scripts and CLI tools
- ✅ Inline retries with delays

**Trade-offs:**
- ❌ No crash recovery
- ❌ No workflow suspension
- ❌ State lost on process exit
- ❌ No audit trail

**Use cases:**
- CLI tools and scripts
- Short-lived workflows (seconds/minutes)
- Data processing pipelines
- Testing and development

## Comparison Table

| Feature | Durable Mode | Transient Mode |
|---------|--------------|----------------|
| **Storage Required** | Yes (InMemory, File, etc.) | No |
| **Crash Recovery** | Yes (event replay) | No |
| **Workflow Suspension** | Yes (`sleep()`, webhooks) | No (blocks) |
| **Audit Trail** | Yes (event log) | No |
| **Idempotency** | Yes | No |
| **Performance** | Slight overhead | Very fast |
| **Complexity** | Medium | Low |
| **Best For** | Production workflows | Scripts & tools |

## Directory Structure

```
local/
├── README.md           This file
├── durable/            Event-sourced workflows (6 examples)
│   ├── README.md
│   ├── 01_basic_workflow.py
│   ├── 02_file_storage.py
│   ├── 03_retries.py
│   ├── 04_long_running.py
│   ├── 05_event_log.py
│   └── 06_idempotency.py
└── transient/          Simple workflows (3 examples)
    ├── README.md
    ├── 01_quick_tasks.py
    ├── 02_retries.py
    └── 03_sleep.py
```

## Getting Started

### Durable Mode Quick Start

```python
import asyncio
from pyworkflow import configure, start, step, workflow
from pyworkflow.storage import InMemoryStorageBackend

# Configure with storage backend
configure(
    storage=InMemoryStorageBackend(),
    default_durable=True
)

@step()
async def process_data(value: int) -> int:
    return value * 2

@workflow(durable=True)
async def my_workflow(value: int) -> int:
    result = await process_data(value)
    return result

async def main():
    run_id = await start(my_workflow, 42)
    print(f"Workflow completed: {run_id}")

asyncio.run(main())
```

### Transient Mode Quick Start

```python
import asyncio
from pyworkflow import configure, start, step, workflow

# Configure for transient mode (no storage)
configure(default_durable=False)

@step()
async def process_data(value: int) -> int:
    return value * 2

@workflow(durable=False)
async def my_workflow(value: int) -> int:
    result = await process_data(value)
    return result

async def main():
    run_id = await start(my_workflow, 42)
    print(f"Workflow completed: {run_id}")

asyncio.run(main())
```

## Example Learning Paths

### Durable Mode Path (Recommended for Production)

1. **01_basic_workflow.py** - Start here! Simple 3-step workflow with InMemoryStorageBackend
2. **02_file_storage.py** - Learn FileStorageBackend for persistence
3. **03_retries.py** - Handle flaky APIs with automatic retries
4. **04_long_running.py** - Master workflow suspension and resumption
5. **05_event_log.py** - Deep dive into event sourcing
6. **06_idempotency.py** - Prevent duplicate workflow execution

### Transient Mode Path (Quick Start)

1. **01_quick_tasks.py** - Simple workflow execution
2. **02_retries.py** - Inline retry mechanics
3. **03_sleep.py** - Understand async sleep behavior

## Next Steps

- Explore [durable/](durable/) for production-ready event-sourced workflows
- Explore [transient/](transient/) for simple script-based workflows
- Check [../README.md](../README.md) for other runtime options
