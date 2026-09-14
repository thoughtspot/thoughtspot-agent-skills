"""ThoughtSpot Model TML → dbt project files (ts-convert-to-dbt, Case A: scaffold).

Pure functions: dicts in, {relative_path: file_content} out. No I/O, no network —
the command layer (commands/dbt_export.py) handles TML export and file writes.

Reuses the dialect-agnostic parsing in tml_model_parse.py (column index, column_id
resolution, dimension/metric classification, join-graph walk) — the same substrate
sv_build_sv.py uses for Snowflake Semantic Views.

Emits ONE artifact per ThoughtSpot model_table by default (`models/schema.yml`)
and a second, complementary one behind `emit_semantic_models`, per
agents/cli/ts-convert-to-dbt/references/open-items.md's design decision (2026-08-27,
prompted by a direct question about whether ThoughtSpot's `ts_*` dbt metadata tags
and MetricFlow integration had been incorporated — they had not, in an earlier
version of this module):

1. **`models/schema.yml`** — the PRIMARY mechanism. Plain dbt `columns:`/
   `data_tests:` with ThoughtSpot's own `ts_*` metadata tags under `meta:`
   (`ts_column_type`, `ts_aggregation`, `ts_synonym`, `ts_format_pattern`,
   `ts_index_type`, `ts_index_priority`, `ts_attr_dim`, `ts_additive`,
   `ts_spotiq_pref` on columns; `ts_join_cardinality`/`ts_join_type`/
   `ts_join_name` on a `relationships:` test). Read by the SAME base dbt sync
   `ts dbt generate-tml`/`generate-sync-tml` already drives (see
   commands/dbt.py) — but NOT directly, and NOT the same way for every
   connection type. For a `ZIP_FILE` connection (dbt Core, or a
   dbt-Cloud-managed repo compiled locally), ThoughtSpot reads dbt's COMPILED
   `manifest.json`/`catalog.json` (`file_content` on `dbtGenerateTml`,
   verified via the REST API spec 2026-08-27), not this raw source file — a
   `dbt run`/`dbt compile` + `dbt docs generate` step in between compiles
   `meta:` through into `manifest.json`. For a `DBT_CLOUD` connection there is
   no local artifact file at all — ThoughtSpot calls the dbt Cloud API
   directly, so the hand-off is committing these generated files into the
   dbt-Cloud-connected repo and letting a dbt Cloud job run. This module's job
   stops at a valid, compilable dbt project either way (see open-items.md #7
   for the scope decision and the two hand-off paths). Tag list verified
   against docs.thoughtspot.com/cloud/
   26.8.0.cl/dbt-integration-metadata-tags (2026-08-27) — exhaustive, with
   exact YAML nesting. TML property→tag mapping verified against
   agents/shared/schemas/thoughtspot-model-tml.md, this repo's own
   live-census-verified reference. `is_hidden` and `calendar` are
   deliberately NEVER emitted — that schema doc explicitly warns against
   emitting either during model generation.

   YAML shape targets the CURRENT dbt config syntax (`config: {meta: ...}`
   on columns, `data_tests:` + `arguments: {to, field}` + `config: {meta:
   ...}` on a generic test) rather than the older bare `meta:`/`tests:`/
   `to:`/`field:` shape ThoughtSpot's own docs example happens to show —
   live-verified against a real `dbt-fusion parse` (dbt-fusion
   2.0.0-preview.212, 2026-08-27): the bare/older shape produced hard parse
   ERRORS in this build (even for a plain column-level `meta:`, unrelated to
   any test), while the current syntax parsed clean. Prioritized real-tool
   compatibility over matching a docs example that is plausibly stale
   relative to current dbt tooling — the same class of "product moved past
   its own docs" issue this repo has hit before (Worksheet→Model, v1→v2
   endpoints). Verified against dbt-fusion AND dbt-core 1.12.4 (2026-09-10):
   a generated project parses clean and its manifest carries the `alias`, every
   `ts_*` column tag and every `ts_join_*` test — see open-items.md #8.

2. **`models/semantic_models.yml`** — a SECONDARY artifact, emitted only when
   `emit_semantic_models=True` (`--semantic-models`). Off by default because it
   makes the project fail `dbt parse` under dbt-core whenever a semantic model
   carries a time dimension: dbt-core requires a `metricflow_time_spine` model
   and this generator emits none. It is the legacy
   top-level `semantic_models:`/`metrics:` MetricFlow spec (entities/dimensions/
   measures), for ThoughtSpot's separate MetricFlow-import enrichment. ThoughtSpot
   documents dbt support only through "dbt 1.7 and earlier" (docs.thoughtspot.com/
   cloud/26.8.0.cl/dbt-metricflow-integration), which predates dbt's CURRENT nested
   semantic-layer spec (needs dbt Core 1.12+) — so this targets the older top-level
   shape. **Not live-verified against ThoughtSpot's actual importer** (no live
   ThoughtSpot + dbt Cloud connection in this environment) — see open-items.md #2.
   ThoughtSpot's own join_type/cardinality/name have no representation in this
   spec at all (MetricFlow entities are pure identity, no join metadata) — that
   fidelity lives only in artifact #1.

Formula (calculated) columns are NOT translated in either artifact — dbt's metric
taxonomy is a structurally different problem from SQL-text translation and needs
its own reference file (ts-dbt-formula-translation.md, not yet written). Every
formula column is reported in ``skipped_formulas``, never silently dropped.

Formula round-trip: ``build_dbt_export`` writes formulas to ``schema.yml`` as
``ts_formula`` meta config entries so they are version-controlled in the dbt project
and flow back to ThoughtSpot via ``build_model_tml_from_schema_yml`` on resync.
"""
from __future__ import annotations

