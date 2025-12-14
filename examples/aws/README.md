# AWS Durable Lambda Functions Examples

This directory contains examples of PyWorkflow workflows running on AWS Lambda
with Durable Functions support.

## Prerequisites

Install PyWorkflow with AWS support:

```bash
pip install pyworkflow[aws]
```

## Examples

### order_workflow.py

A simple order processing workflow demonstrating:
- Step execution with automatic checkpointing
- Cost-free sleep/wait operations
- Passing data between steps

## Local Testing

All examples can be run locally with mock contexts:

```bash
python examples/aws/order_workflow.py
```

## Deploying to AWS

1. **Package your workflow with dependencies**:
   ```bash
   pip install pyworkflow[aws] -t package/
   cp your_workflow.py package/
   cd package && zip -r ../deployment.zip .
   ```

2. **Create Lambda function**:
   - Runtime: Python 3.11+
   - Enable Durable Functions in Lambda configuration
   - Handler: `your_workflow.handler`

3. **Invoke the workflow**:
   ```bash
   aws lambda invoke \
     --function-name your-workflow \
     --payload '{"order_id": "ORD-123"}' \
     response.json
   ```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    AWS Lambda + Durable Functions               │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ @aws_workflow_handler                                     │   │
│  │ @workflow                                                 │   │
│  │ async def order_workflow(ctx, order_id):                  │   │
│  │     validation = await validate_order(order_id)          │   │
│  │     ctx.sleep(300)  # Free wait!                         │   │
│  │     payment = await process_payment(...)                 │   │
│  │     return result                                        │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                  │
│                              ▼                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ AWS Durable Execution SDK                                │   │
│  │ - Automatic checkpointing                                │   │
│  │ - Replay on Lambda restart                               │   │
│  │ - Cost-free waits                                        │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Key Concepts

### Steps

Steps are automatically checkpointed. If your Lambda is interrupted:
- Completed steps won't re-run
- Results are replayed from checkpoints
- Execution continues from last checkpoint

```python
@step()
async def my_step(data: str) -> dict:
    return {"processed": data}
```

### Sleep/Wait

Sleep operations use AWS's native wait feature:
- No compute charges during wait
- Lambda is suspended, not running
- Execution resumes automatically

```python
ctx.sleep(300)  # Wait 5 minutes (no charges!)
ctx.sleep("1h")  # Also supports duration strings
```

### Error Handling

Use PyWorkflow's error types:

```python
from pyworkflow import FatalError, RetryableError

@step()
async def my_step():
    if permanent_failure:
        raise FatalError("Cannot proceed")  # No retry
    if temporary_failure:
        raise RetryableError("Try again")   # Will retry
```

## Testing

Use the mock context for local testing:

```python
from pyworkflow.aws.testing import MockDurableContext, create_test_handler

def test_my_workflow():
    mock_ctx = MockDurableContext()
    handler = create_test_handler(my_workflow, mock_ctx)

    result = handler({"input": "data"})

    assert "validate" in mock_ctx.checkpoints
    assert mock_ctx.wait_count > 0
```
