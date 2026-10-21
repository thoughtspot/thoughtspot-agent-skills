"""A Model's join graph, as ThoughtSpot validates it — plus the opt-in join-key rule.

The graph is DIRECTED: an edge runs from a `model_tables[]` entry to its `joins[].with`
target, and every entry is its own node (`alias` when present, else `id`, else `name` —
the same identity `tml_lint._node_id` uses). Direction is the whole point. A loop that
only appears when direction is ignored — two fact tables sharing a date and a product
dimension — is the ordinary multi-fact shape and imports fine; ThoughtSpot rejects only
a loop that follows the arrows, or two arrow-following routes between one pair.

Live-probed on se-thoughtspot 2026-10-21 with throwaway Models over existing tables
(nothing persisted), `VALIDATE_ONLY` and `ALL_OR_NONE` agreeing on every shape:

| Shape | Server response |
|---|---|
| directed cycle, including A -> B plus B -> A | error 13123 "Schema validation failed" |
| two directed routes to one table (a diamond) | error 13124 "Schema validation failed" |
| a table joined to itself, aliased or not | 13125 / 14565 "INTERNAL ERROR" |
| `on:` naming a third table, or an alias | "Invalid srcTable or destTable in join expression" |
| two facts sharing dimensions (undirected loop only) | OK |
| `on:` sides in either order | OK |

The server's text never says which joins are at fault — the code is the only signal —
so the rules in `tml_lint.py` that use this module exist to name them.

Pure functions, no I/O. The rule functions that EMIT invariant findings live in
`tml_lint.py` (its CANONICAL-RULE-SET gate reads that file alone); this module holds the
graph mechanics they share and `lint_required_join_key`, which is opt-in and so is not
an invariant.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# `[TABLE::COL]` inside a join `on:` clause.
_JOIN_ON_REF_RE = re.compile(r"\[([^\[\]]+?)::([^\[\]]+)\]")
# One equality term: `[T1::C1] = [T2::C2]`, tolerating the optional wrapping parens.
_JOIN_ON_EQ_RE = re.compile(r"\[([^\[\]]+?)::([^\[\]]+)\]\s*=\s*\[([^\[\]]+?)::([^\[\]]+)\]")


@dataclass(frozen=True)
class Edge:
    frm: str          # node id of the source entry
    to: str           # node id of the target entry
    name: str         # join name, for messages
    join: dict        # the raw joins[] entry


def node_id(entry: dict) -> str:
    return entry.get("alias") or entry.get("id") or entry.get("name") or "?"


class JoinGraph:
    """Nodes, physical names and edges of one Model. Unresolvable `with` targets are
    skipped — a join to a table the Model does not declare is XREF's business."""

    def __init__(self, model_tables: list):
        self.physical: dict[str, str] = {}
        self._entries: list[dict] = []
        for t in model_tables or []:
            if isinstance(t, dict):
                self.physical.setdefault(node_id(t), t.get("name") or "?")
                self._entries.append(t)
        self._by_lower = {n.lower(): n for n in self.physical}
        self.edges: list[Edge] = []
        for t in self._entries:
            frm = node_id(t)
            for j in t.get("joins") or []:
                if not isinstance(j, dict) or not j.get("with"):
                    continue
                to = self.resolve(j["with"])
                if to is None:
                    continue
                name = j.get("name") or j.get("referencing_join") or "(unnamed)"
                self.edges.append(Edge(frm, to, name, j))

    def resolve(self, ref: str):
        if ref in self.physical:
            return ref
        return self._by_lower.get(str(ref).lower())

    def is_self_join(self, e: Edge) -> bool:
        return self.physical[e.frm].lower() == self.physical[e.to].lower()

    def adjacency(self, skip_self: bool = True) -> dict[str, list[str]]:
        """Deduplicated successors, sorted for deterministic output. Parallel edges
        collapse — two joins between one ordered pair is I14's finding, not a cycle's."""
        adj: dict[str, set] = {n: set() for n in self.physical}
        for e in self.edges:
            if skip_self and self.is_self_join(e):
                continue
            adj[e.frm].add(e.to)
        return {n: sorted(s) for n, s in adj.items()}


