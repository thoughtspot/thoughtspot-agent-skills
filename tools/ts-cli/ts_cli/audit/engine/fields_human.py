"""Derived fields for the H (Human Readiness) rules.

Registered into the same registry as engine/fields.py (which imports this module at its
end, so `fields.FIELDS` — and the catalog gate's list of known names — always includes
them). Each reproduces what a legacy check in checks_human.py (deleted in Task 12b)
read, step for step, including the readings that are known to be wrong (the legacy
answers pinned in tests/audit_rule_fixtures/legacy_findings.json.gz hold them to it;
fixing them is the follow-up work the spec lists):

- H3 decides which tables are "joined" by a model table's `name` (and a join's
  `with`), where its columns' `column_id`s carry the `alias` when it has one — so a
  hidden column of an aliased table that declares its own joins is never exempt
  (@is_sole_join_carrier keeps that).
- H3 tests a formula-backed column by its formula's display name in brackets, where
  real TML references a formula by id (`[formula_<name>]`) — @referenced_by_formula
  keeps that.

Where the legacy check would raise on a malformed value (a non-string expression or
`column_id`, a non-mapping `properties`), these read it as absent instead: a raising
legacy check aborts the whole H category, so there is nothing to reproduce.

Same import constraint as fields.py: Python 3.9, no third-party imports at module level.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from ts_cli.audit.engine.fields import _model_of, register
from ts_cli.audit.engine.memo import cached

_WHITESPACE = re.compile(r"\s+")


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""


# ── H3: hidden columns no formula references ────────────────────────────────

def _joined_table_names(model: dict) -> set:
    """legacy H3's `joined`: the `name` of every model table that declares a join, and
    every join's `with` (a table with `joins` absent or empty contributes nothing).
    Once per Model per run (engine/memo.py)."""
    return cached("h3_joined_table_names", model, _build_joined_table_names, model)


def _build_joined_table_names(model: dict) -> set:
    joined: set = set()
    for t in model.get("model_tables") or []:
        for j in t.get("joins") or []:
            joined.add(t.get("name", ""))
            joined.add(j.get("with", ""))
    return joined


def _is_hidden(column: Any) -> bool:
    props = column.get("properties") if isinstance(column, dict) else None
    return bool(props.get("is_hidden")) if isinstance(props, dict) else False


@register("is_sole_join_carrier", uses=())
def _is_sole_join_carrier(item: dict, ctx: Any) -> bool:
    """Model column: its `column_id` prefix ("" without `::`) names a joined table
    (by NAME — see the module docstring) and no OTHER visible column of the Model
    carries that prefix — so hiding it keeps the join alive, and H3 excuses it."""
    model = _model_of(item)
    column = item.get("obj") or {}
    cid = _str(column.get("column_id", ""))
    table = cid.split("::")[0] if "::" in cid else ""
    if table not in _joined_table_names(model):
        return False
    prefix = f"{table}::"
    return not any(_str(cc.get("column_id", "")).startswith(prefix)
                   for cc in model.get("columns") or []
                   if cc is not column and not _is_hidden(cc))


@register("referenced_by_formula", uses=())
def _referenced_by_formula(item: dict, ctx: Any) -> bool:
    """Model column: `[<its name>]` appears in the Model's formula expressions joined by
    spaces — or it surfaces a formula (`formula_id`) whose `[<display name>]` does."""
    model = _model_of(item)
    formulas = model.get("formulas") or []
    exprs = cached("h3_formula_text", model, _formula_text, formulas)
    column = item.get("obj") or {}
    if f"[{column.get('name', '')}]" in exprs:
        return True
    fid = column.get("formula_id")
    return bool(fid) and any(f"[{fn.get('name', '')}]" in exprs
                             for fn in formulas if fn.get("id") == fid)


def _formula_text(formulas: list) -> str:
    """The Model's formula expressions joined by spaces (non-strings skipped)."""
    return " ".join(e for e in (f.get("expr", "") for f in formulas) if isinstance(e, str))


# ── H4 / H5: dependents ─────────────────────────────────────────────────────

