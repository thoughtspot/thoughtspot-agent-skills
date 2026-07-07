"""ts tableau — Tableau Server/Cloud REST API commands."""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Optional

import typer

from ts_cli.tableau.client import TableauClient, _resolve_tableau_profile


# ---------------------------------------------------------------------------
# Typer commands
# ---------------------------------------------------------------------------

app = typer.Typer(help="Tableau Server/Cloud REST API commands.")

_profile_option = typer.Option(
    None, "--profile", "-p",
    help="Tableau profile name (default: first profile in ~/.claude/tableau-profiles.json)",
)


@app.command()
def signin(
    profile: Optional[str] = _profile_option,
) -> None:
    """Sign in to Tableau Server/Cloud and verify credentials."""
    p = _resolve_tableau_profile(profile)
    client = TableauClient(p)
    result = client.signin()
    print(json.dumps(result))


@app.command()
def datasources(
    profile: Optional[str] = _profile_option,
    name: Optional[str] = typer.Option(None, "--name", "-n",
                                        help="Exact datasource name filter"),
) -> None:
    """List published datasources on the Tableau site."""
    p = _resolve_tableau_profile(profile)
    client = TableauClient(p)
    result = client.datasources(name_filter=name)
    print(json.dumps(result))


@app.command()
def datasource(
    datasource_id: str = typer.Argument(..., help="Datasource UUID"),
    profile: Optional[str] = _profile_option,
    fields: bool = typer.Option(False, "--fields", "-f",
                                 help="Include field metadata via VizQL read-metadata"),
) -> None:
    """Get datasource details, optionally with field metadata."""
    p = _resolve_tableau_profile(profile)
    client = TableauClient(p)
    client.signin()

    path = f"{client._base_path()}/datasources/{datasource_id}"
    resp = client.request("GET", path)
    ds_info = resp.json()

    if fields:
        field_list = client.datasource_fields(datasource_id)
        ds_info["fields"] = field_list

    print(json.dumps(ds_info))


@app.command()
def download(
    datasource_id: str = typer.Argument(..., help="Datasource UUID"),
    profile: Optional[str] = _profile_option,
    output_dir: str = typer.Option(".", "--output-dir", "-o",
                                    help="Directory to save downloaded content"),
) -> None:
    """Download a published datasource's content (TDSX) and extract data files.

    Downloads the datasource, extracts the TDSX archive, and validates any CSV
    files for row integrity (column count consistency, corrupt lines).
    """
    p = _resolve_tableau_profile(profile)
    client = TableauClient(p)
    result = client.download_datasource(datasource_id, Path(output_dir))
    print(json.dumps(result, indent=2))


def _twb_root(twb_file: str) -> ET.Element:
    """Load the root XML element from a .twb or .twbx path (zip-aware)."""
    p = Path(twb_file)
    if p.suffix.lower() == ".twbx":
        with zipfile.ZipFile(p) as z:
            name = next(n for n in z.namelist() if n.endswith(".twb"))
            return ET.parse(z.open(name)).getroot()
    return ET.parse(str(p)).getroot()


@app.command("parse")
def parse_cmd(
    twb_file: str = typer.Argument(..., help="Path to .twb or .twbx file"),
    output_file: str = typer.Option(..., "--output", "-o",
                                     help="Output parsed JSON path"),
) -> None:
    """Parse a TWB into structured JSON for SKILL.md Step 3 to consume.

    Composes the existing tables/columns/joins/calcs parser with the blend
    graph, table-calc addressing, and per-datasource orphan-calc detection
    extractors, so downstream steps read fields from this JSON instead of
    re-deriving them by hand-parsing the TWB XML. Handles .twbx (zip) the
    same way ``parse_twb`` does.
    """
    from ts_cli.model_builder import (
        build_blend_plan,
        detect_orphan_calcs,
        extract_blends,
        extract_table_calc_addressing,
        parse_twb,
    )

    twb_path = Path(twb_file)
    if not twb_path.exists():
        typer.echo(f"File not found: {twb_file}", err=True)
        raise SystemExit(1)

    parsed = parse_twb(twb_path)
    root = _twb_root(twb_file)
    parsed["blends"] = extract_blends(root)
    parsed["table_calc_addressing"] = extract_table_calc_addressing(root)
    for ds in parsed["datasources"]:
        ds["orphan_calcs"] = detect_orphan_calcs(ds)
    parsed["blend_plan"] = build_blend_plan(parsed["blends"], parsed["datasources"])

    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    Path(output_file).write_text(json.dumps(parsed, indent=2))

    typer.echo(
        f"Parsed {len(parsed['datasources'])} datasource(s), "
        f"{len(parsed['blends'])} blend edge-set(s) -> {output_file}",
        err=True,
    )


