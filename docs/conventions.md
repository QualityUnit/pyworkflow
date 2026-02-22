# Coding Conventions

This document is the authoritative reference for coding standards in PyWorkflow. Both human developers and AI coding agents must follow these rules.

## Naming Conventions

### Files
All source files use **snake_case** with `.py` extension (e.g., `workflow_base.py`, `step_context.py`, `child_handle.py`). Test files are prefixed `test_` (e.g., `test_cancellation.py`).

### Variables and Functions
**snake_case** for all variables and functions:
```python
async def start_child_workflow(workflow_func, *args, wait_for_completion=True): ...
run_id: str = generate_run_id()
retry_delay: str | int | list[int] = "exponential"
```

### Classes and Types
**PascalCase** with no prefix conventions:
```python
class WorkflowContext: ...
class LocalContext(WorkflowContext): ...
class StorageBackend(ABC): ...
class RetryableError(WorkflowError): ...
```

### Constants
**UPPER_SNAKE_CASE** for module-level constants:
```python
MAX_NESTING_DEPTH = 3
MAX_EVENTS_DEFAULT = 50_000
CELERY_QUEUE_WORKFLOWS = "pyworkflow.workflows"
CELERY_QUEUE_STEPS = "pyworkflow.steps"
```

### Enums
PascalCase class, UPPER_SNAKE_CASE members:
```python
class EventType(str, Enum):
    WORKFLOW_STARTED = "workflow_started"
    STEP_COMPLETED = "step_completed"
```

## Type Hints

Always use type hints. Prefer `X | Y` union syntax (Python 3.10+) over `Optional[X]` or `Union[X, Y]`:
```python
async def sleep(
    duration: str | int | float | timedelta | datetime,
    name: str | None = None,
) -> None: ...
```

Use `dict[str, Any]`, `list[str]`, `tuple[str, ...]` — lowercase generics, not `Dict`, `List`, `Tuple`.

## Import Organization

Standard order, one blank line between groups:
```python
# 1. stdlib
import asyncio
from datetime import datetime, timedelta
from typing import Any, Callable

# 2. third-party
from pydantic import BaseModel
from loguru import logger

# 3. internal (absolute)
from pyworkflow.core.exceptions import SuspensionSignal
from pyworkflow.engine.events import Event, EventType

# 4. relative (only within a subpackage)
from .base import StorageBackend
```

Never use wildcard imports (`from x import *`) outside of `__init__.py` re-exports.

## Error Handling

### Exception Hierarchy
Raise from the project's exception hierarchy (`core/exceptions.py`); never raise bare `Exception`:
```python
raise FatalError("Invalid order ID")          # non-retriable
raise RetryableError("Rate limited", retry_after="60s")  # auto-retried
raise WorkflowNotFoundError(run_id)           # domain error
```

`SuspensionSignal` and `ContinueAsNewSignal` extend `BaseException` — catch them explicitly before `except Exception` blocks.

### Error Messages
Include actionable context:
```python
# Good
raise ValueError(f"Step '{step_name}' not found in registry. Register it with @step.")
# Avoid
raise ValueError("Not found")
```

### Logging
Use the project logger from `observability/logging.py`. Pass structured key-value pairs — do not use f-strings in log messages:
```python
from pyworkflow.observability.logging import get_logger
logger = get_logger()
logger.info("Step completed", run_id=ctx.run_id, step_id=step_id, result=result)
```

Log levels:
- `DEBUG` — internal state transitions (replay events, retry attempts)
- `INFO` — workflow/step lifecycle milestones
- `WARNING` — recoverable failures (worker loss detected, retry scheduled)
- `ERROR` — unrecoverable failures before raising

## Async/Await

All I/O must be async. Never use blocking calls in async code:
```python
# Correct
async with httpx.AsyncClient() as client:
    response = await client.get(url)

# Wrong — blocks the event loop
response = requests.get(url)
```

Storage backend methods are all `async def`. Celery task execution uses an event loop bridge (`celery/loop.py`) to run async code from synchronous Celery task callbacks.

## Testing Conventions

### Test Location
- Unit tests: `tests/unit/test_<module>.py` — mirrors source module name
- Integration tests: `tests/integration/test_<feature>.py`
- Fixtures: `tests/unit/conftest.py`

### Test Naming
`test_<what>_<condition>`:
```python
def test_step_retries_on_retryable_error(): ...
def test_workflow_suspends_on_sleep(): ...
def test_replay_restores_step_results(): ...
```

### Async Tests
Mark with `@pytest.mark.asyncio`:
```python
@pytest.mark.asyncio
async def test_workflow_execution():
    run_id = await start(my_workflow, "arg")
    ...
```

### Mocking
Unit tests mock storage and Celery. Use `InMemoryStorageBackend` for integration tests that need real storage behavior without database setup:
```python
from pyworkflow.storage.memory import InMemoryStorageBackend
storage = InMemoryStorageBackend()
```

### What Must Be Tested
- All public API functions in `pyworkflow/__init__.py`
- Every `EventType` transition in `engine/replay.py`
- Every `StorageBackend` implementation against the contract in `storage/base.py`
- Retry exhaustion, cancellation, and suspension/resumption paths

## Code Style

**Formatter**: black (enforced; run `black .` before pushing)

**Linter**: ruff (enforced; run `ruff check .` before pushing)

**Type checker**: mypy (strict mode; run `mypy pyworkflow/` before pushing)

Do not disable ruff or mypy rules without a code comment explaining why.

## Git Workflow

### Branch Naming
```
feat/<short-description>
fix/<short-description>
chore/<short-description>
docs/<short-description>
refactor/<short-description>
test/<short-description>
```

### Commit Messages
[Conventional Commits](https://www.conventionalcommits.org/) format:
```
feat: add continue_as_new primitive
fix: handle SuspensionSignal in broad except blocks
chore: bump celery to 5.4.0
docs: document child workflow nesting limits
refactor: extract _poll_child_completion to engine/executor
test: add integration test for DynamoDB backend
```

### PR Guidelines
- One concern per PR. Do not mix feature changes with unrelated refactors.
- Classify by risk tier in the PR description (see Code Review Standards below).
- All checks (lint, type-check, tests) must pass before review.

## Code Review Standards

| Tier | Scope | Required Checks |
|---|---|---|
| **Tier 1** (low) | Docs, comments, config | lint |
| **Tier 2** (medium) | Feature code, new primitives, storage backends | lint, mypy, pytest, review-agent |
| **Tier 3** (high) | `engine/executor.py`, `engine/replay.py`, `core/exceptions.py`, storage migrations | lint, mypy, pytest, review-agent, manual sign-off |

**Automated checks**: lint (ruff), type correctness (mypy), full test suite (pytest).

**Human reviewers focus on**:
- Event sourcing correctness: Does the new code record the right events in the right order?
- Replay safety: Will this code behave identically on replay as on first execution?
- Suspension correctness: Does `SuspensionSignal` propagate without being swallowed?
- Backward compatibility: Do existing stored events still replay correctly?
