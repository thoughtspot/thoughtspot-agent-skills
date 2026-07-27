"""DAX -> ThoughtSpot formula translation (safe subset + cluster-verified extensions).

Ported from the standalone Power BI converter (generate_tml.py). Pure functions, no I/O.
translate_dax(dax, home_table, home_cols, date_cols, measure_dax) -> (expr|None, status, note);
expr is None for NEEDS REVIEW (caller preserves the original DAX). Verified on-cluster:
CALCULATE(<agg>, FILTER) -> sum_if; CALCULATE(m, ALL(col)) -> group_aggregate; measure/
calc-column refs -> [formula_<name>] id-refs (name-refs do not resolve on import);
ROUND-increment semantics; 2-arg CEILING/FLOOR; DATE subtraction -> diff_days.
"""
from __future__ import annotations

import re

# Presence of any of these makes the whole measure NEEDS REVIEW: they manipulate
# filter context / iterate / do time intelligence and have no 1:1 TS formula.
_DAX_REVIEW = {
    "calculate", "calculatetable", "filter", "all", "allexcept", "allselected",
    "removefilters", "keepfilters", "earlier", "earliest", "sumx", "averagex",
    "minx", "maxx", "countx", "rankx", "addcolumns", "summarize", "summarizecolumns",
    "topn", "values", "distinct", "related", "relatedtable", "userelationship",
    "totalytd", "totalqtd", "totalmtd", "datesytd", "datesqtd", "datesmtd",
    "sameperiodlastyear", "dateadd", "datediff", "parallelperiod", "previousmonth",
    "previousyear", "previousquarter", "previousday", "nextmonth", "nextyear",
    "lastdate", "firstdate", "startofyear", "endofyear", "startofmonth",
    "endofmonth", "var", "return", "switch",
}

# DAX function -> ThoughtSpot function (1:1, deterministic).
_DAX_FUNC = {
    "sum": "sum", "average": "average", "min": "min", "max": "max",
    "count": "count", "counta": "count", "distinctcount": "unique_count",
    "abs": "abs", "round": "round", "int": "floor",  # DAX INT rounds toward -inf = floor.
    # NB: DAX TRUNC truncates toward zero (TRUNC(-2.5) = -2), which floor gets wrong for
    # negatives; there is no 1:1 ThoughtSpot equivalent, so TRUNC is left unmapped and flagged.
    "ceiling": "ceil", "floor": "floor",
    "sqrt": "sqrt", "exp": "exp", "power": "pow", "mod": "mod", "sign": "sign",
    "year": "year", "month": "month", "day": "day", "hour": "hour",
    "minute": "minute", "second": "second", "quarter": "quarter_number",
    "upper": "upper", "lower": "lower", "len": "strlen", "trim": "trim",
    "isblank": "isnull",
}

