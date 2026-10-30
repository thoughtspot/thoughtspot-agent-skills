"""Derived fields for the H (Human Readiness) rules.

Registered into the same registry as engine/fields.py (which imports this module at its
end, so `fields.FIELDS` — and the catalog gate's list of known names — always includes
them). Each reproduces what a legacy check in checks_human.py (deleted when the rule catalog replaced them)
read, step for step, including the readings that are known to be wrong (the legacy
answers pinned in tests/audit_rule_fixtures/legacy_findings.json.gz hold them to it;
fixing them is the follow-up work the spec lists):

- H3 decided which tables are "joined" by a model table's `name` (and a join's raw
  `with`), where its columns' `column_id`s carry the `alias` when it has one, and
  tested a formula-backed column by its formula's display name only, where real TML
  references a formula by id (`[formula_<name>]`). Both fixed 2026-10 (roadmap PR 2.3):
  a table is keyed by alias, else name, and an id reference counts.

Where the legacy check would raise on a malformed value (a non-string expression or
`column_id`, a non-mapping `properties`), these read it as absent instead: a raising
legacy check aborts the whole H category, so there is nothing to reproduce.

Same import constraint as fields.py: Python 3.9, no third-party imports at module level.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from ts_cli.audit.engine import tml
from ts_cli.audit.engine.fields import _model_of, register
from ts_cli.audit.engine.memo import cached

_WHITESPACE = re.compile(r"\s+")


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""


# ── H1: column names a person would not search for ──────────────────────────

#: col1, field_2, val, tmp_x, a leading digit (any case) — and SHOUTING_SNAKE warehouse
#: names. H1 and the report's Spotter readiness score both read them through
#: `is_poor_name`; each kept its own copy until 2026-10.
_NAME_ANTI = re.compile(r"^col\d+$|^field[-_]?\d+$|^val\d*$|^tmp[-_]|^\d", re.IGNORECASE)
_NAME_ANTI_UPPER = re.compile(r"^[A-Z][A-Z0-9]*_[A-Z0-9_]+$")


def is_poor_name(name: Any) -> bool:
    """A name matching either pattern; False for a non-string."""
    return isinstance(name, str) and bool(_NAME_ANTI.match(name) or
                                          _NAME_ANTI_UPPER.match(name))


@register("is_poor_name", uses=(),
          label="the column's name is generic or a warehouse name")
def _is_poor_name(item: dict, ctx: Any) -> bool:
    """Model column: its `name` is one a person would not search for (is_poor_name)."""
    return is_poor_name((item.get("obj") or {}).get("name"))


# ── H3: hidden columns no formula references ────────────────────────────────

def _joined_table_names(model: dict) -> set:
    """H3's joined tables, by key: the same set D5 and D10 read (tml.joined_keys). Once
    per Model per run (engine/memo.py)."""
    return cached("joined_keys", model, tml.joined_keys, model.get("model_tables") or [])


def _is_hidden(column: Any) -> bool:
    props = column.get("properties") if isinstance(column, dict) else None
    return bool(props.get("is_hidden")) if isinstance(props, dict) else False


@register("is_sole_join_carrier", uses=(),
          label="the column is the only visible one from its joined table")
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


@register("referenced_by_formula", uses=(),
          label="a formula references the column")
def _referenced_by_formula(item: dict, ctx: Any) -> bool:
    """Model column: the Model's formula expressions, joined by spaces, reference it —
    as `[<its name>]` or `[<its column_id>]` (`[TABLE::COL]`, the usual form) — or it
    surfaces a formula (`formula_id`) that another formula references, by `[<its id>]`
    (how TML writes it) or `[<its display name>]`."""
    model = _model_of(item)
    formulas = model.get("formulas") or []
    exprs = cached("h3_formula_text", model, _formula_text, formulas)
    column = item.get("obj") or {}
    if f"[{column.get('name', '')}]" in exprs:
        return True
    fid = column.get("formula_id")
    cid = column.get("column_id")
    if isinstance(cid, str) and cid and f"[{cid}]" in exprs:
        return True  # `[TABLE::COL]`, how most formulas reference a physical column
    if not fid:
        return False
    if isinstance(fid, str) and f"[{fid}]" in exprs:
        return True
    return any(f"[{fn.get('name', '')}]" in exprs for fn in formulas if fn.get("id") == fid)


def _formula_text(formulas: list) -> str:
    """The Model's formula expressions joined by spaces (non-strings skipped)."""
    return " ".join(e for e in (f.get("expr", "") for f in formulas) if isinstance(e, str))