import os
import re
from collections import defaultdict

import yaml

from .dbt.tags import (
    _NO_TAG_PROPS,
    _PASSTHROUGH_PROPS,
    _TS_INDEX_TYPE_MAP,
    _apply_index_type,
    _build_column_meta,
    _first_table_ref,
    prettify_column_name as _prettify_column_name,
)
from .tml_model_parse import (
    build_column_index,
    build_table_maps,
    classify_column,
    collect_join_data,
    resolve_column_id,
    to_snake,
)


# ---------------------------------------------------------------------------
# Column classification — grouped by owning table node
# ---------------------------------------------------------------------------
def _classify_model_columns(
    columns: list[dict],
    formulas_by_id: dict[str, dict],
    mt_names: dict[str, str],
    col_index: dict[tuple[str, str], dict],
    mt_phys: dict[str, str],
) -> tuple[list[dict], list[dict], list[dict]]:
    """Classify model columns into resolved entries + skipped formulas + formula entries.

    Each resolved entry: {alias, display_name, table, db_col, kind, agg,
    synonyms, comment, <passthrough TML properties>} where kind is
    'dimension' | 'time_dimension' | 'metric' and table is the owning node key
    (alias for a role-play).

    Formula entries have the first [TABLE::COLUMN] reference resolved to the
    owning node key; formulas with no table reference go to skipped_formulas.
    """
    entries: list[dict] = []
    skipped_formulas: list[dict] = []
    formula_entries: list[dict] = []
    table_name_to_node: dict[str, str] = {v: k for k, v in mt_names.items()}

    for col in columns:
        col_name = col.get("name", "")
        alias = to_snake(col_name)
        props = col.get("properties") or {}

        if col.get("formula_id"):
            fid = col["formula_id"]
            formula = formulas_by_id.get(fid)
            expr = formula.get("expr", "") if formula else ""
            first_table = _first_table_ref(expr)
            target_node = table_name_to_node.get(first_table, "") if first_table else ""
            if target_node:
                is_measure = (props.get("column_type") or "") == "MEASURE"
                fe = {
                    "name": col_name,
                    # _build_column_meta reads display_name; a formula column's
                    # display name IS its name, so the two emit paths can share it
                    "display_name": col_name,
                    "ts_formula": expr,
                    "table": target_node,
                    "kind": "metric" if is_measure else "dimension",
                    "agg": props.get("aggregation") if is_measure else None,
                    "synonyms": props.get("synonyms", []),
                    "comment": col.get("description"),
                    "ai_context": props.get("ai_context"),
                }
                # A formula column carries the same property set as a physical
                # one — geo_config and calendar are census-confirmed on
                # formula-backed columns (thoughtspot-model-tml.md, 2026-07-30).
                for key in _PASSTHROUGH_PROPS:
                    fe[key] = props.get(key)
                formula_entries.append(fe)
            else:
                skipped_formulas.append({
                    "name": col_name,
                    "formula_id": fid,
                    "ts_expr": expr,
                    "reason": "no table reference found in formula expression — cannot determine target model",
                })
            continue

        column_id = col.get("column_id", "")
        if not column_id:
            continue
        try:
            table, db_col, data_type = resolve_column_id(
                column_id, mt_names, col_index, mt_phys)
        except ValueError:
            continue

        kind = classify_column(col, formulas_by_id, data_type)
        if kind == "skip":
            continue

        entry = {
            "alias": alias, "display_name": col_name, "table": table,
            "db_col": db_col, "kind": kind,
            "agg": props.get("aggregation") if kind == "metric" else None,
            "synonyms": props.get("synonyms", []),
            "comment": col.get("description"),
            "ai_context": props.get("ai_context"),
        }
        for key in _PASSTHROUGH_PROPS:
            entry[key] = props.get(key)
        entries.append(entry)

    return entries, skipped_formulas, formula_entries