@app.command("translate-formulas")
def translate_formulas_cmd(
    input_file: str = typer.Option(..., "--input", "-i",
                                    help="classification.json from TWB parse"),
    output_file: str = typer.Option(..., "--output", "-o",
                                     help="Output translated formulas JSON"),
    tables: Optional[str] = typer.Option(None, "--tables", "-t",
                                          help="Comma-separated table names for this model"),
    table_columns: Optional[str] = typer.Option(None, "--table-columns",
                                                 help="JSON file mapping column→table"),
    parameters_file: Optional[str] = typer.Option(None, "--parameters",
                                                   help="JSON file with parameter definitions"),
    param_map_file: Optional[str] = typer.Option(None, "--param-map",
                                                  help="JSON file mapping internal param names→captions"),
    calc_map_file: Optional[str] = typer.Option(None, "--calc-map",
                                                 help="JSON file mapping [Calculation_NNN]→caption"),
    datasource: Optional[str] = typer.Option(None, "--datasource", "-d",
                                              help="Filter to a single datasource name"),
    csq_map_file: Optional[str] = typer.Option(None, "--csq-map",
                                                help="JSON file mapping Custom SQL Query aliases→table names"),
    date_columns_opt: Optional[str] = typer.Option(None, "--date-columns",
                                                    help="Comma-separated date column names for arithmetic rewrite"),
) -> None:
    """Translate Tableau calculated fields to ThoughtSpot formula syntax.

    Reads classification.json (from the TWB parse), applies the ordered translation
    pipeline, resolves cross-references via dependency DAG, and outputs a JSON file
    with translated formulas ready for TML generation.
    """
    from ts_cli.tableau_translate import translate_formulas

    input_path = Path(input_file)
    if not input_path.exists():
        typer.echo(f"Input file not found: {input_file}", err=True)
        raise SystemExit(1)

    classification = json.loads(input_path.read_text())

    # Filter to datasource if specified
    if datasource:
        classification = [f for f in classification if f.get("datasource") == datasource]
        typer.echo(f"Filtered to datasource '{datasource}': {len(classification)} formulas", err=True)

    # Load scoped columns map
    scoped_columns: dict[str, str] = {}
    if table_columns:
        tc_path = Path(table_columns)
        if tc_path.exists():
            scoped_columns = json.loads(tc_path.read_text())
    elif tables:
        typer.echo("Warning: --tables without --table-columns; column scoping disabled", err=True)

    # Load parameters
    parameters: list[dict] = []
    if parameters_file:
        p_path = Path(parameters_file)
        if p_path.exists():
            parameters = json.loads(p_path.read_text())

    # Load param name map (internal name → caption)
    param_map: dict[str, str] = {}
    if param_map_file:
        pm_path = Path(param_map_file)
        if pm_path.exists():
            param_map = json.loads(pm_path.read_text())

    # Load calc ID map ([Calculation_NNN] → caption)
    calc_id_map: dict[str, str] | None = None
    if calc_map_file:
        cm_path = Path(calc_map_file)
        if cm_path.exists():
            calc_id_map = json.loads(cm_path.read_text())

    # Load Custom SQL Query alias map
    csq_to_table: dict[str, str] | None = None
    if csq_map_file:
        csq_path = Path(csq_map_file)
        if csq_path.exists():
            csq_to_table = json.loads(csq_path.read_text())

    # Parse date columns
    date_columns: set[str] | None = None
    if date_columns_opt:
        date_columns = {c.strip() for c in date_columns_opt.split(",") if c.strip()}

    result = translate_formulas(
        formulas=classification,
        scoped_columns=scoped_columns,
        param_map=param_map,
        parameters=parameters,
        calc_id_map=calc_id_map,
        csq_to_table=csq_to_table,
        date_columns=date_columns,
    )

    output_path = Path(output_file)
    output_path.write_text(json.dumps(result, indent=2))

    typer.echo(
        f"Translated: {result['stats']['translated']}/{result['stats']['total']} formulas\n"
        f"Skipped: {result['stats']['skipped']} "
        f"(levels: {json.dumps(result['stats']['levels'])})",
        err=True,
    )

    print(json.dumps(result["stats"]))


@app.command("classify-formulas")
def classify_formulas_cmd(
    input_file: str = typer.Option(..., "--input", "-i",
                                    help="parsed.json (from `ts tableau parse`) or a JSON list of calc-field dicts"),
    output_file: str = typer.Option(..., "--output", "-o",
                                     help="Output classification JSON path"),
    datasource: Optional[str] = typer.Option(None, "--datasource", "-d",
                                              help="Limit to one datasource name"),
) -> None:
    """Classify calculated fields into translation tiers.

    The translatable verdict is delegated to the translate pipeline (via
    classify_formulas), so audit-mode tier counts and migrate-mode translation
    results can never diverge.
    """
    from ts_cli.tableau.classify import classify_formulas, classify_workbook

    input_path = Path(input_file)
    if not input_path.exists():
        typer.echo(f"Input file not found: {input_file}", err=True)
        raise SystemExit(1)

    data = json.loads(input_path.read_text())

    if isinstance(data, dict) and "datasources" in data:
        # Parsed-workbook input: classify PER DATASOURCE (each is its own model),
        # so a calc name shared across datasources is tiered against its own
        # expression and per-datasource totals reconcile. See classify_workbook.
        result = classify_workbook(data, datasource=datasource)
        n_formulas = sum(len(d["formulas"]) for d in result["datasources"])
        n_ds = len(result["datasources"])
        summary = f"Classified {n_formulas} formula(s) across {n_ds} datasource(s)"
    else:
        # Bare list (e.g. Step 5b's translate-formulas input, already one datasource).
        result = classify_formulas(data)
        n_formulas = len(result["formulas"])
        summary = f"Classified {n_formulas} formula(s)"

    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    Path(output_file).write_text(json.dumps(result, indent=2))

    typer.echo(f"{summary} -> {output_file}", err=True)

    print(json.dumps(result["tier_counts"]))


