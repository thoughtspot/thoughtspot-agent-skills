"""Dialect detection — a scored heuristic (spec §4). It never routes silently.

``detect(expr)`` scores every candidate language from textual signals and returns them
ranked, with ``ambiguous`` set when the caller MUST ask rather than confirm:

- the top two candidates are within ``MARGIN`` points (includes a 0-0 tie: no signal);
- the best candidate rests only on weak signals (score below ``MIN_CONFIDENT_SCORE``);
- the best is Snowflake or Databricks and no signal unique to one of them fired;
- the best candidate is in a must-ask family — Excel / Google Sheets / Omni table calc
  share one grammar, and LookML / Omni share ``${view.field}`` — unless a signal unique
  to the best candidate fired (today: a Google Sheets-only function, which settles
  Sheets; see ``SHEETS_ONLY``).

``ask`` lists only the tied candidates (spec §4: "the question lists only the tied
candidates"). Weights: 3 = a construct only one language has, 2 = strong, 1 = weak.
"""
from __future__ import annotations

import re
from typing import Any

MARGIN = 1

TRANSLATOR_BACKED = {"tableau", "dax", "qlik", "sisense", "snowflake", "databricks", "excel",
                     "google_sheets"}
EXCEL_MAP = "docs/function-maps/ts-excel-function-mapping.md"
SHEETS_MAP = "docs/function-maps/ts-sheets-function-mapping.md"
# Excel and Google Sheets are translator-backed (ts_cli/excel/); their maps stay listed as
# the fallback for a construct the translator returns NEEDS_REVIEW.
MAP_BACKED = {
    "excel": EXCEL_MAP,
    # The Sheets map is a DELTA on the Excel map (BL-338): read it first; a name it does
    # not row takes its Excel row (a ‡ compatibility alias takes its successor's) — its E1.
    "google_sheets": SHEETS_MAP,
    "omni_table_calc": "docs/function-maps/ts-omni-function-mapping.md",
    "omni": "docs/function-maps/ts-omni-function-mapping.md",
    "sigma": "docs/function-maps/ts-sigma-function-mapping.md",
}
# A map-backed dialect whose map is a delta: names it does not row fall back to this map.
MAP_FALLBACK = {"google_sheets": EXCEL_MAP}

# The functions Google Sheets has and Excel does not — the Sheets map's rowed names minus
# the 17 shared names its reconciliation lists (test_formula_translate checks this set
# against the map, so the two cannot drift). Shared names such as REGEXEXTRACT and
# REGEXREPLACE (Excel 365 has both) are deliberately absent: they are not Sheets evidence.
SHEETS_ONLY = frozenset({
    "ADD", "MINUS", "MULTIPLY", "DIVIDE", "POW", "UMINUS", "UPLUS", "UNARY_PERCENT",
    "EQ", "NE", "GT", "GTE", "LT", "LTE", "ISBETWEEN",
    "AVERAGE.WEIGHTED", "COUNTUNIQUE", "COUNTUNIQUEIFS", "MARGINOFERROR",
    "JOIN", "REGEXMATCH", "SPLIT",
    "EPOCHTODATE", "ISDATE", "ISEMAIL", "ISURL",
    "TO_DATE", "TO_DOLLARS", "TO_PERCENT", "TO_PURE_NUMBER", "TO_TEXT",
    "ARRAY_CONSTRAIN", "ARRAYFORMULA", "CONTINUE", "FLATTEN", "SORTN", "QUERY",
    "AI", "GOOGLEFINANCE", "GOOGLETRANSLATE",
    "IMPORTDATA", "IMPORTFEED", "IMPORTHTML", "IMPORTRANGE", "IMPORTXML", "SPARKLINE",
})
# Sheets-only names that another supported dialect also spells as a function or keyword:
# TO_DATE / SPLIT / FLATTEN / POW (Snowflake, Databricks; SPLIT also Tableau, POW also
# Qlik), DIVIDE (DAX), JOIN / MINUS (SQL keywords before a subquery), ISDATE (Tableau).
# These count for Sheets ONLY beside spreadsheet context (a leading ``=``, an A1 or
# whole-column reference, ``Sheet!ref``); alone they are no evidence at all.
SHEETS_COLLIDING = frozenset({"TO_DATE", "SPLIT", "FLATTEN", "POW", "DIVIDE", "JOIN",
                              "MINUS", "ISDATE"})
SHEETS_STRONG_LABEL = "Sheets-only fn"
SHEETS_CONTEXT_LABEL = "Sheets-only fn (spreadsheet context)"
_SPREADSHEET_CONTEXT = {"leading =", "A1 cell / range reference", "whole-column range",
                        "Sheet!ref"}


