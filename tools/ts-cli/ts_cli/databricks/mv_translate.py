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
    if measure.get("window") is not None:
        raise UntranslatableError(
            "translate_measure received a windowed measure — route via "
            "translate_window_measure")
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


_OUTER_AGG_RE = re.compile(r"^([A-Za-z_]\w*)\s*\((.*)\)\s*$", re.DOTALL)
_DATE_TRUNC_DIM_RE = re.compile(
    r"^DATE_TRUNC\s*\(\s*'(\w+)'\s*,\s*(.+?)\s*\)\s*$", re.IGNORECASE | re.DOTALL)
_MOVING_FN = {"SUM": "moving_sum", "AVG": "moving_average",
              "MIN": "moving_min", "MAX": "moving_max"}
_CUMULATIVE_FN = {"SUM": "cumulative_sum", "AVG": "cumulative_average",
                  "MIN": "cumulative_min", "MAX": "cumulative_max"}
_UNIT_MONTHS = {"month": 1, "quarter": 3, "year": 12}
_GRAIN_MONTHS = {"month": 1, "quarter": 3, "year": 12}

_SPARSE_RISK = (
    "range '{raw_range}' is a date-interval frame on Databricks but "
    "row-positional {fn} on ThoughtSpot — numbers match only if order "
    "column '{order}' is dense at the {unit} grain (one row per {unit}, no "
    "gaps). Verify density before trusting the translation (BL-098; "
    "docs/audit/2026-07-09-dbx-semantic-claim-matrix.md E1).")
_ONE_ROW_PER_PERIOD = (
    "the moving_sum LAG idiom is exact only when the query returns exactly "
    "one row per period in order column '{order}' — gaps or multiple rows "
    "per period need a period-grain pre-aggregation first "
    "(ts-databricks-formula-translation.md, Period Filter).")
_C8_PENDING = (
    "period-offset translation live-verified only for N=1 at month grain "
    "(matrix C6); this {grain}-grain / {unit}-offset combination is the "
    "documented extrapolation of the same idiom, not separately live-tested "
    "(Deferred C8 — docs/audit/2026-07-08-dbx-window-claim-matrix.md).")
_NOT_LIVE_TESTED = (
    "{fn} carries the same 4-arg signature and frame rule as the "
    "live-verified moving_sum/cumulative_sum but was not separately "
    "live-tested (ts-databricks-formula-translation.md).")


def translate_window_measure(measure: dict, dimensions: list[dict],
                             tables: dict) -> dict:
    """Translate a windowed measure per the rules-doc decision tree."""
    if measure["cross_refs"] or measure["lod_refs"]:
        raise UntranslatableError(
            "a windowed measure combining MEASURE()/ANY_VALUE() cross-refs "
            "has no documented translation")
    window = measure["window"]
    rng = window["range"]
    if rng["type"] == "all":
        raise UntranslatableError(
            "range: all requires a partition-dimension judgment call (which "
            "dims scope the window is a per-MV decision, not derivable from "
            "the YAML) — build group_aggregate ( sum ( [m] ) , { dims } , "
            "query_filters ( ) ) manually per ts-from-databricks-rules.md "
            "All-Partition Window")
    order = _find_order_dim(window["order"], dimensions, tables)
    agg, inner = _window_inner(measure, tables)
    if rng["type"] in ("trailing", "leading"):
        return _window_moving(measure, window, order, agg, inner)
    if rng["type"] == "cumulative":
        return _window_cumulative(measure, order, agg, inner)
    # rng["type"] == "current"
    return _window_current(measure, window, order, agg, inner)