def _export_model_tml(existing_guid: str, profile: str) -> dict:
    """Export an existing model's TML via the ts CLI (subprocess I/O)."""
    import subprocess

    typer.echo(f"\n  Exporting existing model {existing_guid}...", err=True)
    export_proc = subprocess.run(
        ["ts", "tml", "export", existing_guid, "--profile", profile, "--parse"],
        capture_output=True, text=True,
    )
    if export_proc.returncode != 0:
        typer.echo(f"  Export failed: {export_proc.stderr[:200]}", err=True)
        raise SystemExit(1)
    existing_tml = json.loads(export_proc.stdout)[0]["tml"]
    typer.echo(
        f"  Existing model: {len(existing_tml['model'].get('formulas', []))} formulas",
        err=True,
    )
    return existing_tml


def _reconcile_plan(cleaned_cols: list[dict], target_cols: set[str]) -> dict:
    """Pure planning helper for --reconcile-plan: partition emitted columns by
    whether the target table already has them, and suggest renames for the rest.
    """
    from ts_cli.tableau.reconcile import suggest_column_mappings

    present = [c["db_column_name"] for c in cleaned_cols if c["db_column_name"] in target_cols]
    absent = [c["db_column_name"] for c in cleaned_cols if c["db_column_name"] not in target_cols]
    suggestions = suggest_column_mappings(absent, target_cols)
    mapped_from = {s["from"] for s in suggestions}
    return {
        "target_columns": len(target_cols),
        "matched": present,
        "suggested_mappings": suggestions,
        "unmatched_drop": [a for a in absent if a not in mapped_from],
    }


