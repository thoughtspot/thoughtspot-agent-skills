"""Bind Sisense widget fields to an EXISTING ThoughtSpot Model (``--target-model``).

The default ``build-liveboard`` path resolves a widget field by its bare column name against
the model ``build-model`` would generate. That cannot bind to a hand-designed model: the
table qualifier is dropped (``[fact.case_id_]`` -> ``case_id_``), role-playing copies of one
table collapse (``[Start_Date.date_day]`` and ``[End_Date.date_day]`` are both ``date_day``),
and the model's display names differ. This module reads the target Model TML and resolves
``[Table.column]`` -> the model column that exposes exactly that table instance + column.

Instance resolution, in order:
1. A model instance named like the Sisense table (``Visit_Start_Date`` ~ alias
   ``Visit Start Date``; ``dim_case`` ~ unaliased ``dim_case``) -- unless the Sisense
   relation joins the widget's fact through a DIFFERENT instance, which is flagged.
2. Otherwise the Sisense relation that connects the table to the widget's fact: the model
   instance the fact joins ON THE SAME FOREIGN-KEY COLUMN (so ``fact.site_id_`` picks the
   ``Visit Site`` alias and ``fact.home_site_id_`` the ``Home Site`` alias of one base table).
3. Otherwise any instance of that base table reachable from the widget's facts; more than
   one candidate is ambiguous, and one the facts cannot reach is refused -- both flagged,
   never guessed.

Pure functions, no I/O: the command layer loads the TML file and passes the dict.
"""
from __future__ import annotations

import re
from collections import deque
from typing import Optional