def _fn_pattern(names: frozenset[str]) -> "re.Pattern[str]":
    alts = "|".join(re.escape(n) for n in sorted(names, key=lambda n: (-len(n), n)))
    return re.compile(rf"(?<![\w.])(?:{alts})\s*\(", re.I)


_SHEETS_STRONG_RE = _fn_pattern(SHEETS_ONLY - SHEETS_COLLIDING)
_SHEETS_COLLIDING_RE = _fn_pattern(SHEETS_COLLIDING)
# Families whose members cannot be told apart from the text alone.
MUST_ASK_FAMILIES = [
    {"excel", "google_sheets", "omni_table_calc"},
    {"lookml", "omni"},
]
# Snowflake vs Databricks is a must-ask pair UNLESS a signal only one of them has fired.
SQL_PAIR = {"snowflake", "databricks"}
SQL_UNIQUE = {"Snowflake-only fn", "date_add(", "2-arg datediff(",
              "backtick identifier", "MEASURE(", "Spark SQL fn"}
# A pick resting only on weak (1-point) signals is asked, never confirmed.
MIN_CONFIDENT_SCORE = 2

_I = re.I
SIGNALS: list[tuple[str, int, str, "re.Pattern[str]"]] = [
    # --- Tableau
    ("tableau", 3, "LOD {FIXED|INCLUDE|EXCLUDE", re.compile(r"\{\s*(FIXED|INCLUDE|EXCLUDE)\b", _I)),
    ("tableau", 3, "ATTR(", re.compile(r"\bATTR\s*\(", _I)),
    ("tableau", 3, "COUNTD(", re.compile(r"\bCOUNTD\s*\(", _I)),
    ("tableau", 3, "ZN(", re.compile(r"\bZN\s*\(")),
    ("tableau", 3, "single-quoted date part", re.compile(
        r"\bDATE(DIFF|TRUNC|PART|ADD|NAME)\s*\(\s*'(year|quarter|month|week|day|hour|minute|second)'", _I)),
    ("tableau", 3, "IF … THEN … END", re.compile(r"\bIF\b[\s\S]*\bTHEN\b[\s\S]*\bEND\b", _I)),
    ("tableau", 2, "ELSEIF", re.compile(r"\bELSEIF\b", _I)),
    ("tableau", 3, "[Parameters].", re.compile(r"\[Parameters\]\.", _I)),
    ("tableau", 3, "table calc", re.compile(r"\b(WINDOW_\w+|RUNNING_\w+)\s*\(|\bINDEX\s*\(\s*\)|\bSIZE\s*\(\s*\)", _I)),
    ("tableau", 1, "IIF(", re.compile(r"\bIIF\s*\(", _I)),
    # Tableau accepts double-quoted date parts too; its functions are upper case, Sigma's
    # are CamelCase, so the case-sensitive spelling separates the two.
    ("tableau", 3, "double-quoted date part (upper-case fn)", re.compile(
        r"\bDATE(DIFF|TRUNC|PART|ADD|NAME)\s*\(\s*\"(year|quarter|month|week|day|hour|minute|second|weekday)\"")),
    # --- DAX
    ("dax", 3, "CALCULATE(", re.compile(r"\bCALCULATE(TABLE)?\s*\(", _I)),
    ("dax", 3, "'Table'[Column]", re.compile(r"'[^']+'\s*\[[^\]]+\]")),
    ("dax", 2, "Table[Column]", re.compile(r"\b[A-Za-z_]\w*\[[^\]@#]+\]")),
    ("dax", 3, "VAR … RETURN", re.compile(r"\bVAR\b[\s\S]*\bRETURN\b", _I)),
    ("dax", 3, "SELECTEDVALUE(", re.compile(r"\bSELECTEDVALUE\s*\(", _I)),
    ("dax", 3, "DIVIDE(", re.compile(r"\bDIVIDE\s*\(", _I)),
    ("dax", 3, "DISTINCTCOUNT(", re.compile(r"\bDISTINCTCOUNT\s*\(", _I)),
    ("dax", 3, "DAX iterator / filter fn", re.compile(
        r"\b(SUMX|AVERAGEX|COUNTROWS|RELATED|ALLEXCEPT|SAMEPERIODLASTYEAR|TOTALYTD|DATESYTD|USERELATIONSHIP)\s*\(", _I)),
    ("dax", 1, "&& / ||", re.compile(r"&&")),
    # --- Qlik
    ("qlik", 3, "set analysis {<…>}", re.compile(r"\{\s*<[^>]*>\s*\}|\{\s*\$\s*<|\{\s*1\s*\}")),
    ("qlik", 3, "$(var)", re.compile(r"\$\(\w")),
    ("qlik", 3, "Aggr(", re.compile(r"\bAggr\s*\(", _I)),
    ("qlik", 3, "Only(", re.compile(r"\bOnly\s*\(", _I)),
    ("qlik", 3, "Qlik-only fn", re.compile(
        r"\b(RangeSum|ApplyMap|SubField|FirstSortedValue|Num#|Date#|Peek|Above|Below)\s*\(", _I)),
    ("qlik", 1, "Count(DISTINCT", re.compile(r"\bCount\s*\(\s*DISTINCT\b", _I)),
    # --- Sisense
    ("sisense", 3, "Sisense-only fn", re.compile(
        r"\b(PASTYEAR|PASTMONTH|PASTQUARTER|YTDSUM|MTDSUM|QTDSUM|RSUM|RAVG|CONTRIBUTION|DDIFF|MDIFF|YDIFF|PREV|NEXT|GROWTH)\s*\(", _I)),
    ("sisense", 1, "lowercase [key] placeholder", re.compile(r"\[[a-z][a-z0-9_]{0,15}\]")),
    # --- Excel / Sheets / Omni table calc (one grammar)
    ("excel", 3, "leading =", re.compile(r"^\s*=")),
    ("excel", 3, "A1 cell / range reference", re.compile(r"(?<![\w\[])\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?(?![\w\]])(?!\s*\()")),
    ("excel", 3, "whole-column range", re.compile(r"(?<![\w\[])[A-Z]{1,3}:[A-Z]{1,3}(?![\w\]])")),
    ("excel", 3, "Sheet!ref", re.compile(r"\w+!\$?[A-Z]{1,3}\$?\d+")),
    ("excel", 3, "[@Column] structured ref", re.compile(r"\[@[^\]]+\]")),
    ("excel", 2, "Excel-named fn", re.compile(
        r"\b(SUMIFS?|COUNTIFS?|AVERAGEIFS?|XLOOKUP|VLOOKUP|HLOOKUP|IFERROR|TEXTJOIN|DATEDIF|EOMONTH|NETWORKDAYS|SUMPRODUCT)\s*\(", _I)),
    # --- Sigma
    ("sigma", 3, "double-quoted date unit (CamelCase fn)", re.compile(
        r"\bDate(Diff|Trunc|Add|Part)\s*\(\s*\"(year|quarter|month|week|day|hour|minute|second)\"")),
    ("sigma", 1, "[Table/Column]", re.compile(r"\[[^\]/\[]+/[^\]\[]+\]")),
    ("sigma", 1, "Sigma CamelCase fn", re.compile(
        r"\b(CountDistinct|CumulativeSum|MovingAvg|RowNumber|SumIf|CountIf|DateFormat|IsNull)\s*\(")),
    # --- generic shapes several languages share (weak; they produce ties, by design)
    *[(d, 1, "[Field] reference", re.compile(r"(?<![\w'\]])\[[^\]\[/@:.]+\](?!\s*\.)"))
      for d in ("tableau", "dax", "qlik", "sisense", "sigma")],
    *[(d, 1, "bare identifier argument", re.compile(r"\b[A-Za-z_]\w*\s*\(\s*[A-Za-z_]\w*\s*[,)]"))
      for d in ("snowflake", "databricks", "qlik")],
    ("excel", 2, "Table[Column] structured ref", re.compile(r"\b[A-Za-z_]\w*\[[^\]@#]+\]")),
    # --- LookML / Omni modelling layer
    ("lookml", 3, "${view.field}", re.compile(r"\$\{[\w.]+\}")),
    ("omni", 3, "${view.field}", re.compile(r"\$\{[\w.]+\}")),
    # --- Snowflake / Databricks SQL. Databricks also has IFF, ::, QUALIFY and
    # DATEDIFF(unit, …) (docs.databricks.com, checked 2026-10-06), so those are SHARED
    # signals; only the dialect-unique ones below settle the pair (see SQL_UNIQUE).
    *[(d, 2, label, pat) for d in ("snowflake", "databricks") for label, pat in (
        ("CASE WHEN", re.compile(r"\bCASE\s+WHEN\b", _I)),
        ("IFF(", re.compile(r"\bIFF\s*\(", _I)),
        (":: cast", re.compile(r"(?<!:)::\s*[A-Za-z]\w*")),
        ("QUALIFY", re.compile(r"\bQUALIFY\b", _I)),
        ("unquoted date part", re.compile(
            r"\bDATE(ADD|DIFF)\s*\(\s*(day|month|year|week|quarter|hour|minute|second)s?\s*,", _I)),
        ("COUNT(DISTINCT", re.compile(r"\bCOUNT\s*\(\s*DISTINCT\b", _I)),
    )],
    ("snowflake", 3, "Snowflake-only fn", re.compile(
        r"\b(DIV0|DIV0NULL|TO_VARCHAR|TRY_TO_\w+|ZEROIFNULL|DAYOFWEEKISO|IFNULL2)\s*\(", _I)),
    ("databricks", 3, "date_add(", re.compile(r"\bdate_add\s*\(")),
    # Two-argument datediff(end, start): Snowflake's DATEDIFF always takes a unit first.
    ("databricks", 3, "2-arg datediff(", re.compile(
        r"\bdatediff\s*\(\s*[A-Za-z_`][\w`]*\s*,\s*[A-Za-z_`][\w`]*\s*\)", _I)),
    ("databricks", 3, "backtick identifier", re.compile(r"`[^`]+`")),
    ("databricks", 3, "MEASURE(", re.compile(r"\bMEASURE\s*\(", _I)),
    ("databricks", 3, "Spark SQL fn", re.compile(
        r"\b(date_format|try_divide|collect_list|array_contains|get_json_object)\s*\(")),
]

