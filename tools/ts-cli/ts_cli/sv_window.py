"""SQL window and semi-additive constructs -> ThoughtSpot window functions.

Split out of ``sv_translate`` (with ``sv_resolve``) when that module reached the
1000-line gate. Everything here answers "how does an aggregate over an
``OVER (...)`` clause, or a ``NON ADDITIVE BY`` metric, become a ThoughtSpot
``group_*`` / ``cumulative_*`` / ``moving_*`` / ``last_value`` call?" It takes a
resolver as a parameter and knows nothing about how identifiers are resolved,
so it sits below both ``sv_resolve`` and ``sv_translate`` in the import graph.
Names are re-exported from ``sv_translate`` so callers and tests import
unchanged.

Pure functions, no I/O.
"""
from __future__ import annotations

import re
from typing import Any, Callable

from ts_cli.formula_common import UntranslatableError

# --- window expression handling ----------------------------------------------

_OVER_RE = re.compile(r"\bOVER\s*\(", re.IGNORECASE)

_AGG_TO_GROUP = {
    "sum": "group_sum", "count": "group_count",
    "average": "group_average", "min": "group_min", "max": "group_max",
    "unique count": "group_unique_count",
    "median": "group_aggregate", "stddev": "group_aggregate",
    "variance": "group_aggregate",
}

_AGG_TO_CUMULATIVE = {
    "sum": "cumulative_sum", "average": "cumulative_average",
    "min": "cumulative_min", "max": "cumulative_max",
}

_AGG_TO_MOVING = {
    "sum": "moving_sum", "average": "moving_average",
    "min": "moving_min", "max": "moving_max",
}


def _skip_string_literal(expr: str, i: int, n: int) -> int:
    """Advance past a single-quoted string literal starting at position i.

    Returns the index after the closing quote."""
    i += 1
    while i < n:
        if expr[i] == "'" and i + 1 < n and expr[i + 1] == "'":
            i += 2
            continue
        if expr[i] == "'":
            return i + 1
        i += 1
    return i


def _find_over_split(expr: str) -> int | None:
    """Find the position of OVER keyword outside string literals and parens.

    Returns the char index of the 'O' in OVER, or None if not found."""
    depth = 0
    i = 0
    n = len(expr)
    while i < n:
        ch = expr[i]
        if ch == "'":
            i = _skip_string_literal(expr, i, n)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and expr[i:i + 4].upper() == "OVER":
            after = i + 4
            while after < n and expr[after] in " \t\n\r":
                after += 1
            if after < n and expr[after] == "(":
                return i
        i += 1
    return None


def _extract_over_clause(expr: str, over_pos: int) -> tuple[str, str]:
    """Split expr at OVER position into (agg_sql, window_spec_inner).

    Returns the SQL before OVER and the content inside OVER(...)."""
    agg_sql = expr[:over_pos].rstrip()
    rest = expr[over_pos + 4:].lstrip()
    if not rest.startswith("("):
        raise UntranslatableError("OVER without opening paren")
    depth = 0
    for i, ch in enumerate(rest):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                inner = rest[1:i].strip()
                return agg_sql, inner
    raise UntranslatableError("OVER clause: unbalanced parentheses")


def _clause_boundaries(upper: str) -> tuple:
    """Find regex match positions for PARTITION BY, ORDER BY, and the frame
    (ROWS or RANGE)."""
    pb = re.search(r"\bPARTITION\s+BY\b", upper)
    ob = re.search(r"\bORDER\s+BY\b", upper)
    rows = re.search(r"\b(ROWS|RANGE)\b", upper)
    return pb, ob, rows


def _parse_partition_cols(spec: str, start: int, end: int) -> list[str]:
    text = spec[start:end].strip()
    return [c.strip() for c in text.split(",") if c.strip()]


def _parse_order_cols(spec: str, start: int, end: int) -> list[dict]:
    text = spec[start:end].strip()
    cols: list[dict] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        direction = "asc"
        for t in tokens[1:]:
            if t.upper() in ("ASC", "DESC"):
                direction = t.lower()
        cols.append({"col": tokens[0], "dir": direction})
    return cols


_BOUND_RE = re.compile(r"^(UNBOUNDED|\d+)\s+(PRECEDING|FOLLOWING)$|^CURRENT\s+ROW$")


def _bound(text: str) -> tuple[str, int] | None:
    """('unbounded', 0) | ('rows', n preceding; negative = following), or None."""
    m = _BOUND_RE.match(" ".join(text.split()))
    if not m:
        return None
    if m.group(1) is None:
        return ("rows", 0)
    if m.group(1) == "UNBOUNDED":
        return ("unbounded", 0 if m.group(2) == "PRECEDING" else 1)
    n = int(m.group(1))
    return ("rows", n if m.group(2) == "PRECEDING" else -n)


def _parse_frame(spec: str, kind_start: int, start: int) -> dict:
    """The frame clause as {'kind': cumulative|moving|other, 'unit': ROWS|RANGE,
    'preceding': N, 'following': M}. ThoughtSpot's moving_* takes (N preceding,
    M following); `N PRECEDING AND CURRENT ROW` is (N, 0) — offset table,
    thoughtspot-formula-patterns.md, verified 2026-06-15."""
    unit = spec[kind_start:start].strip().upper()
    text = " ".join(spec[start:].strip().upper().split())
    m = re.match(r"^BETWEEN (.+) AND (.+)$", text)
    lo, hi = (_bound(m.group(1)), _bound(m.group(2))) if m else (_bound(text), ("rows", 0))
    if lo is None or hi is None:
        return {"kind": "other", "unit": unit}
    if lo == ("unbounded", 0) and hi == ("rows", 0):
        return {"kind": "cumulative", "unit": unit}
    if lo[0] == "unbounded" or hi[0] == "unbounded" or unit != "ROWS":
        return {"kind": "other", "unit": unit}
    return {"kind": "moving", "unit": unit, "preceding": lo[1], "following": -hi[1]}


