"""Lark AST-based Tableau→ThoughtSpot formula translator (experimental).

An alternative to the regex translator in ``tableau.py``. Instead of a chain of
string substitutions, this parses each formula into an abstract syntax tree with
a grammar, then walks the tree to emit ThoughtSpot syntax. The tree makes
structure explicit, so nested calls, quoted keywords, and operator precedence
cannot be confused the way text substitution can.

Entry point: ``translate_ast(formula: str) -> str``. Raises ``FormulaParseError``
when the grammar cannot parse the input (callers can fall back to regex).

Function mappings are imported from ``tableau.py`` so the two translators stay in
lockstep on which Tableau function maps to which ThoughtSpot function.
"""
from __future__ import annotations

from lark import Lark, Transformer, v_args
from lark.exceptions import LarkError

from ts_cli.commands.tableau_parse import (
    _DATEDIFF_MAP,
    _DATETRUNC_MAP,
    _DATEADD_MAP,
    _DATEPART_MAP,
    _ensure_trailing_else,
)


class FormulaParseError(Exception):
    """Raised when the grammar cannot parse a formula."""


# ─────────────────────────────────────────────────────────────────────────────
# Grammar
# ─────────────────────────────────────────────────────────────────────────────
# Keyword terminals are case-insensitive and given higher priority than NAME so
# `IF`, `AND`, etc. are never captured as function/field identifiers. Field refs
# are always bracketed, so they never collide with keywords.

GRAMMAR = r"""
?start: expr

?expr: if_expr
     | case_expr
     | or_expr

if_expr: IF expr THEN expr elseif* else_clause? END
elseif: ELSEIF expr THEN expr
else_clause: ELSE expr

case_expr: CASE expr? when_clause+ else_clause? END
when_clause: WHEN expr THEN expr

?or_expr: and_expr (OR and_expr)*
?and_expr: not_expr (AND not_expr)*
?not_expr: NOT not_expr        -> not_op
         | comparison

?comparison: sum_expr comp_tail?
comp_tail: COMP_OP sum_expr    -> comp
         | NOT? IN "(" arglist ")"  -> in_clause

?sum_expr: sum_expr PLUS term   -> add
         | sum_expr MINUS term  -> sub
         | term

?term: term STAR power    -> mul
     | term SLASH power   -> div
     | term PERCENT power -> mod
     | power

?power: factor CARET power -> powexpr
      | factor

?factor: MINUS factor     -> neg
       | primary

?primary: NUMBER          -> number
        | ESCAPED_STRING  -> dstring
        | SINGLE_STRING   -> sstring
        | DATE_LITERAL    -> datelit
        | TRUE            -> true
        | FALSE           -> false
        | NULL            -> null
        | cast
        | lod
        | funccall
        | field
        | "(" expr ")"    -> paren

cast: CAST "(" expr AS TYPENAME ")"

funccall: NAME "(" arglist? ")"
arglist: expr ("," expr)*

field: FIELD

lod: "{" lod_body "}"
lod_body: FIXED dimlist? ":" expr   -> lod_fixed
        | INCLUDE dimlist ":" expr  -> lod_include
        | EXCLUDE dimlist ":" expr  -> lod_exclude
        | expr                      -> lod_bare
dimlist: field ("," field)*

// ── terminals ──
IF: /IF/i
THEN: /THEN/i
ELSEIF: /ELSEIF/i
ELSE: /ELSE/i
END: /END/i
CASE: /CASE/i
WHEN: /WHEN/i
AND: /AND/i
OR: /OR/i
NOT: /NOT/i
IN: /IN/i
TRUE: /TRUE/i
FALSE: /FALSE/i
NULL: /NULL/i
CAST: /CAST/i
AS: /AS/i
FIXED: /FIXED/i
INCLUDE: /INCLUDE/i
EXCLUDE: /EXCLUDE/i
// Longest-first: alternation is not longest-match, so INTEGER must precede INT,
// DATETIME precede DATE, BOOLEAN precede BOOL. \b guards against prefix bleed.
TYPENAME: /(INTEGER|INT|DOUBLE|DECIMAL|NUMERIC|REAL|FLOAT|VARCHAR|STRING|TEXT|CHAR|DATETIME|TIMESTAMP|DATE|BOOLEAN|BOOL)\b/i

COMP_OP: "==" | "!=" | "<>" | "<=" | ">=" | "<" | ">" | "="
PLUS: "+"
MINUS: "-"
STAR: "*"
SLASH: "/"
PERCENT: "%"
CARET: "^"

FIELD: /\[[^\]]*\](\s*\.\s*\[[^\]]*\])*/
NAME: /[A-Za-z_][A-Za-z0-9_]*/
NUMBER: /\d+(\.\d+)?/
ESCAPED_STRING: /"[^"]*"/
SINGLE_STRING: /'[^']*'/
DATE_LITERAL: /#[^#]*#/

// Tableau formula comments — line (// …) and block (/* … */). Ignored.
COMMENT_LINE: /\/\/[^\n]*/
COMMENT_BLOCK: /\/\*[\s\S]*?\*\//

%import common.WS
%ignore WS
%ignore COMMENT_LINE
%ignore COMMENT_BLOCK
"""

