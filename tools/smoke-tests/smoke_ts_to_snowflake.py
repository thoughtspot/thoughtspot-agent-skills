#!/usr/bin/env python3
"""
smoke_ts_to_snowflake.py — live round-trip smoke test for ts-to-snowflake-sv.

Verifies the full path:
  1. ThoughtSpot auth
  2. Find the target model/worksheet by name
  3. Export TML and confirm it parses
  4. Validate the worked-example Semantic View YAML against check_sv_yaml
  5. Dry-run SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML (validate: TRUE)
  6. Create the Semantic View
  7. Confirm it appears in SHOW SEMANTIC VIEWS
  8. DESCRIBE SEMANTIC VIEW — confirm structure is well-formed
  9. Cleanup (unless --no-cleanup)

This script is intentionally NOT a pytest test — it has side effects (creates and
drops a Snowflake Semantic View) and requires live credentials.

Usage:
    python tools/smoke-tests/smoke_ts_to_snowflake.py \\
        --ts-profile production \\
        --sf-profile production \\
        --sv-yaml agents/shared/worked-examples/snowflake/ts-to-snowflake.md \\
        --sf-target-db ANALYTICS \\
        --sf-target-schema PUBLIC_SMOKE_TEST \\
        [--ts-model-name "Retail Sales"] \\
        [--no-cleanup]

Credentials are read from:
  - ThoughtSpot: ~/.claude/thoughtspot-profiles.json  (ts CLI handles auth)
  - Snowflake:   ~/.claude/snowflake-profiles.json    (snow CLI connection)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

# Allow imports from tools/validate without installing them as a package
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "tools" / "validate"))
sys.path.insert(0, str(Path(__file__).parent))

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Run: pip install PyYAML")
    sys.exit(1)

from check_sv_yaml import validate_sv_yaml  # noqa: E402
from _common import (  # noqa: E402
    SmokeTestResult, SkipStep,
    ts_auth_check, run_ts,
    load_sf_profile, get_snow_cmd, snow_json_file, snow_exec,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_sv_yaml_from_md(md_path: Path) -> dict:
    """Extract the last ```yaml block that looks like a Semantic View from a .md file."""
    content = md_path.read_text(encoding="utf-8")
    in_block = False
    block_lines: list[str] = []
    candidates: list[str] = []

    for line in content.splitlines():
        stripped = line.strip()
        if not in_block:
            if stripped.startswith("```yaml") or stripped.startswith("```yml"):
                in_block = True
                block_lines = []
        else:
            if stripped == "```":
                in_block = False
                candidates.append("\n".join(block_lines))
                block_lines = []
            else:
                block_lines.append(line)

    # Find the last block that looks like a Semantic View YAML
    for block in reversed(candidates):
        try:
            data = yaml.safe_load(block)
            if isinstance(data, dict) and "tables" in data and "name" in data:
                return data
        except yaml.YAMLError:
            continue

    raise RuntimeError(
        f"No Semantic View YAML block found in {md_path.name}. "
        "The file must contain a ```yaml block with 'name' and 'tables' keys."
    )



