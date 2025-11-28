# Distributed Execution Guide

This guide explains how to deploy PyWorkflow in a distributed environment using Celery for horizontal scaling.

## Architecture

```
┌─────────────────┐
│   Your App      │
│  (starts        │
│   workflows)    │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────┐
│         Celery Broker               │
│         (Redis/RabbitMQ)            │
│  - Queues workflow/step tasks       │
│  - Manages task distribution        │
└─────────┬───────────────────────────┘
          │
          ├──────────┬──────────┬──────────┐
          ▼          ▼          ▼          ▼
    ┌─────────┐┌─────────┐┌─────────┐┌─────────┐
    │ Worker 1││ Worker 2││ Worker 3││ Worker N│
    │         ││         ││         ││         │
    │ Executes││ Executes││ Executes││ Executes│
    │  steps  ││  steps  ││  steps  ││  steps  │
    └────┬────┘└────┬────┘└────┬────┘└────┬────┘
         │          │          │          │
         └──────────┴──────────┴──────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │  Storage Backend       │
         │  (Redis/PostgreSQL)    │
         │  - Workflow state      │
         │  - Event logs          │
         │  - Results             │
         └───────────────────────┘
```

## Quick Start

### 1. Install Dependencies

```bash
# Install PyWorkflow with Celery support
poetry install --extras redis

# Or with pip
pip install pyworkflow[redis]
```

### 2. Start Redis

```bash
# Using Docker
docker run -d -p 6379:6379 redis:7-alpine

# Or install locally
# Mac: brew install redis && redis-server
# Ubuntu: sudo apt-get install redis-server && redis-server
```

### 3. Start Celery Worker(s)

```bash
# Terminal 1: Start worker for step execution
celery -A pyworkflow.celery.app worker \
    --loglevel=info \
    --queues=pyworkflow.steps \
    --concurrency=4

# Terminal 2: Start worker for workflow orchestration
celery -A pyworkflow.celery.app worker \
    --loglevel=info \
    --queues=pyworkflow.workflows \
    --concurrency=2

# Terminal 3: Start Celery Beat for scheduled tasks (sleep resumption)
celery -A pyworkflow.celery.app beat --loglevel=info
```

### 4. Start Workflows

```python
from pyworkflow import workflow, step, start, sleep

@step()
async def process_item(item_id: int):
    # This runs on any available worker
    return f"Processed {item_id}"

@workflow
async def my_workflow(item_id: int):
    result = await process_item(item_id)
    await sleep("5m")  # Automatically resumes after 5 minutes!
    return result

# Start workflow - executes across workers
run_id = start(my_workflow, item_id=123)
```

## Production Deployment

### Using Docker Compose

```yaml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  worker:
    build: .
    command: celery -A pyworkflow.celery.app worker --loglevel=info
    environment:
      - CELERY_BROKER_URL=redis://redis:6379/0
      - CELERY_RESULT_BACKEND=redis://redis:6379/1
    depends_on:
      - redis
    deploy:
      replicas: 3  # Scale to 3 workers

  beat:
    build: .
    command: celery -A pyworkflow.celery.app beat --loglevel=info
    environment:
      - CELERY_BROKER_URL=redis://redis:6379/0
      - CELERY_RESULT_BACKEND=redis://redis:6379/1
    depends_on:
      - redis

  app:
    build: .
    command: python your_app.py
    environment:
      - CELERY_BROKER_URL=redis://redis:6379/0
      - CELERY_RESULT_BACKEND=redis://redis:6379/1
    depends_on:
      - redis
      - worker
      - beat

volumes:
  redis_data:
```

### Using Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: pyworkflow-worker
spec:
  replicas: 5
  selector:
    matchLabels:
      app: pyworkflow-worker
  template:
    metadata:
      labels:
        app: pyworkflow-worker
    spec:
      containers:
      - name: worker
        image: your-registry/pyworkflow:latest
        command: ["celery", "-A", "pyworkflow.celery.app", "worker", "--loglevel=info"]
        env:
        - name: CELERY_BROKER_URL
          value: "redis://redis-service:6379/0"
        - name: CELERY_RESULT_BACKEND
          value: "redis://redis-service:6379/1"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: pyworkflow-beat
