"""ThoughtSpot Model TML → Snowflake Semantic View DDL assembly.

Pure functions: dicts in, string out. No I/O, no network. The command layer
(commands/snowflake.py build_sv_cmd) handles TML export and DDL file writes.

Codifies ts-convert-to-snowflake-sv Steps 5–8: column_id resolution, column
classification (dimension/metric/time_dimension), to_snake aliasing,
relationship naming, metric ordering, DDL assembly, and CA extension JSON.
The dialect-agnostic parsing (column index, column_id resolution,
classification, join-graph walk, metric ordering) lives in tml_model_parse.py,
shared with dbt_build_export.py (ts-convert-to-dbt).

Formula translation (Step 9) is handled separately — this module accepts
pre-translated formulas as optional input.
"""
from __future__ import annotations

import json
from collections import defaultdict

from .tml_model_parse import (
    build_column_index,
    build_table_maps,
    classify_column,
    collect_join_data,
    model_table_identity,
    order_metrics,
    parse_join_on,
    resolve_column_id,
    to_snake,
)

__all__ = [
    "to_snake", "build_column_index", "resolve_column_id", "classify_column",
    "parse_join_on", "order_metrics", "aggregation_expr",
    "build_relationship_name", "escape_comment", "build_synonym_clause",
    "build_ca_json", "build_sv_ddl",
]


# ---------------------------------------------------------------------------
# Aggregation mapping
# ---------------------------------------------------------------------------

_AGG_MAP = {
    "SUM": "SUM",
    "COUNT": "COUNT",
    "COUNT_DISTINCT": "COUNT(DISTINCT",
    "AVG": "AVG",
    "AVERAGE": "AVG",
    "MIN": "MIN",
    "MAX": "MAX",
    "STD_DEVIATION": "STDDEV",
    "VARIANCE": "VARIANCE",
}


def aggregation_expr(agg: str | None, table_lower: str, col: str) -> str:
    """Build SV metric expression from aggregation type and column."""
    agg_upper = (agg or "SUM").upper()
    if agg_upper == "COUNT_DISTINCT":
        return f"COUNT(DISTINCT {table_lower}.{col})"
    fn = _AGG_MAP.get(agg_upper, "SUM")
    return f"{fn}({table_lower}.{col})"


# ---------------------------------------------------------------------------
# Comment/synonym helpers
# ---------------------------------------------------------------------------

def escape_comment(text: str) -> str:
    """Escape single quotes for SV comment strings."""
    return text.replace("'", "''")


def build_synonym_clause(
    display_name: str, synonyms: list[str],
) -> str | None:
    """Build `with synonyms=(...)` clause if there are synonyms to emit."""
    parts = [display_name]
    for s in synonyms:
        if s != display_name:
            parts.append(s)
    if len(parts) <= 1:
        return None
    escaped = ", ".join(f"'{escape_comment(p)}'" for p in parts)
    return f"with synonyms=({escaped})"


# ---------------------------------------------------------------------------
# CA extension JSON
# ---------------------------------------------------------------------------

def build_ca_json(
    tables_data: dict[str, dict],
    relationships: list[str],
) -> str:
    """Build the Cortex Analyst extension JSON string.

    tables_data: {sv_table_name: {dimensions: [...], time_dimensions: [...], metrics: [...]}}
    relationships: [relationship_name, ...]
    """
    tables = []
    for tname, data in tables_data.items():
        entry: dict = {"name": tname}
        if data.get("dimensions"):
            entry["dimensions"] = [{"name": d} for d in data["dimensions"]]
        if data.get("time_dimensions"):
            entry["time_dimensions"] = [{"name": d} for d in data["time_dimensions"]]
        if data.get("metrics"):
            entry["metrics"] = [{"name": m} for m in data["metrics"]]
        tables.append(entry)

    ca: dict = {"tables": tables}
    if relationships:
        ca["relationships"] = [{"name": r} for r in relationships]
    return json.dumps(ca, separators=(",", ":"))


# ---------------------------------------------------------------------------
# DDL assembly — main entry point
# ---------------------------------------------------------------------------

