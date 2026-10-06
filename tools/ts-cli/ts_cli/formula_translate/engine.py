"""``translate()`` — the dialect-independent pipeline around one adapter call.

Steps, in order: adapter → COUNT(*) repair → leftover-keyword guard → traps → role
inference → classification → TML snippet → the skill's questions (``needs_types``,
``role_ambiguous`` / ``role_options``; ``prompts.py``). Output is the spec §3.1 shape.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from ts_cli.formula_translate.adapters import (
    ADAPTERS, APPROXIMATED, NEEDS_REVIEW, TRANSLATED, TRANSLATOR_INFO, normalise_dialect,
)
from ts_cli.formula_translate.context import ColumnContext
from ts_cli.formula_translate.defects import find_defects
from ts_cli.formula_translate.editor import editor_form
from ts_cli.formula_translate.prompts import (
    ROLE_GRAIN_DIALECTS, build_needs_types, has_ratio, role_option,
)
from ts_cli.formula_translate.refs import split_literals
from ts_cli.formula_translate.traps import (
    detect_traps, is_downgrade, output_guard, repair_count_star,
)

# Comment syntaxes per source dialect (stripped before translating; never inside literals).
_LINE_COMMENTS = {"snowflake": ("--",), "databricks": ("--",), "dax": ("--", "//"),
                  "tableau": ("//",), "qlik": ("//",)}
_BLOCK_COMMENT_DIALECTS = {"snowflake", "databricks", "dax", "qlik", "tableau"}


def strip_comments(source: str, dialect: str) -> tuple[str, bool]:
    """Remove ``--`` / ``//`` line comments and ``/* */`` blocks outside string literals."""
    markers = _LINE_COMMENTS.get(dialect, ())
    block = dialect in _BLOCK_COMMENT_DIALECTS
    if not markers and not block:
        return source, False
    out: list[str] = []
    for lit, seg in split_literals(source):
        if lit:
            out.append(seg)
            continue
        if block:
            seg = re.sub(r"/\*.*?\*/", " ", seg, flags=re.S)
        for mk in markers:
            seg = re.sub(re.escape(mk) + r"[^\n]*", " ", seg)
        out.append(seg)
    cleaned = re.sub(r"[ \t]+", " ", "".join(out)).strip()
    return cleaned, cleaned != source.strip()

DEFAULT_NAME = "Translated_Formula"  # coined: underscores, so editor + TML share it

_CLASSIFICATION = {TRANSLATED: "direct", APPROXIMATED: "direct (downgrade)",
                   NEEDS_REVIEW: "unmappable"}
_PASSTHROUGH = re.compile(r"\bsql_\w+?_op\s*\(")


def infer_role(expr: str, ctx: ColumnContext, intended: Optional[str] = None) -> dict[str, Any]:
    """MEASURE iff the formula aggregates — by its own text, or because it references an
    aggregate Model formula (``[formula_X]`` hides the aggregate; BL-331 review).

    ``intended`` is a role the translator already applied (Excel ``--role``): a row-level
    numeric flag kept as a MEASURE is totalled by its column aggregation, so AgentQL wraps it
    in ``SUM``."""
    from ts_cli.spotql_ops import SEMIADDITIVE_OUTER_FUNCS, classify_expr, outermost_func

    cls = classify_expr(expr)
    aggregates = cls["column_type"] == "MEASURE" or any(
        t in expr for t in ctx.aggregate_formula_targets())
    if intended in ("MEASURE", "ATTRIBUTE"):
        if intended == "ATTRIBUTE":
            return {"role": "ATTRIBUTE", "agentql_wrapper": None}
        if not aggregates:
            return {"role": "MEASURE", "agentql_wrapper": "SUM"}
    is_measure = aggregates
    outer = outermost_func(expr)
    return {
        "role": "MEASURE" if is_measure else "ATTRIBUTE",
        "agentql_wrapper": (("SUM" if outer in SEMIADDITIVE_OUTER_FUNCS else "AGG")
                            if is_measure else None),
    }


def formula_id(name: str) -> str:
    """``formula_<display name>`` with spaces kept (thoughtspot-formula-patterns.md)."""
    return f"formula_{name}"


def formula_tml_entries(name: str, expr: str, role: str) -> tuple[dict, dict]:
    """The ``formulas[]`` and ``columns[]`` entries. ``aggregation`` only on the column."""
    fid = formula_id(name)
    formula = {"id": fid, "name": name, "expr": expr}
    props: dict[str, Any] = {"column_type": role}
    if role == "MEASURE":
        props["aggregation"] = "SUM"  # repo convention; ignored at query time for formulas
    column = {"name": name, "formula_id": fid, "properties": props}
    return formula, column


def tml_snippet(name: str, expr: str, role: str) -> str:
    from ts_cli.tml_common import dump_tml_yaml

    formula, column = formula_tml_entries(name, expr, role)
    # Two dumps so `formulas:` reads first (dump_tml_yaml sorts keys).
    return dump_tml_yaml({"formulas": [formula]}) + dump_tml_yaml({"columns": [column]})


