#!/usr/bin/env bash
# scripts/deploy.sh
#
# Push to GitHub and conditionally sync CoCo files to the Snowflake stage.
# Must be run from the main branch with a clean working tree.
#
# Usage:
#   ./scripts/deploy.sh          # smart deploy (changed files only)
#   ./scripts/deploy.sh --all    # force full Snowflake upload

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Guard: must be on main ────────────────────────────────────────────────────
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" != "main" ]; then
  echo "Error: deploy.sh must be run from the main branch (currently on '$CURRENT_BRANCH')."
  echo ""
  echo "To sync CoCo files from a feature branch during development:"
  echo "  ./scripts/stage-sync.sh"
  exit 1
fi

# ── Guard: clean working tree ─────────────────────────────────────────────────
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Error: you have uncommitted changes. Commit or stash before deploying."
  exit 1
fi

# ── Pre-deploy: full validation suite ────────────────────────────────────────
echo "Running full validation suite before deploy..."

DEPLOY_FAILED=0

deploy_check() {
  local label="$1"
  local cmd="$2"
  printf "  %-32s " "$label"
  if python3 $cmd > /dev/null 2>&1; then
    echo "PASS"
  else
    echo "FAIL"
    python3 $cmd 2>&1 | sed 's/^/    /'
    DEPLOY_FAILED=$((DEPLOY_FAILED + 1))
  fi
}

deploy_check "reference paths"      "tools/validate/check_references.py --root $SCRIPT_DIR/.."
deploy_check "anti-patterns"        "tools/validate/check_patterns.py --root $SCRIPT_DIR/.."
deploy_check "SV YAML structure"    "tools/validate/check_sv_yaml.py --root $SCRIPT_DIR/.."
deploy_check "TML structure"        "tools/validate/check_tml.py --root $SCRIPT_DIR/.."
deploy_check "version sync"         "tools/validate/check_version_sync.py --root $SCRIPT_DIR/.."

# Open items: warn but don't block deploy (items may be in-flight)
printf "  %-32s " "open items"
if python3 tools/validate/check_open_items.py --root "$SCRIPT_DIR/.." --warn > /dev/null 2>&1; then
  echo "PASS"
else
  echo "WARN"
  python3 tools/validate/check_open_items.py --root "$SCRIPT_DIR/.." --warn 2>&1 | sed 's/^/    /'
fi

if [ "$DEPLOY_FAILED" -gt 0 ]; then
  echo ""
  echo "Error: $DEPLOY_FAILED validation check(s) failed. Fix before deploying."
  exit 1
fi

echo "Validation passed."
echo ""

# ── Push to GitHub ────────────────────────────────────────────────────────────
echo "Pushing main to GitHub..."
git push origin main
echo "Done."
echo ""

# ── Sync to Snowflake stage (only if CoCo/shared files changed) ───────────────
echo "Checking for CoCo/shared changes to sync to Snowflake..."
"$SCRIPT_DIR/stage-sync.sh" "$@"
