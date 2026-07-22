"""Sisense JAQL -> ThoughtSpot formula translation (deterministic safe subset).

Ported from the standalone converter (map/formula.py). Pure functions, no I/O.
translate_jaql(expr, context=None) -> (expr_out, status, note); expr_out is None for
NEEDS REVIEW (the caller preserves the original Sisense formula). translate_agg(agg)
translates a plain JAQL aggregation (no formula) to a TML aggregation keyword.

STRATEGY (unchanged from the standalone converter): deterministically translate the
common subset; emit everything else as NEEDS REVIEW with the original formula preserved.
The long tail (time-intelligence, RANK/ORDERING, measured-value scoping, R) is out of
scope by design.

Coverage -> status mapping (mirrors the Power BI converter's three statuses):
  AUTO -> "Migrated"; PARTIAL -> "Approximated"; MANUAL -> "NEEDS REVIEW".
"""
from __future__ import annotations

import re

# Sisense JAQL `agg` -> TML aggregation property (for SIMPLE measures, no formula).
# NOTE on count semantics (verified against Sisense docs): Sisense `count` returns the
# number of *unique* values (distinct), while `dupCount`/`countduplicates` returns the
# *total* item count including duplicates. So they map OPPOSITE to the intuitive reading:
#   count           -> COUNT_DISTINCT  (unique)
#   countduplicates -> COUNT           (exact total; NOT approximate)
AGG_MAP: dict[str, str] = {
    "sum": "SUM",
    "avg": "AVERAGE",
    "count": "COUNT_DISTINCT",    # Sisense count == distinct/unique count
    "countduplicates": "COUNT",   # Sisense dupCount == exact total count (incl. duplicates)
    "dupcount": "COUNT",          # JAQL sometimes spells it `dupCount`
    "min": "MIN",
    "max": "MAX",
    "stdev": "STD_DEVIATION",
    "var": "VARIANCE",
    # median / stdevp / varp / mode have no clean TML aggregation -> MANUAL
}

# Sisense formula function -> TML formula function (deterministic 1:1 subset only).
FUNCTION_MAP: dict[str, str] = {
    # aggregation (see AGG_MAP note: Sisense count == distinct; dupCount == total)
    "sum": "sum",
    "avg": "average",
    "average": "average",
    "count": "unique count",    # Sisense count is distinct -> TS `unique count`
    "dupcount": "count",         # Sisense dupCount is total -> TS `count`
    "countduplicates": "count",
    "min": "min",
    "max": "max",
    # mathematical
    "abs": "abs",
    "round": "round",
    "ceiling": "ceil",
    "floor": "floor",
    "power": "pow",
    "sqrt": "sqrt",
    "exp": "exp",
    "mod": "mod",
    "log": "ln",       # Sisense `Log` is the NATURAL log (Sisense has no separate `Ln`)
    "ln": "ln",        # defensive alias if a JAQL variant uses `ln`
    "log10": "log10",
    "sign": "sign",
    # date difference -- Sisense DDiff(d1, d2) -> ThoughtSpot diff_days(d1, d2)
    "ddiff": "diff_days",
    # statistical (sample variants)
    "stdev": "stddev",
    "var": "variance",
    "median": "median",
    # logical / conditional
    # `if` is handled structurally (functional if(c,a,b) -> `if (c) then a else b`),
    # NOT via a name rename — see _rewrite_conditionals. `case` is NEEDS REVIEW (its
    # multi-branch shape has no safe deterministic 1:1 — rebuild as nested if manually).
    "isnull": "isnull",    # TS spells it `isnull` (NOT `is_null`)
    "ifnull": "ifnull",
}

# Functions we will NOT auto-translate. Presence => NEEDS REVIEW. Unknown functions are
# NEEDS REVIEW anyway; this set exists for clearer notes and to guard names that look
# translatable but are not (population stats, R, window, time-intelligence).
UNSUPPORTED: frozenset = frozenset({
    # window / ranking
    "rank", "ordering", "rsum", "rpsum", "rpavg", "prev", "next", "all", "now",
    # time intelligence: period-to-date
    "ytdsum", "ytdavg", "mtdsum", "mtdavg", "qtdsum", "qtdavg", "wtdsum",
    # time intelligence: prior period
    "pastday", "pastweek", "pastmonth", "pastquarter", "pastyear",
    # time intelligence: growth / diff (ddiff is supported -> diff_days, see FUNCTION_MAP)
    "growth", "growthrate", "diffpastyear", "diffpastmonth", "growthpastyear",
    "ydiff", "qdiff", "mdiff", "hdiff", "mndiff", "sdiff",
    # population / advanced statistics (no confident TML 1:1)
    "stdevp", "varp", "mode", "largest", "smallest",
    "percentile", "quartile", "correl", "covar", "slope",
    # R integration
    "rdouble", "rint",
})

