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

exec "$PYTHON_BIN" tools/validate/pr_ready.py "$@"