# ── H4 / H5: dependents ─────────────────────────────────────────────────────

# Declares `sets` too: it reads `ctx.dependents`, which Set discovery writes SET rows
# into. It filters them out, but no static check can prove that (catalog_reads.py).
@register("dependent_count", uses={"dependents", "sets"},
          label="the number of dependent objects")
def _dependent_count(item: dict, ctx: Any) -> int:
    """Model: how many `ctx.dependents` rows under its guid are not Sets. A Set is a
    column on the Model, so whatever uses it is already a Model dependent: a SET row
    alone never makes a Model used. A Model never listed has none."""
    rows = ctx.dependents.get(item.get("guid"), []) or []
    return sum(1 for d in rows if d.get("type") != "SET")


@register("orphan_model", uses={"dependents", "sets"}, values=(False, True),
          label="the item is a Model nothing uses")
def _orphan_model(item: dict, ctx: Any) -> bool:
    """True for a Model with no dependents but Sets (H4's test, @dependent_count); False
    for any other item, a column included — H10 grades its findings on this."""
    return item.get("scope") == "model" and _dependent_count(item, ctx) == 0


@register("set_consumers", uses={"dependents", "sets"},
          label="the objects that use the Set")
def _set_consumers(item: dict, ctx: Any) -> Any:
    """Set: the consumers its lookup returned (`ctx.dependents[<set guid>]`); None when
    it was not looked up — which a rule declaring `requires: [sets]` never sees."""
    return ctx.dependents.get(item.get("guid"))


# ── H7: Answers built straight off a Table ──────────────────────────────────

def _known_table_guids(ctx: Any) -> set:
    """legacy H7's `table_guids`: every non-empty `model_tables[].fqn` of every Model,
    and every Table TML key in the context — those left out as malformed included (they
    are still Tables). Once per run (engine/memo.py)."""
    return cached("h7_known_table_guids", ctx, _build_known_table_guids, ctx)


def _build_known_table_guids(ctx: Any) -> set:
    guids: set = set()
    for doc in _all_models(ctx):
        for mt in (doc.get("model") or {}).get("model_tables") or []:
            fqn = mt.get("fqn", "") if isinstance(mt, dict) else ""
            if fqn:
                guids.add(fqn)
    return guids | set(ctx.tables) | set(getattr(ctx, "excluded_tables", {}) or {})


def _all_models(ctx: Any) -> list:
    """Every Model in the run: the judged ones and those left out as malformed (BL-406
    item 10). A rule asking whether something is on NO Model reads this, never
    `ctx.models` alone, or excluding a Model would make that answer false."""
    return list(ctx.models) + list(getattr(ctx, "excluded_models", []) or [])


@register("is_table_reference", uses=(),
          label="the Answer reads a Table directly")
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
    for doc in _all_models(ctx):
        for f in (doc.get("model") or {}).get("formulas") or []:
            key = _normalize(f.get("expr", ""))
            if key is not None:
                names[key] = f.get("name", "")
    return names


@register("normalized_expr", uses=(),
          label="the formula expression, normalised")
def _normalized_expr(item: dict, ctx: Any) -> Optional[str]:
    """Answer formula: its `expr` normalised (see _normalize; absent reads as "")."""
    return _normalize((item.get("obj") or {}).get("expr", ""))


@register("matches_model_formula", uses=(),
          label="a Model formula has the same expression")
def _matches_model_formula(item: dict, ctx: Any) -> bool:
    """Answer formula: a Model formula has the same normalised expression — a blank one
    included (legacy H9 has no blank guard; H8 excludes blanks itself)."""
    expr = _normalized_expr(item, ctx)
    return expr is not None and expr in _model_formula_names(ctx)


@register("matched_model_formula_name", uses=(),
          label="the Model formula with the same expression")
def _matched_model_formula_name(item: dict, ctx: Any) -> Any:
    """Answer formula: the name of the Model formula it duplicates (the last one with
    that expression), or None."""
    return _model_formula_names(ctx).get(_normalized_expr(item, ctx))


@register("answer_name", uses=(),
          label="the Answer's name")
def _answer_name(item: dict, ctx: Any) -> Any:
    """Answer formula: the name of its Answer, as an Answer finding reports it ("" when
    the Answer has no `name`)."""
    return (item.get("parent") or {}).get("name")
