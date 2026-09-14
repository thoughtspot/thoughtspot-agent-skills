"""Compiled dbt `manifest.json` (+ `catalog.json`) -> ThoughtSpot Model TML.

The Path Y reader behind `ts dbt build-model`: reads `ts_join_*` relationship
tests, `ts_*` column meta, MetricFlow `semantic_models`/`metrics` and
model-level `ts_rls_rules` out of a compiled manifest and assembles one unified
Model TML. Columns carrying no `ts_*` meta are typed from `catalog.json`.

Split out of `dbt_build_export.py` under the `check_file_size` gate
(pure functions, no I/O).
"""
from __future__ import annotations

import os
import re
from collections import defaultdict

from .node_paths import model_in_path, join_test_in_path
from .tags import (
    _AGG_MAP,
    _COL_TYPE_MAP,
    _TS_INDEX_TYPE_REVERSE_MAP,
    _formula_id,
    infer_column_meta,
    is_column_excluded,
    prettify_column_name,
    tml_properties_from_ts_meta,
)

def extract_model_rls_from_manifest(manifest: dict, model_path: str) -> dict[str, dict]:
    """Extract ts_rls_rules from compiled manifest model nodes.

    Parallel to extract_table_rls_from_schema_yml but reads from a compiled
    dbt manifest dict instead of raw schema.yml text.  dbt compiles model-level
    config.meta (including ts_rls_rules) into the manifest on each job run, so
    this returns the same data as the schema.yml reader without needing the
    source file.

    Returns {TABLE_NAME_UPPER: rls_rules_block} for each model in model_path
    that carries ts_rls_rules under config.meta.  The caller should export the
    current Table TML, merge in the rls_rules block, and re-import.
    """
    result: dict[str, dict] = {}
    for node in manifest.get("nodes", {}).values():
        # Exact dirname, matching inspect.py's rls_models. This was a substring
        # match, which also swept in a sibling directory sharing the prefix
        # (`models/staging` picking up `models/staging_archive`) and disagreed
        # with what `ts dbt inspect` reported for the same path.
        if not model_in_path(node, model_path):
            continue
        model_name = node.get("name")
        if not model_name:
            continue
        model_meta = (node.get("config") or {}).get("meta") or {}
        ts_rls = model_meta.get("ts_rls_rules")
        if not ts_rls:
            continue

        table_name = model_name.upper()
        table_paths_out: list[dict] = []
        rules_out: list[dict] = []
        seen_path_ids: set[str] = set()

        for rule in ts_rls:
            rules_out.append({"name": rule["name"], "expr": rule["expr"]})
            for tp in (rule.get("table_paths") or []):
                if tp["id"] not in seen_path_ids:
                    seen_path_ids.add(tp["id"])
                    table_paths_out.append({
                        "id": tp["id"],
                        "table": tp["table"],
                        "column": tp.get("columns") or [],
                    })

        all_tables = sorted({tp["table"] for tp in table_paths_out})
        result[table_name] = {
            "tables": [{"name": t} for t in all_tables],
            "table_paths": table_paths_out,
            "rules": rules_out,
        }

    return result
def manifest_table_locations(manifest: dict) -> dict[str, dict]:
    """Map each model's ThoughtSpot Table name to its warehouse location.

    Returns {TABLE_NAME_UPPER: {"database", "schema", "db_table"}} for every
    model node in the manifest (not just one directory — join targets may live
    outside ``model_path``).  ``db_table`` is the model's ``alias`` (what dbt
    actually materialised), falling back to ``name``.  Used by
    ``ts dbt build-model`` to disambiguate same-named Tables in an Org.
    """
    out: dict[str, dict] = {}
    for node in manifest.get("nodes", {}).values():
        if node.get("resource_type") != "model" or not node.get("name"):
            continue
        out[node["name"].upper()] = {
            "database": node.get("database") or "",
            "schema": node.get("schema") or "",
            "db_table": node.get("alias") or node["name"],
        }
    return out