_ON_SIDE = re.compile(r"\[([^\]:]+)::([^\]]+)\]")
_OUTER_AGG = re.compile(r"^\s*(unique\s+count|count|sum|average|min|max)\s*\(", re.I)
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

    def __init__(self, tml: dict, tables=None):
        model = tml.get("model") or tml.get("worksheet") or tml
        self.name = model.get("name") or ""
        # root obj_id (`ts tml export --include-obj-id`): the ONLY exact viz binding — a Model
        # may carry a custom obj_id no derivation from its name can reproduce
        self.obj_id = tml.get("obj_id") if model is not tml else None
        self.base_of: dict = {}           # instance -> base table name
        # instance -> [(target instance, fk column on instance)], ALWAYS many -> one: a join
        # declared ONE_TO_MANY (on the dimension side) is reversed, so the facts are the roots
        self.joins: dict = {}
        self.join_pk: dict = {}           # (many, one, fk) -> the column joined on the one side
        self.composite: set = set()       # (many, one, fk) of joins on more than one condition
        self._index_tables(model.get("model_tables") or model.get("tables") or [])
        self.formulas = {f.get("id"): f.get("expr") or "" for f in model.get("formulas") or []}
        self.instances_of: dict = {}      # column name -> instances it reads (column_id / formula refs)
        self.by_column_id: dict = {}      # 'inst::col' -> column name
        self.measures: set = set()
        self.formula_measures: set = set()  # formula-backed measures keep their name as output
        self.formula_columns: set = set()   # every formula-backed column (attribute or measure)
        self.formula_agg: dict = {}         # formula column -> its outermost aggregation, if whole-expr
        self.count_measures: dict = {}    # ('unique count'|'count', inst, col) -> column name
        self.columns: list = []
        self.formatted: set = set()       # columns carrying their own format_pattern / currency_type
        self.calendars: dict = {}         # column -> custom calendar it buckets by
        # base table -> {warehouse column: Table TML column name}, from the associated Table TMLs
        # (`ts tml export --associated`): a Model column_id names the TABLE column, which a
        # hand-designed Table may have renamed from the warehouse column a Sisense dim carries
        self.table_cols = _table_columns(tables)
        for c in model.get("columns") or []:
            self._index_column(c)
        self._expand_formula_refs(model.get("columns") or [])
        self._insts_by_norm: dict = {}
        for inst in self.base_of:
            self._insts_by_norm.setdefault(_norm(inst), []).append(inst)

    def _index_tables(self, model_tables: list) -> None:
        declared = []
        for mt in model_tables:
            inst = mt.get("alias") or mt.get("name")
            self.base_of[inst] = mt.get("name")
            self.joins.setdefault(inst, [])
            declared += [(inst,) + j for j in _joins_of(mt)]
        for inst, target, sides, card in declared:     # after every instance's base is known
            self._add_join(inst, target, sides, card)

    def _add_join(self, inst: str, target: str, sides: list, card: str) -> None:
        if card == "MANY_TO_MANY":       # no many -> one direction: not followed, so a widget
            return                       # needing it reports its table as unreachable
        many, one = (target, inst) if card == "ONE_TO_MANY" else (inst, target)
        names, one_names = {many, self.base_of.get(many)}, {one, self.base_of.get(one)}
        fk = next((col for tbl, col in sides if tbl in names), None)
        pk = next((col for tbl, col in sides if tbl in one_names and col != fk), None) or \
            next((col for tbl, col in sides if tbl in one_names), None)
        self.joins.setdefault(many, []).append((one, fk))
        self.join_pk[(many, one, fk)] = pk
        if len(sides) != 2:              # more than one condition: not a one-column relation
            self.composite.add((many, one, fk))

    def _expand_formula_refs(self, columns: list) -> None:
        """A formula referencing other formulas (``[formula_A]``, or a column by display name)
        reads every instance THEY read: resolved to a fixed point, so a formula built from two
        facts' formulas is seen spanning both."""
        by_ref = {c.get("formula_id"): c.get("name") for c in columns if c.get("formula_id")}
        by_ref.update({c.get("name"): c.get("name") for c in columns})
        refs = {c["name"]: {by_ref[r] for r in re.findall(r"\[([^\]:]+)\]", self.formulas.get(c["formula_id"], ""))
                            if r in by_ref and by_ref[r] != c["name"]}
                for c in columns if c.get("formula_id")}
        changed = True
        while changed:
            changed = False
            for name, used in refs.items():
                extra = set().union(*(self.instances_of.get(u, set()) for u in used)) - self.instances_of.get(name, set())
                if extra:
                    self.instances_of[name] = self.instances_of.get(name, set()) | extra
                    changed = True

    def _index_column(self, c: dict) -> None:
        nm = c.get("name")
        self.columns.append(nm)
        props = c.get("properties") or {}
        is_measure = props.get("column_type") == "MEASURE"
        if props.get("format_pattern") or props.get("currency_type"):
            self.formatted.add(nm)
        if props.get("calendar"):
            self.calendars[nm] = props["calendar"]
        if is_measure:
            self.measures.add(nm)
        if c.get("column_id"):
            self.by_column_id[c["column_id"]] = nm
            self.instances_of[nm] = {c["column_id"].split("::")[0]}
            return
        if not c.get("formula_id"):
            return
        self.formula_columns.add(nm)
        if is_measure:
            self.formula_measures.add(nm)
        expr = self.formulas.get(c["formula_id"], "")
        agg = _outer_aggregation(expr)
        if agg:
            self.formula_agg[nm] = agg
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

    def single_instance(self, name: str):
        """The one instance a Model column reads, or None (a formula over several, or none)."""
        insts = self.instances_of.get(name) or set()
        return next(iter(insts)) if len(insts) == 1 else None

    def spans_facts(self, column_names) -> bool:
        """The columns read instances no single fact reaches: a multi-fact (chasm) query."""
        need = set().union(*(self.instances_of.get(c, set()) for c in column_names)) if column_names else set()
        return bool(need) and not self.facts_for(column_names)

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
        hits = self.fk_instances(sis_table, anchors, relations)
        missing = [] if hits else self.unjoined_relations(sis_table, anchors, relations)
        if missing:
            return None, (f"Sisense joins {sis_table} on {', '.join(missing)}, which the target model does "
                          "not join, so it would reach the table another way")
        reach = set().union(*(self.reachable(a) for a in anchors)) if anchors else None
        if len(named) == 1:
            return self._by_name(sis_table, named[0], hits, reach, anchors)
        # 2. the instance each anchor joins on the FK column Sisense relates the table by
        if len(hits) == 1:
            return hits.pop(), ""
        # 3. any instance playing that table's role, reachable from the anchors
        return self._by_role(sis_table, self.candidates(sis_table, relations), reach, anchors)

    @staticmethod
    def _by_name(sis_table: str, inst: str, hits: set, reach, anchors: list) -> tuple:
        if reach is not None and inst not in reach:
            return None, (f"table {sis_table} ({inst}) is not reachable from the widget's facts "
                          f"({', '.join(sorted(anchors))})")
        if hits and inst not in hits:   # the name and the Sisense join key disagree
            return None, (f"table {sis_table} matches instance {inst} by name, but the Sisense "
                          f"relation joins through {', '.join(sorted(hits))} (map it via field_map)")
        return inst, ""

    @staticmethod
    def _by_role(sis_table: str, cands: list, reach, anchors: list) -> tuple:
        if reach is not None and cands:
            if not any(c in reach for c in cands):
                return None, (f"table {sis_table} ({', '.join(sorted(cands))}) is not reachable from "
                              f"the widget's facts ({', '.join(sorted(anchors))})")
            cands = [c for c in cands if c in reach]
        if len(cands) == 1:
            return cands[0], ""
        if not cands:
            return None, f"table {sis_table} is not in the target model"
        return None, f"table {sis_table} is ambiguous in the target model ({', '.join(sorted(cands))})"

    def path_known(self, sis_table: str, inst: str, anchors: list, has_fact: bool, relations) -> bool:
        """The copy is decided by the widget itself: it names a fact table, or every fact linking
        its tables that Sisense relates to ``sis_table`` joins it through ``inst`` (a fact with no
        Sisense relation to the table -- one the Model added -- is no path in Sisense)."""
        if has_fact:
            return True
        hits = [self.fk_instances(sis_table, [a], relations or []) for a in anchors]
        hits = [h for h in hits if h]
        return bool(hits) and all(h == {inst} for h in hits)

    def unjoined_relations(self, sis_table: str, anchors: list, relations: list) -> list:
        """``anchor.column`` for each Sisense relation from a widget fact to ``sis_table`` whose
        column the Model joins nothing on from that fact."""
        out = []
        for a in anchors:
            joined = {_norm(fk) for _, fk in self.joins.get(a, []) if fk}
            for fk in _sisense_fk_cols(sis_table, self.base_of.get(a) or a, relations or []):
                tfk = self._table_column(a, fk) or fk
                if _norm(fk) not in joined and _norm(tfk) not in joined:
                    out.append(f"{a}.{fk}")
        return out

    def fk_instances(self, sis_table: str, anchors: list, relations: list) -> set:
        """Instances the anchors join on the FK column a Sisense relation links ``sis_table`` by."""
        hits = set()
        for anchor in anchors:
            for fk in _sisense_fk_cols(sis_table, self.base_of.get(anchor) or anchor, relations):
                keys = {_norm(fk), _norm(self._table_column(anchor, fk) or fk)}
                hits.update(t for t, c in self.joins.get(anchor, []) if c and _norm(c) in keys)
        return hits

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
        """Model column exposing ``col`` (a WAREHOUSE column name, as a Sisense dim carries it) on
        ``inst``. When the Table TML was supplied, ONLY its db_column_name mapping decides (exact,
        else a unique case/underscore-insensitive db name) -- a fallback there could bind another
        warehouse column. Without it: the column name itself, else a unique
        case/underscore-insensitive match. Anything ambiguous is None, never a guess."""
        if self.base_of.get(inst) in self.table_cols:   # the Table is known: its mapping decides
            tcol = self._table_column(inst, col)
            return self.by_column_id.get(f"{inst}::{tcol}") if tcol else None
        if f"{inst}::{col}" in self.by_column_id:
            return self.by_column_id[f"{inst}::{col}"]
        hits = [nm for key, nm in self.by_column_id.items()
                if key.split("::")[0] == inst and _norm(key.split("::", 1)[1]) == _norm(col)]
        return hits[0] if len(hits) == 1 else None

    def _table_column(self, inst: str, col: str) -> Optional[str]:
        cols = self.table_cols.get(self.base_of.get(inst), {})
        if col in cols:
            return cols[col]
        hits = [name for db, name in cols.items() if _norm(db) == _norm(col)]
        return hits[0] if len(hits) == 1 else None

    def _role_copies(self, sis_table: str, inst: str, widget_insts: set) -> set:
        """The copies of ``inst``'s base table when its role is a real choice for this widget:
        not for one copy, a Sisense table of its own for this role, or a widget with no other
        table to join through (every copy then reads the same rows)."""
        copies = set(self.instances_of_base(self.base_of.get(inst) or ""))
        own_role_table = self.named_instances(sis_table) and _norm(sis_table) != _norm(self.base_of.get(inst) or "")
        return set() if len(copies) <= 1 or own_role_table or not (widget_insts - copies) else copies

    def role_conflict(self, sis_table: str, inst: str, widget_insts: set, path_known: bool,
                      relations=None) -> str:
        """Why binding ``inst`` for a role-played table may not be the copy Sisense joins for this
        widget, or ''. Sisense joins the table through its RELATIONS from the widget's other
        tables, so a copy one of them joins on a column a Sisense relation uses decides it; two
        such copies cannot be decided. With no such copy, ``path_known`` says whether the
        widget's path to the table is otherwise determined (it names a fact, or exactly one fact
        links its tables and its Sisense relation picked ``inst``)."""
        copies = self._role_copies(sis_table, inst, widget_insts)
        if not copies:
            return ""
        adjacent = {t for other in widget_insts - copies for t in self.fk_instances(sis_table, [other], relations or [])
                    if t in copies}
        if len(adjacent) > 1:
            return (f"the widget's tables join {', '.join(sorted(adjacent))} directly, so which copy of "
                    f"{sis_table} Sisense uses cannot be decided")
        if adjacent and inst not in adjacent:
            return f"Sisense joins {sis_table} through {adjacent.pop()} for this widget, not {inst}"
        if not adjacent and not path_known:
            return (f"the widget queries no fact table, so which copy of {sis_table} Sisense joins "
                    "cannot be decided")
        return ""

    def count_measure(self, kind: str, inst: str, col: str) -> Optional[str]:
        """A model formula measure ``unique count ( [inst::col] )`` (or ``count``), if any. The
        warehouse column goes through the Table TML mapping like any binding, and the base table
        name stands in for ``inst`` only when the table has no other copy (it would count
        another role's rows otherwise)."""
        base = self.base_of.get(inst)
        tcol = self._table_column(inst, col) if base in self.table_cols else col
        if not tcol:
            return None
        refs = [inst] + ([base] if base != inst and len(self.instances_of_base(base or "")) == 1 else [])
        return next((self.count_measures[(kind, r, tcol)] for r in refs if (kind, r, tcol) in self.count_measures), None)


