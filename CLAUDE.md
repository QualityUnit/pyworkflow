# CLAUDE.md

## Project Overview

PyWorkflow (`pyworkflow-engine`) is a distributed, durable workflow orchestration framework for Python 3.11+. It uses event sourcing and Celery to build fault-tolerant, long-running workflows with automatic retry, sleep/delay, and webhook integration. No web framework; pure Python library.

## Build & Run Commands

```bash
# Install dependencies
poetry install

# Run tests
pytest

# Run single test file
pytest tests/unit/test_events.py

# Lint
ruff check .

# Format
black .

# Type check
mypy pyworkflow

# Pre-commit (all hooks)
pre-commit run --all-files
```

## Code Style Rules

- **Formatter**: black, line length 100
- **Linter**: ruff (rules: E, W, F, I, B, C4, UP, ARG, SIM)
- **Imports**: absolute only; order: stdlib → third-party → local (`pyworkflow.*`); isort black profile
- **Naming**: `snake_case` for functions/variables/files, `PascalCase` for classes, `UPPER_CASE` for constants
- **File naming**: `snake_case.py` throughout
- **Type hints**: required on all public APIs; use modern union syntax (`str | None`, not `Optional[str]`)
- **Async**: all I/O must be `async`/`await`; no blocking calls (`requests`, `time.sleep`) in step/workflow code
- **Error handling**: use `FatalError` (no retry) or `RetryableError(retry_after=...)` from `pyworkflow.core.exceptions`; never swallow exceptions silently
- **`__init__.py`**: F401 (unused import) is suppressed — re-exports are intentional

## Architecture Overview

```
pyworkflow/
├── core/          # @workflow / @step decorators and base classes
├── engine/        # Executor, event sourcing, replay, state machine
├── celery/        # Celery task definitions and workflow-Celery bridge
├── storage/       # StorageBackend ABC + file/redis/sqlite/postgres impls
├── primitives/    # sleep(), hook(), parallel(), retry strategies
├── context/       # WorkflowContext / LocalContext (contextvars-based)
├── serialization/ # Encoder (JSON + cloudpickle fallback) / Decoder
├── observability/ # Loguru structured logging, metrics
├── cli/           # Click CLI
└── utils/         # Duration parsing, helpers
```

**Dependency rule**: `core` ← `engine` ← `celery`; `primitives` may use `context` and `storage`; `storage` has no upward deps. Never import from `celery/` inside `core/` or `engine/`.

## Critical Paths — Extra Care Required

Changes to these paths require additional test coverage and **human review**:

- `pyproject.toml` — dependency versions, build config, tool settings
- `pyworkflow/engine/executor.py` — main execution loop
- `pyworkflow/engine/replay.py` — event replay; bugs here corrupt workflow state
- `pyworkflow/celery/tasks.py` — Celery task entry points, recovery logic
- `pyworkflow/storage/base.py` — StorageBackend ABC; breaking changes affect all backends

These are **Tier 3 (high risk)** per `harness.config.json`. All Tier 3 changes require: lint + type-check + full test suite + review-agent sign-off + manual human review.

## Security Constraints

- Never commit secrets, API keys, `.env` files, or credentials
- Never disable ruff rules, mypy checks, or pre-commit hooks inline without a documented reason
- Validate all external input (webhook payloads, step arguments) at system boundaries using Pydantic models
- Use parameterized queries for all database storage backends (never f-string SQL)
- Never pass unsanitized user input to shell commands or `eval`

## Dependency Management

```bash
poetry add <pkg>              # Add runtime dependency
poetry add --group dev <pkg>  # Add dev-only dependency
```

- Always commit `poetry.lock` after any dependency change
- Do not upgrade major versions (e.g., Celery 5→6, Pydantic 2→3) without explicit instruction
- Pin exact versions for production deps; use `>=` ranges for library deps in `pyproject.toml`

## Harness System Reference

- Risk tiers are defined in `harness.config.json`
- CI gates enforce risk-appropriate checks (lint, type-check, tests, review-agent) on every PR
- A review agent automatically reviews PRs and flags issues before human merge
- Pre-commit hooks (`ruff`, `ruff-format`) enforce local quality checks on every commit
- **Chrome DevTools MCP**: `.mcp.json` at project root configures `@modelcontextprotocol/server-puppeteer` — agents can use `mcp__puppeteer__*` tools to navigate, screenshot, inspect DOM, and validate UI behavior
- See `docs/architecture.md` and `docs/conventions.md` for detailed guidelines

## PR Conventions

- **Branch naming**: `<type>/<short-description>` (e.g., `feat/add-dynamodb-backend`, `fix/replay-race-condition`)
- **Commit messages**: Conventional Commits — `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`
- All PRs must pass lint, type-check, and full test suite CI gates before merge
- Classify every PR by risk tier (Tier 1 / 2 / 3) in the PR description
- Include the affected component (e.g., `engine`, `storage`, `primitives`) in the PR title
