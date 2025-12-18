# PyWorkflow Examples

Welcome to PyWorkflow examples! This directory contains practical examples demonstrating different runtimes and execution modes.

## Quick Start

**New to PyWorkflow?** Start here:
1. Read [local/README.md](local/README.md) to understand LocalRuntime
2. Try [local/durable/01_basic_workflow.py](local/durable/01_basic_workflow.py) - your first event-sourced workflow
3. Compare with [local/transient/01_quick_tasks.py](local/transient/01_quick_tasks.py) - fast, simple execution

## Directory Structure

```
examples/
├── local/          In-process execution (start here!)
│   ├── durable/    Event-sourced workflows with persistence
│   └── transient/  Fast execution without persistence
├── celery/         Distributed execution with Celery (coming soon)
└── aws/            AWS Lambda serverless runtime (coming soon)
```

## Runtime Selection Guide

### Local Runtime (`local/`)
**Best for:** Development, testing, single-machine deployments

- **Durable mode**: Event-sourced workflows with crash recovery
  - Perfect for: Payment processing, long-running jobs, critical workflows
  - Examples: 6 examples from basic to advanced
  - Storage: InMemoryStorageBackend or FileStorageBackend

- **Transient mode**: Fast, simple execution
  - Perfect for: Scripts, CLI tools, short-lived tasks
  - Examples: 3 examples covering basics to error handling
  - Storage: None required

### Celery Runtime (`celery/`)
**Coming Soon** - Distributed task execution across multiple workers

### AWS Runtime (`aws/`)
**Coming Soon** - Serverless execution on AWS Lambda

## Decision Tree

### Should I use Durable or Transient mode?

Use **Durable Mode** if you need:
- Crash recovery and fault tolerance
- Long-running workflows (hours/days)
- Audit trail (event log)
- Workflow suspension/resumption
- Idempotency guarantees

Use **Transient Mode** if:
- Workflow completes in seconds/minutes
- No need for crash recovery
- Simplicity over durability
- No external state persistence needed

## Running Examples

All examples can be run directly:

```bash
# Durable mode example
python examples/local/durable/01_basic_workflow.py 2>/dev/null

# Transient mode example
python examples/local/transient/01_quick_tasks.py 2>/dev/null
```

The `2>/dev/null` suppresses INFO-level logs for cleaner output.

## Example Progression

### Durable Mode Learning Path
1. `01_basic_workflow.py` - Foundation: simple 3-step workflow
2. `02_file_storage.py` - Persistence with FileStorageBackend
3. `03_retries.py` - Error handling and automatic retries
4. `04_long_running.py` - Sleep and suspension/resumption
5. `05_event_log.py` - Event sourcing deep dive
6. `06_idempotency.py` - Duplicate prevention

### Transient Mode Learning Path
1. `01_quick_tasks.py` - Simple workflow execution
2. `02_retries.py` - Inline retry mechanics
3. `03_sleep.py` - Async sleep behavior

## Key Concepts

### Event Sourcing (Durable Mode)
Every state change is recorded as an immutable event. On crash recovery, PyWorkflow replays events to restore state and resume from the suspension point.

### Suspension & Resumption (Durable Mode)
When a workflow calls `sleep()` or waits for a webhook, it suspends (releases resources) and can be resumed later, even after process restart.

### Storage Backends
- **InMemoryStorageBackend**: Fast, data lost on process exit (testing)
- **FileStorageBackend**: Persistent, human-readable JSON files (development)
- **Future**: Redis, PostgreSQL, SQLite (production)

## Getting Help

- Check individual README files in each directory for detailed guides
- Read [CLAUDE.md](../CLAUDE.md) for architecture documentation
- Run examples with verbose logging: remove `2>/dev/null` from run commands

## Next Steps

1. Explore [local/durable/](local/durable/) examples for production-ready workflows
2. Explore [local/transient/](local/transient/) examples for simple tasks
3. Stay tuned for Celery and AWS runtime examples!
