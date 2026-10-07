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
from functools import lru_cache, partial
from typing import Any, Optional

from ts_cli.formula_common import (
    rewrite_marker_calls,
    wrap_passthrough_calls,
)
from ts_cli.formula_text import ts_finalize_formula
# Weekday() / WeekStart() / FirstWeekDay live in qlik/weeks.py (split under the
# file-size gate) and are re-exported here.
from ts_cli.qlik.weeks import (  # noqa: F401
    _weekday, _weekstart, _weekstart_arg_problem, known_week_starts,
    parse_first_week_day,
)

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
    "mid": _mid, "weekday": _weekday, "index": _index, "weekstart": _weekstart,
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
    "quarterstart": "start_of_quarter", "weekstart": "weekstart",
    "date": "to_date", "networkdays": None,
    # math
    "round": "round", "floor": "floor", "ceil": "ceil", "abs": "abs",
    "sqrt": "sqrt", "pow": "pow", "log": "ln", "exp": "exp", "mod": "mod",
    "rangesum": None, "mode": None,
}


def field_quotes_to_brackets(expr: str) -> str:
    """Rewrite Qlik's double-quoted FIELD names to its other field-quoting form:
    ``"Sales Amount"`` -> ``[Sales Amount]`` (BL-368).

    In Qlik a double-quoted token is a field name and a single-quoted one is a string
    literal; in ThoughtSpot (since BL-365) a double-quoted token is a string literal, so a
    field name left double-quoted would be summed as a constant string. Untouched:

    * single-quoted literals (``'say "hi"'``) — SQL-standard, ``''`` escapes a quote;
    * ``[...]`` field names, which may legitimately hold a double quote;
    * Set Analysis ``{...}`` regions, where ``{"2023"}`` is an element-set *value* (a
      search string), not a field — ``_set_analysis`` strips those quotes itself.

    A doubled ``""`` inside a double-quoted name is Qlik's escape and is unescaped.
    Idempotent: a second pass finds no double-quoted field to rewrite.
    """
    return _field_quotes(expr)[0]


def _field_quotes(expr: str) -> tuple[str, Optional[str]]:
    """``field_quotes_to_brackets`` plus why a double-quoted name could not become a
    field reference (None when every one could): an empty ``""``, an unterminated
    quote, or a name holding ``]`` — which cannot sit inside ``[…]`` (#583 review)."""
    out: list[str] = []
    problem: Optional[str] = None
    i, n, depth = 0, len(expr), 0
    while i < n:
        c = expr[i]
        if c == "'":
            j, _ = _scan_quoted(expr, i, "'")
            out.append(expr[i:j + 1])
        elif c == "[":
            j = expr.find("]", i + 1)
            j = n - 1 if j < 0 else j
            out.append(expr[i:j + 1])
        elif c == '"' and depth == 0:
            j, name = _scan_quoted(expr, i, '"')
            why = _field_name_problem(name, j >= n)
            problem = problem or why
            out.append(expr[i:j + 1] if why else f"[{name}]")
        else:
            depth = _brace_depth(c, depth)
            out.append(c)
            j = i
        i = j + 1
    return "".join(out), problem


def _field_name_problem(name: str, unterminated: bool) -> Optional[str]:
    if unterminated:
        return "an unterminated double-quoted field name"
    if not name:
        return 'an empty double-quoted field name ("")'
    if "]" in name:
        return (f'the field name "{name}" holds "]", which cannot be written as a '
                "ThoughtSpot [reference]")
    return None


def _scan_quoted(expr: str, i: int, q: str) -> tuple[int, str]:
    """From the opening quote ``q`` at ``i``: (index of the closing quote — ``len(expr)``
    when unterminated — and the content with doubled ``qq`` escapes unescaped)."""
    j, n, body = i + 1, len(expr), []
    while j < n:
        if expr[j] == q:
            if expr[j + 1:j + 2] != q:
                break
            j += 1
        body.append(expr[j])
        j += 1
    return j, "".join(body)


