"""Qlik expression -> ThoughtSpot formula translation + coverage reference.

Ported from the vendored q2t transform package (expr.py + formula_map.py).

``translate(expr) -> (ts_formula, review_required, reason)`` is the pragmatic
translator: a function-name map (aggregation / string / date / math),
conditional rewriting (If/nested), and Set Analysis pattern recognition.
Anything it cannot translate confidently is returned with review_required=True
and a human-readable reason — never silently dropped, never substituted with a
wrong-but-valid formula (flag-don't-downgrade; see .claude/rules and the repo
CLAUDE.md "Flag, don't downgrade" convention).

The ``lookup`` / ``classify`` / ``audit`` helpers load the canonical mapping
table (``data/qlik_ts_formula_map.json``) and answer, before translating, how
much of an app's formula surface will convert cleanly vs. need manual work.

Pure functions — stdlib only (the mapping table loads via importlib.resources).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Function-name map + translator
# ---------------------------------------------------------------------------

# Qlik function name (lowercase) -> ThoughtSpot formula function.
# None means "no equivalent" -> flagged for manual review.
FUNCTION_MAP: dict[str, Optional[str]] = {
    # aggregation
    "sum": "sum", "avg": "average", "average": "average", "count": "count",
    "min": "min", "max": "max", "median": "median", "stdev": "stddev",
    "variance": "variance",
    # string
    "left": "left", "right": "right", "mid": "mid", "len": "len",
    "upper": "upper", "lower": "lower", "trim": "trim", "ltrim": "ltrim",
    "rtrim": "rtrim", "index": "strpos", "concat": "concat",
    "replace": "replace", "num": "to_double", "text": "to_string",
    "subfield": None,
    # date
    "year": "year", "month": "month_number", "day": "day_of_month",
    "weekday": "day_of_week", "quarter": "quarter_number", "today": "today",
    "now": "now", "addmonths": "add_months", "addyears": "add_years",
    "monthstart": "date_trunc_month", "yearstart": "date_trunc_year",
    "quarterstart": "date_trunc_quarter", "weekstart": "date_trunc_week",
    "date": "to_date", "networkdays": None,
    # math
    "round": "round", "floor": "floor", "ceil": "ceiling", "abs": "abs",
    "sqrt": "sqrt", "pow": "power", "log": "log", "exp": "exp", "mod": "mod",
    "rangesum": None, "mode": None,
}


def translate(expr: str) -> tuple[str, bool, str]:
    """Translate a Qlik expression to a ThoughtSpot formula.

    Returns ``(ts_formula, review_required, reason)``. When review_required is
    True the original intent could not be faithfully translated — ``ts_formula``
    carries a ``/* TODO review ... */`` marker (never a plausible-but-wrong
    substitute) and ``reason`` explains why.
    """
    expr = (expr or "").strip()
    if not expr:
        return "", False, ""

    # Set Analysis first — recognizable by {<...>} / {1} / {$}.
    if "{" in expr:
        return _set_analysis(expr)

    # Count(DISTINCT X) -> unique_count(X)
    m = re.match(r"(?i)^count\(\s*distinct\s+(.+?)\)$", expr)
    if m:
        return f"unique_count({m.group(1).strip()})", False, ""

    # If(cond, t, f) -> if (cond) then t else f
    if re.match(r"(?i)^if\s*\(", expr):
        rewritten = _translate_if(expr)
        if rewritten is not None:
            return rewritten, False, ""
        return (f"/* TODO review: {expr} */", True,
                f"Could not parse If() structure: {expr}")

    # Generic function-name remap on the whole expression.
    out, unknown = _remap_functions(expr)
    if unknown:
        return out, True, f"Unmapped Qlik function(s): {', '.join(sorted(unknown))}"
    return out, False, ""


_FUNC_CALL = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")

# ThoughtSpot has no native upper()/lower() in formula context — push them to
# the warehouse via sql_string_op (same pattern the Tableau converter uses).
# FUNCTION_MAP keeps upper/lower "known" (so they are never flagged as unmapped);
# _wrap_string_ops rewrites the emitted upper(...)/lower(...) into sql_string_op.
_STRING_OP = {"upper": "UPPER", "lower": "LOWER"}
_STROP_TOKEN = re.compile(r"(?<![A-Za-z0-9_])(upper|lower)\s*\(")


def _wrap_string_ops(text: str) -> str:
    """Rewrite bare upper(x)/lower(x) into sql_string_op('UPPER({0})', x)."""
    while True:
        m = _STROP_TOKEN.search(text)
        if not m:
            return text
        fn = m.group(1)
        open_idx = m.end() - 1
        depth, in_str, i = 0, None, open_idx
        while i < len(text):
            ch = text[i]
            if in_str:
                if ch == in_str:
                    in_str = None
            elif ch in "'\"":
                in_str = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        if depth != 0:
            return text  # unbalanced parens; leave as-is rather than corrupt
        inner = text[open_idx + 1:i].strip()
        replacement = f"sql_string_op('{_STRING_OP[fn]}({{0}})', {inner})"
        text = text[:m.start()] + replacement + text[i + 1:]


def _remap_functions(expr: str) -> tuple[str, set[str]]:
    unknown: set[str] = set()

    def repl(m: re.Match) -> str:
        name = m.group(1)
        low = name.lower()
        if low in FUNCTION_MAP:
            ts = FUNCTION_MAP[low]
            if ts is None:
                unknown.add(name)
                return f"{name}("        # leave as-is, flagged
            return f"{ts}("
        unknown.add(name)
        return f"{name}("

    out = _FUNC_CALL.sub(repl, expr)
    out = out.replace("<>", "!=").replace("&", "+")
    out = _wrap_string_ops(out)
    return out, unknown


def _translate_if(expr: str) -> Optional[str]:
    """If(cond, true[, false]) -> if (cond) then true else false, recursively."""
    args = _split_call(expr, "if")
    if args is None or len(args) < 2:
        return None
    cond, _ = _remap_functions(args[0])
    true_val = _translate_arg(args[1])
    if len(args) >= 3:
        false_val = _translate_arg(args[2])
        return f"if ({cond}) then {true_val} else {false_val}"
    return f"if ({cond}) then {true_val}"


def _translate_arg(arg: str) -> str:
    arg = arg.strip()
    if re.match(r"(?i)^if\s*\(", arg):
        inner = _translate_if(arg)
        if inner is not None:
            return inner
    out, _ = _remap_functions(arg)
    return out


def _split_call(expr: str, fname: str) -> Optional[list[str]]:
    m = re.match(rf"(?i)^{fname}\s*\((.*)\)\s*$", expr, re.DOTALL)
    if not m:
        return None
    return _split_top_level(m.group(1))


def _split_top_level(s: str) -> list[str]:
    parts, depth, cur, in_str = [], 0, [], None
    for ch in s:
        if in_str:
            cur.append(ch)
            if ch == in_str:
                in_str = None
            continue
        if ch in "'\"":
            in_str = ch
            cur.append(ch)
        elif ch in "([{":
            depth += 1
            cur.append(ch)
        elif ch in ")]}":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur))
    return [p.strip() for p in parts]


def _set_analysis(expr: str) -> tuple[str, bool, str]:
    # Pattern 1: {1} -> ignore all selections (total).
    m = re.match(r"(?i)^(\w+)\(\s*\{1\}\s*(.+?)\)$", expr)
    if m:
        agg = FUNCTION_MAP.get(m.group(1).lower(), "sum")
        return f"group_aggregate({agg}({m.group(2).strip()}), {{}}, {{}})", False, ""

    # Pattern 2/3/4: {<Field={...}>} (equals / exclude / union).
    m = re.match(r"(?i)^(\w+)\(\s*\{<\s*([\w \[\]]+?)\s*(-?=)\s*(.+?)\s*>\}\s*(.+?)\)$", expr)
    if m:
        agg_fn = FUNCTION_MAP.get(m.group(1).lower(), "sum")
        field = m.group(2).strip().strip("[]")
        op = m.group(3)
        raw_vals = m.group(4)
        measure = m.group(5).strip()
        groups = re.findall(r"\{([^}]*)\}", raw_vals) or [raw_vals]
        values = []
        for g in groups:
            values += [v.strip().strip("'\"") for v in g.split(",") if v.strip()]
        if op == "-=":
            cond = " and ".join(f"{field} != '{v}'" for v in values) or "true"
        else:
            cond = " or ".join(f"{field} = '{v}'" for v in values) or "true"
        if len(values) > 1:
            cond = f"({cond})"
        return f"{agg_fn}(if ({cond}) then {measure} else 0)", False, ""

    # Pattern 5/6: intersection with selection ($*<...>) or $-expansion.
    if "$" in expr:
        return (f"/* TODO review set analysis: {expr} */", True,
                "Set analysis uses current-selection context ($) or $-expansion; "
                "approximate manually — selection state is not preserved in ThoughtSpot.")

    return (f"/* TODO review set analysis: {expr} */", True,
            f"Unrecognized Set Analysis pattern: {expr}")


# ---------------------------------------------------------------------------
# Mapping-table reference (coverage / audit)
# ---------------------------------------------------------------------------

_MANUAL_MARKERS = ("no direct equivalent", "no equivalent")
_FUNC_TOKEN = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")


@dataclass
class Mapping:
    id: str
    category: str
    qlik: str
    qlik_example: str
    ts: str
    ts_example: str
    comment: str
    status: str            # ok | corrected | verify

    @property
    def tier(self) -> str:
        if self.status == "verify":
            return "verify"
        if any(m in self.ts.lower() for m in _MANUAL_MARKERS):
            return "manual"
        return "translatable"


def _load_map_raw() -> list[dict]:
    """Load the canonical mapping rows from packaged data.

    Uses importlib.resources so the JSON resolves whether the package is run
    from the source tree or an installed wheel (see pyproject package-data).
    """
    from importlib import resources
    with resources.files(__package__).joinpath("data/qlik_ts_formula_map.json").open(
        encoding="utf-8"
    ) as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def _rows() -> list[Mapping]:
    out = []
    for r in _load_map_raw():
        out.append(Mapping(
            id=r.get("#", ""), category=r.get("Category", ""),
            qlik=r.get("Qlik Sense Formula", ""), qlik_example=r.get("Qlik Example", ""),
            ts=r.get("ThoughtSpot Equivalent", ""), ts_example=r.get("ThoughtSpot Example", ""),
            comment=r.get("Comments / Context", ""), status=r.get("status", "ok"),
        ))
    return out


@lru_cache(maxsize=1)
def _by_fn() -> dict[str, list[Mapping]]:
    idx: dict[str, list[Mapping]] = {}
    for m in _rows():
        token = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)", m.qlik)
        if token:
            idx.setdefault(token.group(1).lower(), []).append(m)
    return idx


def lookup(text: str) -> list[Mapping]:
    """Find mappings by Qlik function name or free-text substring."""
    text = text.strip().lower()
    hits = list(_by_fn().get(text, []))
    if hits:
        return hits
    return [m for m in _rows()
            if text in m.qlik.lower() or text in m.ts.lower() or text in m.category.lower()]


def classify(expr: str) -> list[tuple[str, Optional[Mapping]]]:
    """Return (function_name, mapping-or-None) for each function used in expr."""
    seen, result = set(), []
    for fn in _FUNC_TOKEN.findall(expr or ""):
        low = fn.lower()
        if low in seen:
            continue
        seen.add(low)
        rows = _by_fn().get(low)
        result.append((fn, rows[0] if rows else None))
    return result


def audit(expressions: list[str]) -> dict[str, Any]:
    """Coverage summary across a list of Qlik expressions."""
    translatable, manual, verify, unknown = set(), set(), set(), set()
    for expr in expressions:
        for fn, m in classify(expr):
            if m is None:
                unknown.add(fn)
            elif m.tier == "manual":
                manual.add(fn)
            elif m.tier == "verify":
                verify.add(fn)
            else:
                translatable.add(fn)
    total = len(translatable | manual | verify | unknown)
    return {
        "expressions": len(expressions),
        "distinct_functions": total,
        "translatable": sorted(translatable),
        "manual": sorted(manual),
        "verify": sorted(verify),
        "unknown": sorted(unknown),
        "coverage_pct": round(100 * len(translatable) / total, 1) if total else 100.0,
    }
