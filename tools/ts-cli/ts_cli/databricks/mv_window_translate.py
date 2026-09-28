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
helpers (_find_order_dim and the per-range *_wrap builders) need
mv_translate's make_resolver/_formula_measure/display_title back.
To keep both modules independently importable regardless of which loads
first, every cross-reference to mv_translate is a late import inside the
function that needs it — this module has no top-level dependency on
mv_translate.
"""
from __future__ import annotations

import re

from ts_cli.databricks.mv_sql import UntranslatableError, translate_sql_expr

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
_TRUNC_GRAINS = {"day", "week", "month", "quarter", "year"}

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
    "(ts-databricks-formula-translation.md, Period Filter). The query's "
    "filters must also keep the rows the lag reads: a date filter that "
    "excludes the prior period returns NULL where Databricks still returns a "
    "value (live-verified 2026-09-28).")
_ORDER_BY_FORMULA = (
    "ordered by the '{title}' formula, not the raw date column: '{order}' is "
    "not a bucket of the date, and a date-ordered moving_sum forces the query "
    "to daily grain and returns NULL (live-verified 2026-09-28).")
# (order grain, offset unit) pairs whose LAG was number-matched against
# Databricks: month/month at N=1 (matrix C6) and N=12, day/day at N=364,
# week/day at 364 days = 52 rows (2026-09-28, nebula-ts-semview).
_LAG_VERIFIED = {("month", "month"), ("day", "day"), ("week", "day")}
_ORDER_FN_OK = frozenset({"DATE_ADD", "DATE_SUB", "DATE_TRUNC"})
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
    """Translate a windowed measure per the rules-doc decision tree.

    The window is applied to EVERY aggregate in the expression (BL-316 item
    7): the range decides a wrap(AGG, inner) function, and the tokenizer hands
    it each aggregate call. A single-aggregate measure gets the same text it
    always did; a ratio `SUM(a) / NULLIF(SUM(b), 0)` gets
    safe_divide ( moving_sum ( a ) , moving_sum ( b ) ).
    """
    from ts_cli.databricks.mv_translate import (
        _formula_measure, make_resolver, scalar_annotations)
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
    if order.get("formula_title") and rng["type"] != "current":
        raise UntranslatableError(
            f"range '{window['raw_range']}' over the derived order dimension "
            f"'{window['order']}' has no verified mapping (only range: current "
            f"is verified with a formula-ordered window)")
    annotations: list[dict] = []
    if rng["type"] in ("trailing", "leading"):
        wrap = _moving_wrap(window, order, annotations)
    elif rng["type"] == "cumulative":
        wrap = _cumulative_wrap(order, annotations)
    else:
        wrap = _current_wrap(window, order, annotations)
    wrapped: list[str] = []

    def hook(agg: str, inner: str) -> str:
        wrapped.append(agg)
        return wrap(agg, inner)

    resolver = make_resolver(tables, measure.get("scalar_subqueries"),
                             in_window=True)
    ts = translate_sql_expr(measure["expr"], resolver, agg_hook=hook)
    if not wrapped:
        raise UntranslatableError(
            "windowed measure expr contains no aggregate for the window to "
            "apply to (worked-example rule 9)")
    if order.get("formula_title"):
        annotations.append({"kind": "order_by_formula", "detail":
                            _ORDER_BY_FORMULA.format(title=order["formula_title"],
                                                     order=window["order"])})
    annotations.extend(scalar_annotations(measure, in_window=True))
    return _formula_measure(measure, ts, annotations=_dedupe(annotations))


def _dedupe(annotations: list[dict]) -> list[dict]:
    seen, out = set(), []
    for a in annotations:
        key = (a["kind"], a["detail"])
        if key not in seen:
            seen.add(key)
            out.append(a)
    return out


def _find_order_dim(order_name: str, dimensions: list[dict],
                    tables: dict) -> dict:
    """Classify the order: dimension -> {'grain': day|week|month|quarter|year,
    'sort_ref': '[T::col]' or '[<Formula Title>]', 'formula_title'?}.

    'day' == raw date. A week grain, or any truncation wrapped in date shifts
    (the Friday-start `DATE_ADD(DATE_TRUNC('WEEK', DATE_ADD(dt, 3)), -3)`), is
    ordered by the dimension's own formula (BL-316 item 6); build-model's
    add_formula_prefix turns `[Week]` into `[formula_Week]`."""
    from ts_cli.databricks.mv_translate import display_title, make_resolver
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
        if m and _PLAIN_COLUMN_RE.match(m.group(2).strip()):
            unit = m.group(1).lower()
            inner = m.group(2).strip()
            if unit == "day":
                return {"grain": "day", "sort_ref": resolver(inner)}
            if unit in _GRAIN_MONTHS:
                return {"grain": unit, "sort_ref": resolver(inner)}
        unit = _shifted_trunc_unit(stripped)
        if unit is not None:
            title = display_title(dim)
            return {"grain": unit, "sort_ref": f"[{title}]",
                    "formula_title": title}
        if m and not _PLAIN_COLUMN_RE.match(m.group(2).strip()):
            raise UntranslatableError(
                f"order dimension '{order_name}' truncates a non-column "
                f"expression — cannot derive the physical sort column")
        if m:
            raise UntranslatableError(
                f"order dimension '{order_name}' truncates to "
                f"'{m.group(1).lower()}' — only day/week/month/quarter/year "
                f"grains are mapped")
    raise UntranslatableError(
        f"cannot determine the physical sort column for window order "
        f"dimension '{order_name}' (expr must be a direct column, "
        f"DATE_TRUNC('<unit>', col), or a date-shifted DATE_TRUNC of one column)")


def _shifted_trunc_unit(expr: str) -> str | None:
    """Unit of an expr that is one DATE_TRUNC('<unit>', …) of ONE column,
    wrapped only in DATE_ADD/DATE_SUB shifts — else None."""
    from ts_cli.databricks.mv_sql import tokenize
    try:
        toks = tokenize(expr)
    except UntranslatableError:
        return None
    fns, cols, units = [], set(), []
    for i, (kind, text) in enumerate(toks):
        nxt = toks[i + 1] if i + 1 < len(toks) else (None, None)
        if kind == "ident" and nxt == ("op", "("):
            fns.append(text.upper())
        elif kind == "ident":
            cols.add(text)
        elif kind == "string":
            units.append(text.strip("'").lower())
        elif kind not in ("op", "number"):
            return None
    if (fns.count("DATE_TRUNC") != 1 or not set(fns) <= _ORDER_FN_OK
            or len(cols) != 1 or len(units) != 1
            or units[0] not in _TRUNC_GRAINS):
        return None
    return units[0]


def _moving_wrap(window, order, annotations):
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
    n = rng["n"]
    if rng["type"] == "trailing":
        start, end = (n, -1) if rng["anchor"] == "exclusive" else (n - 1, 0)
    else:  # leading
        start, end = (-1, n) if rng["anchor"] == "exclusive" else (0, n - 1)

    def wrap(agg: str, inner: str) -> str:
        fn = _MOVING_FN.get(agg)
        if fn is None:
            raise UntranslatableError(
                f"aggregate '{agg}' has no moving_* ThoughtSpot function")
        annotations.append({"kind": "sparse_data_risk",
                            "detail": _SPARSE_RISK.format(
                                raw_range=window["raw_range"], fn=fn,
                                order=window["order"], unit=rng["unit"])})
        if agg in ("MIN", "MAX"):
            annotations.append({"kind": "pending_verification",
                                "detail": _NOT_LIVE_TESTED.format(fn=fn)})
        return f"{fn} ( {inner} , {start} , {end} , {order['sort_ref']} )"
    return wrap


def _cumulative_wrap(order, annotations):
    def wrap(agg: str, inner: str) -> str:
        fn = _CUMULATIVE_FN.get(agg)
        if fn is None:
            raise UntranslatableError(
                f"aggregate '{agg}' has no cumulative_* ThoughtSpot function")
        if agg != "SUM":
            annotations.append({"kind": "pending_verification",
                                "detail": _NOT_LIVE_TESTED.format(fn=fn)})
        return f"{fn} ( {inner} , {order['sort_ref']} )"
    return wrap


_CURRENT_AGGS = {"SUM", "AVG", "MIN", "MAX", "COUNT", "STDDEV", "VARIANCE"}
_LOWER = {"AVG": "average", "STDDEV": "stddev", "VARIANCE": "variance"}


def _current_wrap(window, order, annotations):
    offset = window["offset"]
    if offset is not None:
        # BL-315: the day-grain branch below used to run first and return
        # last_value(...) with the offset silently dropped — a prior-year
        # measure returned this year's number. An offset always means LAG.
        return _lag_wrap(window, order, offset, annotations)

    def check(agg: str) -> str:
        if agg not in _CURRENT_AGGS:
            raise UntranslatableError(
                f"aggregate '{agg}' has no ThoughtSpot aggregate-function "
                f"mapping for a range: current window")
        return _LOWER.get(agg, agg.lower())

    if order["grain"] == "day":  # raw date -> true semi-additive (C7)
        fn = "last_value" if window["semiadditive"] == "last" else "first_value"

        def wrap(agg: str, inner: str) -> str:
            lower = check(agg)
            if agg != "SUM":
                annotations.append({"kind": "pending_verification",
                                    "detail": _NOT_LIVE_TESTED.format(fn=fn)})
            return (f"{fn} ( {lower} ( {inner} ) , query_groups ( ) , "
                    f"{{ {order['sort_ref']} }} )")
        return wrap

    def plain(agg: str, inner: str) -> str:  # period filter, no offset (C6)
        return f"{check(agg)} ( {inner} )"
    return plain


def _lag_periods(grain: str, offset: dict) -> int:
    """Rows back for a `range: current` + `offset:` window at this grain."""
    unit, n = offset["unit"], abs(offset["n"])
    if grain == "day":
        if unit in ("day", "week"):
            return n * (7 if unit == "week" else 1)
        raise UntranslatableError(
            f"offset '{offset['n']} {unit}' over a daily order dimension: a "
            f"calendar {unit} is not a fixed number of day rows")
    if grain == "week":
        if unit == "week":
            return n
        if unit == "day" and n % 7 == 0:
            return n // 7
        raise UntranslatableError(
            f"offset '{offset['n']} {unit}' does not divide evenly into the "
            f"'week' order grain")
    unit_months = _UNIT_MONTHS.get(unit)
    if unit_months is None:
        raise UntranslatableError(
            f"offset unit '{unit}' has no period-offset mapping "
            f"(month|quarter|year — day/week offsets are not periods)")
    grain_months = _GRAIN_MONTHS[grain]
    total = n * unit_months
    if total % grain_months:
        raise UntranslatableError(
            f"offset '{offset['n']} {unit}' does not divide evenly "
            f"into the '{grain}' order grain")
    return total // grain_months


def _lag_wrap(window, order, offset, annotations):
    p = _lag_periods(order["grain"], offset)
    annotations.append({"kind": "one_row_per_period",
                        "detail": _ONE_ROW_PER_PERIOD.format(order=window["order"])})
    if (order["grain"], offset["unit"]) not in _LAG_VERIFIED:
        annotations.append({"kind": "pending_verification",
                            "detail": _C8_PENDING.format(
                                grain=order["grain"], unit=offset["unit"])})

    def wrap(agg: str, inner: str) -> str:
        if agg != "SUM":
            raise UntranslatableError(
                f"period-offset windows are documented for SUM measures only "
                f"(the moving_sum LAG idiom); aggregate '{agg}' needs a live probe")
        return f"moving_sum ( {inner} , {p} , -{p} , {order['sort_ref']} )"
    return wrap
