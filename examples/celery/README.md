# Celery Runtime Examples

This directory contains example workflows designed to run on Celery workers, demonstrating distributed execution with automatic sleep resumption.

## Directory Structure

```
celery/
├── README.md           # This file
├── durable/            # Event-sourced, persistent workflows
│   ├── 01_basic_workflow.py      # Simple 3-step order processing
│   ├── 02_long_running.py        # Sleep with auto-resumption
│   ├── 03_retries.py             # Retry handling
│   ├── 04_batch_processing.py    # Batch item processing
│   └── 05_idempotency.py         # Duplicate prevention
└── transient/          # Not supported (see README)
    └── README.md       # Explanation and alternatives
```

## Prerequisites

- Python 3.11+
- Redis (as Celery broker and result backend)
- PyWorkflow with Celery dependencies

```bash
pip install pyworkflow celery[redis] redis
```

## Quick Start

### 1. Start Redis

```bash
docker run -d --name redis -p 6379:6379 redis:7-alpine
```

### 2. Verify Environment

```bash
pyworkflow setup --check
```

### 3. Start Celery Workers

```bash
# Option A: Run from the examples directory with config file (RECOMMENDED)
cd examples/celery/durable
pyworkflow worker run

# Option B: Use --module flag from project root
pyworkflow --module examples.celery.durable worker run

# Option C: Use environment variable
PYWORKFLOW_DISCOVER=examples.celery.durable pyworkflow worker run
```

### 4. List Available Workflows

```bash
pyworkflow --module examples.celery.durable workflows list
```

Output:
```
Registered Workflows
┏━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━┓
┃ Name                ┃ Max Duration ┃ Metadata ┃
┡━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━┩
│ order_workflow      │ -            │ -        │
│ onboarding_workflow │ -            │ -        │
│ retry_demo_workflow │ -            │ -        │
│ batch_workflow      │ -            │ -        │
│ payment_workflow    │ -            │ -        │
└─────────────────────┴──────────────┴──────────┘
```

## Running Examples

### Basic Workflow

```bash
pyworkflow --module examples.celery.durable workflows run order_workflow \
    --arg order_id=order-123 --arg amount=99.99
```

### Long Running with Sleep

```bash
pyworkflow --module examples.celery.durable workflows run onboarding_workflow \
    --arg user_id=user-456
```

Watch the worker output to see automatic resumption after each 30-second sleep.

### Retry Demo

```bash
pyworkflow --module examples.celery.durable workflows run retry_demo_workflow \
    --arg endpoint=/api/data
```

### Batch Processing

```bash
pyworkflow --module examples.celery.durable workflows run batch_workflow \
    --arg batch_id=batch-789 --arg limit=5
```

### Idempotent Payment

```bash
# First run - starts new workflow
pyworkflow --module examples.celery.durable workflows run payment_workflow \
    --arg payment_id=pay-123 --arg amount=99.99 \
    --idempotency-key payment-pay-123

# Second run with same key - returns existing run (no duplicate charge)
pyworkflow --module examples.celery.durable workflows run payment_workflow \
    --arg payment_id=pay-123 --arg amount=99.99 \
    --idempotency-key payment-pay-123
```

## Monitoring Workflows

```bash
# List recent runs
pyworkflow runs list

# Filter by status
pyworkflow runs list --status completed
pyworkflow runs list --status suspended

# Check specific run
pyworkflow runs status <run_id>

# View event log
pyworkflow runs logs <run_id>
pyworkflow runs logs <run_id> --filter step_completed
```

## Worker Management

### Start Specialized Workers

For production, run separate workers for each queue type:

```bash
# Terminal 1: Workflow orchestration (lightweight)
pyworkflow --module examples.celery.durable worker run --workflow --concurrency 2

# Terminal 2+: Step execution (scale for heavy work)
pyworkflow --module examples.celery.durable worker run --step --concurrency 8

# Terminal N: Schedule handling (for sleep resumption)
pyworkflow --module examples.celery.durable worker run --schedule --concurrency 2
```

### Check Worker Status

```bash
pyworkflow worker status
pyworkflow worker queues
```

## Configuration

### Using Config File (Recommended)

Create `pyworkflow.config.yaml` in your working directory:

```yaml
# Module containing workflow definitions
module: examples.celery.durable

# Runtime configuration
runtime: celery

# Storage backend
storage:
  backend: file
  path: ./workflow_data

# Celery settings
celery:
  broker: redis://localhost:6379/0
  result_backend: redis://localhost:6379/1
```

Now commands are simpler (run from directory containing config):
```bash
cd examples/celery/durable
pyworkflow worker run
pyworkflow workflows list
pyworkflow workflows run order_workflow --arg order_id=123 --arg amount=50
```

### Discovery Priority

PyWorkflow discovers workflows in this order:

1. `--module` CLI argument (highest priority)
2. `PYWORKFLOW_DISCOVER` environment variable
3. `pyworkflow.config.yaml` in current directory

### Environment Variables

```bash
export PYWORKFLOW_MODULE=examples.celery.durable
export PYWORKFLOW_CELERY_BROKER=redis://localhost:6379/0
export PYWORKFLOW_CELERY_RESULT_BACKEND=redis://localhost:6379/1
```

## Transient Workflows

Celery runtime **only supports durable workflows** due to its distributed nature.

For transient (non-persistent) execution, use `--runtime local`:

```bash
pyworkflow --runtime local --module examples.celery.durable workflows run order_workflow \
    --arg order_id=123 --arg amount=50 --no-durable
```

See [transient/README.md](transient/README.md) for more details.

## Troubleshooting

### Workers Not Picking Up Tasks

1. Ensure Redis is running: `redis-cli ping` should return `PONG`
2. Check broker URL matches in workers and CLI
3. Verify workflows are imported: `python -c "import examples.celery.durable"`

### Workflows Stuck in "suspended"

Ensure a worker is processing the `pyworkflow.schedules` queue:
```bash
pyworkflow worker run  # Processes all queues including schedules
```

### Enable Debug Logging

```bash
pyworkflow --verbose worker run --loglevel debug
```

## Comparison: Local vs Celery Runtime

| Feature | Local Runtime | Celery Runtime |
|---------|---------------|----------------|
| Execution | In-process | Distributed workers |
| Sleep resumption | Manual | Automatic |
| Scaling | Single process | Horizontal scaling |
| Transient support | Yes | No |
| Use case | Dev/Testing/CI | Production |

## Next Steps

- [durable/README.md](durable/README.md) - Detailed durable examples
- [transient/README.md](transient/README.md) - Why transient isn't supported
- [../local/](../local/) - Local runtime examples
- [../../docs/guides/cli.mdx](../../docs/guides/cli.mdx) - Full CLI documentation