def _run_adapter(source: str, dialect: str, ctx: ColumnContext,
                 sisense_context: Optional[dict], tableau_role: Optional[str],
                 first_week_day: Optional[int] = None):
    adapter = ADAPTERS[dialect]
    if dialect in ("excel", "google_sheets"):
        return adapter(source, ctx, role_hint=tableau_role)
    if dialect == "qlik":
        return adapter(source, ctx, first_week_day=first_week_day)
    if dialect == "sisense":
        return adapter(source, ctx, context=sisense_context)
    if dialect == "tableau":
        return adapter(source, ctx, role_hint=tableau_role)
    return adapter(source, ctx)


def _post_process(raw, dialect: str, source: str, ctx: ColumnContext):
    """COUNT(*) repair, leftover-keyword guard, traps. Returns (expr, status, notes, traps)."""
    out, status, notes = raw.expr, raw.status, list(raw.notes)
    traps: list[str] = list(raw.traps)
    if out is None:
        return out, status, notes, traps
    defects = find_defects(dialect, source, out)
    for d in defects:
        if d.action == NEEDS_REVIEW:
            notes.append(d.message)
            raw.partial = out
            return None, NEEDS_REVIEW, notes, traps
    allow = frozenset().union(*(d.allow_functions for d in defects))
    out, count_trap = repair_count_star(out, ctx)
    if count_trap:
        traps.append(count_trap)
    guard = output_guard(out, allow=allow, source=source)
    if guard:
        notes.append(guard)
        raw.partial = out
        return None, NEEDS_REVIEW, notes, traps
    for d in defects:  # the APPROXIMATED ones
        traps.append(d.message)
        if status == TRANSLATED:
            status = APPROXIMATED
    traps.extend(t for t in detect_traps(dialect, source, out) if t not in traps)
    if status == TRANSLATED and any(is_downgrade(t) for t in traps):
        status = APPROXIMATED
    return out, status, notes, traps


def translate(expr: str, dialect: str, ctx: Optional[ColumnContext] = None, *,
              name: str = DEFAULT_NAME, sisense_context: Optional[dict] = None,
              tableau_role: Optional[str] = None,
              first_week_day: Optional[int] = None,
              role: Optional[str] = None) -> dict[str, Any]:
    """Translate one source formula. Never raises for an untranslatable input — that is
    ``status: NEEDS_REVIEW`` with the reason in ``notes``.

    ``role`` (``measure`` / ``attribute``) is the intended role: a role hint for Tableau, and
    for Excel / Google Sheets the grain the formula is built at (``excel.measure``).
    ``tableau_role`` is its older spelling."""
    dialect = normalise_dialect(dialect)
    tableau_role = role or tableau_role
    ctx = ctx or ColumnContext()
    source = (expr or "").strip()
    if not source:
        raise ValueError("empty formula")

    source, had_comments = strip_comments(source, dialect)
    if not source:
        raise ValueError("the formula is only a comment")
    raw = _run_adapter(source, dialect, ctx, sisense_context, tableau_role, first_week_day)
    if had_comments:
        raw.notes.append("comments were removed before translating")
    out, status, notes, traps = _post_process(raw, dialect, source, ctx)

    translator, tests = TRANSLATOR_INFO[dialect]
    result: dict[str, Any] = {
        "dialect": dialect,
        "input": source,
        "formula": out,
        "status": status,
        "classification": _CLASSIFICATION[status],
        "role": None,
        "references": [r.as_dict() for r in ctx.references],
        "unresolved": [r.source for r in ctx.unresolved],
        "context_level": ctx.level,
        "traps": traps,
        "notes": [n for n in notes if n],
        "verification": {"level": "none", "translator": translator, "tests": tests},
        "tml": None,
        "needs_types": build_needs_types(raw.type_needs, ctx),
        "role_ambiguous": False,
        "role_options": [],
    }
    if out is None:
        result["original_kept"] = source
        if raw.partial:
            result["partial"] = raw.partial
        return result
    if _PASSTHROUGH.search(out) and status == TRANSLATED:
        result["classification"] = "passthrough"
    role = infer_role(out, ctx, raw.role)
    editor, editor_notes = editor_form(out, ctx)
    result.update(role=role["role"], agentql_wrapper=role["agentql_wrapper"], name=name,
                  formula_editor=editor, formula_editor_notes=editor_notes,
                  tml=tml_snippet(name, out, role["role"]))
    options = _role_options(expr, dialect, ctx, name, tableau_role)
    result.update(role_ambiguous=bool(options), role_options=options)
    return result


def _role_options(expr: str, dialect: str, ctx: ColumnContext, name: str,
                  given_role: Optional[str]) -> list[dict]:
    """Both translations of a ratio when the role decides the grain, else ``[]``.

    Ambiguous only when the formula has a ratio, both roles translate, and they differ: an
    already-aggregated ratio, or one whose MEASURE form is NEEDS_REVIEW, has one answer."""
    if given_role is not None or dialect not in ROLE_GRAIN_DIALECTS:
        return []

    def run(role: str) -> dict:
        fresh = ColumnContext(ctx.specs, ctx.level, ctx.model_name)
        return translate(expr, dialect, fresh, name=name, role=role)

    attribute, measure = run("attribute"), run("measure")
    if not (attribute["formula"] and measure["formula"] and has_ratio(attribute["formula"])):
        return []
    if attribute["formula"] == measure["formula"]:
        return []
    return [role_option("attribute", attribute), role_option("measure", measure)]