def _parse_window_spec(spec: str) -> dict[str, Any]:
    """Parse the inner content of OVER(...) into structured components."""
    if not spec.strip():
        return {"partition_by": [], "order_by": [], "frame": None}

    pb, ob, rows = _clause_boundaries(spec.upper())

    partition = []
    if pb:
        end = ob.start() if ob else (rows.start() if rows else len(spec))
        partition = _parse_partition_cols(spec, pb.end(), end)

    order = []
    if ob:
        end = rows.start() if rows else len(spec)
        order = _parse_order_cols(spec, ob.end(), end)

    frame = _parse_frame(spec, rows.start(), rows.end()) if rows else None

    return {"partition_by": partition, "order_by": order, "frame": frame}


def _unwrap_agg(ts_expr: str) -> tuple[str, str]:
    """Extract (agg_function_name, inner_args) from translated TS agg expr.

    E.g. 'sum ( [T::x] )' -> ('sum', '[T::x]')."""
    m = re.match(r"^(\w[\w ]*?)\s*\(\s*(.*)\s*\)$", ts_expr, re.DOTALL)
    if not m:
        raise UntranslatableError(
            f"cannot unwrap aggregate from '{ts_expr}' for window translation")
    return m.group(1).strip(), m.group(2).strip()


def _frame_kind(frame: dict | None, order: list) -> str | None:
    """cumulative | moving | other, or None for an unordered window (an LOD).
    An ORDER BY with no frame is SQL's default RANGE BETWEEN UNBOUNDED PRECEDING AND
    CURRENT ROW: a running total, not a grand total."""
    if not order:
        return None
    if frame is None:
        return "cumulative"
    return frame["kind"]


def _refuse_unmappable_order(partition: list, order: list) -> None:
    """moving_* / cumulative_* take their partition from the query and order ascending
    by one column (thoughtspot-formula-patterns.md, Window Functions, 2026-07-30).
    `PARTITION BY EXCLUDING <dim>` (the query's dimensions minus <dim>) is that same
    query partition, so it passes; a fixed PARTITION BY does not."""
    if any(not p.upper().startswith("EXCLUDING") for p in partition):
        raise UntranslatableError(
            "a running or moving window with an explicit PARTITION BY has no native "
            "ThoughtSpot form (the partition comes from the search); build it as a "
            "sql_*_aggregate_op pass-through wrapped in group_aggregate")
    if len(order) != 1 or order[0]["dir"] != "asc":
        raise UntranslatableError(
            "a running or moving window ordered DESC or by several columns has no "
            "ThoughtSpot form (moving_* / cumulative_* order ascending by one column)")


def _translate_window(
    ts_agg_expr: str,
    window_spec: dict[str, Any],
    resolver: Callable[[str], str],
) -> str:
    """Translate an aggregate + OVER window spec to TS formula."""
    agg_fn, inner = _unwrap_agg(ts_agg_expr)
    partition = window_spec["partition_by"]
    order = window_spec["order_by"]
    frame = window_spec["frame"]
    kind = _frame_kind(frame, order)
    if kind in ("cumulative", "moving"):
        _refuse_unmappable_order(partition, order)

    if kind == "cumulative":
        fn = _AGG_TO_CUMULATIVE.get(agg_fn)
        if fn is None:
            raise UntranslatableError(
                f"cumulative window for '{agg_fn}' not mapped")
        order_col = resolver(order[0]["col"])
        return f"{fn} ( {inner} , {order_col} )"

    if kind == "moving":
        fn = _AGG_TO_MOVING.get(agg_fn)
        if fn is None:
            raise UntranslatableError(
                f"moving window for '{agg_fn}' not mapped")
        order_col = resolver(order[0]["col"])
        return (f"{fn} ( {inner} , {frame['preceding']} , {frame['following']} , "
                f"{order_col} )")
    if kind == "other":
        raise UntranslatableError(
            f"window frame {frame.get('unit', '')} with these bounds has no ThoughtSpot "
            f"form (moving_* counts ROWS between N preceding and M following; a RANGE "
            f"offset, an UNBOUNDED FOLLOWING end, or an unparsed bound is refused)")

    group_fn = _AGG_TO_GROUP.get(agg_fn)
    if group_fn is None:
        raise UntranslatableError(
            f"window function for '{agg_fn}' not mapped")
    if not partition:
        return f"{group_fn} ( {inner} )"
    resolved_parts = [resolver(p) for p in partition]
    parts_str = " , ".join(resolved_parts)
    return f"{group_fn} ( {inner} , {parts_str} )"


# --- semi-additive wrapping --------------------------------------------------

def _wrap_semi_additive(
    ts_expr: str,
    semi_additive: dict[str, str],
    resolver: Callable[[str], str],
) -> str:
    """Wrap a translated expression with last_value/first_value for
    semi-additive metrics.

    asc -> last_value (latest value); desc -> first_value (earliest value)."""
    order_col = resolver(semi_additive["order_col"])
    direction = semi_additive.get("direction", "asc")
    fn = "last_value" if direction == "asc" else "first_value"
    return f"{fn} ( {ts_expr} , query_groups ( ) , {{{order_col}}} )"
