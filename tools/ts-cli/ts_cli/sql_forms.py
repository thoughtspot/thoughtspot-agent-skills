"""SQL -> ThoughtSpot forms shared by the Snowflake (``sv_sql``) and Databricks (``mv_sql``)
expression translators.

One copy, so the two SQL engines cannot drift (BL-217). Every form here was chosen against
live evidence from formula fidelity M0 (Snowflake) and M2 (Databricks); the reasons sit with
each function. Pure functions over the translators' token-joined text and ``units`` lists
(the flat list ``_expr_units`` builds before joining). stdlib only — vendored into the
Databricks Genie notebook (``agents/databricks/build_mv_lib.py``), so every top-level name
here must be unique across that closure.

Division (BL-357, user decision 2026-10-07: *return zero only when the source asks for zero*):

* ThoughtSpot ``a / b`` compiles to ``a / NULLIF(b, 0.0)`` (M2 compiled SQL) — NULL on a zero
  divisor, NULL on a NULL operand. So SQL ``x / NULLIF(y, 0)`` is plain ``x / y``.
* ``safe_divide ( a , b )`` compiles to ``CASE WHEN b = 0 THEN 0 ELSE a / NULLIF(b, 0) END``:
  **0** on a zero divisor — even when ``a`` is NULL — and NULL on a NULL divisor.
* ``COALESCE(x / NULLIF(y, 0), 0)`` is 0 on a zero divisor *and* on any NULL operand, so its
  exact form is ``ifnull ( safe_divide ( x , y ) , 0 )`` (``safe_divide`` alone was NULL on a
  NULL operand — M2 ``dbx-arith-005``).
"""
from __future__ import annotations

import re

from ts_cli.formula_common import (
    UntranslatableError,
    expr_is_aggregated,
    sql_digits_to_ts_increment,
    sql_passthrough_call,
    sql_int_digits,
)

#: Units that are binary operators in a translator's flat ``units`` list (after keyword
#: translation, so ``and`` / ``or`` are lower case). Anything else is an operand.
#: Placeholder unit for the Databricks ``DIV`` operator, folded by ``sqlf_fold_multiplicative``.
SQLF_DIV_MARK = "\x00DIV\x00"
SQLF_BINARY_OPS = frozenset({"+", "-", "*", "/", "%", "||", SQLF_DIV_MARK, "=", "!=", "<", ">",
                             "<=", ">=", "and", "or"})
#: The multiplicative level: ``*``, ``/``, ``%`` and ``DIV`` bind equally, left to right
#: (Databricks operator precedence; Snowflake has no ``DIV``).
_SQLF_MULT = frozenset({"*", "/", "%", SQLF_DIV_MARK})
#: Boundaries a ``||`` chain cannot cross: comparisons and boolean connectors bind looser.
_SQLF_CONCAT_BOUNDARY = frozenset({"=", "!=", "<", ">", "<=", ">=", "and", "or"})

#: Snap applied to a DOUBLE scaled for floor/ceil, before the floor/ceil. The same constant
#: as ``ts_cli/excel/functions.py`` ``SNAP`` (probe record §7: ``ceil ( to_double ( '1.1' ) *
#: 100 ) * 0.01`` is 1.11, the snapped form 1.1).
SQLF_SCALE_SNAP = "0.000000001"
#: Largest |scale| accepted for FLOOR(x, s) / CEIL(x, s): past 15 a double has no digits left
#: and the 10^s factor overflows floor/ceil's INT64 result.
SQLF_MAX_SCALE = 15


# --- grouping ----------------------------------------------------------------------------

def _sqlf_close(text: str, i: int) -> int:
    """Index of the ``)`` closing the ``(`` at ``text[i]``, skipping quoted text; -1 if none."""
    depth, quote = 0, None
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def sqlf_is_atomic(expr: str) -> bool:
    """True when ``expr`` needs no parentheses as an operand: one token, or one call /
    parenthesised group that closes at the very end (``sum ( [T::a] )``, ``( a + b )``)."""
    e = expr.strip()
    if " " not in e:
        return True
    if (e.startswith("'") and e.endswith("'") and e.count("'") == 2):
        return True
    if e.startswith("[") and e.endswith("]") and e.count("[") == 1 and e.count("]") == 1:
        return True
    head = e.split(" (", 1)[0] if " (" in e else None
    if e.startswith("( "):
        return _sqlf_close(e, 0) == len(e) - 1
    if head is not None and (head.isidentifier() or head == "unique count"):
        return _sqlf_close(e, len(head) + 1) == len(e) - 1
    return False


