"""``translate_excel()`` — one Excel / Google Sheets formula → ThoughtSpot formula text.

Pipeline: parse (``parser``) → row-level translation (``forward.Translator``, rules in
``functions*``) → the intended-role pass (``measure.apply_role``) → canonical text
(``tsast.to_text``). Pure; the ``formula_translate`` adapter wraps it and adds the
dialect-independent steps (output guard, generic traps, TML).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ts_cli.excel.forward import NEEDS_REVIEW, NeedsReview, Translator, check_a1
from ts_cli.excel.measure import apply_role
from ts_cli.excel.parser import ExcelSyntaxError, parse
from ts_cli.excel.tsast import to_text
from ts_cli.formula_common import UntranslatableError

ROLES = ("measure", "attribute")


@dataclass
class ExcelResult:
    expr: Optional[str]
    status: str
    notes: list = field(default_factory=list)
    traps: list = field(default_factory=list)
    role: Optional[str] = None    # MEASURE | ATTRIBUTE when an intended role was applied
    type_needs: list = field(default_factory=list)  # (target, reason, note) — see prompts.py


def translate_excel(source: str, ctx, dialect: str = "excel",
                    role: Optional[str] = None) -> ExcelResult:
    """Translate one formula. Never raises for an untranslatable input — that is
    ``NEEDS_REVIEW`` with the reason in ``notes``."""
    role = (role or "").strip().lower() or None
    if role is not None and role not in ROLES:
        raise ValueError(f"role must be one of {', '.join(ROLES)}, not {role!r}")
    tr = Translator(ctx, dialect)
    try:
        tree = parse(source)
        check_a1(tree)
        row_level = tr.expr(tree)
        node, out_role = apply_role(tr, row_level, role)
    except ExcelSyntaxError as exc:
        return ExcelResult(None, NEEDS_REVIEW, [f"cannot parse the formula: {exc}"])
    except (NeedsReview, UntranslatableError) as exc:
        return ExcelResult(None, NEEDS_REVIEW, tr.notes + [str(exc)], tr.traps,
                           type_needs=tr.type_needs)
    return ExcelResult(to_text(node), tr.status, tr.notes, tr.traps, out_role, tr.type_needs)
