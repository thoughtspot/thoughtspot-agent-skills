"""Field paths and the derived-field registry.

A rule reads an item through a *field path* (`field:` in an expression, `measure:`,
group `key:`/`value:`/`member:`, pairwise `set:`, composite components, a severity
mapping's `field:`, an `{each}` message placeholder):

    properties.column_type   walk the item's `obj` mapping key by key
    model_tables.fqn         a non-numeric step on a list maps over it -> [fqn, ...]
    properties.synonyms.0    a numeric step on a list indexes it
    parent.name              `parent.` (repeatable) reads the enclosing item instead
    @is_indexed              a derived field: a registered function of (item, ctx)

A missing key, an index out of range or a step into a scalar yields None, never an
error — absence is data, and the operators define what None means.

Derived fields are small pure functions, written once, for what a path cannot express
(a default the schema implies, a join graph, a lookup into another document). Register
one with `@register("name")`; the catalog validator learns the name from `FIELDS`.

Kept importable on Python 3.9 with no third-party imports (the catalog gate imports
this module to learn the registered names): import anything heavier inside the
function that needs it.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Tuple

from ts_cli.audit import rules

DerivedField = Callable[[dict, Any], Any]
FIELDS: Dict[str, DerivedField] = {}

_PARENT = "parent."


def register(name: str) -> Callable[[DerivedField], DerivedField]:
    """Decorator: make `fn(item, ctx)` available to rules as `@name`."""
    def deco(fn: DerivedField) -> DerivedField:
        if name in FIELDS:
            raise ValueError(f"derived field '@{name}' is already registered")
        FIELDS[name] = fn
        return fn
    return deco


def get(item: dict | None, path: str, ctx: Any) -> Any:
    """The value at `path` for `item` (see the module docstring); None when absent."""
    while path.startswith(_PARENT):
        item = item.get("parent") if item else None
        path = path[len(_PARENT):]
    if item is None:
        return None
    if path.startswith("@"):
        fn = FIELDS.get(path[1:])
        if fn is None:
            raise KeyError(f"unknown derived field '{path}'")
        return fn(item, ctx)
    return walk(item.get("obj"), path)


def walk(value: Any, path: str) -> Any:
    """Follow a dotted path through mappings and lists (lists map or index).

    A derived `@name` is only ever a whole path (handled by `get`); as a step inside
    one it would silently read None, so it raises.
    """
    for step in path.split(".") if path else []:
        if step.startswith("@"):
            raise KeyError(f"derived field '{step}' must be the whole path, "
                           f"not a step in '{path}'")
        value = _step(value, step)
        if value is None:
            return None
    return value


def _step(value: Any, step: str) -> Any:
    if isinstance(value, dict):
        return value.get(step)
    if isinstance(value, list):
        if step.lstrip("-").isdigit():
            i = int(step)
            return value[i] if -len(value) <= i < len(value) else None
        return [_step(v, step) for v in value]
    return None


# ── derived fields ──────────────────────────────────────────────────────────

@register("is_indexed")
def _is_indexed(item: dict, ctx: Any) -> bool:
    """Column: text-search indexed (absent `index_type` means indexed by default)."""
    return rules.is_indexed(item.get("obj") or {})


@register("has_synonyms")
def _has_synonyms(item: dict, ctx: Any) -> bool:
    """Column: carries synonyms under `properties:` (exported TML) or at the root."""
    col = item.get("obj") or {}
    props = col.get("properties") or {}
    return bool((props.get("synonyms") if isinstance(props, dict) else None)
                or col.get("synonyms"))


@register("join_depth")
def _join_depth(item: dict, ctx: Any) -> int:
    """Model: longest join chain across `model_tables` (rules.join_depth)."""
    return rules.join_depth((item.get("obj") or {}).get("model_tables") or [])


@register("is_coached")
def _is_coached(item: dict, ctx: Any) -> bool:
    """Model: coached — its ai/instructions response carries an instruction, or its TML
    has `model_instructions.data_model_instructions`. A model whose lookup failed (no
    entry in `ctx.ai_instructions`) reads as uncoached here; a rule that must skip it
    instead declares `requires: [ai_instructions]` (A3 does, A5 does not)."""
    from ts_cli.audit.context import nl_instructions  # not gate-safe: import on use
    model = item.get("obj") or {}
    return bool(
        nl_instructions(ctx.ai_instructions.get(item.get("guid")))
        or ((model.get("model_instructions") or {}).get("data_model_instructions")
            or "").strip())


def _model_of(item: dict) -> dict:
    """The Model body a child item (column, formula, join) belongs to."""
    return ((item.get("parent") or {}).get("obj")) or {}


@register("is_scalar_formula")
def _is_scalar_formula(item: dict, ctx: Any) -> bool:
    """Formula: no `columns[]` entry surfacing it (by `formula_id`) declares an
    `aggregation`. A formula with no `id` is not scalar when some aggregating column
    has no `formula_id` either (both read None) — the legacy P2 reading, kept."""
    aggregated = {c.get("formula_id") for c in (_model_of(item).get("columns") or [])
                  if (c.get("properties") or {}).get("aggregation")}
    return (item.get("obj") or {}).get("id") not in aggregated


@register("has_date_constraint")
def _has_date_constraint(item: dict, ctx: Any) -> bool:
    """Model: a `date_range_condition` anywhere in its `constraints` (a mapping in
    exported TML, a list in hand-built fixtures — searched as text, BL-303)."""
    return "date_range_condition" in str((item.get("obj") or {}).get("constraints") or {})


def _fact_table_names(item: dict) -> set:
    model = item.get("obj") or {}
    return rules.fact_tables(model.get("columns") or [], model.get("model_tables") or [])


@register("fact_tables")
def _fact_tables(item: dict, ctx: Any) -> List[str]:
    """Model: the distinct `model_tables[].name`s that read as fact tables
    (rules.fact_tables — keyed by name, not alias), sorted; a name list in messages."""
    from ts_cli.audit.engine.messages import NameList  # messages imports this module
    return NameList(sorted(_fact_table_names(item)))


@register("fact_table_count")
def _fact_table_count(item: dict, ctx: Any) -> int:
    """Model: how many distinct table names read as fact tables (see @fact_tables)."""
    return len(_fact_table_names(item))


@register("varchar_join_keys")
def _varchar_join_keys(item: dict, ctx: Any) -> List[str]:
    """Join: the column ids in its `on` clause whose warehouse type, read off the Table
    TMLs (AuditContext.column_types), is a string type. A key whose table is not in
    the context has no type and is not listed — unknown is not "a string"."""
    from ts_cli.audit.context import join_key_ids  # not gate-safe: import on use
    from ts_cli.audit.engine.messages import NameList
    col_types = ctx.column_types(item["doc"])
    return NameList(k for k in join_key_ids((item.get("obj") or {}).get("on"))
                    if col_types.get(k, "").upper() in rules.STRING_TYPES)


@register("is_string_type")
def _is_string_type(item: dict, ctx: Any) -> bool:
    """RLS column reference: its warehouse `data_type` is a string type
    (rules.is_string_type — `.upper()` against VARCHAR/CHAR/STRING/TEXT, exactly; an
    unknown "" type is not a string)."""
    return rules.is_string_type((item.get("obj") or {}).get("data_type"))


@register("varchar_join_key_count")
def _varchar_join_key_count(item: dict, ctx: Any) -> int:
    """Join: how many of its keys are string-typed (see @varchar_join_keys)."""
    return len(_varchar_join_keys(item, ctx))


_IF_CALL = re.compile(r"\bif\s*\(", re.IGNORECASE)


@register("if_call_count")
def _if_call_count(item: dict, ctx: Any) -> int:
    """Formula: how many `if (` calls its `expr` makes."""
    return len(_IF_CALL.findall((item.get("obj") or {}).get("expr", "")))


def _reference_graph(formulas: list) -> Tuple[Dict[Any, list], Dict[Any, int]]:
    """A Model's formula reference graph, keyed by formula NAME.

    A cross-reference is written as the formula's id (`[formula_<name>]`), or — in a
    hand-built model — its display name; both resolve back to the name (BL-300). A
    formula's edges are the other formulas its `expr` references. Formulas sharing a
    name share a node, holding the references of the LAST of them that has any;
    `owner` maps each node to that formula's position in the list, so a rule reports a
    node once — even when one formula mapping is listed twice.
    """
    by_ref: Dict[Any, Any] = {}
    for f in formulas:
        fname = f.get("name", "")
        if not fname:
            continue
        by_ref[fname] = fname
        fid = f.get("id", "")
        if fid:
            by_ref[fid] = fname
    graph: Dict[Any, list] = {}
    owner: Dict[Any, int] = {}
    for i, f in enumerate(formulas):
        fname = f.get("name", "")
        refs = rules.BRACKET_REF.findall(f.get("expr", ""))
        cross = [by_ref[r] for r in refs if r in by_ref and by_ref[r] != fname]
        if cross:
            graph[fname] = cross
            owner[fname] = i
    return graph, owner


def _bfs_depth(graph: Dict[Any, list], start: Any) -> int:
    """Hops to the farthest node reachable from `start` (breadth first)."""
    visited: set = set()
    queue = [(start, 0)]
    max_d = 0
    while queue:
        node, d = queue.pop(0)
        if node in visited:
            continue
        visited.add(node)
        max_d = max(max_d, d)
        for nb in graph.get(node, []):
            queue.append((nb, d + 1))
    return max_d


@register("reference_chain_depth")
def _reference_chain_depth(item: dict, ctx: Any):
    """Formula: the longest chain of formula references starting at its node of the
    Model's reference graph (see _reference_graph). None — no value, so no finding —
    for a formula that references no other formula, or whose name another formula's
    references represent."""
    graph, owner = _reference_graph(_model_of(item).get("formulas") or [])
    name = (item.get("obj") or {}).get("name", "")
    if name not in owner or owner[name] != item.get("index"):
        return None
    return _bfs_depth(graph, name)