def sqlf_group(expr: str) -> str:
    """``expr`` parenthesised unless it is already an atomic operand."""
    return expr if sqlf_is_atomic(expr) else f"( {expr} )"


# --- division (BL-357) ------------------------------------------------------------------

def sqlf_nullif_division_parts(units: list[str], marker: str):
    """``(numerator_units, divisor)`` when ``units`` is one multiplicative term ending in
    ``/ NULLIF(y, 0)`` (the marker unit), else None. A leading unary minus is allowed."""
    if len(units) < 3 or units[-2] != "/" or not units[-1].startswith(marker):
        return None
    prefix = units[:-2]
    for j, u in enumerate(prefix):
        if u in SQLF_BINARY_OPS and u not in _SQLF_MULT and not (j == 0 and u == "-"):
            return None
    return prefix, units[-1][len(marker):]


def _sqlf_is_zero(text: str) -> bool:
    return text.strip() in ("0", "0.0")


def sqlf_zero_on_zero_division(x: str, y: str) -> str:
    """``COALESCE(x / NULLIF(y, 0), 0)``: 0 on a zero divisor and on any NULL operand."""
    return f"ifnull ( safe_divide ( {x} , {y} ) , 0 )"


def sqlf_null_default_call(name: str, raw_args: list[list[str]], finish, marker: str) -> str:
    """COALESCE / IFNULL / NVL / ZEROIFNULL over raw (unfinished) argument units.

    ``finish(units)`` collapses markers and folds operators in place; it is applied to a copy
    of each argument. A first argument that is exactly ``x / NULLIF(y, 0)`` takes the
    division forms (module docstring); anything else the generic forms, which are exact over
    any expression — ThoughtSpot ``/`` is already NULL on a zero divisor.
    """
    texts = [" ".join(finish(list(a))) for a in raw_args]
    want = {"ZEROIFNULL": (1,), "IFNULL": (2,), "NVL": (2,)}.get(name)
    if want is not None and len(raw_args) not in want:
        raise UntranslatableError(f"{name} expects {want[0]} arguments, got {len(raw_args)}")
    if not raw_args:
        raise UntranslatableError(f"{name} needs at least one argument")
    default = "0" if name == "ZEROIFNULL" else (texts[1] if len(texts) == 2 else None)
    parts = sqlf_nullif_division_parts(raw_args[0], marker)
    if parts is not None and default is not None:
        x = " ".join(finish(list(parts[0])))
        if _sqlf_is_zero(default):
            return sqlf_zero_on_zero_division(x, parts[1])
        return f"ifnull ( {x} / {sqlf_group(parts[1])} , {default} )"
    if name in ("ZEROIFNULL", "IFNULL", "NVL"):
        return f"ifnull ( {texts[0]} , {default} )"
    return _sqlf_coalesce_chain(texts)


def _sqlf_coalesce_chain(texts: list[str]) -> str:
    if len(texts) == 1:
        return texts[0]
    inner = _sqlf_coalesce_chain(texts[1:])
    return f"if ( {texts[0]} != null ) then {texts[0]} else {inner}"


def sqlf_div0(x: str, y: str) -> str:
    """Snowflake ``DIV0(x, y)``: 0 on a zero divisor, NULL when either operand is NULL —
    including ``DIV0(NULL, 0)``, which is NULL where ``safe_divide`` gives 0 (Snowflake, live
    2026-10-07). Hence the NULL guard on ``x``."""
    return f"( if ( isnull ( {x} ) ) then null else safe_divide ( {x} , {y} ) )"


def sqlf_div0null(x: str, y: str) -> str:
    """Snowflake ``DIV0NULL(x, y)``: 0 on a zero **or NULL** divisor, NULL on a NULL
    dividend (``DIV0NULL(NULL, 0)`` and ``DIV0NULL(NULL, NULL)`` are NULL — live 2026-10-07)."""
    return f"( if ( isnull ( {x} ) ) then null else safe_divide ( {x} , ifnull ( {y} , 0 ) ) )"


def _sqlf_tokens(expr: str) -> list[str]:
    """``expr``'s space-joined tokens, a quoted string or ``[…]`` reference kept whole."""
    toks, cur, quote, bracket = [], [], None, 0
    for ch in expr.strip():
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
            cur.append(ch)
        elif ch == "[":
            bracket += 1
            cur.append(ch)
        elif ch == "]":
            bracket -= 1
            cur.append(ch)
        elif ch == " " and not bracket:
            if cur:
                toks.append("".join(cur))
                cur = []
        else:
            cur.append(ch)
    if cur:
        toks.append("".join(cur))
    return toks