def _brace_depth(c: str, depth: int) -> int:
    if c == "{":
        return depth + 1
    if c == "}":
        return max(depth - 1, 0)
    return depth


def translate(expr: str, first_week_day: Optional[int] = None,
              field_types: Optional[dict[str, str]] = None) -> tuple[str, bool, str]:
    """Translate a Qlik expression to a ThoughtSpot formula (see ``_translate``). Qlik
    string literals are SQL-standard (``'it''s'``); the output's literals are printed in
    the form ThoughtSpot reads back exactly, and a product under a division is bracketed
    (BL-365). Double-quoted field names are read as fields first (BL-368), so the
    converter and ``ts formula translate --from qlik`` share one reading. The advisory
    notes of ``translate_with_notes`` are dropped here."""
    out, review, reason, _notes = translate_with_notes(expr, first_week_day, field_types)
    return out, review, reason


def translate_with_notes(expr: str, first_week_day: Optional[int] = None,
                         field_types: Optional[dict[str, str]] = None
                         ) -> tuple[str, bool, str, list[str]]:
    """``translate`` plus advisory notes that never change the status (Set Analysis
    semantics ThoughtSpot cannot match exactly — the converter's ``review_notes``).

    ``field_types``: lower-cased field name -> ThoughtSpot data type (``VARCHAR``,
    ``INT64`` …), when known; it decides whether a bare Set Analysis value is quoted."""
    fixed, problem = _field_quotes(expr or "")
    if problem:
        return (f"/* TODO review: {(expr or '').strip()} */", True,
                f"Cannot read {problem} (BL-368)", [])
    ctx = {"notes": [], "field_types": {k.lower(): v for k, v in (field_types or {}).items()}}
    out, review, reason = _translate(fixed, first_week_day, ctx)
    notes = [] if review else list(dict.fromkeys(ctx["notes"]))
    return ts_finalize_formula(out), review, reason, notes


def _translate(expr: str, first_week_day: Optional[int] = None,
               ctx: Optional[dict] = None) -> tuple[str, bool, str]:
    """Translate a Qlik expression to a ThoughtSpot formula.

    Returns ``(ts_formula, review_required, reason)``. When review_required is
    True the original intent could not be faithfully translated — ``ts_formula``
    carries a ``/* TODO review ... */`` marker (never a plausible-but-wrong
    substitute) and ``reason`` explains why.

    ``first_week_day`` is the app's `FirstWeekDay` (0 = Mon ... 6 = Sun, from
    ``parse_first_week_day``); without it a one-argument `Weekday()` is flagged.
    """
    expr = (expr or "").strip()
    if not expr:
        return "", False, ""

    # Set Analysis first — recognizable by {<...>} / {1} / {$}.
    if "{" in expr:
        return _set_analysis(expr, first_week_day, ctx)

    # Count(DISTINCT X) -> `unique count(X)`. BL-171: the function name has a
    # SPACE — `unique_count` (underscore) does not exist and is rejected with
    # error_code 14516 (live-verified 2026-07-30, se-thoughtspot). Only the
    # conditional variants carry an underscore (`unique_count_if`).
    m = re.match(r"(?i)^count\(\s*distinct\s+(.+?)\)$", expr)
    if m:
        return f"unique count({m.group(1).strip()})", False, ""

    # If(cond, t, f) -> if (cond) then t else f
    if re.match(r"(?i)^if\s*\(", expr):
        if_unknown: set[str] = set()
        rewritten = _translate_if(expr, first_week_day, if_unknown)
        if rewritten is not None:
            if if_unknown:
                return (rewritten, True,
                        _unmapped_reason(if_unknown, first_week_day, expr))
            return rewritten, False, ""
        return (f"/* TODO review: {expr} */", True,
                f"Could not parse If() structure: {expr}")

    # Generic function-name remap on the whole expression.
    out, unknown = _remap_functions(expr, first_week_day)
    if unknown:
        return out, True, _unmapped_reason(unknown, first_week_day, expr)
    return out, False, ""


