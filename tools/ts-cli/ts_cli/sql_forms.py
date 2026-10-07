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


def sqlf_mod(x: str, y: str) -> str:
    """SQL ``x % y`` / ``MOD(x, y)``: the remainder takes the dividend's sign in Snowflake and
    Databricks, as ThoughtSpot ``mod`` does (probe record §7). But ``mod`` accepts INT64 only
    and rejects a DOUBLE at import (probe record §7; M2 ``dbxn-002`` ``I1 % N2``, 2026-10-07),
    and the translator cannot see column types. So a row-level operand with a column is the
    warehouse's own ``MOD`` (exact for any numeric type); an aggregate, which a row-level
    pass-through cannot wrap, and a literal-only remainder stay native ``mod``."""
    if expr_is_aggregated(x) or expr_is_aggregated(y) or "[" not in f"{x} {y}":
        return f"mod ( {x} , {y} )"
    return sql_passthrough_call("sql_double_op", "MOD", [x, y])


_SQLF_FOLDS = {"%": sqlf_mod, SQLF_DIV_MARK: sqlf_int_div}


def sqlf_fold_multiplicative(units: list[str]) -> None:
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
            units[start:i + 2] = [_SQLF_FOLDS[u](left, units[i + 1])]
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

    ``snap`` wraps the scaled value in ``round ( … , 0.000000001 )``. Databricks needs it: its
    ``floor(DOUBLE, s)`` works in DECIMAL (``floor(0.29D, 2)`` = 0.29, ``ceil(1.1D, 2)`` =
    1.10), while ThoughtSpot's ``0.29 * 100`` is 28.999999999999996. Snowflake must NOT have
    it: its ``FLOOR(DOUBLE, s)`` is plain double arithmetic (``FLOOR(0.29::DOUBLE, 2)`` = 0.28,
    ``CEIL(1.1::DOUBLE, 2)`` = 1.11), which the unsnapped form reproduces (both live
    2026-10-07). Residual with the snap: a value within 5e-10 of a step below the scale is
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
        scaled, back = f"{g} * {factor}", f"* {sql_digits_to_ts_increment(str(s))}"
    else:
        factor = sql_digits_to_ts_increment(str(s))
        scaled, back = f"{g} / {factor}", f"* {factor}"
    if snap:
        scaled = f"round ( {scaled} , {SQLF_SCALE_SNAP} )"
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
    if any(ch in p for ch in '"{}\\'):
        raise UntranslatableError(
            f"{op} pattern {p} holds a double quote, a brace or a backslash, which a "
            "sql_*_op template cannot carry")
    return f'sql_bool_op ( "{{0}} {op} {p}" , {operand} )'
