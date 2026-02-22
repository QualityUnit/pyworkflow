#!/usr/bin/env bash
# ============================================================================
# Risk Policy Gate — Preflight CI gate for PR risk classification
#
# Determines the risk tier and required CI checks for a pull request.
# Exit 0: gate passed (tier and checks computed for downstream jobs).
# Exit 1: hard failure (SHA mismatch, unrecoverable error).
#
# Environment variables (set by CI workflow):
#   EXPECTED_SHA          — PR head SHA from the CI event payload
#   BASE_REF              — PR base branch name (default: main)
#   STRICTNESS            — relaxed | standard | strict (default: relaxed)
#   REVIEW_AGENT_STATUS   — optional override from remediation loop
#   GITHUB_OUTPUT         — path to GitHub Actions output file (set by runner)
#   GITHUB_REPOSITORY     — owner/repo (set by runner)
# ============================================================================
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
CONFIG_FILE="${REPO_ROOT}/harness.config.json"
STRICTNESS="${STRICTNESS:-relaxed}"

# --- Globals populated during execution ---
VERIFIED_SHA=""
MAX_TIER=0
TIER1_FILES=()
TIER2_FILES=()
TIER3_FILES=()
REQUIRED_CHECKS=()
DOCS_DRIFT_DETECTED=false
DOCS_DRIFT_WARNING=""
REVIEW_AGENT_RESULT="skipped"

# ============================================================================
# harness.config.json Reader Utility
#
# Validates the config file and optionally extracts values. Falls back to
# built-in defaults when the file is missing or malformed. Uses python3
# (guaranteed present) or jq if available.
# ============================================================================
validate_config() {
  if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "::notice::harness.config.json not found — using built-in defaults"
    return 0
  fi

  local valid=false
  if command -v jq &>/dev/null; then
    jq empty "$CONFIG_FILE" 2>/dev/null && valid=true
  elif command -v python3 &>/dev/null; then
    python3 -c "import json; json.load(open('${CONFIG_FILE}'))" 2>/dev/null && valid=true
  else
    # Neither jq nor python3 available — assume valid and continue
    valid=true
  fi

  if ! $valid; then
    echo "::warning::harness.config.json is not valid JSON — using built-in defaults"
    return 0
  fi

  echo "✔ harness.config.json validated"
}

# Read a scalar value from harness.config.json via a jq-style dotted path.
# Falls back to $default when the key is absent or the file is unreadable.
# Example: read_config '.commands.lint' 'ruff check .'
read_config() {
  local jq_filter="$1"
  local default="${2:-}"

  if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "$default"
    return
  fi

  local value=""
  if command -v jq &>/dev/null; then
    value="$(jq -r "${jq_filter} // empty" "$CONFIG_FILE" 2>/dev/null || true)"
  elif command -v python3 &>/dev/null; then
    # Minimal dotted-key resolver for simple paths like .riskTiers.tier3.name
    local py_key
    py_key="${jq_filter#.}"  # strip leading dot
    value="$(python3 - <<PYEOF 2>/dev/null || true
import json
try:
    with open('${CONFIG_FILE}') as f:
        data = json.load(f)
    keys = '${py_key}'.split('.')
    val = data
    for k in keys:
        val = val[k]
    print(val if not isinstance(val, (dict, list)) else '')
except Exception:
    pass
PYEOF
)"
  fi

  echo "${value:-$default}"
}

# ============================================================================
# Step 1: SHA Discipline Check
# Ensures the checked-out commit matches the expected PR head SHA.
# Prevents TOCTOU races where code changes between review and merge.
# ============================================================================
verify_sha() {
  local actual_sha
  actual_sha="$(git rev-parse HEAD)"

  # When running outside CI (local testing), skip SHA enforcement
  if [[ -z "${EXPECTED_SHA:-}" ]]; then
    echo "::notice::EXPECTED_SHA not set — skipping SHA discipline check (local mode)"
    VERIFIED_SHA="$actual_sha"
    return 0
  fi

  # Compare SHAs case-insensitively (hex strings)
  if [[ "${actual_sha,,}" != "${EXPECTED_SHA,,}" ]]; then
    echo "::error::SHA discipline violation: checked-out HEAD (${actual_sha}) ≠ expected PR SHA (${EXPECTED_SHA})"
    echo "::error::The branch changed after this workflow was triggered. Re-run the workflow on the latest commit."
    return 1
  fi

  VERIFIED_SHA="$actual_sha"
  echo "✔ SHA verified: ${VERIFIED_SHA:0:12}"
}

