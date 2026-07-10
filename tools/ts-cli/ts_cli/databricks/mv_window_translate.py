"""Windowed-measure translation for `ts databricks translate-formulas`.

Split out of mv_translate.py to keep both files under the file-size warn
line (BL-063 PR3) — pure function move, no behavior change. Pure functions:
parsed window measure + dimensions + alias->table map in, translated entry
dict out. No I/O, no network calls. stdlib only (Genie-vendorable).

Decision-tree rules: agents/shared/mappings/ts-databricks/
ts-from-databricks-rules.md (window decision tree section). BL-098 items 1-2
(sparse-data risk annotation) are implemented here — see _SPARSE_RISK.

Circular-import seam: translate_window_measure is called by
mv_translate.translate_metric_view and re-exported from mv_translate for
that module's public API (tests import it from mv_translate), but its own
helpers (_find_order_dim, _window_inner, _window_moving, _window_cumulative,
_window_current) need mv_translate's make_resolver/_formula_measure back.
To keep both modules independently importable regardless of which loads
first, every cross-reference to mv_translate is a late import inside the
function that needs it — this module has no top-level dependency on
mv_translate.
"""
from __future__ import annotations

import re

from ts_cli.databricks.mv_expr import mask_string_literals
from ts_cli.databricks.mv_sql import UntranslatableError, translate_sql_expr

_OUTER_AGG_RE = re.compile(r"^([A-Za-z_]\w*)\s*\((.*)\)\s*$", re.DOTALL)
_DATE_TRUNC_DIM_RE = re.compile(
    r"^DATE_TRUNC\s*\(\s*'(\w+)'\s*,\s*(.+?)\s*\)\s*$", re.IGNORECASE | re.DOTALL)
_PLAIN_COLUMN_RE = re.compile(
    r"^(?:`[^`]+`|[A-Za-z_][\w$]*)(?:\.(?:`[^`]+`|[A-Za-z_][\w$]*))*$")
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
    from ts_cli.databricks.mv_translate import make_resolver
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
            inner = m.group(2).strip()
            if not _PLAIN_COLUMN_RE.match(inner):
                raise UntranslatableError(
                    f"order dimension '{order_name}' truncates a non-column "
                    f"expression — cannot derive the physical sort column")
            if unit == "day":
                return {"grain": "day", "sort_ref": resolver(inner)}
            if unit in _GRAIN_MONTHS:
                return {"grain": unit, "sort_ref": resolver(inner)}
            raise UntranslatableError(
                f"order dimension '{order_name}' truncates to '{unit}' — "
                f"only day/month/quarter/year grains are mapped")
    raise UntranslatableError(
        f"cannot determine the physical sort column for window order "
        f"dimension '{order_name}' (expr must be a direct column or "
        f"DATE_TRUNC('<unit>', col))")


def _window_inner(measure: dict, tables: dict) -> tuple[str, str]:
    """Strip the outer aggregate; return (AGG_NAME, translated_inner_ts)."""
    from ts_cli.databricks.mv_translate import make_resolver
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
    from ts_cli.databricks.mv_translate import _formula_measure
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
    from ts_cli.databricks.mv_translate import _formula_measure
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


_CURRENT_AGGS = {"SUM", "AVG", "MIN", "MAX", "COUNT", "STDDEV", "VARIANCE"}


def _window_current(measure, window, order, agg, inner) -> dict:
    from ts_cli.databricks.mv_translate import _formula_measure
    if agg not in _CURRENT_AGGS:
        raise UntranslatableError(
            f"aggregate '{agg}' has no ThoughtSpot aggregate-function "
            f"mapping for a range: current window")
    lower = {"AVG": "average", "STDDEV": "stddev",
             "VARIANCE": "variance"}.get(agg, agg.lower())
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