def _sqlf_strip_parens(toks: list[str]) -> list[str]:
    """``toks`` without redundant outer ``( … )`` pairs."""
    while len(toks) >= 2 and toks[0] == "(" and toks[-1] == ")":
        depth = 0
        for i, t in enumerate(toks):
            depth += (t == "(") - (t == ")")
            if depth == 0:
                break
        if i != len(toks) - 1:
            break
        toks = toks[1:-1]
    return toks


def _sqlf_top_split(toks: list[str]) -> tuple[list[list[str]], list[str]]:
    """Operands and the top-level binary operators between them. An operator token with no
    operand before it (``- x``, ``a * - b``) is unary and stays in its operand."""
    parts, ops, cur, depth = [], [], [], 0
    for t in toks:
        if depth == 0 and t in SQLF_BINARY_OPS and cur:
            parts.append(cur)
            ops.append(t)
            cur = []
            continue
        depth += (t == "(") - (t == ")")
        cur.append(t)
    parts.append(cur)
    return parts, ops


def _sqlf_join(parts: list[list[str]], ops: list[str]) -> list[str]:
    """The tokens of ``parts`` interleaved with ``ops`` (inverse of ``_sqlf_top_split``)."""
    out = list(parts[0])
    for op, part in zip(ops, parts[1:]):
        out += [op, *part]
    return out


def sqlf_safe_divide_form(cond: str, then: str, else_: str):
    """``safe_divide ( a , b )`` when a translated two-way conditional is exactly the form
    ``safe_divide`` compiles to, else None (BL-374).

    The source is ``CASE WHEN b = 0 THEN 0 ELSE a / NULLIF(b, 0) END`` — or ``IFF`` / ``IF``
    with the same three arguments, or the ELSE written ``a / b``. By the time this runs the
    pieces are translated ThoughtSpot text (``[B] = 0``, ``0``, ``[A] / [B]``: the
    ``/ NULLIF(b, 0)`` divisor idiom has already collapsed to ``/``), so the comparison is over
    normalised token sequences — whitespace, keyword case and identifier case are gone, and
    redundant outer parentheses are stripped — not over source strings.

    Exact on every NULL / zero input: the ELSE branch is reached only when ``b`` is non-zero
    or NULL, where ``NULLIF(b, 0)`` is ``b`` and ThoughtSpot's ``/`` (``a / NULLIF(b, 0.0)``)
    is plain division, so ``if ( b = 0 ) then 0 else a / b`` and ``safe_divide ( a , b )`` agree
    cell for cell (grid in the mapping docs). Refused: any THEN but ``0``, a condition other
    than ``b = 0`` (``0 = b``, ``b != 0`` with the arms swapped — NULL ``b`` then takes the 0
    arm), an ELSE whose top level is not one multiplicative term ending ``/ b``, and a divisor
    that differs from the condition's ``b``. The caller passes only a single-WHEN CASE.
    """
    if _sqlf_strip_parens(_sqlf_tokens(then)) != ["0"]:
        return None
    c_parts, c_ops = _sqlf_top_split(_sqlf_strip_parens(_sqlf_tokens(cond)))
    if [op for op in c_ops if op in _SQLF_CONCAT_BOUNDARY] != ["="] or c_ops[-1] != "=":
        return None
    if _sqlf_strip_parens(c_parts[-1]) != ["0"]:
        return None
    b = _sqlf_strip_parens(_sqlf_join(c_parts[:-1], c_ops[:-1]))
    e_parts, e_ops = _sqlf_top_split(_sqlf_strip_parens(_sqlf_tokens(else_)))
    if not e_ops or e_ops[-1] != "/" or any(op not in _SQLF_MULT for op in e_ops):
        return None
    if not b or _sqlf_strip_parens(e_parts[-1]) != b:
        return None
    numerator = _sqlf_join(e_parts[:-1], e_ops[:-1])
    a = " ".join(_sqlf_strip_parens(numerator) if len(e_parts) == 2 else numerator)
    return f"safe_divide ( {a} , {' '.join(b)} )"


def sqlf_plain_division(x: str, y: str) -> str:
    """``x / y`` as one operand (Databricks ``try_divide``: NULL on a zero divisor)."""
    return f"( {sqlf_group(x)} / {sqlf_group(y)} )"


