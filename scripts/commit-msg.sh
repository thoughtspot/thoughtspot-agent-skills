#!/usr/bin/env bash
# scripts/commit-msg.sh
#
# Commit-message hook: fails the commit if the message links into a tenant's internal
# systems (or names an entry on the opt-in private customer denylist). A commit message
# is published with the branch and never appears in the tree, so the pre-commit scan
# cannot see it. CI's `--range` scan is the backstop for --no-verify.
#
# Install once with: bash scripts/install-hooks.sh  (the dispatcher it writes runs THIS
# worktree's copy of this file).
#
# To skip in an emergency: git commit --no-verify (use sparingly)

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
exec python3 "$REPO_ROOT/tools/validate/check_customer_references.py" \
  --root "$REPO_ROOT" --message-file "$1"
