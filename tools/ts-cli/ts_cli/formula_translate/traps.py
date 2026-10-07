"""Traps: the semantic differences a translated formula carries (spec §6 item 3).

Each trap is derived from the source text and the translated output — only the ones that
fired are returned. The wording is the user-facing line. Live evidence is cited where a
trap rests on it:

- BL-331 (2026-10-06): ``round``'s 2nd argument is an increment, not a digit count.
- OI-2 (2026-10-06): ``day_number_of_week`` is fixed 1 = Monday; ``start_of_week`` compiles
  to ``DATE_TRUNC(week, d)``. Both assume a Monday week start (the Gregorian default).
- OI-3 (2026-10-06): ``diff_months`` / ``diff_years`` count calendar boundaries crossed.
- OI-4 (2026-10-06): ``=``, ``contains`` and ``strpos`` on strings are case-insensitive
  (BL-333). OI-2's week-start consequences are BL-334.
- BL-358 (formula fidelity M2, 2026-10-07): ThoughtSpot's queries over a Databricks
  connection run non-ANSI — BIGINT overflow wraps, an out-of-range cast clamps, a bad
  string cast is NULL — where an ANSI Databricks source raises.

Also hosts the two output repairs that are about ThoughtSpot, not about any one source
language: ``COUNT(*)`` → count of a key column, and a guard against SQL keywords a
translator left behind (``count(DISTINCT x)`` mid-expression, which no ThoughtSpot
function accepts).
"""
from __future__ import annotations

import re
from typing import Optional

from ts_cli.formula_translate.context import ColumnContext
from ts_cli.formula_translate.catalog import is_known
from ts_cli.formula_translate.refs import split_literals

# Dialects whose string comparison is case-sensitive by default (OI-4 applies).
CASE_SENSITIVE_DIALECTS = {"tableau", "snowflake", "databricks"}

_ROUND_SRC = re.compile(r"\bround\s*\(", re.I)
_ROUND_OUT = re.compile(r"\bround\s*\(")
_DISTINCT_SRC = re.compile(r"\b(countd|distinctcount|count\s*\(\s*distinct|countdistinct)\b", re.I)
_UNIQUE_OUT = re.compile(r"\bunique count\s*\(")
_DIFF_OUT = re.compile(r"\bdiff_(days|months|years|weeks|quarters|hours|minutes|seconds|time)\s*\(")
_DAYS_OVER_7 = re.compile(r"\bdiff_days\s*\([^()]*(?:\([^()]*\)[^()]*)*\)\s*/\s*7\b")
_DIFF_MY_OUT = re.compile(r"\bdiff_(months|years|quarters)\s*\(")
_DIFF_WEEKS_OUT = re.compile(r"\bdiff_weeks\s*\(")
_WEEK_OUT = re.compile(
    r"\b(start_of_week|day_number_of_week|week_number_of_year|day_of_week|"
    r"week_number_of_month|week_number_of_quarter)\s*\(")
_STRCMP_OUT = re.compile(
    r"(\bcontains\s*\(|\bstrpos\s*\(|\bbegins_with\s*\(|\bends_with\s*\(|"
    r"(?:=|!=|<>)\s*'|'\s*(?:=|!=|<>))")
_PASSTHROUGH_OUT = re.compile(r"\bsql_(\w+?)_op\s*\(")
_COUNT_STAR = re.compile(r"\bcount\s*\(\s*(?:\*|1)\s*\)", re.I)
_SQL_LEFTOVER = re.compile(r"\b(DISTINCT|OVER|PARTITION\s+BY|QUALIFY|WITHIN\s+GROUP)\b", re.I)
_CALL = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_CALL_KEYWORDS = {"if", "and", "or", "not", "in", "then", "else"}
_SQL_KEYWORD_REF = re.compile(
    r"\[[^\]]*::\s*(ILIKE|RLIKE|LIKE|NOT|TOTAL|REGEXP|SIMILAR|ESCAPE|OVER|DISTINCT|IS|NULL|"
    r"AND|OR|IN|BETWEEN|CASE|WHEN|THEN|ELSE|END|EXISTS|ANY|ALL)\s*\]", re.I)
