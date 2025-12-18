# Transient Mode Examples

Fast, simple workflow execution without persistence or crash recovery.

## What is Transient Mode?

Transient mode (`durable=False`) executes workflows directly in-process without event sourcing. No storage backend is required, making it perfect for scripts, CLI tools, and short-lived tasks.

## Key Characteristics

### No Persistence
- No events recorded
- No storage backend required
- State lost when process exits
- No crash recovery

### Direct Execution
- Workflows run like regular async functions
- Steps execute immediately (no event replay)
- Sleep uses `asyncio.sleep()` (blocks the workflow)
- Fast execution with minimal overhead

### Inline Retries
- Retries work with `@step(max_retries=3, retry_delay=1)`
- Retry logic runs inline (no event log needed)
- Failures cause immediate re-execution
- Configurable delays between retries

## When to Use Transient Mode

**Use transient mode for:**
- CLI tools and scripts
- Short-lived workflows (seconds to minutes)
- Data processing pipelines
- Testing and development
- Tasks where simplicity > durability

**Don't use transient mode for:**
- Long-running workflows (hours/days)
- Workflows requiring crash recovery
- Workflows needing audit trails
- Critical workflows (payments, orders, etc.)

## Comparison with Durable Mode

| Feature | Transient Mode | Durable Mode |
|---------|----------------|--------------|
| **Storage** | None required | Required (InMemory, File, etc.) |
| **Crash Recovery** | ❌ None | ✅ Event replay |
| **Sleep Behavior** | `asyncio.sleep()` (blocks) | Suspends & resumes |
| **Audit Trail** | ❌ None | ✅ Complete event log |
| **Performance** | ⚡ Very fast | ⚠️  Slight overhead |
| **Complexity** | 🟢 Low | 🟡 Medium |
| **Retries** | ✅ Inline | ✅ Inline + recorded |
| **Idempotency** | ❌ None | ✅ Via idempotency keys |

## Examples

### 01_quick_tasks.py - Basics

**What it demonstrates:**
- Simple 3-step order workflow
- No storage backend configuration
- Fast, direct execution
- Basic `@workflow` and `@step` usage

**Key patterns:**
```python
from pyworkflow import configure, start, step, workflow

configure(default_durable=False)

@step()
async def process_order(order_id: str) -> dict:
    return {"order_id": order_id, "status": "processed"}

@workflow(durable=False)
async def order_workflow(order_id: str) -> dict:
    order = await process_order(order_id)
    return order
```

**Run:** `python 01_quick_tasks.py 2>/dev/null`

### 02_retries.py - Retry Mechanics

**What it demonstrates:**
- Inline retry with `@step(max_retries=3, retry_delay=1)`
- Simulated flaky API
- Retry behavior without event sourcing
- Global counter to track attempts

**Key patterns:**
```python
attempt_count = 0

@step(max_retries=3, retry_delay=1)
async def call_flaky_api(order: dict) -> dict:
    global attempt_count
    attempt_count += 1
    if attempt_count < 3:
        raise Exception(f"API timeout (attempt {attempt_count})")
    return {"api_response": "success"}
```

**Run:** `python 02_retries.py 2>/dev/null`

### 03_sleep.py - Async Sleep Behavior

**What it demonstrates:**
- `sleep()` uses `asyncio.sleep()` in transient mode
- No workflow suspension (just blocking sleep)
- Difference from durable sleep behavior
- Simple delay mechanism

**Key patterns:**
```python
@workflow(durable=False)
async def delayed_workflow():
    await step1()
    await sleep("5s")  # Blocks for 5 seconds (no suspension)
    await step2()
```

**Run:** `python 03_sleep.py 2>/dev/null`

## Learning Path

**Recommended order:**
1. **01_quick_tasks.py** - Start here for basic transient execution
2. **02_retries.py** - Learn inline retry mechanics
3. **03_sleep.py** - Understand sleep behavior