_FUNC_CALL = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*)\s*\(")  # incl. dotted names (PERCENTILE.INC)
# Table[Column] or 'Table Name'[Column] -> capture (table, column). Unquoted
# DAX table names have no spaces (only the quoted form may), so the bare branch
# is \w-only: this stops it from swallowing a preceding keyword (e.g. "then x[c]").
_COL_REF = re.compile(r"(?:'([^']+)'|([A-Za-z_]\w*))\s*\[([^\]]+)\]")
# A bare measure reference: [Measure Name] not preceded by a table token.
_MEASURE_REF = re.compile(r"(?<![\w'\]])\[([^\]]+)\]")


def _split_args(s):
    """Split a function-call argument string on top-level commas (respecting
    nested parens and brackets). Returns the list of trimmed arg strings."""
    args, depth, cur = [], 0, []
    for ch in s:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            args.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur or args:
        args.append("".join(cur).strip())
    return args


def _match_paren(s, open_idx):
    """Given index of a '(', return index of its matching ')' (or -1)."""
    depth = 0
    for i in range(open_idx, len(s)):
        if s[i] == "(":
            depth += 1
        elif s[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _calc_approx(args):
    """Approximate a 2-arg CALCULATE(<agg>, <filter>) as a conditional aggregation.
    Returns a DAX-ish `sum_if(cond, expr)` string (re-processed downstream) or None
    when the pattern isn't a simple agg+filter (e.g. wraps another measure)."""
    if len(args) != 2:
        return None                       # multiple filters / context transition: defer
    inner, filt = args[0].strip(), args[1].strip()
    if inner.startswith("(") and _match_paren(inner, 0) == len(inner) - 1:
        inner = inner[1:-1].strip()       # unwrap a paren added by reference inlining
    fm = re.match(r"(?i)FILTER\s*\(", filt)         # CALCULATE(agg, FILTER(table, cond))
    if fm:
        fc = _match_paren(filt, fm.end() - 1)
        fa = _split_args(filt[fm.end():fc]) if fc > 0 else []
        if len(fa) != 2:
            return None
        cond = fa[1]
    else:
        cond = filt                                  # CALCULATE(agg, <boolean>)
    sm = re.match(r"(?i)SUM\s*\(", inner)
    if sm:
        return f"sum_if({cond}, {inner[sm.end():_match_paren(inner, sm.end() - 1)]})"
    if re.match(r"(?i)COUNTROWS\s*\(", inner) or re.match(r"(?i)COUNTA?\s*\(", inner):
        return f"sum_if({cond}, 1)"                    # COUNT/COUNTA/COUNTROWS -> count rows meeting cond
    return None      # AVERAGE/MIN/MAX/measure-ref: not a safe 1-line approximation


def _refs_to_ids(dax, names, physical_cols=None):
    """Rewrite a DAX reference to another measure/calc-column as a ThoughtSpot
    formula-ID reference: [formula_<name>].

    ThoughtSpot resolves a sibling formula by its column id (formula_<name>), NOT by
    its display name -- a bare [Display Name] in a formula expression does not resolve
    (and a leading reserved word like 'Sum' is even mis-parsed as the agg keyword).
    Using the id keeps the measure dependency graph intact instead of inlining every
    definition: DIVIDE([Seps],[Actives]) -> [formula_Seps] / [formula_Actives], and
    SUM(Employee[isNewHire]) -> sum([formula_isNewHire]). Physical column refs
    ('Table'[Col] / Table[Col]) are NOT in `names`, so they fall through to _COL_REF
    which qualifies them to [Table::Col]. Verified on-cluster 2026-06-29.

    A reference to a measure that itself fails to translate would dangle; build_model_tml
    cascades a NEEDS-REVIEW to dependents (see _cascade_flag) so the report stays honest."""
    physical_cols = physical_cols or set()
    out = dax
    for name in sorted((n for n in names if n), key=len, reverse=True):
        if name in physical_cols:
            # `name` collides with a physical column: only an UNqualified `[name]` is the
            # formula (a measure ref). A qualified `Table[name]` is the physical column and
            # is left for the _COL_REF pass to qualify to [Table::name] -- so a physical
            # `Fact[Sales]` is not hijacked into `[formula_Sales]` when a measure `Sales` exists.
            pat = re.compile(r"(?<![\w'])\[" + re.escape(name) + r"\]")
        else:
            # optional table qualifier ('T'[name] / T[name]) or a bare [name]
            pat = re.compile(r"(?:'[^']*'|[A-Za-z_]\w*)?\s*\[" + re.escape(name) + r"\]")
        out = pat.sub("[formula_" + name + "]", out)
    return out


def _calc_all_to_group_agg(s):
    """Rewrite CALCULATE(m, ALL(col), ALL(col), ...) -> group_aggregate(m,
    query_groups() - {cols}, query_filters() - {cols}) -- ThoughtSpot's equivalent of
    DAX removing specific dimensions from filter context (verified on-cluster; it's how
    a "normalized" measure like TO % Norm = CALCULATE([TO %], ALL(Gender), ALL(Ethnicity))
    ports). Only fires when EVERY filter arg is ALL/REMOVEFILTERS/ALLSELECTED of a single
    column; otherwise returns s unchanged so other CALCULATE shapes are handled/flagged.
    The raw column refs (Table[Col]) are left for the later _COL_REF pass to qualify."""
    out, guard = s, 0
    while guard < 50:
        guard += 1
        m = re.search(r"\bCALCULATE\s*\(", out, re.I)
        if not m:
            return out
        close = _match_paren(out, m.end() - 1)
        if close < 0:
            return out
        args = _split_args(out[m.end():close])
        if len(args) < 2:
            return out
        cols, ok = [], True
        for a in args[1:]:
            am = re.match(r"(?i)\s*(ALL|REMOVEFILTERS|ALLSELECTED)\s*\(", a)
            fc = _match_paren(a, am.end() - 1) if am else -1
            inner = a[am.end():fc].strip() if fc > 0 else ""
            # only a single COLUMN ref (Table[Col]); ALL(<whole table>) has no "[" and is
            # a different semantic (remove all that table's cols) -> defer/flag, don't rewrite
            if not am or not inner or "," in inner or "[" not in inner:
                ok = False
                break
            cols.append(inner)
        if not ok:
            return out
        cset = ", ".join(cols)
        repl = ("group_aggregate(%s, query_groups() - {%s}, query_filters() - {%s})"
                % (args[0].strip(), cset, cset))
        out = out[:m.start()] + repl + out[close + 1:]
    return out


def _approx_calculate(s):
    """Rewrite every approximable CALCULATE in `s` to a conditional sum_if. Returns
    the rewritten string, or None if any CALCULATE is present but not approximable
    (so the caller leaves it to be flagged NEEDS REVIEW)."""
    out, guard = s, 0
    while guard < 50:
        guard += 1
        m = re.search(r"\bCALCULATE\s*\(", out, re.I)
        if not m:
            return out
        close = _match_paren(out, m.end() - 1)
        if close < 0:
            return None
        repl = _calc_approx(_split_args(out[m.end():close]))
        if repl is None:
            return None
        out = out[:m.start()] + repl + out[close + 1:]
    return None


def _apply_calculate_rewrites(src, measure_dax, physical_cols=None):
    """id-refs + group_aggregate + sum_if rewrites, run before the review check.
    Returns (src, note_bits). See _refs_to_ids / _calc_all_to_group_agg / _approx_calculate."""
    note_bits = []
    # Sibling measure/calc-column refs -> [formula_<name>] id-refs (keeps the dependency
    # graph; TS resolves siblings by id, not display name).
    if measure_dax:
        src = _refs_to_ids(src, set(measure_dax), physical_cols)
    # CALCULATE(m, ALL(col), ...) -> group_aggregate removing those dims (cluster-verified).
    ga = _calc_all_to_group_agg(src)
    if ga != src:
        src = ga
        note_bits.append("CALCULATE(ALL(dims)) -> group_aggregate removing those dims; verify vs Power BI")
    # CALCULATE(<agg>, FILTER(table, cond)) -> conditional sum_if.
    approx = _approx_calculate(src)
    if approx is not None and approx != src:
        src = approx
        note_bits.append("CALCULATE+FILTER approximated as a conditional sum_if; verify vs Power BI")
    return src, note_bits


def _review_reason(src):
    """A NEEDS-REVIEW reason if src still holds a filter-context / time-intelligence /
    iterator construct (no 1:1 ThoughtSpot formula), else None."""
    funcs = [m.group(1).lower() for m in _FUNC_CALL.finditer(src)]
    bad = sorted({f for f in funcs if f in _DAX_REVIEW})
    if re.search(r"\bvar\b", src, re.I) and re.search(r"\breturn\b", src, re.I):
        bad.append("VAR/RETURN")
    if bad:
        return ("contains " + ", ".join(sorted(set(bad))) +
                " (filter-context / time-intelligence / iterator) - rebuild by hand")
    return None


def _expand_functions(expr):
    """Expand argument-aware calls (OR/AND before IF; DIVIDE/ROUND/CEILING/FLOOR anywhere).
    Returns expr, or None if any call is unbalanced/unconvertible."""
    for fname, repl in (("DIVIDE", _divide_repl), ("OR", _or_repl),
                        ("AND", _and_repl), ("IF", _if_repl), ("ROUND", _round_repl),
                        ("CEILING", _ceiling_repl), ("FLOOR", _floor_repl)):
        expr = _expand_calls(expr, fname, repl)
        if expr is None:
            return None
    return expr


def _normalize_operators(expr):
    """DAX string literals + operators -> ThoughtSpot. Returns (expr, concat_note|None)."""
    # DAX "double" string quotes -> ThoughtSpot 'single'.
    expr = re.sub(r'"([^"]*)"', lambda m: "'" + m.group(1).replace("'", "''") + "'", expr)
    expr = expr.replace("<>", "!=")
    expr = expr.replace("&&", " and ").replace("||", " or ")
    expr = re.sub(r"\bNOT\b", "not", expr)
    # a & b string concat is non-trivial; flag if a lone & remains.
    concat_note = ("string '&' concatenation left as-is; verify (use concat())"
                   if re.search(r"(?<![&])&(?![&])", expr) else None)
    expr = re.sub(r"\bCONCATENATE\s*\(", "concat(", expr, flags=re.I)
    return expr, concat_note


def _map_known_functions(expr):
    """Rename known DAX functions to TS names, keep logical keywords / passthroughs, and
    flag any unknown function. Restores synthesized sentinels. Returns (expr|None, reason|None)."""
    # Logical keywords sit before '(' but are operators -> keep a space ("else (x)").
    _LOGICAL_KW = {"if", "then", "else", "and", "or", "not", "in"}
    # Synthesized fns (sum_if, diff_days, ...) + TS targets of _DAX_FUNC -> never flag.
    _PASS_FUNCS = ({"concat", "safe_divide", "sum_if", "count_if", "diff_days",
                    "group_aggregate", "query_groups", "query_filters"}
                   | set(_DAX_FUNC.values()))
    unknown = []

    def _rename(m):
        low = m.group(1).lower()
        if low in _DAX_FUNC:
            return _DAX_FUNC[low] + "("
        if low in _LOGICAL_KW:
            return m.group(1) + " ("
        if low in _PASS_FUNCS:
            return m.group(1) + "("
        unknown.append(m.group(1))
        return m.group(1) + "("

    expr = _FUNC_CALL.sub(_rename, expr)
    if unknown:
        return None, "unmapped function(s): " + ", ".join(sorted(set(unknown)))
    for sent, kw in _SENTINELS:              # restore synthesized keywords/functions
        expr = expr.replace(sent, kw)
    return expr, None


def _qualify_home_and_dates(expr, home_table, home_cols, date_cols):
    """Qualify bare home-table column refs ([HireDate] -> [Employee::HireDate]) and rewrite
    DATE subtraction ([a]-[b]) to diff_days([a],[b]) (TS has no date '-' operator)."""
    if home_table and home_cols:
        def _qual(m):
            inner = m.group(1)
            if "::" in inner or inner not in home_cols:
                return m.group(0)
            return f"[{home_table}::{inner}]"
        expr = re.sub(r"\[([^\]]+)\]", _qual, expr)
    if date_cols:
        dpat = re.compile(r"\[([^\]]+)\]\s*-\s*\[([^\]]+)\]")
        def _diff(m):
            a, b = m.group(1), m.group(2)
            return f"diff_days([{a}], [{b}])" if a in date_cols and b in date_cols else m.group(0)
        for _ in range(6):
            new = dpat.sub(_diff, expr)
            if new == expr:
                break
            expr = new
    return expr


def translate_dax(dax, home_table=None, home_cols=None, date_cols=None, measure_dax=None, physical_cols=None):
    """Translate a DAX measure/calc-column expression to a ThoughtSpot formula.

    home_table / home_cols qualify bare refs like [HireDate] to [Employee::HireDate];
    date_cols turns DATE subtraction into diff_days(); measure_dax lets sibling measure
    refs become [formula_<name>] id-references. Returns (expr, status, note); expr is
    None for NEEDS REVIEW (the caller preserves the original DAX). The pipeline runs as
    phase helpers so each stays simple: calculate-rewrites -> review gate -> qualify ->
    expand -> normalize -> map -> home/date qualify."""
    src = (dax or "").strip()
    if not src:
        return None, "NEEDS REVIEW", "empty measure expression"

    src, note_bits = _apply_calculate_rewrites(src, measure_dax, physical_cols)

    reason = _review_reason(src)
    if reason:
        return None, "NEEDS REVIEW", reason

    # Qualify Table[Col] -> [Table::Col] BEFORE expanding IF/DIVIDE/... so the "then"/
    # "else" keywords those introduce are never mistaken for a table name.
    expr = _COL_REF.sub(
        lambda m: f"[{(m.group(1) or m.group(2)).strip()}::{m.group(3).strip()}]", src)

    expr = _expand_functions(expr)
    if expr is None:
        return None, "NEEDS REVIEW", "could not expand a DIVIDE/IF/OR/AND/ROUND/CEILING/FLOOR call"

    expr, concat_note = _normalize_operators(expr)
    if concat_note:
        note_bits.append(concat_note)
        status_floor = "Approximated"
    else:
        status_floor = "Migrated"

    expr, reason = _map_known_functions(expr)
    if reason:
        return None, "NEEDS REVIEW", reason

    expr = _qualify_home_and_dates(expr, home_table, home_cols, date_cols)
    expr = re.sub(r"\s+", " ", expr).strip()
    status = "Approximated" if note_bits else status_floor
    return expr, status, "; ".join(note_bits)


def _expand_calls(expr, fname, repl_fn):
    """Replace every FNAME(...) call (case-insensitive) using repl_fn(args)->str.
    Works inside-out so nested calls of the same function expand correctly.
    Returns None on an unbalanced/invalid call."""
    pat = re.compile(r"\b" + fname + r"\s*\(", re.I)
    guard = 0
    while True:
        guard += 1
        if guard > 1000:
            return None
        # find the LAST occurrence so inner calls (later in string for same-name
        # nesting) resolve first when we go right-to-left.
        matches = list(pat.finditer(expr))
        if not matches:
            return expr
        m = matches[-1]
        close = _match_paren(expr, m.end() - 1)
        if close < 0:
            return None
        args = _split_args(expr[m.end():close])
        repl = repl_fn(args)
        if repl is None:
            return None
        expr = expr[:m.start()] + repl + expr[close + 1:]


# Synthesized keywords/functions are emitted as sentinels so the case-insensitive
# expanders don't re-match (and choke on) the `if`/`or`/`and`/`round` they just
# produced. translate_dax swaps the sentinels back once all expansion is done.
_IF = "\x00IF\x00"
_OR = "\x00OR\x00"
_AND = "\x00AND\x00"
_RND = "\x00ROUND\x00"
_FLR = "\x00FLOOR\x00"   # FLOOR->floor collides with the case-insensitive expander re-match
_SENTINELS = ((_IF, "if"), (_OR, "or"), (_AND, "and"), (_RND, "round"), (_FLR, "floor"))


def _divide_repl(args):
    if len(args) == 2:
        return f"safe_divide({args[0]}, {args[1]})"
    if len(args) == 3:
        return f"({_IF} ({args[1]} = 0) then {args[2]} else ({args[0]}) / ({args[1]}))"
    return None


def _if_repl(args):
    if len(args) == 2:
        return f"({_IF} ({args[0]}) then {args[1]} else 0)"
    if len(args) == 3:
        return f"({_IF} ({args[0]}) then {args[1]} else {args[2]})"
    return None


def _or_repl(args):    # DAX OR(a, b ...) -> (a) or (b) ...
    return "(" + f" {_OR} ".join(f"({a})" for a in args) + ")" if len(args) >= 2 else None


def _and_repl(args):   # DAX AND(a, b ...) -> (a) and (b) ...
    return "(" + f" {_AND} ".join(f"({a})" for a in args) + ")" if len(args) >= 2 else None


def _round_repl(args):
    # DAX ROUND(x, n): n = decimal places. ThoughtSpot round(x, inc): inc = rounding
    # increment. So ROUND(x, 0) -> round(x, 1); ROUND(x, 2) -> round(x, 0.01).
    if len(args) == 1:
        return f"{_RND}({args[0]})"
    if len(args) == 2 and re.fullmatch(r"-?\d+", args[1].strip()):
        n = int(args[1].strip())
        inc = 10.0 ** (-n)
        inc_s = str(int(inc)) if inc >= 1 else ("%.10f" % inc).rstrip("0")
        return f"{_RND}({args[0]}, {inc_s})"
    return None      # non-literal precision -> can't convert reliably; NEEDS REVIEW


def _ceiling_repl(args):
    # DAX CEILING(x[, sig]): round UP. TS ceil(y) rounds up to the nearest integer, so
    # CEILING(x) -> ceil(x); CEILING(x, sig) -> ceil(x/sig)*sig (sig=1 collapses to ceil(x)).
    if len(args) == 1:
        return f"ceil({args[0]})"
    if len(args) == 2:
        x, sig = args[0].strip(), args[1].strip()
        return f"ceil({x})" if sig in ("1", "1.0") else f"(ceil(({x})/({sig}))*({sig}))"
    return None


def _floor_repl(args):
    # DAX FLOOR(x[, sig]): round DOWN, mirror of CEILING. Emit via the _FLR sentinel so
    # the generated floor() isn't re-matched by this same case-insensitive expander.
    if len(args) == 1:
        return f"{_FLR}({args[0]})"
    if len(args) == 2:
        x, sig = args[0].strip(), args[1].strip()
        return f"{_FLR}({x})" if sig in ("1", "1.0") else f"({_FLR}(({x})/({sig}))*({sig}))"
    return None