# ============================================================================
# Step 2: Changed File Classification
# Gets the PR diff and classifies each file into risk tiers.
#
# Tier 3 — critical paths (executor, replay, storage contract, build config)
# Tier 2 — source code, tests, CI configs, tool config
# Tier 1 — documentation, non-code metadata
#
# The PR's overall tier is the maximum tier of any changed file.
# ============================================================================

# Classify a single file path into a tier (1, 2, or 3).
# In bash case, * matches any characters including /, so *.py matches any
# .py file at any depth. Tier 3 is checked first (exact paths + extensions).
classify_file() {
  local file="$1"

  # Tier 3: Critical paths — any change here requires human review + full suite.
  # These map exactly to the CLAUDE.md "Critical Paths" and harness.config.json tier3.
  case "$file" in
    pyproject.toml)                echo 3; return ;;
    poetry.lock)                   echo 3; return ;;
    pyworkflow/engine/executor.py) echo 3; return ;;
    pyworkflow/engine/replay.py)   echo 3; return ;;
    pyworkflow/celery/tasks.py)    echo 3; return ;;
    pyworkflow/storage/base.py)    echo 3; return ;;
    harness.config.json)           echo 3; return ;;
  esac

  # Tier 1: Documentation and non-code metadata — no logic impact.
  # Checked before tier-2 so docs-only PRs stay lightweight.
  case "$file" in
    *.md|*.mdx|*.txt) echo 1; return ;;
    LICENSE*)          echo 1; return ;;
    MANIFEST.in)       echo 1; return ;;
    .gitignore)        echo 1; return ;;
    .dockerignore)     echo 1; return ;;
    .editorconfig)     echo 1; return ;;
    docs/*)            echo 1; return ;;
    .vscode/*)         echo 1; return ;;
  esac

  # Tier 2: Source code, tests, CI configs, tool configuration.
  # *.py matches all Python files (bash case * spans path separators).
  case "$file" in
    *.py)                    echo 2; return ;;
    .github/workflows/*.yml) echo 2; return ;;
    .github/workflows/*.yaml)echo 2; return ;;
    .pre-commit-config.yaml) echo 2; return ;;
    docker-compose.yaml)     echo 2; return ;;
    scripts/*)               echo 2; return ;;
    *.cfg|*.ini)             echo 2; return ;;
  esac

  # Default: unknown files get Tier 2 scrutiny
  echo 2
}

classify_changed_files() {
  local base_ref="${BASE_REF:-main}"

  # Ensure we have the base branch ref for computing the merge base
  if ! git rev-parse --verify "origin/${base_ref}" &>/dev/null; then
    git fetch origin "${base_ref}" --depth=1 2>/dev/null || true
  fi

  local merge_base
  merge_base="$(git merge-base "origin/${base_ref}" HEAD 2>/dev/null || echo "")"

  if [[ -z "$merge_base" ]]; then
    echo "::warning::Could not compute merge base against origin/${base_ref}. Defaulting to Tier 3 (safest)."
    MAX_TIER=3
    return
  fi

  local changed_files
  changed_files="$(git diff --name-only "${merge_base}...HEAD" 2>/dev/null || echo "")"

  if [[ -z "$changed_files" ]]; then
    echo "::notice::No changed files detected. Defaulting to Tier 1."
    MAX_TIER=1
    return
  fi

  while IFS= read -r file; do
    [[ -z "$file" ]] && continue
    local tier
    tier="$(classify_file "$file")"

    case "$tier" in
      1) TIER1_FILES+=("$file") ;;
      2) TIER2_FILES+=("$file") ;;
      3) TIER3_FILES+=("$file") ;;
    esac

    if (( tier > MAX_TIER )); then
      MAX_TIER=$tier
    fi
  done <<< "$changed_files"

  echo "✔ Classified files: ${#TIER1_FILES[@]} tier-1, ${#TIER2_FILES[@]} tier-2, ${#TIER3_FILES[@]} tier-3 → overall Tier ${MAX_TIER}"
}

# ============================================================================
# Step 3: Required Checks Computation
# Maps the determined tier to the CI checks that must pass.
# Higher tiers are strict supersets of lower tiers.
# ============================================================================
compute_required_checks() {
  case "$MAX_TIER" in
    1)
      REQUIRED_CHECKS=("lint" "harness-smoke")
      ;;
    2)
      REQUIRED_CHECKS=("lint" "type-check" "test" "build" "structural-tests" "review-agent" "harness-smoke")
      ;;
    3)
      REQUIRED_CHECKS=("lint" "type-check" "test" "build" "structural-tests" "review-agent" "harness-smoke" "manual-approval" "expanded-coverage")
      ;;
    *)
      echo "::warning::Unexpected tier ${MAX_TIER}. Applying Tier 3 checks as safeguard."
      MAX_TIER=3
      REQUIRED_CHECKS=("lint" "type-check" "test" "build" "structural-tests" "review-agent" "harness-smoke" "manual-approval" "expanded-coverage")
      ;;
  esac

  echo "✔ Required checks (${#REQUIRED_CHECKS[@]}): ${REQUIRED_CHECKS[*]}"
}

# ============================================================================
# Step 4: Docs Drift Assertion
# Detects when source code changes lack corresponding documentation updates.
#   relaxed  → skip entirely
#   standard → emit warning
#   strict   → fail the gate
# ============================================================================
check_docs_drift() {
  if [[ "$STRICTNESS" == "relaxed" ]]; then
    echo "✔ Docs drift check skipped (strictness=relaxed)"
    return 0
  fi

  # Only relevant when source files (tier 2+) were changed
  if (( ${#TIER2_FILES[@]} == 0 && ${#TIER3_FILES[@]} == 0 )); then
    echo "✔ No source files changed — docs drift N/A"
    return 0
  fi

  # Check if any documentation files were also modified
  local has_docs=false
  for file in "${TIER1_FILES[@]+"${TIER1_FILES[@]}"}"; do
    case "$file" in
      *.md|docs/*) has_docs=true; break ;;
    esac
  done

  if ! $has_docs; then
    DOCS_DRIFT_DETECTED=true
    DOCS_DRIFT_WARNING="Source files changed without documentation updates. Consider updating README.md or docs/."

    if [[ "$STRICTNESS" == "strict" ]]; then
      echo "::error::Docs drift: ${DOCS_DRIFT_WARNING}"
      return 1
    else
      echo "::warning::Docs drift: ${DOCS_DRIFT_WARNING}"
    fi
  else
    echo "✔ Documentation updated alongside source changes"
  fi
}

# ============================================================================
# Step 5: Review Agent Completion Check
# For Tier 2+, verifies the review agent has analyzed this SHA.
# On first run the agent hasn't executed yet, so status is "pending".
# Subsequent runs (triggered by remediation loop) query the GitHub API.
# ============================================================================
check_review_agent() {
  if (( MAX_TIER < 2 )); then
    REVIEW_AGENT_RESULT="skipped"
    echo "✔ Review agent: skipped (Tier 1)"
    return 0
  fi

  # Accept explicit status injected by the remediation loop
  if [[ -n "${REVIEW_AGENT_STATUS:-}" ]]; then
    REVIEW_AGENT_RESULT="$REVIEW_AGENT_STATUS"
    echo "✔ Review agent: ${REVIEW_AGENT_RESULT} (from env)"
    return 0
  fi

  # Query GitHub API for review-agent check run on this commit
  if command -v gh &>/dev/null && [[ -n "${GITHUB_REPOSITORY:-}" ]]; then
    local conclusion
    conclusion="$(gh api "repos/${GITHUB_REPOSITORY}/commits/${VERIFIED_SHA}/check-runs" \
      --jq '.check_runs[] | select(.name == "review-agent") | .conclusion' 2>/dev/null \
      | head -1 || echo "")"

    case "$conclusion" in
      success)  REVIEW_AGENT_RESULT="approved" ;;
      failure)  REVIEW_AGENT_RESULT="rejected" ;;
      *)        REVIEW_AGENT_RESULT="pending" ;;
    esac
  else
    REVIEW_AGENT_RESULT="pending"
  fi

  echo "✔ Review agent: ${REVIEW_AGENT_RESULT}"
}

# ============================================================================
# Step 6: Output Results
# Emits structured JSON and sets GitHub Actions step outputs.
# ============================================================================

# Build a JSON array string from arguments. Returns "[]" for zero arguments.
to_json_array() {
  if (( $# == 0 )); then
    echo "[]"
    return
  fi
  local json="[" sep=""
  for item in "$@"; do
    json+="${sep}\"${item}\""
    sep=","
  done
  echo "${json}]"
}

output_results() {
  local tier_name
  case "$MAX_TIER" in
    1) tier_name="low" ;;
    2) tier_name="medium" ;;
    3) tier_name="high" ;;
    *) tier_name="unknown" ;;
  esac

  local checks_json tier1_json tier2_json tier3_json

  checks_json="$(to_json_array "${REQUIRED_CHECKS[@]}")"

  tier1_json="[]"
  tier2_json="[]"
  tier3_json="[]"
  (( ${#TIER1_FILES[@]} > 0 )) && tier1_json="$(to_json_array "${TIER1_FILES[@]}")"
  (( ${#TIER2_FILES[@]} > 0 )) && tier2_json="$(to_json_array "${TIER2_FILES[@]}")"
  (( ${#TIER3_FILES[@]} > 0 )) && tier3_json="$(to_json_array "${TIER3_FILES[@]}")"

  # Escape warning message for JSON string safety
  local escaped_warning="${DOCS_DRIFT_WARNING//\\/\\\\}"
  escaped_warning="${escaped_warning//\"/\\\"}"

  local result
  result=$(cat <<EOF
{
  "sha": "${VERIFIED_SHA}",
  "tier": ${MAX_TIER},
  "tierName": "${tier_name}",
  "requiredChecks": ${checks_json},
  "changedFiles": {
    "tier1": ${tier1_json},
    "tier2": ${tier2_json},
    "tier3": ${tier3_json}
  },
  "docsDrift": {
    "detected": ${DOCS_DRIFT_DETECTED},
    "warning": "${escaped_warning}"
  },
  "reviewAgentStatus": "${REVIEW_AGENT_RESULT}"
}
EOF
)

  echo ""
  echo "═══════════════════════════════════════════════════"
  echo " Risk Policy Gate Result"
  echo "═══════════════════════════════════════════════════"
  echo "$result"
  echo "═══════════════════════════════════════════════════"

  # Set GitHub Actions step outputs for downstream job conditionals
  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    {
      echo "sha=${VERIFIED_SHA}"
      echo "tier=${MAX_TIER}"
      echo "tier-name=${tier_name}"
      echo "required-checks=${checks_json}"
      echo "docs-drift=${DOCS_DRIFT_DETECTED}"
      echo "review-agent-status=${REVIEW_AGENT_RESULT}"
      echo "result<<GATE_EOF"
      echo "$result"
      echo "GATE_EOF"
    } >> "$GITHUB_OUTPUT"
    echo ""
    echo "✔ GitHub Actions outputs written"
  fi
}

# ============================================================================
# Main
# ============================================================================
main() {
  echo "╔═════════════════════════════════════════════════╗"
  echo "║       Risk Policy Gate — Preflight Check        ║"
  echo "╚═════════════════════════════════════════════════╝"
  echo ""

  validate_config
  verify_sha
  classify_changed_files
  compute_required_checks
  check_docs_drift
  check_review_agent
  output_results

  echo ""
  echo "✔ Gate completed — Tier ${MAX_TIER} ($(
    case $MAX_TIER in 1) echo low;; 2) echo medium;; 3) echo high;; *) echo unknown;; esac
  )) — ${#REQUIRED_CHECKS[@]} checks required"
}

main "$@"
