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

import re
from typing import Callable

from ts_cli.databricks.mv_expr import (
    mask_string_literals,
    split_dot_path,
    strip_sql_comments,
)
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


_COLUMN_AGG = {"SUM": "SUM", "AVG": "AVERAGE", "MIN": "MIN", "MAX": "MAX",
               "COUNT": "COUNT", "STDDEV": "STD_DEVIATION",
               "VARIANCE": "VARIANCE"}
_AGG_IF = {"SUM": "sum_if", "COUNT": "count_if", "AVG": "average_if",
           "MIN": "min_if", "MAX": "max_if", "STDDEV": "stddev_if",
           "VARIANCE": "variance_if"}
_FILTER_SPLIT_RE = re.compile(
    r"^(?P<agg>[A-Za-z_]\w*)\s*\(\s*(?P<distinct>DISTINCT\s+)?(?P<inner>.*)\)"
    r"\s*FILTER\s*\(\s*WHERE\s+(?P<cond>.*)\)\s*$",
    re.IGNORECASE | re.DOTALL)
_MEASURE_SUB_RE = re.compile(
    r"\b(MEASURE|ANY_VALUE)\s*\(\s*(`[^`]+`|[A-Za-z_]\w*)\s*\)", re.IGNORECASE)


def translate_measure(measure: dict, tables: dict) -> dict:
    """Translate one parsed non-window measure. Raises to skip.

    complex_cross_measure output is INTERMEDIATE: __MVREF_n__ placeholders
    remain until the orchestrator (translate_metric_view) inlines them in
    dependency order."""
    kind = measure["expr_kind"]
    resolver = make_resolver(tables)
    if kind == "simple":
        return _translate_simple(measure, tables)
    if kind == "count_distinct":
        table, column = resolve_parts(tables, measure["physical_ref"])
        return _formula_measure(measure,
                                f"unique count ( [{table}::{column}] )")
    if kind == "count_star":
        return _formula_measure(measure, "count ( 1 )")
    if kind == "conditional":
        return _formula_measure(measure,
                                _translate_conditional(measure, resolver))
    if kind == "complex":
        return _formula_measure(measure,
                                translate_sql_expr(measure["expr"], resolver))
    if kind == "complex_cross_measure":
        sql, refs = _prepare_cross_measure(measure["expr"])
        return _formula_measure(measure, translate_sql_expr(sql, resolver),
                                inlined_refs=refs)
    raise UntranslatableError(f"unknown measure expr_kind {kind!r}")


def _formula_measure(measure: dict, ts_expr: str, *,
                     inlined_refs: list[str] | None = None,
                     annotations: list[dict] | None = None) -> dict:
    return _entry(measure["name"], "measure", "formula", "MEASURE", measure,
                  ts_expr=ts_expr, aggregation="SUM",
                  inlined_refs=inlined_refs, annotations=annotations)


def _translate_simple(measure: dict, tables: dict) -> dict:
    if measure["distinct"]:
        raise UntranslatableError(
            f"{measure['agg_function']}(DISTINCT …) has no ThoughtSpot "
            f"mapping (only COUNT(DISTINCT col) -> unique count)")
    aggregation = _COLUMN_AGG.get(measure["agg_function"])
    if aggregation is None:
        # Not a TML column aggregation — try the full formula path (which
        # fail-louds on an unmapped function, naming it).
        ts = translate_sql_expr(measure["expr"], make_resolver(tables))
        return _formula_measure(measure, ts)
    table, column = resolve_parts(tables, measure["physical_ref"])
    return _entry(measure["name"], "measure", "column", "MEASURE", measure,
                  table=table, column=column, aggregation=aggregation)


def _translate_conditional(measure: dict, resolver) -> str:
    e = strip_sql_comments(measure["expr"])
    m = _FILTER_SPLIT_RE.match(mask_string_literals(e))
    if not m:
        raise UntranslatableError(
            "FILTER (WHERE …) shape not recognized — expected "
            "AGG(expr) FILTER (WHERE cond)")
    agg = e[m.start("agg"):m.end("agg")].upper()
    distinct = bool(m.group("distinct"))
    inner = translate_sql_expr(e[m.start("inner"):m.end("inner")], resolver)
    cond = translate_sql_expr(e[m.start("cond"):m.end("cond")], resolver)
    if agg == "COUNT" and distinct:
        return f"unique_count_if ( {cond} , {inner} )"
    if distinct:
        raise UntranslatableError(
            f"{agg}(DISTINCT …) FILTER (WHERE …) has no ThoughtSpot mapping")
    fn = _AGG_IF.get(agg)
    if fn is not None:
        return f"{fn} ( {cond} , {inner} )"
    # Every doc-mapped aggregate has a native *_if form, so the doc's
    # agg(if(cond, x, null)) fallback is unreachable today — fail loud
    # instead of shipping a dead branch; add the fallback when a mapped
    # aggregate without a *_if actually appears.
    raise UntranslatableError(
        f"aggregate '{agg}' under FILTER (WHERE …) has no native *_if "
        f"function mapping (ts-databricks-formula-translation.md)")


def _prepare_cross_measure(expr: str) -> tuple[str, list[str]]:
    """Replace MEASURE(x)/ANY_VALUE(y) with __MVREF_n__ placeholders.

    Scans the same surface parse-mv's extract_cross_refs scans
    (comment-stripped, string-literals masked) so the placeholder list
    always agrees with the parsed cross_refs/lod_refs."""
    e = strip_sql_comments(expr)
    masked = mask_string_literals(e)
    refs: list[str] = []
    out: list[str] = []
    last = 0
    for m in _MEASURE_SUB_RE.finditer(masked):
        refs.append(e[m.start(2):m.end(2)].strip("`"))
        out.append(e[last:m.start()])
        out.append(f"__MVREF_{len(refs) - 1}__")
        last = m.end()
    out.append(e[last:])
    return "".join(out), refs