def apply_table_fqns(model_tml: dict, table_guids: dict[str, str]) -> dict:
    """Add ``fqn`` to each ``model_tables[]`` entry whose name has a resolved GUID.

    A name-only ``model_tables[]`` reference fails to import when the Org holds
    more than one LOGICAL_TABLE with that name (ThoughtSpot error 14502 "Found
    multiple data sources with same name"); ``fqn`` pins the reference.
    Entries without a resolved GUID are left name-only.  Mutates and returns
    ``model_tml``.
    """
    for entry in model_tml.get("model", {}).get("model_tables", []):
        guid = table_guids.get(entry.get("name", ""))
        if guid:
            entry["fqn"] = guid
    return model_tml
def build_model_tml_from_manifest(
    manifest: dict,
    catalog: dict,
    model_path: str,
    model_name: str,
    pretty_names: bool = False,
    metrics: bool = True,
) -> dict:
    """Build a ThoughtSpot Model TML dict from dbt Cloud job artifacts.

    Uses ts_join_* relationship tests from the manifest for the join graph and
    manifest column meta for ts_* column properties. Returns {"model": {...}}
    with no guid — suitable for first-import via ts tml import.

    Display names: a column's ``ts_display_name`` meta tag always wins; otherwise
    the warehouse name is used verbatim, or passed through
    :func:`prettify_column_name` when ``pretty_names`` is set. ``column_id``
    always keeps the physical ``TABLE::COLUMN`` form. Formula columns keep the
    name given in schema.yml either way.

    MetricFlow: when ``metrics`` is true (default), in-scope ``semantic_models``/
    ``metrics`` from the manifest are translated to formulas via
    :func:`ts_cli.dbt_metricflow.translate_metrics` and appended. A metric whose
    label matches a ``ts_formula`` column (case-insensitive) supersedes it. The
    translation report is returned under ``_metrics_report`` (diagnostics only —
    the caller strips it), alongside ``_excluded_columns``.
    """
    # Collect model nodes whose original_file_path lives in model_path
    model_nodes: dict[str, dict] = {}
    for node in manifest.get("nodes", {}).values():
        if model_in_path(node, model_path):
            model_nodes[node["name"]] = node

    dbt_to_table: dict[str, str] = {n: n.upper() for n in model_nodes}

    # Collect relationship tests with ts_join_* meta in this directory
    joins_by_table: dict[str, list[dict]] = defaultdict(list)
    for node in manifest.get("nodes", {}).values():
        if node.get("resource_type") != "test":
            continue
        # Placed by the model the test is ATTACHED to, not by the schema.yml
        # declaring it — the same predicate inspect.py's ts_join_tests uses, so
        # the two cannot disagree about a directory's join graph (open-items #18).
        if not join_test_in_path(manifest, node, model_path):
            continue
        tm = node.get("test_metadata", {})
        if tm.get("name") != "relationships":
            continue
        meta = (node.get("config") or {}).get("meta") or {}
        if not any(k.startswith("ts_join_") for k in meta):
            continue

        kwargs = tm.get("kwargs", {})
        # source model is wrapped: {{ get_where_subquery(ref('name')) }} — use search
        src_m = re.search(r"""ref\(['"]([^'"]+)['"]\)""", kwargs.get("model", ""))
        tgt_m = re.search(r"""ref\(['"]([^'"]+)['"]\)""", kwargs.get("to", ""))
        if not src_m or not tgt_m:
            continue

        source_table = src_m.group(1).upper()
        target_table = tgt_m.group(1).upper()
        col_name = kwargs.get("column_name", "")
        right_field = kwargs.get("field", col_name)

        joins_by_table[source_table].append({
            "name": meta.get("ts_join_name") or f"{src_m.group(1)}_to_{tgt_m.group(1)}",
            "with": target_table,
            "on": f"[{source_table}::{col_name}] = [{target_table}::{right_field}]",
            "type": (meta.get("ts_join_type") or "left_outer").upper(),
            "cardinality": (meta.get("ts_join_cardinality") or "many_to_one").upper(),
        })

    # MetricFlow entities → joins, only for table pairs no ts_join_* test covers.
    entity_join_report: list[dict] = []
    if metrics:
        from ts_cli.dbt_metricflow import entity_joins, semantic_models_in_scope  # lazy import
        covered = {(src, j["with"]) for src, jl in joins_by_table.items() for j in jl}
        for ej in entity_joins(semantic_models_in_scope(manifest, model_path)):
            pair = (ej["source"], ej["target"])
            if pair in covered or (ej["target"], ej["source"]) in covered:
                continue
            covered.add(pair)
            joins_by_table[ej["source"]].append(dict(ej["join"]))
            entity_join_report.append(ej)

    # All tables: model tables + join targets (in case target is outside model_path)
    all_tables: set[str] = set(dbt_to_table.values())
    for jl in joins_by_table.values():
        for j in jl:
            all_tables.add(j["with"])

    # Order: tables with outgoing joins first, then sorted remainder
    tables_with_joins = [t for t in dbt_to_table.values() if t in joins_by_table]
    tables_without_joins = sorted(all_tables - set(tables_with_joins))
    seen: set[str] = set()
    table_order: list[str] = []
    for t in tables_with_joins + tables_without_joins:
        if t not in seen:
            seen.add(t)
            table_order.append(t)

    # model_tables[]
    model_tables_tml = []
    for table_name in table_order:
        entry: dict = {"id": table_name, "name": table_name}
        joins = joins_by_table.get(table_name)
        if joins:
            entry["joins"] = list(joins)
        model_tables_tml.append(entry)

    # Column metadata from manifest model nodes. Columns with no ts_* meta — declared
    # without meta, or present only in catalog.json — are still included: their type is
    # inferred from catalog.json (numeric → MEASURE/SUM) unless the column is a MetricFlow
    # entity or dimension (always ATTRIBUTE).
    col_meta_by_table: dict[str, dict[str, dict]] = {}
    col_desc_by_table: dict[str, dict[str, str]] = {}
    excluded_columns: list[str] = []          # TABLE::COL left out via ts_column_exclude
    inferred_columns: list[str] = []          # TABLE::COL typed from catalog.json, no ts_* meta
    catalog_nodes = (catalog or {}).get("nodes") or {}
    for dbt_name, node in model_nodes.items():
        table_name = dbt_name.upper()
        col_meta_by_table[table_name] = {}
        col_desc_by_table[table_name] = {}
        cat_cols = {k.upper(): v for k, v in
                    ((catalog_nodes.get(node.get("unique_id", "")) or {}).get("columns") or {}).items()}
        mf_attr_cols = {c.upper() for c, col in (node.get("columns") or {}).items()
                        if col.get("entity") or col.get("dimension")}
        for col_name, col in (node.get("columns") or {}).items():
            col_meta = (col.get("config") or {}).get("meta") or col.get("meta") or {}
            if is_column_excluded(col_meta):
                excluded_columns.append(f"{table_name}::{col_name}")
                continue
            if col_meta:
                col_meta_by_table[table_name][col_name] = col_meta
            else:
                cat_type = str((cat_cols.get(col_name.upper()) or {}).get("type") or "")
                col_meta_by_table[table_name][col_name] = infer_column_meta(
                    cat_type, is_mf_attribute=col_name.upper() in mf_attr_cols,
                    column_name=col_name)
                inferred_columns.append(f"{table_name}::{col_name}")
            desc = col.get("description")
            if desc:
                col_desc_by_table[table_name][col_name] = desc
        # Physical columns present in catalog.json but never declared in schema.yml
        # (common in a MetricFlow-only project that lists just entities/dimensions).
        declared = {c.upper() for c in (node.get("columns") or {})}
        for cat_name, cat_col in cat_cols.items():
            if cat_name in declared:
                continue
            col_meta_by_table[table_name][cat_col.get("name") or cat_name] = infer_column_meta(
                str(cat_col.get("type") or ""), is_mf_attribute=False,
                column_name=cat_col.get("name") or cat_name)
            inferred_columns.append(f"{table_name}::{cat_col.get('name') or cat_name}")

    # columns[] — deduplicate names across tables (prefix with table name when collision)
    col_name_counts: dict[str, int] = defaultdict(int)
    for table_name in table_order:
        for col_name, meta in (col_meta_by_table.get(table_name) or {}).items():
            if not meta.get("ts_formula"):
                col_name_counts[col_name] += 1

    columns: list[dict] = []
    formulas: list[dict] = []
    formula_col_entries: list[dict] = []

    for table_name in table_order:
        for col_name, meta in (col_meta_by_table.get(table_name) or {}).items():
            if meta.get("ts_formula"):
                fid = _formula_id(col_name)
                formulas.append({"id": fid, "name": col_name, "expr": meta["ts_formula"]})
                props_f = tml_properties_from_ts_meta(meta)
                props_f.setdefault("column_type", "ATTRIBUTE")
                if props_f["column_type"] != "MEASURE":
                    props_f.pop("aggregation", None)
                entry_f: dict = {"name": col_name, "formula_id": fid, "properties": props_f}
                desc_f = (col_desc_by_table.get(table_name) or {}).get(col_name)
                if desc_f:
                    entry_f["description"] = desc_f
                formula_col_entries.append(entry_f)
                continue

            display_name = (
                f"{table_name}_{col_name}" if col_name_counts[col_name] > 1 else col_name
            )
            if meta.get("ts_display_name"):
                display_name = str(meta["ts_display_name"]).strip()
            elif pretty_names:
                display_name = prettify_column_name(display_name)
            props = tml_properties_from_ts_meta(meta)

            col_doc: dict = {"name": display_name, "column_id": f"{table_name}::{col_name}"}
            desc = (col_desc_by_table.get(table_name) or {}).get(col_name)
            if desc:
                col_doc["description"] = desc
            if props:
                col_doc["properties"] = props
            columns.append(col_doc)

    metrics_report: dict | None = None
    if metrics:
        from ts_cli.dbt_metricflow import translate_metrics   # lazy — avoids a circular import
        metrics_report = translate_metrics(
            manifest, model_path, {f["name"] for f in formulas})
        if metrics_report["superseded"]:
            drop = {n.lower() for n in metrics_report["superseded"]}
            formulas = [f for f in formulas if f["name"].lower() not in drop]
            formula_col_entries = [
                c for c in formula_col_entries if c["name"].lower() not in drop]
        formulas.extend(metrics_report["formulas"])
        formula_col_entries.extend(metrics_report["columns"])

    # An inferred (untagged) physical column may prettify to the same name as a
    # metric-derived formula — the docs' own pattern (TRANSACTION_TOTAL column vs the
    # `transaction_total` metric). There is no schema.yml entry to hang a
    # ts_display_name on, so resolve it here with the table-prefix convention already
    # used for cross-table duplicates; declared columns still fail fast (caller).
    inferred_renames: list[dict] = []
    inferred_set = set(inferred_columns)
    formula_names_lower = {c["name"].lower() for c in formula_col_entries}
    for col_doc in columns:
        if col_doc["column_id"] in inferred_set and col_doc["name"].lower() in formula_names_lower:
            table_name, col_name = col_doc["column_id"].split("::", 1)
            new_name = f"{table_name}_{col_name}"
            if pretty_names:
                new_name = prettify_column_name(new_name)
            inferred_renames.append({"column_id": col_doc["column_id"],
                                     "from": col_doc["name"], "to": new_name})
            col_doc["name"] = new_name

    model_doc: dict = {
        "name": model_name,
        "model_tables": model_tables_tml,
        "columns": columns + formula_col_entries,
    }
    if formulas:
        model_doc["formulas"] = formulas
    out: dict = {"model": model_doc}
    if excluded_columns:
        out["_excluded_columns"] = sorted(excluded_columns)   # diagnostics only — caller strips
    if inferred_columns:
        out["_inferred_columns"] = sorted(inferred_columns)   # diagnostics only — caller strips
    if inferred_renames:
        out["_inferred_renames"] = inferred_renames           # diagnostics only — caller strips
    if metrics_report is not None:
        metrics_report["entity_joins"] = entity_join_report
    if metrics_report and (metrics_report["formulas"] or metrics_report["unmapped"]
                           or metrics_report["entity_joins"]):
        out["_metrics_report"] = metrics_report                # diagnostics only — caller strips
    return out