def _find_order_dim(order_name: str, dimensions: list[dict],
                    tables: dict) -> dict:
    """Classify the order: dimension -> {'grain': 'day'|'month'|'quarter'|'year',
    'sort_ref': '[T::col]'} ('day' == raw date)."""
    dim = next((d for d in dimensions if d["name"] == order_name), None)
    if dim is None:
        raise UntranslatableError(
            f"window order dimension '{order_name}' not found in the MV's "
            f"dimensions")
    resolver = make_resolver(tables)
    if dim["kind"] == "direct":
        return {"grain": "day", "sort_ref": resolver(dim["expr"])}
    if dim["kind"] == "computed":
        stripped = dim["expr"].strip()
        m = _DATE_TRUNC_DIM_RE.match(stripped)
        if m:
            unit = m.group(1).lower()
            if unit == "day":
                return {"grain": "day", "sort_ref": resolver(m.group(2))}
            if unit in _GRAIN_MONTHS:
                return {"grain": unit, "sort_ref": resolver(m.group(2))}
            raise UntranslatableError(
                f"order dimension '{order_name}' truncates to '{unit}' — "
                f"only day/month/quarter/year grains are mapped")
    raise UntranslatableError(
        f"cannot determine the physical sort column for window order "
        f"dimension '{order_name}' (expr must be a direct column or "
        f"DATE_TRUNC('<unit>', col))")


def _window_inner(measure: dict, tables: dict) -> tuple[str, str]:
    """Strip the outer aggregate; return (AGG_NAME, translated_inner_ts)."""
    resolver = make_resolver(tables)
    if measure["expr_kind"] == "simple":
        return (measure["agg_function"],
                resolver(measure["physical_ref"]))
    e = measure["expr"].strip()
    m = _OUTER_AGG_RE.match(mask_string_literals(e))
    if m and _balanced(m.group(2)):
        agg = e[m.start(1):m.end(1)].upper()
        inner_sql = e[m.start(2):m.end(2)]
        return agg, translate_sql_expr(inner_sql, resolver)
    raise UntranslatableError(
        "windowed measure expr must be AGG(expression) — the outer "
        "aggregate is stripped because moving_/cumulative_ functions "
        "aggregate internally (worked-example rule 9)")


def _balanced(s: str) -> bool:
    depth = 0
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _window_moving(measure, window, order, agg, inner) -> dict:
    rng = window["range"]
    if rng["unit"] != "day":
        raise UntranslatableError(
            f"range '{window['raw_range']}': unit '{rng['unit']}' — only "
            f"day grain trailing/leading windows are live-verified "
            f"(BL-098 item 3 / C8); non-day units need a live probe first")
    if order["grain"] != "day":
        raise UntranslatableError(
            f"trailing/leading window over non-daily order dimension "
            f"'{window['order']}' has no verified mapping")
    fn = _MOVING_FN.get(agg)
    if fn is None:
        raise UntranslatableError(
            f"aggregate '{agg}' has no moving_* ThoughtSpot function")
    n = rng["n"]
    if rng["type"] == "trailing":
        start, end = (n, -1) if rng["anchor"] == "exclusive" else (n - 1, 0)
    else:  # leading
        start, end = (-1, n) if rng["anchor"] == "exclusive" else (0, n - 1)
    ts = f"{fn} ( {inner} , {start} , {end} , {order['sort_ref']} )"
    annotations = [{"kind": "sparse_data_risk",
                    "detail": _SPARSE_RISK.format(
                        raw_range=window["raw_range"], fn=fn,
                        order=window["order"], unit=rng["unit"])}]
    if agg in ("MIN", "MAX"):
        annotations.append({"kind": "pending_verification",
                            "detail": _NOT_LIVE_TESTED.format(fn=fn)})
    return _formula_measure(measure, ts, annotations=annotations)


def _window_cumulative(measure, order, agg, inner) -> dict:
    fn = _CUMULATIVE_FN.get(agg)
    if fn is None:
        raise UntranslatableError(
            f"aggregate '{agg}' has no cumulative_* ThoughtSpot function")
    annotations = []
    if agg != "SUM":
        annotations.append({"kind": "pending_verification",
                            "detail": _NOT_LIVE_TESTED.format(fn=fn)})
    return _formula_measure(
        measure, f"{fn} ( {inner} , {order['sort_ref']} )",
        annotations=annotations)


