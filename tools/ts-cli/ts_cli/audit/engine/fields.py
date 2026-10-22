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

from typing import Any, Callable, Dict

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
