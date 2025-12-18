# AWS Lambda Runtime Examples

**Status:** Coming Soon

## Overview

The AWS Lambda runtime enables serverless workflow execution on AWS Lambda, leveraging AWS's Durable Execution features for fault-tolerant, long-running workflows.

## What AWS Runtime Will Enable

### Serverless Execution
- Run workflows on AWS Lambda (no server management)
- Automatic scaling based on demand
- Pay only for actual execution time

### AWS Durable Execution Integration
- **Cost-free sleep**: No charges during workflow sleep
- **Automatic checkpointing**: Steps never re-execute on retry
- **Managed durability**: AWS handles all state persistence
- **Parallel execution**: Built-in support for concurrent steps

### Use Cases
- Serverless microservices
- Event-driven workflows (S3, SNS, SQS triggers)
- Cost-optimized long-running workflows
- Auto-scaling workloads

## Current Status

AWS Lambda runtime integration is planned for a future release. In the meantime:

### Get Started with Local Runtime

Explore the [local/](../local/) examples to learn PyWorkflow fundamentals:
- [local/durable/](../local/durable/) - Event-sourced workflows with persistence
- [local/transient/](../local/transient/) - Fast, simple execution

### What You'll Learn

The workflow and step definitions you write for LocalRuntime will work seamlessly with AWSRuntime once available. You'll only need to change the runtime configuration.

## Example Preview

```python
from pyworkflow import configure, start, step, workflow
from pyworkflow.runtime import AWSRuntime
from pyworkflow.context import AWSContext

# Configure AWS runtime
runtime = AWSRuntime(region="us-east-1")
configure(default_runtime=runtime)

@step()
async def process_data(data: dict) -> dict:
    # This will execute on AWS Lambda with automatic checkpointing
    return transform_data(data)

@workflow(durable=True)
async def serverless_workflow(input_data: dict) -> dict:
    result = await process_data(input_data)

    # Sleep is FREE on AWS Lambda (no charges during sleep)
    await sleep("1h")

    final = await process_data(result)
    return final

# Deploy to AWS Lambda
# lambda_function.py:
from pyworkflow.aws import aws_workflow_handler

@aws_workflow_handler
async def handler(event, context):
    run_id = await start(serverless_workflow, event)
    return {"run_id": run_id}
```

## Key Features

### Cost-Free Sleep
Sleep operations on AWS Lambda incur no charges:
```python
await sleep("24h")  # Free! No Lambda charges for 24 hours
```

### Automatic Checkpointing
Steps are never re-executed on retry:
```python
@step()
async def expensive_computation(data):
    # Executes once, result cached by AWS
    return compute(data)
```

### Parallel Execution
Built-in parallel step support:
```python
results = await parallel(
    process_data(data1),
    process_data(data2),
    process_data(data3)
)
```

## Stay Updated

Check back here for updates, or explore the existing [local runtime examples](../local/) to get started with PyWorkflow today.

## Questions?

- Read [CLAUDE.md](../../CLAUDE.md) for architecture details
- Check [examples/README.md](../README.md) for navigation
- Explore [local/README.md](../local/README.md) to get started
