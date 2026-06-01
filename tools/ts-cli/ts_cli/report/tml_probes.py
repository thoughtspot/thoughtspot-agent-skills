"""ts_cli.report.tml_probes — TML inspection for RLS, alerts, aliases, joins, AI surface.

All functions are pure: they take parsed-TML dicts (already exported by the caller)
and return structured findings. No HTTP calls inside this module.
"""
from __future__ import annotations

from typing import Iterable, List


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