# `if` is a supported conditional but is rewritten structurally, not renamed.
_CONDITIONAL: frozenset = frozenset({"if"})

# identifier immediately followed by "(" -> a function call in the expression.
_FUNC_CALL = re.compile(r"([A-Za-z_]\w*)\s*\(")

# Trailing date-hierarchy tag on a Sisense dim (e.g. "Date (Calendar)", "Order Date (Months)").
# Only these known level/hierarchy labels are stripped — a legitimate name like
# "Profit (Adjusted)" must be preserved (finding: over-eager paren strip corrupts names).
_DATE_LEVEL_WORDS = frozenset({
    "calendar", "fiscal",
    "year", "years", "quarter", "quarters", "month", "months",
    "week", "weeks", "day", "days", "date", "hour", "hours",
    "minute", "minutes", "second", "seconds",
    "day of week", "week of year", "day of month", "day of year",
    "quarter of year", "month of year",
})

# Coverage levels used internally; mapped to status strings on the way out.
_AUTO, _PARTIAL, _MANUAL = "AUTO", "PARTIAL", "MANUAL"
_STATUS = {_AUTO: "Migrated", _PARTIAL: "Approximated", _MANUAL: "NEEDS REVIEW"}


def _column_from_dim(dim: str | None) -> str | None:
    """Sisense dim '[Orders.Revenue]' -> TML column ref '[Revenue]'.

    Strips the surrounding brackets and the 'Table.' qualifier, keeping the display
    name (spaces and all), and drops a trailing date-hierarchy tag so the ref matches
    the base model column (e.g. "Date(Calendar)" -> "Date").
    """
    if not dim:
        return None
    s = dim.strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    s = s.split(".")[-1].strip()
    # Drop a trailing parenthesized tag ONLY when it is a known date-hierarchy level, so
    # "Date (Calendar)" -> "Date" but a real name like "Profit (Adjusted)" is left intact.
    m = re.search(r"^(.*?)\s*\(([^)]*)\)\s*$", s)
    if m and m.group(2).strip().lower() in _DATE_LEVEL_WORDS:
        s = m.group(1).strip()
    return "[" + s + "]"


def _agg_to_func(agg: str) -> tuple:
    """A JAQL agg used as a formula wrapper -> (tml_func|None, coverage, note).

    count -> `unique count` (distinct) and dupCount/countduplicates -> `count` (exact total)
    both come straight from FUNCTION_MAP; neither is approximate (see AGG_MAP note).
    """
    key = (agg or "").lower()
    if key in FUNCTION_MAP:           # sum, avg->average, count->unique count, dupCount->count, min, max
        return FUNCTION_MAP[key], _AUTO, ""
    return None, _MANUAL, f"no TML function for agg '{agg}'"


def _normalize_key(raw_key: str) -> str:
    """Context keys may be bracketed ('[rev]') or bare ('rev'); normalize to bare."""
    k = raw_key.strip()
    if k.startswith("[") and k.endswith("]"):
        k = k[1:-1]
    return k


def _apply_downgrade(coverage: str, notes: list, level: str, note: str = "") -> str:
    """Fold a coverage downgrade into ``coverage`` (returning the new level) and record ``note``.

    MANUAL is the floor; PARTIAL only downgrades from AUTO. Pure: mutates ``notes`` in place,
    returns the (possibly changed) coverage level.
    """
    if note:
        notes.append(note)
    if level == _MANUAL or coverage == _AUTO:
        return level
    return coverage


