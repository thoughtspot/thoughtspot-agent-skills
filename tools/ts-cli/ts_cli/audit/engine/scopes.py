"""Engine-provided scopes: what a rule iterates over.

`iterate(ctx, scope, parent=None)` yields one *item* per object in the scope:

    {"obj":         the object's own mapping (a column, a join, a Table's `table:` body, …),
     "parent":      the enclosing item (a column's model), or None at top level,
     "guid":        the guid a finding about this item reports,
     "name":        the name a finding about this item reports,
     "object_type": the object_type a finding about this item reports,
     "scope":       the scope name,
     "doc":         the top-level document the item came from (the Model TML, …),
     "index":       its position among its parent's children of this scope (top level:
                    among the scope's items) — what tells apart one object listed twice}

`guid` / `name` / `object_type` are what the legacy checks put on a finding, so they
follow those, not the item's own identity — and are read as they read them
(`.get("name", "")`): an absent key is "", a present None stays None. A model's children report the Model's guid;
an RLS rule reports its Table; an Answer's table reference reports the Answer.

Without `parent`, every item of the scope (a child scope: every parent's children in
turn). With `parent`, the children belonging to `parent` or to the nearest item
enclosing it of the child scope's parent type; a `parent` with no such item, or a
top-level scope, raises rather than silently counting the whole context.

`has_data(item, ctx, requirement)` answers the data-availability rule: an object whose
rule `requires` data the context does not hold for it is skipped, not judged.
`available(ctx, rule)` applies it: the rule's scope items with all their required data.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Iterator, Optional

from ts_cli.audit import rules
from ts_cli.audit.catalog_expr import PARENT_SCOPE

Item = Dict[str, Any]


def _item(scope: str, obj: Any, parent: Optional[Item], guid: str, name: str,
          object_type: str, doc: Any) -> Item:
    return {"obj": obj, "parent": parent, "guid": guid, "name": name,
            "object_type": object_type, "scope": scope, "doc": doc}


# ── top-level scopes ────────────────────────────────────────────────────────

def _models(ctx) -> Iterator[Item]:
    for doc in ctx.models:
        m = doc.get("model") or {}
        yield _item("model", m, None, ctx.guid_for(doc), m.get("name", ""), "model", doc)


def _tables(ctx) -> Iterator[Item]:
    for doc in ctx.tables.values():
        t = doc.get("table") or {}
        yield _item("table", t, None, doc.get("guid", ""), t.get("name", ""), "table", doc)


def _answers(ctx) -> Iterator[Item]:
    for doc in ctx.answers:
        a = doc.get("answer") or {}
        yield _item("answer", a, None, doc.get("guid", ""), a.get("name", ""), "answer", doc)


def _sets(ctx) -> Iterator[Item]:
    """Each Set once, however many dependents lists name it (first listing wins)."""
    seen = set()
    for rows in ctx.dependents.values():
        for row in rows:
            guid = row.get("guid", "")
            if row.get("type") != "SET" or guid in seen:
                continue
            seen.add(guid)
            yield _item("set", row, None, guid, row.get("name", ""), "set", row)


def _metadata(ctx) -> Iterator[Item]:
    for entry in ctx.metadata:
        header = entry.get("metadata_header") or entry
        yield _item("metadata", header, None, header.get("id", ""), header.get("name", ""),
                    "table", entry)


# ── children of one parent item ─────────────────────────────────────────────

def _model_columns(p: Item) -> Iterator[Item]:
    for c in p["obj"].get("columns") or []:
        yield _item("model.column", c, p, p["guid"], c.get("name", ""), "column", p["doc"])


def _model_formulas(p: Item) -> Iterator[Item]:
    for f in p["obj"].get("formulas") or []:
        yield _item("model.formula", f, p, p["guid"], f.get("name", ""), "formula", p["doc"])


def _filter_name(column: Any) -> str:
    """A filter's `column` list joined; any other value (a hand-edited scalar) as text,
    never an error — no legacy check names a filter, so this only labels it."""
    if isinstance(column, (list, tuple)):
        return ", ".join(str(c) for c in column)
    return "" if column is None else str(column)


def _model_filters(p: Item) -> Iterator[Item]:
    for f in p["obj"].get("filters") or []:
        yield _item("model.filter", f, p, p["guid"], _filter_name(f.get("column")), "filter",
                    p["doc"])


def _model_tables(p: Item) -> Iterator[Item]:
    """Keyed by alias, else name — the prefix its columns' `column_id`s carry (BL-305)."""
    for mt in p["obj"].get("model_tables") or []:
        yield _item("model.table", mt, p, p["guid"], rules.table_key(mt), "table", p["doc"])


def _joins(p: Item, ctx) -> Iterator[Item]:
    """Every join, inline or referencing, resolved to one shape (rules.model_joins)."""
    for j in rules.model_joins(p["obj"], ctx.tables):
        yield _item("join", j, p, p["guid"], j["name"], "join", p["doc"])


def _rls_rules(p: Item) -> Iterator[Item]:
    for r in (p["obj"].get("rls_rules") or {}).get("rules") or []:
        yield _item("table.rls_rule", r, p, p["guid"], p["name"], "table", p["doc"])