def _window_current(measure, window, order, agg, inner) -> dict:
    lower = agg.lower() if agg != "AVG" else "average"
    if order["grain"] == "day":  # raw date -> true semi-additive (C7)
        fn = "last_value" if window["semiadditive"] == "last" else "first_value"
        ts = (f"{fn} ( {lower} ( {inner} ) , query_groups ( ) , "
              f"{{ {order['sort_ref']} }} )")
        annotations = []
        if agg != "SUM":
            annotations.append({"kind": "pending_verification",
                                "detail": _NOT_LIVE_TESTED.format(fn=fn)})
        return _formula_measure(measure, ts, annotations=annotations)
    offset = window["offset"]
    if offset is None:  # period filter, no offset -> plain aggregate (C6)
        return _formula_measure(measure, f"{lower} ( {inner} )")
    unit_months = _UNIT_MONTHS.get(offset["unit"])
    if unit_months is None:
        raise UntranslatableError(
            f"offset unit '{offset['unit']}' has no period-offset mapping "
            f"(month|quarter|year — day/week offsets are not periods)")
    grain_months = _GRAIN_MONTHS[order["grain"]]
    total = abs(offset["n"]) * unit_months
    if total % grain_months:
        raise UntranslatableError(
            f"offset '{offset['n']} {offset['unit']}' does not divide evenly "
            f"into the '{order['grain']}' order grain")
    p = total // grain_months
    ts = f"moving_sum ( {inner} , {p} , -{p} , {order['sort_ref']} )"
    annotations = [{"kind": "one_row_per_period",
                    "detail": _ONE_ROW_PER_PERIOD.format(order=window["order"])}]
    verified = (order["grain"] == "month" and offset["unit"] == "month"
                and abs(offset["n"]) == 1)
    if not verified:
        annotations.append({"kind": "pending_verification",
                            "detail": _C8_PENDING.format(
                                grain=order["grain"], unit=offset["unit"])})
    if agg != "SUM":
        raise UntranslatableError(
            f"period-offset windows are documented for SUM measures only "
            f"(the moving_sum LAG idiom); aggregate '{agg}' needs a live probe")
    return _formula_measure(measure, ts, annotations=annotations)


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


_PLACEHOLDER_RE = re.compile(r"__MVREF_(\d+)__")


def translate_metric_view(parsed: dict, tables: dict) -> dict:
    """Translate a parse-mv result. Content failures -> skipped[]; only a
    malformed tables map raises (ValueError -> command exit 1)."""
    _validate_tables(tables)
    translated: list[dict] = []
    skipped: list[dict] = []
    by_name: dict[str, dict] = {}       # name -> translated entry
    skip_names: set[str] = set()
    dag: dict[str, list[str]] = {}
    window_measures: list[str] = []

    for dim in parsed["dimensions"]:
        _translate_item(lambda: translate_dimension(dim, tables),
                        dim["name"], "dimension",
                        translated, skipped, by_name, skip_names)

    deferred: list[dict] = []
    for m in parsed["measures"]:
        refs = list(m["cross_refs"]) + list(m["lod_refs"])
        if refs:
            dag[m["name"]] = refs
            deferred.append(m)
            continue
        fn = ((lambda m=m: translate_window_measure(m, parsed["dimensions"], tables))
              if m.get("window") else (lambda m=m: translate_measure(m, tables)))
        if m.get("window"):
            window_measures.append(m["name"])
        _translate_item(fn, m["name"], "measure",
                        translated, skipped, by_name, skip_names)

    _translate_cross_measures(deferred, parsed, tables, translated, skipped,
                              by_name, skip_names, window_measures)

    filter_out = None
    total = len(parsed["dimensions"]) + len(parsed["measures"])
    if parsed["filter"] is not None:
        total += 1
        try:
            filter_out = translate_filter(parsed["filter"], tables)
        except UntranslatableError as exc:
            skipped.append({"name": "MV Filter", "role": "filter",
                            "reason": str(exc)})
    n_skipped = len(skipped)
    return {"translated": translated, "skipped": skipped,
            "filter": filter_out, "dependency_dag": dag,
            "window_measures": window_measures,
            "stats": {"total": total, "translated": total - n_skipped,
                      "skipped": n_skipped}}