# ---------------------------------------------------------------------------
# Join graph → entities (for semantic_models.yml) + relationship tests (for schema.yml)
# ---------------------------------------------------------------------------

_TS_JOIN_CARDINALITY_VALUES = {"one_to_one", "many_to_one", "one_to_many"}
_TS_JOIN_TYPE_VALUES = {"inner", "left_outer", "right_outer", "full_outer"}


def _build_entities(
    join_data: list[dict],
) -> tuple[dict[str, list[dict]], list[dict]]:
    """Derive per-table MetricFlow entities from the resolved join graph, for
    the legacy semantic_models.yml. A single-column join `A.fk = B.pk` becomes
    a foreign entity on A (named after B) and a primary entity on B —
    MetricFlow matches semantic models across tables by entity *name*, not
    column name. Composite-key joins have no single-column entity
    representation and are reported as skipped, not mis-emitted.

    Returns (entities_by_table: {node_key: [entity dicts]}, skipped_composite).
    """
    entities_by_table: dict[str, list[dict]] = defaultdict(list)
    skipped: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()

    for jd in join_data:
        if len(jd["pairs"]) != 1:
            skipped.append({
                "relationship": jd["name"],
                "reason": "composite join key — entity/relationships-test not emitted",
                "column_count": len(jd["pairs"]),
            })
            continue

        _, left_col, _, right_col = jd["pairs"][0]
        entity_name = to_snake(jd["right_table"])

        right_key = (jd["right_table"], right_col, "primary", entity_name)
        if right_key not in seen:
            seen.add(right_key)
            entities_by_table[jd["right_table"]].append({
                "column": right_col, "type": "primary", "name": entity_name,
            })

        left_key = (jd["left_id"], left_col, "foreign", entity_name)
        if left_key not in seen:
            seen.add(left_key)
            entities_by_table[jd["left_id"]].append({
                "column": left_col, "type": "foreign", "name": entity_name,
            })

    return dict(entities_by_table), skipped


def _build_relationship_tests(
    join_data: list[dict],
    model_names: dict[str, str],
    unmapped_props: list[dict],
) -> dict[str, dict[str, dict]]:
    """Build ts_join_* relationships tests, keyed by (left table node, fk column).

    Only single-column joins are represented (composite joins already reported
    by _build_entities — dbt's own `relationships:` test is single-column too,
    so the limitation is shared by both artifacts, not specific to this one).

    Returns {node_key: {db_col: test_dict}}.
    """
    tests_by_table: dict[str, dict[str, dict]] = defaultdict(dict)

    for jd in join_data:
        if len(jd["pairs"]) != 1:
            continue
        _, left_col, _, right_col = jd["pairs"][0]
        right_model = model_names.get(jd["right_table"])
        if right_model is None:
            continue

        # Prefer the join's own ThoughtSpot name over the derived one, so a
        # round trip does not rename every join in the Model.
        meta: dict = {"ts_join_name": jd.get("ts_name") or jd["name"]}
        cardinality = (jd.get("cardinality") or "").lower()
        if cardinality:
            if cardinality in _TS_JOIN_CARDINALITY_VALUES:
                meta["ts_join_cardinality"] = cardinality
            else:
                unmapped_props.append({
                    "column": None, "property": "join_cardinality", "value": cardinality,
                    "reason": f"no ts_join_cardinality equivalent for '{cardinality}' "
                              f"on join '{jd['name']}'",
                })
        join_type = (jd.get("join_type") or "").lower()
        if join_type:
            if join_type in _TS_JOIN_TYPE_VALUES:
                meta["ts_join_type"] = join_type
            else:
                unmapped_props.append({
                    "column": None, "property": "join_type", "value": join_type,
                    "reason": f"no ts_join_type equivalent for '{join_type}' "
                              f"on join '{jd['name']}'",
                })

        tests_by_table[jd["left_id"]][left_col] = {
            "relationships": {
                "arguments": {"to": f"ref('{right_model}')", "field": right_col},
                "config": {"meta": meta, "severity": "warn"},
            }
        }

    return dict(tests_by_table)


