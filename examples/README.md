# PyWorkflow Examples

This directory contains examples demonstrating various PyWorkflow features and use cases.

## Directory Structure

- **functional/** - Examples using the functional decorator-based API
- **oop/** - Examples using the object-oriented class-based API (coming soon)
- **real_world/** - Real-world use cases and patterns (coming soon)

## Getting Started

### Basic Example

Start with the basic workflow example to understand core concepts:

```bash
cd examples/functional
python basic_workflow.py
```

This example demonstrates:
- Defining workflows and steps
- Sequential execution
- Error handling and retries
- Using sleep for delays
- Idempotent workflow execution

## Available Examples

### Functional API

#### `basic_workflow.py`
A simple order processing workflow that demonstrates:
- User data fetching with automatic retry
- Data validation with fatal errors
- Payment processing
- Durable sleep/delays
- Email confirmation

**Run it:**
```bash
python examples/functional/basic_workflow.py
```

## Coming Soon

More examples will be added covering:
- Parallel step execution
- Webhooks and hooks for external events
- Custom storage backends (Redis, PostgreSQL)
- Complex retry strategies
- Workflow composition
- Error recovery patterns
- Testing workflows
- Production deployment patterns

## Documentation

For detailed documentation, see:
- [Main README](../README.md) - Project overview
- [CLAUDE.md](../CLAUDE.md) - Development guide
- [API Documentation](../docs/) - Detailed API reference

## Contributing

Have an example use case? Feel free to contribute! See the main README for contribution guidelines.