ALL_DIALECTS = sorted({s[0] for s in SIGNALS} | {"google_sheets", "omni_table_calc"})


def _score(text: str) -> tuple[dict[str, int], dict[str, list[str]]]:
    scores: dict[str, int] = {d: 0 for d in ALL_DIALECTS}
    signals: dict[str, list[str]] = {d: [] for d in ALL_DIALECTS}
    for dialect, weight, label, pat in SIGNALS:
        if pat.search(text):
            scores[dialect] += weight
            signals[dialect].append(label)
    # Sheets and Omni table calcs share Excel's grammar: same evidence, same score.
    for twin in ("google_sheets", "omni_table_calc"):
        scores[twin] = scores["excel"]
        signals[twin] = list(signals["excel"])
    # ...plus what only Sheets has. A colliding name counts only in spreadsheet context.
    if _SHEETS_STRONG_RE.search(text):
        scores["google_sheets"] += 3
        signals["google_sheets"].append(SHEETS_STRONG_LABEL)
    if _SPREADSHEET_CONTEXT & set(signals["excel"]) and _SHEETS_COLLIDING_RE.search(text):
        scores["google_sheets"] += 3
        signals["google_sheets"].append(SHEETS_CONTEXT_LABEL)
    return scores, signals


def _backing(d: str) -> dict[str, Any]:
    if d in TRANSLATOR_BACKED:
        out: dict[str, Any] = {"backing": "translator"}
        if d in MAP_BACKED:  # Excel / Sheets: the map is the NEEDS_REVIEW fallback
            out["map"] = MAP_BACKED[d]
            if d in MAP_FALLBACK:
                out["fallback_map"] = MAP_FALLBACK[d]
        return out
    if d in MAP_BACKED:
        out = {"backing": "map", "map": MAP_BACKED[d]}
        if d in MAP_FALLBACK:
            out["fallback_map"] = MAP_FALLBACK[d]
        return out
    return {"backing": "none"}