def _rls_column_refs(p: Item) -> Iterator[Item]:
    """`obj` is {rule, column, data_type, value_casing}; type/casing "" when unknown."""
    for rule, col, dt, vc in rules.rls_column_refs(p["doc"]):
        obj = {"rule": rule, "column": col, "data_type": dt, "value_casing": vc}
        yield _item("rls_column_ref", obj, p, p["guid"], col, "column", p["doc"])


def _answer_table_refs(p: Item) -> Iterator[Item]:
    for ref in p["obj"].get("tables") or []:
        yield _item("answer.table_ref", ref, p, p["guid"], p["name"], "answer", p["doc"])


def _answer_formulas(p: Item) -> Iterator[Item]:
    for f in p["obj"].get("formulas") or []:
        yield _item("answer.formula", f, p, p["guid"], f.get("name", ""), "formula", p["doc"])


_TOP: Dict[str, Callable[[Any], Iterator[Item]]] = {
    "model": _models, "table": _tables, "answer": _answers, "set": _sets,
    "metadata": _metadata,
}
_CHILDREN: Dict[str, Callable[[Item, Any], Iterator[Item]]] = {
    "model.column": lambda p, ctx: _model_columns(p),
    "model.formula": lambda p, ctx: _model_formulas(p),
    "model.filter": lambda p, ctx: _model_filters(p),
    "model.table": lambda p, ctx: _model_tables(p),
    "join": _joins,
    "table.rls_rule": lambda p, ctx: _rls_rules(p),
    "rls_column_ref": lambda p, ctx: _rls_column_refs(p),
    "answer.table_ref": lambda p, ctx: _answer_table_refs(p),
    "answer.formula": lambda p, ctx: _answer_formulas(p),
}
ITERATORS = {**_TOP, **_CHILDREN}


def iterate(ctx, scope: str, parent: Optional[Item] = None) -> Iterator[Item]:
    """Items of `scope`: all of them, or (child scope) those under `parent`."""
    if scope not in ITERATORS:
        raise ValueError(f"unknown scope '{scope}'")
    if parent is None:
        parents = None if scope in _TOP else _TOP[PARENT_SCOPE[scope]](ctx)
    else:
        owner = ancestor(parent, PARENT_SCOPE.get(scope, ""))
        if owner is None:
            raise ValueError(f"'{scope}' items do not belong to a '{parent.get('scope')}' "
                             "item or any item enclosing it")
        parents = [owner]
    if parents is None:
        yield from _indexed(_TOP[scope](ctx))
        return
    for p in parents:
        yield from _indexed(_CHILDREN[scope](p, ctx))


def _indexed(items: Iterator[Item]) -> Iterator[Item]:
    for i, item in enumerate(items):
        item["index"] = i
        yield item


def ancestor(item: Optional[Item], scope: str) -> Optional[Item]:
    """`item` itself or its nearest enclosing item of `scope`."""
    while item is not None and item.get("scope") != scope:
        item = item.get("parent")
    return item


def root(item: Item) -> Item:
    while item.get("parent") is not None:
        item = item["parent"]
    return item


# ── data availability ───────────────────────────────────────────────────────

def _has_table_tml(item: Item, ctx) -> bool:
    top = root(item)
    if top["scope"] == "table":
        return True
    if top["scope"] == "model":
        return any(mt.get("fqn") in ctx.tables for mt in top["obj"].get("model_tables") or [])
    return bool(ctx.tables)


def _has_ai_instructions(item: Item, ctx) -> bool:
    top = root(item)
    return top["guid"] in ctx.ai_instructions if top["scope"] == "model" \
        else bool(ctx.ai_instructions)


def _set_looked_up(item: Item, ctx) -> bool:
    """A Set's consumers were looked up cleanly iff its guid keys `dependents`
    (context._add_set_dependents): absence is "unknown", never "no consumers"."""
    top = root(item)
    return top["guid"] in ctx.dependents if top["scope"] == "set" else True


# requirement -> (item, ctx) -> does the context hold that data for this item?
#   model_tml / answers  the item came from one, else the context holds any at all
#   table_tml            a Model holds TML for at least one of its tables
#   ai_instructions      the Model's guid was looked up (a failed fetch leaves no entry)
#   sets                 the Set's consumers were looked up
#   metadata, dependents always: fetched for every scoped object, so a missing entry
#                        means "none", which a rule may legitimately report on
AVAILABILITY: Dict[str, Callable[[Item, Any], bool]] = {
    "model_tml": lambda item, ctx: root(item)["scope"] == "model" or bool(ctx.models),
    "table_tml": _has_table_tml,
    "metadata": lambda item, ctx: True,
    "dependents": lambda item, ctx: True,
    "ai_instructions": _has_ai_instructions,
    "answers": lambda item, ctx: root(item)["scope"] == "answer" or bool(ctx.answers),
    "sets": _set_looked_up,
}


def has_data(item: Item, ctx, requirement: str) -> bool:
    return AVAILABILITY[requirement](item, ctx)


def available(ctx, rule) -> Iterator[Item]:
    """The items of `rule.scope` for which every `rule.requires` entry is available —
    what a rule judges. The modes and the code rules both iterate with this, so
    `requires` means the same thing for a declarative rule and a code rule."""
    for item in iterate(ctx, rule.scope):
        if all(has_data(item, ctx, req) for req in rule.requires):
            yield item