def _validate_tables(tables: dict) -> None:
    if not isinstance(tables, dict) or "source" not in tables:
        raise ValueError(
            "--tables map must be a JSON object with a 'source' key "
            "(alias path -> ThoughtSpot table name)")
    for k, v in tables.items():
        if not isinstance(k, str) or not isinstance(v, str) or not v.strip():
            raise ValueError(
                f"--tables entries must map string alias paths to non-empty "
                f"table names (bad entry: {k!r}: {v!r})")


def _translate_item(fn, name, role, translated, skipped, by_name,
                    skip_names) -> None:
    try:
        entry = fn()
    except UntranslatableError as exc:
        skipped.append({"name": name, "role": role, "reason": str(exc)})
        skip_names.add(name)
        return
    translated.append(entry)
    by_name[name] = entry


def _translate_cross_measures(deferred, parsed, tables, translated, skipped,
                              by_name, skip_names, window_measures) -> None:
    """Kahn topo-sort the MEASURE()/ANY_VALUE() referrers, inline in order."""
    names = {m["name"] for m in deferred}
    waiting = {m["name"]: m for m in deferred}
    indegree = {m["name"]: sum(1 for r in (m["cross_refs"] + m["lod_refs"])
                               if r in names)
                for m in deferred}
    queue = [n for n, d in indegree.items() if d == 0]
    order: list[str] = []
    while queue:
        n = queue.pop(0)
        order.append(n)
        for other in deferred:
            if n in (other["cross_refs"] + other["lod_refs"]):
                indegree[other["name"]] -= 1
                if indegree[other["name"]] == 0:
                    queue.append(other["name"])
    for m_name in order:
        m = waiting[m_name]
        if m.get("window"):
            window_measures.append(m_name)
        _translate_item(
            lambda m=m: _inline_and_translate(m, parsed, tables, by_name,
                                              skip_names),
            m_name, "measure", translated, skipped, by_name, skip_names)
    for m_name in names - set(order):  # cycle members
        skipped.append({"name": m_name, "role": "measure",
                        "reason": "circular MEASURE() reference "
                                  f"(cycle involves: {sorted(names - set(order))})"})
        skip_names.add(m_name)


def _inline_and_translate(m, parsed, tables, by_name, skip_names) -> dict:
    if m.get("window"):
        return translate_window_measure(m, parsed["dimensions"], tables)
    entry = translate_measure(m, tables)
    refs = entry["inlined_refs"]

    def substitute(match: re.Match) -> str:
        ref = refs[int(match.group(1))]
        if ref in skip_names or ref not in by_name:
            raise UntranslatableError(
                f"references '{ref}', which was skipped or does not exist")
        return f"( {_inline_text(by_name[ref])} )"

    entry["ts_expr"] = _PLACEHOLDER_RE.sub(substitute, entry["ts_expr"])
    return entry


def _inline_text(ref_entry: dict) -> str:
    if ref_entry["output_kind"] == "formula":
        return ref_entry["ts_expr"]
    # column-kind simple measure: synthesize its aggregate expression
    lower = {"AVERAGE": "average", "STD_DEVIATION": "stddev"}.get(
        ref_entry["aggregation"], ref_entry["aggregation"].lower())
    if ref_entry["aggregation"] == "COUNT":
        return f"count ( [{ref_entry['table']}::{ref_entry['column']}] )"
    return f"{lower} ( [{ref_entry['table']}::{ref_entry['column']}] )"