_BARE_TOTAL = re.compile(r"\bTOTAL\b", re.I)
_DOUBLE_EQ = re.compile(r"==")
_PLUS_STRING = re.compile(r"''\s*\+|\+\s*''")
_COLUMN_CMP = re.compile(r"\]\s*(?:=|!=|<>)\s*\[")
_CALENDAR_OUT = re.compile(r"\bstart_of_(month|quarter|year)\s*\(")
_SCALED_CAST_SRC = re.compile(
    r"\b(?:CAST|TRY_CAST)\s*\(.*\bAS\s+(?:DECIMAL|NUMBER|NUMERIC|DEC)\s*\(\s*\d+\s*,\s*[1-9]"
    r"|\bTO_(?:NUMBER|DECIMAL|NUMERIC)\s*\(.*,\s*\d+\s*,\s*[1-9]", re.I | re.S)
_ROUND_AGG_OUT = re.compile(r"\bround\s*\(\s*(?:sum|average|min|max|median|stddev|variance)\s*\(")
_DBX_CAST_SRC = re.compile(r"\bCAST\s*\(|::", re.I)
# An integer literal of 10+ digits beside an arithmetic operator: past INT range, and the
# realistic way a formula reaches BIGINT's limit (M2 dbx-arith-013).
_DBX_BIG_LITERAL = re.compile(r"[-+*]\s*\d{10,}\b|\b\d{10,}\s*[-+*]")


# Trap lines that mean the output does NOT compute what the source computes: a translation
# carrying one is downgraded to APPROXIMATED, never reported as a clean TRANSLATED.
DOWNGRADE_TRAP_PREFIXES = (
    "week difference emitted as diff_days / 7",
    # A case-sensitive source comparison against a literal answers differently for any
    # value that differs only in case (OI-4, BL-333).
    "string comparison is case-INSENSITIVE",
    # An overflow wraps to a wrong number where the ANSI source raises (BL-358).
    "integer overflow wraps",
    # round() on a DOUBLE aggregate is not the warehouse's half-up DECIMAL rounding (#578).
    "rounded cast over an aggregate",
)


def is_downgrade(trap: str) -> bool:
    return trap.startswith(DOWNGRADE_TRAP_PREFIXES)


def _code(expr: str) -> str:
    """``expr`` with string literals blanked to ``''`` and ``[…]`` references to ``[]``, so
    keyword and function checks never fire on a literal or a column name (``[Over Budget]``)."""
    out = "".join("''" if lit else seg for lit, seg in split_literals(expr))
    return re.sub(r"\[[^\[\]]*\]", "[]", out)


def _round_has_increment(code: str) -> bool:
    """True if some ``round (`` call in ``code`` has a second argument."""
    for m in _ROUND_OUT.finditer(code):
        depth, i = 0, m.end() - 1
        while i < len(code):
            ch = code[i]
            if ch in "({":
                depth += 1
            elif ch in ")}":
                depth -= 1
                if depth == 0:
                    break
            elif ch == "," and depth == 1:
                return True
            i += 1
    return False


def repair_count_star(expr: str, ctx: ColumnContext) -> tuple[str, Optional[str]]:
    """``count ( 1 )`` / ``count(*)`` → ``count ( <key> )``. Returns (expr, trap)."""
    if not _COUNT_STAR.search(_code(expr)):
        return expr, None
    key = ctx.key_reference()
    out = "".join(seg if lit else _COUNT_STAR.sub(f"count ( {key} )", seg)
                  for lit, seg in split_literals(expr))
    return out, ("COUNT(*) has no ThoughtSpot form — counted a non-null key column "
                 f"instead ({key}); name the table's primary key if this is a placeholder")


def leftover_sql(expr: str) -> Optional[str]:
    """A SQL keyword no ThoughtSpot formula accepts, left by a translator, or None."""
    m = _SQL_LEFTOVER.search(_code(expr))
    if m:
        return (f"the translator left the SQL keyword {m.group(1).upper()!r} in its output; "
                "no ThoughtSpot formula accepts it, so this needs a manual rewrite")
    return None


