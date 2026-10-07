"""One adapter per translator-backed dialect (spec §3.2).

The adapters WRAP the converters' translators — they never re-implement them (BL-217):
a fix to ``translate_single`` / ``translate_dax`` / ``translate`` / ``translate_jaql`` /
``sv_sql.translate_sql_expr`` / ``mv_sql.translate_sql_expr`` reaches both the converter
skill and ``ts formula translate``.

Each adapter returns a ``RawResult``: the translated text (or None), a normalised status,
and notes. ``translate`` then applies the dialect-independent steps — reference recording,
COUNT(*) repair, leftover-keyword guard, traps, role inference — and builds the §3.1 shape.

Verified signatures (read from the code, 2026-10-06):

| Dialect | Entry point | Returns |
|---|---|---|
| tableau | ``tableau_translate.translate_single(raw, role, scoped_columns, param_map, formula_names, parameter_names, csq_to_table, date_columns)`` | ``(expr, errors[], notes{})`` |
| dax | ``powerbi.functions.translate_dax(dax, home_table, home_cols, date_cols, measure_dax, physical_cols)`` | ``(expr or None, "Migrated"/"Approximated"/"NEEDS REVIEW", note)`` |
| qlik | ``qlik.functions.translate(expr)`` | ``(expr, review_required, reason)`` |
| sisense | ``sisense.functions.translate_jaql(expr, context)`` | ``(expr or None, status, note)`` — same statuses as DAX |
| snowflake | ``sv_sql.translate_sql_expr(sql, resolver)`` | ``str``; raises ``UntranslatableError`` |
| databricks | ``databricks.mv_sql.translate_sql_expr(sql, resolver, agg_hook=None)`` | ``str``; raises ``UntranslatableError`` |
| excel, google_sheets | ``excel.translate.translate_excel(src, ctx, dialect, role)`` | ``ExcelResult(expr, status, notes, traps, role)`` |
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ts_cli.formula_translate.context import PLACEHOLDER_TABLE, ColumnContext
from ts_cli.formula_translate.refs import bracket_refs, qualify_refs, split_literals

TRANSLATED = "TRANSLATED"
APPROXIMATED = "APPROXIMATED"
NEEDS_REVIEW = "NEEDS_REVIEW"

DIALECTS = ("tableau", "dax", "qlik", "sisense", "snowflake", "databricks", "excel",
            "google_sheets", "thoughtspot")
ALIASES = {"powerbi": "dax", "power_bi": "dax", "sf": "snowflake", "dbx": "databricks",
           "ts": "thoughtspot", "xlsx": "excel", "sheets": "google_sheets",
           "gsheets": "google_sheets", "google-sheets": "google_sheets"}

# Where each translator lives and which tests cover it (spec §6 item 5).
TRANSLATOR_INFO = {
    "tableau": ("ts_cli.tableau_translate.translate_single",
                ["tests/test_tableau_translate.py", "tests/test_tableau.py"]),
    "dax": ("ts_cli.powerbi.functions.translate_dax", ["tests/test_powerbi_functions.py"]),
    "qlik": ("ts_cli.qlik.functions.translate", ["tests/test_qlik_functions.py"]),
    "sisense": ("ts_cli.sisense.functions.translate_jaql", ["tests/test_sisense_functions.py"]),
    "snowflake": ("ts_cli.sv_sql.translate_sql_expr", ["tests/test_sv_sql.py"]),
    "databricks": ("ts_cli.databricks.mv_sql.translate_sql_expr",
                   ["tests/test_databricks_sql.py"]),
    "excel": ("ts_cli.excel.translate.translate_excel",
              ["tests/test_excel_translate.py", "tests/test_excel_regression.py"]),
    "google_sheets": ("ts_cli.excel.translate.translate_excel (Sheets delta rules)",
                      ["tests/test_excel_translate.py"]),
    "thoughtspot": (None, []),
}

# The status strings the pipeline translators use → this command's statuses.
_PIPELINE_STATUS = {"Migrated": TRANSLATED, "Approximated": APPROXIMATED,
                    "NEEDS REVIEW": NEEDS_REVIEW}

_SENTINEL = "__FT_TABLE__"


@dataclass
class RawResult:
    expr: Optional[str]
    status: str
    notes: list[str] = field(default_factory=list)
    partial: Optional[str] = None  # what a review-flagged translator emitted, if anything
    traps: list[str] = field(default_factory=list)  # translator-specific trap lines
    role: Optional[str] = None     # MEASURE | ATTRIBUTE when the translator applied an intent
    type_needs: list = field(default_factory=list)  # (target, reason, note) — prompts.py


def normalise_dialect(name: str) -> str:
    d = (name or "").strip().lower()
    d = ALIASES.get(d, d)
    if d not in DIALECTS:
        raise ValueError(f"unknown --from dialect {name!r}; choose one of {', '.join(DIALECTS)}")
    return d


# ---------------------------------------------------------------------------
# Tableau
# ---------------------------------------------------------------------------

_TABLEAU_PARAM = re.compile(r"\[Parameters\]\.\[([^\]]+)\]", re.I)


_TABLEAU_BLOCK_TOK = re.compile(
    r"'(?:[^']|'')*'|\"[^\"]*\"|\[[^\]]*\]|\b(IF|ELSEIF|ELSE|END|CASE)\b", re.I)


def add_missing_else(expr: str) -> tuple[str, bool]:
    """Give every Tableau IF/CASE block without an ELSE an explicit ``ELSE NULL``.

    Tableau returns NULL when no branch matches, and ``else null`` is live-verified in
    ThoughtSpot (tableau-formula-translation.md). Without this, translate_single guesses a
    default from the formula's text (``else 0`` / ``else ''``), which can be the wrong type
    and is never the source's NULL.
    """
    stack: list[bool] = []
    inserts: list[int] = []
    for m in _TABLEAU_BLOCK_TOK.finditer(expr):
        kw = (m.group(1) or "").upper()
        if kw in ("IF", "CASE"):
            stack.append(False)
        elif kw == "ELSE" and stack:
            stack[-1] = True
        elif kw == "END" and stack and not stack.pop():
            inserts.append(m.start())
    for pos in reversed(inserts):
        expr = expr[:pos] + "ELSE NULL " + expr[pos:]
    return expr, bool(inserts)


def adapt_tableau(expr: str, ctx: ColumnContext, role_hint: Optional[str] = None) -> RawResult:
    from ts_cli.tableau_translate import translate_single

    expr, added_else = add_missing_else(expr)

    params = {m.group(1) for m in _TABLEAU_PARAM.finditer(expr)}
    stripped = _TABLEAU_PARAM.sub("", expr)
    names = [r for r in bracket_refs(stripped) if r not in params]
    # translate_single scopes [Col] → [TABLE::Col] itself; give it a sentinel table and
    # let qualify_refs map the sentinel through the recording resolver afterwards.
    scoped = {n: _SENTINEL for n in names}
    date_cols = {n for n in names if n in ctx.date_names()}
    role = role_hint or ("measure" if re.search(
        r"\b(SUM|AVG|COUNTD?|MIN|MAX|MEDIAN|STDEV|VAR|ATTR|WINDOW_\w+|RUNNING_\w+)\s*\(",
        expr, re.I) else "attribute")
    out, errors, notes = translate_single(
        expr, role=role, scoped_columns=scoped, parameter_names=params,
        date_columns=date_cols)
    note_list = [f"tableau: {k} applied" for k in sorted(notes)]
    if added_else:
        note_list.append("IF/CASE without ELSE: Tableau returns NULL, so the translation "
                         "ends `else null`")
    if errors:
        return RawResult(None, NEEDS_REVIEW, note_list + errors, partial=out)
    out = "".join(seg if lit else re.sub(r"\belse NULL\b", "else null", seg)
                  for lit, seg in split_literals(out))
    out = qualify_refs(out, ctx, parameters=params, placeholder_tables={_SENTINEL})
    return RawResult(out, TRANSLATED, note_list)


# ---------------------------------------------------------------------------
# DAX
# ---------------------------------------------------------------------------

_DAX_TABLE_REF = re.compile(r"(?:'[^']+'|[A-Za-z_]\w*)\s*\[[^\]]+\]")
_DAX_BARE_REF = re.compile(r"(?<![\w'\]])\[([^\]]+)\]")


def adapt_dax(expr: str, ctx: ColumnContext) -> RawResult:
    from ts_cli.powerbi.functions import translate_dax

    without_qualified = _DAX_TABLE_REF.sub("", expr)
    home_cols = {m.group(1).strip() for m in _DAX_BARE_REF.finditer(without_qualified)}
    date_cols = set()
    for n in home_cols:
        if n in ctx.date_names():
            date_cols.add(f"{_SENTINEL}::{n}")
    for t in ctx.date_targets():
        date_cols.add(t)
    # translate_dax qualifies Table[Col] → [Table::Col] and bare [Col] → [home::Col]
    # BEFORE its DATE-subtraction rewrite, which therefore looks for "Table::Col".
    for m in re.finditer(r"(?:'([^']+)'|([A-Za-z_]\w*))\s*\[([^\]]+)\]", expr):
        t, c = (m.group(1) or m.group(2)).strip(), m.group(3).strip()
        if c in ctx.date_names():
            date_cols.add(f"{t}::{c}")
    out, status, note = translate_dax(expr, home_table=_SENTINEL, home_cols=home_cols,
                                      date_cols=date_cols)
    notes = [note] if note else []
    mapped = _PIPELINE_STATUS.get(status, NEEDS_REVIEW)
    if mapped == NEEDS_REVIEW or out is None:
        return RawResult(None, NEEDS_REVIEW, notes or ["DAX translator: needs review"])
    out = qualify_refs(out, ctx, placeholder_tables={_SENTINEL})
    return RawResult(out, mapped, notes)


# ---------------------------------------------------------------------------
# Qlik
# ---------------------------------------------------------------------------

def qlik_field_quotes(expr: str) -> str:
    """Qlik ``"Sales Amount"`` is a FIELD name, not a string: rewrite it ``[Sales Amount]``
    (Qlik's other field-quoting form) so neither the translator nor the reference pass
    treats it as a literal. Single-quoted strings are left alone."""
    parts = re.split(r"('(?:[^']|'')*')", expr)
    for i in range(0, len(parts), 2):
        parts[i] = re.sub(r'"([^"]+)"', r"[\1]", parts[i])
    return "".join(parts)


def adapt_qlik(expr: str, ctx: ColumnContext, first_week_day: Optional[int] = None) -> RawResult:
    """``first_week_day``: the app's ``FirstWeekDay`` (0 = Mon … 6 = Sun). A pasted formula
    has no load script, so without it a one-argument ``Weekday()`` is NEEDS_REVIEW (#565)."""
    from ts_cli.qlik.functions import translate

    out, review, reason = translate(qlik_field_quotes(expr), first_week_day=first_week_day)
    if review or not out:
        return RawResult(None, NEEDS_REVIEW, [reason or "Qlik translator: needs review"],
                         partial=out or None)
    return RawResult(qualify_refs(out, ctx, bare_idents=True), TRANSLATED)


# ---------------------------------------------------------------------------
# Sisense
# ---------------------------------------------------------------------------

def synthesise_sisense_context(expr: str) -> dict:
    """Level 0/1: one ``{dim: "[TABLE.key]"}`` fragment per ``[key]`` in ``expr``.

    No ``agg`` is invented: a bare placeholder therefore stays a row-level column, which is
    the honest reading when the JAQL context that would say otherwise is absent.
    """
    return {f"[{k}]": {"dim": f"[{PLACEHOLDER_TABLE}.{k}]"} for k in bracket_refs(expr)}


def adapt_sisense(expr: str, ctx: ColumnContext, context: Optional[dict] = None) -> RawResult:
    from ts_cli.sisense.functions import translate_jaql

    jaql_ctx = context if context else synthesise_sisense_context(expr)
    out, status, note = translate_jaql(expr, jaql_ctx)
    notes = [note] if note else []
    if not context:
        notes.append("sisense: no JAQL context supplied — each [key] was read as a column "
                     "named key, with no context aggregation")
    mapped = _PIPELINE_STATUS.get(status, NEEDS_REVIEW)
    if mapped == NEEDS_REVIEW or out is None:
        return RawResult(None, NEEDS_REVIEW, notes or ["Sisense translator: needs review"])
    return RawResult(qualify_refs(out, ctx), mapped, notes)


# ---------------------------------------------------------------------------
# Snowflake / Databricks SQL — resolver-based
# ---------------------------------------------------------------------------

def _unquote(part: str) -> str:
    p = part.strip()
    if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"`":
        return p[1:-1]
    return p


def make_recording_resolver(ctx: ColumnContext) -> Callable[[str], str]:
    """A ``resolver(ident) -> '[T::col]'`` for the SQL translators that records each call.

    Carries ``metric_refs`` (the BL-331 hook): references to aggregate Model formulas, so
    ``ROUND(<metric>, d)`` is treated as aggregated even though ``[formula_X]`` hides it.
    """
    def resolve(ident: str) -> str:
        parts = [_unquote(p) for p in re.split(r"\.(?=(?:[^\"`]*[\"`][^\"`]*[\"`])*[^\"`]*$)", ident)]
        col = parts[-1]
        hint = parts[-2] if len(parts) > 1 and ctx.level > 0 else None
        return ctx.resolve(col, table_hint=hint)

    resolve.metric_refs = ctx.aggregate_formula_targets()  # type: ignore[attr-defined]
    # References known to be DATE (not DATE_TIME): Databricks datediff(DAY, …) is native
    # diff_days only between two of these (BL-345); anything else passes through.
    resolve.date_only_refs = {  # type: ignore[attr-defined]
        s.target for s in ctx.specs if (s.data_type or "").upper() == "DATE"}
    # References known to be integers: `x % y` / MOD stay native `mod` over them (native
    # `mod` rejects a DOUBLE, so an untyped operand is the warehouse MOD — sql_forms.sqlf_mod).
    resolve.int_refs = {  # type: ignore[attr-defined]
        s.target for s in ctx.specs
        if (s.data_type or "").upper() in {"INT64", "INT32", "INT", "INTEGER", "BIGINT"}}
    return resolve


def _adapt_sql(expr: str, ctx: ColumnContext, translate_fn) -> RawResult:
    from ts_cli.formula_common import UntranslatableError

    resolver = make_recording_resolver(ctx)
    try:
        out = translate_fn(expr, resolver)
    except UntranslatableError as exc:
        return RawResult(None, NEEDS_REVIEW, [str(exc)])
    except Exception as exc:  # a parser error is still "untranslated", never a crash
        return RawResult(None, NEEDS_REVIEW, [f"{type(exc).__name__}: {exc}"])
    return RawResult(out, TRANSLATED)


def adapt_snowflake(expr: str, ctx: ColumnContext) -> RawResult:
    from ts_cli.sv_sql import translate_sql_expr

    return _adapt_sql(expr, ctx, translate_sql_expr)


def adapt_databricks(expr: str, ctx: ColumnContext) -> RawResult:
    from ts_cli.databricks.mv_sql import translate_sql_expr

    return _adapt_sql(expr, ctx, translate_sql_expr)


# ---------------------------------------------------------------------------
# Excel / Google Sheets
# ---------------------------------------------------------------------------

def adapt_excel(expr: str, ctx: ColumnContext, role_hint: Optional[str] = None,
                dialect: str = "excel") -> RawResult:
    """``role_hint``: the intended role (``measure`` / ``attribute``). A MEASURE over row-level
    ``[@Col]`` references is built at the right grain — additive sums, a ratio of totals —
    by ``excel.measure``; without it the row-level translation's own role is inferred."""
    from ts_cli.excel.translate import translate_excel

    r = translate_excel(expr, ctx, dialect=dialect, role=role_hint)
    return RawResult(r.expr, r.status, list(r.notes), traps=list(r.traps), role=r.role,
                     type_needs=list(r.type_needs))


def adapt_google_sheets(expr: str, ctx: ColumnContext,
                        role_hint: Optional[str] = None) -> RawResult:
    return adapt_excel(expr, ctx, role_hint=role_hint, dialect="google_sheets")


# ---------------------------------------------------------------------------
# ThoughtSpot (identity) — for a formula already in ThoughtSpot syntax
# ---------------------------------------------------------------------------

def adapt_thoughtspot(expr: str, ctx: ColumnContext) -> RawResult:
    """No translation: resolve the references and pass the text through.

    This is how a map-backed (hand-composed) formula reaches ``--validate`` without being
    re-translated by some other dialect's translator.
    """
    out = qualify_refs(expr, ctx)
    return RawResult(out, TRANSLATED, ["input is ThoughtSpot syntax: references resolved, "
                                       "nothing translated"])


ADAPTERS: dict[str, Any] = {
    "tableau": adapt_tableau, "dax": adapt_dax, "qlik": adapt_qlik,
    "sisense": adapt_sisense, "snowflake": adapt_snowflake, "databricks": adapt_databricks,
    "excel": adapt_excel, "google_sheets": adapt_google_sheets,
    "thoughtspot": adapt_thoughtspot,
}
