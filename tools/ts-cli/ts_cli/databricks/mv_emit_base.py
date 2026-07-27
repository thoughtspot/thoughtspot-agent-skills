"""Foundation helpers for the reverse (ThoughtSpot Model TML -> Databricks
Metric View) emit direction: physical-column indexing, column resolvers, and
formula-AST [ref] resolution shared by mv_emit_joins.py, mv_emit_classify.py,
and mv_emit.py's own assembly code.

Split out of mv_emit.py under the file-size gate (tools/validate/
check_file_size.py) specifically to break a circular import: mv_emit.py's
assembly code needs build_joins (mv_emit_joins.py) and classify_column/
emit_*() (mv_emit_classify.py), so neither of those modules can import these
Foundation primitives back from mv_emit.py itself without creating a cycle.
This module has no ts_cli.databricks.mv_emit* dependency of its own, so it
sits at the bottom of the dependency DAG: base <- joins, base <- classify,
{base, joins, classify} <- mv_emit. mv_emit.py re-exports every name here so
existing callers/tests keep importing from `ts_cli.databricks.mv_emit`
unchanged.

Pure: stdlib only. No I/O here.
"""
from __future__ import annotations
import re
from typing import Callable

from ts_cli.databricks.mv_emit_expr import UntranslatableError
from ts_cli.databricks.mv_tml import ts_type_to_dbx


def to_snake(name: str) -> str:
    s = re.sub(r"[^0-9A-Za-z]+", "_", name.strip()).strip("_").lower()
    return re.sub(r"_+", "_", s) or "col"


def build_column_index(model: dict, tables: list[dict]) -> dict:
    """Index every physical column of every table in `tables` by its
    `TABLE::COLUMN` id.

    Sourced from the physical schema (`tables`), not from `model.get("columns")`
    — real ThoughtSpot Models commonly reference a physical column inside a
    formula (e.g. an LOD partition column, a semi-additive order column, a
    conditional-aggregate's filter column) WITHOUT that column also being its
    own separately-declared model column (see the Dunder Mifflin worked
    example: `DM_INVENTORY::FILLED_INVENTORY`, `DM_EMPLOYEE::LAST_NAME`, and
    `DM_ORDER::EMPLOYEE_ID` are all formula-only references, never their own
    `columns[]` entry). Indexing from `tables` makes every such reference
    resolvable; `model` is kept as a parameter for interface stability but is
    no longer consulted here.
    """
    idx: dict = {}
    by_table: dict[str, dict] = {}
    for t in tables:
        tname = t["table"]["name"]
        cols: dict = {}
        for c in t["table"].get("columns", []):
            ts_type = (c.get("db_column_properties") or {}).get("data_type") or "VARCHAR"
            try:
                dbx_type = ts_type_to_dbx(ts_type)
            except ValueError:
                dbx_type = "string"
            entry = {"table": tname, "column": c["name"],
                     "dbx_type": dbx_type, "dot_path": None}
            idx[f"{tname}::{c['name']}"] = entry
            cols[c["name"]] = entry
        by_table[tname] = cols
    # Role-playing (aliased) tables: a reused physical table referenced under an
    # alias in model_tables gets its columns via `[ALIAS::col]` (e.g.
    # `[ON_BEHALF_ACCOUNT::NAME]`). The physical index above only holds
    # `[ACCOUNT::NAME]`, so mirror each physical column under the alias key too —
    # otherwise the alias's dimensions/measures fail cid lookup and are dropped.
    for mt in model.get("model_tables", []):
        alias = mt.get("alias")
        phys = mt.get("name")
        if not alias or alias == phys:
            continue
        for cname, entry in by_table.get(phys, {}).items():
            idx.setdefault(f"{alias}::{cname}", {
                "table": alias, "column": cname,
                "dbx_type": entry["dbx_type"], "dot_path": None})
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
    """Return a copy of the AST with every {'node':'ref'} replaced by a raw-SQL literal.

    ref_resolver MUST return atomic/self-delimiting SQL (e.g. `MEASURE(x)`/`ANY_VALUE(x)`),
    since the raw-literal substitution is emitted without any added parentheses.
    """
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