def _resolve_placeholder(raw_key: str, frag, source: str, out: str,
                         coverage: str, notes: list) -> tuple:
    """Resolve one `[key]` context placeholder within ``out``.

    Returns (out, coverage, terminal) where ``terminal`` is either None (continue) or a
    finished ``(None, status, note)`` result that aborts the whole translation. A `{dim, agg}`
    fragment becomes a bare column ref when the expression already wraps it in an aggregation,
    or ``agg([Column])`` when it appears bare; a nested ``formula`` fragment recurses.
    """
    key = _normalize_key(raw_key)
    token = "[" + key + "]"
    frag = frag if isinstance(frag, dict) else {}

    if frag.get("formula"):  # nested calc -> recurse
        sub_expr, sub_status, sub_note = translate_jaql(str(frag["formula"]),
                                                        frag.get("context") or {})
        if sub_status == "NEEDS REVIEW" or sub_expr is None:
            return out, coverage, (None, "NEEDS REVIEW",
                                   sub_note or f"unsupported nested formula for '{key}'")
        if sub_status == "Approximated":
            coverage = _apply_downgrade(coverage, notes, _PARTIAL, sub_note)
        return out.replace(token, "(" + sub_expr + ")"), coverage, None

    col = _column_from_dim(frag.get("dim"))
    if col is None:
        return out, coverage, (None, "NEEDS REVIEW",
                               f"cannot resolve placeholder '{key}' (no dim/formula)")

    # If the expression already aggregates the placeholder (e.g. "sum([rev])"),
    # substitute the bare column and let the function-map pass handle the wrapper. If it
    # appears bare, apply the context agg here.
    wrapped = re.search(r"[A-Za-z_]\w*\s*\(\s*" + re.escape(token) + r"\s*\)", source)
    agg = frag.get("agg")
    if wrapped or not agg:
        replacement = col
    else:
        fn, cov, note = _agg_to_func(agg)
        if fn is None:
            return out, coverage, (None, "NEEDS REVIEW", note)
        coverage = _apply_downgrade(coverage, notes, cov, note)
        replacement = f"{fn}({col})"
    return out.replace(token, replacement), coverage, None


def _inspect_functions(source: str, coverage: str, notes: list) -> tuple:
    """Inspect every function call in ``source`` for support.

    Returns (coverage, terminal): ``terminal`` is None when all calls are AUTO/PARTIAL, or a
    finished ``(None, "NEEDS REVIEW", note)`` result for the first unsupported/unknown call.
    """
    for name in _FUNC_CALL.findall(source):
        low = name.lower()
        if low == "case":
            return coverage, (None, "NEEDS REVIEW",
                              "Sisense case(): multi-branch conditional has no safe 1:1 "
                              "translation — rebuild as nested if() manually")
        if low in UNSUPPORTED:
            return coverage, (None, "NEEDS REVIEW", f"unsupported function '{name}'")
        if low in FUNCTION_MAP or low in _CONDITIONAL:
            continue
        return coverage, (None, "NEEDS REVIEW", f"unknown function '{name}'")
    return coverage, None


def _rename_func(m: "re.Match") -> str:
    """Rename a mapped function call in the resolved expression (ceiling->ceil, count->unique count).

    `if` is intentionally NOT renamed here — it is rewritten structurally afterwards by
    _rewrite_conditionals into ThoughtSpot's `if (cond) then a else b` form.
    """
    low = m.group(1).lower()
    return FUNCTION_MAP.get(low, m.group(1)) + "("


_IF_CALL = re.compile(r"(?<![A-Za-z0-9_])if\s*\(", re.IGNORECASE)


def _split_top_level_args(s: str) -> list:
    """Split ``s`` on top-level commas, respecting (), [] nesting and quoted strings."""
    args, depth, buf, quote = [], 0, [], None
    for ch in s:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
            buf.append(ch)
        elif ch in "([":
            depth += 1
            buf.append(ch)
        elif ch in ")]":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    args.append("".join(buf))
    return [a.strip() for a in args]