def strongly_connected(adj: dict[str, list[str]]) -> list[list[str]]:
    """Tarjan's SCCs, iterative (a deep join chain must not hit the recursion limit)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set = set()
    stack: list[str] = []
    out: list[list[str]] = []
    counter = 0
    for root in sorted(adj):
        if root in index:
            continue
        work = [(root, iter(adj[root]))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            v, it = work[-1]
            advanced = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on_stack.add(w)
                    work.append((w, iter(adj[w])))
                    advanced = True
                    break
                if w in on_stack:
                    low[v] = min(low[v], index[w])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                out.append(sorted(comp))
    return out


def _shortest_path(adj: dict[str, list[str]], src: str, dst: str, within=None):
    """BFS path src -> dst (inclusive), optionally restricted to the node set `within`."""
    prev = {src: None}
    queue = [src]
    for v in queue:
        if v == dst:
            break
        for w in adj.get(v, []):
            if w not in prev and (within is None or w in within):
                prev[w] = v
                queue.append(w)
    if dst not in prev:
        return None
    path, cur = [], dst
    while cur is not None:
        path.append(cur)
        cur = prev[cur]
    return path[::-1]


def directed_cycles(graph: JoinGraph) -> list[list[str]]:
    """One representative cycle per strongly connected component of two or more nodes,
    written closed (`[A, B, A]`). Self-joins are excluded — they are their own rule."""
    adj = graph.adjacency()
    cycles = []
    for comp in strongly_connected(adj):
        if len(comp) < 2:
            continue
        members = set(comp)
        start = comp[0]
        # the shortest way back to `start` from any of its in-component successors
        best = None
        for nxt in adj[start]:
            if nxt not in members:
                continue
            back = _shortest_path(adj, nxt, start, within=members)
            if back and (best is None or len(back) < len(best)):
                best = back
        if best:
            cycles.append([start] + best)
    return cycles


def ambiguous_paths(graph: JoinGraph) -> list[tuple[str, str, list[str], list[str]]]:
    """Merge points reached by two different directed routes from one ancestor.

    Returns ``(source, target, path_a, path_b)`` — one per target. A target `v` is
    ambiguous when two of its distinct predecessors share an ancestor (each counting as
    its own ancestor, so a triangle A->B->C plus A->C is caught). The reported source is
    the LOWEST shared ancestor, so a diamond deep in a chain is reported once at its
    split point rather than again for every table above it.

    A directed cycle is collapsed to one node first, named by its members joined with
    `/`: the cycle is reported on its own, path counting through a loop is meaningless,
    and a second route that merely passes through a cycle is still a second route.
    """
    dag = _condense(graph.adjacency())
    anc = _Ancestors(dag)
    found = []
    for v in sorted(dag):
        hit = _first_converging_pair(sorted(set(anc.preds[v])), anc)
        if not hit:
            continue
        p1, p2, shared = hit
        src = _lowest(shared, anc)
        found.append((src, v, _shortest_path(dag, src, p1) + [v],
                      _shortest_path(dag, src, p2) + [v]))
    return found


def _condense(adj: dict[str, list[str]]) -> dict[str, list[str]]:
    """The condensation DAG: each strongly connected component becomes one node, named
    by its sorted members joined with `/` (a single table keeps its own name)."""
    label: dict[str, str] = {}
    for comp in strongly_connected(adj):
        for n in comp:
            label[n] = "/".join(comp)
    out: dict[str, set] = {lbl: set() for lbl in label.values()}
    for v, ws in adj.items():
        for w in ws:
            if label[v] != label[w]:
                out[label[v]].add(label[w])
    return {v: sorted(ws) for v, ws in out.items()}


class _Ancestors:
    """Predecessors of a DAG and memoised ancestor sets (each node its own ancestor)."""

    def __init__(self, dag: dict[str, list[str]]):
        self.preds: dict[str, list[str]] = {v: [] for v in dag}
        for v, ws in dag.items():
            for w in ws:
                self.preds[w].append(v)
        self._cache: dict[str, set] = {}

    def of(self, v: str) -> set:
        if v not in self._cache:
            seen, todo = {v}, [v]
            while todo:
                for p in self.preds[todo.pop()]:
                    if p not in seen:
                        seen.add(p)
                        todo.append(p)
            self._cache[v] = seen
        return self._cache[v]


def _first_converging_pair(preds: list[str], anc: _Ancestors):
    """The first two predecessors with a common ancestor, and that shared set."""
    for i, p1 in enumerate(preds):
        for p2 in preds[i + 1:]:
            shared = anc.of(p1) & anc.of(p2)
            if shared:
                return p1, p2, shared
    return None


def _lowest(shared: set, anc: _Ancestors) -> str:
    """The shared ancestor nearest the merge point: one that is no other's ancestor."""
    lowest = sorted(u for u in shared if not any(u in anc.of(c) for c in shared if c != u))
    return lowest[0] if lowest else sorted(shared)[0]