def _fetch_target_columns(guid: str, profile: str) -> set[str]:
    """Export an existing table object and return its logical column names
    (consultant/stand-in-view reconcile case: --reconcile-table).

    Matches the subprocess + --parse pattern already used by
    _export_model_tml: without --parse, `ts tml export` returns a raw YAML
    edoc string, which is not directly JSON-parseable; --parse returns a
    pre-parsed TML dict under the "tml" key.
    """
    import subprocess

    proc = subprocess.run(
        ["ts", "tml", "export", guid, "--profile", profile, "--parse"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        typer.echo(f"reconcile: failed to export target table {guid}: {proc.stderr[:200]}", err=True)
        raise SystemExit(1)
    tml = json.loads(proc.stdout)[0]["tml"]
    tbl = tml.get("table", {})
    return {c["name"] for c in tbl.get("columns", [])}


def _load_column_name_map(column_name_map: Optional[str]) -> dict[str, str]:
    """Load and validate the --column-name-map JSON file; exits on a bad
    path, a chained mapping, or a convergent mapping. See
    reconcile.validate_name_map for why both shapes are rejected.
    """
    if not column_name_map:
        return {}
    cnm_path = Path(column_name_map)
    if not cnm_path.exists():
        typer.echo(f"Column name map file not found: {column_name_map}", err=True)
        raise SystemExit(1)
    name_map: dict[str, str] = json.loads(cnm_path.read_text())
    from ts_cli.tableau.reconcile import validate_name_map

    error = validate_name_map(name_map)
    if error:
        typer.echo(error, err=True)
        raise SystemExit(1)
    return name_map


def _translate_and_validate(
    ds: dict,
    resolved_calcs: list[dict],
    scoped_columns: dict,
    parsed: dict,
) -> tuple[list, list, list]:
    """Translate a datasource's calculated fields and run pre-import validation.

    Returns (translated, skipped, validation_issues); echoes progress to stderr.
    """
    from ts_cli.tableau_translate import translate_formulas, validate_pre_import

    translate_result = translate_formulas(
        formulas=resolved_calcs,
        scoped_columns=scoped_columns,
        param_map=parsed["param_map"],
        parameters=parsed["parameters"],
        calc_id_map=ds["calc_map"],
    )

    translated = translate_result["translated"]
    skipped = translate_result["skipped"]
    typer.echo(
        f"  Translated: {len(translated)}/{len(ds['calculated_fields'])} formulas",
        err=True,
    )
    if skipped:
        typer.echo(f"  Skipped: {len(skipped)}", err=True)
        for s in skipped[:5]:
            typer.echo(f"    - {s['name']}: {s['reason'][:80]}", err=True)

    # Pre-import validation (catches issues before ThoughtSpot rejects them)
    col_names = {c["name"] for c in ds["columns"]}
    formula_name_set = {f["name"] for f in translated}
    validation_issues = validate_pre_import(translated, col_names, formula_name_set)
    if validation_issues:
        typer.echo(f"  Validation warnings: {len(validation_issues)}", err=True)
        for vi in validation_issues[:10]:
            for w in vi["warnings"]:
                typer.echo(f"    ! {vi['name']}: {w}", err=True)

    return translated, skipped, validation_issues


def _collect_cascade_victims(
    merged: dict, bad_name: str, err_detail: str
) -> tuple[list[str], dict[str, str]]:
    """Return the failed formula plus the transitive closure of formulas that
    reference it, with a drop reason for each (breadth-first to a fixpoint)."""
    to_drop = [bad_name]
    reasons = {bad_name: err_detail}
    seen = {bad_name}
    i = 0
    while i < len(to_drop):
        victim = to_drop[i]
        i += 1
        token = f"[formula_{victim}]"
        for fm in merged["model"].get("formulas", []):
            dep = fm["name"]
            if dep not in seen and token in fm.get("expr", ""):
                seen.add(dep)
                to_drop.append(dep)
                reasons[dep] = f"depends on dropped formula '{victim}'"
    return to_drop, reasons


def _migrate_missing_parameters(
    existing_tml: dict, parameters: Optional[list]
) -> list[str]:
    """Add TWB parameters not already on the model. Returns names added.

    Parameters must exist on the model BEFORE formula import — a formula that
    references a parameter the model doesn't have is unresolvable and gets
    dropped. Mutates ``existing_tml`` in place.
    """
    if not parameters:
        return []
    model = existing_tml.setdefault("model", {})
    existing_params = model.setdefault("parameters", [])
    have = {p.get("name") for p in existing_params}
    added = [p for p in parameters if p.get("name") not in have]
    existing_params.extend(added)
    return [p["name"] for p in added]


def _import_with_retry(
    merged: dict,
    ds: dict,
    existing_guid: str,
    profile: str,
    max_retries: int,
    result: dict,
) -> None:
    """Import merged TML, dropping failing formulas and retrying (subprocess I/O).

    Mutates ``merged`` (formulas dropped on error), ``merged["_merge_stats"]``,
    and ``result`` (import_status / updated_model_guid / dropped list).
    """
    import subprocess

    from ts_cli.tableau.build_model import (
        extract_imported_guid,
        parse_import_error,
        remove_formula,
    )

    stats = merged["_merge_stats"]
    expr_by_fid = {f["id"]: f.get("expr", "") for f in merged["model"]["formulas"]}
    original_by_name = {
        c.get("caption", c.get("name", "")): c.get("formula", "")
        for c in ds.get("calculated_fields", [])
    }
    dropped_on_import: list[dict] = []
    for _attempt in range(max_retries):
        import_tml = {k: v for k, v in merged.items() if not k.startswith("_")}
        tml_str = json.dumps(import_tml)
        import_proc = subprocess.run(
            ["ts", "tml", "import", "--profile", profile, "--policy", "ALL_OR_NONE"],
            input=json.dumps([tml_str]),
            capture_output=True, text=True,
        )
        if import_proc.returncode != 0:
            typer.echo(f"  Import failed: {import_proc.stderr[:200]}", err=True)
            raise SystemExit(1)
        import_result = json.loads(import_proc.stdout)
        status = import_result[0]["response"]["status"]["status_code"]
        if status == "OK":
            result["import_status"] = status
            result["updated_model_guid"] = (
                extract_imported_guid(import_result) or existing_guid
            )
            typer.echo(f"  Import: OK", err=True)
            break
        msg = import_result[0]["response"]["status"].get("error_message", "")
        parsed_err = parse_import_error(msg)
        if parsed_err is None:
            result["import_status"] = status
            result["import_error"] = msg
            typer.echo(f"  Import: {status} — {msg[:200]}", err=True)
            break
        bad_name, err_detail = parsed_err
        typer.echo(f"  Import error on '{bad_name}': {err_detail} — dropping", err=True)
        # Drop the failing formula, then cascade-drop any formula that
        # references it — in THIS cycle — so a failed root (e.g. a date-window
        # formula) doesn't cost one import round-trip per downstream dependent.
        to_drop, reasons = _collect_cascade_victims(merged, bad_name, err_detail)
        for victim in to_drop:
            dropped_on_import.append({
                "name": victim,
                "expr": expr_by_fid.get(f"formula_{victim}", ""),
                "error": reasons[victim],
                "original_tableau": original_by_name.get(victim, ""),
            })
            remove_formula(merged, victim)
            stats["added"] -= 1
        if len(to_drop) > 1:
            typer.echo(
                f"    ↳ cascade-dropped {len(to_drop) - 1} dependent formula(s)",
                err=True,
            )
        if stats["added"] <= 0:
            typer.echo("  All new formulas dropped — nothing to import", err=True)
            result["import_status"] = "SKIPPED"
            break
    else:
        result["import_status"] = "ERROR"
        result["import_error"] = "Max retry attempts exceeded"
    if dropped_on_import:
        result["formulas_dropped_on_import"] = dropped_on_import
        result["formulas_added"] = stats["added"]


def _merge_flow(
    ds: dict,
    name: str,
    existing_guid: str,
    existing_tml: dict,
    cleaned_formulas: list[dict],
    translated: list,
    skipped: list,
    validation_issues: list,
    profile: str,
    dry_run: bool,
    max_retries: int,
    column_name_map: Optional[dict] = None,
    parameters: Optional[list] = None,
) -> dict:
    """Merge translated formulas into an existing model and import it."""
    from ts_cli.model_builder import (
        filter_unresolvable_formulas,
        merge_formulas_into_model,
    )
    from ts_cli.tableau.build_model import (
        collect_existing_model_context,
        prepare_formulas_for_merge,
    )
    from ts_cli.tableau.reconcile import rewrite_formula_refs

    added_params = _migrate_missing_parameters(existing_tml, parameters)
    if added_params:
        typer.echo(
            f"  Added {len(added_params)} parameter(s) to model: "
            f"{', '.join(added_params)}",
            err=True,
        )

    if column_name_map:
        n_rewritten = rewrite_formula_refs(cleaned_formulas, column_name_map)
        if n_rewritten:
            typer.echo(
                f"  Applied column-name map to {n_rewritten} formulas "
                f"({len(column_name_map)} mappings)",
                err=True,
            )

    ctx = collect_existing_model_context(existing_tml)
    formula_dicts, bare_fixed = prepare_formulas_for_merge(cleaned_formulas, ctx)
    if bare_fixed:
        typer.echo(f"  Fixed bare refs in {bare_fixed} formulas", err=True)

    kept, dropped_names = filter_unresolvable_formulas(
        formula_dicts, ctx["existing_ids"], ctx["existing_cols"],
        ctx["formula_names"], ctx["param_names"],
    )
    typer.echo(
        f"  Filter: {len(kept)} kept, {len(dropped_names)} dropped",
        err=True,
    )
    if dropped_names:
        for dn in dropped_names[:10]:
            typer.echo(f"    - {dn}", err=True)

    merged = merge_formulas_into_model(existing_tml, kept)
    stats = merged["_merge_stats"]
    typer.echo(
        f"  Merge: added={stats['added']}, skipped={stats['skipped_existing']}",
        err=True,
    )
    if stats.get("added_names"):
        for an in stats["added_names"]:
            typer.echo(f"    + {an}", err=True)

    result = {
        "datasource": ds["name"],
        "model_name": name,
        "existing_guid": existing_guid,
        "formulas_translated": len(translated),
        "formulas_skipped": len(skipped),
        "formulas_filtered": len(dropped_names),
        "formulas_added": stats["added"],
        "formulas_skipped_existing": stats["skipped_existing"],
    }
    if validation_issues:
        result["validation_warnings"] = validation_issues

    if not dry_run and stats["added"] > 0:
        _import_with_retry(merged, ds, existing_guid, profile, max_retries, result)
    elif dry_run:
        typer.echo("  Dry run — skipping import", err=True)
    else:
        typer.echo("  No new formulas to add — skipping import", err=True)
    return result


def _write_sql_view_files(sql_views: list, connection_name: str, out_path, slug: str) -> list:
    """Write one ``{slug}.{ViewName}.sql_view.tml`` per Custom SQL relation; return paths.

    SQL Views are written separately from the model phases and must be imported before
    the model (which references them by name).
    """
    from ts_cli.model_builder import build_sql_view_tml
    from ts_cli.tableau_translate import dump_tml_yaml

    paths = []
    for sv in sql_views:
        sv_tml = build_sql_view_tml(
            name=sv["name"],
            connection_name=connection_name,
            sql_query=sv["sql_query"],
            columns=sv.get("columns", []),
        )
        sv_slug = re.sub(r"[^0-9A-Za-z._-]+", "_", sv["name"]).strip("_") or "custom_sql"
        sv_path = out_path / f"{slug}.{sv_slug}.sql_view.tml"
        sv_path.write_text(dump_tml_yaml(sv_tml))
        typer.echo(f"  Wrote SQL View: {sv_path}", err=True)
        paths.append(str(sv_path))
    return paths


def _generate_flow(
    ds: dict,
    name: str,
    slug: str,
    connection_name: str,
    parsed: dict,
    cleaned_cols: list,
    cleaned_formulas: list[dict],
    translated: list,
    skipped: list,
    rename_map: dict,
    raw_levels: dict,
    validation_issues: list,
    out_path: Path,
    dry_run: bool,
    reconcile_table: Optional[str] = None,
    reconcile_plan_mode: bool = False,
    column_name_map: Optional[dict] = None,
    profile: Optional[str] = None,
) -> dict:
    """Build phased model TML files from scratch and write them to disk."""
    from ts_cli.model_builder import build_model_tml, split_for_phased_import
    from ts_cli.tableau.build_model import apply_prefix_and_double_agg
    from ts_cli.tableau.reconcile import clean_columns, drop_junk_formulas, strip_suffix_in_expr
    from ts_cli.tableau_translate import dump_tml_yaml

    # Tier-1: strip Custom-SQL suffixes, drop junk, dedupe, and set the table so
    # column_id qualifies (single-table sqlproxy models otherwise emit bare ids).
    # Only stamp a table onto every column in the single-table case — for
    # multi-table datasources, columns belong to different tables and
    # stamping tables[0] on all of them would mis-qualify columns that
    # actually belong to other tables (worse than the pre-existing bare
    # column_id, which _build_model_columns's own single_table guard leaves
    # alone). Multi-table sources have no Custom-SQL suffixes/junk anyway —
    # that only comes from single-table sqlproxy sources — so leaving
    # cleaned_cols untouched here is safe.
    if len(ds.get("tables", [])) == 1:
        _table_name = ds["tables"][0]["name"]
        cleaned_cols = clean_columns(cleaned_cols, _table_name)
    for f in cleaned_formulas:
        f["expr"] = strip_suffix_in_expr(f["expr"])

    # Tier-1 (cont.): drop formulas referencing a now-dropped junk column —
    # must run unconditionally, not just under --reconcile-table.
    cleaned_formulas, _junk_dropped = drop_junk_formulas(cleaned_formulas)

    # Tier-2: reconcile emitted columns against a real target table's schema
    # (consultant/stand-in-view case, where the .twb's column names don't
    # match the ThoughtSpot table that will actually back this model).
    result_reconcile_dropped: Optional[dict] = None
    if reconcile_table:
        target_cols = _fetch_target_columns(reconcile_table, profile)
        if reconcile_plan_mode:
            print(json.dumps(_reconcile_plan(cleaned_cols, target_cols), indent=2))
            return {"reconcile_plan": True}
        from ts_cli.tableau.reconcile import apply_reconciliation

        cleaned_cols, cleaned_formulas, result_reconcile_dropped = apply_reconciliation(
            cleaned_cols, cleaned_formulas, target_cols, column_name_map or {},
        )
        typer.echo(
            f"  Reconcile: {len(result_reconcile_dropped['columns'])} column(s) dropped, "
            f"{len(result_reconcile_dropped['formulas'])} formula(s) dropped",
            err=True,
        )

    gen_formula_names = {f["name"] for f in cleaned_formulas}
    gen_param_names = {p["name"] for p in parsed["parameters"]}
    apply_prefix_and_double_agg(cleaned_formulas, gen_formula_names, gen_param_names)

    sql_views = ds.get("sql_views", [])

    model_tml = build_model_tml(
        model_name=name,
        connection_name=connection_name,
        tables=ds["tables"],
        columns=cleaned_cols,
        joins=ds["joins"],
        parameters=parsed["parameters"],
        translated_formulas=cleaned_formulas,
        formula_rename_map=rename_map,
        sql_views=sql_views,
    )

    levels = {}
    for f in cleaned_formulas:
        fname = f["name"]
        levels[fname] = raw_levels.get(fname, 0)
    phases = split_for_phased_import(model_tml, levels)

    typer.echo(f"  Phases: {len(phases)} (phase 0 = base, then per dependency level)", err=True)
    for i, phase in enumerate(phases):
        fc = len(phase["model"].get("formulas", []))
        typer.echo(f"    Phase {i}: {fc} formulas", err=True)

    result = {
        "datasource": ds["name"],
        "model_name": name,
        "tables": len(ds["tables"]),
        "columns": len(cleaned_cols),
        "formulas_translated": len(translated),
        "formulas_skipped": len(skipped),
        "formulas_total": len(ds["calculated_fields"]),
        "parameters": len(parsed["parameters"]),
        "name_renames": rename_map,
        "sql_views": len(sql_views),
        "phases": len(phases),
    }
    if validation_issues:
        result["validation_warnings"] = validation_issues
    if _junk_dropped:
        result["junk_formulas_dropped"] = _junk_dropped
    if result_reconcile_dropped is not None:
        result["reconcile_dropped"] = result_reconcile_dropped

    if not dry_run:
        # SQL Views first — they must exist before the model that references them.
        # (empty list when the datasource has no Custom SQL relations)
        result["sql_view_files"] = _write_sql_view_files(sql_views, connection_name, out_path, slug)

        for i, phase in enumerate(phases):
            fname = f"{slug}.phase{i}.model.tml"
            fpath = out_path / fname
            yaml_str = dump_tml_yaml(phase)
            fpath.write_text(yaml_str)
            typer.echo(f"  Wrote: {fpath}", err=True)
            result[f"phase_{i}_file"] = str(fpath)

    return result


def _load_table_name_map(
    table_name_map: Optional[str],
    existing_guid: Optional[str],
) -> dict[str, str]:
    """Load the --table-name-map JSON file, if provided; exits on a bad path.

    GENERATE-mode-only option — echoes a heads-up to stderr (but does not
    error) when combined with --existing-guid, since merge mode ignores it.
    """
    if not table_name_map:
        return {}
    tnm_path = Path(table_name_map)
    if not tnm_path.exists():
        typer.echo(f"Table name map file not found: {table_name_map}", err=True)
        raise SystemExit(1)
    name_map: dict[str, str] = json.loads(tnm_path.read_text())
    if existing_guid:
        typer.echo(
            "--table-name-map is ignored with --existing-guid "
            "(merge mode resolves tables from the existing model)",
            err=True,
        )
    return name_map


def _process_datasource(
    ds: dict,
    model_name: Optional[str],
    connection_name: str,
    parsed: dict,
    name_map: dict,
    col_name_map: dict,
    existing_guid: Optional[str],
    profile: Optional[str],
    dry_run: bool,
    max_retries: int,
    out_path: Path,
    reconcile_table: Optional[str],
    reconcile_plan_mode: bool,
) -> Optional[dict]:
    """Run the full per-datasource pipeline (translate, merge-or-generate) for
    one TWB datasource. Returns None to signal --reconcile-plan already
    printed its JSON and the caller should stop without further output.
    """
    from ts_cli.model_builder import (
        build_formula_levels,
        resolve_all_internal_refs,
        resolve_name_collisions,
    )
    from ts_cli.tableau.build_model import apply_table_name_map, fix_sqlproxy_scoping

    ds_name = ds["name"]
    name = model_name or ds_name.replace(" ", "_")
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")

    typer.echo(f"\n{'='*60}", err=True)
    typer.echo(f"Datasource: {ds_name}", err=True)
    typer.echo(f"  Tables: {len(ds['tables'])}", err=True)
    typer.echo(f"  Columns: {len(ds['columns'])}", err=True)
    typer.echo(f"  Calculated fields: {len(ds['calculated_fields'])}", err=True)
    typer.echo(f"  Parameters: {len(parsed['parameters'])}", err=True)

    # Step 2: Resolve internal references + translate formulas
    scoped_columns = ds.get("col_table_map", {})

    # When merging into an existing model, export it early so we can
    # fix sqlproxy→actual-table mapping before translation
    existing_tml = None
    if existing_guid:
        existing_tml = _export_model_tml(existing_guid, profile)
        scoped_columns, scoping_msg = fix_sqlproxy_scoping(
            scoped_columns, existing_tml,
        )
        if scoping_msg:
            typer.echo(f"  {scoping_msg}", err=True)
        if reconcile_table:
            typer.echo(
                "  --reconcile-table is ignored with --existing-guid "
                "(merge mode already resolves columns against the existing model)",
                err=True,
            )
    elif name_map:
        ds, scoped_columns = apply_table_name_map(ds, scoped_columns, name_map)
        typer.echo(f"  Applied table name map ({len(name_map)} entries)", err=True)

    # Build dependency levels from raw calcs (before resolution strips refs)
    raw_levels = build_formula_levels(ds["calculated_fields"], ds["calc_map"])

    # Pre-process: resolve copy-style and Calculation_ refs to display names
    resolved_calcs = resolve_all_internal_refs(
        ds["calculated_fields"], ds["calc_map"],
    )

    translated, skipped, validation_issues = _translate_and_validate(
        ds, resolved_calcs, scoped_columns, parsed,
    )

    # Step 3: Resolve name collisions
    cleaned_cols, cleaned_formulas, rename_map = resolve_name_collisions(
        ds["columns"], translated, parsed["parameters"],
    )
    if rename_map:
        typer.echo(f"  Renamed: {rename_map}", err=True)

    if existing_guid:
        return _merge_flow(
            ds=ds,
            name=name,
            existing_guid=existing_guid,
            existing_tml=existing_tml,
            cleaned_formulas=cleaned_formulas,
            translated=translated,
            skipped=skipped,
            validation_issues=validation_issues,
            profile=profile,
            dry_run=dry_run,
            max_retries=max_retries,
            column_name_map=col_name_map,
            parameters=parsed.get("parameters"),
        )

    result = _generate_flow(
        ds=ds,
        name=name,
        slug=slug,
        connection_name=connection_name,
        parsed=parsed,
        cleaned_cols=cleaned_cols,
        cleaned_formulas=cleaned_formulas,
        translated=translated,
        skipped=skipped,
        rename_map=rename_map,
        raw_levels=raw_levels,
        validation_issues=validation_issues,
        out_path=out_path,
        dry_run=dry_run,
        reconcile_table=reconcile_table,
        reconcile_plan_mode=reconcile_plan_mode,
        column_name_map=col_name_map,
        profile=profile,
    )
    if result.get("reconcile_plan"):
        # _generate_flow already printed the plan JSON to stdout — signal
        # the caller to stop without printing the all_results wrapper below
        # (which would emit a second, invalid-to-concatenate JSON blob) and
        # without writing any phased TML.
        return None
    return result


def _validate_build_options(
    existing_guid: Optional[str],
    profile: Optional[str],
    connection_name: str,
    reconcile_table: Optional[str] = None,
    reconcile_plan: bool = False,
) -> None:
    """Validate build-model option combinations; exits with code 1 on error."""
    if existing_guid and not profile:
        typer.echo("--profile is required when using --existing-guid", err=True)
        raise SystemExit(1)
    if not existing_guid and not connection_name:
        typer.echo("--connection is required when not using --existing-guid", err=True)
        raise SystemExit(1)
    if reconcile_table and not profile:
        typer.echo("--profile is required when using --reconcile-table", err=True)
        raise SystemExit(1)
    if reconcile_plan and not reconcile_table:
        typer.echo("--reconcile-plan requires --reconcile-table", err=True)
        raise SystemExit(1)


@app.command("build-model")
def build_model_cmd(
    twb_file: str = typer.Argument(..., help="Path to .twb or .twbx file"),
    connection_name: str = typer.Option("", "--connection", "-c",
                                         help="ThoughtSpot connection name (required unless --existing-guid)"),
    output_dir: str = typer.Option(".", "--output-dir", "-o",
                                    help="Directory for output TML files"),
    model_name: Optional[str] = typer.Option(None, "--model-name", "-m",
                                              help="Model name (default: derived from TWB)"),
    datasource_name: Optional[str] = typer.Option(None, "--datasource", "-d",
                                                    help="Filter to a single datasource"),
    existing_guid: Optional[str] = typer.Option(None, "--existing-guid",
                                                  help="GUID of existing model to merge formulas into"),
    profile: Optional[str] = typer.Option(None, "--profile", "-p",
                                            help="ThoughtSpot profile (required with --existing-guid)"),
    dry_run: bool = typer.Option(False, "--dry-run",
                                  help="Report only — don't write files or import"),
    max_retries: int = typer.Option(10, "--max-retries",
                                     help="Maximum formula-drop retry cycles (default 10). "
                                          "Deterministic failures (missing columns/params, "
                                          "cross-formula cascades) are caught pre-import; this "
                                          "budget is for genuine server-side rejections."),
    table_name_map: Optional[str] = typer.Option(
        None, "--table-name-map",
        help="GENERATE mode only (no --existing-guid). JSON file mapping TWB "
             "physical table name -> ThoughtSpot table TML name, for when they "
             "differ (warehouse-normalized names, sqlproxy/published-datasource "
             "scoping). Ignored when --existing-guid is set.",
    ),
    reconcile_table: Optional[str] = typer.Option(
        None, "--reconcile-table",
        help="GUID of an existing ThoughtSpot table to reconcile emitted "
             "columns against (consultant/stand-in-view case). Requires --profile.",
    ),
    reconcile_plan: bool = typer.Option(
        False, "--reconcile-plan",
        help="With --reconcile-table: print the reconcile plan (suggested "
             "mappings + drops) as JSON and exit without writing TML.",
    ),
    column_name_map: Optional[str] = typer.Option(
        None, "--column-name-map",
        help="JSON file mapping datasource column -> target column name (from "
             "the confirmed reconcile plan). Applies in GENERATE mode "
             "(--reconcile-table) and MERGE mode (--existing-guid).",
    ),
) -> None:
    """Parse a Tableau workbook and build import-ready ThoughtSpot model TML.

    Extracts tables, columns, joins, parameters, and calculated fields from
    the TWB XML, translates formulas, resolves name collisions, applies
    formula_ prefix for cross-references, detects double aggregation, and
    outputs phased model TML files ready for ts tml import.

    With --existing-guid: exports the existing model, merges new formulas
    into it (skipping existing), filters unresolvable references, and
    imports the merged model.

    With --reconcile-table: after Tier-1 cleanup, reconciles emitted columns
    against an existing ThoughtSpot table's real schema (GENERATE mode only —
    ignored with --existing-guid, which already resolves columns against the
    live model). --reconcile-plan prints the suggested mappings/drops as JSON
    and exits without writing TML; without it, --column-name-map (from the
    confirmed plan) is applied and columns/formulas that still can't be
    reconciled are dropped and reported in the result's "reconcile_dropped".
    --column-name-map also applies in MERGE mode (--existing-guid).
    """
    _validate_build_options(existing_guid, profile, connection_name, reconcile_table, reconcile_plan)
    from ts_cli.model_builder import parse_twb

    twb_path = Path(twb_file)
    if not twb_path.exists():
        typer.echo(f"File not found: {twb_file}", err=True)
        raise SystemExit(1)

    name_map = _load_table_name_map(table_name_map, existing_guid)
    col_name_map = _load_column_name_map(column_name_map)

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # Step 1: Parse TWB
    typer.echo(f"Parsing {twb_path.name}...", err=True)
    parsed = parse_twb(twb_path)

    # Filter datasources
    datasources = parsed["datasources"]
    if datasource_name:
        datasources = [ds for ds in datasources if ds["name"] == datasource_name]
        if not datasources:
            available = [ds["name"] for ds in parsed["datasources"]]
            typer.echo(
                f"Datasource '{datasource_name}' not found.\n"
                f"Available: {', '.join(available)}",
                err=True,
            )
            raise SystemExit(1)

    all_results = []
    for ds in datasources:
        result = _process_datasource(
            ds=ds,
            model_name=model_name,
            connection_name=connection_name,
            parsed=parsed,
            name_map=name_map,
            col_name_map=col_name_map,
            existing_guid=existing_guid,
            profile=profile,
            dry_run=dry_run,
            max_retries=max_retries,
            out_path=out_path,
            reconcile_table=reconcile_table,
            reconcile_plan_mode=reconcile_plan,
        )
        if result is None:
            # --reconcile-plan already printed its JSON — stop without
            # printing the all_results wrapper or writing any TML.
            return
        all_results.append(result)

    print(json.dumps(all_results, indent=2))
