"""ThoughtSpot formula TEXT: how a string literal is spelled, how `a * b / c` groups, how a
SQL source literal decodes, and the trigonometry forms (BL-364, BL-365).

Split from ``formula_common`` (its line-count gate). Pure functions, stdlib only — part of the
Genie-vendorable closure (``agents/databricks/build_mv_lib.py``). Every text translator calls
``ts_finalize_formula`` as its last step; never fork these into a platform module.
"""
from __future__ import annotations

import re

from ts_cli.formula_common import UntranslatableError, sql_passthrough_call
# ---------------------------------------------------------------------------
# ThoughtSpot string literals and `a * b / c` grouping (BL-365)
# ---------------------------------------------------------------------------
#
# Live, se-thoughtspot 2026-10-07 (probe record §7, "Quotes and grouping"), each
# formula compared with the Snowflake value over the same rows:
#
#   * A doubled quote in a single-quoted ThoughtSpot literal is TWO quotes: `'it''s'`
#     compiles to `'it''''s'`. Every SQL-style source literal copied across verbatim was
#     a silent wrong answer.
#   * The backslash escape `'it\'s'` is exact only when the literal has no space after
#     it: `'it\'s here'` and `'x\'s '` are rejected at import.
#   * A DOUBLE-quoted literal is native and exact in every position tried — equality,
#     `!=`, `in { }`, `contains`, `concat` after an earlier literal, an `if` branch, and a
#     `sql_*_op` argument — and `\\` inside it is one backslash (`"a\\'b"` is `a\'b`).
#   * In a single-quoted literal `\\` is one backslash and a lone `\` is dropped.
#
#   * `[n] * 4 / 3` compiles to `n * (4 / NULLIF(3, 0))`: ThoughtSpot gives a division
#     the operand immediately before it, so `a * b * c / d` is `a * b * ( c / d )`, and a
#     literal-over-literal (or integer-over-integer) division is fixed-point at scale 6 in
#     Snowflake. `a / b / c`, `a / b * c`, `a - b + c` and `a - b - c` stay left to right.

def ts_string_literal(text: str) -> str:
    """ThoughtSpot formula text that evaluates to exactly ``text``.

    Plain text → ``'text'``. Text holding a quote or a backslash → the double-quoted
    literal ``"…"`` with each backslash doubled. Text holding both quote kinds → a
    ``concat`` of those forms split at each ``"`` (``'"'`` for the double quote).
    The output is a fixed point of ``ts_finalize_string_literals``."""
    if "'" not in text and "\\" not in text:
        return "'" + text + "'"
    if '"' not in text:
        return '"' + text.replace("\\", "\\\\") + '"'
    pieces: list[str] = []
    for i, part in enumerate(text.split('"')):
        if i:
            pieces.append("'\"'")
        if part:
            pieces.append(ts_string_literal(part))
    return "concat ( " + " , ".join(pieces) + " )"


def sql_std_literal(text: str) -> str:
    """``text`` as a SQL-standard literal (quote doubled, backslash literal) — the form
    the text translators carry internally until ``ts_finalize_formula``."""
    return "'" + text.replace("'", "''") + "'"


_TS_SCAN_RE = re.compile(r"""
    (?P<ws>\s+)
  | (?P<comment>/\*.*?\*/)
  | (?P<ref>\[[^\]]*\])
  | (?P<dq>"[^"]*")
  | (?P<sq>'(?:[^']|'')*')
  | (?P<num>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)
  | (?P<word>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>!=|<=|>=|[-+*/=<>(),{}])
  | (?P<other>.)
""", re.VERBOSE | re.DOTALL)

_TS_KEYWORDS = frozenset({"if", "then", "else", "and", "or", "not", "in", "between"})


def _ts_scan(text: str) -> list[tuple[str, str, int, int]]:
    return [(m.lastgroup, m.group(), m.start(), m.end()) for m in _TS_SCAN_RE.finditer(text)]


def ts_literals_unbalanced(text: str) -> bool:
    """True when ``text``'s single-quoted literals do not scan as SQL-standard literals: a quote
    is left unterminated. ThoughtSpot's own backslash escape does this (``[a] = 'it\\'s'``
    scans as ``'it\\'`` then a stray ``s'``)."""
    return any(kind == "other" and tok == "'" for kind, tok, _s, _e in _ts_scan(text))