# Keyword terminals must beat NAME. Lark's contextual lexer usually resolves
# this, but we bump priority to be safe by defining them as regex terminals
# above (regex terminals default to priority based on length; explicit
# same-length keywords are fine because they only match whole tokens the parser
# expects in that position with the earley+dynamic lexer).

_parser = Lark(GRAMMAR, parser="earley", lexer="dynamic", maybe_placeholders=True)


# ─────────────────────────────────────────────────────────────────────────────
# Function mapping
# ─────────────────────────────────────────────────────────────────────────────

# Simple name renames: TableauFUNC(args) -> tsname(args), args unchanged.
# The standard aggregates are lowercased for consistency with the docs/house
# style (the TS parser is case-insensitive, so this is cosmetic).
_SIMPLE_RENAME = {
    "SUM": "sum",
    "MIN": "min",
    "MAX": "max",
    "COUNT": "count",
    "COUNTD": "unique count",
    "AVG": "average",
    "STDEV": "stddev",
    "STDEVP": "stddev",
    "LEN": "strlen",
    "FIND": "strpos",
    "CEILING": "ceil",
    "LOG": "log10",
    "POWER": "pow",
    "MONTH": "month_number",
    "YEAR": "year",
    "DAY": "day",
    "WEEK": "week_number_of_year",
    "ISNULL": "isnull",
    "IFNULL": "ifnull",
    "CONTAINS": "contains",
    "STARTSWITH": "starts_with",
    "ENDSWITH": "ends_with",
    "FLOAT": "to_double",
    "WINDOW_AVG": "moving_average",
    "WINDOW_SUM": "moving_sum",
    "WINDOW_MIN": "moving_min",
    "WINDOW_MAX": "moving_max",
    "RUNNING_SUM": "cumulative_sum",
    "RUNNING_AVG": "cumulative_average",
    "RUNNING_MIN": "cumulative_min",
    "RUNNING_MAX": "cumulative_max",
    # variance — mirror of STDEV/STDEVP -> stddev (Tableau name differs from TS)
    "VAR": "variance",
    "VARP": "variance",
    # same-named functions — map explicitly rather than relying on the TS
    # parser's case-insensitive pass-through. (Trig fns are deliberately NOT
    # here: Tableau uses radians, ThoughtSpot uses degrees — a rename would be
    # silently wrong.)
    "MEDIAN": "median",
    "ABS": "abs",
    "FLOOR": "floor",
    "SQRT": "sqrt",
    "EXP": "exp",
    "LN": "ln",
    "TODAY": "today",
    "NOW": "now",
}

# Sub-day DATEDIFF units — the shared _DATEDIFF_MAP only covers day-granularity
# and coarser. diff_time returns whole seconds.
_DATEDIFF_TIME = {
    "hour": "diff_hours",
    "minute": "diff_minutes",
    "second": "diff_time",
}


def _call(name: str, args: list) -> str:
    return f"{name} ( {' , '.join(args)} )"


def _round_factor(places: int) -> str:
    """Convert a Tableau ROUND decimal-places count into a ThoughtSpot factor.

    Tableau ``ROUND(x, 2)`` means "2 decimal places"; ThoughtSpot
    ``round(x, factor)`` means "round to the nearest factor". So
    2 -> '0.01', 1 -> '0.1', 0 -> '1', -1 -> '10'.
    """
    if places <= 0:
        return str(10 ** (-places))
    return "0." + "0" * (places - 1) + "1"


