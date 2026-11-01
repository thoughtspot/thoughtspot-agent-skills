#!/usr/bin/env bash
# scripts/pr-ready.sh
#
# Run everything CI's `suite` job checks on a pull request — the check list,
# the PR-only gates, the smoke suites and the pytest invocations — locally,
# against upstream main (found by URL and fetched every run), and write an
# evidence block for the PR description. Exits 1 on any hard FAIL or when the
# branch is behind upstream main; 2 when the run could not start (no usable
# interpreter — a CHECKS_PYTHON that is missing, older than 3.10 or without pytest —
# no upstream remote, a failed fetch, an unreadable workflow), with no verdict.
#
#   bash scripts/pr-ready.sh [--no-review] [--post PR_NUMBER]
#
# The logic is in tools/validate/pr_ready.py (see its docstring); this wrapper
# replaces the evidence block and picks the interpreter, the same way pre-commit does.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# Replace any earlier block BEFORE choosing the interpreter: python-bin.sh exits 2 on
# a bad CHECKS_PYTHON, and a run that stops there must not leave an earlier READY
# block looking current. The text is evidence.UNFINISHED exactly (a test pins it), the
# placeholder pr_ready.py itself writes first.
EVIDENCE_DIR="$(git rev-parse --absolute-git-dir)/pr-ready"
if ! { mkdir -p "$EVIDENCE_DIR" &&
       printf '%s\n' '**pr-ready** did not finish: NOT READY. This file is replaced when a run completes; until then it describes nothing.' >| "$EVIDENCE_DIR/evidence.md"; }; then
  echo "pr-ready: cannot replace the evidence file in $EVIDENCE_DIR" >&2
  exit 2
fi

# shellcheck source=lib/python-bin.sh
source "$REPO_ROOT/scripts/lib/python-bin.sh"

# Opt-in (the severity rubric, 2026-11): with TS_AUDIT_SNAPSHOT naming an audit snapshot
# directory (kept OUTSIDE the repo), report which rules fire at MEDIUM or above on more
# than half of their objects without a current fire_rate_reviewed. Warnings only, never a
# failure, and nothing from the snapshot is written anywhere.
if [ -n "${TS_AUDIT_SNAPSHOT:-}" ]; then
  for assessment in general spotter; do
    PYTHONPATH="$REPO_ROOT/tools/ts-cli" "$PYTHON_BIN" -c "from ts_cli.cli import app; app()" \
      audit fire-rates --snapshot-in "$TS_AUDIT_SNAPSHOT" --assessment "$assessment" \
      >/dev/null || echo "pr-ready: fire-rates could not run on $TS_AUDIT_SNAPSHOT" >&2
  done
fi

exec "$PYTHON_BIN" tools/validate/pr_ready.py "$@"
