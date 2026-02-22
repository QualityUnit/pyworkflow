---
name: Harness Gap Report
about: Convert a production regression into a harness improvement
title: "[HARNESS GAP] "
labels: harness-gap, quality
assignees: ''
---

## Incident Summary

<!-- What happened in production? Include date, severity, and user impact. -->

## Root Cause

<!-- Why did this happen? What was the underlying defect? -->

## What Should Have Caught It

Which harness layer should have prevented this regression?

- [ ] Pre-commit hooks (`ruff check` / `ruff format`)
- [ ] Risk policy gate (mis-classified tier, skipped checks)
- [ ] CI pipeline (`ruff` lint / `mypy` type-check / `pytest` / `python -m build`)
- [ ] Review agent
- [ ] Architectural linter (boundary violations: `core` ← `engine` ← `celery`)
- [ ] Structural tests (harness smoke)
- [ ] Other: ___

## Proposed Harness Improvement

<!-- What specific check, test, rule, or gate should be added or strengthened? -->

## Affected Critical Paths

<!-- Which paths from harness.config.json are affected? Check all that apply. -->

- [ ] `pyproject.toml`
- [ ] `poetry.lock`
- [ ] `pyworkflow/engine/executor.py`
- [ ] `pyworkflow/engine/replay.py`
- [ ] `pyworkflow/celery/tasks.py`
- [ ] `pyworkflow/storage/base.py`
- [ ] `harness.config.json`
- [ ] None of the above (new critical path needed)

## SLO Target

- [ ] **P0**: Within 24 hours (active production breakage)
- [ ] **P1**: Within 1 week (high-risk gap, could recur imminently)
- [ ] **P2**: Within 1 sprint (medium-risk, workaround exists)
- [ ] **P3**: Next planning cycle (defense-in-depth, low urgency)

## Test Case Specification

Describe the test that would catch this regression going forward:

- **Input / preconditions**: <!-- e.g., "A PR that modifies `pyworkflow/engine/replay.py` with a corrupted event ordering" -->
- **Expected behavior**: <!-- e.g., "CI fails at `pytest` with an event-replay integrity assertion" -->
- **Actual behavior**: <!-- e.g., "PR merged; workflow state silently corrupted on replay" -->
- **Files to test**: <!-- e.g., "`pyworkflow/engine/replay.py`, `tests/unit/test_replay.py`" -->

## Evidence

<!-- Links to incident reports, error logs, Sentry traces, or related PRs/issues. -->

---

> **Process**: After filing this issue, add a priority label (`P0`/`P1`/`P2`/`P3`) and update [docs/harness-gaps.md](../../docs/harness-gaps.md). See the [incident-to-harness loop process](../../docs/harness-gaps.md#process) for next steps.
