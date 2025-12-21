# Celery Transient Workflows

## Important Note

**Celery runtime does not support transient (non-durable) workflows.**

This is by design: Celery requires state persistence for proper task routing, message acknowledgment, and workflow resumption across distributed workers.

## When to Use Transient Workflows

Transient workflows are useful for:
- Quick scripts that don't need persistence
- Testing and development
- CI/CD pipelines
- Simple, short-lived operations

## How to Run Transient Workflows

Use the `--runtime local` flag with `--no-durable`:

```bash
# Run durable workflow examples as transient using local runtime
pyworkflow --runtime local --module examples.celery.durable.01_basic_workflow \
    workflows run order_workflow \
    --arg order_id=order-123 --arg amount=99.99 \
    --no-durable
```

This executes the workflow in-process without:
- Event recording
- State persistence
- Distributed execution

## Comparison

| Feature | Celery Durable | Local Transient |
|---------|---------------|-----------------|
| Persistence | Yes | No |
| Event sourcing | Yes | No |
| Distributed | Yes | No |
| Sleep resumption | Automatic | Manual/None |
| Use case | Production | Dev/Testing |

## Recommended Approach

For development and testing:
1. Use `--runtime local` for quick iteration
2. Switch to `--runtime celery` (default) for production testing

```bash
# Development - fast, no persistence
pyworkflow --runtime local workflows run my_workflow --no-durable

# Production testing - with workers
pyworkflow workflows run my_workflow  # Uses celery by default
```

## See Also

- [Local transient examples](../../local/transient/) - Examples designed for transient execution
- [Celery durable examples](../durable/) - Production-ready durable workflows
- [Local durable examples](../../local/durable/) - Durable workflows without Celery
