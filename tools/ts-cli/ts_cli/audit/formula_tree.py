"""A Model's formula dependency tree, for the report's Formulas view (audit v2 roadmap
PR 3.2). Pure; reads the Model TML only.

Each formula is a node: its MEASURE / ATTRIBUTE kind, whether it is hidden, and the
name people search it by, all read from the `columns[]` entry that surfaces it (by
`formula_id`); what it uses; and how many formulas use it. A bracket reference outside
a quoted literal resolves, in order, to a formula (by id or `formulas[].name`, through
`tml.formula_reference_index`, which also resolves the display name of the column that
surfaces it — the index P17 and P2 share, BL-504), a parameter (`parameters[].name`), else a column
(`TABLE::COL`, or a bare Model column name). Literals are split off with
`formula_translate.refs.split_literals`, which keeps a `[...]` reference whole even when
the name inside it holds a quote (BL-369). The roots are the formulas nothing uses,
typically the measures people search on. A cycle no root reaches is rooted where it is
entered: at a formula everything upstream of which lies in its own cycle, so no formula
is lost; the view guards against walking a cycle. A formula or column id that is not a
string is ignored (malformed TML must not end a narrow run, BL-501).
"""
from __future__ import annotations

from typing import Any, Dict, List

from ts_cli.audit.engine import tml


def _surfacing_columns(model: dict) -> Dict[Any, dict]:
    out: Dict[Any, dict] = {}
    for c in model.get("columns") or []:
        fid = c.get("formula_id") if isinstance(c, dict) else None
        if isinstance(fid, str) and fid and fid not in out:
            out[fid] = c
    return out


def _parameter_names(model: dict) -> set:
    return {str(p.get("name")) for p in model.get("parameters") or []
            if isinstance(p, dict) and p.get("name")}


def _resolve(ref: str, by_ref: Dict[Any, Any], params: set) -> dict:
    target = by_ref.get(ref)
    if target:
        return {"formula": target}
    if ref in params:
        return {"parameter": ref}
    return {"column": ref}


def _uses(expr: Any, by_ref: Dict[Any, Any], params: set, own: str) -> List[dict]:
    """What one expression refers to, in order, each once (see the module docstring)."""
    seen, out = set(), []
    for ref in tml.expr_refs(str(expr or "")):
        item = _resolve(ref, by_ref, params)
        key = tuple(item.items())
        if item.get("formula") == own or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _node(formula: dict, column: Any, by_ref: Dict[Any, Any], params: set) -> dict:
    props = tml.mapping(column, "properties") if column else {}
    label = column.get("name") if column and column.get("name") else formula["name"]
    return {"name": formula["name"], "label": str(label),
            "kind": str(props.get("column_type") or "").upper() or None,
            "hidden": column is None or bool(props.get("is_hidden")),
            "uses": _uses(formula.get("expr"), by_ref, params, formula["name"]),
            "used_by": 0}


def _reachable(roots: List[str], nodes: Dict[str, dict]) -> set:
    seen, stack = set(), list(roots)
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        stack += [u["formula"] for u in nodes[name]["uses"] if "formula" in u]
    return seen


def _upstream(name: str, users: Dict[str, set]) -> set:
    seen, stack = set(), list(users[name])
    while stack:
        n = stack.pop()
        if n not in seen:
            seen.add(n)
            stack += users[n]
    return seen


def _cycle_roots(nodes: Dict[str, dict], reached: set) -> List[str]:
    """Roots for what no root reaches (only cycles, and what they use): a formula whose
    every unreached upstream user is in its own cycle (reachable from it), so neither its
    cycle nor a cycle above it leads into it; the first such, in formula order, per cycle."""
    users: Dict[str, set] = {n: set() for n in nodes}
    for n, node in nodes.items():
        for u in node["uses"]:
            if "formula" in u:
                users[u["formula"]].add(n)
    roots: List[str] = []
    for name in nodes:
        if name in reached:
            continue
        own = _reachable([name], nodes)
        if (_upstream(name, users) - reached) <= own:
            roots.append(name)
            reached |= own
    return roots


def formula_tree(model: dict) -> dict:
    """`{"nodes": [...], "roots": [names]}` for a Model TML body; nodes in formula order.
    A node: `name` (its `formulas[].name`, the key), `label` (the surfacing column's name,
    which people search by, else `name`), `kind` ("MEASURE", "ATTRIBUTE" or None when no
    column surfaces it), `hidden` (its column is hidden, or no column surfaces it),
    `uses` (`{"formula": name}` / `{"parameter": name}` / `{"column": ref}`) and
    `used_by` (how many formulas use it). Formulas sharing a name are one node (the
    first)."""
    formulas = [f if isinstance(f.get("id"), (str, type(None))) else {**f, "id": None}
                for f in (model.get("formulas") or [])
                if isinstance(f, dict) and isinstance(f.get("name"), str) and f["name"]]
    columns = _surfacing_columns(model)
    by_ref = tml.formula_reference_index(formulas, model.get("columns") or [])
    params = _parameter_names(model)
    nodes: Dict[str, dict] = {}
    for f in formulas:
        if f["name"] not in nodes:
            nodes[f["name"]] = _node(f, columns.get(f.get("id")), by_ref, params)
    for node in nodes.values():
        for use in node["uses"]:
            if "formula" in use:
                nodes[use["formula"]]["used_by"] += 1
    roots = [n for n, node in nodes.items() if node["used_by"] == 0]
    roots += _cycle_roots(nodes, _reachable(roots, nodes))
    return {"nodes": list(nodes.values()), "roots": roots}