def _unmapped_reason(unknown: set[str], first_week_day: Optional[int],
                     expr: str = "") -> str:
    reason = f"Unmapped Qlik function(s): {', '.join(sorted(unknown))}"
    if any(u.lower() == "weekstart" for u in unknown):
        reason += (f" — WeekStart() with a {_weekstart_arg_problem(expr)} has no exact "
                   "ThoughtSpot form (the offset must be an integer, the first week day "
                   "0-6); rewrite it by hand (BL-334)")
    if first_week_day is None and any(u.lower() == "weekday" for u in unknown):
        reason += (" — Weekday() numbers from the app's FirstWeekDay, and no "
                   "`SET FirstWeekDay=n;` was found in the load script; pass "
                   "the week start explicitly (Weekday(d, n)) or review "
                   "(BL-334)")
    return reason


_FUNC_CALL = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def _remap_functions(expr: str, first_week_day: Optional[int] = None
                     ) -> tuple[str, set[str]]:
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

    # Function calls are read outside quotes and [field names] only: a field named
    # [Re(gion] or [It's (x)] is data, not a call (#583 review).
    out = _map_code(expr, lambda seg: _FUNC_CALL.sub(repl, seg))
    out = out.replace("<>", "!=")
    if "&" in out:
        # Qlik `&` is string concatenation; ThoughtSpot `+` is numeric only (#579 review)
        joined = _concat_ampersands(out)
        if joined is None:
            unknown.add("&")
        else:
            out = joined
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
    handlers = COMPOSITION_MAP
    if first_week_day is not None:
        handlers = {**COMPOSITION_MAP,
                    "weekday": partial(_weekday, first_week_day=first_week_day),
                    "weekstart": partial(_weekstart, first_week_day=first_week_day)}
    out, unresolved_comp = rewrite_marker_calls(out, handlers)
    unknown |= {origin.get(name, name)
                for name in (unresolved | unresolved_comp)}
    return out, unknown


_RELATIONAL = re.compile(r"!=|<=|>=|[=<>]|\b(?:and|or|not)\b", re.IGNORECASE)


def _scan(expr: str, opens: str = "(", closes: str = ")"):
    """Yield (char, depth, opaque) for each character. Quoted text ('…' / "…", a doubled
    quote re-opening it) and a ``[…]`` field name are OPAQUE — nothing inside them nests,
    splits or quotes, so ``[Bob's]`` does not open a string (#583 review). ``depth``
    counts the ``opens`` / ``closes`` characters outside opaque text."""
    depth, close = 0, None
    for ch in expr:
        if close:
            yield ch, depth, True
            if ch == close:
                close = None
            continue
        if ch in "'\"[":
            close = "]" if ch == "[" else ch
            yield ch, depth, True
            continue
        if ch in opens:
            depth += 1
        elif ch in closes:
            depth -= 1
        yield ch, depth, False


def _map_code(expr: str, fn) -> str:
    """Apply ``fn`` to each run of ``expr`` outside quotes and ``[…]`` (see ``_scan``)."""
    out, run, opaque_run = [], [], False
    for ch, _depth, opaque in _scan(expr):
        if opaque != opaque_run and run:
            out.append("".join(run) if opaque_run else fn("".join(run)))
            run = []
        opaque_run = opaque
        run.append(ch)
    if run:
        out.append("".join(run) if opaque_run else fn("".join(run)))
    return "".join(out)


def _top_level_spans(expr: str):
    """Yield (char, depth, opaque) for each character, tracking () depth (see ``_scan``)."""
    return _scan(expr)


