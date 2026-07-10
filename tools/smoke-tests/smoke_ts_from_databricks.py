#!/usr/bin/env python3
"""
smoke_ts_from_databricks.py — live smoke test for ts-convert-from-databricks-mv.

Verifies the full path:
  1. Databricks auth (databricks CLI)
  2. List Metric Views in a catalog
  3. Fetch a known Metric View definition via DESCRIBE TABLE EXTENDED
  4. `ts databricks parse-mv` — parse the YAML into structured JSON
  5. Derive tables.json (alias -> ThoughtSpot table name) from the parsed source/joins
  6. `ts databricks translate-formulas` — translate expressions to ThoughtSpot formulas
  7. `ts databricks build-model` (files only) — assemble + lint the Model TML
  8. (Optional, --import-model) resolve real ThoughtSpot table GUIDs, re-run
     build-model with --profile to import, verify, and clean up

Usage:
    python tools/smoke-tests/smoke_ts_from_databricks.py \\
        --dbx-profile Production \\
        --mv-fqn "demo_qsr.prayansh.ecommerce_transactions_basic_sales_metrics_view"

    # Also exercise the live ThoughtSpot import (requires the source table(s)
    # to already exist as ThoughtSpot Table objects — this smoke test does
    # NOT create them; see Step 8B of ts-convert-from-databricks-mv/SKILL.md):
    python tools/smoke-tests/smoke_ts_from_databricks.py \\
        --dbx-profile Production \\
        --mv-fqn "demo_qsr.prayansh.ecommerce_transactions_basic_sales_metrics_view" \\
        --ts-profile production --connection "APJ_DBX" --import-model

Notes:
  - The Metric View must already exist in Databricks.
  - The SQL warehouse must be on the Preview channel.
  - --import-model creates a real ThoughtSpot Model named SMOKE_{table}_MV and
    deletes it at the end (use --no-cleanup to leave it for inspection).
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Run: pip install PyYAML")
    sys.exit(1)

from _common import (
    SmokeTestResult,
    load_dbx_profile, get_dbx_warehouse_id,
    databricks_sql, dbx_sql_rows,
)


def _parse_mv_yaml(dbx_profile: str, mv_fqn: str) -> tuple[str, dict]:
    """Fetch and parse the Metric View YAML definition.

    Returns (raw_view_text, parsed_dict). raw_view_text is what gets written
    to mv.yaml and fed to `ts databricks parse-mv`; parsed_dict is kept only
    as a fail-fast PyYAML sanity check (unchanged from the pre-pipeline
    version of this step) — the CLI does the real structural parsing.
    """
    data = databricks_sql(dbx_profile, f"DESCRIBE TABLE EXTENDED {mv_fqn}")
    rows = data.get("result", {}).get("data_array", [])

    view_text = None
    mv_type = None
    for row in rows:
        if row[0] == "View Text":
            view_text = row[1]
        if row[0] == "Type":
            mv_type = row[1]

    if mv_type != "METRIC_VIEW":
        raise RuntimeError(f"Expected Type=METRIC_VIEW, got {mv_type}")
    if not view_text:
        raise RuntimeError("No View Text found in DESCRIBE output")

    return view_text, yaml.safe_load(view_text)


# ---------------------------------------------------------------------------
# `ts` CLI subprocess helper (BL-097: stdin is ALWAYS provided explicitly —
# `ts tml import`'s stdin-piped-content probe hangs forever on an open,
# non-TTY stdin that never receives data; every invocation here supplies
# stdin, even "" for commands with no payload, so no call can block).
# ---------------------------------------------------------------------------

def _run_ts(args: list[str], stdin_text: str | None = None) -> subprocess.CompletedProcess:
    """Run a `ts` CLI command through a login shell (so ~/.zshenv is sourced)."""
    return subprocess.run(
        ["bash", "-c", "source ~/.zshenv && " + " ".join(shlex.quote(a) for a in args)],
        input=stdin_text if stdin_text is not None else "",
        capture_output=True, text=True, timeout=120)


def _run_ts_json(args: list[str], stdin_text: str | None = None):
    """Run a `ts` CLI command and parse its stdout as JSON. Raises on non-zero exit."""
    result = _run_ts(args, stdin_text)
    if result.returncode != 0:
        raise RuntimeError(
            f"{' '.join(args)} failed (exit {result.returncode}):\n{result.stderr.strip()}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"{' '.join(args)} returned non-JSON output:\n{result.stdout[:300]}"
        ) from exc


# ---------------------------------------------------------------------------
# Pipeline steps: parse-mv -> tables.json -> translate-formulas -> build-model
# ---------------------------------------------------------------------------

def _run_offline_step(cmd: list[str], out_path: Path, label: str) -> dict:
    """Run an offline `ts databricks` transform (parse-mv / translate-formulas)
    and load its --output JSON file. Raises on non-zero exit (stderr carries
    the human-readable diagnostics, including any UNSUPPORTED/SKIPPED list)."""
    result = _run_ts(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"{label} failed (exit {result.returncode}):\n{result.stderr.strip()}")
    return json.loads(out_path.read_text())


def _flatten_join_aliases(joins: list) -> list[tuple[str, dict]]:
    """Pre-order walk of the parsed joins tree -> (alias_path, join_node) pairs.

    Mirrors ts_cli.databricks.mv_build_model.flatten_join_aliases: alias_path
    is dot-joined from the root; the parent of a top-level join is "source".
    """
    out: list[tuple[str, dict]] = []

    def walk(nodes: list, parent_path: str) -> None:
        for j in nodes:
            path = j["alias"] if parent_path == "source" else f"{parent_path}.{j['alias']}"
            out.append((path, j))
            walk(j.get("joins") or [], path)

    walk(joins or [], "source")
    return out


def _build_tables_map(parsed: dict) -> dict:
    """Derive {alias: TABLE_NAME} from parsed source/joins 3-part FQNs.

    Fails loud when any source (the top-level source or any join) lacks a
    3-part `parts` list — a SQL-query source or a 1/2-part FQN can't be
    turned into a bare ThoughtSpot table name offline.
    """
    def table_name(alias_path: str, source: dict | None) -> str:
        parts = (source or {}).get("parts")
        if not parts or len(parts) != 3:
            raise RuntimeError(
                f"source for '{alias_path}' has no 3-part catalog.schema.table "
                f"FQN (parts={parts!r}) — cannot derive a ThoughtSpot table name "
                "offline; resolve manually and edit tables.json"
            )
        return parts[-1].upper()

    tables = {"source": table_name("source", parsed.get("source"))}
    for alias_path, node in _flatten_join_aliases(parsed.get("joins") or []):
        tables[alias_path] = table_name(alias_path, node.get("source"))
    return tables


def _run_build_model(cmd: list[str]) -> dict:
    """Run `ts databricks build-model` and return its summary JSON.

    The summary is printed to stdout on both success AND failure (lint/
    invariant findings, or a failed import) — so parse stdout regardless of
    exit code, then raise on any non-empty finding list.
    """
    result = _run_ts(cmd)
    try:
        summary = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"ts databricks build-model returned non-JSON stdout "
            f"(exit {result.returncode}):\n{result.stdout[:300]}\n"
            f"stderr:\n{result.stderr.strip()[-500:]}"
        ) from exc
    if summary.get("invariant_findings"):
        raise RuntimeError(f"invariant_findings non-empty: {summary['invariant_findings']}")
    if summary.get("lint_findings"):
        raise RuntimeError(f"lint_findings non-empty: {summary['lint_findings']}")
    return summary


# ---------------------------------------------------------------------------
# Optional live-import leg (--import-model)
# ---------------------------------------------------------------------------

def _resolve_table_guids(r: SmokeTestResult, ts_profile: str, tables: dict) -> dict | None:
    """Search ThoughtSpot for each table alias's real Table object GUID.

    Fails naming Step 8B (`ts tables create`) as the manual precondition —
    this smoke test does NOT create tables, only verifies they already exist.
    """
    guids: dict[str, str] = {}
    for alias, table_name in tables.items():
        def _search(table_name=table_name):
            results = _run_ts_json(
                ["ts", "metadata", "search", "--profile", ts_profile,
                 "--subtype", "ONE_TO_ONE_LOGICAL", "--name", f"%{table_name}%"])
            exact = [x for x in results
                     if (x.get("metadata_name") or "").upper() == table_name.upper()]
            if not exact:
                raise RuntimeError(
                    f"Table '{table_name}' not found in ThoughtSpot (subtype "
                    "ONE_TO_ONE_LOGICAL). This smoke test does NOT create tables "
                    "— run Step 8B (`ts tables create`) in "
                    "ts-convert-from-databricks-mv/SKILL.md first, then re-run "
                    "with --import-model."
                )
            if len(exact) > 1:
                raise RuntimeError(
                    f"Table '{table_name}' is ambiguous — {len(exact)} exact-name "
                    "matches found. Disambiguate manually (see Step 8A) before "
                    "running --import-model."
                )
            return exact[0]["metadata_id"]

        ok, guid = r.step(
            f"Resolve ThoughtSpot table GUID for '{table_name}' (alias '{alias}')",
            _search)
        if not ok:
            return None
        guids[alias] = guid
    return guids


def _run_import_leg(
    r: SmokeTestResult, args: argparse.Namespace, tables: dict,
    parsed_path: Path, translated_path: Path, tmp_path: Path, model_name: str,
) -> None:
    """Resolve real table GUIDs, import the model, verify, and clean up.

    Cleanup always runs once a model has been imported — even if an earlier
    verification step in this leg failed — so no SMOKE_* object is ever left
    behind. A cleanup failure is itself a smoke-test failure.
    """
    guids = _resolve_table_guids(r, args.ts_profile, tables)
    if guids is None:
        return

    enriched_tables = {alias: {"name": name, "fqn": guids[alias]}
                       for alias, name in tables.items()}
    enriched_path = tmp_path / "tables.import.json"
    enriched_path.write_text(json.dumps(enriched_tables, indent=2))

    out_import_dir = tmp_path / "out_import"

    def _import_step():
        summary = _run_build_model(
            ["ts", "databricks", "build-model",
             "--parsed", str(parsed_path), "--translated", str(translated_path),
             "--tables", str(enriched_path), "--connection", args.connection,
             "--model-name", model_name, "--output-dir", str(out_import_dir),
             "--profile", args.ts_profile])
        if summary.get("import_status") != "imported" or not summary.get("model_guid"):
            raise RuntimeError(
                f"import did not succeed: import_status="
                f"{summary.get('import_status')!r} error={summary.get('import_error')!r}"
            )
        return summary

    ok, import_summary = r.step(
        f"ts databricks build-model --profile {args.ts_profile} -> import '{model_name}'",
        _import_step)
    if not ok:
        # The import step can fail AFTER a model was actually created in
        # ThoughtSpot — e.g. a PARTIAL import that created the object but
        # whose GUID extraction failed, so we have no model_guid to target
        # a direct delete. Do a best-effort name-scoped sweep so no SMOKE_*
        # object is left behind. This must not clear the import failure
        # already recorded in r.failures above.
        if args.no_cleanup:
            r.info(f"Skipping cleanup sweep (--no-cleanup). Model name: {model_name}")
        else:
            def _cleanup_sweep():
                results = _run_ts_json(
                    ["ts", "metadata", "search", "--profile", args.ts_profile,
                     "--name", f"%{model_name}%"])
                exact = [x for x in results
                         if (x.get("metadata_name") or "").upper() == model_name.upper()]
                if not exact:
                    r.info(f"No leaked '{model_name}' object found in metadata search")
                    return
                for item in exact:
                    guid = item["metadata_id"]
                    _run_ts_json(
                        ["ts", "metadata", "delete", guid, "--profile", args.ts_profile])
                    r.info(f"Deleted leaked model '{model_name}' (GUID {guid})")

            r.step("cleanup sweep (import failed)", _cleanup_sweep)
        return

    model_guid = import_summary["model_guid"]
    r.info(f"Imported model GUID: {model_guid}")
    expected_cols = (len(import_summary["columns"]["attributes"])
                      + len(import_summary["columns"]["measures"]))

    try:
        def _verify_search():
            results = _run_ts_json(
                ["ts", "metadata", "search", "--profile", args.ts_profile,
                 "--name", f"%{model_name}%"])
            found = [x for x in results if x.get("metadata_id") == model_guid]
            if not found:
                raise RuntimeError(
                    f"Model GUID {model_guid} not found via metadata search "
                    f"for '{model_name}'"
                )

        r.step(f"Verify '{model_name}' appears in metadata search", _verify_search)

        def _verify_export():
            items = _run_ts_json(
                ["ts", "tml", "export", model_guid, "--profile", args.ts_profile, "--parse"])
            items = items if isinstance(items, list) else [items]
            model_item = next((it for it in items if it.get("type") == "model"), None)
            if model_item is None:
                raise RuntimeError(f"No model TML found in export result for {model_guid}")
            cols = model_item["tml"]["model"].get("columns", [])
            if len(cols) != expected_cols:
                raise RuntimeError(
                    f"Column count mismatch: export has {len(cols)}, "
                    f"build-model summary expects {expected_cols} "
                    f"({len(import_summary['columns']['attributes'])} attribute(s) + "
                    f"{len(import_summary['columns']['measures'])} measure(s))"
                )
            return len(cols)

        ok, col_count = r.step(
            f"Verify exported column count == summary ({expected_cols})", _verify_export)
        if ok:
            r.info(f"Exported model has {col_count} column(s)")
    finally:
        if args.no_cleanup:
            r.info(f"Skipping cleanup (--no-cleanup). Model GUID: {model_guid}")
        else:
            def _cleanup():
                _run_ts_json(
                    ["ts", "metadata", "delete", model_guid, "--profile", args.ts_profile])
                r.info(f"Deleted model GUID: {model_guid}")

            r.step(f"Cleanup: delete '{model_name}' (GUID {model_guid})", _cleanup)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dbx-profile", required=True,
                        help="Databricks profile name from ~/.claude/databricks-profiles.json")
    parser.add_argument("--mv-fqn", required=True,
                        help="Fully qualified Metric View name (catalog.schema.view)")
    parser.add_argument("--ts-profile", default=None,
                        help="ThoughtSpot profile name — required with --import-model")
    parser.add_argument("--connection", default=None,
                        help="ThoughtSpot connection display name — required with "
                             "--import-model (the files-only pipeline leg uses a "
                             "placeholder instead)")
    parser.add_argument("--import-model", action="store_true",
                        help="Also resolve real ThoughtSpot table GUIDs, import the "
                             "model live, verify it, and clean up (requires "
                             "--ts-profile and --connection)")
    parser.add_argument("--no-cleanup", action="store_true",
                        help="Skip deleting the imported model (--import-model leg only)")
    args = parser.parse_args()

    if args.import_model and (not args.ts_profile or not args.connection):
        parser.error("--import-model requires --ts-profile and --connection")

    r = SmokeTestResult()
    print(f"\nSmoke test: ts-convert-from-databricks-mv")
    print(f"  MV: {args.mv_fqn}")
    print()

    # Step 1: Databricks auth
    ok, profile = r.step("Load Databricks profile",
                         load_dbx_profile, args.dbx_profile)
    if not ok:
        return r.summary()

    ok, wh_id = r.step("Extract warehouse ID",
                        get_dbx_warehouse_id, profile)
    if not ok:
        return r.summary()
    r.info(f"Warehouse ID: {wh_id}")

    # Step 2: Test SQL connectivity
    ok, _ = r.step("Test SQL connectivity (SELECT 1)",
                    databricks_sql, args.dbx_profile, "SELECT 1 AS test")
    if not ok:
        return r.summary()

    # Step 3: List Metric Views
    parts = args.mv_fqn.split(".")
    catalog = parts[0] if len(parts) >= 3 else ""

    def list_mvs():
        rows = dbx_sql_rows(
            args.dbx_profile,
            f"SELECT table_catalog, table_schema, table_name "
            f"FROM system.information_schema.tables "
            f"WHERE table_type = 'METRIC_VIEW' AND table_catalog = '{catalog}'"
        )
        if not rows:
            raise RuntimeError(f"No Metric Views found in catalog '{catalog}'")
        return rows

    ok, mv_list = r.step(f"List Metric Views in '{catalog}'", list_mvs)
    if ok:
        r.info(f"Found {len(mv_list)} Metric View(s)")

    # Step 4: Fetch and parse MV definition (raw YAML text + PyYAML sanity check)
    ok, fetched = r.step("Fetch and parse MV YAML",
                         _parse_mv_yaml, args.dbx_profile, args.mv_fqn)
    if not ok:
        return r.summary()
    view_text, mv_def = fetched
    r.info(f"Version: {mv_def.get('version')}")

    # Steps 5+: the CLI pipeline (parse-mv -> tables.json -> translate-formulas
    # -> build-model), run inside a temp working directory.
    with tempfile.TemporaryDirectory(prefix="smoke_ts_from_databricks_") as tmp:
        tmp_path = Path(tmp)
        mv_yaml_path = tmp_path / "mv.yaml"
        mv_yaml_path.write_text(view_text)

        parsed_path = tmp_path / "parsed.json"

        def _parse_mv_step():
            parsed = _run_offline_step(
                ["ts", "databricks", "parse-mv", str(mv_yaml_path),
                 "--output", str(parsed_path)],
                parsed_path, "ts databricks parse-mv")
            if parsed.get("unsupported"):
                raise RuntimeError(
                    f"{len(parsed['unsupported'])} unsupported construct(s): "
                    f"{json.dumps(parsed['unsupported'])[:500]}"
                )
            return parsed

        ok, parsed = r.step("ts databricks parse-mv", _parse_mv_step)
        if not ok:
            return r.summary()
        r.info(
            f"Parsed MV v{parsed.get('version')}: {len(parsed['dimensions'])} "
            f"dimension(s), {len(parsed['measures'])} measure(s), "
            f"{len(parsed['joins'])} top-level join(s)"
        )

        tables_path = tmp_path / "tables.json"

        def _tables_step():
            tables = _build_tables_map(parsed)
            tables_path.write_text(json.dumps(tables, indent=2))
            return tables

        ok, tables = r.step("Derive tables.json from parsed source/joins", _tables_step)
        if not ok:
            return r.summary()
        r.info(f"tables.json: {json.dumps(tables)}")

        translated_path = tmp_path / "translated.json"

        def _translate_step():
            return _run_offline_step(
                ["ts", "databricks", "translate-formulas",
                 "--input", str(parsed_path), "--tables", str(tables_path),
                 "--output", str(translated_path)],
                translated_path, "ts databricks translate-formulas")

        ok, translated = r.step("ts databricks translate-formulas", _translate_step)
        if not ok:
            return r.summary()
        stats = translated.get("stats", {})
        r.info(
            f"Translated {stats.get('translated')}/{stats.get('total')} "
            f"({stats.get('skipped')} skipped)"
        )
        if translated.get("skipped"):
            r.info(f"Skipped: {json.dumps(translated['skipped'])[:300]}")

        source_table = tables["source"]
        model_name = f"SMOKE_{source_table}_MV"
        out_files_dir = tmp_path / "out_files"

        def _build_files_step():
            summary = _run_build_model(
                ["ts", "databricks", "build-model",
                 "--parsed", str(parsed_path), "--translated", str(translated_path),
                 "--tables", str(tables_path), "--connection", "SMOKE_PLACEHOLDER",
                 "--model-name", model_name, "--output-dir", str(out_files_dir)])
            model_file = Path(summary["model_file"])
            if not model_file.exists():
                raise RuntimeError(f"model file not written: {model_file}")
            return summary

        ok, files_summary = r.step(
            f"ts databricks build-model (files only) -> {model_name}", _build_files_step)
        if ok:
            n_attrs = len(files_summary["columns"]["attributes"])
            n_meas = len(files_summary["columns"]["measures"])
            r.info(
                f"Model TML: {n_attrs} attribute(s), {n_meas} measure(s), "
                f"{files_summary['formula_count']} formula(s) -> "
                f"{files_summary['model_file']}"
            )

        # Step 8 (optional): live import leg. Gated on the files-only build
        # succeeding first — it is the canary that the assembled TML is
        # structurally sound before attempting a real import.
        if ok and args.import_model:
            print()
            print("  -- Live import leg (--import-model) --")
            _run_import_leg(r, args, tables, parsed_path, translated_path,
                            tmp_path, model_name)

    return r.summary()


if __name__ == "__main__":
    sys.exit(main())