# ---------------------------------------------------------------------------
# schema.yml assembly (primary artifact — ts_* meta tags)
# ---------------------------------------------------------------------------

def _build_schema_columns(
    table_entries: list[dict],
    relationship_tests: dict[str, dict],
    unmapped_props: list[dict],
    formula_entries: list[dict] = (),
) -> list[dict]:
    """Build the `columns:` list for one table's schema.yml model entry,
    merging ts_* meta tags (from Model columns) with relationships tests
    (from the join graph) and formula columns (ts_formula in config.meta).
    A column can carry both when it's both a Model-declared dimension AND
    a join's FK column.
    """
    by_col: dict[str, dict] = {}
    order: list[str] = []

    for e in table_entries:
        col = e["db_col"]
        if col not in by_col:
            by_col[col] = {"name": col}
            order.append(col)
        if e.get("comment"):
            by_col[col]["description"] = e["comment"]
        meta = _build_column_meta(e, unmapped_props)
        _apply_index_type(meta, e)
        ai_ctx = e.get("ai_context")
        if ai_ctx:
            meta["ts_ai_context"] = ai_ctx
        # Model display name, when it isn't the physical name and isn't what
        # `ts dbt build-model --pretty-names` would derive from it anyway.
        display = (e.get("display_name") or "").strip()
        derivable = {col, prettify_column_name(col),
                     # build-model's own dedupe form for same-named columns across tables
                     f"{e.get('table', '')}_{col}", prettify_column_name(f"{e.get('table', '')}_{col}")}
        if display and display not in derivable:
            meta["ts_display_name"] = display
        by_col[col].setdefault("config", {}).setdefault("meta", {}).update(meta)

    for col, test in relationship_tests.items():
        if col not in by_col:
            by_col[col] = {"name": col}
            order.append(col)
        by_col[col].setdefault("data_tests", []).append(test)

    for fe in formula_entries:
        name = fe["name"]
        if name not in by_col:
            by_col[name] = {"name": name}
            order.append(name)
        if fe.get("comment"):
            by_col[name]["description"] = fe["comment"]
        # Same emit path as a physical column, so a formula column gets the
        # full documented tag set rather than the four it used to get.
        meta = _build_column_meta(fe, unmapped_props)
        _apply_index_type(meta, fe)
        if fe.get("ai_context"):
            meta["ts_ai_context"] = fe["ai_context"]
        meta["ts_formula"] = fe["ts_formula"]
        by_col[name].setdefault("config", {}).setdefault("meta", {}).update(meta)

    return [by_col[c] for c in order]


def _build_ts_rls_rules(rls: dict) -> list[dict]:
    """Convert a Table TML rls_rules block to the ts_rls_rules schema.yml list.

    Each entry carries the rule name, expression, and the table_paths it references.
    The top-level `tables` list in TML is derivable from table_paths on read-back
    so it is not stored. `columns` is the key used in schema.yml (TML uses `column`).
    """
    table_paths_tml = rls.get("table_paths") or []
    rules_tml = rls.get("rules") or []
    if not rules_tml:
        return []
    table_paths = [
        {"id": p["id"], "table": p["table"], "columns": p.get("column") or []}
        for p in table_paths_tml
    ]
    result = []
    for rule in rules_tml:
        entry: dict = {"name": rule["name"], "expr": rule["expr"]}
        if table_paths:
            entry["table_paths"] = table_paths
        result.append(entry)
    return result


