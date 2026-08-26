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

from ts_cli.formula_common import rewrite_marker_calls, wrap_passthrough_calls

# ---------------------------------------------------------------------------
# Function-name map + translator
# ---------------------------------------------------------------------------

# Functions with NO ThoughtSpot equivalent: marker name (lowercase) ->
# (sql_*_op, SQL template, arity). BL-171 — `upper`/`lower` were disproved
# 2026-06-13 and `trim`/`ltrim`/`rtrim`/`replace` on 2026-07-29, all
# re-verified 2026-07-30 on se-thoughtspot: each bare call is rejected with
# `Search did not find "<fn> ("` (error_code 14516). FUNCTION_MAP maps the
# Qlik name onto the marker; `_remap_functions` then rewrites the marker into
# the pass-through, so the marker never reaches an emitted formula (asserted
# by tests/test_qlik_functions.py::TestMapIntegrity).
PASSTHROUGH_MAP: dict[str, tuple[str, str, int]] = {
    "upper": ("sql_string_op", "UPPER({0})", 1),
    "lower": ("sql_string_op", "LOWER({0})", 1),
    "trim": ("sql_string_op", "TRIM({0})", 1),
    "ltrim": ("sql_string_op", "LTRIM({0})", 1),
    "rtrim": ("sql_string_op", "RTRIM({0})", 1),
    "replace": ("sql_string_op", "REPLACE({0}, {1}, {2})", 3),
}


def _mid(args: list[str]) -> Optional[str]:
    """Qlik Mid(str, start, n) -> ThoughtSpot substr, start decremented.

    Qlik `Mid()` is **1-indexed**; ThoughtSpot `substr()` takes a
    **ZERO-indexed** start (`thoughtspot-formula-patterns.md` String Functions
    — the authoritative source per CLAUDE.md's precedence, and the offset the
    Tableau converter's MID handler has always applied). A bare `mid`->`substr`
    rename therefore imports cleanly and returns strings shifted by one
    character — the valid-but-wrong class, which is worse than the bare
    `mid ( )` it replaced: that at least failed loudly with error_code 14516.
    """
    if len(args) != 3:
        return None
    return f"substr({args[0]}, {args[1]} - 1, {args[2]})"


def _index(args: list[str]) -> Optional[str]:
    """Qlik Index(str, substr[, n]) -> ThoughtSpot strpos — 2 arguments only.

    `strpos(x, sub)` returns the position of the **first** occurrence, which is
    exactly Qlik `Index()` with its default `n=1`. The **nth-occurrence** form
    (`n` >= 2) has no ThoughtSpot equivalent at all, and a bare rename passed
    the third argument straight through as `strpos(x, sub, 2)` — a real function
    with the wrong arity, so the translation reported success and the *import*
    failed later — live-confirmed on se-thoughtspot 2026-07-30: `Function strpos
    expects only 2 arguments.` (error_code 14516). Returning None here flags it
    at translate time instead, which is where a reviewer can act on it.
    """
    if len(args) != 2:
        return None
    return f"strpos({args[0]}, {args[1]})"


def _weekday(args: list[str]) -> Optional[str]:
    """Qlik Weekday(date) -> ThoughtSpot day_number_of_week, origin shifted.

    Qlik `Weekday()` returns a **number** with **0 = Monday**; ThoughtSpot
    `day_of_week()` returns the day NAME (so the old mapping compared a name to
    a number) and `day_number_of_week()` returns **1 = Monday**. Renaming alone
    leaves every literal comparison off by one — `Weekday(d) = 5` would mean
    Friday instead of Saturday — so the origin is shifted here.

    Caveat: a Qlik app with a non-default `FirstWeekDay` numbers the days from a
    different origin. That is app configuration the converter cannot see; the
    shift above assumes Qlik's default. Documented on row D06.
    """
    if len(args) != 1:
        return None
    return f"(day_number_of_week({args[0]}) - 1)"


# Functions needing an ARGUMENT-AWARE rewrite rather than a rename: marker
# name -> handler(args) -> replacement or None (flagged for review). Same
# marker mechanism as PASSTHROUGH_MAP; the handler emits native ThoughtSpot
# functions rather than a sql_*_op pass-through.
#
# Both entries exist because a bare rename is *valid and wrong* — an index or
# origin differs between the two platforms, which imports cleanly and returns
# the wrong answer. That is the failure mode BL-171 was filed against.
# `index` is here for a third reason: an arity the ThoughtSpot target cannot
# express. A bare rename let the extra argument through into a real function
# with the wrong arity, which reads as a successful translation and fails at
# import — unflagged, so nobody sees it until then.
COMPOSITION_MAP: dict[str, Any] = {
    "mid": _mid, "weekday": _weekday, "index": _index,
}

