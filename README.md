# PyWorkflow

**Distributed, durable workflow orchestration for Python**

Build long-running, fault-tolerant workflows with automatic retry, sleep/delay capabilities, and complete observability. PyWorkflow uses event sourcing and Celery for production-grade distributed execution.

---

## What is PyWorkflow?

PyWorkflow is a workflow orchestration framework that enables you to build complex, long-running business processes as simple Python code. It handles the hard parts of distributed systems: fault tolerance, automatic retries, state management, and horizontal scaling.

### Key Features

- **Distributed by Default**: All workflows execute across Celery workers for horizontal scaling
- **Durable Execution**: Event sourcing ensures workflows can recover from any failure
- **Auto Recovery**: Automatic workflow resumption after worker crashes with event replay
- **Time Travel**: Sleep for minutes, hours, or days with automatic resumption
- **Fault Tolerant**: Automatic retries with configurable backoff strategies
- **Zero-Resource Suspension**: Workflows suspend without holding resources during sleep
- **Production Ready**: Built on battle-tested Celery and Redis
- **Fully Typed**: Complete type hints and Pydantic validation
- **Observable**: Structured logging with workflow context

---

## Quick Start

### Installation

**Basic installation** (File and Memory storage backends):
```bash
pip install pyworkflow-engine
```

**With optional storage backends:**
```bash
# Redis backend (includes Redis as Celery broker)
pip install pyworkflow-engine[redis]

# SQLite backend
pip install pyworkflow-engine[sqlite]

# PostgreSQL backend
pip install pyworkflow-engine[postgres]

# All storage backends
pip install pyworkflow-engine[all]

# Development (includes all backends + dev tools)
pip install pyworkflow-engine[dev]
```

### Prerequisites

**For distributed execution** (recommended for production):

PyWorkflow uses Celery for distributed task execution. You need a message broker:

**Option 1: Redis (recommended)**
```bash
# Install Redis support
pip install pyworkflow-engine[redis]

# Start Redis
docker run -d -p 6379:6379 redis:7-alpine

# Start Celery worker(s)
celery -A pyworkflow.celery.app worker --loglevel=info

# Start Celery Beat (for automatic sleep resumption)
celery -A pyworkflow.celery.app beat --loglevel=info
```

Or use the CLI to set up Docker infrastructure:
```bash
pyworkflow setup
```

**Option 2: Other brokers** (RabbitMQ, etc.)
```bash
# Celery supports multiple brokers
# Configure via environment: CELERY_BROKER_URL=amqp://localhost
```

**For local development/testing:**
```bash
# No broker needed - use in-process execution
pyworkflow configure --runtime local
```

See [DISTRIBUTED.md](DISTRIBUTED.md) for complete deployment guide.

### Your First Workflow

```python
from pyworkflow import workflow, step, start, sleep

@step()
async def send_welcome_email(user_id: str):
    # This runs on any available Celery worker
    print(f"Sending welcome email to user {user_id}")
    return f"Email sent to {user_id}"

@step()
async def send_tips_email(user_id: str):
    print(f"Sending tips email to user {user_id}")
    return f"Tips sent to {user_id}"

@workflow()
async def onboarding_workflow(user_id: str):
    # Send welcome email immediately
    await send_welcome_email(user_id)

    # Sleep for 1 day - workflow suspends, zero resources used
    await sleep("1d")

    # Automatically resumes after 1 day!
    await send_tips_email(user_id)

    return "Onboarding complete"

# Start workflow - executes across Celery workers
run_id = start(onboarding_workflow, user_id="user_123")
print(f"Workflow started: {run_id}")
```

**What happens:**
1. Workflow starts on a Celery worker
2. Welcome email is sent
3. Workflow suspends after calling `sleep("1d")`
4. Worker is freed to handle other tasks
5. After 1 day, Celery Beat automatically schedules resumption
6. Workflow resumes on any available worker
7. Tips email is sent