def _build_schema_docs(
    mt_order: list[str],
    model_names: dict[str, str],
    entries_by_table: dict[str, list[dict]],
    relationship_tests_by_table: dict[str, dict],
    unmapped_props: list[dict],
    formula_entries_by_table: "dict[str, list[dict]] | None" = None,
    rls_by_table: "dict[str, dict] | None" = None,
    aliases: "dict[str, str] | None" = None,
) -> list[dict]:
    docs = []
    for node_key in mt_order:
        table_entries = entries_by_table.get(node_key, [])
        rel_tests = relationship_tests_by_table.get(node_key, {})
        fe = (formula_entries_by_table or {}).get(node_key, [])
        rls = (rls_by_table or {}).get(node_key)
        if not table_entries and not rel_tests and not fe and not rls:
            continue
        columns = _build_schema_columns(table_entries, rel_tests, unmapped_props, fe)
        model_doc: dict = {"name": model_names[node_key]}
        alias = (aliases or {}).get(node_key)
        if alias:
            model_doc.setdefault("config", {})["alias"] = alias
        if rls:
            ts_rls = _build_ts_rls_rules(rls)
            if ts_rls:
                model_doc.setdefault("config", {}).setdefault("meta", {})["ts_rls_rules"] = ts_rls
        model_doc["columns"] = columns
        docs.append(model_doc)
    return docs


def _compute_aliases(
    mt_order: list,
    model_names: dict,
    model_name_overrides: "dict[str, str] | None",
) -> dict:
    """`alias:` for each model whose dbt name differs from its ThoughtSpot Table.

    Without this, `stg_appointments` materialises as `STG_APPOINTMENTS` and the
    return leg brings a **second** Table into ThoughtSpot beside the original
    `APPOINTMENTS` — the Model silently re-points at the copy while the
    original keeps every dependent it had. `alias:` keeps dbt's staging-layer
    file convention while materialising under the name ThoughtSpot already
    knows, so a resync lands on the same object.

    An **adopted** name (Case B, `model_name_overrides`) is never aliased: that
    project's models already materialise somewhere real, and forcing an alias
    would repoint live relations in the warehouse.
    """
    overrides = model_name_overrides or {}
    out = {}
    for node_key in mt_order:
        if node_key in overrides:
            continue
        if model_names.get(node_key) != node_key:
            out[node_key] = node_key
    return out


def find_target_schema_collisions(
    table_tmls: dict, target_schema: str
) -> list:
    """Tables whose own location is the schema dbt is about to write into.

    A model aliased to its Table's name and materialised into that Table's own
    schema would overwrite its own source. dbt does not reliably catch this, so
    it is refused at build time rather than discovered during `dbt run`.

    `target_schema` is `DB.SCHEMA` or a bare `SCHEMA` (matched on the schema
    alone). Comparison is case-insensitive — warehouses vary, and a collision
    that differs only in case is still a collision.
    """
    want = [p.strip().upper() for p in (target_schema or "").split(".") if p.strip()]
    if not want:
        return []
    hits = []
    for name, tml in sorted(table_tmls.items()):
        t = tml.get("table", {})
        db, schema = (t.get("db") or "").upper(), (t.get("schema") or "").upper()
        match = [db, schema] == want if len(want) == 2 else schema == want[0]
        if match:
            hits.append(f"{t.get('db')}.{t.get('schema')}.{name}")
    return hits


# ---------------------------------------------------------------------------
# semantic_models.yml assembly (secondary artifact — legacy MetricFlow spec)
# ---------------------------------------------------------------------------

def _build_legacy_dimension(entry: dict) -> dict:
    if entry["kind"] == "time_dimension":
        return {
            "name": entry["alias"], "type": "time", "expr": entry["db_col"],
            "type_params": {"time_granularity": "day"},
        }
    return {"name": entry["alias"], "type": "categorical", "expr": entry["db_col"]}


def _build_legacy_measures_and_metrics(measures: list[dict]) -> tuple[list[dict], list[dict]]:
    measure_docs = [
        {"name": m["alias"], "agg": (m["agg"] or "SUM").lower(), "expr": m["db_col"]}
        for m in measures
    ]
    metric_docs = [
        {"name": m["alias"], "type": "simple", "type_params": {"measure": m["alias"]}}
        for m in measures
    ]
    return measure_docs, metric_docs


def _build_one_legacy_semantic_model(
    model_name: str, entities: list[dict], table_entries: list[dict],
) -> tuple[dict, list[dict]]:
    """Returns (semantic_model_doc, metric_docs) for one table."""
    dims = [e for e in table_entries if e["kind"] in ("dimension", "time_dimension")]
    measures = [e for e in table_entries if e["kind"] == "metric"]

    doc: dict = {"name": model_name, "model": f"ref('{model_name}')"}
    if entities:
        doc["entities"] = [
            {"name": e["name"], "type": e["type"], "expr": e["column"]}
            for e in entities
        ]
    if dims:
        doc["dimensions"] = [_build_legacy_dimension(e) for e in dims]

    metric_docs: list[dict] = []
    if measures:
        doc["measures"], metric_docs = _build_legacy_measures_and_metrics(measures)

    return doc, metric_docs


