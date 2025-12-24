# Durable Mode Examples

Event-sourced workflows with persistence, crash recovery, and suspension/resumption capabilities.

## What is Durable Mode?

Durable mode (`durable=True`) uses event sourcing to make workflows fault-tolerant and resumable. Every state change is recorded as an immutable event in a storage backend. If the process crashes, PyWorkflow replays the event log to restore state and resume execution.

## Key Concepts

### Event Sourcing

Instead of storing current state, PyWorkflow records every state change as an event:

```
Events:
1. workflow_started - Workflow begins
2. step_completed   - Step 1 finished (result stored)
3. step_completed   - Step 2 finished (result stored)
4. sleep_started    - Workflow suspended
... process restarts ...
5. sleep_completed  - Workflow resumed
6. step_completed   - Step 3 finished (result stored)
7. workflow_completed - Workflow done
```

**Benefits:**
- Complete audit trail
- Deterministic replay on crash
- Time-travel debugging (inspect any point in history)

### Suspension & Resumption

Workflows can pause execution and resume later:

```python
@workflow(durable=True)
async def long_running_workflow():
    await step1()
    await sleep("1h")  # Suspends here, releases resources
    await step2()      # Resumes after 1 hour
```

**How it works:**
1. `sleep()` records `sleep_started` event
2. Workflow raises `SuspensionSignal`
3. LocalRuntime catches signal, saves state
4. After 1 hour, runtime calls `resume(run_id)`
5. Event log replayed, execution continues from `step2()`

**Use cases:**
- Waiting for external events (webhooks)
- Rate limiting (delay between API calls)
- Scheduled workflows (run steps at specific times)

---

⚠️ **IMPORTANT: Local Runtime Limitations**

The examples in this directory use **manual resumption** (`await resume(run_id)`) for suspended workflows. This is an **artificial pattern** designed for local development and CI pipelines only.

**What happens in these examples:**
```python
run_id = await start(my_workflow)
await asyncio.sleep(delay)  # Manual wait
await resume(run_id)        # Manual resume
```

**Why this is NOT recommended for production:**
- ❌ Requires your script to stay running during suspension
- ❌ No automatic scheduling - you must manually call `resume()`
- ❌ No distributed execution - single process
- ❌ No fault tolerance - if script crashes, resumption won't happen

**For production, use:**
- ✅ **Celery Runtime** - Automatic scheduled resumption via Celery workers
- ✅ **AWS Lambda Runtime** - Automatic resumption via EventBridge/Step Functions
- ✅ **Distributed workers** - Multiple processes handling workflows in parallel

**When to use local runtime:**
- ✅ Local development and debugging
- ✅ Unit tests and integration tests
- ✅ CI/CD pipelines (ephemeral, controlled environment)
- ✅ Simple scripts where manual control is acceptable

**Example production setup (Celery):**
```python
# Workflow suspends with sleep("1h")
# Celery automatically schedules resume task for 1 hour later
# No manual intervention needed!
configure(
    default_runtime="celery",
    celery_broker="redis://localhost:6379/0",
    storage=RedisStorageBackend()
)
```

See [../celery/](../celery/) for distributed runtime examples.

---

### Storage Backends

Durable mode requires a storage backend to persist events.

#### InMemoryStorageBackend

```python
from pyworkflow.storage import InMemoryStorageBackend

storage = InMemoryStorageBackend()
configure(storage=storage, default_durable=True)
```

**Characteristics:**
- ✅ Fastest performance
- ✅ No external dependencies
- ✅ Perfect for testing
- ❌ Data lost when process exits
- ❌ No persistence across restarts

**Use for:** Unit tests, development, ephemeral workflows

#### FileStorageBackend

```python
from pyworkflow.storage import FileStorageBackend

storage = FileStorageBackend(base_path="./workflow_data")
configure(storage=storage, default_durable=True)
```

**Characteristics:**
- ✅ Persistent (survives restarts)
- ✅ Human-readable JSON files
- ✅ Easy debugging (inspect files directly)
- ✅ No external dependencies
- ⚠️  Not suitable for high concurrency
- ⚠️  File I/O overhead

**Directory structure:**
```
workflow_data/
├── runs/           {run_id}.json
├── events/         {run_id}.jsonl (append-only)
├── steps/          {step_id}.json
├── hooks/          {hook_id}.json
└── .locks/         (internal lock files)
```

**Use for:** Development, single-machine deployments, low-volume production

### Idempotency

Prevent duplicate workflow execution with idempotency keys:

```python
# First call - creates new workflow
run_id_1 = await start(my_workflow, idempotency_key="order-123")

# Second call - returns same run_id, doesn't re-execute
run_id_2 = await start(my_workflow, idempotency_key="order-123")

assert run_id_1 == run_id_2  # True!
```

**Use cases:**
- Prevent duplicate orders from retry logic
- Ensure exactly-once execution in distributed systems
- Handle duplicate webhook deliveries

## Examples

### 01_basic_workflow.py - Foundation

**What it demonstrates:**
- Simple 3-step order workflow
- InMemoryStorageBackend setup
- Event log inspection
- Basic `@workflow` and `@step` decorators

**Key patterns:**
```python
@step()
async def process_order(order_id: str) -> dict:
    return {"order_id": order_id, "status": "processed"}

@workflow(durable=True)
async def order_workflow(order_id: str, amount: float) -> dict:
    order = await process_order(order_id)
    order = await charge_payment(order, amount)
    order = await send_notification(order)
    return order
```

**Run:** `python 01_basic_workflow.py 2>/dev/null`

### 02_file_storage.py - Persistence

