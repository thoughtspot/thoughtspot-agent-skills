"""Bind Sisense widget fields to an EXISTING ThoughtSpot Model (``--target-model``).

The default ``build-liveboard`` path resolves a widget field by its bare column name against
the model ``build-model`` would generate. That cannot bind to a hand-designed model: the
table qualifier is dropped (``[fact.case_id_]`` -> ``case_id_``), role-playing copies of one
table collapse (``[Start_Date.date_day]`` and ``[End_Date.date_day]`` are both ``date_day``),
and the model's display names differ. This module reads the target Model TML and resolves
``[Table.column]`` -> the model column that exposes exactly that table instance + column.

Instance resolution, in order:
1. A model instance named like the Sisense table (``Visit_Start_Date`` ~ alias
   ``Visit Start Date``; ``dim_case`` ~ unaliased ``dim_case``).
2. Otherwise the Sisense relation that connects the table to the widget's fact: the model
   instance the fact joins ON THE SAME FOREIGN-KEY COLUMN (so ``fact.site_id_`` picks the
   ``Visit Site`` alias and ``fact.home_site_id_`` the ``Home Site`` alias of one base table).
3. Otherwise any instance of that base table reachable from the widget's facts; more than
   one candidate is ambiguous and flagged, never guessed.

Pure functions, no I/O: the command layer loads the TML file and passes the dict.
"""
from __future__ import annotations

import re
from collections import deque
from typing import Optional

_ON_SIDE = re.compile(r"\[([^\]:]+)::([^\]]+)\]")
_COUNT_EXPR = re.compile(r"^\s*(unique\s+count|count)\s*\(\s*\[([^\]:]+)::([^\]]+)\]\s*\)\s*$", re.I)


def _norm(name: str) -> str:
    return re.sub(r"[\s_]+", "", (name or "").lower())


def split_dim(dim: str) -> tuple:
    """Sisense dim ``[Table.Column (Calendar)]`` -> (table, column), date-hierarchy tag dropped."""
    inner = (dim or "").strip().strip("[]")
    if "." not in inner:
        return "", inner
    table, col = inner.split(".", 1)
    col = col.strip()
    if col.endswith(")") and " (" in col:
        col = col.split(" (")[0].strip()
    return table.strip(), col