# Declares `sets` too: it reads `ctx.dependents`, which Set discovery writes SET rows
# into. It filters them out (R15), but no static check can prove that (catalog_reads.py).
@register("dependent_count", uses={"dependents", "sets"})
def _dependent_count(item: dict, ctx: Any) -> int:
    """Model: how many `ctx.dependents` rows under its guid are not Sets. A Set is a
    column on the Model, so whatever uses it is already a Model dependent: a SET row
    alone never makes a Model used (ruling R15). A Model never listed has none."""
    rows = ctx.dependents.get(item.get("guid"), []) or []
    return sum(1 for d in rows if d.get("type") != "SET")


@register("set_consumers", uses={"dependents", "sets"})
def _set_consumers(item: dict, ctx: Any) -> Any:
    """Set: the consumers its lookup returned (`ctx.dependents[<set guid>]`); None when
    it was not looked up — which a rule declaring `requires: [sets]` never sees."""
    return ctx.dependents.get(item.get("guid"))


# ── H7: Answers built straight off a Table ──────────────────────────────────

def _known_table_guids(ctx: Any) -> set:
    """legacy H7's `table_guids`: every non-empty `model_tables[].fqn` of every Model,
    and every Table TML key in the context. Once per run (engine/memo.py)."""
    return cached("h7_known_table_guids", ctx, _build_known_table_guids, ctx)


def _build_known_table_guids(ctx: Any) -> set:
    guids: set = set()
    for doc in ctx.models:
        for mt in (doc.get("model") or {}).get("model_tables") or []:
            fqn = mt.get("fqn", "")
            if fqn:
                guids.add(fqn)
    return guids | set(ctx.tables)


@register("is_table_reference", uses=())
def _is_table_reference(item: dict, ctx: Any) -> bool:
    """Answer table reference: its `fqn` is set and is a Table's guid (see
    _known_table_guids). An Answer built on a Model carries the Model's guid there; an
    fqn matching nothing known is unresolved, not a bypass (BL-301)."""
    fqn = (item.get("obj") or {}).get("fqn", "")
    return bool(fqn) and fqn in _known_table_guids(ctx)


# ── H8 / H9: Answer formulas against Model formulas ─────────────────────────

def _normalize(expr: Any) -> Optional[str]:
    """legacy `_normalize_expr`: stripped, lower-cased, whitespace runs collapsed to one
    space. None for a non-string."""
    if not isinstance(expr, str):
        return None
    return _WHITESPACE.sub(" ", expr.strip().lower())


def _model_formula_names(ctx: Any) -> Dict[str, Any]:
    """Normalised expression -> the `name` of the LAST Model formula (across every
    Model, in order) with that expression, as legacy H9 builds it; its keys are H8's
    set. An absent `expr` normalises to "" like any other. Once per run — it is read for
    every Answer formula (engine/memo.py)."""
    return cached("h8_model_formula_names", ctx, _build_model_formula_names, ctx)


def _build_model_formula_names(ctx: Any) -> Dict[str, Any]:
    names: Dict[str, Any] = {}
    for doc in ctx.models:
        for f in (doc.get("model") or {}).get("formulas") or []:
            key = _normalize(f.get("expr", ""))
            if key is not None:
                names[key] = f.get("name", "")
    return names


@register("normalized_expr", uses=())
def _normalized_expr(item: dict, ctx: Any) -> Optional[str]:
    """Answer formula: its `expr` normalised (see _normalize; absent reads as "")."""
    return _normalize((item.get("obj") or {}).get("expr", ""))


@register("matches_model_formula", uses=())
def _matches_model_formula(item: dict, ctx: Any) -> bool:
    """Answer formula: a Model formula has the same normalised expression — a blank one
    included (legacy H9 has no blank guard; H8 excludes blanks itself)."""
    expr = _normalized_expr(item, ctx)
    return expr is not None and expr in _model_formula_names(ctx)


@register("matched_model_formula_name", uses=())
def _matched_model_formula_name(item: dict, ctx: Any) -> Any:
    """Answer formula: the name of the Model formula it duplicates (the last one with
    that expression), or None."""
    return _model_formula_names(ctx).get(_normalized_expr(item, ctx))


@register("answer_name", uses=())
def _answer_name(item: dict, ctx: Any) -> Any:
    """Answer formula: the name of its Answer, as an Answer finding reports it ("" when
    the Answer has no `name`)."""
    return (item.get("parent") or {}).get("name")