**What it demonstrates:**
- FileStorageBackend for persistent storage
- Same workflow as 01, different backend
- Stored file structure inspection
- Data survives process restarts

**Key difference:**
```python
storage = FileStorageBackend(base_path="./workflow_data")
configure(storage=storage, default_durable=True)
```

**Run:** `python 02_file_storage.py 2>/dev/null`

### 03_retries.py - Error Handling

**What it demonstrates:**
- Automatic retry with `@step(max_retries=3, retry_delay=1)`
- Simulated flaky API (fails 2x, succeeds 3rd try)
- Retry events in event log
- Exponential backoff patterns

**Key patterns:**
```python
@step(max_retries=3, retry_delay=1)
async def call_flaky_api(order: dict) -> dict:
    if attempt < 3:
        raise Exception("Temporary failure")
    return {"api_response": "success"}
```

**Run:** `python 03_retries.py 2>/dev/null`

### 04_long_running.py - Suspension

**What it demonstrates:**
- Workflow suspension with `sleep("1h")`
- Manual resumption with `resume(run_id)`
- Suspension state inspection
- FileStorageBackend for cross-restart persistence

**Key patterns:**
```python
@workflow(durable=True)
async def long_running_workflow():
    await step1()
    await sleep("1h")  # Suspends here
    await step2()      # Resumes after manual resume() call
```

**Run:** `python 04_long_running.py 2>/dev/null`

**Note:** Requires manual `resume(run_id)` after suspension

### 05_event_log.py - Event Sourcing Deep Dive

**What it demonstrates:**
- Multiple workflows with different event sequences
- Detailed event inspection (sequence, type, timestamp, data)
- Event types: `workflow_started`, `step_completed`, `workflow_completed`
- Event replay concepts

**Key patterns:**
```python
events = await get_workflow_events(run_id)
for event in events:
    print(f"{event.sequence}: {event.type.value}")
    print(f"  Data: {event.data}")
    print(f"  Timestamp: {event.timestamp}")
```

**Run:** `python 05_event_log.py 2>/dev/null`

### 06_idempotency.py - Duplicate Prevention

**What it demonstrates:**
- Idempotency key usage
- Same workflow called twice with same key
- Second call returns same `run_id`, doesn't re-execute
- Status inspection with `get_workflow_run()`

**Key patterns:**
```python
run_id_1 = await start(my_workflow, idempotency_key="unique-123")
run_id_2 = await start(my_workflow, idempotency_key="unique-123")
assert run_id_1 == run_id_2
```

**Run:** `python 06_idempotency.py 2>/dev/null`

### 07_hooks.py - External Events

See the hooks example for webhook/callback patterns.

**Run:** `python 07_hooks.py 2>/dev/null`

### 08_cancellation.py - Graceful Cancellation

**What it demonstrates:**
- Cancel running or suspended workflows with `cancel_workflow()`
- Handle `CancellationError` for cleanup/compensation logic
- Use `shield()` to protect critical cleanup operations
- Checkpoint-based cancellation (not mid-step)

**Key patterns:**
```python
@workflow(durable=True)
async def order_workflow(order_id: str):
    try:
        order = await reserve_inventory(order_id)
        await sleep("5s")  # Can be cancelled here
        order = await charge_payment(order)
        return order
    except CancellationError:
        # Cleanup with shield to ensure completion
        async with shield():
            await release_inventory(order_id)
            await refund_payment(order_id)
        raise

# Cancel a workflow
await cancel_workflow(run_id, reason="Customer cancelled")
```

**Run:** `python 08_cancellation.py 2>/dev/null`

## Learning Path

**Recommended order:**
1. Start with **01_basic_workflow.py** to understand event-sourced execution
2. Try **02_file_storage.py** to see persistence in action
3. Learn error handling with **03_retries.py**
4. Master suspension with **04_long_running.py**
5. Deep dive into events with **05_event_log.py**
6. Prevent duplicates with **06_idempotency.py**

## Common Patterns

### Basic Configuration

```python
from pyworkflow import configure, reset_config
from pyworkflow.storage import InMemoryStorageBackend

reset_config()
configure(
    storage=InMemoryStorageBackend(),
    default_durable=True
)
```

### Workflow Definition

```python
@workflow(durable=True)
async def my_workflow(arg1: str, arg2: int) -> dict:
    result = await step1(arg1)
    result = await step2(result, arg2)
    return result
```

### Step Definition

```python
@step(max_retries=3, retry_delay=1)
async def my_step(data: dict) -> dict:
    # Step logic here
    return processed_data
```

### Event Inspection

```python
from pyworkflow import get_workflow_events, get_workflow_run

run = await get_workflow_run(run_id)
print(f"Status: {run.status.value}")

events = await get_workflow_events(run_id)
for event in events:
    print(f"{event.sequence}: {event.type.value}")
```

## Troubleshooting

### Workflow stuck in SUSPENDED state

Check if workflow is waiting for manual resumption:

```python
run = await get_workflow_run(run_id)
if run.status == RunStatus.SUSPENDED:
    # Resume manually
    await resume(run_id)
```

### Events not persisting

Ensure storage backend is configured before starting workflows:

```python
# Wrong - no storage configured
await start(my_workflow)

# Right - storage configured
configure(storage=FileStorageBackend("./data"))
await start(my_workflow)
```

### Step re-executing on replay

Check that step_id is deterministic. PyWorkflow uses step name and call order as step_id.

## Next Steps

- Try [../transient/](../transient/) for simple, non-durable workflows
- Read [CLAUDE.md](../../../CLAUDE.md) for architecture deep dive
- Explore future Celery and AWS runtimes for distributed execution