def _build_legacy_semantic_docs(
    mt_order: list[str],
    model_names: dict[str, str],
    entities_by_table: dict[str, list[dict]],
    entries_by_table: dict[str, list[dict]],
) -> tuple[list[dict], list[dict]]:
    """Build the legacy top-level `semantic_models:` + `metrics:` lists.

    Returns (semantic_models, metrics). A table with no entities and no
    dimensions/measures contributes nothing — an empty semantic model is not
    useful and dbt's own classic spec requires at least `entities` on record.
    """
    semantic_models: list[dict] = []
    metrics: list[dict] = []

    for node_key in mt_order:
        entities = entities_by_table.get(node_key, [])
        table_entries = entries_by_table.get(node_key, [])
        if not entities and not table_entries:
            continue
        doc, metric_docs = _build_one_legacy_semantic_model(
            model_names[node_key], entities, table_entries)
        semantic_models.append(doc)
        metrics.extend(metric_docs)

    return semantic_models, metrics


# ---------------------------------------------------------------------------
# SQL file assembly
# ---------------------------------------------------------------------------

def _staging_sql(source_name: str, db_table: str) -> str:
    return f"select * from {{{{ source('{source_name}', '{db_table}') }}}}\n"


def _alias_sql(base_model_name: str) -> str:
    return f"select * from {{{{ ref('{base_model_name}') }}}}\n"


def _stg_name(table_name: str) -> str:
    """Return the staging model name, avoiding double stg_ prefix."""
    snake = to_snake(table_name)
    return snake if snake.startswith("stg_") else f"stg_{snake}"


def _compute_model_names(mt_order: list[str], mt_phys: dict[str, str]) -> dict[str, str]:
    """Map every node key (table or role-play alias) to its dbt model name."""
    names: dict[str, str] = {}
    for node_key in mt_order:
        physical = mt_phys.get(node_key, node_key)
        if node_key == physical:
            names[node_key] = _stg_name(physical)
        else:
            names[node_key] = f"dim_{to_snake(node_key)}"
    return names


def _write_sql_files(
    mt_order: list[str], mt_phys: dict[str, str], table_tmls: dict[str, dict],
    source_by_table: dict[str, str], source_name: str, model_names: dict[str, str],
) -> dict[str, str]:
    files: dict[str, str] = {}
    written_staging: set[str] = set()
    for node_key in mt_order:
        physical = mt_phys.get(node_key, node_key)
        model_name = model_names[node_key]
        if node_key == physical:
            if model_name in written_staging:
                continue
            written_staging.add(model_name)
            db_table = table_tmls.get(physical, {}).get("table", {}).get("db_table", physical)
            files[f"models/staging/{model_name}.sql"] = _staging_sql(
                source_by_table.get(physical, source_name), db_table)
        else:
            base_model = model_names[physical] if physical in model_names else _stg_name(physical)
            files[f"models/marts/{model_name}.sql"] = _alias_sql(base_model)
    return files


# ---------------------------------------------------------------------------
# sources.yml / dbt_project.yml
# ---------------------------------------------------------------------------

def group_tables_by_location(
    table_tmls: dict[str, dict],
) -> dict[tuple[str, str], list[tuple[str, str]]]:
    """Group physical tables by (database, schema) → [(physical_name, db_table)].

    dbt `sources:` puts `database:`/`schema:` at the SOURCE level, not per-table
    (verified against docs.getdbt.com/reference/source-properties 2026-08-27 —
    there is no per-table database/schema override) — a Model spanning more
    than one (database, schema) pair needs one `sources:` entry per pair.
    """
    groups: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for phys_name, tml in sorted(table_tmls.items()):
        tbl = tml.get("table", {})
        key = (tbl.get("db", ""), tbl.get("schema", ""))
        groups[key].append((phys_name, tbl.get("db_table", phys_name)))
    return dict(groups)


def source_names_by_table(
    source_name: str, groups: dict[tuple[str, str], list[tuple[str, str]]],
) -> dict[str, str]:
    """Map physical_name → the dbt source name its staging model should reference."""
    multi = len(groups) > 1
    out: dict[str, str] = {}
    for i, (_key, tables) in enumerate(sorted(groups.items())):
        name = source_name if not multi else f"{source_name}_{i + 1}"
        for phys_name, _db_table in tables:
            out[phys_name] = name
    return out