def _build_tables_clause(
    mt_order: list[str],
    mt_names: dict[str, str],
    mt_fqns: dict[str, str],
    mt_pks: dict[str, list[str]],
) -> list[str]:
    """Build the tables() clause entries."""
    parts = []
    for mt_id in mt_order:
        sv_ident = mt_names.get(mt_id, mt_id)
        fqn = mt_fqns.get(mt_id, sv_ident)
        # A role-playing instance (SV table name differs from the physical table's
        # own name) must be declared with an explicit alias: `<alias> as <FQN>`.
        # Otherwise the same physical table would appear multiple times unaliased,
        # which is invalid SV DDL and leaves the alias referenced by relationships
        # undefined.
        physical_last = fqn.rsplit(".", 1)[-1]
        table_ref = f"{sv_ident} as {fqn}" if sv_ident != physical_last else fqn
        pk_cols = mt_pks.get(sv_ident) or mt_pks.get(mt_id)
        if pk_cols:
            unique_pks = list(dict.fromkeys(pk_cols))
            pk_str = ", ".join(unique_pks)
            # No square brackets: `[...]` is GET_DDL *display* notation for the
            # optional clause, not valid CREATE SEMANTIC VIEW input syntax.
            parts.append(f"{table_ref} primary key ({pk_str})")
        else:
            parts.append(table_ref)
    return parts


def _build_relationships_clause(
    join_data: list[dict],
    mt_names: dict[str, str],
) -> tuple[list[str], list[str], list[dict]]:
    """Build the relationships() clause entries.

    Endpoints reference the SV **logical table name** (the alias/name declared in
    the tables() clause), never the fully-qualified physical name — Snowflake SV
    relationship syntax is `rel as LEFT(fk) references RIGHT(pk)` over the logical
    tables. For a role-play, that logical name is the alias (e.g. CASE_OWNER).

    Returns (rel_clause_parts, rel_names_list, dropped_joins).
    """
    rel_clause_parts: list[str] = []
    rel_names_list: list[str] = []
    dropped_joins: list[dict] = []

    for jd in join_data:
        ref_pairs = [(lc, rc) for _, lc, _, rc in jd["pairs"]]
        left = mt_names.get(jd["left_id"], jd["left_table"])
        right = mt_names.get(jd["right_table"], jd["right_table"])

        if len(ref_pairs) == 1:
            fk, pk = ref_pairs[0]
            rel_clause_parts.append(
                f"{jd['name']} as {left}({fk}) references {right}({pk})")
        else:
            fk_list = ", ".join(p[0] for p in ref_pairs)
            pk_list = ", ".join(p[1] for p in ref_pairs)
            rel_clause_parts.append(
                f"{jd['name']} as {left}({fk_list}) references {right}({pk_list})")

        rel_names_list.append(jd["name"])

        if jd["join_type"] or jd["cardinality"]:
            dropped_joins.append({
                "relationship": jd["name"],
                "join_type": jd["join_type"],
                "cardinality": jd["cardinality"],
            })

    return rel_clause_parts, rel_names_list, dropped_joins


def _classify_columns(
    columns: list[dict],
    formulas_by_id: dict[str, dict],
    translated: dict[str, dict],
    model_table_map: dict[str, str],
    col_index: dict[tuple[str, str], dict],
    phys_by_node: dict[str, str] | None = None,
) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict]]:
    """Classify model columns into dims, time_dims, metrics, skipped, unmapped.

    Returns (dims, time_dims, metrics_list, skipped_formulas, unmapped_props).
    """
    dims: list[dict] = []
    time_dims: list[dict] = []
    metrics_list: list[dict] = []
    skipped_formulas: list[dict] = []
    unmapped_props: list[dict] = []

    for col in columns:
        props = col.get("properties") or {}
        col_name = col.get("name", "")
        alias = to_snake(col_name)

        if col.get("formula_id"):
            _classify_formula_column(
                col, alias, col_name, props, translated,
                formulas_by_id, dims, metrics_list, skipped_formulas)
            continue

        _classify_physical_column(
            col, alias, col_name, props, formulas_by_id,
            model_table_map, col_index,
            dims, time_dims, metrics_list, unmapped_props, phys_by_node)

    return dims, time_dims, metrics_list, skipped_formulas, unmapped_props