def _split_ampersands(expr: str) -> tuple[list[str], str]:
    """Split at top-level ``&``; also return the top-level text (quoted and nested blanked)."""
    parts, cur, top = [], [], []
    for ch, depth, quoted in _top_level_spans(expr):
        if ch == "&" and depth == 0 and not quoted:
            parts.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
        top.append(" " if (quoted or depth > 0) else ch)
    parts.append("".join(cur))
    return parts, "".join(top)


def _group_end(expr: str, i: int) -> int:
    """Index of the ``)`` closing the ``(`` at ``i`` (quotes and ``[…]`` skipped)."""
    for k, (_ch, depth, opaque) in enumerate(_scan(expr[i:])):
        if not opaque and depth == 0:
            return i + k
    return len(expr) - 1


def _opaque_end(expr: str, i: int) -> int:
    """Index of the character closing the quote or ``[`` at ``i``."""
    for k, (_ch, _depth, opaque) in enumerate(_scan(expr[i:])):
        if k and not opaque:
            return i + k - 1
    return len(expr) - 1


def _concat_in_groups(expr: str) -> Optional[str]:
    """Rewrite ``&`` inside each parenthesised group (function arguments) of ``expr``."""
    out, i = [], 0
    while i < len(expr):
        ch = expr[i]
        if ch in "'\"[":
            j = _opaque_end(expr, i)
        elif ch == "(":
            j = _group_end(expr, i)
            if "&" in expr[i:j + 1]:
                done = [_concat_ampersands(a) for a in _split_top_level(expr[i + 1:j])]
                if any(d is None for d in done):
                    return None
                out.append("(" + ", ".join(done) + ")")
                i = j + 1
                continue
        else:
            j = i
        out.append(expr[i:j + 1])
        i = j + 1
    return "".join(out)


def _concat_ampersands(expr: str) -> Optional[str]:
    """Qlik ``a & b & c`` -> ``concat ( a , b , c )``, recursively and quote-aware. Qlik's
    ``&`` binds looser than arithmetic and tighter than comparison, so a segment that also
    has a top-level comparison or logical operator returns None (left for review)."""
    expr = expr.strip()
    parts, top = _split_ampersands(expr)
    if len(parts) == 1:
        return _concat_in_groups(expr)
    if _RELATIONAL.search(top):
        return None
    inner = [_concat_ampersands(x) for x in parts]
    if any(not x for x in inner):
        return None
    return "concat ( " + " , ".join(inner) + " )"


def _translate_if(expr: str, first_week_day: Optional[int] = None,
                  unknown: Optional[set[str]] = None) -> Optional[str]:
    """If(cond, true[, false]) -> if (cond) then true else false, recursively.

    Unresolved names inside the branches are collected into ``unknown`` so the
    caller can flag them (previously they were discarded)."""
    if unknown is None:
        unknown = set()
    args = _split_call(expr, "if")
    if args is None or len(args) < 2:
        return None
    cond, u = _remap_functions(args[0], first_week_day)
    unknown |= u
    true_val = _translate_arg(args[1], first_week_day, unknown)
    if len(args) >= 3:
        false_val = _translate_arg(args[2], first_week_day, unknown)
        return f"if ({cond}) then {true_val} else {false_val}"
    return f"if ({cond}) then {true_val}"


def _translate_arg(arg: str, first_week_day: Optional[int] = None,
                   unknown: Optional[set[str]] = None) -> str:
    if unknown is None:
        unknown = set()
    arg = arg.strip()
    if re.match(r"(?i)^if\s*\(", arg):
        inner = _translate_if(arg, first_week_day, unknown)
        if inner is not None:
            return inner
    out, u = _remap_functions(arg, first_week_day)
    unknown |= u
    return out


def _split_call(expr: str, fname: str) -> Optional[list[str]]:
    m = re.match(rf"(?i)^{fname}\s*\((.*)\)\s*$", expr, re.DOTALL)
    if not m:
        return None
    return _split_top_level(m.group(1))


