"""Join-path equivalence between a Sisense data model and a target Model (pure, no I/O).

A widget's numbers depend on HOW its tables are joined, not only on which columns it reads.
Sisense joins a widget's tables along its relations, taking the shortest path; ThoughtSpot joins
them along the Model's many -> one joins. Binding the right column through a different path (a
direct join Sisense does not have, a second hop on another foreign key) returns different rows,
so a binding is carried only when the two paths are the SAME, hop for hop on the same columns.

Anything that cannot be decided is reported: no Sisense path, a tie between Sisense's shortest
paths (Sisense's own choice is then not known), no Model path, or more than one shortest Model
path (ThoughtSpot's choice is then not known).
"""
from __future__ import annotations

import re
from collections import deque

_MAX_HOPS = 6


def _norm(name: str) -> str:
    return re.sub(r"[\s_]+", "", (name or "").lower())


def sisense_graph(relations: list) -> dict:
    """Sisense table -> [(neighbour, column here, column there)], one-column relations only."""
    graph: dict = {}
    for rel in relations or []:
        ends = [(e.get("table"), e.get("column")) for e in rel.get("endpoints") or []]
        if len(ends) != 2 or not all(t for t, _ in ends):
            continue
        (ta, ca), (tb, cb) = ends
        graph.setdefault(ta, []).append((tb, ca, cb))
        graph.setdefault(tb, []).append((ta, cb, ca))
    return graph


def _shortest_paths(start, goal, neighbours) -> list:
    """Every shortest path start -> goal as a list of edges; [] when none within _MAX_HOPS."""
    paths, frontier, seen = [], deque([(start, [])]), {start: 0}
    while frontier:
        node, path = frontier.popleft()
        if paths and len(path) >= len(paths[0]):
            break
        if len(path) >= _MAX_HOPS:
            continue
        for edge in neighbours(node):
            nxt = edge[0]
            if nxt == goal:
                paths.append(path + [(node,) + edge])
            elif seen.get(nxt, len(path) + 1) >= len(path) + 1 and nxt not in {e[0] for e in path}:
                seen[nxt] = len(path) + 1
                frontier.append((nxt, path + [(node,) + edge]))
    return paths


def _path_count(start, goal, neighbours, limit: int = 2) -> int:
    """Simple paths start -> goal within _MAX_HOPS, counted up to ``limit``."""
    count, stack = 0, [(start, {start})]
    while stack and count < limit:
        node, seen = stack.pop()
        for edge in neighbours(node):
            nxt = edge[0]
            if nxt == goal:
                count += 1
            elif nxt not in seen and len(seen) < _MAX_HOPS:
                stack.append((nxt, seen | {nxt}))
    return count


def loop_problem(relations: list, tables: set) -> str:
    """The widget's Sisense tables relate in a loop among themselves: Sisense's join tree is then a
    tie between equally short trees, so which one it uses is not verified."""
    graph = sisense_graph(relations)
    edges = {frozenset((a, b)) for a in tables for b, _, _ in graph.get(a, []) if b in tables and b != a}
    if len(edges) < len(tables):          # a tree on n nodes has n - 1 edges; n or more means a loop
        return ""
    return (f"the widget's tables ({', '.join(sorted(tables))}) relate to each other in a loop in Sisense, so "
            "which joins it uses for this widget is not verified")


def one_hop_problem(target, relations: list, a_inst: str, b_inst: str, a_table: str, b_table: str) -> str:
    """Two tables Sisense relates directly: '' when the Model joins the bound copies by that same
    relation (either direction, same columns, one condition)."""
    if path_problem(target, relations, a_inst, b_inst, b_table) == "" and b_inst in {o for o, _ in target.joins.get(a_inst, [])}:
        return ""
    if path_problem(target, relations, b_inst, a_inst, a_table) == "" and a_inst in {o for o, _ in target.joins.get(b_inst, [])}:
        return ""
    return f"Sisense joins {a_table} and {b_table} directly, which the target model does not join the same way"


