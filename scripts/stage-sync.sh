#!/usr/bin/env bash
# scripts/stage-sync.sh
#
# Sync CoCo skill files and shared references to the Snowflake stage.
#
# Only uploads files that changed since the last sync, tracked via
# .snowflake-deploy-sha (gitignored, local to your machine).
#
# Usage:
#   ./scripts/stage-sync.sh          # sync changed files only
#   ./scripts/stage-sync.sh --all    # force full upload (e.g. after initial clone)

set -euo pipefail

# Stage location — override with SNOW_STAGE env var if your account uses a different stage.
# Example: export SNOW_STAGE="@MY_DB.MY_SCHEMA.MY_STAGE/skills/.snowflake/cortex"
STAGE="${SNOW_STAGE:-@SKILLS.PUBLIC.SHARED/skills/.snowflake/cortex}"
SHA_FILE=".snowflake-deploy-sha"
FORCE_ALL=false

for arg in "$@"; do
  case $arg in
    --all) FORCE_ALL=true ;;
    *) echo "Unknown argument: $arg" >&2; exit 1 ;;
  esac
done

# ── Determine which files changed since last sync ─────────────────────────────
if $FORCE_ALL; then
  echo "Full sync requested — uploading all CoCo and shared files."
  CHANGED_FILES=$(git ls-files agents/coco/ agents/shared/)
elif [ -f "$SHA_FILE" ]; then
  LAST_SHA=$(cat "$SHA_FILE")
  echo "Last stage sync: $LAST_SHA"
  # Include locally modified but uncommitted files too
  COMMITTED=$(git diff --name-only "$LAST_SHA" HEAD 2>/dev/null || git ls-files agents/coco/ agents/shared/)
  UNCOMMITTED=$(git diff --name-only agents/coco/ agents/shared/; git diff --cached --name-only agents/coco/ agents/shared/)
  CHANGED_FILES=$(printf '%s\n%s\n' "$COMMITTED" "$UNCOMMITTED" | sort -u)
else
  echo "No previous sync found — uploading all CoCo and shared files."
  CHANGED_FILES=$(git ls-files agents/coco/ agents/shared/)
fi

# Filter to only coco/ and shared/ paths
COCO_CHANGED=$(echo "$CHANGED_FILES" | grep -E "^agents/(coco|shared)/" || true)

if [ -z "$COCO_CHANGED" ]; then
  echo "No CoCo or shared files changed since last sync. Nothing to upload."
  exit 0
fi

echo ""
echo "Files to upload:"
echo "$COCO_CHANGED" | sed 's/^/  /'
echo ""

SYNCED=0
FAILED=0

while IFS= read -r file; do
  [ -z "$file" ] && continue
  [ ! -f "$file" ] && { echo "  (skipping deleted) $file"; continue; }

  if [[ "$file" == agents/coco/* ]]; then
    rel="${file#agents/coco/}"
    rel_dir="$(dirname "$rel")"
    dest_dir="$STAGE/skills/$( [ "$rel_dir" = "." ] && echo "" || echo "$rel_dir/" )"

  elif [[ "$file" == agents/shared/* ]]; then
    rel="${file#agents/shared/}"
    rel_dir="$(dirname "$rel")"
    dest_dir="$STAGE/shared/$( [ "$rel_dir" = "." ] && echo "" || echo "$rel_dir/" )"

  else
    continue
  fi

  printf "  uploading %-60s → %s\n" "$file" "$dest_dir"
  if snow stage copy "$file" "$dest_dir" --overwrite --silent 2>/dev/null; then
    SYNCED=$((SYNCED + 1))
  else
    echo "  ERROR: failed to upload $file" >&2
    FAILED=$((FAILED + 1))
  fi

done <<< "$COCO_CHANGED"

echo ""

if [ "$FAILED" -gt 0 ]; then
  echo "Sync completed with $FAILED error(s). $SYNCED file(s) uploaded."
  echo "Fix the errors above and re-run to retry."
  exit 1
fi

# Update sync marker only on clean success
git rev-parse HEAD > "$SHA_FILE"

echo "$SYNCED file(s) synced to stage."
echo "Reload your Snowsight Workspace to pick up the changes."
echo "Run /ts-sv-setup in the Workspace if stored procedures changed."