class TargetModel:
    """Index over one Model TML dict (``{"model": {...}}`` or the bare model body)."""

    def __init__(self, tml: dict):
        model = tml.get("model") or tml.get("worksheet") or tml
        self.name = model.get("name") or ""
        # root obj_id (`ts tml export --include-obj-id`): the ONLY exact viz binding — a Model
        # may carry a custom obj_id no derivation from its name can reproduce
        self.obj_id = tml.get("obj_id") if model is not tml else None
        self.base_of: dict = {}           # instance -> base table name
        self.joins: dict = {}             # instance -> [(target instance, fk column on instance)]
        for mt in model.get("model_tables") or model.get("tables") or []:
            inst = mt.get("alias") or mt.get("name")
            self.base_of[inst], self.joins[inst] = mt.get("name"), _joins_of(mt)
        self.formulas = {f.get("id"): f.get("expr") or "" for f in model.get("formulas") or []}
        self.instances_of: dict = {}      # column name -> instances it reads (column_id / formula refs)
        self.by_column_id: dict = {}      # 'inst::col' -> column name
        self.measures: set = set()
        self.formula_measures: set = set()  # formula-backed measures keep their name as output
        self.count_measures: dict = {}    # ('unique count'|'count', inst, col) -> column name
        self.columns: list = []
        for c in model.get("columns") or []:
            self._index_column(c)
        self._insts_by_norm: dict = {}
        for inst in self.base_of:
            self._insts_by_norm.setdefault(_norm(inst), []).append(inst)

    def _index_column(self, c: dict) -> None:
        nm = c.get("name")
        self.columns.append(nm)
        is_measure = (c.get("properties") or {}).get("column_type") == "MEASURE"
        if is_measure:
            self.measures.add(nm)
        if c.get("column_id"):
            self.by_column_id[c["column_id"]] = nm
            self.instances_of[nm] = {c["column_id"].split("::")[0]}
            return
        if not c.get("formula_id"):
            return
        if is_measure:
            self.formula_measures.add(nm)
        expr = self.formulas.get(c["formula_id"], "")
        self.instances_of[nm] = {t for t, _ in _ON_SIDE.findall(expr)}
        m = _COUNT_EXPR.match(expr)
        if m:
            kind = "unique count" if m.group(1).lower().startswith("unique") else "count"
            self.count_measures[(kind, m.group(2), m.group(3))] = nm

    # ---- graph ----------------------------------------------------------------------
    def reachable(self, start: str) -> set:
        """Instances reachable from ``start`` following MANY_TO_ONE-style join direction."""
        seen, todo = {start}, deque([start])
        while todo:
            for nxt, _ in self.joins.get(todo.popleft(), []):
                if nxt and nxt not in seen:
                    seen.add(nxt)
                    todo.append(nxt)
        return seen

    def roots(self) -> list:
        """Instances nothing joins TO: the model's facts."""
        targets = {t for js in self.joins.values() for t, _ in js}
        return [i for i in self.base_of if i not in targets]

    # ---- instance resolution ----------------------------------------------------------
    def named_instances(self, sis_table: str) -> list:
        return list(self._insts_by_norm.get(_norm(sis_table), []))

    def instances_of_base(self, base: str) -> list:
        return [i for i, b in self.base_of.items() if _norm(b) == _norm(base)]

    def relation_instances(self, sis_table: str, relations: list) -> list:
        """Instances that play ``sis_table``'s role: joined from some instance on a FK column a
        Sisense relation links to ``sis_table``. Keeps two Sisense copies of one base table
        (e.g. a site and a home site) from claiming each other's aliases."""
        out = []
        for src, js in self.joins.items():
            fks = set(_sisense_fk_cols(sis_table, self.base_of.get(src) or src, relations))
            out += [t for t, fk in js if fk in fks and t not in out]
        return out

    def candidates(self, sis_table: str, relations: list) -> list:
        return (self.named_instances(sis_table) or self.relation_instances(sis_table, relations)
                or self.instances_of_base(sis_table))

    def facts_for(self, column_names) -> list:
        """Roots (facts) whose join tree reaches every instance the given columns read."""
        need = set().union(*(self.instances_of.get(c, set()) for c in column_names)) if column_names else set()
        return [r for r in self.roots() if need and need <= self.reachable(r)]

    def column_by_display(self, display: str):
        """Unique Model column whose name equals a Sisense column display name (normalised)."""
        hits = [c for c in self.columns if _norm(c) == _norm(display)]
        return hits[0] if len(hits) == 1 else None

    def resolve_instance(self, sis_table: str, anchors: list, relations: list) -> tuple:
        """Sisense table -> (instance|None, note). ``anchors`` are the widget's fact
        instances; ``relations`` the parsed Sisense relations (``[{left, right}]`` endpoints)."""
        named = self.named_instances(sis_table)
        if len(named) == 1:
            return named[0], ""
        # 2. the instance each anchor joins on the FK column Sisense relates the table by
        hits = set()
        for anchor in anchors:
            for fk in _sisense_fk_cols(sis_table, self.base_of.get(anchor) or anchor, relations):
                hits.update(t for t, c in self.joins.get(anchor, []) if c == fk)
        if len(hits) == 1:
            return hits.pop(), ""
        # 3. any instance playing that table's role, reachable from the anchors
        cands = self.candidates(sis_table, relations)
        if anchors:
            reach = set().union(*(self.reachable(a) for a in anchors))
            cands = [c for c in cands if c in reach] or cands
        if len(cands) == 1:
            return cands[0], ""
        if not cands:
            return None, f"table {sis_table} is not in the target model"
        return None, f"table {sis_table} is ambiguous in the target model ({', '.join(sorted(cands))})"

    def resolve_chip_instance(self, sis_table: str, anchor_sets: list, relations=None) -> tuple:
        """Dashboard filter (no widget context) -> the instance reachable from the most
        widgets' facts, so one chip filters as many tiles as possible. Ties are flagged."""
        cands = self.candidates(sis_table, relations or [])
        if len(cands) <= 1:
            return (cands[0], "") if cands else (None, f"table {sis_table} is not in the target model")
        reach = {c: sum(1 for anchors in anchor_sets
                        if any(c in self.reachable(a) for a in anchors)) for c in cands}
        best = max(reach.values())
        top = [c for c, n in reach.items() if n == best]
        if len(top) > 1:   # Sisense's own rule: the shortest join path from the facts wins
            top = self._nearest(top, anchor_sets)
        top.sort()
        if len(top) == 1:
            return top[0], ""
        return top[0], f"filter table {sis_table} is ambiguous ({', '.join(top)}); chose {top[0]}"

    def _nearest(self, cands: list, anchor_sets: list) -> list:
        """Candidates with the smallest total join distance from every widget's facts."""
        dist = {c: sum(min((self.distance(a, c) for a in anchors), default=99) for anchors in anchor_sets)
                for c in cands}
        low = min(dist.values())
        return [c for c in cands if dist[c] == low]

    def distance(self, start: str, target: str) -> int:
        """Join hops from ``start`` to ``target`` (99 when unreachable)."""
        seen, todo = {start: 0}, deque([start])
        while todo:
            cur = todo.popleft()
            if cur == target:
                return seen[cur]
            for nxt, _ in self.joins.get(cur, []):
                if nxt and nxt not in seen:
                    seen[nxt] = seen[cur] + 1
                    todo.append(nxt)
        return 99

    # ---- column resolution ------------------------------------------------------------
    def column(self, inst: str, col: str) -> Optional[str]:
        for key in (f"{inst}::{col}", f"{self.base_of.get(inst)}::{col}" if inst == self.base_of.get(inst) else None):
            if key and key in self.by_column_id:
                return self.by_column_id[key]
        return None

    def count_measure(self, kind: str, inst: str, col: str) -> Optional[str]:
        """A model formula measure ``unique count ( [inst::col] )`` (or ``count``), if any."""
        for ref in (inst, self.base_of.get(inst)):
            nm = self.count_measures.get((kind, ref, col))
            if nm:
                return nm
        return None


def _joins_of(mt: dict) -> list:
    """A model_tables entry's joins -> [(target instance, fk column on this table)]."""
    inst, out = mt.get("alias") or mt.get("name"), []
    for j in mt.get("joins") or []:
        # YAML 1.1 resolves an unquoted `on:` key to boolean True — accept both
        sides = _ON_SIDE.findall(j.get("on", j.get(True)) or "")
        fk = next((col for tbl, col in sides if tbl in (mt.get("name"), inst)), None)
        out.append((j.get("with"), fk))
    return out


def _sisense_fk_cols(sis_table: str, anchor_table: str, relations: list) -> list:
    """FK columns on ``anchor_table`` that a Sisense relation links to ``sis_table``."""
    out = []
    for rel in relations or []:
        ends = [(e.get("table"), e.get("column")) for e in rel.get("endpoints") or []]
        if len(ends) != 2:
            continue
        (ta, ca), (tb, cb) = ends
        if _norm(ta) == _norm(anchor_table) and _norm(tb) == _norm(sis_table):
            out.append(ca)
        elif _norm(tb) == _norm(anchor_table) and _norm(ta) == _norm(sis_table):
            out.append(cb)
    return out
