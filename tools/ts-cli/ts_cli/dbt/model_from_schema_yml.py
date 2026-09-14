"""Raw dbt `schema.yml` -> ThoughtSpot Model TML.

The offline return leg behind `ts dbt-export build-model`: the reverse of what
`ts dbt-export build` emits. Reads `ts_*` column meta and `ts_join_*`
relationship tests straight from the source YAML rather than a compiled
manifest, so it needs no dbt run — at the cost of not seeing `catalog.json`
types or MetricFlow metrics.

`extract_table_rls_from_schema_yml` returns model-level `ts_rls_rules` in Table
TML shape; RLS lives on the Table, not the Model, so the caller patches it in.

Split out of `dbt_build_export.py` under the `check_file_size` gate
(pure functions, no I/O).
"""
from __future__ import annotations

from collections import defaultdict

import yaml

from .tags import (
    _formula_id,
    is_column_excluded,
    tml_properties_from_ts_meta,
)

def _extract_ref_name(ref_str: str) -> str:
    """Extract the model name from a dbt ref() call: ref('name') → 'name'."""
    import re
    m = re.match(r"""ref\(['"]([^'"]+)['"]\)""", ref_str.strip())
    return m.group(1) if m else ""


def _table_name_of(model_entry: dict) -> str:
    """The ThoughtSpot Table name a dbt model entry maps to.

    `config.alias` when set, else the model name — always upper-cased. This is
    the relation dbt materialises, which is what ThoughtSpot registers as a
    Table, and it must agree with `manifest.manifest_table_locations`, which
    reads `alias or name` off the compiled manifest for the same reason.
    """
    alias = (model_entry.get("config") or {}).get("alias")
    return str(alias or model_entry.get("name") or "").upper()