def _sisense_table(graph: dict, inst: str, base: str):
    """The Sisense table a Model instance stands for: named like the instance, else its base."""
    for name in (inst, base):
        hit = next((t for t in graph if _norm(t) == _norm(name)), None)
        if hit:
            return hit
    return None


def _model_edges(target, node: str) -> list:
    """(next instance, fk column, pk column) for each many -> one join out of ``node``."""
    return [(one, fk, target.join_pk.get((node, one, fk))) for one, fk in target.joins.get(node, [])]


def _same_hop(target, m_edge: tuple, s_edge: tuple, graph: dict) -> bool:
    inst, nxt, fk, pk = m_edge[0], m_edge[1], m_edge[2], m_edge[3]
    if (inst, nxt, fk) in target.composite:       # a join on several conditions is not one relation
        return False
    s_from, s_to, s_fk, s_pk = s_edge
    if _sisense_table(graph, inst, target.base_of.get(inst)) != s_from:
        return False
    if _sisense_table(graph, nxt, target.base_of.get(nxt)) != s_to:
        return False
    return _same_col(target, inst, fk, s_fk) and _same_col(target, nxt, pk, s_pk)


def _same_col(target, inst: str, model_col, sis_col) -> bool:
    if model_col is None or sis_col is None:
        return False
    if target.base_of.get(inst) in target.table_cols:     # the Table is known: only its mapping counts
        mapped = target._table_column(inst, sis_col)
        return bool(mapped) and _norm(model_col) == _norm(mapped)
    return _norm(model_col) == _norm(sis_col)


def path_problem(target, relations: list, fact: str, inst: str, sis_table: str) -> str:
    """Why the Model's path fact -> inst is not Sisense's path to ``sis_table``, or ''."""
    if inst == fact:
        return ""
    graph = sisense_graph(relations)
    src = _sisense_table(graph, fact, target.base_of.get(fact))
    if src is None or sis_table not in graph:
        return (f"{fact} or {sis_table} is not in a Sisense relation, so the join path to {sis_table} cannot "
                "be compared with Sisense's")
    if src == sis_table:                       # the column is on the fact itself in Sisense
        return "" if inst == fact else (f"Sisense reads {sis_table} on the fact itself, but the binding reads "
                                        f"{inst}, joined from {fact}")
    s_paths = _shortest_paths(src, sis_table, lambda n: graph.get(n, []))
    m_paths = _shortest_paths(fact, inst, lambda n: _model_edges(target, n))
    if not s_paths:
        return f"Sisense has no relation path from {src} to {sis_table}"
    if len(s_paths) > 1:
        return f"Sisense has {len(s_paths)} equally short paths from {src} to {sis_table}, so its choice is not known"
    if len(m_paths) != 1:
        return (f"the target model has {'no' if not m_paths else len(m_paths)} shortest join path from {fact} to "
                f"{inst}, so ThoughtSpot's path cannot be compared")
    if _path_count(fact, inst, lambda n: _model_edges(target, n)) > 1:
        return (f"the target model reaches {inst} from {fact} more than one way, so which join ThoughtSpot takes "
                "is not verified")
    s_path, m_path = s_paths[0], m_paths[0]
    if len(s_path) == len(m_path) and all(_same_hop(target, m, s, graph) for m, s in zip(m_path, s_path)):
        return ""
    return (f"the target model joins {fact} to {inst} through {_describe_model(m_path)}, while Sisense joins "
            f"{src} to {sis_table} through {_describe_sisense(s_path)}")


def _describe_model(path: list) -> str:
    return " > ".join(f"{a}.{fk} = {b}.{pk}" for a, b, fk, pk in path)


def _describe_sisense(path: list) -> str:
    return " > ".join(f"{a}.{ca} = {b}.{cb}" for a, b, ca, cb in path)
