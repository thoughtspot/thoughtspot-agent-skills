"""ts-convert-to-dbt Case B — read an existing dbt project and diff it.

The engine behind `ts dbt-export diff` / `sync`: walks a project's `models/`
tree, adopts its existing model naming, regenerates Case A output in memory and
reports the change-set. Also holds the `ts_*` ownership-boundary merge
(`_merge_ts_meta`) and the deletion-safety gate (`_is_ts_only_column`) that make
`sync --update-metadata` safe to run.

`diff` and `sync` share `build_case_b_report`, so the two commands cannot
disagree about what is new / removed / changed.

Reads the filesystem (project state) but touches no network and writes nothing —
every write lives in the command layer, `commands/dbt_export.py`. Split out of
that module under the `check_file_size` gate.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Case B — diff / sync against an existing dbt project
# ---------------------------------------------------------------------------

def _safe_load_yaml_dict(text: str) -> "dict | None":
    if not text or not text.strip():
        return None
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    return doc if isinstance(doc, dict) else None


def _flatten_source_tables(doc: dict) -> set[str]:
    names: set[str] = set()
    for src in doc.get("sources") or []:
        for t in src.get("tables") or []:
            if isinstance(t, dict) and t.get("name"):
                names.add(t["name"])
    return names


_SOURCE_CALL_RE = re.compile(
    r"""source\(\s*['"]([^'"]+)['"]\s*,\s*['"]([^'"]+)['"]\s*\)""")


def _existing_source_locations(project_dir: Path) -> dict[str, tuple[str, str]]:
    """{source_name: (DATABASE, SCHEMA)} from every sources.yml-style file under models/."""
    out: dict[str, tuple[str, str]] = {}
    models_dir = project_dir / "models"
    if not models_dir.is_dir():
        return out
    for yml in sorted(models_dir.rglob("*.yml")):
        doc = _safe_load_yaml_dict(yml.read_text(encoding="utf-8")) if yml.is_file() else None
        for src in (doc or {}).get("sources") or []:
            if isinstance(src, dict) and src.get("name"):
                out[src["name"]] = (
                    str(src.get("database") or "").upper(), str(src.get("schema") or "").upper())
    return out


def _existing_models_by_source_table(project_dir: Path) -> dict[tuple, str]:
    """Map each warehouse table an existing staging model selects from to that
    model's name, keyed by (DATABASE, SCHEMA, TABLE): the source block's
    location plus the table named in `{{ source('<src>', '<TABLE>') }}`.

    This is how Case B adopts the project's own naming instead of the
    generator's `stg_<table>` default — a project that renamed `stg_appointments`
    to `appointments` still selects from the same warehouse table, so the table
    is the stable identity, not the file name. Keying by location (not table
    name alone) keeps `DL_TEST.BARBERSHOP_DEMO.CUSTOMERS` apart from another
    source's `customers`. A location selected by two models is ambiguous and
    left unmapped (the default name is used).
    """
    models_dir = project_dir / "models"
    if not models_dir.is_dir():
        return {}
    locations = _existing_source_locations(project_dir)
    hits: dict[tuple, set[str]] = {}
    for sql in models_dir.rglob("*.sql"):
        try:
            text = sql.read_text(encoding="utf-8")
        except OSError:
            continue
        for src, table in _SOURCE_CALL_RE.findall(text):
            db, schema = locations.get(src, ("", ""))
            hits.setdefault((db, schema, table.upper()), set()).add(sql.stem)
    return {k: next(iter(v)) for k, v in hits.items() if len(v) == 1}


def _model_dirs(project_dir: Path, model_names: "set[str]") -> "set[Path]":
    """Directories (relative to project_dir) holding the given models' .sql files."""
    models_dir = project_dir / "models"
    if not models_dir.is_dir():
        return set()
    return {sql.parent.relative_to(project_dir)
            for sql in models_dir.rglob("*.sql") if sql.stem in model_names}


