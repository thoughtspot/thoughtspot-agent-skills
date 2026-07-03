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

# ── Python interpreter resolution ───────────────────────────────────────────
# ts-cli's own floor is Python >=3.10 (tools/ts-cli/pyproject.toml), but some
# machines only expose an EOL system `python3` (e.g. macOS ships 3.9.6). Prefer
# the newest 3.10+ interpreter on PATH that actually has this repo's tooling
# installed — pytest below is a hard requirement with no graceful fallback, so
# picking a bare interpreter with nothing installed would turn every check into
# a false FAIL. Fall back to plain `python3` with a warning rather than
# hard-failing the commit over interpreter selection itself.
PYTHON_BIN=""
for _candidate in python3.12 python3.11 python3.10; do
  if command -v "$_candidate" >/dev/null 2>&1 && "$_candidate" -c "import pytest" >/dev/null 2>&1; then
    PYTHON_BIN="$_candidate"
    break
  fi
done
unset _candidate

if [ -z "$PYTHON_BIN" ]; then
  PYTHON_BIN="python3"
  echo "Warning: no python3.10+ interpreter with pytest installed found on PATH"
  echo "  (checked python3.12, python3.11, python3.10). Falling back to '$PYTHON_BIN'"
  echo "  ($($PYTHON_BIN --version 2>&1)) — ts-cli requires Python >=3.10."
  echo ""
fi