def _table_columns(tables) -> dict:
    """Table / SQL View TML dicts -> {name: {warehouse column: TML column name}}."""
    names = {}
    for t in tables or []:
        body = t.get("table") or t.get("sql_view") or t
        cols = body.get("columns") or body.get("sql_view_columns") or []
        names[body.get("name")] = {(c.get("db_column_name") or c.get("sql_output_column")): c.get("name")
                                   for c in cols if c.get("db_column_name") or c.get("sql_output_column")}
    return names


def _outer_aggregation(expr: str) -> Optional[str]:
    """``sum ( ... )`` -> 'sum' when that aggregation wraps the WHOLE expression, else None."""
    m = _OUTER_AGG.match(expr or "")
    if not m:
        return None
    depth = 0
    for i, ch in enumerate(expr):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return re.sub(r"\s+", " ", m.group(1).lower()) if not expr[i + 1:].strip() else None
    return None


def _joins_of(mt: dict) -> list:
    """A model_tables entry's joins -> [(target instance, [(table, column)] on-clause sides,
    cardinality)]."""
    out = []
    for j in mt.get("joins") or []:
        # YAML 1.1 resolves an unquoted `on:` key to boolean True — accept both
        sides = _ON_SIDE.findall(j.get("on", j.get(True)) or "")
        out.append((j.get("with"), sides, (j.get("cardinality") or "").upper()))
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
