#!/usr/bin/env bash
# scripts/pre-push.sh
#
# Pre-push hook: runs smoke tests for any skill modified in the commits being pushed.
# Blocks the push if a smoke test fails; skips skills that need local config
# (see tools/smoke-tests/smoke-config.local.json.example) but warns loudly.
#
# Install once:
#   ln -s ../../scripts/pre-push.sh .git/hooks/pre-push
#
# To skip in an emergency: git push --no-verify (use sparingly)

set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

SKILLS=""

while read -r local_ref local_sha remote_ref remote_sha; do
    # Branch deletion — nothing to test
    [ "$local_sha" = "0000000000000000000000000000000000000000" ] && continue

    # New branch — find the merge-base with origin/main as the diff base
    if [ "$remote_sha" = "0000000000000000000000000000000000000000" ]; then
        remote_sha=$(git merge-base "$local_sha" origin/main 2>/dev/null || true)
        [ -z "$remote_sha" ] && continue
    fi

    # Collect skill directories touched in this push.
    # Match only paths with at least one more component after the skill dir
    # (e.g. agents/cli/ts-variable-timezone/SKILL.md) — not files directly
    # in agents/cli/ like agents/cli/SETUP.md.
    BATCH=$(git diff --name-only "$remote_sha" "$local_sha" 2>/dev/null \
        | grep -E '^agents/(cli|claude)/[^/]+/' \
        | grep -oE '^agents/(cli|claude)/[^/]+' \
        | sed 's|^agents/cli/||;s|^agents/claude/||' \
        | sort -u || true)

    SKILLS=$(printf "%s\n%s" "$SKILLS" "$BATCH" | sort -u | grep -v '^$' || true)
done

if [ -z "$SKILLS" ]; then
    exit 0
fi

echo "pre-push: smoke-testing modified skills..."
echo ""

# Pass skill list to the Python runner
if echo "$SKILLS" | python3 tools/validate/run_smoke_tests.py; then
    echo ""
    echo "All smoke tests passed."
    exit 0
else
    echo ""
    echo "Smoke test(s) failed. Fix the issues above before pushing."
    echo "To skip (emergency only): git push --no-verify"
    exit 1
fi