def build_sources_yaml(
    source_name: str, groups: dict[tuple[str, str], list[tuple[str, str]]],
) -> dict:
    """Build the `sources:` document — one entry per distinct (database, schema)."""
    multi = len(groups) > 1
    sources = []
    for i, ((db, schema), tables) in enumerate(sorted(groups.items())):
        name = source_name if not multi else f"{source_name}_{i + 1}"
        entry: dict = {"name": name}
        if db:
            entry["database"] = db
        if schema:
            entry["schema"] = schema
        entry["tables"] = [{"name": db_table} for _phys, db_table in tables]
        sources.append(entry)
    return {"version": 2, "sources": sources}


def build_dbt_project_yaml(project_name: str) -> dict:
    """Minimal dbt_project.yml scaffold for Case A (new project)."""
    return {
        "name": project_name,
        "version": "1.0.0",
        "config-version": 2,
        "profile": project_name,
        "model-paths": ["models"],
        "clean-targets": ["target", "dbt_packages"],
    }


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def _add_semantic_artifact(
    files: dict,
    mt_order: list,
    model_names: dict,
    entities_by_table: dict,
    entries_by_table: dict,
    *,
    enabled: bool,
) -> tuple[bool, bool]:
    """Write `models/semantic_models.yml` into `files` when asked. OFF by default.

    Returns (available, emitted) — "available" meaning the Model had enough to
    build one, so the caller can report a deliberate omission rather than
    leaving the user to wonder where the file went.

    Why off by default: it makes the generated project fail `dbt parse` under
    real dbt-core whenever a semantic model carries a time dimension —

        Parsing Error: The semantic layer requires a time spine model with
        granularity DAY or smaller in the project, but none was found.

    dbt-core wants a `metricflow_time_spine` model beside it and this generator
    emits none (verified against dbt-core 1.12.4 / dbt-snowflake 1.12.0,
    2026-09-10: deleting this one file turned the error into a clean parse).
    dbt-fusion does not enforce it, which is why it went unseen.

    Emitting a time spine to prop the file up would materialise a date table the
    user never asked for, in dialect-specific SQL — a poor trade for an artifact
    with no evidence of a consumer: ThoughtSpot's own MetricFlow importer
    produced NOTHING across three connection shapes (ts-convert-from-dbt
    open-items #14). So the default is a project that parses, and the flag
    exists to keep testing open-items #2.
    """
    semantic_models, metrics = _build_legacy_semantic_docs(
        mt_order, model_names, entities_by_table, entries_by_table)
    if not semantic_models:
        return False, False
    if not enabled:
        return True, False
    doc: dict = {"semantic_models": semantic_models}
    if metrics:
        doc["metrics"] = metrics
    files["models/semantic_models.yml"] = yaml.safe_dump(doc, sort_keys=False)
    return True, True