# --- integer division and modulo (BL-360, BL-362) ---------------------------------------

def sqlf_int_div(x: str, y: str) -> str:
    """Databricks ``x DIV y``: the quotient truncated toward zero (``-7 DIV 2 = -3``), BIGINT.

    ThoughtSpot's ``/`` is a DOUBLE division, exact to the integer part while |x| < 2^53;
    ``floor`` / ``ceil`` return INT64. A zero divisor makes the quotient NULL, and so the
    result — the non-ANSI answer (``7 DIV 0`` is NULL non-ANSI, DIVIDE_BY_ZERO under ANSI)."""
    q = f"{sqlf_group(x)} / {sqlf_group(y)}"
    return f"( if ( {q} >= 0 ) then floor ( {q} ) else ceil ( {q} ) )"


#: ThoughtSpot functions that return INT64 (probe record §7 and the formula reference).
_SQLF_INT_FUNCS = frozenset({
    "floor", "ceil", "to_integer", "sql_int_op", "strlen", "strpos", "count", "unique count",
    "year", "month_number", "day", "hour_of_day", "quarter_number", "day_number_of_week",
    "day_number_of_year", "week_number_of_year", "diff_days", "diff_months", "diff_years",
    "diff_quarters", "diff_weeks", "diff_hours", "diff_minutes", "diff_time"})
_SQLF_INT_LITERAL = re.compile(r"^-?\s*\d+$")


def sqlf_split_top(expr: str, ops: frozenset) -> list[str]:
    """``expr`` split on top-level binary operators in ``ops`` (spaced token style)."""
    parts, depth, cur = [], 0, []
    for tok in expr.split(" "):
        depth += tok.count("(") - tok.count(")")
        if depth == 0 and tok in ops and cur:
            parts.append(" ".join(cur))
            cur = []
        else:
            cur.append(tok)
    parts.append(" ".join(cur))
    return parts


def sqlf_is_integral(expr: str, int_refs=()) -> bool:
    """True when ``expr`` is an integer by construction: an integer literal, a column known to
    be integer-typed, an INT64-returning call, or ``+`` / ``-`` / ``*`` over those."""
    e = expr.strip()
    if _SQLF_INT_LITERAL.match(e) or e in int_refs:
        return True
    if e.startswith("( ") and sqlf_is_atomic(e):
        return sqlf_is_integral(e[2:-2], int_refs)
    head = e.split(" (", 1)[0]
    if sqlf_is_atomic(e) and head in _SQLF_INT_FUNCS:
        return True
    parts = sqlf_split_top(e, frozenset({"+", "-", "*"}))
    return len(parts) > 1 and all(p and sqlf_is_integral(p, int_refs) for p in parts)


def sqlf_resolver_is_aggregated(resolver):
    """An ``is_aggregated(text)`` for ``resolver``: aggregated by its text, or because it holds a
    metric reference the resolver handed out (``[formula_X]``; Databricks ``__MVREF_n__``)."""
    refs = tuple(getattr(resolver, "metric_refs", ()) or ())
    return lambda t: expr_is_aggregated(t) or "__MVREF_" in t or any(r in t for r in refs)


def sqlf_mod(x: str, y: str, resolver=None) -> str:
    """SQL ``x % y`` / ``MOD(x, y)``: the remainder takes the dividend's sign in Snowflake and
    Databricks, as ThoughtSpot ``mod`` does (probe record §7). But ``mod`` accepts INT64 only
    and rejects a DOUBLE at import (probe record §7; M2 ``dbxn-002`` ``I1 % N2``, 2026-10-07).
    Native ``mod`` when both operands are integral by construction (``sqlf_is_integral``, with
    the resolver's ``int_refs`` from ``--columns`` types), over an aggregate or a metric
    reference (which a row-level pass-through cannot wrap), or between literals; otherwise the
    warehouse's own ``MOD``, exact for any numeric type."""
    is_agg = sqlf_resolver_is_aggregated(resolver)
    int_refs = getattr(resolver, "int_refs", ()) or ()
    if (is_agg(x) or is_agg(y) or "[" not in f"{x} {y}"
            or (sqlf_is_integral(x, int_refs) and sqlf_is_integral(y, int_refs))):
        return f"mod ( {x} , {y} )"
    return sql_passthrough_call("sql_double_op", "MOD", [x, y])