spec:
  replicas: 1
  selector:
    matchLabels:
      app: pyworkflow-beat
  template:
    metadata:
      labels:
        app: pyworkflow-beat
    spec:
      containers:
      - name: beat
        image: your-registry/pyworkflow:latest
        command: ["celery", "-A", "pyworkflow.celery.app", "beat", "--loglevel=info"]
        env:
        - name: CELERY_BROKER_URL
          value: "redis://redis-service:6379/0"
        - name: CELERY_RESULT_BACKEND
          value: "redis://redis-service:6379/1"
```

## Configuration

### Environment Variables

```bash
# Celery Broker
export CELERY_BROKER_URL="redis://localhost:6379/0"

# Result Backend
export CELERY_RESULT_BACKEND="redis://localhost:6379/1"

# Worker Configuration
export CELERY_WORKER_CONCURRENCY=4
export CELERY_WORKER_PREFETCH_MULTIPLIER=1

# Task Settings
export CELERY_TASK_ACKS_LATE=True
export CELERY_TASK_REJECT_ON_WORKER_LOST=True
```

### Custom Celery Configuration

```python
from pyworkflow.celery import create_celery_app

# Create custom Celery app
app = create_celery_app(
    broker_url="redis://redis-cluster:6379/0",
    result_backend="redis://redis-cluster:6379/1",
    app_name="my_workflows"
)

# Additional configuration
app.conf.update(
    task_time_limit=3600,  # 1 hour max per task
    worker_max_tasks_per_child=100,  # Restart worker after 100 tasks
)
```

## Monitoring

### Celery Flower (Web UI)

```bash
# Install Flower
pip install flower

# Start Flower
celery -A pyworkflow.celery.app flower --port=5555

# Access at http://localhost:5555
```

### Prometheus + Grafana

```python
# Install celery-exporter
pip install celery-exporter

# Start exporter
celery-exporter --broker-url=redis://localhost:6379/0
```

## Performance Tuning

### Worker Configuration

```bash
# CPU-bound tasks
celery -A pyworkflow.celery.app worker --concurrency=8 --pool=prefork

# I/O-bound tasks
celery -A pyworkflow.celery.app worker --concurrency=100 --pool=gevent

# Mixed workload
celery -A pyworkflow.celery.app worker --concurrency=16 --pool=eventlet
```

### Queue Priorities

```python
from pyworkflow import start

# All workflows use the default queue
run_id = start(critical_workflow)

# Note: Custom queue routing is configured at the Celery level,
# not per-workflow. See Celery documentation for advanced routing:
# https://docs.celeryq.dev/en/stable/userguide/routing.html
```

## Troubleshooting

### Workers Not Picking Up Tasks

1. Check broker connection:
   ```bash
   celery -A pyworkflow.celery.app inspect ping
   ```

2. Verify queues:
   ```bash
   celery -A pyworkflow.celery.app inspect active_queues
   ```

3. Check worker status:
   ```bash
   celery -A pyworkflow.celery.app inspect stats
   ```

### Tasks Failing Silently

1. Enable verbose logging:
   ```bash
   celery -A pyworkflow.celery.app worker --loglevel=debug
   ```

2. Check result backend:
   ```python
   from pyworkflow.celery import celery_app

   result = celery_app.AsyncResult(task_id)
   print(result.state)
   print(result.traceback)
   ```

### Sleep Not Auto-Resuming

1. Ensure Celery Beat is running:
   ```bash
   celery -A pyworkflow.celery.app beat --loglevel=info
   ```

2. Check scheduled tasks:
   ```bash
   celery -A pyworkflow.celery.app inspect scheduled
   ```

## Best Practices

1. **Use Redis for distributed environments** instead of FileStorageBackend
2. **Set task timeouts** to prevent stuck workers
3. **Enable task acks_late** for fault tolerance
4. **Use queues** to separate different types of work
5. **Monitor worker health** with Flower or Prometheus
6. **Scale workers** based on queue depth and latency
7. **Use idempotency keys** for critical workflows
8. **Implement circuit breakers** for external service calls

## See Also

- [Celery Documentation](https://docs.celeryproject.org/)
- [Redis Best Practices](https://redis.io/docs/management/optimization/)
- [Kubernetes Scaling](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/)