def ts_finalize_string_literals(text: str) -> str:
    """Rewrite every SQL-standard single-quoted literal in ThoughtSpot formula text that
    ThoughtSpot would misread — one holding a doubled quote or a backslash — into
    ``ts_string_literal`` form. References, ``sql_*_op`` templates (double-quoted),
    comments and plain literals are untouched; idempotent.

    **Precondition:** the text's single-quoted literals are SQL-standard (quote doubled,
    backslash literal), as every translator carries them. Text that uses ThoughtSpot's own
    backslash escape (``'it\\'s'``) violates it — the scanner would end the literal at the
    escaped quote — and any text whose quotes do not balance is returned unchanged
    (``ts_literals_unbalanced``); ``output_guard`` reports it."""
    if ts_literals_unbalanced(text):
        return text
    out: list[str] = []
    for kind, tok, _s, _e in _ts_scan(text):
        if kind == "sq" and ("''" in tok[1:-1] or "\\" in tok):
            out.append(ts_string_literal(tok[1:-1].replace("''", "'")))
        else:
            out.append(tok)
    result = "".join(out)
    assert not ts_literals_unbalanced(result), result  # the precondition holds on the output
    return result


_TS_OPERANDS = ("ref", "dq", "sq", "num")


def _ts_is_operand_end(tok) -> bool:
    """True when ``tok`` can end an operand (so a following ``-`` is binary)."""
    kind, text = tok[0], tok[1]
    return kind in _TS_OPERANDS or (kind == "word" and text.lower() not in _TS_KEYWORDS) \
        or (kind == "op" and text in (")", "}"))


def _ts_opener(toks: list, pos: int) -> int | None:
    """Index of the ``(`` / ``{`` matching the closer at ``pos``."""
    depth = 0
    for i in range(pos, -1, -1):
        kind, text = toks[i][0], toks[i][1]
        if kind != "op":
            continue
        if text in (")", "}"):
            depth += 1
        elif text in ("(", "{"):
            depth -= 1
            if depth == 0:
                return i if text == ("(" if toks[pos][1] == ")" else "{") else None
    return None


def _ts_primary_start(toks: list, pos: int) -> int | None:
    """Index of the first token of the primary (with any unary sign) ending at ``pos``,
    in the non-whitespace token list; None when ``pos`` does not end a primary."""
    kind, tok = toks[pos][0], toks[pos][1]
    if kind == "op" and tok in (")", "}"):
        start = _ts_opener(toks, pos)
        if start is None:
            return None
        while start > 0 and toks[start - 1][0] == "word" \
                and toks[start - 1][1].lower() not in _TS_KEYWORDS:
            start -= 1  # a function name, possibly two words (`unique count`)
    elif kind in _TS_OPERANDS or (kind == "word" and tok.lower() not in _TS_KEYWORDS):
        start = pos
    else:
        return None
    while start > 0 and toks[start - 1][0] == "op" and toks[start - 1][1] in ("-", "+"):
        if start >= 2 and _ts_is_operand_end(toks[start - 2]):
            break  # a binary operator, not a sign
        start -= 1
    return start


def _ts_product_left_of(toks: list, j: int) -> int | None:
    """For the ``/`` at ``j``: the start of its left operand chain when that chain holds a
    ``*`` (the product ThoughtSpot would split), else None."""
    pos, star, start = j - 1, False, None
    while pos >= 0:
        start = _ts_primary_start(toks, pos)
        if start is None:
            return None
        prev = toks[start - 1] if start > 0 else None
        if prev is None or prev[0] != "op" or prev[1] not in ("*", "/"):
            break
        star = star or prev[1] == "*"
        pos = start - 2
    return start if star else None


def ts_bracket_product_divisions(text: str) -> str:
    """Bracket every product that is the left operand of a division —
    ``a * b / c`` → ``( a * b ) / c`` — so ThoughtSpot evaluates it left to right, as
    every source dialect does. Exact algebra either way; only the precision changes
    (``[n] * 4 / 3`` was 3.999999). Anything the scanner cannot read is left as is."""
    for _ in range(200):
        toks = [t for t in _ts_scan(text) if t[0] not in ("ws", "comment")]
        edit = next(((toks[start][2], toks[j - 1][3]) for j in range(1, len(toks))
                     if toks[j][:2] == ("op", "/")
                     for start in [_ts_product_left_of(toks, j)] if start is not None), None)
        if edit is None:
            return text
        a, b = edit
        text = text[:a] + "( " + text[a:b] + " )" + text[b:]
    return text


def ts_finalize_formula(text: str) -> str:
    """The last step of every text translator: string literals into the form ThoughtSpot
    reads back exactly, then products under a division bracketed (BL-365). Idempotent."""
    if not text:
        return text
    return ts_bracket_product_divisions(ts_finalize_string_literals(text))