## Common Patterns

### Basic Configuration

```python
from pyworkflow import configure, reset_config

reset_config()
configure(default_durable=False)
```

**Note:** No storage backend needed!

### Workflow Definition

```python
@workflow(durable=False)
async def my_workflow(arg1: str, arg2: int) -> dict:
    result = await step1(arg1)
    result = await step2(result, arg2)
    return result
```

### Step with Retries

```python
@step(max_retries=3, retry_delay=1)
async def my_step(data: dict) -> dict:
    # Step logic here
    # Will retry up to 3 times on failure
    return processed_data
```

### Error Handling

```python
from pyworkflow import FatalError

@step()
async def validate_input(value: int) -> int:
    if value < 0:
        raise FatalError("Negative values not allowed")  # Won't retry
    return value
```

**Error types:**
- `FatalError` - Don't retry, fail immediately
- `Exception` - Retry if `max_retries > 0`

### Sleep Usage

```python
from pyworkflow import sleep

@workflow(durable=False)
async def workflow_with_delay():
    await step1()
    await sleep("5s")  # Blocks for 5 seconds
    await step2()
```

**Supported formats:**
- `sleep("5s")` - 5 seconds
- `sleep("2m")` - 2 minutes
- `sleep("1h")` - 1 hour
- `sleep(30)` - 30 seconds (int)

## Use Cases

### CLI Tool

```python
# process_files.py
import asyncio
from pyworkflow import configure, start, step, workflow

configure(default_durable=False)

@step()
async def read_file(path: str) -> str:
    with open(path) as f:
        return f.read()

@step()
async def transform_data(content: str) -> str:
    return content.upper()

@step()
async def write_file(path: str, content: str):
    with open(path, 'w') as f:
        f.write(content)

@workflow(durable=False)
async def process_file(input_path: str, output_path: str):
    content = await read_file(input_path)
    transformed = await transform_data(content)
    await write_file(output_path, transformed)

if __name__ == "__main__":
    import sys
    asyncio.run(start(process_file, sys.argv[1], sys.argv[2]))
```

### Data Processing Pipeline

```python
@step()
async def fetch_data(url: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        return response.json()

@step()
async def transform_data(data: dict) -> list:
    return [item["value"] for item in data["items"]]

@step()
async def save_results(results: list):
    with open("results.json", "w") as f:
        json.dump(results, f)

@workflow(durable=False)
async def data_pipeline(url: str):
    data = await fetch_data(url)
    results = await transform_data(data)
    await save_results(results)
```

## Troubleshooting

### Workflow crashes and loses all state

**Expected behavior in transient mode.** Use durable mode if you need crash recovery:

```python
# Switch to durable mode
from pyworkflow.storage import InMemoryStorageBackend

configure(
    storage=InMemoryStorageBackend(),
    default_durable=True
)
```

### Sleep blocks the entire process

**Expected behavior in transient mode.** Sleep uses `asyncio.sleep()` which blocks the workflow. If you need non-blocking sleep with suspension, use durable mode.

### No event log available

**Expected behavior in transient mode.** Transient mode doesn't record events. Use durable mode if you need audit trails.

## When to Upgrade to Durable Mode

Consider switching to durable mode when:
- Workflow execution time exceeds a few minutes
- You need crash recovery
- You need to suspend/resume workflows
- You need audit trails for compliance
- You need idempotency guarantees

**Migration is easy:**
```python
# Before (transient)
configure(default_durable=False)

# After (durable)
from pyworkflow.storage import FileStorageBackend
configure(
    storage=FileStorageBackend("./workflow_data"),
    default_durable=True
)
```

Your workflow code stays the same!

## Next Steps

- Explore [../durable/](../durable/) for production-ready event-sourced workflows
- Read [../README.md](../README.md) for LocalRuntime overview
- Check [CLAUDE.md](../../../CLAUDE.md) for architecture details
