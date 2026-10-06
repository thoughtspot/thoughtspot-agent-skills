"""``translate()`` — the dialect-independent pipeline around one adapter call.

Steps, in order: adapter → COUNT(*) repair → leftover-keyword guard → traps → role
inference → classification → TML snippet. Output is the spec §3.1 shape.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from ts_cli.formula_translate.adapters import (
    ADAPTERS, APPROXIMATED, NEEDS_REVIEW, TRANSLATED, TRANSLATOR_INFO, normalise_dialect,
)
from ts_cli.formula_translate.context import ColumnContext
from ts_cli.formula_translate.traps import detect_traps, leftover_sql, repair_count_star

DEFAULT_NAME = "Translated Formula"

_CLASSIFICATION = {TRANSLATED: "direct", APPROXIMATED: "direct (downgrade)",
                   NEEDS_REVIEW: "unmappable"}
_PASSTHROUGH = re.compile(r"\bsql_\w+?_op\s*\(")


def infer_role(expr: str, ctx: ColumnContext) -> dict[str, Any]:
    """MEASURE iff the formula aggregates — by its own text, or because it references an
    aggregate Model formula (``[formula_X]`` hides the aggregate; BL-331 review)."""
    from ts_cli.spotql_ops import SEMIADDITIVE_OUTER_FUNCS, classify_expr, outermost_func

    cls = classify_expr(expr)
    is_measure = cls["column_type"] == "MEASURE" or any(
        t in expr for t in ctx.aggregate_formula_targets())
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
                 sisense_context: Optional[dict], tableau_role: Optional[str]):
    adapter = ADAPTERS[dialect]
    if dialect == "sisense":
        return adapter(source, ctx, context=sisense_context)
    if dialect == "tableau":
        return adapter(source, ctx, role_hint=tableau_role)
    return adapter(source, ctx)


def _post_process(raw, dialect: str, source: str, ctx: ColumnContext):
    """COUNT(*) repair, leftover-keyword guard, traps. Returns (expr, status, notes, traps)."""
    out, status, notes = raw.expr, raw.status, list(raw.notes)
    traps: list[str] = []
    if out is None:
        return out, status, notes, traps
    out, count_trap = repair_count_star(out, ctx)
    if count_trap:
        traps.append(count_trap)
    guard = leftover_sql(out)
    if guard:
        notes.append(guard)
        raw.partial = out
        return None, NEEDS_REVIEW, notes, traps
    traps.extend(detect_traps(dialect, source, out))
    return out, status, notes, traps


def translate(expr: str, dialect: str, ctx: Optional[ColumnContext] = None, *,
              name: str = DEFAULT_NAME, sisense_context: Optional[dict] = None,
              tableau_role: Optional[str] = None) -> dict[str, Any]:
    """Translate one source formula. Never raises for an untranslatable input — that is
    ``status: NEEDS_REVIEW`` with the reason in ``notes``."""
    dialect = normalise_dialect(dialect)
    ctx = ctx or ColumnContext()
    source = (expr or "").strip()
    if not source:
        raise ValueError("empty formula")

    raw = _run_adapter(source, dialect, ctx, sisense_context, tableau_role)
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
    }
    if out is None:
        result["original_kept"] = source
        if raw.partial:
            result["partial"] = raw.partial
        return result
    if _PASSTHROUGH.search(out) and status == TRANSLATED:
        result["classification"] = "passthrough"
    role = infer_role(out, ctx)
    result.update(role=role["role"], agentql_wrapper=role["agentql_wrapper"], name=name,
                  tml=tml_snippet(name, out, role["role"]))
    return result