def build_dbt_export(
    *,
    model_tml: dict,
    table_tmls: dict[str, dict],
    project_name: str,
    source_name: str,
    model_name_overrides: "dict[str, str] | None" = None,
    emit_semantic_models: bool = False,
) -> tuple[dict[str, str], dict]:
    """Assemble a dbt project scaffold from a ThoughtSpot Model TML + Table TMLs.

    Returns ({relative_path: file_content}, build_info). Nothing is silently
    dropped — skipped_formulas/skipped_composite_joins/unmapped_properties
    account for every construct this pass doesn't carry forward.

    ``model_name_overrides`` maps a physical Table name (as in ``model_tables[]``)
    to the dbt model name to use instead of the default ``stg_<table>``. Case B
    (`ts dbt-export diff/sync`) fills it from the models already on disk so an
    existing project's naming is adopted rather than a convention imposed;
    role-play aliases keep their ``dim_`` names.
    """
    model = model_tml.get("model", {})
    columns = model.get("columns", [])
    formulas = model.get("formulas", [])
    model_tables = model.get("model_tables", [])
    formulas_by_id = {f["id"]: f for f in formulas}

    col_index = build_column_index(table_tmls)
    mt_names, _mt_fqns, mt_order, mt_phys = build_table_maps(model_tables, table_tmls)
    join_data, _mt_pks = collect_join_data(model_tables, mt_names, col_index)
    model_names = _compute_model_names(mt_order, mt_phys)
    for node_key in mt_order:
        physical = mt_phys.get(node_key, node_key)
        if node_key == physical and (model_name_overrides or {}).get(physical):
            model_names[node_key] = model_name_overrides[physical]

    entries, skipped_formulas, formula_entries = _classify_model_columns(
        columns, formulas_by_id, mt_names, col_index, mt_phys)
    entities_by_table, skipped_joins = _build_entities(join_data)

    entries_by_table: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        entries_by_table[e["table"]].append(e)

    formula_entries_by_table: dict[str, list[dict]] = defaultdict(list)
    for fe in formula_entries:
        formula_entries_by_table[fe["table"]].append(fe)

    unmapped_props: list[dict] = []
    relationship_tests_by_table = _build_relationship_tests(
        join_data, model_names, unmapped_props)

    # Extract RLS rules from each physical table's TML, keyed by node_key
    rls_by_table: dict[str, dict] = {}
    for node_key in mt_order:
        physical = mt_phys.get(node_key, node_key)
        rls = table_tmls.get(physical, {}).get("table", {}).get("rls_rules")
        if rls:
            rls_by_table[node_key] = rls

    location_groups = group_tables_by_location(table_tmls)
    source_by_table = source_names_by_table(source_name, location_groups)

    files: dict[str, str] = {
        "dbt_project.yml": yaml.safe_dump(
            build_dbt_project_yaml(project_name), sort_keys=False),
        "models/staging/sources.yml": yaml.safe_dump(
            build_sources_yaml(source_name, location_groups), sort_keys=False),
    }
    files.update(_write_sql_files(
        mt_order, mt_phys, table_tmls, source_by_table, source_name, model_names))

    aliases = _compute_aliases(mt_order, model_names, model_name_overrides)
    schema_docs = _build_schema_docs(
        mt_order, model_names, entries_by_table, relationship_tests_by_table,
        unmapped_props, formula_entries_by_table=formula_entries_by_table,
        rls_by_table=rls_by_table or None, aliases=aliases)
    if schema_docs:
        files["models/schema.yml"] = yaml.safe_dump(
            {"version": 2, "models": schema_docs}, sort_keys=False)

    # OFF by default -- see _add_semantic_artifact for why.
    semantic_available, semantic_emitted = _add_semantic_artifact(
        files, mt_order, model_names, entities_by_table, entries_by_table,
        enabled=emit_semantic_models)

    dim_count = sum(1 for e in entries if e["kind"] == "dimension")
    time_dim_count = sum(1 for e in entries if e["kind"] == "time_dimension")
    metric_count = sum(1 for e in entries if e["kind"] == "metric")

    build_info = {
        "tables": len(mt_order),
        "dimensions": dim_count,
        "time_dimensions": time_dim_count,
        "metrics": metric_count,
        "formula_columns": len(formula_entries),
        "skipped_formulas": skipped_formulas,
        "skipped_composite_joins": skipped_joins,
        "unmapped_properties": unmapped_props,
        "files_written": sorted(files.keys()),
        "model_names": sorted(set(model_names.values())),
        # So the command layer can say the artifact was withheld rather than
        # leave the user wondering where it went (and warn when one is emitted
        # with time dimensions, which needs a metricflow_time_spine model).
        "semantic_models_available": semantic_available,
        "semantic_models_emitted": semantic_emitted,
    }
    return files, build_info


# ---------------------------------------------------------------------------
# Re-exports — the module was split under the check_file_size gate
# ---------------------------------------------------------------------------
# Every public name below moved to ts_cli/dbt/ but is re-exported here so no
# import site changed. Same facade pattern as ts_cli/databricks/mv_emit.py.
# Import from the owning module in NEW code; these exist for continuity.

from .dbt.tags import (                                          # noqa: E402,F401
    GENERATED_COLUMN_META_KEYS,
    GENERATED_MODEL_META_KEYS,
    find_display_name_collisions,
    infer_column_meta,
    is_column_excluded,
    prettify_column_name,
    tml_currency_type_from_ts,
    tml_geo_config_from_ts,
    tml_properties_from_ts_meta,
    ts_currency_type_from_tml,
    ts_geo_config_from_tml,
)
from .dbt.manifest import (                                      # noqa: E402,F401
    apply_table_fqns,
    build_model_tml_from_manifest,
    extract_model_rls_from_manifest,
    manifest_table_locations,
)
from .dbt.model_from_schema_yml import (                         # noqa: E402,F401
    build_model_tml_from_schema_yml,
    extract_table_rls_from_schema_yml,
)