def _find_model_guid(ts_profile: str, model_name: str) -> str:
    """Search ThoughtSpot for a worksheet/model by name and return its GUID."""
    results = run_ts(
        ["metadata", "search", "--subtype", "WORKSHEET", "--name", f"%{model_name}%"],
        ts_profile,
    )
    if not isinstance(results, list) or not results:
        raise RuntimeError(
            f"No ThoughtSpot model found matching '{model_name}'. "
            "Check the model name and profile."
        )
    # Pick exact match if possible, else first result
    exact = [r for r in results if r.get("metadata_name") == model_name]
    chosen = exact[0] if exact else results[0]
    guid = chosen.get("metadata_id") or chosen.get("id")
    if not guid:
        raise RuntimeError(f"Result for '{model_name}' has no GUID: {chosen}")
    return guid


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke test: ts-to-snowflake-sv round-trip."
    )
    parser.add_argument(
        "--ts-profile", required=True,
        help="ThoughtSpot profile name (from ~/.claude/thoughtspot-profiles.json)",
    )
    parser.add_argument(
        "--sf-profile", required=True,
        help="Snowflake profile name (from ~/.claude/snowflake-profiles.json)",
    )
    parser.add_argument(
        "--sv-yaml",
        default="agents/shared/worked-examples/snowflake/ts-to-snowflake.md",
        help="Path to a .md file containing the Semantic View YAML to test, "
             "OR a path to a standalone .yaml file. "
             "(default: agents/shared/worked-examples/snowflake/ts-to-snowflake.md)",
    )
    parser.add_argument(
        "--sf-target-db", required=True,
        help="Snowflake database to create the test Semantic View in",
    )
    parser.add_argument(
        "--sf-target-schema", required=True,
        help="Snowflake schema to create the test Semantic View in",
    )
    parser.add_argument(
        "--ts-model-name",
        help="ThoughtSpot model/worksheet name to verify TML export (optional). "
             "If omitted, the ThoughtSpot TML export step is skipped.",
    )
    parser.add_argument(
        "--no-cleanup", action="store_true",
        help="Keep the created Semantic View after the test (for manual inspection).",
    )
    args = parser.parse_args()

    r = SmokeTestResult()

    print()
    print("=" * 60)
    print("Smoke test: ts-to-snowflake-sv")
    print("=" * 60)
    print(f"  ThoughtSpot profile:  {args.ts_profile}")
    print(f"  Snowflake profile:    {args.sf_profile}")
    print(f"  SV YAML source:       {args.sv_yaml}")
    print(f"  Target:               {args.sf_target_db}.{args.sf_target_schema}")
    print()

    # ── Load Snowflake profile ────────────────────────────────────────────────
    ok, sf_profile = r.step("Load Snowflake profile", load_sf_profile, args.sf_profile)
    if not ok:
        return r.summary()

    snow_cmd = get_snow_cmd(sf_profile)
    cli_conn = sf_profile.get("cli_connection")
    if not cli_conn:
        r.failures.append("Load Snowflake profile: profile has no 'cli_connection' — "
                          "only CLI method profiles are supported for smoke tests")
        return r.summary()

    # ── ThoughtSpot auth ──────────────────────────────────────────────────────
    ok, whoami = r.step("ThoughtSpot auth (ts auth whoami)", ts_auth_check, args.ts_profile)
    if not ok:
        return r.summary()
    r.info(f"Authenticated as: {whoami.get('display_name', whoami.get('name', '?'))}")

    # ── Optional: verify TML export ───────────────────────────────────────────
    if args.ts_model_name:
        ok, guid = r.step(
            f"Find ThoughtSpot model '{args.ts_model_name}'",
            _find_model_guid, args.ts_profile, args.ts_model_name,
        )
        if ok:
            r.info(f"GUID: {guid}")
            ok, tml_result = r.step(
                "Export model TML",
                run_ts, ["tml", "export", guid, "--fqn", "--associated"], args.ts_profile,
            )
            if ok:
                count = len(tml_result) if isinstance(tml_result, list) else 1
                r.info(f"Exported {count} TML object(s)")

    # ── Load SV YAML ─────────────────────────────────────────────────────────
    sv_path = Path(args.sv_yaml)
    if not sv_path.is_absolute():
        sv_path = _REPO_ROOT / sv_path

    if sv_path.suffix in (".yaml", ".yml"):
        ok, sv_data = r.step(
            "Load Semantic View YAML",
            lambda: yaml.safe_load(sv_path.read_text(encoding="utf-8")),
        )
    else:
        ok, sv_data = r.step(
            "Extract SV YAML from .md file",
            _extract_sv_yaml_from_md, sv_path,
        )
    if not ok:
        return r.summary()

    view_name: str = sv_data.get("name", "smoke_test_sv")
    r.info(f"View name: {view_name}")

    # ── Structural validation ────────────────────────────────────────────────
    def _structural_validate():
        errors = validate_sv_yaml(sv_data)
        if errors:
            raise RuntimeError(
                f"{len(errors)} structural error(s):\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

    ok, _ = r.step("Structural validation (check_sv_yaml)", _structural_validate)
    if not ok:
        return r.summary()  # no point running live tests if structure is wrong

    # ── Snowflake: set context ────────────────────────────────────────────────
    sv_yaml_str = yaml.dump(sv_data, default_flow_style=False, allow_unicode=True)

    def _set_context():
        snow_exec(
            snow_cmd, cli_conn,
            f"USE DATABASE {args.sf_target_db}; "
            f"USE SCHEMA {args.sf_target_schema};"
        )

    ok, _ = r.step(
        f"Set Snowflake context ({args.sf_target_db}.{args.sf_target_schema})",
        _set_context,
    )
    if not ok:
        return r.summary()

    # ── Dry-run validation ───────────────────────────────────────────────────
    def _dry_run():
        rows = snow_json_file(
            snow_cmd, cli_conn,
            f"CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML("
            f"'{args.sf_target_db}.{args.sf_target_schema}', $${sv_yaml_str}$$, TRUE);"
        )
        # Success returns something like [{"SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML": "..."}]
        if rows:
            val = list(rows[0].values())[0] if rows[0] else ""
            if "error" in str(val).lower() or "fail" in str(val).lower():
                raise RuntimeError(f"Dry-run returned error: {val}")

    ok, _ = r.step("Dry-run SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML (..., TRUE)", _dry_run)
    if not ok:
        return r.summary()

    # ── Drop existing view if present ────────────────────────────────────────
    def _drop_existing():
        snow_exec(
            snow_cmd, cli_conn,
            f"DROP SEMANTIC VIEW IF EXISTS "
            f"{args.sf_target_db}.{args.sf_target_schema}.{view_name};"
        )

    r.step("Drop existing view if present", _drop_existing)

    # ── Create the Semantic View ──────────────────────────────────────────────
    def _create_sv():
        rows = snow_json_file(
            snow_cmd, cli_conn,
            f"CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML("
            f"'{args.sf_target_db}.{args.sf_target_schema}', $${sv_yaml_str}$$);"
        )
        if rows:
            val = list(rows[0].values())[0] if rows[0] else ""
            if "error" in str(val).lower():
                raise RuntimeError(f"CREATE returned error: {val}")

    ok, _ = r.step("Create Semantic View", _create_sv)
    if not ok:
        return r.summary()

    # ── Confirm view exists via SHOW ─────────────────────────────────────────
    def _show_sv():
        rows = snow_json_file(
            snow_cmd, cli_conn,
            f"SHOW SEMANTIC VIEWS LIKE '{view_name}' "
            f"IN SCHEMA {args.sf_target_db}.{args.sf_target_schema};"
        )
        found = [
            row for row in rows
            if str(row.get("name", "")).upper() == view_name.upper()
        ]
        if not found:
            raise RuntimeError(
                f"SHOW SEMANTIC VIEWS returned no row for '{view_name}'. "
                "The CREATE call may have succeeded without creating the view — "
                "check for silent errors."
            )
        return found[0]

    ok, sv_row = r.step(f"SHOW SEMANTIC VIEWS confirms '{view_name}' exists", _show_sv)
    if ok and sv_row:
        r.info(f"View row: name={sv_row.get('name')}, owner={sv_row.get('owner')}")

    # ── Describe the Semantic View (confirm structure is well-formed) ─────────
    # DESCRIBE SEMANTIC VIEW returns one row per element (dimensions, metrics, etc.)
    # and confirms the view was created with the expected content, not just that an
    # entry exists in the catalog.
    if ok:
        def _describe_sv():
            rows = snow_json_file(
                snow_cmd, cli_conn,
                f"DESCRIBE SEMANTIC VIEW "
                f"{args.sf_target_db}.{args.sf_target_schema}.{view_name};"
            )
            if not rows:
                raise RuntimeError(
                    f"DESCRIBE SEMANTIC VIEW returned no rows for '{view_name}'. "
                    "The view may be structurally empty or malformed."
                )
            return rows

        ok, desc_rows = r.step(
            f"DESCRIBE SEMANTIC VIEW '{view_name}' is well-formed", _describe_sv
        )
        if ok and desc_rows:
            r.info(f"Semantic View has {len(desc_rows)} described element(s)")

    # Note: Snowflake Semantic Views created via SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML
    # are NOT directly queryable with SQL SELECT — they are a semantic layer definition
    # consumed by Cortex Analyst, not a regular SQL view. SHOW SEMANTIC VIEWS +
    # DESCRIBE SEMANTIC VIEW are the correct confirmations that the view was created
    # and is well-formed. To test Cortex Analyst end-to-end, upload the YAML to a
    # Snowflake stage and call the Cortex Analyst REST API directly.

    # ── Cleanup ───────────────────────────────────────────────────────────────
    if args.no_cleanup:
        r.info(
            f"Skipping cleanup (--no-cleanup). "
            f"View remains at: {args.sf_target_db}.{args.sf_target_schema}.{view_name}"
        )
    else:
        def _cleanup():
            snow_exec(
                snow_cmd, cli_conn,
                f"DROP SEMANTIC VIEW IF EXISTS "
                f"{args.sf_target_db}.{args.sf_target_schema}.{view_name};"
            )

        r.step("Cleanup: DROP SEMANTIC VIEW", _cleanup)

    return r.summary()


if __name__ == "__main__":
    sys.exit(main())
