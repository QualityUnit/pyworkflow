# Harness Gap Tracker

Tracks gaps identified in the harness engineering setup through production incidents. Each gap represents a regression that our harness system should have prevented.

## Metrics

| Metric | Target | Current |
|--------|--------|---------|
| Mean time to harness (MTTH) | < 7 days | - |
| Open P0 gaps | 0 | 0 |
| Open P1 gaps | < 3 | 0 |
| Gap close rate (monthly) | > 80% | - |
| Repeat regression rate | 0% | 0% |

> Updated weekly by the [weekly-metrics workflow](../.github/workflows/weekly-metrics.yml). Run manually via `workflow_dispatch` for on-demand updates.

## SLO Definitions

| Priority | SLO | Description |
|----------|-----|-------------|
| **P0** | 24 hours | Active production breakage. Drop everything. |
| **P1** | 1 week | High-risk gap that could recur imminently. |
| **P2** | 1 sprint | Medium-risk gap with a known workaround. |
| **P3** | Next planning cycle | Defense-in-depth improvement, low urgency. |

## Open Gaps

<!-- Auto-updated by weekly-metrics workflow. Manual edits are overwritten. -->

| # | Title | Priority | Layer | Created | SLO Due |
|---|-------|----------|-------|---------|---------|
| - | No open gaps | - | - | - | - |

## Closed Gaps

| # | Title | Layer | Resolution | Closed |
|---|-------|-------|------------|--------|
| - | No closed gaps yet | - | - | - |

## Process

1. **Report**: When a production incident occurs, create a [Harness Gap issue](../.github/ISSUE_TEMPLATE/harness-gap.md) using the template.
2. **Triage**: Add a priority label (`P0`–`P3`) and identify the harness layer that should have caught it.
3. **Implement**: Add the missing test, rule, or gate. Reference the gap issue in the PR.
4. **Verify**: Confirm the new check would have caught the original regression (re-run against the offending commit if possible).
5. **Close**: Close the issue and update this tracker.
6. **Review**: Weekly metrics report verifies SLO compliance and flags overdue gaps.

## Harness Layers Reference

| Layer | Catches | Tools |
|-------|---------|-------|
| Pre-commit hooks | Local quality issues before push | `ruff check`, `ruff format` |
| Risk policy gate | Mis-classified PR risk | `risk-policy-gate.yml` |
| CI pipeline | Build/test/lint/type failures | `ruff`, `mypy`, `pytest`, `python -m build` |
| Review agent | Logic errors, missing tests | `code-review-agent.yml` |
| Architectural linter | Boundary violations (`core`←`engine`←`celery`) | `structural-tests.yml` |
| Structural tests | Harness config drift, missing critical files | `harness-smoke.yml` |

## Critical Paths (Tier 3)

Changes to these paths require lint + type-check + full test suite + review-agent sign-off + manual human review:

| Path | Risk | Reason |
|------|------|--------|
| `pyproject.toml` | High | Dependency versions and build config affect every environment |
| `poetry.lock` | High | Lock file drift causes non-reproducible builds |
| `pyworkflow/engine/executor.py` | High | Main execution loop — bugs break all workflow runs |
| `pyworkflow/engine/replay.py` | High | Bugs here corrupt persisted workflow state |
| `pyworkflow/celery/tasks.py` | High | Celery entry points and recovery logic |
| `pyworkflow/storage/base.py` | High | StorageBackend ABC — breaking changes affect all backends |
| `harness.config.json` | High | Defines risk tiers and CI gate requirements |
