# PyWorkflow

A Python implementation of durable, event-sourced workflows inspired by [Vercel's Workflow Development Kit](https://github.com/vercel/workflow).

## About This Project

PyWorkflow brings the power of durable workflows to Python developers. It enables building long-running, fault-tolerant workflows with automatic retry, sleep/delay capabilities, webhook integration, and complete observability.

---

## Analysis of Vercel Workflow (TypeScript)

This project is inspired by Vercel's Workflow framework. Here's our analysis of the original TypeScript implementation:

### Core Architecture

**Event-Sourced Execution Model**
- Complete event log captures all workflow state changes
- Deterministic replay enables fault tolerance and resumption
- Events stored in append-only log with sequence numbers

**Two-Tier Queue System**
- **Workflow Queue**: Handles workflow orchestration (lightweight, high priority)
- **Step Queue**: Executes actual business logic (worker-intensive, scalable)

**Suspension & Resumption**
- Workflows suspend at `sleep()` and `createHook()` calls
- Zero resources consumed during suspension
- Automatic resumption via scheduled tasks or webhook triggers

### Key Features from Vercel Workflow

| Feature | Description | Implementation |
|---------|-------------|----------------|
| **Workflows** | Durable orchestration functions | Async functions with `"use workflow"` directive |
| **Steps** | Isolated, retryable units of work | Functions with `"use step"` directive |
| **Sleep** | Time-based delays | `sleep("5s")`, `sleep("2h")`, `sleep("3d")` |
| **Hooks** | External event integration | `createHook()` for webhooks |
| **Retry** | Automatic retry with backoff | Default 3 attempts, configurable |
| **Error Handling** | Fatal vs Retriable errors | `FatalError`, `RetryableError` |
| **Event Log** | Complete execution history | All state changes recorded |
| **Storage** | Pluggable backends | PostgreSQL (PgBoss), Local (file-based) |

### API Design (Vercel Workflow)

```typescript
// Workflow definition
async function processOrder(orderId: string) {
  "use workflow";

  const order = await validateOrder(orderId);
  await sleep("5m");
  const shipment = await createShipment(orderId);

  return shipment;
}

// Step definition
async function validateOrder(orderId: string) {
  "use step";
  // Business logic with full Node.js access
  return order;
}

// With webhooks
async function paymentFlow(orderId: string) {
  "use workflow";

  const hook = await createHook();
  await sendWebhook(hook.url);

  const result = await hook; // Suspends until webhook receives data
  return result;
}
```

### Technical Implementation Details

**Serialization** (Vercel uses `devalue` library)
- Complex type support: Date, Map, Set, Error, Stream, ArrayBuffer
- Binary data → Base64 encoding
- Errors → Structured objects with stack traces

**Queue Integration** (Vercel uses PgBoss for PostgreSQL)
- Workflow invocations → workflow queue
- Step executions → step queue
- Idempotency keys prevent duplicate execution

**Event Types**
- `workflow_started`, `workflow_completed`, `workflow_failed`
- `step_started`, `step_completed`, `step_failed`, `step_retrying`
- `wait_created`, `wait_completed`
- `hook_created`, `hook_received`, `hook_disposed`

---

## PyWorkflow: Python Implementation

### Design Goals

1. **Pythonic API**: Use decorators (`@workflow`, `@step`) instead of string directives
2. **Dual API**: Support both functional (decorators) and OOP (classes) styles
3. **Production-Ready**: Leverage battle-tested Celery for task execution
4. **Pluggable Storage**: Multiple backends from Day 1 (File, Redis, SQLite, PostgreSQL)
5. **Type Safety**: Full type hints and Pydantic validation
6. **Observability**: Structured logging with Loguru

### Quick Start

#### Installation

```bash
pip install pyworkflow
```

#### Basic Example (Functional API)

```python
from pyworkflow import workflow, step, start

@workflow
async def greet_user(name: str):
    message = await create_greeting(name)
    await send_message(message)
    return message

@step
async def create_greeting(name: str):
    return f"Hello, {name}!"

@step
async def send_message(message: str):
    print(message)
    return True

# Start workflow
run_id = await start(greet_user, "Alice")
```

#### Basic Example (OOP API)

```python
from pyworkflow import Workflow, Step

class GreetWorkflow(Workflow):
    name = "greet_user"

    async def run(self, name: str):
        message = await CreateGreetingStep()(name)
        await SendMessageStep()(message)
        return message

class CreateGreetingStep(Step):
    async def execute(self, name: str):
        return f"Hello, {name}!"

class SendMessageStep(Step):
    async def execute(self, message: str):
        print(message)
        return True

# Usage
workflow = GreetWorkflow()
run_id = await workflow.start("Alice")
```

### Core Features

#### 1. Sequential and Parallel Execution

```python
@workflow
async def process_order(order_id: str):
    # Sequential
    order = await validate_order(order_id)

    # Parallel execution
    import asyncio
    payment, inventory = await asyncio.gather(
        process_payment(order["total"]),
        reserve_inventory(order["items"])
    )

    # Continue sequential
    shipment = await create_shipment(order_id)
    return shipment
```

#### 2. Sleep and Delays

```python
@workflow
async def onboarding_flow(user_id: str):
    await send_welcome_email(user_id)

    await sleep("1d")  # Sleep for 1 day
    await send_tips_email(user_id)

    await sleep("3d")  # Sleep for 3 more days
    await send_feedback_request(user_id)
```

#### 3. Webhooks and External Events

```python
@workflow
async def payment_flow(order_id: str, amount: float):
    # Create webhook
    payment_hook = await create_hook(timeout="30m")

    # Send to payment provider
    await initiate_payment(order_id, amount, payment_hook.url)

    # Workflow suspends here (no resources used)
    payment_result = await payment_hook

    if payment_result["status"] == "success":
        await fulfill_order(order_id)

    return payment_result
```

#### 4. Error Handling and Retries

```python
from pyworkflow import FatalError, RetryableError

@step(max_retries=5, retry_delay="exponential")
async def call_external_api(url: str):
    try:
        response = await httpx.get(url)

        if response.status_code == 404:
            raise FatalError("Resource not found")  # Don't retry

        if response.status_code >= 500:
            raise RetryableError("Server error", retry_after="30s")  # Retry

        return response.json()
    except httpx.NetworkError:
        raise RetryableError("Network error")  # Retry with exponential backoff
```

### Architecture Comparison

| Aspect | Vercel Workflow (TS) | PyWorkflow (Python) |
|--------|---------------------|---------------------|
| **API Style** | String directives (`"use workflow"`) | Decorators (`@workflow`) + Classes |
| **Execution** | Custom VM isolation | Celery workers |
| **Queue System** | Custom (PgBoss) | Celery (Redis/RabbitMQ) |
| **Serialization** | devalue library | cloudpickle + JSON |
| **Logging** | Custom | Loguru |
| **Type Safety** | TypeScript types | Python type hints + Pydantic |
| **Storage** | PostgreSQL, Local | File, Redis, SQLite, PostgreSQL |
| **Event Sourcing** | ✅ Full event log | ✅ Full event log |
| **Sleep** | ✅ Duration strings | ✅ Duration strings + timedelta |
| **Hooks** | ✅ External events | ✅ External events + type safety |

### Key Differences

**Advantages of PyWorkflow:**
- ✅ Dual API (functional + OOP) for different programming styles
- ✅ Multiple storage backends out of the box
- ✅ Production-ready Celery integration (proven at scale)
- ✅ Type-safe hooks with Pydantic validation
- ✅ More Pythonic (decorators vs string directives)

**Vercel Workflow Advantages:**
- VM isolation provides stronger step independence
- Tighter integration with Vercel platform
- Built-in streaming response support

### Feature Parity Status

| Feature | Status | Notes |
|---------|--------|-------|
| Basic Workflows | ⏳ In Progress | Phase 1 |
| Steps with Retry | ⏳ In Progress | Phase 1 |
| Event Sourcing | ⏳ In Progress | Phase 1 |
| File Storage | ⏳ In Progress | Phase 1 |
| Sleep/Delays | 📋 Planned | Phase 2 |
| Hooks/Webhooks | 📋 Planned | Phase 2 |
| Redis Storage | 📋 Planned | Phase 2 |
| SQLite Storage | 📋 Planned | Phase 2 |
| PostgreSQL Storage | 📋 Planned | Phase 3 |
| Observability | 📋 Planned | Phase 3 |
| CLI Tools | 📋 Planned | Phase 3 |
| Parallel Execution | 📋 Planned | Phase 4 |
| Nested Workflows | 📋 Planned | Phase 4 |

### Project Status

🚧 **Status**: Early Development (Phase 1 - Core MVP)

**Current Focus**: Building core workflow execution with event sourcing

**Next Milestones**:
- ✅ Project structure and dependencies
- ⏳ Core decorators and execution engine
- ⏳ File-based storage backend
- ⏳ Celery integration
- ⏳ Basic error handling and retry

### Development Roadmap

**Phase 1: Core MVP** (Weeks 1-3)
- Basic workflow and step execution
- Event sourcing engine
- File-based storage
- Celery integration
- Simple error handling

**Phase 2: Durability Features** (Weeks 4-6)
- Sleep and scheduling
- Hooks and webhooks
- Redis and SQLite storage
- Enhanced serialization
- Retry strategies

**Phase 3: Production Ready** (Weeks 7-9)
- PostgreSQL storage
- Structured logging and metrics
- CLI management tools
- Idempotency support
- Performance optimization

**Phase 4: Advanced Features** (Optional)
- Parallel execution helpers
- Nested workflows
- Web UI
- Framework integrations

## Contributing

Contributions are welcome! This project is in early development.

### Setting Up Development Environment

```bash
# Clone repository
git clone https://github.com/yourusername/pyworkflow
cd pyworkflow

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black pyworkflow tests
ruff check pyworkflow tests

# Type checking
mypy pyworkflow
```

### Development Guidelines

- Follow PEP 8 style guide
- Add type hints to all functions
- Write tests for new features
- Update documentation
- See `CLAUDE.md` for AI-assisted development guide

## Documentation

- [API Reference](docs/api-reference.md)
- [User Guide](docs/user-guide.md)
- [Storage Backends](docs/storage-backends.md)
- [Architecture](docs/architecture.md)
- [Examples](examples/)

## License

Apache License 2.0 - See [LICENSE](LICENSE) file for details.

## Acknowledgments

- Inspired by [Vercel Workflow Development Kit](https://github.com/vercel/workflow)
- Built with [Celery](https://docs.celeryq.dev/)
- Event sourcing patterns from [Temporal](https://temporal.io/)

## Links

- **Vercel Workflow**: https://github.com/vercel/workflow
- **Documentation**: https://useworkflow.dev/
- **Celery**: https://docs.celeryq.dev/

---

**Note**: This is a community project inspired by Vercel Workflow. It is not officially affiliated with Vercel.