@v_args(inline=True)
class TableauToTS(Transformer):
    """Walk the parse tree, emitting ThoughtSpot formula text."""

    def __init__(self):
        super().__init__()
        self._unknown_functions: list[str] = []
        self._on_unknown = None

    def reset(self, on_unknown=None):
        self._unknown_functions = []
        self._on_unknown = on_unknown

    # ── literals ──
    def number(self, tok):
        return str(tok)

    def dstring(self, tok):
        # Tableau double-quoted string -> ThoughtSpot single-quoted
        return "'" + str(tok)[1:-1] + "'"

    def sstring(self, tok):
        return str(tok)

    def datelit(self, tok):
        # Tableau date literal #2024-01-01# -> to_date('2024-01-01', 'fmt').
        # ThoughtSpot has no #...# literal syntax; to_date is the equivalent.
        inner = str(tok)[1:-1].strip()
        fmt = "yyyy-MM-dd HH:mm:ss" if (":" in inner or " " in inner) else "yyyy-MM-dd"
        return f"to_date ( '{inner}' , '{fmt}' )"

    def true(self, tok):
        return "true"

    def false(self, tok):
        return "false"

    def null(self, tok):
        return "null"

    def field(self, tok):
        return str(tok)

    def paren(self, inner):
        return f"( {inner} )"

    # ── operators ──
    def add(self, a, _op, b):
        return self._plus(a, b)

    def sub(self, a, _op, b):
        return f"{a} - {b}"

    def mul(self, a, _op, b):
        return f"{a} * {b}"

    def div(self, a, _op, b):
        return f"{a} / {b}"

    def mod(self, a, _op, b):
        return _call("mod", [a, b])

    def neg(self, _op, a):
        return f"- {a}"

    def powexpr(self, base, _op, exp):
        # Tableau '^' and ThoughtSpot '^' are both power operators — pass through.
        return f"{base} ^ {exp}"

    def _plus(self, a, b):
        # string concatenation if either side looks like a string/field
        if self._is_stringy(a) or self._is_stringy(b):
            # Flatten a chain of + into one flat concat(a, b, c, ...) rather than
            # nesting concat(concat(...)). Same result, cleaner output.
            parts = self._concat_parts(a) + self._concat_parts(b)
            return "concat ( " + " , ".join(parts) + " )"
        return f"{a} + {b}"

    @staticmethod
    def _is_stringy(s: str) -> bool:
        s = s.strip()
        return s.startswith("'") or s.startswith("[") or s.startswith("concat (")

    @classmethod
    def _concat_parts(cls, s: str) -> list:
        """If s is itself a concat(...) expression, return its top-level args so
        chains flatten; otherwise return [s]."""
        s = s.strip()
        if s.startswith("concat (") and s.endswith(")"):
            inner = s[len("concat ("):-1]
            return _split_top_level(inner)
        return [s]

    def not_op(self, _kw, a):
        return f"not {a}"

    # comparison: sum_expr comp_tail?  (comp_tail aliased to comp / in_clause)
    def comparison(self, left, tail=None):
        if tail is None:
            return left
        return tail(left)

    def comp(self, op, rhs):
        op = str(op)
        if op == "==":
            op = "="
        return lambda left: f"{left} {op} {rhs}"

    def in_clause(self, *children):
        # NOT? IN "(" arglist ")" — token order varies with placeholders, so
        # detect NOT by scanning children rather than relying on position.
        not_present = any(getattr(c, "type", None) == "NOT" for c in children)
        arglist = children[-1]
        vals = arglist if isinstance(arglist, list) else [arglist]
        joined = " , ".join(vals)
        kw = "not in" if not_present else "in"
        return lambda left: f"{left} {kw} {{ {joined} }}"

    def or_expr(self, *children):
        parts = [c for c in children if not self._is_kw(c, "OR")]
        return " or ".join(parts)

    def and_expr(self, *children):
        parts = [c for c in children if not self._is_kw(c, "AND")]
        return " and ".join(parts)

    @staticmethod
    def _is_kw(c, kw):
        return hasattr(c, "type") and c.type == kw

    # ── IF / CASE ──
    def else_clause(self, _kw, expr):
        return ("else", expr)

    def elseif(self, _kw, cond, _then, val):
        return ("elseif", cond, val)

    def when_clause(self, _kw, val, _then, res):
        return (val, res)

    def if_expr(self, *children):
        # IF cond THEN val (elseif)* (else)? END
        children = [c for c in children if not self._is_ctrl(c)]
        cond = children[0]
        then_val = children[1]
        rest = children[2:]
        parts = [f"if ({cond}) then {then_val}"]
        else_expr = None
        for item in rest:
            if isinstance(item, tuple) and item and item[0] == "elseif":
                parts.append(f"else if ({item[1]}) then {item[2]}")
            elif isinstance(item, tuple) and item and item[0] == "else":
                else_expr = item[1]
        if else_expr is not None:
            parts.append(f"else {else_expr}")
            return " ".join(parts)
        # no else -> ensure_trailing_else adds one
        return _ensure_trailing_else(" ".join(parts))

    def case_expr(self, *children):
        children = [c for c in children if not self._is_ctrl(c)]
        # optional switch expr: first child is a str that is NOT a (val,res) tuple
        idx = 0
        switch = None
        if children and not isinstance(children[0], tuple):
            switch = children[0]
            idx = 1
        whens = []
        else_expr = None
        for item in children[idx:]:
            if isinstance(item, tuple) and item and item[0] == "else":
                else_expr = item[1]
            elif isinstance(item, tuple):
                whens.append(item)
        ts = else_expr if else_expr is not None else "null"
        for val, res in reversed(whens):
            cond = f"{switch} = {val}" if switch is not None else val
            ts = f"if ({cond}) then {res} else {ts}"
        return ts

    @staticmethod
    def _is_ctrl(c):
        return hasattr(c, "type") and c.type in (
            "IF", "THEN", "ELSE", "ELSEIF", "END", "CASE", "WHEN",
        )

    # ── cast ──  CAST ( expr AS TYPENAME )
    def cast(self, _cast_kw, expr, _as_kw, typ):
        t = str(typ).upper()
        if t in ("INT", "INTEGER"):
            return _call("to_integer", [expr])
        if t in ("FLOAT", "DOUBLE", "DECIMAL", "NUMERIC", "REAL"):
            return _call("to_double", [expr])
        if t in ("VARCHAR", "STRING", "TEXT", "CHAR"):
            return _call("to_string", [expr])
        if t in ("BOOL", "BOOLEAN"):
            return expr
        if t == "DATE":
            if expr.strip().startswith("["):
                return expr
            return f"to_date ( {expr} , '%Y-%m-%d' )"
        if t in ("DATETIME", "TIMESTAMP"):
            if expr.strip().startswith("["):
                return expr
            return f"to_date ( {expr} , '%Y-%m-%d %H:%M:%S' )"
        return _call("cast", [expr])

    # ── function call ──
    def arglist(self, *args):
        return list(args)

    def funccall(self, name, arglist=None):
        fname = str(name)
        up = fname.upper()
        args = arglist if arglist is not None else []
        if not isinstance(args, list):
            args = [args]
        return self._map_function(up, fname, args)

    def _map_function(self, up: str, orig: str, args: list) -> str:
        # date unit-dispatch families
        if up == "DATEDIFF" and len(args) >= 3:
            unit = _strip_q(args[0]).lower()
            fn = _DATEDIFF_MAP.get(unit) or _DATEDIFF_TIME.get(unit)
            if fn:
                if unit == "week":
                    return f"floor ( {fn} ( {args[2]} , {args[1]} ) / 7 )"
                return _call(fn, [args[2], args[1]])
        if up == "DATETRUNC" and len(args) >= 2:
            fn = _DATETRUNC_MAP.get(_strip_q(args[0]).lower())
            if fn:
                return _call(fn, [args[1]])
        if up == "DATEADD" and len(args) >= 3:
            unit = _strip_q(args[0]).lower()
            fn = _DATEADD_MAP.get(unit)
            if fn:
                return _call(fn, [args[2], args[1]])
            if unit == "quarter":
                return f"add_months ( {args[2]} , {args[1]} * 3 )"
            if unit == "hour":
                # ThoughtSpot has no add_hours — express hours as minutes
                return f"add_minutes ( {args[2]} , {args[1]} * 60 )"
            if unit in ("minute", "second"):
                return _call(f"add_{unit}s", [args[2], args[1]])
        if up in ("DATEPART", "DATENAME") and len(args) >= 2:
            fn = _DATEPART_MAP.get(_strip_q(args[0]).lower())
            if fn:
                return _call(fn, [args[1]])
        if up == "DATEPARSE" and len(args) >= 2:
            return f"to_date ( {args[1]} , '{_strip_q(args[0])}' )"
        if up == "DATE" and len(args) == 1:
            if args[0].strip().startswith("["):
                return args[0]
            return f"to_date ( {args[0]} , 'yyyy-MM-dd' )"

        # string / misc arg-transform
        if up == "STR" or up == "STRING":
            if len(args) == 2 and args[1].strip() == "'#'":
                return _call("to_string", [args[0]])
            return _call("to_string", args)
        if up == "LEFT" and len(args) == 2:
            return f"substr ( {args[0]} , 0 , {args[1]} )"
        if up == "RIGHT" and len(args) == 2:
            return f"substr ( {args[0]} , strlen ( {args[0]} ) - {args[1]} , {args[1]} )"
        if up == "MID" and len(args) == 3:
            return f"substr ( {args[0]} , {args[1]} - 1 , {args[2]} )"
        if up == "UPPER" and len(args) == 1:
            return f'sql_string_op ( "upper({{0}})" , {args[0]} )'
        if up == "LOWER" and len(args) == 1:
            return f'sql_string_op ( "lower({{0}})" , {args[0]} )'
        if up == "TRIM" and len(args) == 1:
            return f'sql_string_op ( "trim({{0}})" , {args[0]} )'
        if up == "LTRIM" and len(args) == 1:
            return f'sql_string_op ( "ltrim({{0}})" , {args[0]} )'
        if up == "RTRIM" and len(args) == 1:
            return f'sql_string_op ( "rtrim({{0}})" , {args[0]} )'
        if up == "REPLACE" and len(args) >= 3:
            return f'sql_string_op ( "replace({{0}}, {args[1]}, {args[2]})" , {args[0]} )'
        if up == "ZN" and len(args) == 1:
            return f"ifnull ( {args[0]} , 0 )"
        if up == "SQUARE" and len(args) == 1:
            return f"pow ( {args[0]} , 2 )"
        if up == "ATTR" and len(args) == 1:
            return args[0]
        if up == "IIF" and len(args) >= 3:
            return f"if ( {args[0]} ) then {args[1]} else {args[2]}"
        if up == "TOTAL" and len(args) == 1:
            return f"group_aggregate({args[0]}, {{}}, query_filters())"
        if up in ("INT", "INTEGER") and len(args) == 1:
            return f"if ( {args[0]} >= 0 ) then floor ( {args[0]} ) else ceil ( {args[0]} )"
        if up == "SIGN" and len(args) == 1:
            return f"if ( {args[0]} > 0 ) then 1 else if ( {args[0]} < 0 ) then -1 else 0"

        # rank family — ThoughtSpot rank/rank_percentile take EXACTLY two args:
        # an aggregate expression and a direction ('asc' | 'desc'). Tableau's
        # order arg is optional and defaults to 'desc', so inject 'desc' when the
        # source omits it (a one-arg rank fails TS validation with
        # "Function rank expects 2 arguments, found 1").
        # NOTE: TS rank is always GLOBAL. Tableau table-calc partitioning is
        # defined in the worksheet, not in the formula text, so it cannot be
        # detected here — a partitioned source rank translates to a global rank
        # and must be reviewed (switch to a sql_int_aggregate_op "rank() over
        # (partition by ...)" pass-through downstream if partitioning matters).
        if up in ("RANK", "RANK_PERCENTILE") and len(args) >= 1:
            ts_fn = "rank_percentile" if up == "RANK_PERCENTILE" else "rank"
            direction = args[1] if len(args) >= 2 else "'desc'"
            return _call(ts_fn, [args[0], direction])

        # ROUND — Tableau's 2nd arg is DECIMAL PLACES; ThoughtSpot's is a
        # rounding FACTOR. ROUND(x, 2) -> round(x, 0.01); ROUND(x) (0 dp) ->
        # round(x, 1). Only an integer-literal places arg is converted; a
        # non-literal places arg falls through (cannot be converted safely).
        if up == "ROUND":
            if len(args) == 1:
                return _call("round", [args[0], "1"])
            try:
                places = int(args[1].replace(" ", ""))
            except (ValueError, TypeError):
                places = None
            if places is not None:
                return _call("round", [args[0], _round_factor(places)])

        # PERCENTILE — Tableau uses a 0-1 fraction and no direction; ThoughtSpot
        # uses a 0-100 value and requires a direction. PERCENTILE(x, 0.9) ->
        # percentile(x, 90, 'asc'). Only a numeric-literal fraction is converted.
        if up == "PERCENTILE" and len(args) >= 2:
            try:
                frac = float(args[1])
            except (ValueError, TypeError):
                frac = None
            if frac is not None:
                pct = round(frac * 100, 6)
                pct_str = str(int(pct)) if pct == int(pct) else str(pct)
                return _call("percentile", [args[0], pct_str, "'asc'"])

        # MAX/MIN with two args are Tableau's ROW-LEVEL greatest/least, not the
        # aggregate (one-column) max/min. The 1-arg aggregate form falls through
        # to _SIMPLE_RENAME.
        if up in ("MAX", "MIN") and len(args) == 2:
            return _call("greatest" if up == "MAX" else "least", args)

        # simple renames
        if up in _SIMPLE_RENAME:
            return _call(_SIMPLE_RENAME[up], args)

        # unknown function — record it so the caller can flag for judgment
        self._unknown_functions.append(orig)
        if self._on_unknown is not None:
            self._on_unknown(orig)
        return _call(orig, args)

    # ── LOD ──
    def dimlist(self, *fields):
        return list(fields)

    def lod(self, body):
        return body

    def lod_fixed(self, _kw, dims=None, expr=None):
        # maybe_placeholders: dims may be None
        if expr is None:
            # grammar: FIXED dimlist? ":" expr — with placeholders dims/expr line up
            expr = dims
            dims = None
        dimstr = "{" + " , ".join(dims) + "}" if dims else "{}"
        return f"group_aggregate({expr}, {dimstr}, {{}})"

    def lod_include(self, _kw, dims, expr):
        dimstr = "{" + " , ".join(dims) + "}"
        return f"group_aggregate({expr}, query_groups() + {dimstr}, query_filters())"

    def lod_exclude(self, _kw, dims, expr):
        dimstr = "{" + " , ".join(dims) + "}"
        return f"group_aggregate({expr}, query_groups() - {dimstr}, query_filters())"

    def lod_bare(self, expr):
        return f"group_aggregate({expr}, {{}}, query_filters())"


