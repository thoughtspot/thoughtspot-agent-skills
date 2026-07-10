#!/usr/bin/env bash
# Deploy the Databricks Asset Bundle and Genie skills.
#
# Two deployment targets:
#   1. Bundle → /Workspace/thoughtspot-skills/  (notebooks, token refresh job)
#   2. Genie  → /Workspace/Users/<email>/.assistant/  (skills, shared refs, ts_client)
#
# Usage:
#   ./deploy.sh -u your-email@company.com          # deploys to dev (default)
#   ./deploy.sh -u your-email@company.com -t prod  # deploys to prod
#
# The -u flag is required — Genie discovers skills under the user's personal
# workspace path, not the Service Principal's.

set -euo pipefail

# --- Parse -u flag ---
USER_EMAIL=""
BUNDLE_ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        -u) USER_EMAIL="$2"; shift 2 ;;
        *)  BUNDLE_ARGS+=("$1"); shift ;;
    esac
done

if [ -z "$USER_EMAIL" ]; then
    echo "Error: -u <email> is required."
    echo "Usage: ./deploy.sh -u your-email@company.com [-t dev|prod]"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SHARED_SRC="$REPO_ROOT/agents/shared"
SHARED_DST="$SCRIPT_DIR/shared"

# --- Copy shared references for bundle ---
rm -rf "$SHARED_DST"
mkdir -p "$SHARED_DST/mappings/ts-databricks" "$SHARED_DST/schemas"

cp "$SHARED_SRC/mappings/ts-databricks/ts-to-databricks-rules.md"              "$SHARED_DST/mappings/ts-databricks/"
cp "$SHARED_SRC/mappings/ts-databricks/ts-from-databricks-rules.md"            "$SHARED_DST/mappings/ts-databricks/"
cp "$SHARED_SRC/mappings/ts-databricks/ts-databricks-formula-translation.md"   "$SHARED_DST/mappings/ts-databricks/"
cp "$SHARED_SRC/mappings/ts-databricks/ts-databricks-properties.md"            "$SHARED_DST/mappings/ts-databricks/"
cp "$SHARED_SRC/schemas/databricks-metric-view.md"                             "$SHARED_DST/schemas/"
cp "$SHARED_SRC/schemas/thoughtspot-table-tml.md"                              "$SHARED_DST/schemas/"
cp "$SHARED_SRC/schemas/thoughtspot-model-tml.md"                              "$SHARED_DST/schemas/"
cp "$SHARED_SRC/schemas/ts-tml-import-gate.md"                                 "$SHARED_DST/schemas/"

echo "✓ Copied shared references → $SHARED_DST"

# --- Vendor the pure ts-cli conversion closure as a Genie notebook (BL-063 PR 5) ---
python3 "$SCRIPT_DIR/build_mv_lib.py" \
    --ts-cli-root "$REPO_ROOT/tools/ts-cli" \
    --out "$SCRIPT_DIR/notebooks/databricks_mv_lib.py"
echo "✓ Built vendored databricks_mv_lib notebook"

# --- Deploy bundle (notebooks + token refresh job) ---
cd "$SCRIPT_DIR"
databricks bundle deploy "${BUNDLE_ARGS[@]+"${BUNDLE_ARGS[@]}"}"
echo "✓ Bundle deployed"

# --- Deploy Genie skills to user's .assistant/ path ---
echo ""
echo "Deploying Genie skills to .assistant/ ..."

ASSISTANT_ROOT="/Workspace/Users/${USER_EMAIL}/.assistant"

echo "  User: $USER_EMAIL"
echo "  Path: $ASSISTANT_ROOT"

# Create directory structure
databricks workspace mkdirs "${ASSISTANT_ROOT}/skills/ts-convert-from-databricks-mv" 2>/dev/null || true
databricks workspace mkdirs "${ASSISTANT_ROOT}/skills/ts-convert-to-databricks-mv" 2>/dev/null || true
databricks workspace mkdirs "${ASSISTANT_ROOT}/skills/shared/mappings/ts-databricks" 2>/dev/null || true
databricks workspace mkdirs "${ASSISTANT_ROOT}/skills/shared/schemas" 2>/dev/null || true
databricks workspace mkdirs "${ASSISTANT_ROOT}/notebooks" 2>/dev/null || true

# Import skills
databricks workspace import "${ASSISTANT_ROOT}/skills/ts-convert-from-databricks-mv/SKILL.md" \
    --file "$SCRIPT_DIR/skills/ts-convert-from-databricks-mv/SKILL.md" --format AUTO --overwrite
databricks workspace import "${ASSISTANT_ROOT}/skills/ts-convert-to-databricks-mv/SKILL.md" \
    --file "$SCRIPT_DIR/skills/ts-convert-to-databricks-mv/SKILL.md" --format AUTO --overwrite

# Import shared references
for f in "$SHARED_DST/mappings/ts-databricks/"*.md; do
    fname=$(basename "$f")
    databricks workspace import "${ASSISTANT_ROOT}/skills/shared/mappings/ts-databricks/${fname}" \
        --file "$f" --format AUTO --overwrite
done
for f in "$SHARED_DST/schemas/"*.md; do
    fname=$(basename "$f")
    databricks workspace import "${ASSISTANT_ROOT}/skills/shared/schemas/${fname}" \
        --file "$f" --format AUTO --overwrite
done

# Import ts_client as a notebook (for %run from skill context)
databricks workspace import "${ASSISTANT_ROOT}/notebooks/ts_client" \
    --file "$SCRIPT_DIR/notebooks/ts_client.py" --format SOURCE --language PYTHON --overwrite

databricks workspace import "${ASSISTANT_ROOT}/notebooks/databricks_mv_lib" \
    --file "$SCRIPT_DIR/notebooks/databricks_mv_lib.py" --format SOURCE --language PYTHON --overwrite

echo "✓ Genie skills deployed to ${ASSISTANT_ROOT}"
echo ""
echo "Verify with:"
echo "  databricks workspace list ${ASSISTANT_ROOT}/skills"
