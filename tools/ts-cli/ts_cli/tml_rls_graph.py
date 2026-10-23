"""A Model's join graph plus the joins its Tables' RLS rules use.

ThoughtSpot validates a Model's own joins for cycles at import (`tml_join_graph`), but
an RLS rule's joins are only applied when a query runs. When a rule on a table walks
back into the Model's graph — the Model joins `bridge -> users`, the rule on `users`
joins out to `bridge` — query generation sees `bridge` with two roots and fails with
"Guid Mismatch" (BACH 12325). Root-caused on a support case; the shape is confirmed
from that case's exported TML.

How a rule's joins appear in Table TML (live sighting 2026-10-23)::

    rls_rules:
      joins:                     # each one names a `joins_with` join on this Table
      - {name: users_to_bridge, source: users, destination: bridge, type: INNER}
      table_paths:
      - id: bridge_1
        table: bridge
        join_path: [{join: [users_to_bridge]}]   # ordered segments
      rules:
      - expr: "[bridge_1::group_id] in ts_var(...)"

Two decisions, from the design (docs/superpowers/specs/2026-10-23-rls-join-cycles-design.md):

- A join counts only when it lies on a path that some rule's `expr` references
  (`[path_id::...]`); anything else cannot put a table in a query.
- Direction comes from walking the path outward from the secured table, not from the
  join's `source`/`destination` labels, so it does not matter which table declared
  the table-level join. An RLS join has no cardinality, so the Model's MANY -> ONE
  convention cannot apply.

Only cycles are reported. A second route through an RLS join (a diamond) is not shown
to fail at query time, and the healthy star shape has one. Pure functions, no I/O.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ts_cli.tml_join_graph import JoinGraph, _shortest_path, node_id, strongly_connected

_PATH_REF_RE = re.compile(r"\[([^\[\]:]+)::")


@dataclass(frozen=True)
class RlsEdge:
    frm: str      # Model node id the rule's path leaves
    to: str       # Model node id it reaches
    table: str    # the secured physical table (whose rls_rules declare the join)
    join: str     # the RLS join's name


def _nodes_by_physical(model_tables: list) -> tuple[dict[str, list[str]], dict[str, str]]:
    """physical name (lower) -> Model node ids; and lower -> display name."""
    nodes: dict[str, list[str]] = {}
    display: dict[str, str] = {}
    for t in model_tables or []:
        if isinstance(t, dict) and t.get("name"):
            key = str(t["name"]).lower()
            nodes.setdefault(key, []).append(node_id(t))
            display.setdefault(key, str(t["name"]))
    return nodes, display


def _referenced_path_ids(rules) -> set:
    ids: set = set()
    for rule in rules or []:
        if isinstance(rule, dict):
            ids.update(m.strip() for m in _PATH_REF_RE.findall(str(rule.get("expr") or "")))
    return ids


def _segment_joins(path: dict) -> list:
    names = []
    for seg in path.get("join_path") or []:
        if isinstance(seg, dict):
            names.extend(seg.get("join") or [])
    return names


def _walk(secured: str, path: dict, joins: dict):
    """The path's hops as (from, to, join), walked outward from `secured` (all lower
    case), or a string saying why the path cannot be walked."""
    hops, cur = [], secured
    for name in _segment_joins(path):
        j = joins.get(name)
        if j is None:
            return f"join '{name}' is not in its rls_rules.joins"
        ends = (str(j.get("source") or "").lower(), str(j.get("destination") or "").lower())
        if cur not in ends:
            return f"join '{name}' does not touch '{cur}'"
        nxt = ends[1] if ends[0] == cur else ends[0]
        hops.append((cur, nxt, name))
        cur = nxt
    return hops


def _table_rls_edges(secured: str, rls: dict, nodes: dict, label: str):
    joins = {j["name"]: j for j in rls.get("joins") or []
             if isinstance(j, dict) and j.get("name")}
    used = _referenced_path_ids(rls.get("rules"))
    edges, notes = set(), []
    for path in rls.get("table_paths") or []:
        if not isinstance(path, dict) or path.get("id") not in used:
            continue
        hops = _walk(secured, path, joins)
        if isinstance(hops, str):
            notes.append(f"RLS on '{label}': path '{path.get('id')}' {hops} — path skipped")
            continue
        for cur, nxt, name in hops:
            for a in nodes.get(cur, []):
                for b in nodes.get(nxt, []):
                    edges.add(RlsEdge(a, b, label, name))
    return edges, notes


def rls_edges(model_tables: list, tables: dict) -> tuple[list[RlsEdge], list[str]]:
    """Edges the Model's Tables' RLS rules add, and a note per path that was skipped.

    `tables` maps a physical table name (any case) to its Table TML `table:` body. An
    RLS edge runs from every Model node of one physical table to every node of the
    next: the rule applies wherever the table is queried. Tables the Model does not
    include contribute no node, so an edge to or from them is dropped.
    """
    nodes, display = _nodes_by_physical(model_tables)
    bodies = {str(k).lower(): v for k, v in (tables or {}).items() if isinstance(v, dict)}
    edges: set = set()
    notes: list[str] = []
    for phys in sorted(nodes):
        rls = (bodies.get(phys) or {}).get("rls_rules")
        if isinstance(rls, dict):
            e, n = _table_rls_edges(phys, rls, nodes, display[phys])
            edges |= e
            notes.extend(n)
    return sorted(edges, key=_edge_key), notes


def _edge_key(e: RlsEdge):
    return (e.table.lower(), e.join, e.frm, e.to)


def _combined_adjacency(graph: JoinGraph, edges: list[RlsEdge]) -> dict[str, list[str]]:
    adj = {n: set(s) for n, s in graph.adjacency().items()}
    for e in edges:
        if e.frm != e.to:
            adj.setdefault(e.frm, set()).add(e.to)
            adj.setdefault(e.to, set())
    return {n: sorted(s) for n, s in adj.items()}


def _model_joins_on(graph: JoinGraph, cycle: list[str]) -> list[str]:
    pairs = set(zip(cycle[1:], cycle[2:]))
    return sorted({e.name for e in graph.edges
                   if not graph.is_self_join(e) and e.arrow in pairs})


def rls_join_cycles(model_tables: list, tables: dict) -> list[dict]:
    """Directed cycles in the Model's join graph plus its RLS joins, one per RLS edge
    that closes one: ``{"cycle": [u, v, ..., u], "rls_edge": RlsEdge,
    "model_joins": [Model join names on the way back]}``, ordered by the RLS edge."""
    graph = JoinGraph(model_tables)
    edges, _notes = rls_edges(model_tables, tables)
    adj = _combined_adjacency(graph, edges)
    comp_of = {}
    for comp in strongly_connected(adj):
        for n in comp:
            comp_of[n] = frozenset(comp)
    found = []
    for e in edges:
        comp = comp_of.get(e.frm)
        if e.frm == e.to or comp is None or e.to not in comp:
            continue
        back = _shortest_path(adj, e.to, e.frm, within=comp)
        if back:
            cycle = [e.frm] + back
            found.append({"cycle": cycle, "rls_edge": e,
                          "model_joins": _model_joins_on(graph, cycle)})
    return found
