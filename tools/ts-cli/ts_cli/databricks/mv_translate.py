"""Parsed Metric View -> translated ThoughtSpot formulas
(`ts databricks translate-formulas`).

Pure functions: parse-mv dict + alias->table map in, JSON-ready dict out.
No I/O, no network calls. stdlib only (Genie-vendorable).

Mapping rules: agents/shared/mappings/ts-databricks/
ts-databricks-formula-translation.md and ts-from-databricks-rules.md
(window decision tree). Cross-measure refs are INLINED via the dependency
DAG (topological substitution) — Databricks needs no phased import; do not
port split_for_phased_import/build_formula_levels (spec §Background).
"""
from __future__ import annotations

from typing import Callable

from ts_cli.databricks.mv_expr import split_dot_path
from ts_cli.databricks.mv_sql import UntranslatableError, translate_sql_expr


def resolve_parts(tables: dict, path: str) -> tuple[str, str]:
    """Resolve a dot-path column ref to (ts_table_name, column_name).

    Bare columns resolve through the 'source' alias; `a.b.COL` resolves the
    alias path 'a.b'. Raises UntranslatableError for an unmapped alias."""
    segs = split_dot_path(path.strip())
    if any("." in s for s in segs):
        raise UntranslatableError(
            f"dot inside a backtick-quoted identifier in {path!r}")
    column = segs[-1]
    alias_path = ".".join(segs[:-1]) or "source"
    table = tables.get(alias_path)
    if table is None:
        raise UntranslatableError(
            f"no ThoughtSpot table mapped for alias '{alias_path}' "
            f"(add it to --tables)")
    return table, column


def make_resolver(tables: dict) -> Callable[[str], str]:
    def resolve(path: str) -> str:
        table, column = resolve_parts(tables, path)
        return f"[{table}::{column}]"
    return resolve


_LOD_AGG = {"SUM": "sum", "COUNT": "count", "AVG": "average",
            "MIN": "min", "MAX": "max"}

_LOD_ASYMMETRY_NOTE = (
    "group_aggregate(..., query_filters()) reproduces a Databricks MV's own "
    "global filter: behavior; a DBX consumer's ad hoc query-time WHERE is "
    "filter-blind for this LOD — reproduce that composite with "
    "group_aggregate(..., {}) plus a mirrored model-level filters: block "
    "(A1/A2/A3; docs/audit/2026-07-09-dbx-semantic-claim-matrix.md).")


def _entry(name: str, role: str, output_kind: str, column_type: str,
           meta: dict, *, table: str | None = None, column: str | None = None,
           ts_expr: str | None = None, aggregation: str | None = None,
           inlined_refs: list[str] | None = None,
           annotations: list[dict] | None = None) -> dict:
    return {"name": name, "role": role, "output_kind": output_kind,
            "column_type": column_type, "table": table, "column": column,
            "ts_expr": ts_expr, "aggregation": aggregation,
            "inlined_refs": list(inlined_refs or []),
            "display_name": meta.get("display_name"),
            "comment": meta.get("comment"),
            "synonyms": list(meta.get("synonyms") or []),
            "format": meta.get("format"),
            "annotations": list(annotations or [])}


def translate_dimension(dim: dict, tables: dict) -> dict:
    """Translate one parsed dimension. Raises UntranslatableError to skip."""
    kind = dim["kind"]
    if kind == "direct":
        table, column = resolve_parts(tables, dim["expr"])
        return _entry(dim["name"], "dimension", "column", "ATTRIBUTE", dim,
                      table=table, column=column)
    if kind == "computed":
        ts = translate_sql_expr(dim["expr"], make_resolver(tables))
        return _entry(dim["name"], "dimension", "formula", "ATTRIBUTE", dim,
                      ts_expr=ts)
    if kind == "lod_window":
        return _translate_lod(dim, tables)
    raise UntranslatableError(f"unknown dimension kind {kind!r}")


def _translate_lod(dim: dict, tables: dict) -> dict:
    agg = _LOD_AGG.get(dim["inner_agg"])
    if agg is None:
        raise UntranslatableError(
            f"LOD aggregate '{dim['inner_agg']}' not mapped "
            f"(SUM|COUNT|AVG|MIN|MAX — ts-databricks-formula-translation.md)")
    resolver = make_resolver(tables)
    inner = translate_sql_expr(dim["inner_expr"], resolver)
    dims = " , ".join(resolver(p) for p in dim["partition_by"])
    ts = (f"group_aggregate ( {agg} ( {inner} ) , {{ {dims} }} , "
          f"query_filters ( ) )")
    return _entry(dim["name"], "dimension", "formula", "ATTRIBUTE", dim,
                  ts_expr=ts,
                  annotations=[{"kind": "lod_filter_asymmetry",
                                "detail": _LOD_ASYMMETRY_NOTE}])


def translate_filter(filter_sql: str, tables: dict) -> dict:
    """Translate the MV global filter: to the MV Filter boolean formula."""
    ts = translate_sql_expr(filter_sql, make_resolver(tables))
    return {"name": "MV Filter", "column_type": "ATTRIBUTE", "ts_expr": ts}
