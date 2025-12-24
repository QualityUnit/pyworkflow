# PyWorkflow - Claude Code Assistant Guide

This guide helps Claude Code (or other AI assistants) understand and effectively work with the PyWorkflow codebase.

## Project Overview

PyWorkflow is a Python implementation of durable, event-sourced workflow orchestration inspired by Vercel's Workflow Development Kit. It enables developers to build fault-tolerant, long-running workflows with automatic retry, sleep/delay capabilities, and webhook integration.

### Core Concepts

1. **Workflows**: Orchestration functions that coordinate steps (decorated with `@workflow` or inheriting from `Workflow` class)
2. **Steps**: Isolated, retryable units of work (decorated with `@step` or inheriting from `Step` class)
3. **Event Sourcing**: All state changes recorded as events for deterministic replay
4. **Suspension/Resumption**: Workflows can pause (sleep, webhooks) and resume without holding resources
5. **Dual API**: Both functional (decorators) and OOP (classes) interfaces

## Architecture

### High-Level Flow

```
User Code (Workflow + Steps)
    ↓
Decorators / Base Classes
    ↓
Execution Context + Event Log
    ↓
Celery Tasks (Distributed Execution)
    ↓
Storage Backend (File/Redis/SQLite/PostgreSQL)
```

### Event Sourcing Model

```
Workflow Execution:
1. Create WorkflowRun record
2. Record workflow_started event
3. Execute workflow function
4. When step encountered:
   - Check if step_completed event exists (replay mode)
   - If yes: return cached result
   - If no: execute step, record step_completed event
5. When sleep() encountered:
   - Record sleep_started event
   - Raise SuspensionSignal
   - Schedule Celery task for resumption
6. When hook encountered:
   - Record hook_created event
   - Raise SuspensionSignal
   - Wait for webhook to trigger resumption
7. On resumption:
   - Replay all events
   - Fast-forward to suspension point
   - Continue execution
```

## Project Structure

```
pyworkflow/
├── pyworkflow/              # Main package
│   ├── __init__.py          # Public API exports
│   ├── core/                # Core decorators and classes
│   │   ├── workflow.py      # @workflow decorator
│   │   ├── workflow_base.py # Workflow base class (OOP)
│   │   ├── step.py          # @step decorator
│   │   ├── step_base.py     # Step base class (OOP)
│   │   ├── context.py       # WorkflowContext, execution state
│   │   ├── registry.py      # Workflow/step registration
│   │   └── exceptions.py    # Error classes
│   ├── engine/              # Execution engine
│   │   ├── executor.py      # Main execution logic
│   │   ├── events.py        # Event types and schemas
│   │   ├── replay.py        # Event replay mechanism
│   │   └── state.py         # State machine
│   ├── celery/              # Celery integration
│   │   ├── tasks.py         # Task definitions
│   │   ├── config.py        # Configuration
│   │   └── integration.py   # Workflow-Celery bridge
│   ├── storage/             # Storage backends
│   │   ├── base.py          # StorageBackend ABC
│   │   ├── schemas.py       # Data models
│   │   ├── file.py          # File backend
│   │   ├── redis.py         # Redis backend
│   │   ├── sqlite.py        # SQLite backend
│   │   └── postgres.py      # PostgreSQL backend
│   ├── primitives/          # Workflow primitives
│   │   ├── sleep.py         # sleep() function
│   │   ├── hooks.py         # Hooks/webhooks
│   │   ├── parallel.py      # Parallel execution helper
│   │   └── retry.py         # Retry strategies
│   ├── serialization/       # Serialization layer
│   │   ├── encoder.py       # Encoding complex types
│   │   └── decoder.py       # Decoding complex types
│   ├── observability/       # Logging and metrics
│   │   ├── logging.py       # Loguru integration
│   │   └── metrics.py       # Metrics collection
│   └── utils/               # Utilities
│       ├── duration.py      # Duration parsing ("5s", "2m", etc.)
│       └── helpers.py       # General utilities
├── tests/                   # Test suite
├── examples/                # Example workflows
└── docs/                    # Documentation
```

## Key Design Patterns

### 1. Decorator Pattern (Functional API)

```python
@workflow
async def my_workflow(arg: str):
    result = await my_step(arg)
    return result

@step(max_retries=3)
async def my_step(arg: str):
    return f"processed: {arg}"
```

**How it works:**
- `@workflow` wraps the function, registers it, and adds execution context
- `@step` wraps the function, adds retry logic, and integrates with Celery