_SQLF_FOLDS = {"%": sqlf_mod, SQLF_DIV_MARK: lambda x, y, resolver=None: sqlf_int_div(x, y)}


def sqlf_fold_multiplicative(units: list[str], resolver=None) -> None:
    """Fold ``%`` and ``DIV`` units into calls, in place, at their precedence: the left
    operand is the whole multiplicative run before the operator (``a * b % c`` is
    ``(a * b) % c``), the right operand the one unit after it."""
    i, start = 0, 0
    while i < len(units):
        u = units[i]
        if u in _SQLF_FOLDS:
            if i == start or i + 1 >= len(units) or units[i + 1] in SQLF_BINARY_OPS:
                name = "DIV" if u == SQLF_DIV_MARK else u
                raise UntranslatableError(f"operator {name!r} without two plain operands")
            left = " ".join(units[start:i])
            if i - start > 1:
                left = f"( {left} )"
            units[start:i + 2] = [_SQLF_FOLDS[u](left, units[i + 1], resolver)]
            i = start
        elif u in SQLF_BINARY_OPS and u not in _SQLF_MULT:
            start = i + 1
        i += 1


def sqlf_fold_concat(units: list[str]) -> None:
    """``a || b || c`` -> ``concat ( a , b , c )``, in place. ``||`` binds with ``+``/``-`` and
    tighter than comparisons, so a chain runs between comparison / boolean boundaries; a chain
    mixed with any other operator is refused rather than guessed. NULL-propagating in
    Snowflake and Databricks, like ``concat``. ``concat`` takes Text only (probe record §7), so
    a numeric operand fails at import — loudly."""
    if "||" not in units:
        return
    out: list[str] = []
    seg: list[str] = []
    for u in units + [None]:
        if u is None or u in _SQLF_CONCAT_BOUNDARY:
            out.extend(_sqlf_concat_segment(seg))
            if u is not None:
                out.append(u)
            seg = []
        else:
            seg.append(u)
    units[:] = out


def _sqlf_concat_segment(seg: list[str]) -> list[str]:
    if "||" not in seg:
        return seg
    operands = seg[0::2]
    if (len(seg) % 2 == 0 or any(u != "||" for u in seg[1::2])
            or any(o in SQLF_BINARY_OPS for o in operands)):
        raise UntranslatableError(
            "'||' mixed with other operators — parenthesise the operands or use CONCAT()")
    return [f"concat ( {' , '.join(operands)} )"]


def sqlf_guard_adjacent(units: list[str], text: str) -> None:
    """Refuse an identifier that follows an operand with no operator between them: an SQL
    keyword operator the translator does not know (``a DIV b``, ``s REGEXP p``) would
    otherwise be read as a column and reported TRANSLATED (BL-360)."""
    if units and units[-1] not in SQLF_BINARY_OPS and units[-1] not in ("not",):
        raise UntranslatableError(
            f"'{text}' follows an operand with no operator between them — an unsupported "
            "SQL operator or keyword, not a column")


# --- FLOOR / CEIL with a scale (BL-361) -------------------------------------------------

