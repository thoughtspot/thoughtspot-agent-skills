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
