"""ThoughtSpot Model TML -> Databricks Metric View YAML (reverse orchestrator).
Pure: stdlib + (PyYAML only in build_view). No I/O here.
"""
from __future__ import annotations
import re
from typing import Callable

from ts_cli.databricks.mv_emit_expr import parse_formula, UntranslatableError
from ts_cli.databricks.mv_emit_sql import emit_sql
from ts_cli.databricks.mv_tml import ts_type_to_dbx


def to_snake(name: str) -> str:
    s = re.sub(r"[^0-9A-Za-z]+", "_", name.strip()).strip("_").lower()
    return re.sub(r"_+", "_", s) or "col"


def build_column_index(model: dict, tables: list[dict]) -> dict:
    tbl_by_name = {t["table"]["name"]: t["table"] for t in tables}
    type_by_ref: dict[str, str] = {}
    for t in tables:
        tname = t["table"]["name"]
        for c in t["table"].get("columns", []):
            dt = (c.get("db_column_properties") or {}).get("data_type")
            if dt:
                type_by_ref[f"{tname}::{c['name']}"] = dt
    idx: dict = {}
    for col in model.get("columns", []):
        cid = col.get("column_id")
        if not cid:
            continue
        table, column = cid.split("::", 1)
        ts_type = type_by_ref.get(cid, "VARCHAR")
        try:
            dbx_type = ts_type_to_dbx(ts_type)
        except ValueError:
            dbx_type = "string"
        idx[cid] = {"table": table, "column": column, "dbx_type": dbx_type, "dot_path": None}
    return idx


def make_col_resolver(col_index: dict, source_table: str,
                      dot_path_by_table: dict[str, str] | None = None) -> Callable[[dict], str]:
    dot_path_by_table = dot_path_by_table or {}

    def resolver(node: dict) -> str:
        cid = f"{node['table']}::{node['column']}"
        if cid not in col_index:
            raise UntranslatableError(f"unknown column {cid}")
        prefix = "source" if node["table"] == source_table else dot_path_by_table.get(node["table"])
        if prefix is None:
            raise UntranslatableError(f"no join path for table {node['table']}")
        return f"{prefix}.{node['column']}"
    return resolver


def resolve_refs(node: dict, ref_resolver: Callable[[dict], str]) -> dict:
    """Return a copy of the AST with every {'node':'ref'} replaced by a raw-SQL literal."""
    if node["node"] == "ref":
        return {"node": "lit", "kind": "raw", "value": ref_resolver(node)}
    out = dict(node)
    for key in ("left", "right", "operand", "else"):
        if isinstance(out.get(key), dict):
            out[key] = resolve_refs(out[key], ref_resolver)
    if "args" in out:
        out["args"] = [resolve_refs(a, ref_resolver) for a in out["args"]]
    if "cols" in out:
        out["cols"] = [resolve_refs(c, ref_resolver) for c in out["cols"]]
    if "branches" in out:
        out["branches"] = [[resolve_refs(c, ref_resolver), resolve_refs(v, ref_resolver)]
                           for c, v in out["branches"]]
    return out
