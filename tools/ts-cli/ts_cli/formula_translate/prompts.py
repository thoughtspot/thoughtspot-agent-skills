"""The two questions the skill asks before presenting: column types, and per-row vs KPI.

``needs_types`` — a column whose type is unknown and changes the output. The Excel / Sheets
translator records each one (``excel.forward.Translator.type_needs``) at the rules that already
flag "type unknown"; this module adds a name-based suggestion the user confirms or corrects.

``role_ambiguous`` / ``role_options`` — a ratio over row-level columns has two correct
translations (a per-row value, or a ratio of totals). Only the spreadsheet translators build a
formula at a grain (``excel.measure``), so only they can be ambiguous: every other dialect's
source states its own aggregation (a DAX measure, a SQL metric, a Tableau ``SUM()/SUM()``), and
Tableau's ``--role`` is a clean-up hint, not a grain (a Tableau row-level ratio dragged as a
measure is a sum of per-row ratios in Tableau too).
"""
from __future__ import annotations

import re
from typing import Any, Optional

# Dialects whose --role changes the formula's grain (excel.measure). See the module docstring.
ROLE_GRAIN_DIALECTS = frozenset({"excel", "google_sheets"})

# Why a column's type matters — the rule that recorded it (excel.forward).
TEXT_JOIN = "text join"
CONDITION = "condition"
BLANK_TEST = "blank test"
BLANK_BRANCH = "blank IF branch"
DATE_ARITHMETIC = "date arithmetic"
TYPED_ARGUMENT = "typed argument"   # excel.typecheck: an unknown column in a typed slot

# The name heuristic: (name token, suggested_type, suggested data_type, confidence).
# Matched against the LAST token of the column name (split on _ / space / -), so
# CONTRACT_TERM_MONTHS → MONTHS, MONTH_NAME → NAME, FISCAL_YEAR → YEAR. Anything else: no
# suggestion, confidence "low". A suggestion is a default for the user to confirm, never a
# type the translator applies.
NAME_HEURISTIC: tuple[tuple[str, str, str, str], ...] = (
    ("MONTHS", "number", "INT64", "high"),
    ("DAYS", "number", "INT64", "high"),
    ("WEEKS", "number", "INT64", "high"),
    ("YEARS", "number", "INT64", "high"),
    ("COUNT", "number", "INT64", "high"),
    ("QTY", "number", "INT64", "high"),
    ("QUANTITY", "number", "INT64", "high"),
    ("YEAR", "number", "INT64", "high"),
    ("ID", "number", "INT64", "medium"),        # often a number; sometimes a text code
    ("AMOUNT", "number", "DOUBLE", "high"),
    ("COST", "number", "DOUBLE", "high"),
    ("REVENUE", "number", "DOUBLE", "high"),
    ("PRICE", "number", "DOUBLE", "high"),
    ("DATE", "date", "DATE", "high"),
    ("AT", "date", "DATE_TIME", "medium"),      # CREATED_AT: usually a timestamp
    ("NAME", "text", "VARCHAR", "high"),
    ("LABEL", "text", "VARCHAR", "high"),
    ("BAND", "text", "VARCHAR", "high"),
    ("CODE", "text", "VARCHAR", "medium"),      # sometimes numeric
)
_BY_TOKEN = {tok: (t, dt, conf) for tok, t, dt, conf in NAME_HEURISTIC}


def suggest_type(name: str) -> dict[str, Any]:
    """``{suggested_type, suggested_data_type, confidence}`` from the column name alone."""
    tokens = [t for t in re.split(r"[\s_\-]+", (name or "").strip().upper()) if t]
    hit = _BY_TOKEN.get(tokens[-1]) if tokens else None
    if hit is None:
        return {"suggested_type": None, "suggested_data_type": None, "confidence": "low"}
    t, dt, conf = hit
    return {"suggested_type": t, "suggested_data_type": dt, "confidence": conf}


def _source_name(target: str, ctx) -> str:
    """The name the user typed for ``target`` (what a --columns key is), else the column."""
    for r in ctx.references:
        if r.target == target and r.kind == "column":
            return r.source
    m = re.fullmatch(r"\[(?:[^\]:]*::)?([^\]]+)\]", target)
    return m.group(1) if m else target


def build_needs_types(type_needs: list, ctx) -> list[dict[str, Any]]:
    """One entry per column, in first-seen order: ``{column, target, reason, note,
    suggested_type, suggested_data_type, confidence}``.

    Date arithmetic is listed only when the name suggests a date: its bare output (``a - b``)
    is already right for numbers, the common case, so asking about every subtracted amount is
    noise. Every other rule's bare output is wrong for a number, so those always list."""
    out: dict[str, dict[str, Any]] = {}
    for target, reason, note in type_needs:
        name = _source_name(target, ctx)
        sug = suggest_type(name)
        if reason == DATE_ARITHMETIC and sug["suggested_type"] != "date":
            continue
        entry = out.get(target)
        if entry is None:
            out[target] = {"column": name, "target": target, "reason": reason, "note": note,
                           **sug}
        elif reason not in entry["reason"].split(" and "):
            entry["reason"] += f" and {reason}"
    return list(out.values())


ROLE_MEANINGS = {
    "attribute": ("per row", "one value per row, exactly as the Excel cell computes it; "
                  "use it to label or filter rows — summed in a search it adds up per-row "
                  "ratios, which is not the ratio of the totals"),
    "measure": ("KPI that rolls up", "a ratio of totals, sum ( numerator ) / sum ( "
                "denominator ), correct at any grouping (region, month, total); not the "
                "per-row value on a single row's detail"),
}


def has_ratio(formula: Optional[str]) -> bool:
    """A division whose denominator has a column reference, or a ``safe_divide``."""
    if not formula:
        return False
    try:
        from ts_cli.excel.helpers import from_text
        from ts_cli.excel.measure import _has_ratio

        return _has_ratio(from_text(formula))
    except Exception:  # an unparseable formula: the plain-text reading
        return bool(re.search(r"\bsafe_divide\s*\(|/\s*[\[(]", formula))


def role_option(role: str, result: dict) -> dict[str, Any]:
    label, meaning = ROLE_MEANINGS[role]
    return {"role": role, "flag": f"--role {role}", "label": label, "meaning": meaning,
            "formula": result.get("formula"), "formula_editor": result.get("formula_editor"),
            "status": result.get("status"), "column_type": result.get("role")}
