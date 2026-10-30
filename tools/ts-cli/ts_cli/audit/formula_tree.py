"""A Model's formula dependency tree, for the report's Formulas view (audit v2 roadmap
PR 3.2). Pure; reads the Model TML only.

Each formula is a node: its MEASURE / ATTRIBUTE kind and whether it is hidden, both
read from the `columns[]` entry that surfaces it (by `formula_id`), what it uses (other
formulas, by id or display name, through `tml.formula_ref_index`, the reading P17
shares; and `[TABLE::COL]` columns), and how many formulas use it. The roots are the
formulas nothing uses, typically the measures people search on. A formula reachable
from no root (every formula in a cycle is used by another) is a root too, so none is
lost (its first formula, so the rest hang below it); the view guards against walking a
cycle.
"""
from __future__ import annotations

from typing import Any, Dict, List

from ts_cli.audit.engine import tml


def _surfacing_columns(model: dict) -> Dict[Any, dict]:
    out: Dict[Any, dict] = {}
    for c in model.get("columns") or []:
        if isinstance(c, dict) and c.get("formula_id") and c["formula_id"] not in out:
            out[c["formula_id"]] = c
    return out


def _uses(expr: Any, by_ref: Dict[Any, Any], own: str) -> List[dict]:
    """What one expression refers to, in order, each once: a formula by name, else a
    column (`TABLE::COL`, or a bare Model column name)."""
    seen, out = set(), []
    for ref in tml.BRACKET_REF.findall(str(expr or "")):
        ref = ref.strip()
        target = by_ref.get(ref)
        item = {"formula": target} if target else {"column": ref}
        key = tuple(item.items())
        if target == own or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _node(formula: dict, column: Any, by_ref: Dict[Any, Any]) -> dict:
    props = tml.mapping(column, "properties") if column else {}
    return {"name": formula["name"],
            "kind": str(props.get("column_type") or "").upper() or None,
            "hidden": column is None or bool(props.get("is_hidden")),
            "uses": _uses(formula.get("expr"), by_ref, formula["name"]), "used_by": 0}


def _reachable(roots: List[str], nodes: Dict[str, dict]) -> set:
    seen, stack = set(), list(roots)
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        stack += [u["formula"] for u in nodes[name]["uses"] if "formula" in u]
    return seen


def formula_tree(model: dict) -> dict:
    """`{"nodes": [...], "roots": [names]}` for a Model TML body; nodes in formula order.
    A node: `name`, `kind` ("MEASURE", "ATTRIBUTE" or None when no column surfaces it),
    `hidden` (its column is hidden, or no column surfaces it), `uses` (list of
    `{"formula": name}` / `{"column": ref}`) and `used_by` (how many formulas use it).
    Formulas sharing a name are one node (the first)."""
    formulas = [f for f in (model.get("formulas") or [])
                if isinstance(f, dict) and f.get("name")]
    by_ref = tml.formula_ref_index(formulas)
    columns = _surfacing_columns(model)
    nodes: Dict[str, dict] = {}
    for f in formulas:
        nodes.setdefault(f["name"], _node(f, columns.get(f.get("id")), by_ref))
    for node in nodes.values():
        for use in node["uses"]:
            if "formula" in use:
                nodes[use["formula"]]["used_by"] += 1
    roots = [n for n, node in nodes.items() if node["used_by"] == 0]
    reached = _reachable(roots, nodes)
    for name in nodes:  # a cycle reachable from no root: its first formula roots it
        if name not in reached:
            roots.append(name)
            reached |= _reachable([name], nodes)
    return {"nodes": list(nodes.values()), "roots": roots}
