#!/usr/bin/env bash
# Install ThoughtSpot Cursor rules into a project directory.
#
# Usage:
#   # Install into the current directory
#   ~/Dev/thoughtspot-agent-skills/agents/cursor/scripts/install.sh
#
#   # Install into a specific directory
#   ~/Dev/thoughtspot-agent-skills/agents/cursor/scripts/install.sh /path/to/project
#
# What it does:
#   1. Creates .cursor/rules/ in the target project (if it doesn't exist)
#   2. Symlinks each .mdc file from this repo's agents/cursor/rules/ into .cursor/rules/
#   3. Creates ~/.cursor/shared/ symlink → agents/shared/ (once, global)
#
# To update rules after a git pull: no action needed — symlinks pick up changes automatically.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
RULES_SRC="$REPO_DIR/agents/cursor/rules"
TARGET="${1:-$(pwd)}"
TARGET="$(cd "$TARGET" && pwd)"

echo "Installing ThoughtSpot Cursor rules into: $TARGET"

# ── 1. Create .cursor/rules/ ──────────────────────────────────────────────────
RULES_DEST="$TARGET/.cursor/rules"
mkdir -p "$RULES_DEST"

# ── 2. Symlink each .mdc file ─────────────────────────────────────────────────
linked=0
for src in "$RULES_SRC"/*.mdc; do
    name="$(basename "$src")"
    dest="$RULES_DEST/$name"
    if [ -L "$dest" ]; then
        echo "  skipped (already linked): $name"
    elif [ -e "$dest" ]; then
        echo "  skipped (file exists, not a symlink): $name — remove it manually to link"
    else
        ln -s "$src" "$dest"
        echo "  linked: $name"
        linked=$((linked + 1))
    fi
done

# ── 3. Create ~/.cursor/shared/ symlink (global, one-time) ────────────────────
SHARED_SRC="$REPO_DIR/agents/shared"
SHARED_DEST="$HOME/.cursor/shared"

mkdir -p "$HOME/.cursor"

if [ -L "$SHARED_DEST" ]; then
    echo "  ~/.cursor/shared already linked"
elif [ -e "$SHARED_DEST" ]; then
    echo "  WARNING: ~/.cursor/shared exists and is not a symlink — skipping"
    echo "           Remove it manually and re-run if you want the symlink created."
else
    ln -s "$SHARED_SRC" "$SHARED_DEST"
    echo "  linked: ~/.cursor/shared → $SHARED_SRC"
fi

echo ""
echo "Done. $linked rule(s) installed."
echo ""
echo "Next steps:"
echo "  1. pip install requests pyyaml keyring snowflake-connector-python cryptography"
echo "  2. pip install -e $REPO_DIR/tools/ts-cli"
echo "  3. Open your project in Cursor and ask: 'Set up my ThoughtSpot profile'"