# Qlik function name (lowercase) -> ThoughtSpot formula function.
# None means "no equivalent" -> flagged for manual review. A value that is a
# PASSTHROUGH_MAP key is an intermediate marker, not an emitted name.
#
# BL-171: every value here was audited end-to-end against
# thoughtspot-formula-patterns.md and live-probed on se-thoughtspot
# (2026-07-30). Do not add a value without checking it exists — the previous
# map carried `len`, `mid`, `ceiling`, `power`, `log`, `day_of_month` and four
# `date_trunc_*` names, none of which is a ThoughtSpot function.
FUNCTION_MAP: dict[str, Optional[str]] = {
    # aggregation
    "sum": "sum", "avg": "average", "average": "average", "count": "count",
    "min": "min", "max": "max", "median": "median", "stdev": "stddev",
    "variance": "variance",
    # string
    "left": "left", "right": "right", "mid": "mid", "len": "strlen",
    "upper": "upper", "lower": "lower", "trim": "trim", "ltrim": "ltrim",
    "rtrim": "rtrim", "index": "index",
    # Qlik Concat() aggregates values ACROSS rows (GROUP_CONCAT); ThoughtSpot
    # concat() joins within one row (S14) — mapping the name produced a
    # valid-but-wrong formula, so it is flagged instead (flag, don't downgrade).
    "concat": None,
    "replace": "replace", "num": "to_double", "text": "to_string",
    "subfield": None,
    # date
    "year": "year", "month": "month_number", "day": "day",
    "weekday": "weekday", "quarter": "quarter_number", "today": "today",
    "now": "now", "addmonths": "add_months", "addyears": "add_years",
    "monthstart": "start_of_month", "yearstart": "start_of_year",
    "quarterstart": "start_of_quarter", "weekstart": "start_of_week",
    "date": "to_date", "networkdays": None,
    # math
    "round": "round", "floor": "floor", "ceil": "ceil", "abs": "abs",
    "sqrt": "sqrt", "pow": "pow", "log": "ln", "exp": "exp", "mod": "mod",
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

    # Count(DISTINCT X) -> `unique count(X)`. BL-171: the function name has a
    # SPACE — `unique_count` (underscore) does not exist and is rejected with
    # error_code 14516 (live-verified 2026-07-30, se-thoughtspot). Only the
    # conditional variants carry an underscore (`unique_count_if`).
    m = re.match(r"(?i)^count\(\s*distinct\s+(.+?)\)$", expr)
    if m:
        return f"unique count({m.group(1).strip()})", False, ""

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


def _remap_functions(expr: str) -> tuple[str, set[str]]:
    unknown: set[str] = set()
    # marker name -> the spelling the source expression actually used, so a
    # flag reads "LTrim" (what the author wrote) rather than a reconstructed
    # "Ltrim" that appears nowhere in their app.
    origin: dict[str, str] = {}

    def repl(m: re.Match) -> str:
        name = m.group(1)
        low = name.lower()
        if low in FUNCTION_MAP:
            ts = FUNCTION_MAP[low]
            if ts is None:
                unknown.add(name)
                return f"{name}("        # leave as-is, flagged
            if ts in PASSTHROUGH_MAP or ts in COMPOSITION_MAP:
                origin[ts] = name
            return f"{ts}("
        unknown.add(name)
        return f"{name}("

    out = _FUNC_CALL.sub(repl, expr)
    out = out.replace("<>", "!=").replace("&", "+")
    # BL-171: rewrite the no-equivalent markers into sql_*_op pass-throughs,
    # then the argument-aware compositions. An unresolved marker (wrong arity,
    # unbalanced parens) is flagged rather than emitted — a bare trim/replace
    # call is rejected at import with error_code 14516, and a bare `mid` does
    # not exist at all.
    # quote='"' explicitly: formula_common defaults to a SINGLE quote, and this call
    # was the only one of the five BL-171 emitters to take the default -- so Qlik alone
    # emitted sql_string_op('UPPER({0})', …) while its siblings (and every example in
    # thoughtspot-formula-patterns.md) use the double-quoted outer template. Only the
    # single-quoted form is unverified against the parser, and BL-171 existed to stop
    # emitting forms ThoughtSpot rejects (audit finding 17.2).
    out, unresolved = wrap_passthrough_calls(out, PASSTHROUGH_MAP, quote='"')
    out, unresolved_comp = rewrite_marker_calls(out, COMPOSITION_MAP)
    unknown |= {origin.get(name, name)
                for name in (unresolved | unresolved_comp)}
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


def _agg_fn(name: str) -> str:
    """The ThoughtSpot aggregation for a Qlik aggregation name.

    Falls back to `sum` both for an unmapped name and for one mapped to None
    (no equivalent) — the previous `.get(name, "sum")` returned None for the
    latter and emitted a literal `None(...)` into the formula."""
    return FUNCTION_MAP.get(name.lower()) or "sum"


def _set_analysis(expr: str) -> tuple[str, bool, str]:
    # Pattern 1: {1} -> ignore all selections (total).
    m = re.match(r"(?i)^(\w+)\(\s*\{1\}\s*(.+?)\)$", expr)
    if m:
        agg = _agg_fn(m.group(1))
        return f"group_aggregate({agg}({m.group(2).strip()}), {{}}, {{}})", False, ""

    # Pattern 2/3/4: {<Field={...}>} (equals / exclude / union).
    m = re.match(r"(?i)^(\w+)\(\s*\{<\s*([\w \[\]]+?)\s*(-?=)\s*(.+?)\s*>\}\s*(.+?)\)$", expr)
    if m:
        agg_fn = _agg_fn(m.group(1))
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
