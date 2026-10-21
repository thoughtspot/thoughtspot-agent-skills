"""A Model's join graph, as ThoughtSpot validates it — plus the opt-in join-key rule.

The graph is DIRECTED, and the direction comes from `cardinality`, not from which entry
declares the join: an arrow runs from the MANY side to the ONE side. A MANY_TO_ONE or
ONE_TO_ONE join (or one with no cardinality) points from its `model_tables[]` entry to
its `with:` target; a ONE_TO_MANY join points the other way, so a 1:M join declared
under a dimension is the same arrow as an M:1 declared under the fact. Every entry is
its own node (`alias` when present, else `id`, else `name`). Direction is the whole
point. A loop that only appears when direction is ignored — two fact tables sharing a
date and a product dimension — is the ordinary multi-fact shape and imports fine;
ThoughtSpot rejects only a loop that follows the arrows, or two arrow-following routes
between one pair.

Live-probed on se-thoughtspot 2026-10-21 with throwaway Models over existing tables
(nothing persisted). Every shape was checked with `VALIDATE_ONLY`; the rejected ones
were also imported `ALL_OR_NONE`, with the same result:

| Shape | Server response |
|---|---|
| directed cycle, A -> B -> C -> A or A -> B plus B -> A (both MANY_TO_ONE) | error 13123 "Schema validation failed" |
| two directed routes to one table (a diamond) | error 13124 "Schema validation failed" |
| two joins on the same arrow from different entries (M:1 under A, 1:M under B) | error 13124 |
| a 1:M leg that turns a shared-dimension loop into a diamond | error 13124 |
| a table joined to itself, aliased or not | 13125 / 14565 "INTERNAL ERROR" |
| `on:` naming a third table, or an alias | "Invalid srcTable or destTable in join expression" |
| two facts sharing dimensions (undirected loop only), M:1 or 1:M legs | OK |
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

# `[TABLE::COL]` inside a join `on:` clause. A name may carry server escapes — an exported
# Model writes `[dim_date\.csv::date_id]` for a table named `dim_date.csv` — so a
# backslash-escaped character is part of the name, and `on_clause_refs` unescapes it.
_NAME = r"(?:\\.|[^\[\]\\])+?"
_JOIN_ON_REF_RE = re.compile(rf"\[({_NAME})::({_NAME})\]")
_UNESCAPE_RE = re.compile(r"\\(.)")
# The whole of one AND-conjunct: `[T1::C1] = [T2::C2]` and nothing else.
_JOIN_ON_EQ_RE = re.compile(rf"^\[({_NAME})::({_NAME})\]\s*=\s*\[({_NAME})::({_NAME})\]$")
_TOP_LEVEL_AND_RE = re.compile(r"\s+and\s+", re.IGNORECASE)
_OR_NOT_RE = re.compile(r"\b(or|not)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Edge:
    frm: str          # node id of the declaring entry
    to: str           # node id of the `with:` target
    name: str         # join name, for messages
    join: dict        # the raw joins[] entry

    @property
    def one_to_many(self) -> bool:
        return str(self.join.get("cardinality") or "").upper() == "ONE_TO_MANY"

    @property
    def arrow(self) -> tuple[str, str]:
        """(many side, one side): the direction the server validates."""
        return (self.to, self.frm) if self.one_to_many else (self.frm, self.to)


def node_id(entry: dict) -> str:
    """A model_tables entry's node identity: `alias`, else `id` (pinned to `name` by
    I4), else `name`. Stringified — a YAML-typed `name: 2024` must not crash the lint."""
    return str(entry.get("alias") or entry.get("id") or entry.get("name") or "?")


class JoinGraph:
    """Nodes, physical names and edges of one Model. Unresolvable `with` targets are
    skipped — a join to a table the Model does not declare is XREF's business."""

    def __init__(self, model_tables: list):
        self.physical: dict[str, str] = {}
        self._entries: list[dict] = []
        for t in model_tables or []:
            if isinstance(t, dict):
                self.physical.setdefault(node_id(t), str(t.get("name") or "?"))
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
                name = str(j.get("name") or j.get("referencing_join") or "(unnamed)")
                self.edges.append(Edge(frm, to, name, j))

    def resolve(self, ref):
        ref = str(ref)
        if ref in self.physical:
            return ref
        return self._by_lower.get(ref.lower())

    def is_self_join(self, e: Edge) -> bool:
        return self.physical[e.frm].lower() == self.physical[e.to].lower()

    def adjacency(self) -> dict[str, list[str]]:
        """Deduplicated successors along each join's arrow (many -> one), sorted for
        deterministic output. Self-joins are left out (I18). Parallel arrows collapse
        here; `parallel_arrows` reports them."""
        adj: dict[str, set] = {n: set() for n in self.physical}
        for e in self.edges:
            if not self.is_self_join(e):
                src, dst = e.arrow
                adj[src].add(dst)
        return {n: sorted(s) for n, s in adj.items()}

    def parallel_arrows(self) -> list[tuple[str, str, list[Edge]]]:
        """Arrows carried by two or more joins declared from DIFFERENT entries — an M:1
        under A plus a 1:M under B, both A -> B (server error 13124). Two joins declared
        under the same entry to the same target are I14's finding and are left to it."""
        by_arrow: dict[tuple[str, str], list[Edge]] = {}
        for e in self.edges:
            if not self.is_self_join(e):
                by_arrow.setdefault(e.arrow, []).append(e)
        return [(src, dst, es) for (src, dst), es in sorted(by_arrow.items())
                if len({(e.frm, e.to) for e in es}) > 1]


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

    A directed cycle is collapsed to one node first, labelled `cycle(A, B)`: the cycle
    is reported on its own, path counting through a loop is meaningless, and a second
    route that merely passes through a cycle is still a second route.
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
    """The condensation DAG: each strongly connected component becomes one node,
    labelled `cycle(A, B)` (a single table keeps its own name). The label shape keeps a
    collapsed cycle from colliding with an ordinary table name such as `A/B`."""
    label: dict[str, str] = {}
    for comp in strongly_connected(adj):
        for n in comp:
            label[n] = f"cycle({', '.join(comp)})" if len(comp) > 1 else n
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


