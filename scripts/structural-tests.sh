#!/usr/bin/env bash
# ============================================================================
# Structural Tests — Architectural Boundary Validation
#
# Reads architectural boundaries from harness.config.json and validates that
# import dependencies between pyworkflow/ modules respect the declared rules.
#
# Exit 0: all boundaries respected.
# Exit 1: one or more violations found.
# ============================================================================
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
CONFIG_FILE="${REPO_ROOT}/harness.config.json"

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "::error::harness.config.json not found at ${CONFIG_FILE}"
  exit 1
fi

echo "╔═════════════════════════════════════════════════╗"
echo "║     Architectural Boundary Validation            ║"
echo "╚═════════════════════════════════════════════════╝"
echo ""

export REPO_ROOT CONFIG_FILE

python3 <<'PYEOF'
import json
import os
import re
import sys
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
config_file = Path(os.environ["CONFIG_FILE"])
pkg_dir = repo_root / "pyworkflow"

with open(config_file) as f:
    config = json.load(f)

boundaries = config.get("architecturalBoundaries", {})
if not boundaries:
    print("::error::No architecturalBoundaries defined in harness.config.json")
    sys.exit(1)

print(f"Boundaries loaded from harness.config.json ({len(boundaries)} modules)")
print()

violations = 0

for module, defn in boundaries.items():
    module_dir = pkg_dir / module
    if not module_dir.is_dir():
        continue

    allowed = defn.get("allowedImports", [])
    module_violations = 0

    for py_file in sorted(module_dir.rglob("*.py")):
        try:
            lines = py_file.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue

        for lineno, line in enumerate(lines, 1):
            # Match: from pyworkflow.<target>[.something] import ...
            # or:    import pyworkflow.<target>[.something]
            m = re.match(r"\s*(?:from|import)\s+pyworkflow\.(\w+)", line)
            if not m:
                continue

            target = m.group(1)
            if target == module:
                continue
            if target not in boundaries:
                continue  # not a tracked boundary module
            if target in allowed:
                continue

            rel = py_file.relative_to(repo_root)
            allowed_str = ", ".join(allowed) if allowed else "none"
            print(f"::error file={rel},line={lineno}::{module}/ cannot import from {target}/ (allowed: {allowed_str})")
            violations += 1
            module_violations += 1

    if module_violations == 0:
        allowed_str = ", ".join(allowed) if allowed else "none"
        print(f"  ✔ {module}/ → allowed: [{allowed_str}]")
    else:
        print(f"  ✘ {module}/ → {module_violations} violation(s)")

print()
if violations > 0:
    print(f"✘ Found {violations} architectural boundary violation(s)")
    print()
    print("To fix: either update the import to use an allowed module, or update")
    print("architecturalBoundaries in harness.config.json if the dependency is intentional.")
    sys.exit(1)
else:
    print(f"✔ All architectural boundaries respected ({len(boundaries)} modules checked)")
PYEOF