def _strip_q(s: str) -> str:
    return s.strip().strip("'\"")


def _split_top_level(text: str) -> list:
    """Split on top-level commas, respecting (), [], {} and quotes."""
    parts, depth, cur = [], 0, []
    in_str = False
    for ch in text:
        if ch == "'":
            in_str = not in_str
        if not in_str:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            elif ch == "," and depth == 0:
                parts.append("".join(cur).strip())
                cur = []
                continue
        cur.append(ch)
    tail = "".join(cur).strip()
    if tail:
        parts.append(tail)
    return parts


_transformer = TableauToTS()


def translate_ast(formula: str, on_unknown=None) -> str:
    """Parse a Tableau formula and emit ThoughtSpot syntax via AST walk.

    Raises FormulaParseError if the grammar cannot parse the input.
    ``on_unknown(func_name)`` is called for each function the AST has no
    mapping for (passed through unchanged).
    """
    if not formula or not formula.strip():
        return formula
    _transformer.reset(on_unknown=on_unknown)
    try:
        tree = _parser.parse(formula)
    except LarkError as e:
        raise FormulaParseError(str(e)) from e
    result = _transformer.transform(tree)
    return result if isinstance(result, str) else str(result)


def _regex_pipeline(formula: str) -> str:
    """The regex translator's full pass (LOD → TOTAL → functions), for fallback."""
    from ts_cli.commands.tableau_parse import (
        _translate_lod_expressions,
        _translate_total,
        _translate_tableau_to_ts_functions,
    )
    return _translate_tableau_to_ts_functions(
        _translate_total(_translate_lod_expressions(formula))
    )


def translate_with_fallback(formula: str, on_fallback=None, on_unknown=None) -> str:
    """Translate via the AST; if the grammar can't parse this one formula, fall
    back to the regex translator for it (rather than erroring).

    ``on_fallback(formula, reason)`` is called when a fallback happens — pass a
    callback to count/log fallbacks for telemetry.
    ``on_unknown(func_name)`` is called for each function the translator has no
    mapping for (passed through unchanged). These should be routed to judgment.
    Returns the translated string either way.
    """
    try:
        return translate_ast(formula, on_unknown=on_unknown)
    except FormulaParseError as e:
        if on_fallback is not None:
            on_fallback(formula, str(e).splitlines()[0])
        return _regex_pipeline(formula)