run_check() {
  local label="$1"
  local cmd="$2"
  printf "  %-30s " "$label"
  if output=$("$PYTHON_BIN" $cmd 2>&1); then
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

# Complexity ratchet on staged Python (soft-skips if radon isn't installed locally;
# enforced fully in CI). Blocks new/worsening god-functions; legacy is baselined.
if echo "$STAGED" | grep -q '\.py$'; then
  run_check "module health"      "tools/validate/check_module_health.py --root $REPO_ROOT --staged"
fi

# Line-count gate on staged ts_cli modules (BL-070) — warn >500, fail >1000.
# Complements the complexity ratchet: long-but-simple files slip past radon.
if echo "$STAGED" | grep -q '^tools/ts-cli/ts_cli/.*\.py$'; then
  run_check "file size"          "tools/validate/check_file_size.py --root $REPO_ROOT --staged"
fi

# Only run YAML check if .md files are staged — checks staged files only, not full repo
if echo "$STAGED" | grep -q '\.md$'; then
  run_check "YAML blocks"        "tools/validate/check_yaml.py --root $REPO_ROOT --staged"
fi

# Snowflake SV YAML structural validator — runs when schema or worked-example .md files are staged
if echo "$STAGED" | grep -qE '(snowflake-schema|ts-to-snowflake|\.yaml$|\.yml$)'; then
  run_check "SV YAML structure"  "tools/validate/check_sv_yaml.py --root $REPO_ROOT --staged"
fi

# ThoughtSpot TML structural validator — fire on ANY staged .md file.
# check_tml self-filters: it only validates real Table/Model TML blocks and skips
# templates, partial snippets, worksheets, and non-TML YAML. Narrow filename triggers
# previously meant TML edits in other docs went unchecked.
if echo "$STAGED" | grep -qE '\.md$'; then
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
  "$PYTHON_BIN" tools/validate/suggest_skill_version.py --root $REPO_ROOT
  run_check "skill versions"     "tools/validate/check_skill_versions.py --root $REPO_ROOT"
fi

# Smoke tests — every Claude skill (not on the allowlist) must have a smoke test
# Runs when a SKILL.md or smoke test is touched
if echo "$STAGED" | grep -qE '(agents/(cli|claude)/.*/SKILL\.md|tools/smoke-tests/)'; then
  run_check "smoke tests"        "tools/validate/check_smoke_tests.py --root $REPO_ROOT --staged"
fi

# Skill naming — every skill across all runtimes (Claude / CoCo) must
# match a documented family pattern (see .claude/rules/skill-naming.md).
# Runs when a SKILL.md, the rule itself, or the validator is added/renamed.
if echo "$STAGED" | grep -qE '(agents/(cli|claude|coco-snowsight)/.*/SKILL\.md|\.claude/rules/skill-naming\.md|tools/validate/check_skill_naming\.py)'; then
  run_check "skill naming"       "tools/validate/check_skill_naming.py --root $REPO_ROOT"
fi

# Runtime coverage — CoCo's divergences are documented in EXPECTED_DIVERGENCES
# (see .claude/rules/runtime-coverage.md).
# Runs whenever a skill file is added or renamed in any runtime, or when the
# rule/validator itself changes.
if echo "$STAGED" | grep -qE '(agents/(cli|claude|coco-snowsight)/.*/SKILL\.md|\.claude/rules/runtime-coverage\.md|tools/validate/check_runtime_coverage\.py)'; then
  run_check "runtime coverage"   "tools/validate/check_runtime_coverage.py --root $REPO_ROOT"
fi

# Parity matrix — generated from the filesystem, must match committed PARITY.md
# Runs when any skill file is added/renamed or PARITY.md itself changes
if echo "$STAGED" | grep -qE '(agents/(cli|claude|coco-snowsight)/.*/SKILL\.md|agents/PARITY\.md)'; then
  run_check "parity matrix"      "tools/validate/generate_parity.py --check"
fi

# Mirror sync — check synced-from markers against CLI source versions
# Runs when any mirror file or SYNC-DEBT.md changes
if echo "$STAGED" | grep -qE '(agents/coco-snowsight/|agents/SYNC-DEBT\.md)'; then
  run_check "mirror sync"         "tools/validate/check_mirror_sync.py"
fi

# Coverage matrix — every ts-convert-* skill must have references/coverage-matrix.md
# Runs when a converter skill is touched or the validator itself changes
if echo "$STAGED" | grep -qE '(agents/cli/ts-convert-|tools/validate/check_coverage_matrix\.py)'; then
  run_check "coverage matrix"     "tools/validate/check_coverage_matrix.py --root $REPO_ROOT"
fi

# Formula catalog cross-check — mapping files must only reference valid TS functions
# from thoughtspot-formula-patterns.md. Runs when any mapping or the catalog is touched.
if echo "$STAGED" | grep -qE 'agents/shared/(mappings/|schemas/thoughtspot-formula-patterns\.md)'; then
  run_check "formula catalog"     "tools/validate/check_formula_catalog.py --root $REPO_ROOT"
fi

# No v1 endpoints — the repo is v1-free (.claude/rules/ts-cli.md). Guard against a
# new /tspublic/v1/ call slipping into the CLI or Databricks client. Runs when any
# Python source under tools/ or agents/ is staged, or the validator itself changes.
if echo "$STAGED" | grep -qE '(^(tools|agents|scripts)/.*\.py$|tools/validate/check_no_v1_endpoints\.py)'; then
  run_check "no v1 endpoints"     "tools/validate/check_no_v1_endpoints.py --root $REPO_ROOT"
fi

# No inline TML-invariant gate — CLI convert skills must gate imports with `ts tml lint`,
# not a hand-rolled grep gate (.claude/rules/ts-cli.md; audit angle 11). Runs when a
# convert skill or the validator changes.
if echo "$STAGED" | grep -qE '(^agents/cli/ts-convert-.*/SKILL\.md|tools/validate/check_no_inline_tml_gate\.py)'; then
  run_check "no inline tml gate" "tools/validate/check_no_inline_tml_gate.py --root $REPO_ROOT"
fi

# No inline Python TML assembly — CLI convert skills must use `ts tableau build-model`,
# not hand-rolled Python heredocs for formula import. Runs when a convert skill or the
# validator changes.
if echo "$STAGED" | grep -qE '(^agents/cli/ts-convert-.*/SKILL\.md|tools/validate/check_skill_cli_usage\.py)'; then
  run_check "no inline tml assembly" "tools/validate/check_skill_cli_usage.py --root $REPO_ROOT"
fi

# Currency anchors — SOFT nudge here (prints missing + stale anchors, never blocks the
# commit) when a shared mapping OR schema file is edited. Presence is hard-gated in CI
# (--check) so an anchorless new file fails the PR; staleness stays soft everywhere.
# (.claude/rules/repo-audit.md, angle 13.)
if echo "$STAGED" | grep -qE '^agents/shared/(mappings|schemas)/.*\.md$|^agents/cli/ts-object-model-spotql-query/references/limitations\.md$'; then
  "$PYTHON_BIN" tools/validate/check_mapping_currency.py --root "$REPO_ROOT" --staged || true
fi

# ts-dependency-manager: soft nudge if SKILL.md or open-items.md is staged without
# also staging references/dependency-types.md. Never blocks. (TTY only)
if echo "$STAGED" | grep -qE '^agents/cli/ts-dependency-manager/(SKILL\.md|references/open-items\.md)$'; then
  "$PYTHON_BIN" tools/validate/suggest_dependency_types.py --root $REPO_ROOT
fi

# Repo changelog — for significant staged changes (new skills, ts-cli bumps, new shared
# files, MAJOR/MINOR skill version bumps):
#   1. interactively suggest + auto-insert an entry (TTY only)
#   2. GATE — fail the commit if no same-day CHANGELOG.md entry exists. Runs in non-TTY too
#      (CI / agent-driven commits), so the entry can't be silently skipped.
"$PYTHON_BIN" tools/validate/suggest_repo_changelog.py --root $REPO_ROOT
run_check "repo changelog"     "tools/validate/suggest_repo_changelog.py --root $REPO_ROOT --check"

# Audit freshness — SOFT nudge (never blocks, silent unless due) when an external
# sweep or a full audit is due by time or by accumulated work (.claude/rules/repo-audit.md).
"$PYTHON_BIN" tools/validate/check_audit_freshness.py --root "$REPO_ROOT" || true

# Only run unit tests if Python source files are staged.
#
# Three separate pytest invocations, not one combined command: ts-object-model-erd/tests
# and agents/databricks/tests are each their own bare "tests" package (tests/__init__.py
# with no distinguishing parent package) — same as tools/ts-cli/tests. pytest's conftest
# module registration collides (ImportPathMismatchError / "Plugin already registered
# under a different name") if two same-named "tests" packages are collected in a single
# invocation. tools/validate/tests has no __init__.py, so it can safely share an
# invocation with tools/ts-cli/tests.
#
# Exit code is checked directly — NOT grepped from the summary line. A failing run's
# "3 failed, 898 passed" text still contains the word "passed", which previously made
# this gate false-PASS on real failures.
#
# PYTHONPATH is pinned to this checkout's own tools/ts-cli so tests import THIS repo's
# ts_cli, not a stale editable-install copy pointing at a different checkout — matters
# when running from a git worktree, where `pip install -e` typically points back at the
# original clone.
export PYTHONPATH="$REPO_ROOT/tools/ts-cli${PYTHONPATH:+:$PYTHONPATH}"

run_pytest() {
  local label="$1"
  shift
  printf "  %-30s " "$label"
  if output=$("$PYTHON_BIN" -m pytest "$@" -q --tb=short 2>&1); then
    echo "PASS"
  else
    echo "FAIL"
    echo "$output" | sed 's/^/    /'
    FAILED=$((FAILED + 1))
  fi
}

if echo "$STAGED" | grep -q '\.py$'; then
  run_pytest "unit tests (ts-cli)"      tools/ts-cli/tests/ tools/validate/tests/
  run_pytest "unit tests (erd)"         agents/cli/ts-object-model-erd/tests/
  run_pytest "unit tests (databricks)"  agents/databricks/tests/
fi

echo ""

if [ "$FAILED" -gt 0 ]; then
  echo "$FAILED check(s) failed. Fix the issues above, then re-stage and commit."
  echo "To skip (emergency only): git commit --no-verify"
  exit 1
fi

# ── Main branch skill audit ───────────────────────────────────────────────────
# On any commit to main that touches a skill in ANY runtime, show the full skill
# inventory and require explicit confirmation that every skill belongs in this repo.
# This prevents accidentally committing skills that live in other projects.
# (The agents/claude -> agents/cli rename meant this only watched agents/claude/ —
#  CLI/CoCo skill additions slipped through unaudited. Now spans all runtimes.)
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")

if [ "$CURRENT_BRANCH" = "main" ] && echo "$STAGED" | grep -qE '^agents/(cli|claude|coco-snowsight)/'; then
  # What skill-level changes are in this commit? Names keep the runtime prefix
  # (e.g. cli/ts-dependency-manager) so the same skill name across runtimes is unambiguous.
  ADDING=$(git diff --cached --name-only --diff-filter=A \
    | grep -E '^agents/(cli|claude|coco-snowsight)/[^/]+/SKILL\.md$' \
    | sed 's|agents/||;s|/SKILL\.md||' | sort)
  REMOVING=$(git diff --cached --name-only --diff-filter=D \
    | grep -E '^agents/(cli|claude|coco-snowsight)/[^/]+/SKILL\.md$' \
    | sed 's|agents/||;s|/SKILL\.md||' | sort)
  UPDATING=$(git diff --cached --name-only \
    | grep -E '^agents/(cli|claude|coco-snowsight)/[^/]+/' \
    | sed -E 's|^agents/([^/]+)/([^/]+)/.*|\1/\2|' | sort -u \
    | grep -vxF "$ADDING" | grep -vxF "$REMOVING")

  # Skills on disk after staging (find reflects the post-staged filesystem state)
  ALL_SKILLS=$(find agents/cli agents/claude agents/coco-snowsight \
      -maxdepth 2 -name 'SKILL.md' 2>/dev/null \
    | sed 's|^agents/||;s|/SKILL\.md$||' | sort)

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
