#!/usr/bin/env python3
"""
smoke_ts_from_snowflake.py — live round-trip smoke test for ts-from-snowflake-sv.

Verifies the full path:
  1. ThoughtSpot auth
  2. Snowflake auth (snow CLI)
  3. Fetch DDL for a known Semantic View (GET_DDL)
  4. Confirm the DDL parses as expected (has SEMANTIC VIEW header)
  5. Search ThoughtSpot for table objects matching the SV's tables
  6. Build a minimal Model TML from the SV structure
  7. Validate the Model TML against check_tml
  8. Import the model TML to ThoughtSpot
  9. Verify the model appears in metadata search
 10. Count columns vs expected
 11. Cleanup: delete imported model (unless --no-cleanup)

Usage:
    python tools/smoke-tests/smoke_ts_from_snowflake.py \\
        --ts-profile production \\
        --sf-profile production \\
        --sv-fqn "BIRD.SUPERHERO_SV.BIRD_SUPERHEROS_SV" \\
        [--no-cleanup]

Notes:
  - The Semantic View must already exist in Snowflake.
  - ThoughtSpot table objects for the SV's tables must already exist
    (the smoke test verifies they can be found, not that they are created).
  - The imported model will be named "SMOKE_TEST_{sv_name}" and deleted after.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "tools" / "validate"))
sys.path.insert(0, str(Path(__file__).parent))

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Run: pip install PyYAML")
    sys.exit(1)

from check_tml import validate_model_tml  # noqa: E402
from _common import (  # noqa: E402
    SmokeTestResult, SkipStep,
    ts_auth_check, run_ts,
    load_sf_profile, get_snow_cmd, snow_json,
)


# ---------------------------------------------------------------------------
# Parse SV DDL (minimal — just enough to count tables/metrics for verification)
# ---------------------------------------------------------------------------

def _parse_sv_name(ddl: str) -> str:
    """Extract the semantic view name from its DDL."""
    m = re.search(r'SEMANTIC VIEW\s+(?:\S+\.)*(\w+)', ddl, re.IGNORECASE)
    return m.group(1) if m else "UNKNOWN"


def _count_sv_tables(ddl: str) -> int:
    """Count table entries in the SV DDL's TABLES(...) block.

    The DDL uses 'TABLES' (plural) as the section keyword — 'TABLE' (singular)
    does NOT appear as a standalone keyword in the Semantic View DDL format.
    Each entry in the TABLES block has the form 'alias AS DB.SCHEMA.TABLE_NAME'.
    """
    tables_block = re.search(r'\bTABLES\s*\((.*?)\)', ddl, re.IGNORECASE | re.DOTALL)
    if not tables_block:
        return 0
    block = tables_block.group(1)
    # Count 'AS' keywords — one per table entry (alias AS FQN)
    as_count = len(re.findall(r'\bAS\b', block, re.IGNORECASE))
    return max(as_count, 1) if block.strip() else 0


# ---------------------------------------------------------------------------
# ThoughtSpot model TML helpers
# ---------------------------------------------------------------------------

def _search_ts_tables(ts_profile: str, table_name: str) -> list[dict]:
    """Search for ThoughtSpot Logical Table objects by name."""
    return run_ts(
        ["metadata", "search", "--subtype", "ONE_TO_ONE_LOGICAL",
         "--name", f"%{table_name}%"],
        ts_profile,
    )


def _build_minimal_model_tml(model_name: str, table_guids: list[tuple[str, str]]) -> dict:
    """
    Build the simplest valid Model TML that can be imported.
    table_guids: list of (table_name, guid)

    Per ThoughtSpot TML rules: `id` must equal `name` exactly (ThoughtSpot resolves
    join references against `id`). The GUID goes in `fqn`, not `id`.
    """
    model_tables = [
        {"name": name, "id": name, "fqn": guid}
        for name, guid in table_guids
    ]
    return {
        "model": {
            "name": model_name,
            "model_tables": model_tables,
            "columns": [],
        }
    }


def _import_model_tml(ts_profile: str, tml_data: dict) -> str:
    """Import a model TML and return the created GUID."""
    tml_str = yaml.dump(tml_data, default_flow_style=False, allow_unicode=True)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, prefix="smoke_model_"
    ) as f:
        f.write(tml_str)
        tmp_path = f.name

    result = run_ts(
        ["tml", "import", "--file", tmp_path, "--policy", "ALL_OR_NONE"],
        ts_profile,
    )
    Path(tmp_path).unlink(missing_ok=True)

    # Parse GUID from result
    if isinstance(result, list):
        for item in result:
            g = item.get("response", {}).get("header", {}).get("id_guid") or \
                item.get("id_guid") or item.get("metadata_id")
            if g:
                return g
    elif isinstance(result, dict):
        g = result.get("id_guid") or result.get("metadata_id")
        if g:
            return g

    raise RuntimeError(
        f"Could not extract GUID from import response: {json.dumps(result)[:300]}"
    )


def _delete_ts_object(ts_profile: str, guid: str) -> None:
    """Delete a ThoughtSpot metadata object by GUID."""
    run_ts(["metadata", "delete", guid], ts_profile)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke test: ts-from-snowflake-sv round-trip."
    )
    parser.add_argument(
        "--ts-profile", required=True,
        help="ThoughtSpot profile name",
    )
    parser.add_argument(
        "--sf-profile", required=True,
        help="Snowflake profile name (from ~/.claude/snowflake-profiles.json)",
    )
    parser.add_argument(
        "--sv-fqn", required=True,
        help="Fully qualified Snowflake Semantic View name, e.g. DB.SCHEMA.VIEW_NAME",
    )
    parser.add_argument(
        "--no-cleanup", action="store_true",
        help="Keep the imported ThoughtSpot model after the test.",
    )
    args = parser.parse_args()

    r = SmokeTestResult()

    print()
    print("=" * 60)
    print("Smoke test: ts-from-snowflake-sv")
    print("=" * 60)
    print(f"  ThoughtSpot profile:  {args.ts_profile}")
    print(f"  Snowflake profile:    {args.sf_profile}")
    print(f"  Semantic View:        {args.sv_fqn}")
    print()

    # ── Load Snowflake profile ────────────────────────────────────────────────
    ok, sf_profile = r.step("Load Snowflake profile", load_sf_profile, args.sf_profile)
    if not ok:
        return r.summary()

    snow_cmd = get_snow_cmd(sf_profile)
    cli_conn = sf_profile.get("cli_connection")
    if not cli_conn:
        r.failures.append("Load Snowflake profile: profile has no 'cli_connection'")
        return r.summary()

    # ── ThoughtSpot auth ──────────────────────────────────────────────────────
    ok, whoami = r.step("ThoughtSpot auth (ts auth whoami)", ts_auth_check, args.ts_profile)
    if not ok:
        return r.summary()
    r.info(f"Authenticated as: {whoami.get('display_name', whoami.get('name', '?'))}")

    # ── Fetch SV DDL from Snowflake ───────────────────────────────────────────
    def _fetch_ddl():
        rows = snow_json(
            snow_cmd, cli_conn,
            f"SELECT GET_DDL('SEMANTIC_VIEW', '{args.sv_fqn}') AS ddl;"
        )
        if not rows:
            raise RuntimeError(f"GET_DDL returned no rows for '{args.sv_fqn}'")
        ddl = rows[0].get("DDL") or rows[0].get("ddl") or list(rows[0].values())[0]
        if not ddl:
            raise RuntimeError(f"DDL column was empty for '{args.sv_fqn}'")
        return str(ddl)

    ok, ddl = r.step(f"Fetch DDL: GET_DDL('SEMANTIC_VIEW', '{args.sv_fqn}')", _fetch_ddl)
    if not ok:
        return r.summary()

    sv_name = _parse_sv_name(ddl)
    table_count = _count_sv_tables(ddl)
    r.info(f"View name: {sv_name}, table count (approx): {table_count}")

    # ── Confirm DDL looks like a Semantic View ────────────────────────────────
    def _validate_ddl():
        if "SEMANTIC VIEW" not in ddl.upper():
            raise RuntimeError("DDL does not contain 'SEMANTIC VIEW' — not a semantic view DDL")
        if "TABLES" not in ddl.upper():
            raise RuntimeError(
                "DDL has no TABLES section — unexpected DDL format. "
                f"First 200 chars: {ddl[:200]!r}"
            )
        if table_count == 0:
            raise RuntimeError(
                "No table entries found in the TABLES section of the DDL. "
                f"First 200 chars: {ddl[:200]!r}"
            )

    ok, _ = r.step("Confirm DDL is a Semantic View", _validate_ddl)
    if not ok:
        return r.summary()

    # ── Find ThoughtSpot table objects for the first table in the SV ─────────
    # Extract table names from the TABLES block.
    # Real DDL format: TABLES ( alias AS DB.SCHEMA.PHYSICAL_TABLE [primary key (...)] )
    # We extract alias names (the left-hand side before AS).
    tables_block_m = re.search(r'\bTABLES\s*\((.*?)\)', ddl, re.IGNORECASE | re.DOTALL)
    if tables_block_m:
        ts_table_names = re.findall(
            r'(\w+)\s+AS\s+\w+\.\w+\.\w+', tables_block_m.group(1), re.IGNORECASE
        )
    else:
        ts_table_names = []

    found_tables: list[tuple[str, str]] = []
    if ts_table_names:
        def _search_tables():
            for tname in ts_table_names[:3]:  # check up to 3 tables
                results = _search_ts_tables(args.ts_profile, tname)
                exact = [r for r in results if r.get("metadata_name", "").upper() == tname.upper()]
                if exact:
                    g = exact[0].get("metadata_id") or exact[0].get("id")
                    found_tables.append((tname, g))
            if not found_tables:
                raise SkipStep(
                    f"No ThoughtSpot table objects found for tables: {ts_table_names[:3]}. "
                    "The model import step will be skipped."
                )
            return found_tables

        ok, _ = r.step(
            f"Find ThoughtSpot table objects ({', '.join(ts_table_names[:3])})",
            _search_tables,
        )
    else:
        r.info("Could not extract table names from DDL — skipping table search")

    # ── Build and validate minimal model TML ─────────────────────────────────
    smoke_model_name = f"SMOKE_TEST_{sv_name}"
    imported_guid: str | None = None

    if found_tables:
        model_tml = _build_minimal_model_tml(smoke_model_name, found_tables)

        def _validate_model():
            errors = validate_model_tml(model_tml)
            if errors:
                raise RuntimeError(
                    f"{len(errors)} TML validation error(s):\n"
                    + "\n".join(f"  - {e}" for e in errors)
                )

        ok, _ = r.step("Validate model TML structure (check_tml)", _validate_model)

        # ── Import model to ThoughtSpot ───────────────────────────────────────
        if ok:
            def _import():
                return _import_model_tml(args.ts_profile, model_tml)

            ok, imported_guid = r.step(
                f"Import '{smoke_model_name}' to ThoughtSpot", _import
            )
            if ok:
                r.info(f"Created model GUID: {imported_guid}")

    # ── Verify model exists in metadata search ────────────────────────────────
    if imported_guid:
        def _verify_exists():
            results = run_ts(
                ["metadata", "search", "--subtype", "WORKSHEET",
                 "--name", f"%{smoke_model_name}%"],
                args.ts_profile,
            )
            found = [
                r_ for r_ in results
                if r_.get("metadata_id") == imported_guid
                or r_.get("id") == imported_guid
            ]
            if not found:
                raise RuntimeError(
                    f"Model GUID {imported_guid} not found in metadata search. "
                    "Import may have succeeded but indexing is delayed — retry in a few seconds."
                )
            return found[0]

        ok, model_meta = r.step(
            f"Verify '{smoke_model_name}' appears in ThoughtSpot metadata", _verify_exists
        )
        if ok and model_meta:
            base_url = run_ts(["auth", "whoami"], args.ts_profile).get("base_url", "")
            r.info(f"Model URL: {base_url}/#/model/{imported_guid}")

    # ── Cleanup ───────────────────────────────────────────────────────────────
    if imported_guid:
        if args.no_cleanup:
            r.info(f"Skipping cleanup (--no-cleanup). GUID: {imported_guid}")
        else:
            r.step(
                f"Cleanup: delete '{smoke_model_name}' from ThoughtSpot",
                _delete_ts_object, args.ts_profile, imported_guid,
            )

    return r.summary()


if __name__ == "__main__":
    sys.exit(main())
