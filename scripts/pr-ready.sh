#!/usr/bin/env bash
# scripts/pr-ready.sh
#
# Run everything CI's `suite` job checks on a pull request — the check list,
# the PR-only gates, the smoke suites and the pytest invocations — locally,
# against upstream main (found by URL and fetched every run), and write an
# evidence block for the PR description. Exits 1 on any hard FAIL or when the
# branch is behind upstream main.
#
#   bash scripts/pr-ready.sh [--no-review] [--post PR_NUMBER]
#
# The logic is in tools/validate/pr_ready.py (see its docstring); this wrapper
# only picks the interpreter, the same way pre-commit does.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# shellcheck source=lib/python-bin.sh
source "$REPO_ROOT/scripts/lib/python-bin.sh"

exec "$PYTHON_BIN" tools/validate/pr_ready.py "$@"