def ts_literal_token_text(token: str) -> str:
    """The text ThoughtSpot reads from one of its own string-literal tokens: in a
    single-quoted literal a doubled quote stays two quotes and ``\\x`` is ``x``; in a
    double-quoted literal ``\\x`` is ``x``."""
    return re.sub(r"\\(.)", r"\1", token[1:-1], flags=re.DOTALL)


# ---------------------------------------------------------------------------
# Trigonometry (BL-364)
# ---------------------------------------------------------------------------
#
# ThoughtSpot's sin / cos / tan / asin / acos / atan take and return RADIANS (live,
# se-thoughtspot 2026-10-07: `sin ( 30 )` compiles to SIN(30) = -0.988), exactly as SQL,
# Tableau and Excel do — so they map 1:1. PI is the warehouse's own PI() (a full double; a
# 15-digit literal divided by another literal was fixed-point at scale 6, BL-365), and
# DEGREES / RADIANS are that arithmetic with the product bracketed: native, so they work
# over an aggregate too. ATAN2 has no catalogued native form: a pass-through, (y, x) in
# both SQL dialects.

TS_PI = 'sql_double_op ( "PI()" )'
_TS_TRIG_NATIVE = {"SIN": "sin", "COS": "cos", "TAN": "tan",
                   "ASIN": "asin", "ACOS": "acos", "ATAN": "atan"}
#: Every ThoughtSpot name ``sql_trig_to_ts`` can emit, per source function.
SQL_TRIG_EMITS = {**{k: (v,) for k, v in _TS_TRIG_NATIVE.items()},
                  "COT": ("tan",), "DEGREES": ("sql_double_op",),
                  "RADIANS": ("sql_double_op",), "PI": ("sql_double_op",),
                  "ATAN2": ("sql_double_op",)}


def sql_trig_to_ts(name: str, args: list[str]) -> str:
    """SQL ``SIN`` … ``ATAN2``, ``COT``, ``DEGREES``, ``RADIANS``, ``PI`` → ThoughtSpot."""
    want = 0 if name == "PI" else 2 if name == "ATAN2" else 1
    if len(args) != want:
        raise UntranslatableError(f"{name} expects {want} argument(s), got {len(args)}")
    if name in _TS_TRIG_NATIVE:
        return f"{_TS_TRIG_NATIVE[name]} ( {args[0]} )"
    if name == "COT":
        return f"( 1 / tan ( {args[0]} ) )"
    if name == "DEGREES":
        return f"( ( {args[0]} * 180 ) / {TS_PI} )"
    if name == "RADIANS":
        return f"( ( {args[0]} * {TS_PI} ) / 180 )"
    if name == "PI":
        return TS_PI
    return sql_passthrough_call("sql_double_op", "ATAN2", args)


# ---------------------------------------------------------------------------
# SQL source string literals (BL-365)
# ---------------------------------------------------------------------------
#
# Both warehouses read backslash escapes in a single-quoted literal (Databricks live
# 2026-10-07: 'it\'s' = it's, 'a\\b' = a\b, 'a\qb' = aqb). Snowflake also reads a doubled
# quote as one quote; Databricks reads 'it''s' as two ADJACENT literals, concatenated:
# its (live). The tokenizers decode a literal to its text with ``sql_literal_text`` and
# carry it as ``sql_std_literal`` (quote doubled, backslash literal) until
# ``ts_finalize_formula`` prints it.

SQL_STRING_TOKEN_SNOWFLAKE = r"'(?:[^'\\]|''|\\.)*'"
SQL_STRING_TOKEN_DATABRICKS = r"'(?:[^'\\]|\\.)*'"
_SQL_SAFE_ESCAPES = {"'": "'", '"': '"', "\\": "\\"}


def sql_literal_text(token: str, dialect: str) -> str:
    """The text a Snowflake or Databricks single-quoted literal token stands for. An escape
    other than ``\\'``, ``\\"`` and ``\\\\`` (a newline, a tab, a LIKE escape) has no
    ThoughtSpot literal proven to carry it, so it is refused rather than guessed."""
    inner = token[1:-1]
    out: list[str] = []
    i = 0
    while i < len(inner):
        ch = inner[i]
        if ch == "\\" and i + 1 < len(inner):
            nxt = inner[i + 1]
            if nxt not in _SQL_SAFE_ESCAPES:
                raise UntranslatableError(
                    f"string literal {token}: the escape \\{nxt} has no verified ThoughtSpot "
                    "literal form")
            out.append(_SQL_SAFE_ESCAPES[nxt])
            i += 2
            continue
        if ch == "'" and dialect == "snowflake":  # '' inside the token
            out.append("'")
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)
