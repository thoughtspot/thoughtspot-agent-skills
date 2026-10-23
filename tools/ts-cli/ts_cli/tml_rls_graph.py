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


def _as_list(value) -> list:
    """A list as given; a lone string or dict as a one-item list; anything else none —
    hand-written TML must not crash a lint or an audit."""
    if isinstance(value, list):
        return value
    return [value] if isinstance(value, (str, dict)) else []


def _name(value) -> str:
    return value if isinstance(value, str) else ""


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
    for rule in _as_list(rules):
        if isinstance(rule, dict):
            ids.update(m.strip() for m in _PATH_REF_RE.findall(str(rule.get("expr") or "")))
    return ids


def _segment_joins(path: dict) -> list:
    names = []
    for seg in _as_list(path.get("join_path")):
        if isinstance(seg, dict):
            names.extend(_as_list(seg.get("join")))
    return names


def _walk(secured: str, path: dict, joins: dict):
    """The path's hops as (from, to, join), walked outward from `secured` (all lower
    case), or a string saying why the path cannot be walked."""
    hops, cur = [], secured
    for name in _segment_joins(path):
        j = joins.get(name) if isinstance(name, str) else None
        if j is None:
            return f"join '{name}' is not in its rls_rules.joins"
        ends = (_name(j.get("source")).lower(), _name(j.get("destination")).lower())
        if cur not in ends:
            return f"join '{name}' does not touch '{cur}'"
        nxt = ends[1] if ends[0] == cur else ends[0]
        hops.append((cur, nxt, name))
        cur = nxt
    return hops


def _table_rls_edges(secured: str, rls: dict, nodes: dict, label: str, start: list):
    """Edges from one secured table's rule. The first hop leaves only `start` — the
    Model entries that ARE this table — so a same-named other table never inherits it."""
    joins = {j["name"]: j for j in _as_list(rls.get("joins"))
             if isinstance(j, dict) and isinstance(j.get("name"), str)}
    used = _referenced_path_ids(rls.get("rules"))
    edges, notes = set(), []
    for path in _as_list(rls.get("table_paths")):
        if not isinstance(path, dict) or not isinstance(path.get("id"), str) \
                or path["id"] not in used:
            continue
        hops = _walk(secured, path, joins)
        if isinstance(hops, str):
            notes.append(f"RLS on '{label}': path '{path['id']}' {hops} — path skipped")
            continue
        for i, (cur, nxt, name) in enumerate(hops):
            if cur == nxt:
                continue  # a join from a table to itself adds no edge
            for a in (start if i == 0 else nodes.get(cur, [])):
                for b in nodes.get(nxt, []):
                    edges.add(RlsEdge(a, b, label, name))
    return edges, notes


def _by_name(tables: dict):
    bodies = {str(k).lower(): v for k, v in (tables or {}).items() if isinstance(v, dict)}
    return lambda entry: bodies.get(str(entry.get("name") or "").lower())


def _secured_groups(model_tables: list, table_of) -> list:
    """(physical name lower, display name, rls_rules, [node ids]) per distinct Table
    body carrying RLS, in Model order."""
    groups: dict[int, tuple] = {}
    for t in model_tables or []:
        if not isinstance(t, dict) or not t.get("name"):
            continue
        body = table_of(t)
        rls = body.get("rls_rules") if isinstance(body, dict) else None
        if isinstance(rls, dict):
            key = id(body)
            if key not in groups:
                groups[key] = (str(t["name"]).lower(), str(t["name"]), rls, [])
            groups[key][3].append(node_id(t))
    return list(groups.values())


def rls_edges(model_tables: list, tables: dict, table_of=None) -> tuple[list[RlsEdge], list[str]]:
    """Edges the Model's Tables' RLS rules add, and a note per path that was skipped.

    `table_of(entry)` returns a Model entry's Table TML `table:` body (or None); by
    default it matches `tables` — physical name (any case) -> body — by the entry's
    `name`. An audit passes one that resolves by `fqn`, so two different tables that
    share a name stay apart. The rule's first hop leaves the entries that are the
    secured table; later hops reach every Model node of the next physical table (the
    rule applies wherever that table is queried). Tables the Model does not include
    contribute no node, so an edge to or from them is dropped.
    """
    nodes, _display = _nodes_by_physical(model_tables)
    edges: set = set()
    notes: list[str] = []
    for phys, label, rls, start in _secured_groups(model_tables, table_of or _by_name(tables)):
        e, n = _table_rls_edges(phys, rls, nodes, label, start)
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
    # An inline join often has no `name` (JoinGraph labels it "(unnamed)"): the cycle's
    # table path already says where it runs, so only named joins are listed.
    return sorted({e.name for e in graph.edges
                   if not graph.is_self_join(e) and e.arrow in pairs
                   and (e.join.get("name") or e.join.get("referencing_join"))})


def rls_join_cycles(model_tables: list, tables: dict, table_of=None,
                    notes: list = None) -> list[dict]:
    """Directed cycles in the Model's join graph plus its RLS joins, one per RLS edge
    that closes one: ``{"cycle": [u, v, ..., u], "rls_edge": RlsEdge,
    "model_joins": [Model join names on the way back]}``, ordered by the RLS edge.
    Pass a list as `notes` to collect the paths that could not be walked."""
    graph = JoinGraph(model_tables)
    edges, skipped = rls_edges(model_tables, tables, table_of)
    if notes is not None:
        notes.extend(skipped)
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