def _split_top_level(s: str) -> list[str]:
    parts, cur = [], []
    for ch, depth, opaque in _scan(s, "([{", ")]}"):
        if ch == "," and depth == 0 and not opaque:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur))
    return [p.strip() for p in parts]


# Aggregations Set Analysis translates, and the value rows OUTSIDE the set contribute:
# 0 is neutral only for a sum (a count or average over `else 0` counts / averages the
# zeros). Anything else (Only, Mode, Concat, FirstSortedValue, ...) is NEEDS_REVIEW --
# it was silently read as `sum` (#586 review).
_SET_AGGS: dict[str, tuple[str, str]] = {
    "sum": ("sum", "0"), "avg": ("average", "null"), "count": ("count", "null"),
    "min": ("min", "null"), "max": ("max", "null"),
}


def _set_agg(name: str, measure: str) -> tuple[Optional[tuple[str, str, str]], Optional[str]]:
    """(ThoughtSpot aggregation, measure, value outside the set) or a review reason.
    ``Count(DISTINCT x)`` becomes ``unique count``, whose ThoughtSpot name has a space
    (thoughtspot-formula-patterns.md)."""
    agg = _SET_AGGS.get(name.lower())
    if agg is None:
        return None, (f"the aggregation {name}() has no Set Analysis translation (only "
                      "Sum, Avg, Count, Min and Max)")
    distinct = re.match(r"(?i)^distinct\s+(.+)$", measure.strip())
    if distinct:
        if agg[0] != "count":
            return None, f"{name}(DISTINCT ...) is not translated"
        return ("unique count", distinct.group(1).strip(), "null"), None
    return (agg[0], measure.strip(), agg[1]), None


_SET_MODIFIER = re.compile(r"\{\s*\$?\s*<(.*?)>\s*\}", re.S)


def _set_analysis_shape_problem(expr: str) -> Optional[str]:
    """Why ``expr`` is outside the shapes ``_set_analysis`` translates exactly, or None.

    The patterns below read ONE aggregation over ONE field: a second aggregation was
    stitched into the first's measure, and a second field in the modifier was read as
    more values of the first (``{<Year={2023}, Region={"A"}>}`` became ``Year = '2023'
    or Year = 'A'``) — both silent wrong answers (#583 review)."""
    m = re.match(r"^\w+\s*\(", expr)
    if not m or _group_end(expr, m.end() - 1) != len(expr) - 1:
        return ("more than one aggregation (or text outside the Set Analysis call); "
                "translate each Set Analysis aggregation on its own")
    for mod in _SET_MODIFIER.finditer(expr):
        if len([f for f in _split_top_level(mod.group(1)) if f]) > 1:
            return ("the Set Analysis modifier restricts more than one field; each "
                    "field needs its own condition (AND), which is not translated")
    return None


def _set_field(raw: str) -> str:
    """The modifier's field as a reference: ``[Field Name]`` stays ONE bracketed field
    (BL-378 -- stripped to ``Field Name`` it was read as two bare names)."""
    name = raw.strip()
    if name.startswith("[") and name.endswith("]"):
        name = name[1:-1]
    return f"[{name}]" if not re.fullmatch(r"[A-Za-z_]\w*", name) else name


_SEARCH_CHARS = re.compile(r"[*?]|^\s*[<>=^~]")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
SELECTION_NOTE = ("Set Analysis: an = modifier REPLACES the user's selection on that field in "
                  "Qlik, while the ThoughtSpot if ( … ) intersects with a filter on it — the "
                  "two differ only when the user filters on that field.")
NUMBER_NOTE = ("Set Analysis: a bare value ({0}) is emitted as a number because the field's "
               "type is not known; if the field is text-coded (e.g. {{007}}), quote the value.")