def _tie(ranked: list[str], scores: dict[str, int],
         signals: dict[str, list[str]]) -> tuple[bool, list[str], Any]:
    """(ambiguous, the candidates to ask about, the top guess or None)."""
    top = scores[ranked[0]]
    tied = [d for d in ranked if scores[d] > 0 and scores[d] >= top - MARGIN]
    best = ranked[0] if top > 0 else None
    ambiguous = best is None or len(tied) > 1 or top < MIN_CONFIDENT_SCORE
    if best in SQL_PAIR and not (SQL_UNIQUE & set(signals[best])):
        ambiguous = True
        tied = sorted(set(tied) | SQL_PAIR, key=lambda d: (-scores[d], d))
    sheets_settled = best == "google_sheets" and bool(
        {SHEETS_STRONG_LABEL, SHEETS_CONTEXT_LABEL} & set(signals[best]))
    for fam in MUST_ASK_FAMILIES:
        if best in fam and not sheets_settled:
            ambiguous = True
            tied = sorted(set(tied) | fam, key=lambda d: (-scores[d], d))
    return ambiguous, tied, best


def detect(expr: str) -> dict[str, Any]:
    """Rank dialects for ``expr``. See module docstring for the ``ambiguous`` rule."""
    text = expr or ""
    scores, signals = _score(text)
    ranked = sorted(ALL_DIALECTS, key=lambda d: (-scores[d], d))
    ambiguous, tied, best = _tie(ranked, scores, signals)
    candidates = [{"dialect": d, "score": scores[d], "signals": signals[d], **_backing(d)}
                  for d in ranked if scores[d] > 0]
    return {
        "input": text,
        "best": None if ambiguous else best,
        "guess": best,
        "ambiguous": ambiguous,
        "ask": tied if ambiguous else [],
        "candidates": candidates,
    }