def output_guard(expr: str, allow: frozenset = frozenset(), source: str = "") -> Optional[str]:
    """Why ``expr`` cannot be a valid ThoughtSpot formula, or None.

    Checks: a function name outside the formula catalog (``catalog.is_known``; case
    matters — a leftover ``Sum (`` or ``RUNNING_SUM (`` is untranslated source), a reference
    whose column is a SQL keyword (``[TABLE::ILIKE]`` — an operator read as a column), a
    bare ``TOTAL``, ``==``, ``+`` beside a string literal (ThoughtSpot concatenates with
    ``concat``), and the leftover SQL keywords of ``leftover_sql``.
    """
    code = _code(expr)
    for m in _CALL.finditer(code):
        name = m.group(1)
        if name.lower() in _CALL_KEYWORDS and name == name.lower():
            continue
        if name == "unique" and re.match(r"\s+count\s*\(", code[m.end(1):]):
            continue
        if name == "count" and code[:m.start()].rstrip().endswith("unique"):
            continue
        if not (is_known(name) or name in allow):
            return (f"the output calls {name!r}, which is not in the ThoughtSpot formula "
                    "catalog (thoughtspot-formula-patterns.md) — not emitted as a translation")
    src_code = _code(source)
    for m in _SQL_KEYWORD_REF.finditer(expr):
        # Only when the SOURCE has it bare: a bracketed column named [End] is a real column.
        if re.search(r"\b" + re.escape(m.group(1)) + r"\b", src_code, re.I):
            return (f"the SQL operator {m.group(1).upper()} was read as a column "
                    f"({m.group(0)}); the translator does not support it")
    checks = ((_BARE_TOTAL, "a bare TOTAL keyword survived (Qlik/SQL TOTAL has no inline "
                            "ThoughtSpot form; use group_aggregate)"),
              (_DOUBLE_EQ, "'==' is not a ThoughtSpot operator (use '=')"),
              (_PLUS_STRING, "'+' next to a string literal: ThoughtSpot joins strings with "
                             "concat ( a , b ), not '+'"))
    for pat, why in checks:
        if pat.search(code):
            return why
    return leftover_sql(expr)


# Output-only traps: (pattern on the literal-blanked output, line).
_OUTPUT_TRAPS = (
    (_DIFF_OUT, "diff_*(end, start): ThoughtSpot takes the LATER date first"),
    (_DAYS_OVER_7, "week difference emitted as diff_days / 7 — a fractional count of "
                   "7-day spans, not the number of week boundaries crossed that a "
                   "DATEDIFF('week') source returns; wrap in floor() or rewrite if it matters"),
    (_DIFF_MY_OUT, "diff_months / diff_years count calendar boundaries crossed "
                   "(Jan 31 → Feb 1 = 1 month), not complete periods (OI-3)"),
    (_DIFF_WEEKS_OUT, "diff_weeks counts week boundaries with a FIXED Monday week start "
                      "(epoch day arithmetic in its compiled SQL, 2026-10-06); a SQL "
                      "DATEDIFF(week) follows the warehouse's week start (Snowflake "
                      "WEEK_START), so they agree only under a Monday start (WEEK_START 0 "
                      "or 1)"),
    (_WEEK_OUT,"assumes a Monday week start; diverges if the Model's calendar "
                "starts on another day (day_number_of_week is fixed 1 = Monday; "
                "start_of_week follows the warehouse's DATE_TRUNC(week)) — OI-2, BL-334"),
)
_CASE_LITERAL = ("string comparison is case-INSENSITIVE in ThoughtSpot (=, contains, "
                 "strpos — OI-4, BL-333); if the source compared case-sensitively, use "
                 "sql_bool_op ( \"{0} = {1}\" , … ) instead")
_CASE_COLUMNS = ("if these are text columns: string comparison is case-INSENSITIVE in "
                 "ThoughtSpot (OI-4, BL-333); for a case-sensitive match use "
                 "sql_bool_op ( \"{0} = {1}\" , … )")