---

## Core Concepts

### Workflows

Workflows are the top-level orchestration functions. They coordinate steps, handle business logic, and can sleep for extended periods.

```python
from pyworkflow import workflow, start

@workflow(name="process_order", max_duration="1h")
async def process_order(order_id: str):
    """
    Process a customer order.

    This workflow:
    - Validates the order
    - Processes payment
    - Creates shipment
    - Sends confirmation
    """
    order = await validate_order(order_id)
    payment = await process_payment(order)
    shipment = await create_shipment(order)
    await send_confirmation(order)

    return {"order_id": order_id, "status": "completed"}

# Start the workflow
run_id = start(process_order, order_id="ORD-123")
```

### Steps

Steps are the building blocks of workflows. Each step is an isolated, retryable unit of work that runs on Celery workers.

```python
from pyworkflow import step, RetryableError, FatalError

@step(max_retries=5, retry_delay="exponential")
async def call_external_api(url: str):
    """
    Call external API with automatic retry.

    Retries up to 5 times with exponential backoff if it fails.
    """
    try:
        response = await httpx.get(url)

        if response.status_code == 404:
            # Don't retry - resource doesn't exist
            raise FatalError("Resource not found")

        if response.status_code >= 500:
            # Retry - server error
            raise RetryableError("Server error", retry_after="30s")

        return response.json()
    except httpx.NetworkError:
        # Retry with exponential backoff
        raise RetryableError("Network error")
```

### Sleep and Delays

Workflows can sleep for any duration. During sleep, the workflow suspends and consumes zero resources.

```python
from pyworkflow import workflow, sleep

@workflow()
async def scheduled_reminder(user_id: str):
    # Send immediate reminder
    await send_reminder(user_id, "immediate")

    # Sleep for 1 hour
    await sleep("1h")
    await send_reminder(user_id, "1 hour later")

    # Sleep for 1 day
    await sleep("1d")
    await send_reminder(user_id, "1 day later")

    # Sleep for 1 week
    await sleep("7d")
    await send_reminder(user_id, "1 week later")

    return "All reminders sent"
```

**Supported formats:**
- Duration strings: `"5s"`, `"10m"`, `"2h"`, `"3d"`
- Timedelta: `timedelta(hours=2, minutes=30)`
- Datetime: `datetime(2025, 12, 25, 9, 0, 0)`

---

## Architecture

### Event-Sourced Execution

PyWorkflow uses event sourcing to achieve durable, fault-tolerant execution:

1. **All state changes are recorded as events** in an append-only log
2. **Deterministic replay** enables workflow resumption from any point
3. **Complete audit trail** of everything that happened in the workflow

**Event Types** (16 total):
- Workflow: `started`, `completed`, `failed`, `suspended`, `resumed`
- Step: `started`, `completed`, `failed`, `retrying`
- Sleep: `created`, `completed`
- Logging: `info`, `warning`, `error`, `debug`

### Distributed Execution

```
┌─────────────────────────────────────────────────────┐
│                   Your Application                  │
│                                                     │
│  start(my_workflow, args)                          │
│         │                                           │
└─────────┼───────────────────────────────────────────┘
          │
          ▼
    ┌─────────┐
    │  Redis  │  ◄──── Message Broker
    └─────────┘
          │
          ├──────┬──────┬──────┐
          ▼      ▼      ▼      ▼
     ┌──────┐ ┌──────┐ ┌──────┐
     │Worker│ │Worker│ │Worker│  ◄──── Horizontal Scaling
     └──────┘ └──────┘ └──────┘
          │      │      │
          └──────┴──────┘
                 │
                 ▼
          ┌──────────┐
          │ Storage  │  ◄──── Event Log (File/Redis/PostgreSQL)
          └──────────┘
```

### Storage Backends

PyWorkflow supports pluggable storage backends:

| Backend | Status | Installation | Use Case |
|---------|--------|--------------|----------|
| **File** | ✅ Complete | Included | Development, single-machine |
| **Memory** | ✅ Complete | Included | Testing, ephemeral workflows |
| **SQLite** | ✅ Complete | `pip install pyworkflow-engine[sqlite]` | Embedded, local persistence |
| **PostgreSQL** | ✅ Complete | `pip install pyworkflow-engine[postgres]` | Production, enterprise |
| **Redis** | 📋 Planned | `pip install pyworkflow-engine[redis]` | High-performance, distributed |

---

## Advanced Features

### Parallel Execution

Use Python's native `asyncio.gather()` for parallel step execution:

```python
import asyncio
from pyworkflow import workflow, step

@step()
async def fetch_user(user_id: str):
    # Fetch user data
    return {"id": user_id, "name": "Alice"}

@step()
async def fetch_orders(user_id: str):
    # Fetch user orders
    return [{"id": "ORD-1"}, {"id": "ORD-2"}]

@step()
async def fetch_recommendations(user_id: str):
    # Fetch recommendations
    return ["Product A", "Product B"]

@workflow()
async def dashboard_data(user_id: str):
    # Fetch all data in parallel
    user, orders, recommendations = await asyncio.gather(
        fetch_user(user_id),
        fetch_orders(user_id),
        fetch_recommendations(user_id)
    )

    return {
        "user": user,
        "orders": orders,
        "recommendations": recommendations
    }
```

### Error Handling

PyWorkflow distinguishes between retriable and fatal errors:

```python
from pyworkflow import FatalError, RetryableError, step

@step(max_retries=3, retry_delay="exponential")
async def process_payment(amount: float):
    try:
        # Attempt payment
        result = await payment_gateway.charge(amount)
        return result
    except InsufficientFundsError:
        # Don't retry - user doesn't have enough money
        raise FatalError("Insufficient funds")
    except PaymentGatewayTimeoutError:
        # Retry - temporary issue
        raise RetryableError("Gateway timeout", retry_after="10s")
    except Exception as e:
        # Unknown error - retry with backoff
        raise RetryableError(f"Unknown error: {e}")
```

**Retry strategies:**
- `retry_delay="fixed"` - Fixed delay between retries (default: 60s)
- `retry_delay="exponential"` - Exponential backoff (1s, 2s, 4s, 8s, ...)
- `retry_delay="5s"` - Custom fixed delay

### Auto Recovery

Workflows automatically recover from worker crashes:

```python
from pyworkflow import workflow, step, sleep

@workflow(
    recover_on_worker_loss=True,    # Enable recovery (default for durable)
    max_recovery_attempts=5,         # Max recovery attempts
)
async def resilient_workflow(data_id: str):
    data = await fetch_data(data_id)    # Completed steps are skipped on recovery
    await sleep("10m")                   # Sleep state is preserved
    return await process_data(data)      # Continues from here after crash
```

**What happens on worker crash:**
1. Celery detects worker loss, requeues task
2. New worker picks up the task
3. Events are replayed to restore state
4. Workflow resumes from last checkpoint

Configure globally:
```python
import pyworkflow

pyworkflow.configure(
    default_recover_on_worker_loss=True,
    default_max_recovery_attempts=3,
)
```

Or via config file:
```yaml
# pyworkflow.config.yaml
recovery:
  recover_on_worker_loss: true
  max_recovery_attempts: 3
```

### Idempotency

Prevent duplicate workflow executions with idempotency keys:

```python
from pyworkflow import start

# Same idempotency key = same workflow
run_id_1 = start(
    process_order,
    order_id="ORD-123",
    idempotency_key="order-ORD-123"
)

# This will return the same run_id, not start a new workflow
run_id_2 = start(
    process_order,
    order_id="ORD-123",
    idempotency_key="order-ORD-123"
)

assert run_id_1 == run_id_2  # True!
```

### Observability

PyWorkflow includes structured logging with automatic context:

```python
from pyworkflow import configure_logging

# Configure logging
configure_logging(
    level="INFO",
    log_file="workflow.log",
    json_logs=True,  # JSON format for production
    show_context=True  # Include run_id, step_id, etc.
)

# Logs automatically include:
# - run_id: Workflow execution ID
# - workflow_name: Name of the workflow
# - step_id: Current step ID
# - step_name: Name of the step
```

---

## Testing

PyWorkflow uses a unified API for testing with local execution:

```python
import pytest
from pyworkflow import workflow, step, start, configure, reset_config
from pyworkflow.storage.memory import InMemoryStorageBackend

@step()
async def my_step(x: int):
    return x * 2

@workflow()
async def my_workflow(x: int):
    result = await my_step(x)
    return result + 1

@pytest.fixture(autouse=True)
def setup_storage():
    reset_config()
    storage = InMemoryStorageBackend()
    configure(storage=storage, default_durable=True)
    yield storage
    reset_config()

@pytest.mark.asyncio
async def test_my_workflow(setup_storage):
    storage = setup_storage
    run_id = await start(my_workflow, 5)

    # Get workflow result
    run = await storage.get_run(run_id)
    assert run.status.value == "completed"
```

---

## Production Deployment

### Docker Compose

```yaml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  worker:
    build: .
    command: celery -A pyworkflow.celery.app worker --loglevel=info
    depends_on:
      - redis
    deploy:
      replicas: 3  # Run 3 workers

  beat:
    build: .
    command: celery -A pyworkflow.celery.app beat --loglevel=info
    depends_on:
      - redis

  flower:
    build: .
    command: celery -A pyworkflow.celery.app flower --port=5555
    ports:
      - "5555:5555"
```

Start everything using the CLI:
```bash
pyworkflow setup
```

See [DISTRIBUTED.md](DISTRIBUTED.md) for complete deployment guide with Kubernetes.

---

## Examples

Check out the [examples/](examples/) directory for complete working examples:

- **[basic_workflow.py](examples/functional/basic_workflow.py)** - Complete example with retries, errors, and sleep
- **[distributed_example.py](examples/functional/distributed_example.py)** - Multi-worker distributed execution example

---

## Project Status

✅ **Status**: Production Ready (v1.0)

**Completed Features**:
- ✅ Core workflow and step execution
- ✅ Event sourcing with 16 event types
- ✅ Distributed execution via Celery
- ✅ Sleep primitive with automatic resumption
- ✅ Error handling and retry strategies
- ✅ File storage backend
- ✅ Structured logging
- ✅ Comprehensive test coverage (68 tests)
- ✅ Docker Compose deployment
- ✅ Idempotency support

**Next Milestones**:
- 📋 Redis storage backend
- 📋 PostgreSQL storage backend
- 📋 Webhook integration
- 📋 Web UI for monitoring
- 📋 CLI management tools

---

## Contributing

Contributions are welcome!

### Development Setup

```bash
# Clone repository
git clone https://github.com/QualityUnit/pyworkflow
cd pyworkflow

# Install with Poetry
poetry install

# Run tests
poetry run pytest

# Format code
poetry run black pyworkflow tests
poetry run ruff check pyworkflow tests

# Type checking
poetry run mypy pyworkflow
```

---

## Documentation

- **[Distributed Deployment Guide](DISTRIBUTED.md)** - Production deployment with Docker Compose and Kubernetes
- [Examples](examples/) - Working examples and patterns
- [API Reference](docs/api-reference.md) (Coming soon)
- [Architecture Guide](docs/architecture.md) (Coming soon)

---

## License

Apache License 2.0 - See [LICENSE](LICENSE) file for details.

---

## Links

- **Documentation**: https://docs.pyworkflow.dev
- **GitHub**: https://github.com/QualityUnit/pyworkflow
- **Issues**: https://github.com/QualityUnit/pyworkflow/issues