_NUMERIC_TYPES = ("INT", "DOUBLE", "FLOAT", "DECIMAL", "NUMBER", "NUMERIC", "BIGINT")
CASE_NOTE = ("Set Analysis: a single-quoted element value is a case-SENSITIVE literal in "
             "Qlik, but ThoughtSpot's = is case-insensitive (BL-333), so a value differing "
             "only in case now matches too. Apps built before June 2017 read single quotes "
             "as a search instead.")


def _set_values(raw_vals: str, field_type: Optional[str] = None,
                notes: Optional[list] = None) -> tuple[list[str], Optional[str], bool]:
    """(ThoughtSpot literals, review reason, whether a single-quoted value was read).

    Values split on commas OUTSIDE quotes (BL-376: ``{'A, B'}`` is one value). A single-
    quoted value is a literal; a bare number stays a number (``{2023}`` -> ``2023``),
    another bare value is quoted. A double-quoted value is a Qlik SEARCH string --
    exact (case-insensitively, as ThoughtSpot's ``=`` is) only without wildcards
    (``*``, ``?``) or a leading ``<`` ``>`` ``=`` ``^`` ``~`` (range, expression or
    fuzzy search), which are flagged (BL-377). Loud, never guessed: a set operator
    other than ``+`` (union) between element sets, a function element set (``P()``,
    ``E()``), and an empty set."""
    groups = _brace_groups(raw_vals)
    problem = _element_set_problem(raw_vals, groups)
    if problem:
        return [], problem, False
    values: list[str] = []
    single = False
    for g in groups:
        for v in _split_top_level(g[1:-1]):
            if not v:
                continue
            lit, why = _element_literal(v, field_type, notes)
            if why:
                return [], why, False
            single = single or v[0] == "'"
            values.append(lit)
    if not values:
        return [], "an empty element set ({}) selects nothing; it is not translated", False
    return values, None, single


def _element_set_problem(raw_vals: str, groups: list[str]) -> Optional[str]:
    if re.match(r"(?i)^\s*[EP]\s*\(", raw_vals):
        return ("a function element set (P() / E(), the possible or excluded values) "
                "depends on selection state; it is not translated")
    if not groups:
        return f"the element set {raw_vals.strip()} is not a {{…}} list; it is not translated"
    rest = raw_vals
    for g in groups:
        rest = rest.replace(g, " ", 1)
    ops = set(rest.split())
    if ops - {"+"}:
        return ("a set operator between element sets ("
                + " ".join(sorted(ops - {"+"})) + ") — only + (union) is translated")
    return None


def _element_literal(v: str, field_type: Optional[str] = None,
                     notes: Optional[list] = None) -> tuple[str, Optional[str]]:
    if len(v) >= 2 and v[0] == v[-1] == '"':
        text = v[1:-1].replace('""', '"')
        if _SEARCH_CHARS.search(text):
            return "", (f"the element value {v} is a search (wildcard, range, expression or "
                        "fuzzy), not a single value; it is not translated")
    elif len(v) >= 2 and v[0] == v[-1] == "'":
        text = v[1:-1].replace("''", "'")
    elif _NUMBER.fullmatch(v):
        kind = (field_type or "").upper()
        if kind.startswith(_NUMERIC_TYPES):
            return v, None
        if kind:                      # a known non-numeric field: the value is text
            return "'" + v + "'", None
        if notes is not None:
            notes.append(NUMBER_NOTE.format(v))
        return v, None
    else:
        text = v
    return "'" + text.replace("'", "''") + "'", None


def _brace_groups(raw: str) -> list[str]:
    """Each top-level ``{…}`` in ``raw`` (quotes respected), braces included."""
    out, start = [], None
    for k, (ch, depth, opaque) in enumerate(_scan(raw, "{", "}")):
        if opaque:
            continue
        if ch == "{" and depth == 1:
            start = k
        elif ch == "}" and depth == 0 and start is not None:
            out.append(raw[start:k + 1])
            start = None
    return out


