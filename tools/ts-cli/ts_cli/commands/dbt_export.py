"""ts dbt-export — ThoughtSpot Model TML -> dbt project files (ts-convert-to-dbt).

Emit-only, offline file transform (the `ts snowflake build-sv` precedent): reads
locally exported Model + Table TML JSON and writes dbt project files. No
ThoughtSpot profile or dbt connection is used or needed.

Case A (new project scaffold, `build`) logic lives in ts_cli/dbt_build_export.py
(pure functions, no I/O). Case B (update an existing dbt project in place,
`diff`/`sync`) logic lives in ts_cli/dbt_diff.py (pure functions, no I/O) plus
the project-state I/O in this module. See
agents/cli/ts-convert-to-dbt/references/open-items.md #4.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import typer
import yaml

from ts_cli.dbt.case_b_plan import (
    _build_case_b_report,
    _first_relationship_test_dict,
    _is_ts_only_column,
    _merge_and_record,
    _merge_ts_meta,  # noqa: F401 -- re-exported for tests
    _report_json,
    _safe_load_yaml_dict,
    _set_or_replace_relationship_test,
    _unmanaged_ts_keys,  # noqa: F401 -- re-exported for tests
    render_report_markdown,
)
from ts_cli.io_helpers import load_json_file

app = typer.Typer(help="ThoughtSpot Model TML -> dbt project scaffold (offline file transform).")


def _read_json_file(path_str: str, flag: str) -> dict:
    try:
        return load_json_file(path_str, flag, expect_dict=True)
    except (FileNotFoundError, ValueError, TypeError) as exc:
        raise SystemExit(str(exc))


def _load_table_tmls(tables_dir: str) -> dict[str, dict]:
    """Load every Table TML JSON file in `tables_dir`, keyed by table name."""
    table_tmls: dict[str, dict] = {}
    tables_path = Path(tables_dir)
    if not tables_path.is_dir():
        typer.echo(f"--tables-dir is not a directory: {tables_dir}", err=True)
        raise SystemExit(1)

    for f in tables_path.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if "table" in data:
            tname = data["table"].get("name", f.stem)
            table_tmls[tname] = data

    if not table_tmls:
        typer.echo("no Table TML JSON files found in --tables-dir", err=True)
        raise SystemExit(1)
    return table_tmls


def _report_semantic_models(build_info: dict, requested: bool) -> None:
    """Say what happened to the secondary MetricFlow artifact, either way.

    Silence would be the wrong default in both directions: withholding a file
    the user expected leaves them hunting for it, and writing one that makes
    `dbt parse` fail leaves them debugging dbt (open-items #8).
    """
    if build_info.get("semantic_models_available") and not requested:
        typer.echo(
            "  NOTE: models/semantic_models.yml (legacy MetricFlow spec) was not "
            "written — pass --semantic-models to include it. It is omitted by "
            "default because dbt-core fails to parse a project whose semantic "
            "models carry a time dimension unless a metricflow_time_spine model "
            "exists, and none is generated.", err=True)
    elif build_info.get("semantic_models_emitted") and build_info.get("time_dimensions"):
        typer.echo(
            "  WARNING: models/semantic_models.yml carries "
            f"{build_info['time_dimensions']} time dimension(s). dbt-core will "
            "refuse to parse this project until you add a metricflow_time_spine "
            "model (dbt-fusion does not enforce it).", err=True)


@app.command("build")
def build_cmd(
    model_path: str = typer.Option(
        ..., "--model", "-m",
        help="Path to the Model TML JSON (from `ts tml export --parse`)"),
    tables_dir: str = typer.Option(
        ..., "--tables-dir", "-t",
        help="Directory containing Table TML JSON files (from `ts tml export`)"),
    project_name: str = typer.Option(
        ..., "--project-name", "-n", help="dbt project name (dbt_project.yml `name:`)"),
    source_name: str = typer.Option(
        ..., "--source-name", help="dbt source name for the generated sources.yml"),
    output_dir: str = typer.Option(
        ..., "--output-dir", "-o", help="Directory for the generated dbt project files"),
    target_schema: str = typer.Option(
        None, "--target-schema",
        help="Where dbt will materialise (`DB.SCHEMA`, or a bare `SCHEMA`). "
             "Generated models are aliased to their ThoughtSpot Table names, so "
             "a target equal to a Table's own schema would overwrite its own "
             "source — passing this makes that a build-time refusal instead of "
             "a `dbt run` failure."),
    semantic_models: bool = typer.Option(
        False, "--semantic-models/--no-semantic-models",
        help="Also emit models/semantic_models.yml (legacy MetricFlow spec). "
             "OFF by default: dbt-core refuses to parse a project whose "
             "semantic models carry a time dimension unless a "
             "metricflow_time_spine model exists, and this command emits none. "
             "No ThoughtSpot importer is known to read the file."),
) -> None:
    """Scaffold a new dbt project from a ThoughtSpot Model + Table TMLs (Case A).

    Emits, per ThoughtSpot model_table: one staging model (`select * from
    {{ source(...) }}`) for each distinct physical table, a thin passthrough
    model for each role-play alias of that table, plus `models/schema.yml`
    (the primary mechanism — plain dbt `columns:`/`tests:` with ThoughtSpot's
    own `ts_*` metadata tags under `meta:`, read by the same base dbt sync
    `ts dbt generate-tml` drives).

    `models/semantic_models.yml` (the secondary, legacy-spec MetricFlow
    artifact) is written only with `--semantic-models`. It is off by default
    because dbt-core refuses to parse a project whose semantic models carry a
    time dimension unless a `metricflow_time_spine` model exists, and none is
    generated — and no ThoughtSpot importer is known to read the file
    (open-items.md #2, #8).

    Formula columns are not translated — reported in `skipped_formulas`,
    never silently dropped.

    For an EXISTING dbt project, use `ts dbt-export diff`/`sync` instead
    (Case B) — this command always scaffolds fresh and does not know how to
    avoid clobbering a project that's already there.

    \\b
    Example (`ts tml export` has no --output-dir; split its --parse array
    into the per-file shape this command reads):
      ts tml export {model_guid} --parse --associated > export.json
      python3 -c "
      import json, pathlib
      items = json.load(open('export.json'))
      out = pathlib.Path('export'); out.mkdir(exist_ok=True)
      for it in items:
          name = 'model.json' if it['type'] == 'model' \\
              else f\\"table_{it['tml']['table']['name']}.json\\"
          (out / name).write_text(json.dumps(it['tml']))
      "
      ts dbt-export build --model export/model.json --tables-dir export/ \\
        --project-name sales --source-name warehouse --output-dir ./sales_dbt
    """
    from ts_cli.dbt_build_export import build_dbt_export, find_target_schema_collisions

    model_tml = _read_json_file(model_path, "--model")
    table_tmls = _load_table_tmls(tables_dir)

    # Each staging model carries `alias: <TABLE>` so it materialises under the
    # name ThoughtSpot already knows -- without which the return leg imports a
    # second, STG_-prefixed Table beside the original. That makes dbt's target
    # schema significant: aliased into a Table's OWN schema, the model would
    # overwrite its own source.
    collisions = find_target_schema_collisions(table_tmls, target_schema)
    if collisions:
        raise SystemExit(
            "Refusing to generate: --target-schema is where these Tables already "
            "live, so an aliased model would overwrite its own source:\n"
            + "\n".join(f"  {c}" for c in collisions)
            + "\n\nPoint dbt at a schema distinct from the source tables "
              "(profiles.yml `schema:`), or drop --target-schema if these "
              "models are meant to replace those relations.")
    if not target_schema:
        locations = sorted({
            f"{(t.get('table') or {}).get('db')}.{(t.get('table') or {}).get('schema')}"
            for t in table_tmls.values()})
        typer.echo(
            "  NOTE: generated models are aliased to their ThoughtSpot Table names, "
            f"so dbt must target a schema OTHER than {', '.join(locations)} — "
            "otherwise `dbt run` overwrites its own sources. Pass --target-schema "
            "to have this checked.", err=True)

    files, build_info = build_dbt_export(
        model_tml=model_tml, table_tmls=table_tmls,
        project_name=project_name, source_name=source_name,
        emit_semantic_models=semantic_models)

    _report_semantic_models(build_info, semantic_models)

    out_dir = Path(output_dir)
    for rel_path, content in files.items():
        dest = out_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
    typer.echo(f"  {len(files)} file(s) written to {out_dir}", err=True)

    for sf in build_info.get("skipped_formulas", []):
        typer.echo(f"  SKIPPED formula '{sf['name']}': {sf['reason']}", err=True)
    for sj in build_info.get("skipped_composite_joins", []):
        typer.echo(
            f"  SKIPPED composite join '{sj['relationship']}' "
            f"({sj['column_count']} columns): {sj['reason']}", err=True)
    for up in build_info.get("unmapped_properties", []):
        col = up.get("column")
        label = f"'{col}'" if col else f"join '{up.get('value')}'"
        typer.echo(f"  UNMAPPED {up['property']} on {label}: {up['reason']}", err=True)

    summary = {
        "project_name": project_name,
        "output_dir": str(out_dir),
        "files_written": build_info["files_written"],
        "tables": build_info["tables"],
        "dimensions": build_info["dimensions"],
        "time_dimensions": build_info["time_dimensions"],
        "metrics": build_info["metrics"],
        "skipped_formulas": len(build_info["skipped_formulas"]),
        "skipped_composite_joins": len(build_info["skipped_composite_joins"]),
        "unmapped_properties": len(build_info["unmapped_properties"]),
    }
    print(json.dumps(summary, indent=2))




_CASE_B_OPTIONS = {
    "model_path": typer.Option(
        ..., "--model", "-m",
        help="Path to the Model TML JSON (from `ts tml export --parse`)"),
    "tables_dir": typer.Option(
        ..., "--tables-dir", "-t",
        help="Directory containing Table TML JSON files (from `ts tml export`)"),
    "project_name": typer.Option(
        ..., "--project-name", "-n", help="dbt project name (must match the existing project)"),
    "source_name": typer.Option(
        ..., "--source-name", help="dbt source name (must match the existing sources.yml)"),
    "project_dir": typer.Option(
        ..., "--project-dir", "-p", help="Path to the EXISTING dbt project to compare against"),
    "format": typer.Option(
        "json", "--format",
        help="Output shape on stdout: `json` (default, the scripting contract) "
             "or `md` (the same change-set as markdown, for a human or an LLM "
             "to read without unpacking a nested dict)."),
}


def _emit_report(
    report: dict, fmt: str, *,
    written: "list[str] | None" = None,
    preserved: "dict[str, list[str]] | None" = None,
    dry_run: bool = False,
) -> None:
    """Print the change-set in the requested format. One place, so `diff`,
    `sync` and `sync --dry-run` cannot render the same report differently."""
    fmt = (fmt or "json").lower()
    if fmt not in ("json", "md"):
        raise SystemExit(f"--format must be 'json' or 'md', not {fmt!r}.")
    if fmt == "md":
        print(render_report_markdown(
            report, written=written, preserved=preserved, dry_run=dry_run), end="")
    else:
        print(_report_json(report, written=written, preserved=preserved))


@app.command("diff")
def diff_cmd(
    model_path: str = _CASE_B_OPTIONS["model_path"],
    tables_dir: str = _CASE_B_OPTIONS["tables_dir"],
    project_name: str = _CASE_B_OPTIONS["project_name"],
    source_name: str = _CASE_B_OPTIONS["source_name"],
    project_dir: str = _CASE_B_OPTIONS["project_dir"],
    format: str = _CASE_B_OPTIONS["format"],
) -> None:
    """Diff a fresh regeneration against an EXISTING dbt project (Case B).

    Read-only — mirrors `ts snowflake diff`'s Mode C pattern: NEVER writes
    anything, to `--project-dir` or anywhere else. Regenerates the project
    in memory from the current Model + Table TML, then compares it against
    what's already on disk at `--project-dir`:

    \\b
      new_tables            — dbt models the Model would produce that don't
                               exist yet (safe to add; see `ts dbt-export sync`)
      removed_tables        — dbt models on disk the Model no longer produces
                               (never deleted automatically — review by hand)
      changed_tables        — for models that exist on BOTH sides: per-column
                               ts_* meta tag / relationships-test changes in
                               models/schema.yml (the PRIMARY artifact only —
                               models/semantic_models.yml is not diffed, see
                               open-items.md #4)
      new_source_tables /
      removed_source_tables — the same new/removed comparison for
                               models/staging/sources.yml's table entries

    Output: the change-set to stdout (JSON, or markdown with `--format md`),
    diagnostic counts to stderr.

    `ts dbt-export sync --dry-run` prints exactly this — same engine, same
    renderer — so there is never a question of whether the plan you reviewed
    is the plan that will be applied.

    Example:

    \\b
      ts dbt-export diff --model export/model.json --tables-dir export/ \\
        --project-name sales --source-name warehouse --project-dir ./sales_dbt
    """
    model_tml = _read_json_file(model_path, "--model")
    table_tmls = _load_table_tmls(tables_dir)

    proj = Path(project_dir)
    if not proj.is_dir():
        typer.echo(f"--project-dir is not a directory: {project_dir}", err=True)
        raise SystemExit(1)

    report = _build_case_b_report(model_tml, table_tmls, project_name, source_name, proj)

    typer.echo(
        f"  new_tables:            {len(report['new_tables'])}\n"
        f"  removed_tables:        {len(report['removed_tables'])}\n"
        f"  changed_tables:        {len(report['changed_tables'])}\n"
        f"  new_source_tables:     {len(report['new_source_tables'])}\n"
        f"  removed_source_tables: {len(report['removed_source_tables'])}",
        err=True,
    )
    _emit_report(report, format)


@app.command("sync")
def sync_cmd(
    model_path: str = _CASE_B_OPTIONS["model_path"],
    tables_dir: str = _CASE_B_OPTIONS["tables_dir"],
    project_name: str = _CASE_B_OPTIONS["project_name"],
    source_name: str = _CASE_B_OPTIONS["source_name"],
    project_dir: str = _CASE_B_OPTIONS["project_dir"],
    update_metadata: bool = typer.Option(
        False, "--update-metadata",
        help="Also update ts_* metadata on EXISTING tables (not just new ones). "
             "Preserves non-ts_* meta keys; never auto-deletes columns or "
             "relationship tests."),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Compute and print the change-set, then return without writing "
             "anything. Same engine and same renderer as `ts dbt-export diff`."),
    format: str = _CASE_B_OPTIONS["format"],
) -> None:
    """Add new tables from the Model into an EXISTING dbt project (Case B).

    Computes the same change-set `ts dbt-export diff` would, then writes
    ONLY what's purely additive — nothing that already exists in
    `--project-dir` is ever modified or deleted:

    \\b
      - new_tables: writes each new table's staging/passthrough `.sql` file
      - new_tables: appends each new table's `models/schema.yml` model block
        (creates schema.yml if it doesn't exist yet)
      - new_source_tables: merges each new source table into
        `models/staging/sources.yml` (creates it if it doesn't exist yet;
        appends to the matching database/schema source block, or adds a new
        source block if none matches)

    `changed_tables` and `removed_tables`/`removed_source_tables` (anything
    touching a table that already exists) are NEVER auto-applied — they are
    printed in the output for manual review, exactly like `ts dbt-export
    diff`'s output.

    CAVEAT: appending to schema.yml/sources.yml is a full YAML
    parse-then-dump round-trip (the same mechanism Case A already uses to
    generate these files from scratch) — it reformats the WHOLE file and
    does not preserve comments. Only run this against a version-controlled
    project and review `git diff` before committing.

    Pass ``--dry-run`` to compute and print the change-set without writing
    anything. It returns before the first write and emits exactly what
    `ts dbt-export diff` does — same engine, same renderer — so reviewing the
    dry run is reviewing the real plan.

    Pass ``--update-metadata`` to also apply ts_* metadata changes
    (modified_meta, new_relationship, modified_relationship, model-level
    ts_rls_rules, column descriptions) to tables that ALREADY EXIST in the
    project. Non-ts_* meta keys are always preserved. Columns and
    relationship tests are never auto-deleted.

    Example:

    \\b
      ts dbt-export sync --model export/model.json --tables-dir export/ \\
        --project-name sales --source-name warehouse --project-dir ./sales_dbt
    """
    model_tml = _read_json_file(model_path, "--model")
    table_tmls = _load_table_tmls(tables_dir)

    proj = Path(project_dir)
    if not proj.is_dir():
        typer.echo(f"--project-dir is not a directory: {project_dir}", err=True)
        raise SystemExit(1)

    report = _build_case_b_report(model_tml, table_tmls, project_name, source_name, proj)
    new_tables = set(report["new_tables"])

    if dry_run:
        # Return BEFORE any write, printing the same stdout payload the real
        # run would — the `ts publish run --dry-run` contract.
        typer.echo(f"  --dry-run: nothing written to {proj}", err=True)
        _emit_report(report, format, written=[], dry_run=True)
        return

    written = _write_new_sql_files(proj, report["files"], new_tables)
    written += _append_new_schema_models(proj, report["files"], new_tables)
    written += _merge_new_source_tables(proj, report, source_name)
    preserved: dict[str, list[str]] = {}
    if update_metadata:
        meta_written, preserved = _update_existing_schema_models(proj, report)
        written += meta_written

    _print_sync_result(
        proj, report, written,
        update_metadata_applied=update_metadata, preserved=preserved)
    _emit_report(report, format, written=written, preserved=preserved)



def _write_new_sql_files(proj: Path, files: dict[str, str], new_tables: set[str]) -> list[str]:
    """New tables' staging/passthrough `.sql` files — brand-new files,
    nothing existing is touched."""
    written: list[str] = []
    for rel_path, content in files.items():
        if rel_path.endswith(".sql") and Path(rel_path).stem in new_tables:
            dest = proj / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
            written.append(rel_path)
    return written


def _append_new_schema_models(
    proj: Path, files: dict[str, str], new_tables: set[str],
) -> list[str]:
    """New tables' `models/schema.yml` model blocks — append-only; creates
    schema.yml if it doesn't exist yet."""
    if not new_tables:
        return []
    fresh_schema_doc = _safe_load_yaml_dict(
        files.get("models/schema.yml", "")) or {"version": 2, "models": []}
    new_model_docs = [
        m for m in fresh_schema_doc.get("models") or [] if m.get("name") in new_tables]
    if not new_model_docs:
        return []

    schema_path = proj / "models" / "schema.yml"
    existing_schema_doc = _safe_load_yaml_dict(
        schema_path.read_text(encoding="utf-8") if schema_path.is_file() else ""
    ) or {"version": 2, "models": []}
    existing_schema_doc.setdefault("models", []).extend(new_model_docs)
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path.write_text(
        yaml.safe_dump(existing_schema_doc, sort_keys=False), encoding="utf-8")
    return ["models/schema.yml (appended)"]


def _find_sources_file(proj: Path, source_name: str) -> Path:
    """Return the sources.yml that already contains `source_name`, or the default path.

    Scans models/ recursively so nested project layouts (e.g. models/staging/barbershop/)
    are found correctly. Falls back to models/staging/sources.yml for new projects.
    """
    default = proj / "models" / "staging" / "sources.yml"
    if not source_name:
        return default
    models_dir = proj / "models"
    if models_dir.is_dir():
        for yml_file in sorted(models_dir.rglob("sources.yml")):
            try:
                doc = yaml.safe_load(yml_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(doc, dict):
                continue
            for s in doc.get("sources") or []:
                if isinstance(s, dict) and s.get("name") == source_name:
                    return yml_file
    return default


def _merge_new_source_tables(proj: Path, report: dict, source_name: str = "") -> list[str]:
    """New source table entries merged into the appropriate sources.yml — append-only,
    matched by (database, schema) against the existing source blocks.

    Finds the existing sources.yml that already contains `source_name` (scanning
    models/ recursively) so nested project layouts work correctly. Falls back to
    models/staging/sources.yml for new projects that have no sources.yml yet.
    """
    if not report["new_source_tables"]:
        return []
    new_source_table_set = set(report["new_source_tables"])

    sources_path = _find_sources_file(proj, source_name)
    # Load the specific file's content (not the merged-virtual doc) so we only
    # update that one file and don't copy sources from other subdirectories into it.
    if sources_path.is_file():
        file_sources_doc = _safe_load_yaml_dict(
            sources_path.read_text(encoding="utf-8")) or {"version": 2, "sources": []}
    else:
        file_sources_doc = {"version": 2, "sources": []}

    existing_sources = file_sources_doc.setdefault("sources", [])

    for fresh_src in report["fresh_sources_doc"].get("sources") or []:
        new_entries = [
            t for t in fresh_src.get("tables") or []
            if isinstance(t, dict) and t.get("name") in new_source_table_set
        ]
        if not new_entries:
            continue
        match = next(
            (s for s in existing_sources
             if s.get("database") == fresh_src.get("database")
             and s.get("schema") == fresh_src.get("schema")),
            None,
        )
        if match is not None:
            match.setdefault("tables", []).extend(new_entries)
        else:
            existing_sources.append({**fresh_src, "tables": new_entries})

    sources_path.parent.mkdir(parents=True, exist_ok=True)
    sources_path.write_text(
        yaml.safe_dump(file_sources_doc, sort_keys=False), encoding="utf-8")
    relative_path = str(sources_path.relative_to(proj))
    return [f"{relative_path} (merged)"]


def _update_existing_schema_models(
    proj: Path, report: dict,
) -> list[str]:
    """Sync ts_* metadata from the fresh schema into existing model entries.

    For each model present in BOTH the existing project AND the fresh
    generation (skipping new_tables — those are handled by the additive
    path):
      - ts_* keys this generator OWNS (dbt_build_export.GENERATED_*_META_KEYS)
        are updated in column and model-level config.meta; non-ts_* keys and
        ts_* keys outside that set are preserved untouched (_merge_ts_meta)
      - column `description` is updated when the fresh schema has one
      - new columns (from changed_tables.new_columns) are appended
      - relationship tests are added/replaced (new_relationship/modified_relationship)
      - removed_columns that contain ONLY ts_*-originated content are deleted;
        columns with a description, non-ts_* meta keys, or custom data_tests are
        left in place for manual review (_is_ts_only_column)
      - removed_relationship entries are never auto-deleted

    Returns `(written_paths, preserved)` where `preserved` is
    `{"<model>.<column>": [unmanaged ts_* keys]}` for every entry that carried
    a hand-authored tag this pass deliberately left alone — the caller prints
    it, so the ownership boundary is visible instead of merely respected.
    """
    from ts_cli.dbt_build_export import (
        GENERATED_COLUMN_META_KEYS,
        GENERATED_MODEL_META_KEYS,
    )

    preserved: dict[str, list[str]] = {}
    fresh_schema_doc = _safe_load_yaml_dict(
        report["files"].get("models/schema.yml", "")) or {"version": 2, "models": []}
    fresh_model_map: dict[str, dict] = {
        m["name"]: m
        for m in fresh_schema_doc.get("models") or []
        if isinstance(m, dict) and m.get("name")
    }

    new_tables = set(report["new_tables"])
    models_dir = proj / "models"
    if not models_dir.is_dir():
        return []

    file_docs: dict[Path, dict] = {}
    model_to_file: dict[str, Path] = {}
    for yml_path in sorted(models_dir.rglob("*.yml")):
        try:
            doc = yaml.safe_load(yml_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        file_docs[yml_path] = doc
        for m in doc.get("models") or []:
            if isinstance(m, dict) and m.get("name"):
                model_to_file[m["name"]] = yml_path

    changed_tables = report.get("changed_tables", {})
    updated_files: set[Path] = set()

    for model_name, fresh_model in fresh_model_map.items():
        if model_name in new_tables:
            continue
        if model_name not in model_to_file:
            continue

        yml_path = model_to_file[model_name]
        doc = file_docs[yml_path]
        existing_models = doc.get("models") or []
        model_entry = next(
            (m for m in existing_models if m.get("name") == model_name), None)
        if model_entry is None:
            continue

        changed = False

        # model-level ts_* config.meta (e.g. ts_rls_rules)
        fresh_model_meta = ((fresh_model.get("config") or {}).get("meta")) or {}
        if fresh_model_meta:
            existing_model_meta = ((model_entry.get("config") or {}).get("meta")) or {}
            merged = _merge_and_record(
                existing_model_meta, fresh_model_meta, GENERATED_MODEL_META_KEYS,
                model_name, preserved)
            if merged != existing_model_meta:
                model_entry.setdefault("config", {})["meta"] = merged
                changed = True

        table_diff = changed_tables.get(model_name, {})
        new_cols_set = set(table_diff.get("new_columns") or [])
        new_rel_set = set(table_diff.get("new_relationship") or [])
        mod_rel_set = {
            d["column"] for d in (table_diff.get("modified_relationship") or [])}

        fresh_cols = fresh_model.get("columns") or []
        fresh_col_map: dict[str, dict] = {
            c["name"]: c for c in fresh_cols if isinstance(c, dict) and c.get("name")
        }
        existing_cols = model_entry.setdefault("columns", [])
        existing_col_names = {
            c["name"] for c in existing_cols if isinstance(c, dict) and c.get("name")
        }

        # update existing columns
        for col_entry in existing_cols:
            if not isinstance(col_entry, dict) or not col_entry.get("name"):
                continue
            col_name = col_entry["name"]
            fresh_col = fresh_col_map.get(col_name)
            if not fresh_col:
                continue

            existing_meta = ((col_entry.get("config") or {}).get("meta")) or {}
            fresh_meta = ((fresh_col.get("config") or {}).get("meta")) or {}
            merged_meta = _merge_and_record(
                existing_meta, fresh_meta, GENERATED_COLUMN_META_KEYS,
                f"{model_name}.{col_name}", preserved)
            if merged_meta != existing_meta:
                col_entry.setdefault("config", {})["meta"] = merged_meta
                changed = True

            if (fresh_col.get("description")
                    and col_entry.get("description") != fresh_col["description"]):
                col_entry["description"] = fresh_col["description"]
                changed = True

            if col_name in new_rel_set or col_name in mod_rel_set:
                fresh_test = _first_relationship_test_dict(fresh_col)
                if fresh_test:
                    _set_or_replace_relationship_test(col_entry, fresh_test)
                    changed = True

        # append new columns
        for col_name in sorted(new_cols_set):
            if col_name not in existing_col_names:
                fresh_col = fresh_col_map.get(col_name)
                if fresh_col:
                    existing_cols.append(fresh_col)
                    changed = True

        # remove ts_*-only columns that ThoughtSpot has deleted
        removed_cols_set = set(table_diff.get("removed_columns") or [])
        if removed_cols_set:
            kept = []
            safe_removed = False
            for col_entry in existing_cols:
                if (isinstance(col_entry, dict)
                        and col_entry.get("name") in removed_cols_set
                        and _is_ts_only_column(col_entry)):
                    safe_removed = True
                else:
                    kept.append(col_entry)
            if safe_removed:
                model_entry["columns"] = kept
                existing_cols = kept  # noqa: F841
                changed = True

        if changed:
            updated_files.add(yml_path)

    written = []
    for yml_path in sorted(updated_files):
        yml_path.write_text(
            yaml.safe_dump(file_docs[yml_path], sort_keys=False), encoding="utf-8")
        rel = str(yml_path.relative_to(proj))
        written.append(f"{rel} (updated ts_* metadata)")
    return written, preserved


def _print_sync_result(
    proj: Path, report: dict, written: list[str],
    *, update_metadata_applied: bool = False,
    preserved: "dict[str, list[str]] | None" = None,
) -> None:
    typer.echo(f"  {len(written)} file(s) written/updated in {proj}", err=True)
    for w in written:
        typer.echo(f"    {w}", err=True)
    if written:
        typer.echo(
            "  NOTE: schema.yml/sources.yml writes reformat the whole file "
            "via a YAML round-trip and do not preserve comments — review "
            "`git diff` before committing.", err=True)

    if preserved:
        total = sum(len(v) for v in preserved.values())
        typer.echo(
            f"  Preserved {total} hand-authored ts_* tag(s) on "
            f"{len(preserved)} entr{'y' if len(preserved) == 1 else 'ies'} — "
            "not written by `ts dbt-export build`, so left untouched:", err=True)
        for where, keys in sorted(preserved.items()):
            typer.echo(f"    {where}: {', '.join(keys)}", err=True)

    needs_review = {
        "removed_tables": report["removed_tables"],
        "removed_source_tables": report["removed_source_tables"],
    }
    if not update_metadata_applied:
        needs_review["changed_tables"] = sorted(report["changed_tables"].keys())
    if any(needs_review.values()):
        typer.echo("  The following need manual review (never auto-applied):", err=True)
        for label, value in needs_review.items():
            if value:
                typer.echo(f"    {label}: {value}", err=True)


@app.command("build-model")
def build_model_cmd(
    schema_yml: str = typer.Option(
        ..., "--schema-yml",
        help="Path to schema.yml containing ts_* meta tags and ts_join_* relationship tests"),
    model_name: str = typer.Option(
        ..., "--model-name",
        help="Name for the ThoughtSpot Model (used in the TML name: field)"),
    output: str = typer.Option(
        None, "--output", "-o",
        help="Write TML JSON to this file (default: stdout)"),
    rls_out: str = typer.Option(
        None, "--rls-out",
        help="Directory for per-Table `rls_rules` JSON extracted from model-level "
             "ts_rls_rules. RLS lives on the Table TML, not the Model, so this "
             "command cannot apply it — write the blocks out, merge each into its "
             "Table TML, and re-import. `ts dbt build-model` (dbt Cloud) does this "
             "automatically instead."),
    model_guid: str = typer.Option(
        None, "--model-guid",
        help="Update this existing Model in place: sets `guid` at the TML document "
             "root and, with --import, imports with create_new=false. Without it "
             "an import CREATES A SECOND MODEL rather than updating the first."),
    do_import: bool = typer.Option(
        False, "--import",
        help="Import the assembled TML into ThoughtSpot instead of only emitting it. "
             "Requires --profile."),
    profile: str = typer.Option(
        None, "--profile", "-p", envvar="TS_PROFILE",
        help="ThoughtSpot profile to import with (only used by --import)."),
) -> None:
    """Build a ThoughtSpot Model TML from ts_join_* relationship tests in schema.yml.

    Reads the ts_* column meta tags and ts_join_* data on relationship tests to
    assemble a single unified ThoughtSpot Model TML — the reverse of what
    `ts dbt-export build` emits. Useful when `ts dbt generate-tml` splits a
    multi-fact ThoughtSpot model into separate models (one per connected component
    of the dbt FK graph — see ts-convert-to-dbt open-items.md #11).

    Offline by default: no ThoughtSpot profile or dbt connection needed, TML
    JSON to stdout (or --output).

    ``--model-guid`` sets `guid` at the document root — the ONE placement
    ThoughtSpot accepts (see `thoughtspot-model-tml.md`). It replaces the
    hand-edit the skill used to instruct between emitting and importing;
    getting that wrong, or skipping it, silently creates a second Model
    alongside the one you meant to update.

    ``--import`` does the import here rather than through a pipe, so the
    guid-bearing document cannot be separated from `create_new=false`.

    \\b
    Examples:

    \\b
      # emit only
      ts dbt-export build-model \\
        --schema-yml models/staging/barbershop/schema.yml \\
        --model-name BARBERSHOP_OPERATIONS
    \\b
      # update an existing Model in place, in one call
      ts dbt-export build-model \\
        --schema-yml models/staging/barbershop/schema.yml \\
        --model-name BARBERSHOP_OPERATIONS \\
        --model-guid 1a2b3c --import --profile Embed-1-Prod
    """
    from ts_cli.dbt_build_export import (
        build_model_tml_from_schema_yml,
        extract_table_rls_from_schema_yml,
        find_display_name_collisions,
    )

    schema_path = Path(schema_yml)
    if not schema_path.is_file():
        typer.echo(f"--schema-yml not found: {schema_yml}", err=True)
        raise SystemExit(1)

    if do_import and not profile:
        raise SystemExit("--import requires --profile (or TS_PROFILE).")

    schema_text = schema_path.read_text(encoding="utf-8")
    tml = build_model_tml_from_schema_yml(schema_text, model_name)

    excluded = tml.pop("_excluded_columns", [])
    if excluded:
        typer.echo(
            f"  ts_column_exclude: {len(excluded)} column(s) left out of the Model — "
            + ", ".join(excluded), err=True)

    # ts_display_name can collide with a sibling's name; ThoughtSpot compares
    # Model column names case-insensitively and rejects the whole import.
    collisions = find_display_name_collisions(tml)
    if collisions:
        listing = "\n".join(f"  {name!r}: {', '.join(refs)}" for name, refs in collisions)
        raise SystemExit(
            "Display-name collision — ThoughtSpot compares Model column names "
            f"case-insensitively:\n{listing}\n"
            "Give one of each pair a distinct ts_display_name in schema.yml.")

    _handle_schema_yml_rls(extract_table_rls_from_schema_yml(schema_text), rls_out)

    # guid belongs at the document ROOT, never nested under `model:`
    # (thoughtspot-model-tml.md). Set before writing or importing so both
    # paths emit the identical document.
    if model_guid:
        tml = {"guid": model_guid, **tml}

    result = json.dumps(tml, indent=2)

    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(result, encoding="utf-8")
        typer.echo(f"  Model TML written to {output}", err=True)

    if do_import:
        _import_model_tml(tml, profile, model_guid, model_name)
    elif not output:
        print(result)


def _handle_schema_yml_rls(rls_by_table: dict, rls_out: "str | None") -> None:
    """Write, or loudly refuse to lose, the `ts_rls_rules` this command can't apply.

    RLS lives on the **Table** TML and this command emits the Model only, so
    the choice is write-for-merge or warn — never a silent drop, which is how
    a resync quietly removes row-level security.
    """
    if not rls_by_table:
        return
    if not rls_out:
        typer.echo(
            f"  WARNING: ts_rls_rules found on {len(rls_by_table)} model(s) "
            f"({', '.join(sorted(rls_by_table))}) and NOT applied — RLS lives on "
            "the Table TML, not the Model. Re-run with --rls-out <dir> to write "
            "the blocks, or use `ts dbt build-model` (dbt Cloud), which applies "
            "them automatically.", err=True)
        return

    rls_dir = Path(rls_out)
    rls_dir.mkdir(parents=True, exist_ok=True)
    for table_name, block in sorted(rls_by_table.items()):
        dest = rls_dir / f"{table_name}_rls_rules.json"
        dest.write_text(json.dumps({"rls_rules": block}, indent=2), encoding="utf-8")
        typer.echo(f"  ts_rls_rules: wrote {dest}", err=True)
    typer.echo(
        "  Merge each block into its Table TML under `table.rls_rules` and "
        "re-import — this command emits the Model only.", err=True)


def _import_model_tml(tml: dict, profile: str, model_guid: "str | None",
                      model_name: str) -> None:
    """Import the assembled Model, updating in place when a guid is present."""
    from ts_cli.io_helpers import run_tml_import

    if not model_guid:
        typer.echo(
            "  NOTE: no --model-guid — importing with create_new=true, which "
            "CREATES A NEW Model. Pass --model-guid to update an existing one.",
            err=True)
    status, guid, error = run_tml_import(
        profile, tml,
        policy="ALL_OR_NONE",
        no_create_new=bool(model_guid),
        label=f"tml import ({'update' if model_guid else 'create'} {model_name})")
    print(json.dumps({
        "status": status,
        "guid": guid or model_guid,
        "model_name": model_name,
        "created_new": not model_guid,
        "error": error,
    }, indent=2))
    if status != "imported":
        raise SystemExit(f"Model import failed: {(error or '')[:500]}")