def sqlf_scaled_floor_ceil(fn: str, x: str, scale: str, *, snap: bool) -> str:
    """``FLOOR(x, s)`` / ``CEIL(x, s)`` (``fn`` = ``floor`` | ``ceil``), a literal scale.

    ``s > 0``: ``fn ( x * 10^s ) * 10^-s`` — multiplied back by the increment, never divided
    by the factor (BL-348: Snowflake keeps an integer quotient at scale 6). ``s = 0``:
    ``fn ( x )``. ``s < 0``: ``fn ( x / 10^-s ) * 10^-s``.

    ``snap`` nudges the scaled value by 1e-9 toward the step it may have just missed
    (``ceil ( v - 1e-9 )``, ``floor ( v + 1e-9 )``) and divides back by the factor. Databricks needs it: its
    ``floor(DOUBLE, s)`` works in DECIMAL (``floor(0.29D, 2)`` = 0.29, ``ceil(1.1D, 2)`` =
    1.10), while ThoughtSpot's ``0.29 * 100`` is 28.999999999999996. Snowflake must NOT have
    it: its ``FLOOR(DOUBLE, s)`` is plain double arithmetic (``FLOOR(0.29::DOUBLE, 2)`` = 0.28,
    ``CEIL(1.1::DOUBLE, 2)`` = 1.11), which the unsnapped form reproduces (both live
    2026-10-07). Residual with the nudge: a value within 1e-9 (in scaled units) of a step is
    moved onto it.
    """
    s = sql_int_digits(scale)
    if s is None:
        raise UntranslatableError(
            f"{fn.upper()} with a non-literal scale has no native form (BL-361)")
    if abs(s) > SQLF_MAX_SCALE:
        raise UntranslatableError(f"{fn.upper()} scale {s} is beyond a double's 15 digits")
    if s == 0:
        return f"{fn} ( {x} )"
    g = sqlf_group(x)
    if s > 0:
        factor = sql_digits_to_ts_increment(str(-s))
        scaled = f"{g} * {factor}"
        # Snapped: divide back by the integer factor. Databricks' INT / INT is a DOUBLE
        # division with no scale cap; multiplying by 10^-s added noise live (0.30000000000000004).
        # Unsnapped (Snowflake): multiply by the increment, because Snowflake keeps an integer
        # quotient at scale 6 (BL-348).
        back = f"/ {factor}" if snap else f"* {sql_digits_to_ts_increment(str(s))}"
    else:
        factor = sql_digits_to_ts_increment(str(s))
        scaled, back = f"{g} / {factor}", f"* {factor}"
    if snap:
        # The nudge, not round ( v , 1e-9 ): ThoughtSpot compiles that round to
        # 1.0E-9 * ROUND(v / 1.0E-9), and the DOUBLE multiply-back lands ~1 ulp above an
        # integer, so ceil moved on-step values a whole step (CEIL(3.0, 1) -> 3.1; review of
        # #578, live 2026-10-07). BL-217: the Excel translator is getting the same algorithm as
        # formula_common.scaled_ceil_floor (#577); unify on it when that lands.
        nudge = "-" if fn == "ceil" else "+"
        scaled = f"{scaled} {nudge} {SQLF_SCALE_SNAP}"
    return f"( {fn} ( {scaled} ) {back} )"


# --- integral casts (BL-359) ------------------------------------------------------------

def sqlf_trunc_toward_zero(x: str) -> str:
    """``x`` truncated toward zero with native functions, for an aggregated ``x`` that a
    row-level pass-through cannot wrap. ``floor`` / ``ceil`` return INT64."""
    g = sqlf_group(x)
    return f"( if ( {g} >= 0 ) then floor ( {g} ) else ceil ( {g} ) )"


def sqlf_rounded_cast(x: str, scale: int, op_sql: str, aggregated: bool) -> str:
    """A cast to a DECIMAL / NUMBER with ``scale`` > 0 digits, which rounds half away from
    zero. Row-level: the warehouse's own cast, ``op_sql`` (``"CAST({0} AS DECIMAL(10,2))"``),
    exact by construction. Over an aggregate, which a row-level pass-through cannot wrap:
    ``round ( x , 10^-s )`` — ROUND is half away from zero too, exact on a DECIMAL aggregate."""
    if aggregated:
        return f"round ( {x} , {sql_digits_to_ts_increment(str(scale))} )"
    return f'sql_double_op ( "{op_sql}" , {x} )'


# --- LIKE family (BL-362) ---------------------------------------------------------------

def sqlf_like(op: str, operand: str, pattern: str) -> str:
    """``x [NOT] LIKE | ILIKE | RLIKE 'p'`` -> a ``sql_bool_op`` pass-through, exact by
    construction: the warehouse evaluates its own operator, so LIKE stays case-sensitive (no
    BL-333 divergence) and RLIKE keeps its regex dialect. The pattern must be a string
    literal with no double quote, brace or backslash — a template has no escape for them
    (probe record §7)."""
    p = pattern.strip()
    if not (p.startswith("'") and p.endswith("'") and len(p) >= 2):
        raise UntranslatableError(f"{op} with a non-literal pattern has no pass-through form")
    if "''" in p[1:-1] and not any(ch in p for ch in '"{}\\'):
        # a quote inside the pattern: bound, not inlined — Databricks reads 'it''s' as
        # `its` (BL-365); a bound literal is passed as the warehouse's own literal. A
        # double quote, brace or backslash is still refused below: unprobed as a bound value
        return f'sql_bool_op ( "{{0}} {op} {{1}}" , {operand} , {p} )'
    if any(ch in p for ch in '"{}\\'):
        raise UntranslatableError(
            f"{op} pattern {p} holds a double quote, a brace or a backslash, which a "
            "sql_*_op template cannot carry")
    return f'sql_bool_op ( "{{0}} {op} {p}" , {operand} )'