def _unescape(name: str) -> str:
    return _UNESCAPE_RE.sub(r"\1", name).strip()


def on_clause_refs(on: str) -> list[tuple[str, str]]:
    """Every `[TABLE::COL]` in an `on:` clause as unescaped (table, column) pairs."""
    return [(_unescape(t), _unescape(c)) for t, c in _JOIN_ON_REF_RE.findall(on or "")]


def on_clause_tables(on: str) -> list[str]:
    """Table names referenced in an `on:` clause, in order, de-duplicated."""
    seen: list[str] = []
    for table, _col in on_clause_refs(on):
        if table not in seen:
            seen.append(table)
    return seen


def _wraps_whole(term: str) -> bool:
    """True when `term`'s opening `(` is closed by its final character — `(a) and (b)`
    starts and ends with parens that are NOT a pair."""
    depth = 0
    for i, ch in enumerate(term):
        depth += {"(": 1, ")": -1}.get(ch, 0)
        if depth == 0:
            return i == len(term) - 1
    return False


def _strip_parens(term: str) -> str:
    term = term.strip()
    while term.startswith("(") and _wraps_whole(term):
        term = term[1:-1].strip()
    return term


def _equates_key(on: str, key: str, tables: set) -> bool:
    """True when a top-level AND-conjunct is exactly `[T1::key] = [T2::key]` spanning
    both joined tables. Any OR or NOT in the clause disqualifies it: a key under an OR
    constrains nothing, and for a tenant-isolation rule a false pass is the dangerous
    direction. A conjunct with anything else in it (`= [B::key] + 1`) does not count."""
    on = on or ""
    if _OR_NOT_RE.search(_JOIN_ON_REF_RE.sub("", on)):
        return False
    for term in _TOP_LEVEL_AND_RE.split(_strip_parens(on)):
        m = _JOIN_ON_EQ_RE.match(_strip_parens(term))
        if not m:
            continue
        t1, c1, t2, c2 = (_unescape(x) for x in m.groups())
        if c1.lower() == c2.lower() == key.lower() and {t1.lower(), t2.lower()} == tables:
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
    """The join's `on:` — inline, else the referenced Table TML join, which lives in the
    DECLARING entry's Table TML: a referencing join placed under its destination is
    rejected at import (14504 "Relationships do not exist", live-probed 2026-10-21)."""
    on = e.join.get("on")
    ref = e.join.get("referencing_join")
    if on or not ref:
        return on
    return table_joins.get((graph.physical[e.frm].lower(), ref))


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
