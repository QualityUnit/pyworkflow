# Celery Durable Workflow Examples

These examples demonstrate event-sourced, durable workflows running on Celery workers.

## Prerequisites

```bash
# Install dependencies
pip install pyworkflow celery[redis] redis

# Start Redis
docker run -d --name redis -p 6379:6379 redis:7-alpine

# Verify setup
pyworkflow setup --check
```

## Examples

| Example | Description | Key Concepts |
|---------|-------------|--------------|
| [01_basic_workflow.py](01_basic_workflow.py) | Simple 3-step order processing | Steps, events, distributed execution |
| [02_long_running.py](02_long_running.py) | Onboarding with scheduled emails | Sleep, automatic resumption |
| [03_retries.py](03_retries.py) | Flaky API with retry handling | RetryableError, FatalError, backoff |
| [04_batch_processing.py](04_batch_processing.py) | Process multiple items | Loops, aggregation |
| [05_idempotency.py](05_idempotency.py) | Payment with idempotency | Duplicate prevention |
| [06_fault_tolerance.py](06_fault_tolerance.py) | Automatic recovery from crashes | Worker loss, event replay |
| [07_hooks.py](07_hooks.py) | External events/webhooks | Hooks, callbacks |
| [08_cancellation.py](08_cancellation.py) | Graceful cancellation | cancel_workflow, CancellationError, shield |
| [09_child_workflows.py](09_child_workflows.py) | Parent-child workflow orchestration | start_child_workflow, ChildWorkflowHandle |
| [10_child_workflow_patterns.py](10_child_workflow_patterns.py) | Advanced child patterns | Nesting, parallel, error propagation |

## Running Examples

### Step 1: Start a Worker

Each example can run independently. Start a worker with the example module:

```bash
# For basic workflow
pyworkflow --module examples.celery.durable.01_basic_workflow worker run

# For long running
pyworkflow --module examples.celery.durable.02_long_running worker run

# Or run all examples with a combined import
pyworkflow --module examples.celery.durable worker run
```

### Step 2: Run the Workflow

In another terminal:

```bash
# Basic workflow
pyworkflow --module examples.celery.durable.01_basic_workflow workflows run order_workflow \
    --arg order_id=order-123 --arg amount=99.99

# Long running with sleep
pyworkflow --module examples.celery.durable.02_long_running workflows run onboarding_workflow \
    --arg user_id=user-456

# Retry demo
pyworkflow --module examples.celery.durable.03_retries workflows run retry_demo_workflow \
    --arg endpoint=/api/data

# Batch processing
pyworkflow --module examples.celery.durable.04_batch_processing workflows run batch_workflow \
    --arg batch_id=batch-789 --arg limit=5

# Idempotent payment
pyworkflow --module examples.celery.durable.05_idempotency workflows run payment_workflow \
    --arg payment_id=pay-123 --arg amount=99.99 \
    --idempotency-key payment-pay-123

# Child workflows (order fulfillment with children)
pyworkflow --module examples.celery.durable.09_child_workflows workflows run order_fulfillment_workflow \
    --arg order_id=order-456 --arg amount=149.99 --arg customer_email=customer@example.com

# Parallel child workflows
pyworkflow --module examples.celery.durable.10_child_workflow_patterns workflows run parallel_parent_workflow
```

### Step 3: Monitor Execution

```bash
# List all runs
pyworkflow runs list

# Check specific run
pyworkflow runs status <run_id>

# View event log
pyworkflow runs logs <run_id>
```

## Key Features

### Automatic Sleep Resumption

Unlike local runtime, Celery automatically resumes workflows after sleep:

```python
await sleep("30s")  # Workflow suspends, worker freed
# ... 30 seconds later, Celery resumes automatically
```

### Distributed Execution

Steps execute on any available worker:
- Scale step workers for heavy computation
- Workflow orchestration stays lightweight

### Event Sourcing

Every step is recorded:
- Replay from any point on failure
- Full audit trail
- Deterministic execution

### Graceful Cancellation

Cancel running or suspended workflows:

```bash
# Start a workflow that sleeps
pyworkflow --module examples.celery.durable.08_cancellation workflows run \
    cancellable_order_workflow --arg order_id=order-123

# Cancel it while sleeping
pyworkflow runs cancel <run_id> --reason "Customer cancelled"

# Or wait for cancellation to complete
pyworkflow runs cancel <run_id> --wait --reason "Customer cancelled"
```

Cancellation is checkpoint-based:
- Checked before each step, sleep, and hook
- Does NOT interrupt a step mid-execution
- Use `shield()` to protect cleanup code

### Child Workflows

Spawn child workflows for complex orchestration:

```bash
# Check parent and children
pyworkflow runs status <parent_run_id>
pyworkflow runs children <parent_run_id>
```

Child workflow features:
- Own run_id and event history
- Wait for completion or fire-and-forget
- Automatic cancellation when parent completes (TERMINATE policy)
- Max nesting depth of 3 levels
- Error propagation via ChildWorkflowFailedError

## Next Steps

- See [transient examples](../transient/) for when durable isn't needed
- Read the [main Celery README](../README.md) for full setup guide
- Explore [local examples](../../local/durable/) for simpler development