def _set_analysis(expr: str, first_week_day: Optional[int] = None,
                  ctx: Optional[dict] = None) -> tuple[str, bool, str]:
    ctx = ctx if ctx is not None else {"notes": [], "field_types": {}}
    problem = _set_analysis_shape_problem(expr)
    # Selection state ({$}, {$<…>}) and $(…) dollar expansion first: a value like
    # {$(vYear)} must never reach the literal patterns below (#586 review).
    if not problem and "$" in expr:
        problem = ("uses current-selection context ($) or $-expansion; approximate "
                   "manually — selection state is not preserved in ThoughtSpot")
    if not problem:
        out, problem = _set_analysis_patterns(expr, first_week_day, ctx)
        if out:
            return out, False, ""
    return (f"/* TODO review set analysis: {expr} */", True,
            f"Set Analysis: {problem or 'unrecognized pattern'}")


def _set_measure(measure: str, first_week_day: Optional[int], ctx: dict
                 ) -> tuple[Optional[str], Optional[str]]:
    """The aggregated expression, translated like any other (functions remapped, If()
    rewritten), or a review reason. TOTAL and Aggr() change the aggregation's grain and
    are not translated inside Set Analysis (#586 review)."""
    if re.search(r"(?i)\btotal\b", measure) or re.search(r"(?i)\baggr\s*\(", measure):
        return None, "TOTAL / Aggr() inside a Set Analysis aggregation is not translated"
    out, review, reason = _translate(measure, first_week_day, ctx)
    if review or not out:
        return None, f"the aggregated expression {measure!r}: {reason or 'needs review'}"
    return out, None


def _set_analysis_patterns(expr: str, first_week_day: Optional[int], ctx: dict
                           ) -> tuple[Optional[str], Optional[str]]:
    """(formula, None) for a shape translated exactly (notes go to ``ctx``), else
    (None, reason)."""
    # Pattern 1: {1} ignores the user's selections; the chart's dimensions still group
    # it (dropping them is TOTAL), so the grouping is query_groups ( ) and only the
    # filters are emptied (#586 review — it was a grand total).
    m = re.match(r"(?i)^(\w+)\(\s*\{1\}\s*(.+?)\)$", expr)
    if m:
        agg, why = _set_agg(m.group(1), m.group(2))
        measure, why = (None, why) if why else _set_measure(agg[1], first_week_day, ctx)
        if why:
            return None, why
        return f"group_aggregate ( {agg[0]} ( {measure} ) , query_groups ( ) , {{}} )", None

    # Pattern 2/3/4: {<Field={...}>} (equals / exclude / union).
    m = re.match(r"(?i)^(\w+)\(\s*\{<\s*([\w \[\]]+?)\s*(-?=)\s*(.+?)\s*>\}\s*(.+?)\)$", expr)
    if not m:
        return None, None
    return _modifier_formula(m, first_week_day, ctx)


def _modifier_formula(m: re.Match, first_week_day: Optional[int], ctx: dict
                      ) -> tuple[Optional[str], Optional[str]]:
    agg, why = _set_agg(m.group(1), m.group(5))
    if why:
        return None, why
    field = _set_field(m.group(2))
    notes: list[str] = []
    ftype = ctx["field_types"].get(field.strip("[]").lower())
    values, why, single = _set_values(m.group(4), ftype, notes)
    measure, why = (None, why) if why else _set_measure(agg[1], first_week_day, ctx)
    if why:
        return None, why
    fn, _m, other = agg
    if m.group(3) == "-=":
        cond = " and ".join(f"{field} != {v}" for v in values)
    else:
        cond = " or ".join(f"{field} = {v}" for v in values)
        notes.append(SELECTION_NOTE)
    if len(values) > 1:
        cond = f"({cond})"
    ctx["notes"].extend(notes + ([CASE_NOTE] if single else []))
    return f"{fn}(if ({cond}) then {measure} else {other})", None


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
