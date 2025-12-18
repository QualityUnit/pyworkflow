# Celery Runtime Examples

**Status:** Coming Soon

## Overview

The Celery runtime enables distributed workflow execution across multiple workers, allowing you to scale PyWorkflow horizontally across machines.

## What Celery Runtime Will Enable

### Distributed Execution
- Execute workflows across multiple worker machines
- Scale step execution horizontally
- Separate orchestration (workflow) from execution (steps)

### Two-Queue Architecture
- **Workflows Queue**: Lightweight orchestration logic
- **Steps Queue**: Heavy computational work (scalable)

### Use Cases
- High-volume workflow processing
- Resource-intensive step execution
- Multi-machine deployments
- Load balancing across workers

## Current Status

Celery runtime integration is planned for a future release. In the meantime:

### Get Started with Local Runtime

Explore the [local/](../local/) examples to learn PyWorkflow fundamentals:
- [local/durable/](../local/durable/) - Event-sourced workflows with persistence
- [local/transient/](../local/transient/) - Fast, simple execution

### What You'll Learn

The workflow and step definitions you write for LocalRuntime will work seamlessly with CeleryRuntime once available. You'll only need to change the runtime configuration.

## Example Preview

```python
from pyworkflow import configure, start, step, workflow
from pyworkflow.runtime import CeleryRuntime

# Configure Celery runtime
runtime = CeleryRuntime(broker="redis://localhost:6379/0")
configure(default_runtime=runtime)

@step()
async def expensive_computation(data: dict) -> dict:
    # This will execute on a Celery worker
    return process_data(data)

@workflow(durable=True)
async def distributed_workflow(input_data: dict) -> dict:
    # This orchestration runs on workflow worker
    result = await expensive_computation(input_data)
    return result

# Start distributed workflow
run_id = await start(distributed_workflow, {"value": 42})
```

## Stay Updated

Check back here for updates, or explore the existing [local runtime examples](../local/) to get started with PyWorkflow today.

## Questions?

- Read [CLAUDE.md](../../CLAUDE.md) for architecture details
- Check [examples/README.md](../README.md) for navigation
- Explore [local/README.md](../local/README.md) to get started