### 2. Base Class Pattern (OOP API)

```python
class MyWorkflow(Workflow):
    async def run(self, arg: str):
        result = await MyStep()(arg)
        return result

class MyStep(Step):
    max_retries = 3

    async def execute(self, arg: str):
        return f"processed: {arg}"
```

**How it works:**
- `Workflow.run()` is the entry point (abstract method)
- `Step.execute()` contains business logic (abstract method)
- `Step.__call__()` applies the `@step` decorator internally

### 3. Context Pattern

```python
from pyworkflow.context import get_context

def some_function():
    ctx = get_context()
    print(ctx.run_id, ctx.workflow_name)
```

**How it works:**
- Context stored in `contextvars.ContextVar`
- Accessible from any function in the call stack
- Contains run_id, workflow_name, event_log, step_results, etc.

### 4. Suspension Pattern

```python
async def sleep(duration):
    # Record event
    await ctx.storage.record_event(Event(type=EventType.SLEEP_STARTED, ...))

    # Raise signal
    raise SuspensionSignal(reason="sleep", wake_time=...)

# Workflow executor catches SuspensionSignal
try:
    result = await workflow_func(*args)
except SuspensionSignal as e:
    # Schedule resumption
    schedule_resumption(e)
```

### 5. Event Replay Pattern

```python
async def replay_events(ctx, events):
    for event in sorted(events, key=lambda e: e.sequence):
        if event.type == EventType.STEP_COMPLETED:
            ctx.step_results[event.data["step_id"]] = event.data["result"]
        elif event.type == EventType.HOOK_RECEIVED:
            ctx.hook_results[event.data["hook_id"]] = event.data["payload"]
```

## Common Development Tasks

### Adding a New Event Type

1. Add to `EventType` enum in `pyworkflow/engine/events.py`
2. Update `EventReplayer._apply_event()` in `pyworkflow/engine/replay.py`
3. Record event in relevant code (workflow.py, step.py, primitives/)
4. Add test in `tests/unit/test_events.py`

### Adding a New Storage Backend

1. Create `pyworkflow/storage/your_backend.py`
2. Inherit from `StorageBackend` in `storage/base.py`
3. Implement all abstract methods:
   - `create_run()`, `get_run()`, `update_run_status()`
   - `record_event()`, `get_events()`
   - `create_hook()`, `get_hook()`, `update_hook_payload()`
4. Add backend to `__init__.py` exports
5. Add tests in `tests/integration/test_storage_backends.py`

### Adding a New Primitive

1. Create `pyworkflow/primitives/your_primitive.py`
2. Implement the function/class
3. Handle suspension if needed (raise `SuspensionSignal`)
4. Record appropriate events
5. Add to `pyworkflow/__init__.py` exports
6. Add examples in `examples/`
7. Add tests in `tests/unit/` and `tests/integration/`

### Debugging Workflows

**1. Enable Debug Logging:**
```python
from pyworkflow import configure_logging
configure_logging(level="DEBUG")
```

**2. Inspect Event Log:**
```python
from pyworkflow import get_workflow_run
run = await storage.get_run(run_id)
events = await storage.get_events(run_id)
for event in events:
    print(f"{event.sequence}: {event.type} - {event.data}")
```

**3. Check Workflow Status:**
```python
run = await storage.get_run(run_id)
print(f"Status: {run.status}")
print(f"Error: {run.error}")
```

**4. Test Event Replay:**
```python
# Manually trigger replay
from pyworkflow.engine.replay import EventReplayer
replayer = EventReplayer()
await replayer.replay(ctx, events)
```

## Important Implementation Notes

### Serialization

**Supported Types:**
- Primitives: int, str, bool, float, None
- Collections: list, dict, tuple, set
- Dates: datetime, date, timedelta
- Special: Decimal, Enum, Exception, bytes
- Complex: Any object (via cloudpickle)

**Implementation:**
- Simple types → JSON (human-readable)
- Complex types → cloudpickle → base64 (fallback)
- Custom encoders in `serialization/encoder.py`
- Custom decoders in `serialization/decoder.py`

### Error Handling

**Error Hierarchy:**
```
WorkflowError (base)
├── FatalError (don't retry)
└── RetryableError (auto-retry)
    └── retry_after: delay before retry
```

**Usage:**
```python
# Don't retry
raise FatalError("Invalid input")

# Retry with default delay
raise RetryableError("Temporary failure")

# Retry with specific delay
raise RetryableError("Rate limited", retry_after="60s")
```

### Auto Recovery and Fault Tolerance