def _round_trap(dialect: str, source: str, code: str) -> list[str]:
    if dialect == "thoughtspot" or not _ROUND_SRC.search(source) or not _round_has_increment(code):
        return []
    if dialect == "qlik":
        return ["round: Qlik's 2nd argument is already a step (increment), so it is kept "
                "as-is — ThoughtSpot round(x, 0.01) is 2 decimals"]
    return ["round: the source's decimal-place count became an increment "
            "(2 places → 0.01, 0 → 1; round(x, 0) is NULL in ThoughtSpot) — BL-331"]


def _case_traps(dialect: str, output: str) -> list[str]:
    if dialect not in CASE_SENSITIVE_DIALECTS:
        return []
    if _STRCMP_OUT.search(output):
        return [_CASE_LITERAL]
    return [_CASE_COLUMNS] if _COLUMN_CMP.search(output) else []


_DBX_OVERFLOW = ("integer overflow wraps in ThoughtSpot over Databricks: its queries run "
                 "non-ANSI (BL-358), so BIGINT arithmetic past ±9.22e18 returns a wrapped, "
                 "wrong number where an ANSI Databricks source raises ARITHMETIC_OVERFLOW")
_DBX_CAST = ("CAST over Databricks runs non-ANSI in ThoughtSpot (BL-358): a value that does "
             "not convert gives NULL, and an out-of-range integer cast clamps "
             "(2147483647), where an ANSI Databricks source raises")


_CALENDAR = ("start_of_month / start_of_quarter / start_of_year follow the Model's calendar: "
             "this assumes the Model's default Gregorian calendar — a fiscal calendar shifts "
             "them, where the SQL source's truncation is always Gregorian")
_ROUNDED_CAST = ("rounded cast over an aggregate: a DECIMAL/NUMBER(p, s) cast of a total became "
                 "round ( total , 10^-s ), which is exact on a DECIMAL total but not on a DOUBLE "
                 "one at a half (40.955 rounds to 40.95 in DOUBLE, 40.96 as the warehouse's "
                 "DECIMAL) — cast inside the aggregate, or validate the values")


def _sql_traps(dialect: str, source: str, code: str) -> list[str]:
    """Snowflake / Databricks only: the calendar note (#578 review) and the rounded-cast
    downgrade."""
    if dialect not in ("snowflake", "databricks"):
        return []
    out = [_CALENDAR] if _CALENDAR_OUT.search(code) else []
    if _ROUND_AGG_OUT.search(code) and _SCALED_CAST_SRC.search(_code(source)):
        out.append(_ROUNDED_CAST)
    return out


def _databricks_traps(dialect: str, source: str) -> list[str]:
    if dialect != "databricks":
        return []
    src = _code(source)
    out = [_DBX_OVERFLOW] if _DBX_BIG_LITERAL.search(src) else []
    return out + ([_DBX_CAST] if _DBX_CAST_SRC.search(src) else [])


def detect_traps(dialect: str, source: str, output: str) -> list[str]:
    """Trap lines that apply to this (source → output) pair."""
    code = _code(output)
    traps = _round_trap(dialect, source, code)
    if _DISTINCT_SRC.search(source) and _UNIQUE_OUT.search(code):
        traps.append("distinct count → `unique count` (a space, not an underscore; "
                     "`unique_count` and `count_distinct` are rejected)")
    traps.extend(line for pat, line in _OUTPUT_TRAPS if pat.search(code))
    traps.extend(_case_traps(dialect, output))
    traps.extend(_databricks_traps(dialect, source))
    traps.extend(_sql_traps(dialect, source, code))
    m = _PASSTHROUGH_OUT.search(code)
    if m:
        syntax = "Databricks" if dialect == "databricks" else "Snowflake"
        traps.append(f"passthrough (sql_{m.group(1)}_op): the SQL runs in the warehouse "
                     f"({syntax} syntax assumed), ThoughtSpot cannot plan around it, and the "
                     "variant fixes the column's type and role (Ossie map E7)")
    return traps
