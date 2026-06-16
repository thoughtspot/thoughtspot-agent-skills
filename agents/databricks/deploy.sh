#!/usr/bin/env bash
# Deploy the Databricks Asset Bundle.
#
# Copies shared references from agents/shared/ into a local shared/ dir
# (gitignored) so the bundle can include them, then runs databricks bundle deploy.
#
# Usage:
#   ./deploy.sh          # deploys to the default target (dev)
#   ./deploy.sh -t prod  # deploys to prod

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SHARED_SRC="$REPO_ROOT/agents/shared"
SHARED_DST="$SCRIPT_DIR/shared"

# --- Copy shared references ---
rm -rf "$SHARED_DST"
mkdir -p "$SHARED_DST/mappings/ts-databricks" "$SHARED_DST/schemas"

cp "$SHARED_SRC/mappings/ts-databricks/ts-to-databricks-rules.md"              "$SHARED_DST/mappings/ts-databricks/"
cp "$SHARED_SRC/mappings/ts-databricks/ts-from-databricks-rules.md"            "$SHARED_DST/mappings/ts-databricks/"
cp "$SHARED_SRC/mappings/ts-databricks/ts-databricks-formula-translation.md"   "$SHARED_DST/mappings/ts-databricks/"
cp "$SHARED_SRC/mappings/ts-databricks/ts-databricks-properties.md"            "$SHARED_DST/mappings/ts-databricks/"
cp "$SHARED_SRC/schemas/databricks-metric-view.md"                             "$SHARED_DST/schemas/"
cp "$SHARED_SRC/schemas/thoughtspot-table-tml.md"                              "$SHARED_DST/schemas/"
cp "$SHARED_SRC/schemas/thoughtspot-model-tml.md"                              "$SHARED_DST/schemas/"

echo "Copied shared references → $SHARED_DST"

# --- Deploy bundle ---
cd "$SCRIPT_DIR"
databricks bundle deploy "$@"