def _classify_formula_column(
    col: dict, alias: str, col_name: str, props: dict,
    translated: dict[str, dict],
    formulas_by_id: dict[str, dict],
    dims: list[dict], metrics_list: list[dict],
    skipped_formulas: list[dict],
) -> None:
    """Route a formula column to dims, metrics, or skipped."""
    fid = col["formula_id"]
    if fid not in translated:
        formula = formulas_by_id.get(fid)
        skipped_formulas.append({
            "name": col_name,
            "formula_id": fid,
            "ts_expr": formula.get("expr", "") if formula else "",
            "reason": "not in translated_formulas",
        })
        return

    tf = translated[fid]
    classification = tf.get("kind", "metric")
    entry = {
        "alias": alias,
        "display_name": col_name,
        "expr": tf["expr"],
        "classification": classification,
        "synonyms": props.get("synonyms", []),
        # `description` lives at the COLUMN ROOT, where ThoughtSpot emits it — the
        # `properties` read is a fallback for locally generated TML predating that fix.
        "comment": col.get("description") or props.get("description"),
    }
    if classification == "metric":
        metrics_list.append(entry)
    else:
        dims.append(entry)


def _classify_physical_column(
    col: dict, alias: str, col_name: str, props: dict,
    formulas_by_id: dict[str, dict],
    model_table_map: dict[str, str],
    col_index: dict[tuple[str, str], dict],
    dims: list[dict], time_dims: list[dict],
    metrics_list: list[dict], unmapped_props: list[dict],
    phys_by_node: dict[str, str] | None = None,
) -> None:
    """Route a physical column to dims, time_dims, or metrics."""
    column_id = col.get("column_id", "")
    if not column_id:
        return

    try:
        sv_table, db_col, data_type = resolve_column_id(
            column_id, model_table_map, col_index, phys_by_node)
    except ValueError:
        return

    table_lower = to_snake(sv_table)
    classification = classify_column(col, formulas_by_id, data_type)

    synonyms = props.get("synonyms", [])
    # `description` lives at the COLUMN ROOT, where ThoughtSpot emits it — the
    # `properties` read is a fallback for locally generated TML predating that fix.
    comment = col.get("description") or props.get("description")
    _collect_unmapped_props(col_name, props, unmapped_props)

    if classification == "metric":
        agg = props.get("aggregation")
        expr = aggregation_expr(agg, table_lower, db_col)
        metrics_list.append({
            "alias": alias, "display_name": col_name,
            "table": sv_table, "table_lower": table_lower,
            "expr": expr, "classification": "metric",
            "synonyms": synonyms, "comment": comment,
        })
    else:
        as_expr = f"{table_lower}.{db_col}"
        entry = {
            "alias": alias, "display_name": col_name,
            "table": sv_table, "table_lower": table_lower,
            "expr": as_expr, "classification": classification,
            "synonyms": synonyms, "comment": comment,
        }
        if classification == "time_dimension":
            time_dims.append(entry)
        else:
            dims.append(entry)


def _build_ca_tables(
    dims: list[dict], time_dims: list[dict], metrics_list: list[dict],
) -> dict[str, dict]:
    """Collect per-table column lists for the CA extension JSON."""
    ca_tables: dict[str, dict] = defaultdict(
        lambda: {"dimensions": [], "time_dimensions": [], "metrics": []})

    for d in dims:
        tname = to_snake(d.get("table", ""))
        if tname:
            ca_tables[tname]["dimensions"].append(d["alias"])
    for td in time_dims:
        tname = to_snake(td.get("table", ""))
        if tname:
            ca_tables[tname]["time_dimensions"].append(td["alias"])
    for m in metrics_list:
        tname = to_snake(m.get("table", ""))
        if tname:
            ca_tables[tname]["metrics"].append(m["alias"])

    return dict(ca_tables)


def _assemble_ddl(
    sv_name: str,
    tables_clause: list[str],
    rel_clause: list[str],
    dim_entries: list[dict],
    metric_entries: list[dict],
    comment_text: str,
    ca_json: str,
) -> str:
    """Build the final DDL string from pre-assembled clause parts."""
    ddl_parts = [f"CREATE OR REPLACE SEMANTIC VIEW {sv_name}"]

    if tables_clause:
        inner = ",\n    ".join(tables_clause)
        ddl_parts.append(f"  tables (\n    {inner}\n  )")

    if rel_clause:
        inner = ",\n    ".join(rel_clause)
        ddl_parts.append(f"  relationships (\n    {inner}\n  )")

    dim_lines = [_format_column_entry(d) for d in dim_entries]
    if dim_lines:
        inner = ",\n    ".join(dim_lines)
        ddl_parts.append(f"  dimensions (\n    {inner}\n  )")

    metric_lines = [_format_column_entry(m) for m in metric_entries]
    if metric_lines:
        inner = ",\n    ".join(metric_lines)
        ddl_parts.append(f"  metrics (\n    {inner}\n  )")

    ddl_parts.append(f"  comment='{escape_comment(comment_text)}'")
    ddl_parts.append(f"  with extension (CA='{escape_comment(ca_json)}')")

    return "\n".join(ddl_parts) + "\n;"