PyWorkflow automatically recovers workflows from worker crashes using event replay.

**Worker Loss Detection:**
- Celery detects worker loss via `WorkerLostError`
- Task is requeued; new worker detects `RUNNING` or `INTERRUPTED` status
- Recovery is triggered if `recover_on_worker_loss=True`

**Recovery Flow:**
1. Detect workflow in `RUNNING`/`INTERRUPTED` status on task start
2. Check `recovery_attempts < max_recovery_attempts`
3. Record `WORKFLOW_INTERRUPTED` event
4. Complete any pending sleeps (mark `SLEEP_COMPLETED`)
5. Replay event log to restore cached step results
6. Continue execution from the last checkpoint

**Key Functions (`pyworkflow/celery/tasks.py`):**
- `_handle_workflow_recovery()` - Authorize and initiate recovery (lines 239-318)
- `_recover_workflow_on_worker()` - Execute recovery with event replay (lines 321-428)
- `_complete_pending_sleeps()` - Mark pending sleeps as completed (lines 684-731)

**Configuration Priority:**
1. `@workflow()` decorator parameters (highest)
2. `pyworkflow.configure()` global settings
3. Defaults: `True` for durable workflows, `False` for transient

**Configuration:**
```python
# Per-workflow
@workflow(
    recover_on_worker_loss=True,   # Enable recovery
    max_recovery_attempts=5,        # Max attempts before failure
)
async def my_workflow():
    pass

# Global default
pyworkflow.configure(
    default_recover_on_worker_loss=True,
    default_max_recovery_attempts=3,
)
```

**Durable vs Transient Recovery:**
- **Durable**: Events are replayed, execution resumes from last checkpoint
- **Transient**: No events recorded, workflow restarts from the beginning

**New Event Type:**
- `WORKFLOW_INTERRUPTED` - Recorded when worker crash is detected

**New Run Status:**
- `INTERRUPTED` - Workflow awaiting recovery after worker crash

### Cancellation

PyWorkflow supports graceful workflow cancellation via `cancel_workflow()`.

**Key APIs:**
- `cancel_workflow(run_id, reason=None, wait=False)` - Request workflow cancellation
- `CancellationError` - Raised when workflow/step is cancelled
- `shield()` - Context manager to protect critical sections from cancellation

**Cancellation Check Points:**
Cancellation is checked at these points:
- Before each step execution
- Before sleep suspension
- Before hook suspension

**Important Limitation:**
Cancellation does NOT interrupt a step that is already executing. If a step function takes a long time (e.g., a 10-minute API call), cancellation will only be detected after the step completes. This is by design to avoid leaving operations in an inconsistent state.

For long-running operations that need to be cancellable mid-execution, the step should periodically call `ctx.check_cancellation()` to cooperatively check for cancellation:

```python
@step()
async def long_running_step():
    ctx = get_context()
    for chunk in process_large_dataset():
        ctx.check_cancellation()  # Cooperative cancellation check
        await process_chunk(chunk)
    return result
```

**Shield for Critical Sections:**
Use `shield()` to protect cleanup or critical code from cancellation:

```python
async with shield():
    # This code will complete even if cancellation is requested
    await cleanup_resources()
```

### Celery Integration

**Two Queue System:**
- `workflows` queue: Orchestration (lightweight)
- `steps` queue: Actual work (heavy)

**Task Routing:**
```python
task_routes = {
    'execute_workflow_task': {'queue': 'workflows'},
    'execute_step_task': {'queue': 'steps'},
}
```

**Starting Workers:**
```bash
# Workflow worker
celery -A pyworkflow.celery.tasks worker -Q workflows -n workflow@%h

# Step worker (scalable)
celery -A pyworkflow.celery.tasks worker -Q steps -n step@%h --concurrency=4
```

### Logging with Loguru

**Context-Aware Logging:**
```python
from pyworkflow.observability.logging import get_logger

logger = get_logger()
logger.info("Processing order", order_id=order_id, amount=99.99)
# Output: 2025-01-15 10:30:45 | INFO | run_abc123 | process_order | Processing order
```

**Configuration:**
```python
from pyworkflow import configure_logging

# JSON output for production
configure_logging(level="INFO", serialize=True)

# Pretty output for development
configure_logging(level="DEBUG", serialize=False)
```

## Testing Strategy

### Unit Tests
- Test individual components in isolation
- Mock dependencies (storage, Celery)
- Fast execution (<1s total)

