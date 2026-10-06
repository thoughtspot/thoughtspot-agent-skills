"""Dialect detection — a scored heuristic (spec §4). It never routes silently.

``detect(expr)`` scores every candidate language from textual signals and returns them
ranked, with ``ambiguous`` set when the caller MUST ask rather than confirm:

- the top two candidates are within ``MARGIN`` points (includes a 0-0 tie: no signal);
- the best candidate is in a must-ask family — Excel / Google Sheets / Omni table calc
  share one grammar, and LookML / Omni share ``${view.field}``.

``ask`` lists only the tied candidates (spec §4: "the question lists only the tied
candidates"). Weights: 3 = a construct only one language has, 2 = strong, 1 = weak.
"""
from __future__ import annotations

import re
from typing import Any

MARGIN = 1

TRANSLATOR_BACKED = {"tableau", "dax", "qlik", "sisense", "snowflake", "databricks"}
MAP_BACKED = {
    "excel": "docs/function-maps/ts-excel-function-mapping.md",
    "google_sheets": "docs/function-maps/ts-excel-function-mapping.md",
    "omni_table_calc": "docs/function-maps/ts-omni-function-mapping.md",
    "omni": "docs/function-maps/ts-omni-function-mapping.md",
    "sigma": "docs/function-maps/ts-sigma-function-mapping.md",
}
# Families whose members cannot be told apart from the text alone.
MUST_ASK_FAMILIES = [
    {"excel", "google_sheets", "omni_table_calc"},
    {"lookml", "omni"},
]

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
    ("excel", 3, "A1 cell / range reference", re.compile(r"(?<![\w\[])\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?(?![\w\]])")),
    ("excel", 3, "whole-column range", re.compile(r"(?<![\w\[])[A-Z]{1,3}:[A-Z]{1,3}(?![\w\]])")),
    ("excel", 3, "Sheet!ref", re.compile(r"\w+!\$?[A-Z]{1,3}\$?\d+")),
    ("excel", 3, "[@Column] structured ref", re.compile(r"\[@[^\]]+\]")),
    ("excel", 2, "Excel-named fn", re.compile(
        r"\b(SUMIFS?|COUNTIFS?|AVERAGEIFS?|XLOOKUP|VLOOKUP|HLOOKUP|IFERROR|TEXTJOIN|DATEDIF|EOMONTH|NETWORKDAYS|SUMPRODUCT)\s*\(", _I)),
    # --- Sigma
    ("sigma", 3, "double-quoted date unit", re.compile(
        r"\bDate(Diff|Trunc|Add|Part)\s*\(\s*\"(year|quarter|month|week|day|hour|minute|second)\"", _I)),
    ("sigma", 3, "[Table/Column]", re.compile(r"\[[^\]/\[]+/[^\]\[]+\]")),
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
    # --- Snowflake SQL
    ("snowflake", 2, "CASE WHEN", re.compile(r"\bCASE\s+WHEN\b", _I)),
    ("databricks", 2, "CASE WHEN", re.compile(r"\bCASE\s+WHEN\b", _I)),
    ("snowflake", 3, "IFF(", re.compile(r"\bIFF\s*\(", _I)),
    ("snowflake", 3, ":: cast", re.compile(r"(?<!:)::\s*[A-Za-z]\w*")),
    ("snowflake", 3, "QUALIFY", re.compile(r"\bQUALIFY\b", _I)),
    ("snowflake", 3, "unquoted date part", re.compile(
        r"\bDATE(ADD|DIFF)\s*\(\s*(day|month|year|week|quarter|hour|minute|second)s?\s*,", _I)),
    ("snowflake", 2, "Snowflake fn", re.compile(
        r"\b(ZEROIFNULL|NVL2?|DIV0|TO_VARCHAR|SPLIT_PART|COUNT_IF|TRY_TO_\w+)\s*\(", _I)),
    ("snowflake", 1, "COUNT(DISTINCT", re.compile(r"\bCOUNT\s*\(\s*DISTINCT\b", _I)),
    ("databricks", 1, "COUNT(DISTINCT", re.compile(r"\bCOUNT\s*\(\s*DISTINCT\b", _I)),
    # --- Databricks SQL
    ("databricks", 3, "date_add(", re.compile(r"\bdate_add\s*\(")),
    ("databricks", 3, "backtick identifier", re.compile(r"`[^`]+`")),
    ("databricks", 3, "MEASURE(", re.compile(r"\bMEASURE\s*\(", _I)),
    ("databricks", 2, "Spark SQL fn", re.compile(
        r"\b(date_format|try_divide|collect_list|array_contains|get_json_object|nvl)\s*\(")),
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
    return scores, signals


def _backing(d: str) -> dict[str, Any]:
    if d in TRANSLATOR_BACKED:
        return {"backing": "translator"}
    if d in MAP_BACKED:
        return {"backing": "map", "map": MAP_BACKED[d]}
    return {"backing": "none"}


def _tie(ranked: list[str], scores: dict[str, int]) -> tuple[bool, list[str], Any]:
    """(ambiguous, the candidates to ask about, the top guess or None)."""
    top = scores[ranked[0]]
    tied = [d for d in ranked if scores[d] > 0 and scores[d] >= top - MARGIN]
    best = ranked[0] if top > 0 else None
    ambiguous = best is None or len(tied) > 1
    for fam in MUST_ASK_FAMILIES:
        if best in fam:
            ambiguous = True
            tied = sorted(set(tied) | fam, key=lambda d: (-scores[d], d))
    return ambiguous, tied, best


def detect(expr: str) -> dict[str, Any]:
    """Rank dialects for ``expr``. See module docstring for the ``ambiguous`` rule."""
    text = expr or ""
    scores, signals = _score(text)
    ranked = sorted(ALL_DIALECTS, key=lambda d: (-scores[d], d))
    ambiguous, tied, best = _tie(ranked, scores)
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
