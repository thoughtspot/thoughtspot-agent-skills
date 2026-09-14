"""ts_cli.report.tml_probes — TML inspection for RLS, alerts, aliases, joins, AI surface.

All functions are pure: they take parsed-TML dicts (already exported by the caller)
and return structured findings. No HTTP calls inside this module.
"""
from __future__ import annotations

from typing import Iterable, List, Optional


def find_rls_column_uses(table_tml: dict, target_columns: Iterable[str]) -> List[dict]:
    """Return RLS-rule hits where any rule references a column in target_columns.

    Per open-items.md #7: rules[].expr references columns via [path_id::COL_NAME].
    """
    targets = set(target_columns)
    rls = (table_tml.get("table") or {}).get("rls_rules") or {}
    paths = {p["id"]: p for p in rls.get("table_paths", [])}
    hits = []
    for rule in rls.get("rules", []):
        expr = rule.get("expr", "")
        for path_id, p in paths.items():
            for col in p.get("column", []):
                if col not in targets:
                    continue
                if f"{path_id}::{col}" in expr or f"[{col}]" in expr:
                    hits.append({
                        "rule_name": rule["name"],
                        "path_id": path_id,
                        "column": col,
                        "expr": expr,
                    })
    return hits


def find_alert_column_uses(
    alert_tml: dict,
    target_columns: Iterable[str],
    *,
    source_model_name: Optional[str] = None,
) -> List[dict]:
    """Return alert-filter hits referencing any column in target_columns.

    Per open-items.md #6: filters[].column entries are strings of form
    "TABLE_OR_MODEL_NAME::COLUMN_NAME". When source_model_name is given,
    only hits on that model are returned.
    """
    targets = set(target_columns)
    hits = []
    for alert in alert_tml.get("monitor_alert", []) or []:
        viz_id = (alert.get("metric_id") or {}).get("pinboard_viz_id", {}).get("viz_id", "")
        for j, filt in enumerate(alert.get("personalised_view_info", {}).get("filters", [])):
            for col_ref in filt.get("column", []):
                if "::" not in col_ref:
                    continue
                tbl, col = col_ref.rsplit("::", 1)
                if col not in targets:
                    continue
                if source_model_name and tbl != source_model_name:
                    continue
                hits.append({
                    "alert_guid": alert.get("guid"),
                    "alert_name": alert.get("name"),
                    "viz_id": viz_id,
                    "filter_index": j,
                    "column": col,
                    "table": tbl,
                })
    return hits


def find_alias_column_uses(alias_tml: dict, target_columns: Iterable[str]) -> List[dict]:
    """Return alias entries for any column in target_columns.

    Per open-items.md #10 (resolved 2026-05-28): alias TML structure is
        column_alias:
          model: {name: ..., fqn: ...}
          columns:
            - name: <model alias name>
              locales:
                - name: <locale code>
                  orgs: [...]
    """
    targets = set(target_columns)
    cols = (alias_tml.get("column_alias") or {}).get("columns") or []
    hits = []
    for c in cols:
        if c.get("name") in targets:
            hits.append({
                "name": c["name"],
                "locale_count": len(c.get("locales") or []),
                "locales": [loc.get("name") for loc in (c.get("locales") or [])],
            })
    return hits


def find_join_column_uses(model_tml: dict, target_columns: Iterable[str]) -> List[dict]:
    """Return join hits where any join.on expression references a target column.

    Per open-items.md #4: ThoughtSpot rejects model imports if joins[].on
    references a missing column.
    """
    targets = set(target_columns)
    hits = []
    for tbl in (model_tml.get("model") or {}).get("model_tables", []):
        for join in tbl.get("joins_with", []):
            on_expr = join.get("on", "")
            for col in targets:
                if col in on_expr:
                    hits.append({
                        "table": tbl.get("name", "?"),
                        "join": join.get("name", "unnamed"),
                        "on": on_expr,
                        "column": col,
                    })
                    break
    return hits


def find_formula_column_uses(model_tml: dict, physical_column: str) -> List[dict]:
    """Return model formulas[] entries whose expr references physical_column.

    Unlike the other probes here, this matches the *physical* (db) column name,
    not a display name — a formula expr is written against the underlying
    column identifier, so a dropped physical column breaks the formula even
    though the formula's own display name never changes.
    """
    hits = []
    for f in (model_tml.get("model") or {}).get("formulas", []) or []:
        expr = f.get("expr", "") or ""
        if physical_column and physical_column.lower() in expr.lower():
            hits.append({"formula_id": f.get("id"), "name": f.get("name"), "expr": expr})
    return hits


def find_model_filter_column_uses(model_tml: dict, target_columns: Iterable[str]) -> List[dict]:
    """Return model-level filters[] entries referencing a target column.

    Distinct from find_join_column_uses (joins_with[].on) — a Model's own
    top-level filters[] block applies a filter across the whole model.
    """
    targets = set(target_columns)
    hits = []
    for filt in (model_tml.get("model") or {}).get("filters", []) or []:
        col = filt.get("column")
        if col in targets:
            hits.append({"column": col, "oper": filt.get("oper"), "values": filt.get("values")})
    return hits


def find_sql_view_column_uses(sql_view_doc: dict, physical_column: str) -> Optional[dict]:
    """Return a hit dict if this SQL view's query or output columns reference
    physical_column, else None.

    The dependents API does not track column references inside a SQL view's
    raw query text — callers must enumerate SQL_VIEW objects and scan this way.
    """
    sv = sql_view_doc.get("sql_view") or {}
    if not sv:
        return None
    sql_query = sv.get("sql_query", "") or ""
    output_cols = [
        c.get("sql_output_column") or c.get("name", "")
        for c in (sv.get("sql_view_columns") or [])
    ]
    col_lower = (physical_column or "").lower()
    in_sql = bool(col_lower) and col_lower in sql_query.lower()
    in_cols = bool(col_lower) and any(col_lower in c.lower() for c in output_cols)
    if not (in_sql or in_cols):
        return None
    return {
        "guid": sql_view_doc.get("guid", ""),
        "name": sv.get("name", ""),
        "sql_query": sql_query,
        "output_columns": output_cols,
        "in_sql": in_sql,
        "in_output_columns": in_cols,
    }


def find_ai_surface_uses(model_tml: dict, target_columns: Iterable[str]) -> List[dict]:
    """Return hits where a target column appears in a Spotter-AI surface area:
    Data Model Instructions, synonyms, or business-term column references.
    """
    targets = set(target_columns)
    hits = []
    model = model_tml.get("model") or {}

    # Data Model Instructions — free text; tokens look like [Column Name].
    dmi = ((model.get("model_instructions") or {}).get("data_model_instructions")) or ""
    for col in targets:
        if f"[{col}]" in dmi or col in dmi:
            hits.append({"surface": "data_model_instructions", "column": col})

    # Synonyms — per-column array.
    for c in model.get("columns", []) or []:
        name = c.get("name")
        if name in targets:
            syns = (c.get("properties") or {}).get("synonyms") or []
            if syns:
                hits.append({"surface": "synonyms", "column": name, "values": syns})

    return hits
