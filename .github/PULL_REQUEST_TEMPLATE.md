## Summary
<!-- What this PR does and why. Link to the issue if applicable. -->

## Risk Tier
<!-- The risk-policy-gate auto-detects the tier, but classify here for reviewer context. -->
<!-- See harness.config.json for full pattern definitions. -->
- [ ] **Tier 1 (Low)**: `docs/**`, `*.md`, `LICENSE`, `MANIFEST.in`, `.gitignore`, `.editorconfig`
- [ ] **Tier 2 (Medium)**: `pyworkflow/**/*.py`, `tests/**`, `examples/**`, `.github/workflows/**`, `.pre-commit-config.yaml`
- [ ] **Tier 3 (High)**: `pyproject.toml`, `poetry.lock`, `pyworkflow/engine/executor.py`, `pyworkflow/engine/replay.py`, `pyworkflow/celery/tasks.py`, `pyworkflow/storage/base.py`, `harness.config.json`

## Changes
<!-- Group modified files by logical concern. -->

### Added
-

### Changed
-

### Removed
-

## Testing
<!-- How were these changes validated? -->
- [ ] Unit tests added/updated (`tests/unit/`)
- [ ] Integration tests added/updated (`tests/integration/`)
- [ ] Manual testing completed
- [ ] All checks pass locally:
  ```
  ruff check . && mypy pyworkflow --ignore-missing-imports && pytest
  ```

## Evidence
<!-- Tier 1: none required. Tier 2: tests-pass + lint-clean + type-check-clean. Tier 3: all of Tier 2 + manual-review. -->

| Check | Result |
|-------|--------|
| `ruff check .` | <!-- PASS / FAIL --> |
| `mypy pyworkflow --ignore-missing-imports` | <!-- PASS / FAIL --> |
| `pytest` | <!-- PASS / FAIL --> |
| `python -m build` | <!-- PASS / FAIL --> |

## Architectural Compliance
<!-- Confirm module dependency rules from CLAUDE.md are respected. -->
- [ ] Import direction upheld: `core` ← `engine` ← `celery`
- [ ] No imports from `celery/` inside `core/` or `engine/`
- [ ] `storage/` introduces no upward dependencies
- [ ] `primitives/` only uses `context/` and `storage/`

## Review Checklist
- [ ] Code follows project conventions (`docs/conventions.md`, `CLAUDE.md`)
- [ ] Type hints present on all public APIs; modern union syntax used (`X | None`, not `Optional[X]`)
- [ ] All I/O is `async`/`await`; no blocking calls in step/workflow code
- [ ] Errors raised via `FatalError` or `RetryableError` — no silent exception swallowing
- [ ] No secrets, API keys, or `.env` files committed
- [ ] No ruff rules or mypy checks disabled without documented reason
- [ ] External inputs validated with Pydantic at system boundaries
- [ ] `poetry.lock` committed if `pyproject.toml` changed
- [ ] Documentation updated if public API changed
- [ ] Risk tier accurately reflects the scope of changes