def _load_project_state(project_dir: Path) -> tuple[set[str], str, str]:
    """Returns (existing_model_names, merged_schema_yaml_text, merged_sources_yaml_text).

    `existing_model_names` comes from `.sql` file stems, not schema.yml —
    a table can exist with zero classified columns/joins and so have no
    schema.yml entry at all (dbt_build_export.py's `_build_schema_docs`
    skips it), so `.sql` file presence is the only reliable existence signal.

    Walks the entire `models/` tree recursively so any project layout works —
    flat (ts dbt-export build output) or arbitrarily nested subdirectories.
    """
    models_dir = project_dir / "models"

    existing_model_names: set[str] = {
        f.stem for f in models_dir.rglob("*.sql")
    } if models_dir.is_dir() else set()

    all_models: list[dict] = []
    all_sources: list[dict] = []
    if models_dir.is_dir():
        for yml_file in sorted(models_dir.rglob("*.yml")):
            try:
                doc = yaml.safe_load(yml_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(doc, dict):
                continue
            for m in doc.get("models") or []:
                if isinstance(m, dict) and m.get("name"):
                    all_models.append(m)
            for s in doc.get("sources") or []:
                if isinstance(s, dict):
                    all_sources.append(s)

    schema_text = (
        yaml.safe_dump({"version": 2, "models": all_models}, sort_keys=False)
        if all_models else ""
    )
    sources_text = (
        yaml.safe_dump({"version": 2, "sources": all_sources}, sort_keys=False)
        if all_sources else ""
    )
    return existing_model_names, schema_text, sources_text


def _build_case_b_report(
    model_tml: dict, table_tmls: dict[str, dict], project_name: str,
    source_name: str, project_dir: Path,
) -> dict:
    """Regenerate fresh Case A output in memory and diff it against
    `project_dir`'s current state. Returns everything both `diff` and `sync`
    need — the two commands share this so they can never disagree about
    what's new/removed/changed."""
    from ts_cli.dbt_build_export import build_dbt_export
    from ts_cli.dbt_diff import compute_dbt_change_set, parse_schema_yaml_columns

    # Adopt the existing project's model names: pair each Model table with the
    # on-disk model that selects from its db_table, so a renamed staging model
    # (appointments, not stg_appointments) is recognised rather than reported
    # as one removed table plus one new one.
    existing_model_names, existing_schema_text, existing_sources_text = \
        _load_project_state(project_dir)

    # Two ways a Model table can correspond to an existing dbt model:
    #  (a) the model SELECTS FROM the Table's warehouse location — the Table is a
    #      raw source (Case A output): match `{{ source() }}` by db/schema/table;
    #  (b) the model PRODUCES the Table — the ThoughtSpot Table was generated by
    #      ts-convert-from-dbt from the dbt model's own output relation, so its
    #      db_table IS the dbt model name (e.g. DBT_DLEE_PROD.BARBERS ← barbers).
    #      Such tables have no source entry of their own to regenerate.
    by_source = _existing_models_by_source_table(project_dir)
    by_name = {n.upper(): n for n in existing_model_names}
    adopted_names: dict[str, str] = {}
    dbt_output_tables: set[str] = set()          # matched via (b) — keyed by db_table
    for tname, ttml in table_tmls.items():
        tb = ttml.get("table") or {}
        db_table = str(tb.get("db_table") or tname)
        key = (str(tb.get("db") or "").upper(), str(tb.get("schema") or "").upper(),
               db_table.upper())
        if key in by_source:
            adopted_names[tname] = by_source[key]
        elif db_table.upper() in by_name:
            adopted_names[tname] = by_name[db_table.upper()]
            dbt_output_tables.add(db_table)

    files, build_info = build_dbt_export(
        model_tml=model_tml, table_tmls=table_tmls,
        project_name=project_name, source_name=source_name,
        model_name_overrides=adopted_names or None)
    fresh_model_names = set(build_info["model_names"])

    new_tables = sorted(fresh_model_names - existing_model_names)
    # "Removed" only makes sense within this Model's footprint: when existing
    # models were adopted, restrict the comparison to the directories they live
    # in — other directories (other Models, marts, unrelated sources) are not
    # this Model's to report on.
    scope_dirs = _model_dirs(project_dir, set(adopted_names.values()))
    if scope_dirs:
        in_scope = {sql.stem for d in scope_dirs for sql in (project_dir / d).glob("*.sql")}
        removed_tables = sorted((existing_model_names & in_scope) - fresh_model_names)
    else:
        removed_tables = sorted(existing_model_names - fresh_model_names)

    current_cols = parse_schema_yaml_columns(existing_schema_text)
    new_cols = parse_schema_yaml_columns(files.get("models/schema.yml", ""))
    changed_tables = compute_dbt_change_set(current_cols, new_cols)

    existing_sources_doc = _safe_load_yaml_dict(existing_sources_text) or {
        "version": 2, "sources": []}
    fresh_sources_doc = _safe_load_yaml_dict(
        files.get("models/staging/sources.yml", "")) or {"sources": []}

    # Compare source tables only within the source blocks this Model maps to
    # (same database+schema as one of its Tables, or named --source-name) —
    # other sources' tables are not "removed" just because this Model doesn't use them.
    model_locations = {
        (str((t.get("table") or {}).get("db") or "").upper(),
         str((t.get("table") or {}).get("schema") or "").upper()) for t in table_tmls.values()}
    scoped_existing = {"sources": [
        src for src in existing_sources_doc.get("sources") or []
        if isinstance(src, dict) and (
            src.get("name") == source_name
            or (str(src.get("database") or "").upper(),
                str(src.get("schema") or "").upper()) in model_locations)]}
    # dbt-output Tables (matched via (b)) are produced by the project, not read
    # from a source: the regenerated sources.yml entry for them is meaningless,
    # and the project's own source entry of the same name is the model's INPUT,
    # unrelated to the ThoughtSpot Table — leave both out of the comparison.
    existing_db_tables = _flatten_source_tables(scoped_existing) - dbt_output_tables
    fresh_db_tables = _flatten_source_tables(fresh_sources_doc) - dbt_output_tables
    new_source_tables = sorted(fresh_db_tables - existing_db_tables)
    removed_source_tables = sorted(existing_db_tables - fresh_db_tables)

    return {
        "files": files,
        "build_info": build_info,
        "new_tables": new_tables,
        "removed_tables": removed_tables,
        "changed_tables": changed_tables,
        "new_source_tables": new_source_tables,
        "removed_source_tables": removed_source_tables,
        "existing_sources_doc": existing_sources_doc,
        "fresh_sources_doc": fresh_sources_doc,
        "adopted_names": adopted_names,
        "scoped_to": sorted(str(d) for d in scope_dirs),
        "dbt_output_tables": sorted(dbt_output_tables),
    }


def _report_json(
    report: dict,
    *,
    written: "list[str] | None" = None,
    preserved: "dict[str, list[str]] | None" = None,
) -> str:
    payload = {
        "adopted_names": report.get("adopted_names", {}),
        "scoped_to": report.get("scoped_to", []),
        "dbt_output_tables": report.get("dbt_output_tables", []),
        "new_tables": report["new_tables"],
        "removed_tables": report["removed_tables"],
        "changed_tables": report["changed_tables"],
        "new_source_tables": report["new_source_tables"],
        "removed_source_tables": report["removed_source_tables"],
    }
    if written is not None:
        payload["written"] = written
    if preserved:
        payload["preserved_meta"] = preserved
    return json.dumps(payload, indent=2)


def _meta_delta(current: dict, new: dict) -> str:
    """One-line `key: old -> new` summary of a single column's meta change."""
    keys = sorted(set(current or {}) | set(new or {}))
    parts = []
    for k in keys:
        cur, nxt = (current or {}).get(k), (new or {}).get(k)
        if cur == nxt:
            continue
        parts.append(f"`{k}`: {cur!r} → {nxt!r}" if cur is not None and nxt is not None
                     else f"`{k}`: + {nxt!r}" if cur is None
                     else f"`{k}`: − {cur!r}")
    return "; ".join(parts) or "(no scalar delta)"


def _md_section(heading: str, intro: str, items: list) -> list:
    """A `### heading` + optional intro + bulleted items, or nothing when empty."""
    if not items:
        return []
    out = [heading, ""]
    if intro:
        out.append(intro)
    return out + list(items) + [""]


def _md_summary(counts: dict) -> list:
    return [
        "## dbt project change-set", "",
        "| | count |", "|---|---|",
        f"| new tables | {counts['new_tables']} |",
        f"| removed tables (never auto-applied) | {counts['removed_tables']} |",
        f"| changed tables | {counts['changed_tables']} |",
        f"| new source tables | {counts['new_source_tables']} |",
        f"| removed source tables (never auto-applied) | {counts['removed_source_tables']} |",
        "",
    ]


# What each per-column key in a `changed_tables` entry says, in report order.
# A table rather than a chain of `if`s so adding a key to the change-set is one
# row here, not another branch — and so the report can never silently omit one.
_COLUMN_CHANGE_LINES = (
    ("new_columns", "new column", False),
    ("removed_columns",
     "removed in ThoughtSpot (dropped only if it carries nothing but `ts_*` meta)", False),
    ("modified_meta", None, True),           # rendered via _meta_delta
    ("modified_description", "description changed", True),
    ("new_relationship", "new relationships test", False),
    ("modified_relationship", "relationships test changed", True),
    ("removed_relationship",
     "relationships test removed in ThoughtSpot (never auto-deleted)", False),
)


def _md_changed_table(table: str, diff: dict) -> list:
    out = [f"**{table}**", ""]
    for key, label, is_entry in _COLUMN_CHANGE_LINES:
        for item in diff.get(key) or []:
            if not is_entry:
                out.append(f"- `{item}` — {label}")
            elif label is None:
                out.append(f"- `{item['column']}` — "
                           f"{_meta_delta(item.get('current'), item.get('new'))}")
            else:
                out.append(f"- `{item['column']}` — {label}")
    return out + [""]


def render_report_markdown(
    report: dict,
    *,
    written: "list[str] | None" = None,
    preserved: "dict[str, list[str]] | None" = None,
    dry_run: bool = False,
) -> str:
    """Render a Case B change-set as markdown for a human (or an LLM) to read.

    The JSON on stdout stays the contract for anything scripted; this is the
    same data shaped so the reviewer does not have to hold a nested dict in
    their head. Written here, beside `build_case_b_report`, so `diff` and
    `sync --dry-run` render through one function and cannot describe the same
    change-set differently.

    It leads with the actions that need a decision — the two `removed_*` lists
    are never applied automatically — because those are the only lines where
    reading the report changes what happens next.
    """
    got = {k: report.get(k) or default for k, default in _REPORT_KEYS}
    lines = _md_summary({k: len(v) for k, v in got.items()})
    lines += _md_removals(got["removed_tables"], got["removed_source_tables"])
    lines += _md_section("### New tables", "",
                         [f"- `{t}`" for t in got["new_tables"]])
    lines += _md_section("### New source tables", "",
                         [f"- `{t}`" for t in got["new_source_tables"]])
    lines += _md_changed_tables(got["changed_tables"])
    lines += _md_written(written, dry_run)
    lines += _md_preserved(preserved)
    return "\n".join(lines).rstrip() + "\n"


_REPORT_KEYS = (
    ("new_tables", []), ("removed_tables", []), ("changed_tables", {}),
    ("new_source_tables", []), ("removed_source_tables", []),
)


def _md_removals(removed_tables: list, removed_source_tables: list) -> list:
    if not (removed_tables or removed_source_tables):
        return []
    return (
        ["### Needs a decision — never applied automatically", ""]
        + _md_section(
            "", "ThoughtSpot no longer produces these dbt models. Deleting a dbt "
                "model is not this tool's call:",
            [f"- `{t}`" for t in removed_tables])[1:]
        + _md_section(
            "", "Source-table entries with no matching Table in the Model:",
            [f"- `{t}`" for t in removed_source_tables])[1:]
    )


def _md_changed_tables(changed: dict) -> list:
    if not changed:
        return []
    out = ["### Changed tables", ""]
    for table, diff in sorted(changed.items()):
        out += _md_changed_table(table, diff)
    return out


def _md_written(written: "list[str] | None", dry_run: bool) -> list:
    if written is None:
        return []
    return _md_section(
        f"### {'Would apply' if dry_run else 'Applied'}", "",
        [f"- {w}" for w in written] or ["- (nothing to write)"])


def _md_preserved(preserved: "dict[str, list[str]] | None") -> list:
    if not preserved:
        return []
    total = sum(len(v) for v in preserved.values())
    return _md_section(
        f"### Preserved — {total} hand-authored `ts_*` tag(s)",
        "Outside `ts dbt-export build`'s own vocabulary, so left exactly as written:",
        [f"- `{where}`: {', '.join(keys)}" for where, keys in sorted(preserved.items())])


def _merge_ts_meta(existing_meta: dict, fresh_meta: dict, owned: "frozenset[str]") -> dict:
    """Merge the generator's own ts_* keys into existing_meta.

    Three classes of key, three behaviours:

    - **non-`ts_*`** — preserved. Another tool owns it.
    - **`ts_*` in `owned`** — replaced by the fresh value, or cleared when the
      fresh generation has none (the property was removed in ThoughtSpot, so it
      should leave schema.yml too). This is the actual sync.
    - **`ts_*` NOT in `owned`** — preserved. `ts dbt-export build` cannot
      produce this key, so a human wrote it: `ts_hidden`, `ts_calendar_type`,
      `ts_currency_type`, `ts_geo_config` (all documented ThoughtSpot tags this
      generator deliberately never emits), `ts_column_exclude`, or a tag from a
      newer ThoughtSpot than this build knows about.

    That third class is the fix for a silent-data-loss bug: the previous
    implementation cleared every `ts_*` key not present in the fresh meta, so
    `sync --update-metadata` deleted hand-authored tags with no diagnostic. The
    caller reports what was preserved (`_unmanaged_ts_keys`) so the boundary is
    visible rather than merely safe.

    The fresh side is filtered on the `ts_` prefix rather than on `owned`, so a
    tag a future emitter adds still gets written even if `owned` has not caught
    up — it just won't be cleared until it's declared. Failing in the
    write-it-anyway direction is the safer drift.
    """
    result = {k: v for k, v in existing_meta.items() if k not in owned}
    result.update({k: v for k, v in fresh_meta.items() if k.startswith("ts_")})
    return result


def _unmanaged_ts_keys(existing_meta: dict, owned: "frozenset[str]") -> list[str]:
    """`ts_*` keys present in existing_meta that this generator does not own —
    i.e. the ones `_merge_ts_meta` deliberately leaves untouched."""
    return sorted(
        k for k in existing_meta
        if k.startswith("ts_") and k not in owned
    )


def _merge_and_record(
    existing_meta: dict, fresh_meta: dict, owned: "frozenset[str]",
    label: str, preserved: dict,
) -> dict:
    """`_merge_ts_meta`, recording under `label` any unmanaged `ts_*` key the
    merge left alone so the caller can report it."""
    kept = _unmanaged_ts_keys(existing_meta, owned)
    if kept:
        preserved[label] = kept
    return _merge_ts_meta(existing_meta, fresh_meta, owned)


def _is_ts_only_column(col_entry: dict) -> bool:
    """True if a column entry contains ONLY ts_*-originated content.

    A column is safe to auto-delete when ThoughtSpot removes it if:
    - all config.meta keys are ts_* prefixed (no custom keys from other tools)
    - there is no `description` (could be manually authored)
    - there are no data_tests beyond a `relationships` test (which we manage)

    A column that fails any of these checks is left for manual review.
    """
    meta = ((col_entry.get("config") or {}).get("meta")) or {}
    from ts_cli.dbt_build_export import is_column_excluded
    if is_column_excluded(meta):          # excluded on purpose — not "deleted by ThoughtSpot"
        return False
    if any(not k.startswith("ts_") for k in meta):
        return False
    if col_entry.get("description"):
        return False
    tests = col_entry.get("data_tests") or col_entry.get("tests") or []
    non_rel = [t for t in tests if not (isinstance(t, dict) and "relationships" in t)]
    return not non_rel


def _first_relationship_test_dict(col: dict) -> "dict | None":
    """Return the first `relationships` test dict from data_tests/tests, or None."""
    for test in (col.get("data_tests") or col.get("tests") or []):
        if isinstance(test, dict) and "relationships" in test:
            return test
    return None


def _set_or_replace_relationship_test(col_entry: dict, fresh_test: dict) -> None:
    """Replace an existing relationship test, or append one if absent."""
    tests_key = "data_tests" if "data_tests" in col_entry else "tests"
    tests = col_entry.get(tests_key) or []
    tests = [t for t in tests if not (isinstance(t, dict) and "relationships" in t)]
    tests.append(fresh_test)
    col_entry[tests_key] = tests
