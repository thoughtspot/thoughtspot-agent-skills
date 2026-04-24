#!/usr/bin/env bash
# scripts/pre-commit.sh
#
# Pre-commit validation hook. Runs the full validation suite before any commit.
# Install once with: ln -s ../../scripts/pre-commit.sh .git/hooks/pre-commit
#
# To skip in an emergency: git commit --no-verify (use sparingly)

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# Only run if there are staged changes touching relevant files
STAGED=$(git diff --cached --name-only)

if [ -z "$STAGED" ]; then
  exit 0
fi

echo "Running pre-commit checks..."
echo ""

FAILED=0

run_check() {
  local label="$1"
  local cmd="$2"
  printf "  %-30s " "$label"
  if output=$(python3 $cmd 2>&1); then
    echo "PASS"
  else
    echo "FAIL"
    echo "$output" | sed 's/^/    /'
    FAILED=$((FAILED + 1))
  fi
}

# Always run these — they're fast and catch the most common mistakes
run_check "secrets"              "tools/validate/check_secrets.py --root $REPO_ROOT"
run_check "reference paths"      "tools/validate/check_references.py --root $REPO_ROOT"
run_check "anti-patterns"        "tools/validate/check_patterns.py --root $REPO_ROOT --staged"
run_check "version sync"         "tools/validate/check_version_sync.py --root $REPO_ROOT"

# Only run YAML check if .md files are staged — checks staged files only, not full repo
if echo "$STAGED" | grep -q '\.md$'; then
  run_check "YAML blocks"        "tools/validate/check_yaml.py --root $REPO_ROOT --staged"
fi

# Snowflake SV YAML structural validator — runs when schema or worked-example .md files are staged
if echo "$STAGED" | grep -qE '(snowflake-schema|ts-to-snowflake|\.yaml$|\.yml$)'; then
  run_check "SV YAML structure"  "tools/validate/check_sv_yaml.py --root $REPO_ROOT --staged"
fi

# ThoughtSpot TML structural validator — runs when TML schema or worked-example .md files are staged
if echo "$STAGED" | grep -qE '(thoughtspot-(table|model)-tml|ts-from-snowflake)'; then
  run_check "TML structure"      "tools/validate/check_tml.py --root $REPO_ROOT --staged"
fi

# Open-items tracking — warn only (don't block commits on pre-existing UNTESTED items)
if echo "$STAGED" | grep -q 'open-items\.md'; then
  run_check "open items"         "tools/validate/check_open_items.py --root $REPO_ROOT --warn"
fi

# Cross-file consistency — runs when agents/, README.md, or SETUP.md are touched
# Ensures README skills table, SETUP.md symlink/stage steps stay in sync with repo structure
if echo "$STAGED" | grep -qE '(^agents/|README\.md|SETUP\.md)'; then
  run_check "consistency"        "tools/validate/check_consistency.py --root $REPO_ROOT --staged"
fi

# Skill versioning — runs when any SKILL.md is touched
# Step 1: interactively suggest a changelog entry if one is missing (TTY only)
# Step 2: validate that every staged skill has a changelog entry
if echo "$STAGED" | grep -q 'SKILL\.md'; then
  python3 tools/validate/suggest_skill_version.py --root $REPO_ROOT
  run_check "skill versions"     "tools/validate/check_skill_versions.py --root $REPO_ROOT"
fi

# Repo changelog — suggests a CHANGELOG.md entry for significant staged changes:
# new skills, ts-cli version bumps, new shared reference files (TTY only)
python3 tools/validate/suggest_repo_changelog.py --root $REPO_ROOT

# Only run unit tests if Python source files are staged
if echo "$STAGED" | grep -q '\.py$'; then
  printf "  %-30s " "unit tests"
  if python3 -m pytest tools/ts-cli/tests/ -q --tb=short 2>&1 | tail -1 | grep -q "passed"; then
    echo "PASS"
  else
    echo "FAIL"
    python3 -m pytest tools/ts-cli/tests/ -q --tb=short 2>&1 | sed 's/^/    /'
    FAILED=$((FAILED + 1))
  fi
fi

echo ""

if [ "$FAILED" -gt 0 ]; then
  echo "$FAILED check(s) failed. Fix the issues above, then re-stage and commit."
  echo "To skip (emergency only): git commit --no-verify"
  exit 1
fi

# ── Main branch skill audit ───────────────────────────────────────────────────
# On any commit to main that touches agents/claude/, show the full skill inventory
# and require explicit confirmation that every skill belongs in this repo.
# This prevents accidentally committing skills that live in other projects.
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")

if [ "$CURRENT_BRANCH" = "main" ] && echo "$STAGED" | grep -qE '^agents/claude/'; then
  # What skill-level changes are in this commit?
  ADDING=$(git diff --cached --name-only --diff-filter=A \
    | grep -E '^agents/claude/[^/]+/SKILL\.md$' \
    | sed 's|agents/claude/||;s|/SKILL\.md||' | sort)
  REMOVING=$(git diff --cached --name-only --diff-filter=D \
    | grep -E '^agents/claude/[^/]+/SKILL\.md$' \
    | sed 's|agents/claude/||;s|/SKILL\.md||' | sort)
  UPDATING=$(git diff --cached --name-only \
    | grep -E '^agents/claude/[^/]+/' \
    | sed 's|agents/claude/||;s|/.*||' | sort -u \
    | grep -vxF "$ADDING" | grep -vxF "$REMOVING")

  # Skills on disk after staging (find reflects the post-staged filesystem state)
  ALL_SKILLS=$(find agents/claude -maxdepth 2 -name 'SKILL.md' 2>/dev/null \
    | sed 's|^agents/claude/||;s|/SKILL\.md$||' | sort)

  echo "  ── Main branch skill audit ──────────────────────────────────────"
  echo ""

  if [ -n "$ADDING" ]; then
    while IFS= read -r s; do echo "  + Adding:   $s"; done <<< "$ADDING"
  fi
  if [ -n "$REMOVING" ]; then
    while IFS= read -r s; do echo "  - Removing: $s"; done <<< "$REMOVING"
  fi
  if [ -n "$UPDATING" ]; then
    while IFS= read -r s; do echo "  ~ Updating: $s"; done <<< "$UPDATING"
  fi

  echo ""
  echo "  Skills in this repo after commit:"
  if [ -n "$ALL_SKILLS" ]; then
    while IFS= read -r s; do echo "    $s"; done <<< "$ALL_SKILLS"
  else
    echo "    (none)"
  fi
  echo ""
  printf "  All of the above belong in thoughtspot-agent-skills? [y/N] "

  if [ -e /dev/tty ]; then
    read -r confirm < /dev/tty
  else
    echo ""
    echo "  Non-interactive terminal — cannot prompt. Aborting commit to main."
    echo "  Use --no-verify only if you are certain this is correct."
    exit 1
  fi

  case "$confirm" in
    y|Y) ;;
    *)
      echo ""
      echo "  Commit to main cancelled."
      echo "  Remove any skills that don't belong, then re-stage and commit."
      exit 1
      ;;
  esac
  echo ""
fi

echo "All checks passed."
