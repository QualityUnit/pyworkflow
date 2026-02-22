## Agent-Generated PR

**Agent**: <!-- agent name and version (e.g., Claude Code v1.0, remediation-bot) -->
**Trigger**: <!-- what triggered this PR: remediation, feature request, scheduled task -->
**Head SHA**: `<!-- exact 40-character commit SHA this PR was generated at -->`

## Summary
<!-- Auto-generated summary describing all changes. -->

## Risk Assessment
- **Detected Risk Tier**: <!-- auto-populated by risk-policy-gate -->
- **Critical paths touched**:
  <!-- List any files matching Tier 3 patterns from harness.config.json:
       pyproject.toml, poetry.lock,
       pyworkflow/engine/executor.py, pyworkflow/engine/replay.py,
       pyworkflow/celery/tasks.py, pyworkflow/storage/base.py,
       harness.config.json -->
  -
- **Confidence level**: <!-- high / medium / low -->

## Changes Made
<!-- Complete list of every file modified. -->

| File | Change Type | Description |
|------|-------------|-------------|
| | added / modified / deleted | |

## Validation Results

| Check | Status | Command |
|-------|--------|---------|
| Lint | <!-- PASS / FAIL --> | `ruff check .` |
| Type Check | <!-- PASS / FAIL --> | `mypy pyworkflow --ignore-missing-imports` |
| Tests | <!-- PASS / FAIL --> | `pytest` |
| Build | <!-- PASS / FAIL --> | `python -m build` |
| Structural Tests | <!-- PASS / FAIL --> | `bash scripts/structural-tests.sh` |

## Architectural Compliance
- [ ] Import direction upheld: `core` ← `engine` ← `celery`
- [ ] No imports from `celery/` inside `core/` or `engine/`
- [ ] `storage/` introduces no upward dependencies
- [ ] No protected files modified outside of intended scope (`.github/workflows/`, `harness.config.json`, `CLAUDE.md`, `poetry.lock`)

## Review Agent Status
- [ ] Review agent has analyzed this PR
- [ ] No unresolved blocking findings
- [ ] Review SHA matches current HEAD (`<!-- SHA -->`)
- **Verdict**: <!-- APPROVE / REQUEST_CHANGES / PENDING -->

## Human Review Required
<!-- Tier 3 changes require manual approval via the tier3-approval environment gate (minApprovals: 2). -->
- [ ] Required — Tier 3 (high-risk) changes detected
- [ ] Optional but recommended — Tier 2 changes

## Remediation History
<!-- Only if this PR was created or updated by the remediation agent. Remove this section otherwise. -->
- **Original PR**: #<!-- number -->
- **Remediation attempt**: <!-- 1 / 2 / 3 (max 3) -->
- **Findings fixed**: <!-- count -->
- **Findings skipped**: <!-- count, with brief reasons -->
- **Validation after fix**: <!-- all passed / partial — specify which failed -->