def build_sv_ddl(
    *,
    model_tml: dict,
    table_tmls: dict[str, dict],
    sv_name: str,
    translated_formulas: dict[str, dict] | None = None,
) -> tuple[str, dict]:
    """Assemble a CREATE OR REPLACE SEMANTIC VIEW DDL from Model + Table TMLs.

    translated_formulas: optional {formula_id: {expr: "SV SQL expr", kind: "metric"|"dimension"}}
    for pre-translated formulas. Untranslated formulas are omitted.

    Returns (ddl_string, build_info).
    """
    model = model_tml.get("model", {})
    columns = model.get("columns", [])
    formulas = model.get("formulas", [])
    model_tables = model.get("model_tables", [])

    formulas_by_id = {f["id"]: f for f in formulas}
    translated = translated_formulas or {}
    col_index = build_column_index(table_tmls)

    mt_names, mt_fqns, mt_order, mt_phys = build_table_maps(
        model_tables, table_tmls)
    join_data, mt_pks = collect_join_data(model_tables, mt_names, col_index)

    tables_clause = _build_tables_clause(mt_order, mt_names, mt_fqns, mt_pks)
    rel_clause, rel_names_list, dropped_joins = _build_relationships_clause(
        join_data, mt_names)

    # Column classification owns each dimension by its node key (the alias for a
    # role-play), resolving physical columns via mt_phys so the column index (keyed
    # by physical table name) still hits.
    dims, time_dims, metrics_list, skipped_formulas, unmapped_props = (
        _classify_columns(
            columns, formulas_by_id, translated, mt_names, col_index, mt_phys))

    _dedupe_aliases(dims + time_dims + metrics_list)
    metrics_list = order_metrics(metrics_list)

    ca_json = build_ca_json(
        _build_ca_tables(dims, time_dims, metrics_list), rel_names_list)

    model_desc = model.get("description", "")
    comment_text = f"Migrated from ThoughtSpot: {model.get('name', '')}"
    if model_desc:
        comment_text = f"{model_desc} | {comment_text}"

    ddl = _assemble_ddl(
        sv_name, tables_clause, rel_clause,
        dims + time_dims, metrics_list, comment_text, ca_json)

    return ddl, {
        "dimensions": len(dims),
        "time_dimensions": len(time_dims),
        "metrics": len(metrics_list),
        "skipped_formulas": skipped_formulas,
        "dropped_joins": dropped_joins,
        "unmapped_properties": unmapped_props,
        "relationship_count": len(rel_names_list),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_UNMAPPED_PROP_KEYS = frozenset({
    "format_pattern", "default_date_bucket", "custom_order",
    "data_panel_column_groups", "geo_config",
})


def _collect_unmapped_props(
    col_name: str, props: dict, out: list[dict],
) -> None:
    for key in _UNMAPPED_PROP_KEYS:
        if key in props:
            out.append({"column": col_name, "property": key, "value": str(props[key])})


def _format_column_entry(entry: dict) -> str:
    """Format a dimension or metric entry as a DDL line."""
    table = entry.get("table", "")
    table_upper = table.upper() if table else ""

    alias = entry["alias"]
    expr = entry["expr"]

    if table_upper:
        prefix = f"{table_upper}.{alias}"
    else:
        prefix = alias

    line = f"{prefix} as {expr}"

    syn_clause = build_synonym_clause(
        entry["display_name"], entry.get("synonyms") or [])
    if syn_clause:
        line += f" {syn_clause}"

    comment = entry.get("comment")
    if comment:
        line += f" comment='{escape_comment(comment)}'"

    return line


def _dedupe_aliases(entries: list[dict]) -> None:
    """Ensure alias uniqueness across all entries, appending _2, _3 etc."""
    seen: dict[str, int] = {}
    for e in entries:
        alias = e["alias"]
        if alias in seen:
            seen[alias] += 1
            e["alias"] = f"{alias}_{seen[alias]}"
        else:
            seen[alias] = 1