def on_clause_tables(on: str) -> list[str]:
    """Table names referenced in an `on:` clause, in order, de-duplicated."""
    seen: list[str] = []
    for table, _col in _JOIN_ON_REF_RE.findall(on or ""):
        t = table.strip()
        if t not in seen:
            seen.append(t)
    return seen


def _equates_key(on: str, key: str, tables: set) -> bool:
    """True when some `[T1::key] = [T2::key]` term spans both joined tables."""
    for t1, c1, t2, c2 in _JOIN_ON_EQ_RE.findall(on or ""):
        if c1.strip().lower() == c2.strip().lower() == key.lower():
            if {t1.strip().lower(), t2.strip().lower()} == tables:
                return True
    return False


def table_join_index(tables: dict) -> dict[tuple[str, str], str]:
    """(physical table lower, join name) -> `on:` for every `joins_with[]` entry in a
    batch's Table TMLs, so a Model join that only REFERENCES a Table join can still be
    checked. `tables` maps a table name to its parsed `table:` dict."""
    idx: dict[tuple[str, str], str] = {}
    for tname, table in (tables or {}).items():
        if not isinstance(table, dict):
            continue
        for jw in table.get("joins_with") or []:
            if isinstance(jw, dict) and jw.get("name") and jw.get("on"):
                idx[(str(tname).lower(), jw["name"])] = jw["on"]
    return idx


def lint_required_join_key(model_tml: dict, keys: list, exempt: list = (),
                           table_joins: dict = None) -> list[str]:
    """Opt-in rule: every join must equate each column in `keys` on both tables.

    For a warehouse that holds every tenant in one schema, a join that matches on
    `order_id` alone matches orders across tenants whenever two tenants reuse an id.
    The tenant key belongs in every join, as `[A::customer_id] = [B::customer_id]`.

    `exempt` names tables (physical or alias, case-insensitive) that legitimately carry
    no tenant key — shared reference tables such as a calendar or a country list; a join
    touching one is skipped. `table_joins` is `table_join_index(...)` for the batch, used
    when a Model join only references a Table TML join and carries no `on:` of its own.

    Not an invariant: ThoughtSpot imports such a Model happily. It is a convention a
    team opts into, so its findings carry a `JOIN-KEY:` prefix rather than an `I<N>:` id.
    """
    model = (model_tml or {}).get("model")
    if not isinstance(model, dict) or not keys:
        return []
    graph = JoinGraph(model.get("model_tables") or [])
    skip = {str(x).lower() for x in exempt or ()}
    findings: list[str] = []
    for e in graph.edges:
        if graph.is_self_join(e):
            continue  # I18 already rejects it
        ends = {e.frm.lower(), e.to.lower(),
                graph.physical[e.frm].lower(), graph.physical[e.to].lower()}
        if ends & skip:
            continue
        findings.extend(_join_key_findings(graph, e, keys, table_joins or {}))
    return findings


def _join_on(graph: JoinGraph, e: Edge, table_joins: dict):
    """The join's `on:` — inline, else the referenced Table TML join. A referenced join
    can be declared on either table's TML, so both are looked up."""
    on = e.join.get("on")
    ref = e.join.get("referencing_join")
    if on or not ref:
        return on
    for table in (graph.physical[e.frm], graph.physical[e.to]):
        on = table_joins.get((table.lower(), ref))
        if on:
            return on
    return None


def _join_key_findings(graph: JoinGraph, e: Edge, keys: list, table_joins: dict) -> list[str]:
    label = f"join '{e.name}' ({e.frm} -> {e.to})"
    on = _join_on(graph, e, table_joins)
    if not on:
        return [
            f"JOIN-KEY: {label} has no on: clause in the Model and its Table TML is "
            f"not in this batch, so the join key cannot be checked. Lint the Table "
            f"TML alongside the Model, or --exempt one of its tables."
        ]
    pf, pt = graph.physical[e.frm], graph.physical[e.to]
    return [
        f"JOIN-KEY: {label} does not equate '{key}' on both tables (on: {on}) — rows "
        f"from different tenants can match. Add `AND [{pf}::{key}] = [{pt}::{key}]`, "
        f"or --exempt the table if it is shared reference data with no '{key}'."
        for key in keys if not _equates_key(on, key, {pf.lower(), pt.lower()})
    ]
