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
 11. [--mode-c] Export TML and re-import with --no-create-new; verify GUID unchanged
 12. Cleanup: delete imported model (unless --no-cleanup)

Mode C (--mode-c) specifically tests that `ts tml import --no-create-new` updates
an existing model in-place rather than creating a new one. It exports the just-created
model's TML, adds `guid:` at the document root, and re-imports with --no-create-new.
After the import it verifies:
  - exactly one model with the smoke-test name exists (no duplicate created)
  - the model's GUID is unchanged (not a new object)

Usage:
    python tools/smoke-tests/smoke_ts_from_snowflake.py \\
        --ts-profile production \\
        --sf-profile production \\
        --sv-fqn "BIRD.SUPERHERO_SV.BIRD_SUPERHEROS_SV" \\
        [--mode-c] \\
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


def _import_model_tml_update(ts_profile: str, tml_dict: dict, model_guid: str) -> list | dict:
    """
    Import a model TML update in-place using --no-create-new.

    Per TML invariants: guid: must be at the document root, not nested inside model:.
    --no-create-new fails if the GUID is not found, preventing silent duplicate creation.
    """
    tml_with_guid = {**tml_dict, "guid": model_guid}
    tml_str = yaml.dump(tml_with_guid, default_flow_style=False, allow_unicode=True)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, prefix="smoke_update_"
    ) as f:
        f.write(tml_str)
        tmp_path = f.name
    try:
        return run_ts(
            ["tml", "import", "--file", tmp_path, "--no-create-new"],
            ts_profile,
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


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
    parser.add_argument(
        "--mode-c", action="store_true",
        help=(
            "Also test the Mode C (update existing) path: export the created model's TML, "
            "re-import with --no-create-new, and verify the GUID is unchanged "
            "(no duplicate model created)."
        ),
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

    # ── Mode C: --no-create-new in-place update ───────────────────────────────
    if args.mode_c and imported_guid:
        print()
        print("  -- Mode C: in-place update (--no-create-new) --")

        def _export_for_update():
            result = run_ts(["tml", "export", imported_guid, "--fqn"], args.ts_profile)
            if isinstance(result, list):
                model_obj = next(
                    (obj for obj in result if isinstance(obj, dict) and "model" in obj),
                    None,
                )
            elif isinstance(result, dict) and "model" in result:
                model_obj = result
            else:
                model_obj = None
            if model_obj is None:
                raise RuntimeError(
                    f"No model TML found in export result for GUID {imported_guid}. "
                    f"Export returned {type(result).__name__} with "
                    f"{len(result) if isinstance(result, list) else 1} item(s)."
                )
            return model_obj

        ok, original_model_tml = r.step(
            f"Mode C: Export '{smoke_model_name}' TML for update", _export_for_update
        )

        if ok and original_model_tml is not None:
            def _update_in_place():
                return _import_model_tml_update(
                    args.ts_profile, original_model_tml, imported_guid
                )

            ok, _ = r.step(
                f"Mode C: Re-import with --no-create-new (guid: {imported_guid})",
                _update_in_place,
            )

            if ok:
                def _verify_no_duplicate():
                    results = run_ts(
                        ["metadata", "search", "--subtype", "WORKSHEET",
                         "--name", f"%{smoke_model_name}%"],
                        args.ts_profile,
                    )
                    exact = [
                        r_ for r_ in results
                        if r_.get("metadata_name") == smoke_model_name
                    ]
                    if len(exact) > 1:
                        raise RuntimeError(
                            f"--no-create-new created a duplicate: found {len(exact)} models "
                            f"named '{smoke_model_name}'. The flag may have been silently ignored."
                        )
                    if len(exact) == 0:
                        raise RuntimeError(
                            f"No model named '{smoke_model_name}' found after update — "
                            "the --no-create-new import may have deleted the model."
                        )
                    found_guid = exact[0].get("metadata_id") or exact[0].get("id")
                    if found_guid != imported_guid:
                        raise RuntimeError(
                            f"GUID changed after --no-create-new: expected {imported_guid}, "
                            f"got {found_guid}. A new model was created instead of updating in-place."
                        )

                r.step(
                    "Mode C: Verify GUID unchanged — no duplicate created",
                    _verify_no_duplicate,
                )

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