def _match_paren(s: str, open_idx: int) -> int:
    """Index of the ')' matching the '(' at ``open_idx`` (respecting [] and ()), or -1."""
    depth = 0
    for i in range(open_idx, len(s)):
        if s[i] in "([":
            depth += 1
        elif s[i] in ")]":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _rewrite_conditionals(expr: str) -> tuple:
    """Rewrite functional ``if(cond, then, else)`` -> ThoughtSpot ``if (cond) then <> else <>``.

    Recurses into each argument (nested if) and into the tail (sibling if). Returns
    ``(new_expr, error_note|None)``; a non-3-arg ``if()`` cannot be expressed in
    ThoughtSpot's if/then/else and yields an error note (the caller flags NEEDS REVIEW).
    """
    m = _IF_CALL.search(expr)
    if not m:
        return expr, None
    open_idx = expr.index("(", m.start())
    close_idx = _match_paren(expr, open_idx)
    if close_idx == -1:
        return expr, "malformed if(): unbalanced parentheses"
    args = _split_top_level_args(expr[open_idx + 1:close_idx])
    if len(args) != 3:
        # An already-rewritten `if (cond) then ... else ...` (from a nested formula) has a
        # single-arg paren followed by ` then ` — leave it intact and rewrite only the tail.
        if len(args) == 1 and expr[close_idx + 1:].lstrip().startswith("then "):
            tail_rw, err = _rewrite_conditionals(expr[close_idx + 1:])
            return (expr[:close_idx + 1] + tail_rw, None) if not err else (expr, err)
        return expr, (f"if() has {len(args)} argument(s); ThoughtSpot if/then/else needs "
                      "exactly 3 (condition, then, else)")
    rewritten = []
    for a in args:
        ra, err = _rewrite_conditionals(a)
        if err:
            return expr, err
        rewritten.append(ra)
    cond, then_v, else_v = rewritten
    tail_rw, err = _rewrite_conditionals(expr[close_idx + 1:])
    if err:
        return expr, err
    return f"{expr[:m.start()]}if ({cond}) then {then_v} else {else_v}{tail_rw}", None


def translate_jaql(expr, context: dict | None = None) -> tuple:
    """Translate a Sisense JAQL formula + context into a TML formula expression.

    Steps (per the standalone converter):
      1. Resolve each `[key]` placeholder against the context. A `{dim, agg}` fragment
         becomes a column ref `[Column]` when the expression already wraps it in an
         aggregation, or `agg([Column])` when it appears bare. Nested `formula`
         fragments recurse.
      2. Map function names via FUNCTION_MAP.
      3. Any function in UNSUPPORTED (or unknown), `case`, a non-3-arg `if`, or an
         unresolvable placeholder makes the whole formula NEEDS REVIEW (expr None).
      4. Functional `if(c,a,b)` -> `if (c) then a else b`; 2-arg `round` -> Approximated.

    Returns (expr_out, status, note); expr_out is None when status == "NEEDS REVIEW".
    """
    source = expr or ""
    context = context or {}
    coverage = _AUTO
    notes: list = []

    # 1. Validate every function call in the ORIGINAL source (unsupported/unknown/case -> abort).
    coverage, terminal = _inspect_functions(source, coverage, notes)
    if terminal is not None:
        return terminal

    # 2. round() arg semantics diverge: TS's 2nd arg is a rounding INCREMENT
    # (round(x, .01) for 2 decimals), not Sisense's decimal-place COUNT (Round(x, 2)).
    if re.search(r"\bround\s*\([^()]*,", source, re.IGNORECASE):
        coverage = _apply_downgrade(coverage, notes, _PARTIAL,
                                    "TS round() 2nd arg is a rounding increment, "
                                    "not a decimal-place count")

    # 3. Rename source function names to TS (ceiling->ceil, count->unique count) BEFORE
    #    interpolating resolved content — so TS aggregation names and real column display
    #    names (e.g. "[Profit (Adjusted)]") introduced in step 4 are never re-scanned/mangled.
    out = _FUNC_CALL.sub(_rename_func, source)

    # 4. Resolve context placeholders into the renamed skeleton. A `{dim, agg}` fragment
    #    becomes a bare column ref when already wrapped, or `agg([Column])` (agg already TS)
    #    when bare; a nested `formula` fragment recurses (returns fully-translated text).
    for raw_key, frag in context.items():
        out, coverage, terminal = _resolve_placeholder(raw_key, frag, source, out,
                                                        coverage, notes)
        if terminal is not None:
            return terminal

    # 5. Rewrite the functional if(c,a,b) into ThoughtSpot's `if (c) then a else b`.
    out, cond_err = _rewrite_conditionals(out)
    if cond_err:
        return None, "NEEDS REVIEW", cond_err
    out = re.sub(r"\s+", " ", out).strip()

    return out, _STATUS[coverage], "; ".join(notes)


def translate_agg(agg) -> tuple:
    """Translate a plain JAQL `agg` (no formula) to a TML aggregation keyword.

    Returns (agg_keyword|None, status, note); agg_keyword is None for NEEDS REVIEW.
    """
    key = (agg or "").lower()
    if key in AGG_MAP:
        # count->COUNT_DISTINCT and dupCount->COUNT are both exact (see AGG_MAP note) — no caveat.
        return AGG_MAP[key], "Migrated", ""
    return None, "NEEDS REVIEW", f"no TML aggregation for Sisense agg '{agg}'"