def build_model_tml_from_schema_yml(
    schema_yml_text: str,
    model_name: str,
) -> dict:
    """Build a ThoughtSpot Model TML dict from a dbt schema.yml.

    Reads ts_* column meta tags and ts_join_* relationship tests to assemble
    a single unified Model TML — the reverse of what build_dbt_export emits.
    Useful when generate-tml splits a multi-fact ThoughtSpot model into
    multiple models (one per connected component of the FK graph).

    Returns {"model": {...}} — no guid, suitable for a first-import via
    ts tml import.
    """
    doc = yaml.safe_load(schema_yml_text) or {}
    models_list = doc.get("models") or []

    # Map dbt model name → uppercased ThoughtSpot table name.
    # The ALIAS wins where set: that is the relation dbt materialises, and so
    # the Table ThoughtSpot actually holds. Reading the model name instead
    # brings back STG_APPOINTMENTS beside the real APPOINTMENTS -- a duplicate
    # Table, with the Model silently repointed at the copy.
    dbt_to_table: dict[str, str] = {
        m["name"]: _table_name_of(m)
        for m in models_list if m.get("name")
    }

    # Collect per-table column metadata and joins
    col_meta_by_table: dict[str, dict[str, dict]] = {}   # table_name → {col_name → meta}
    col_desc_by_table: dict[str, dict[str, str]] = {}    # table_name → {col_name → description}
    joins_by_table: dict[str, list[dict]] = defaultdict(list)
    excluded_columns: list[str] = []                     # ts_column_exclude, diagnostics only

    for m in models_list:
        dbt_name = m.get("name")
        if not dbt_name:
            continue
        table_name = _table_name_of(m)
        col_meta_by_table[table_name] = {}
        col_desc_by_table[table_name] = {}

        for col in m.get("columns") or []:
            col_name = col.get("name")
            if not col_name:
                continue

            # Support both current `config.meta` syntax and legacy bare `meta`
            col_meta = (col.get("config") or {}).get("meta") or col.get("meta") or {}
            # ts_column_exclude keeps the column on the Table but out of the
            # Model — same semantics as build_model_tml_from_manifest, which
            # honoured it while this reader silently included the column.
            if is_column_excluded(col_meta):
                excluded_columns.append(f"{table_name}::{col_name}")
                continue
            if col_meta:
                col_meta_by_table[table_name][col_name] = col_meta
            col_desc = col.get("description")
            if col_desc:
                col_desc_by_table[table_name][col_name] = col_desc

            # Extract relationship tests → joins
            for test in col.get("data_tests") or []:
                if not isinstance(test, dict):
                    continue
                rel = test.get("relationships")
                if not rel:
                    continue
                args = rel.get("arguments") or {}
                to_ref = args.get("to") or ""
                right_field = args.get("field") or col_name
                right_dbt_name = _extract_ref_name(to_ref)
                if not right_dbt_name:
                    continue
                # `ref()` names the MODEL; resolve it to the materialised
                # relation so an aliased target joins to the right Table.
                right_table = dbt_to_table.get(right_dbt_name, right_dbt_name.upper())

                join_meta = (rel.get("config") or {}).get("meta") or {}
                jn = join_meta.get("ts_join_name") or f"{table_name}_to_{right_table}".lower()
                card_raw = (join_meta.get("ts_join_cardinality") or "many_to_one").upper()
                type_raw = (join_meta.get("ts_join_type") or "left_outer").upper()

                joins_by_table[table_name].append({
                    "name": jn,
                    "with": right_table,
                    "on": f"[{table_name}::{col_name}] = [{right_table}::{right_field}]",
                    "type": type_raw,
                    "cardinality": card_raw,
                })

    # Collect all referenced tables (left + right sides of joins)
    all_tables: set[str] = set(dbt_to_table.values())
    for join_list in joins_by_table.values():
        for j in join_list:
            all_tables.add(j["with"])

    # Order: tables that have joins listed first, then sorted remainder
    tables_with_joins = [t for t in dbt_to_table.values() if t in joins_by_table]
    tables_without_joins = sorted(all_tables - set(tables_with_joins))
    seen: set[str] = set()
    table_order: list[str] = []
    for t in tables_with_joins + tables_without_joins:
        if t not in seen:
            seen.add(t)
            table_order.append(t)

    # Build model_tables[]
    model_tables = []
    for table_name in table_order:
        entry: dict = {"id": table_name, "name": table_name}
        joins = joins_by_table.get(table_name)
        if joins:
            entry["joins"] = [
                {k: v for k, v in j.items()} for j in joins
            ]
        model_tables.append(entry)

    # Build columns[] — column names must be unique across the whole model.
    # When the same physical column name appears in multiple tables (e.g.
    # CUSTOMER_ID on both the fact and dimension table), prefix ALL occurrences
    # with the table name so every display name is distinct.

    # Count how many tables contribute each col_name (exclude formula columns)
    col_name_counts: dict[str, int] = defaultdict(int)
    for table_name in table_order:
        for col_name, meta in (col_meta_by_table.get(table_name) or {}).items():
            if not meta.get("ts_formula"):
                col_name_counts[col_name] += 1

    columns = []
    for table_name in table_order:
        col_meta_map = col_meta_by_table.get(table_name) or {}
        for col_name, meta in col_meta_map.items():
            if meta.get("ts_formula"):
                continue  # handled separately below
            display_name = (
                f"{table_name}_{col_name}" if col_name_counts[col_name] > 1
                else col_name
            )
            # ts_display_name always wins, same precedence as
            # build_model_tml_from_manifest. Without this the reader handed back
            # the physical name and a renamed column lost its name every resync.
            if meta.get("ts_display_name"):
                display_name = str(meta["ts_display_name"]).strip()
            props = tml_properties_from_ts_meta(meta)

            col_doc: dict = {"name": display_name, "column_id": f"{table_name}::{col_name}"}
            desc = (col_desc_by_table.get(table_name) or {}).get(col_name)
            if desc:
                col_doc["description"] = desc
            if props:
                col_doc["properties"] = props
            columns.append(col_doc)

    # Collect formula columns (columns with ts_formula in config.meta)
    formulas: list[dict] = []
    formula_col_entries: list[dict] = []
    for m in models_list:
        for col in m.get("columns") or []:
            col_name = col.get("name")
            if not col_name:
                continue
            col_meta = (col.get("config") or {}).get("meta") or col.get("meta") or {}
            expr = col_meta.get("ts_formula")
            if not expr:
                continue
            # A formula column can be excluded the same way a physical one is
            if is_column_excluded(col_meta):
                continue
            fid = _formula_id(col_name)
            formulas.append({"id": fid, "name": col_name, "expr": expr})
            props_f = tml_properties_from_ts_meta(col_meta)
            # column_type is mandatory on a formula column; default ATTRIBUTE
            props_f.setdefault("column_type", "ATTRIBUTE")
            if props_f["column_type"] != "MEASURE":
                props_f.pop("aggregation", None)
            col_entry_f: dict = {"name": col_name, "formula_id": fid, "properties": props_f}
            col_desc_f = col.get("description")
            if col_desc_f:
                col_entry_f["description"] = col_desc_f
            formula_col_entries.append(col_entry_f)

    model_doc: dict = {
        "name": model_name,
        "model_tables": model_tables,
        "columns": columns + formula_col_entries,
    }
    if formulas:
        model_doc["formulas"] = formulas
    out: dict = {"model": model_doc}
    if excluded_columns:
        out["_excluded_columns"] = sorted(excluded_columns)   # diagnostics; caller strips
    return out


def extract_table_rls_from_schema_yml(schema_yml_text: str) -> dict[str, dict]:
    """Extract ts_rls_rules from schema.yml and return Table TML rls_rules blocks.

    Returns {TABLE_NAME_UPPER: rls_rules_block} for each model that carries
    ts_rls_rules in its model-level config.meta.  The caller patches the
    corresponding Table TML with this block before importing.

    The returned rls_rules block matches the ThoughtSpot Table TML shape:
      {tables: [{name: ...}], table_paths: [{id, table, column: [...]}], rules: [{name, expr}]}

    `tables` is derived from the unique table names in table_paths — it does not
    need to be stored in schema.yml.
    """
    doc = yaml.safe_load(schema_yml_text) or {}
    result: dict[str, dict] = {}
    for m in (doc.get("models") or []):
        model_name = m.get("name")
        if not model_name:
            continue
        model_meta = (m.get("config") or {}).get("meta") or {}
        ts_rls = model_meta.get("ts_rls_rules")
        if not ts_rls:
            continue

        table_name = _table_name_of(m)
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
