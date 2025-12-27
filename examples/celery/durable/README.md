# Celery Durable Workflow Examples

These examples demonstrate event-sourced, durable workflows running on Celery workers.

## Project Structure

```
examples/celery/durable/
├── pyworkflow.config.yaml    # Configuration (module: workflows)
├── docker-compose.yml        # Docker setup for Redis + Dashboard
├── workflows/                # Workflow package
│   ├── __init__.py          # Exports all workflows
│   ├── basic.py             # Simple order processing
│   ├── long_running.py      # Onboarding with sleeps
│   ├── retries.py           # Retry handling
│   ├── batch_processing.py  # Batch processing
│   ├── idempotency.py       # Idempotent payments
│   ├── fault_tolerance.py   # Worker crash recovery
│   ├── hooks.py             # Webhooks/approvals
│   ├── cancellation.py      # Graceful cancellation
│   ├── child_workflows.py   # Parent-child orchestration
│   ├── child_workflow_patterns.py  # Advanced patterns
│   ├── continue_as_new.py   # Long-running with state reset
│   └── schedules.py         # Scheduled workflows
└── README.md
```

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
| [basic.py](workflows/basic.py) | Simple 3-step order processing | Steps, events, distributed execution |
| [long_running.py](workflows/long_running.py) | Onboarding with scheduled emails | Sleep, automatic resumption |
| [retries.py](workflows/retries.py) | Flaky API with retry handling | RetryableError, FatalError, backoff |
| [batch_processing.py](workflows/batch_processing.py) | Process multiple items | Loops, aggregation |
| [idempotency.py](workflows/idempotency.py) | Payment with idempotency | Duplicate prevention |
| [fault_tolerance.py](workflows/fault_tolerance.py) | Automatic recovery from crashes | Worker loss, event replay |
| [hooks.py](workflows/hooks.py) | External events/webhooks | Hooks, callbacks |
| [cancellation.py](workflows/cancellation.py) | Graceful cancellation | cancel_workflow, CancellationError, shield |
| [child_workflows.py](workflows/child_workflows.py) | Parent-child workflow orchestration | start_child_workflow, ChildWorkflowHandle |
| [child_workflow_patterns.py](workflows/child_workflow_patterns.py) | Advanced child patterns | Nesting, parallel, error propagation |
| [continue_as_new.py](workflows/continue_as_new.py) | Long-running with fresh state | continue_as_new, pagination, streaming |
| [schedules.py](workflows/schedules.py) | Scheduled/recurring workflows | Cron, intervals, schedule management |

## Running Examples

### Step 1: Start a Worker

```bash
# Start worker (discovers all workflows from workflows/ package)
pyworkflow worker start
```

### Step 2: Run a Workflow

In another terminal:

```bash
# Basic workflow
pyworkflow workflows run order_workflow \
    --input '{"order_id": "order-123", "amount": 99.99}'

# Long running with sleep
pyworkflow workflows run onboarding_workflow \
    --input '{"user_id": "user-456"}'

# Retry demo
pyworkflow workflows run retry_demo_workflow \
    --input '{"endpoint": "/api/data"}'

# Batch processing
pyworkflow workflows run batch_workflow \
    --input '{"batch_id": "batch-789", "limit": 5}'

# Idempotent payment
pyworkflow workflows run idempotent_payment_workflow \
    --input '{"payment_id": "pay-123", "amount": 99.99}' \
    --idempotency-key payment-pay-123

# Child workflows (order fulfillment with children)
pyworkflow workflows run order_fulfillment_workflow \
    --input '{"order_id": "order-456", "amount": 149.99, "customer_email": "customer@example.com"}'

# Parallel child workflows
pyworkflow workflows run parallel_parent_workflow
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

## Using Docker Dashboard

Start the full stack with Docker:

```bash
# Generate docker-compose.yml
pyworkflow setup

# Start services
docker compose up -d

# Open dashboard
open http://localhost:5173
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
pyworkflow workflows run cancellable_order_workflow \
    --input '{"order_id": "order-123"}'

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

## Creating Your Own Project

Use this example as a template for your own project:

```
myproject/
├── pyworkflow.config.yaml    # module: myapp.workflows
├── myapp/
│   ├── __init__.py
│   └── workflows/
│       ├── __init__.py       # from .orders import process_order
│       └── orders.py         # @workflow decorated functions
```

The `module` field in `pyworkflow.config.yaml` should point to a Python package that, when imported, registers all workflows via the `@workflow` decorator.

## Next Steps

- See [transient examples](../transient/) for when durable isn't needed
- Read the [main Celery README](../README.md) for full setup guide
- Explore [local examples](../../local/durable/) for simpler development