**Example:**
```python
def test_event_creation():
    event = Event(
        run_id="test_run",
        type=EventType.STEP_COMPLETED,
        timestamp=datetime.utcnow(),
        data={"step_id": "step_1", "result": 42}
    )
    assert event.type == EventType.STEP_COMPLETED
    assert event.data["result"] == 42
```

### Integration Tests
- Test components working together
- Use real storage backends (in-memory, temporary files)
- Test end-to-end workflows

**Example:**
```python
@pytest.mark.asyncio
async def test_workflow_execution():
    @workflow
    async def test_wf():
        return await test_step()

    @step
    async def test_step():
        return 42

    run_id = await start(test_wf)
    # Wait for completion
    await asyncio.sleep(2)

    run = await storage.get_run(run_id)
    assert run.status == RunStatus.COMPLETED
```

### Example Tests
- Full workflow scenarios
- Test retry behavior
- Test sleep and webhooks
- Test error handling

## Code Style Guidelines

### Type Hints
Always use type hints:
```python
async def process_order(order_id: str) -> Dict[str, Any]:
    order: Order = await get_order(order_id)
    return order.to_dict()
```

### Async/Await
Prefer async/await for all I/O operations:
```python
# Good
async def fetch_data():
    return await httpx.get(url)

# Avoid
def fetch_data():
    return requests.get(url)  # Blocking
```

### Error Messages
Provide clear, actionable error messages:
```python
# Good
raise ValueError(f"Order {order_id} not found. Please check the order ID.")

# Avoid
raise ValueError("Not found")
```

### Documentation
Add docstrings to public APIs:
```python
async def sleep(duration: Union[str, int, timedelta]):
    """
    Pause workflow execution for specified duration.

    Args:
        duration: Sleep duration as string ("5s", "2m"), int (seconds),
                 or timedelta object

    Examples:
        await sleep("5m")  # 5 minutes
        await sleep(300)   # 300 seconds

    Raises:
        ValueError: If duration format is invalid
    """
```

## Common Pitfalls

### 1. Forgetting to Record Events
**Wrong:**
```python
async def sleep(duration):
    await asyncio.sleep(duration)  # Loses state!
```

**Right:**
```python
async def sleep(duration):
    await ctx.storage.record_event(Event(...))
    raise SuspensionSignal(...)  # Proper suspension
```

### 2. Not Using Context
**Wrong:**
```python
@step
async def my_step():
    # How do we know which workflow this belongs to?
    pass
```

**Right:**
```python
@step
async def my_step():
    ctx = get_current_context()
    logger.info("Step running", run_id=ctx.run_id)
```

### 3. Blocking I/O
**Wrong:**
```python
@step
async def fetch_data():
    return requests.get(url)  # Blocks event loop!
```

**Right:**
```python
@step
async def fetch_data():
    async with httpx.AsyncClient() as client:
        return await client.get(url)
```

### 4. Mutating Cached Results
**Wrong:**
```python
result = ctx.step_results["step_1"]  # Cached from replay
result["modified"] = True  # Mutates cached data!
```

**Right:**
```python
result = copy.deepcopy(ctx.step_results["step_1"])
result["modified"] = True
```

## Performance Considerations

### Event Replay Optimization
- Long workflows with many events may have replay overhead
- Future: Implement event compaction/snapshotting
- For now: Keep workflows reasonably sized

### Storage Backend Choice
- **Development**: File storage (simple, no dependencies)
- **Production (small)**: SQLite (embedded, single-file)
- **Production (medium)**: Redis (fast, in-memory)
- **Production (large)**: PostgreSQL (scalable, full SQL)

### Celery Concurrency
- Workflow workers: Low concurrency (lightweight orchestration)
- Step workers: High concurrency (actual work)
- Scale step workers horizontally as needed

## References

- [Vercel Workflow Docs](https://useworkflow.dev/)
- [Vercel Workflow GitHub](https://github.com/vercel/workflow)
- [Celery Documentation](https://docs.celeryq.dev/)
- [Loguru Documentation](https://loguru.readthedocs.io/)
- [Pydantic Documentation](https://docs.pydantic.dev/)

## Getting Help

When asking for help or reporting issues, provide:
1. Workflow code
2. Event log (`await storage.get_events(run_id)`)
3. Run status (`await storage.get_run(run_id)`)
4. Error traceback
5. Celery logs (if applicable)

## Version Information

- **Python**: 3.11+
- **Celery**: 5.x
- **Pydantic**: 2.x
- **Loguru**: 0.7.x

---

**Happy coding with PyWorkflow!** 🚀
