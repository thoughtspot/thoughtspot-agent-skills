#!/usr/bin/env bash
# scripts/install-hooks.sh — install (or check) this repo's git hooks.
#
#   bash scripts/install-hooks.sh           install the pre-commit and commit-msg dispatchers
#   bash scripts/install-hooks.sh --check   exit 1 with a loud warning if either is missing
#
# What it installs. Small DISPATCHERS in <git-common-dir>/hooks/ that run the COMMITTING
# worktree's own script: "$(git rev-parse --show-toplevel)/scripts/<hook>.sh". Hooks live in
# the common git dir, shared by every worktree, so the old relative symlink there always ran
# the MAIN checkout's script (BL-193).
#   - pre-commit  -> scripts/pre-commit.sh. Every branch has it, so a missing script fails
#     the commit (closed). An OLDER branch runs its own older pre-commit.sh, which may lack
#     newer gates until it merges main; CI is the backstop.
#   - commit-msg  -> scripts/commit-msg.sh (scans the message for customer references). It
#     is new, so a branch without it simply skips the check (exit 0).
#
# What it deliberately does NOT do:
#   - set core.hooksPath. That config is shared by every worktree, so any checkout whose
#     branch lacks the hooks directory would silently run NO hook. If core.hooksPath is
#     already set (any scope), this script refuses rather than fighting it.
#   - install pre-push. scripts/pre-push.sh runs live smoke tests against a real profile;
#     enabling that is the user's decision. An existing pre-push hook is left untouched.
#
# --check runs from the SessionStart hook in .claude/settings.json, so a missing or stale
# dispatcher is reported at the start of every Claude Code session. It never installs.

set -euo pipefail

HOOKS="pre-commit commit-msg"

dispatcher() {
  case "$1" in
    pre-commit) cat <<'EOF'
#!/bin/sh
# thoughtspot-agent-skills pre-commit dispatcher v1 -- installed by scripts/install-hooks.sh.
# Runs the COMMITTING worktree's own scripts/pre-commit.sh (hooks are shared by every
# worktree, so a fixed path would run one checkout's copy for all of them; see BL-193).
top="$(git rev-parse --show-toplevel)" || exit 1
hook="$top/scripts/pre-commit.sh"
if [ ! -f "$hook" ]; then
  echo "pre-commit dispatcher: $hook not found, so no checks could run." >&2
  echo "Refusing the commit. Use 'git commit --no-verify' only if that is intended." >&2
  exit 1
fi
exec bash "$hook" "$@"
EOF
    ;;
    commit-msg) cat <<'EOF'
#!/bin/sh
# thoughtspot-agent-skills commit-msg dispatcher v1 -- installed by scripts/install-hooks.sh.
# Runs the COMMITTING worktree's own scripts/commit-msg.sh if that branch has one; older
# branches predate it, so its absence is not an error.
top="$(git rev-parse --show-toplevel)" || exit 1
hook="$top/scripts/commit-msg.sh"
[ -f "$hook" ] || exit 0
exec bash "$hook" "$@"
EOF
    ;;
  esac
}

ROOT="$(git rev-parse --show-toplevel)"
# Resolve against ROOT, not the caller's cwd: --git-common-dir can print a RELATIVE path
# (".git"), which is wrong when this script is run from a subdirectory.
COMMON="$(git -C "$ROOT" rev-parse --git-common-dir)"
case "$COMMON" in
  /*) ;;
  *) COMMON="$ROOT/$COMMON" ;;
esac
HOOKS_PATH="$(git -C "$ROOT" config --get core.hooksPath || true)"

if [ "${1:-}" = "--check" ]; then
  if [ -n "$HOOKS_PATH" ]; then
    echo "WARNING: core.hooksPath is set ('$HOOKS_PATH'), so git ignores $COMMON/hooks and"
    echo "         this repo's commit gates (secrets, customer references, ...) may not run."
    echo "         Unset it (git config --unset core.hooksPath, or --global) and run: bash scripts/install-hooks.sh"
    exit 1
  fi
  missing=""
  for h in $HOOKS; do
    f="$COMMON/hooks/$h"
    if ! { [ -x "$f" ] && [ "$(cat "$f")" = "$(dispatcher "$h")" ]; }; then
      missing="$missing $h"
    fi
  done
  [ -z "$missing" ] && exit 0
  echo "WARNING: git hook(s) NOT installed or out of date for this repo:$missing"
  echo "         Commits skip those gates (secrets, customer references, ...)."
  echo "         Fix: bash scripts/install-hooks.sh"
  exit 1
fi

if [ -n "$HOOKS_PATH" ]; then
  echo "REFUSING: core.hooksPath is set to '$HOOKS_PATH'. Git ignores $COMMON/hooks while it is"
  echo "set, so installing there would do nothing. This script will not override your setting."
  echo "Either unset it (git config --unset core.hooksPath, or --global) and re-run, or wire"
  echo "scripts/pre-commit.sh and scripts/commit-msg.sh into your own hooks directory yourself."
  exit 1
fi

mkdir -p "$COMMON/hooks"
for h in $HOOKS; do
  f="$COMMON/hooks/$h"
  if [ -e "$f" ] || [ -L "$f" ]; then
    if [ -f "$f" ] && [ "$(cat "$f")" = "$(dispatcher "$h")" ]; then
      chmod +x "$f"
      echo "Already installed: $f"
      continue
    fi
    # Unique and never overwriting: a one-second timestamp alone collided when two installs
    # ran in the same second, and the second backup replaced the first.
    stamp="$(date +%Y%m%d%H%M%S)-$$"
    BACKUP="$f.backup-$stamp"
    n=0
    while [ -e "$BACKUP" ] || [ -L "$BACKUP" ]; do
      n=$((n + 1))
      BACKUP="$f.backup-$stamp-$n"
    done
    mv -n "$f" "$BACKUP"
    echo "Backed up the existing $h hook to $BACKUP"
  fi
  dispatcher "$h" > "$f"
  chmod +x "$f"
  echo "Installed: $f"
done
echo "  Every worktree now runs its own scripts/pre-commit.sh and scripts/commit-msg.sh."
echo "  pre-push was not touched."
