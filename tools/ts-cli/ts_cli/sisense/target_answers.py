"""Sisense dashboard -> Liveboard bound to an EXISTING Model (``build-liveboard --target-model``).

The default path (answers.py) binds widgets to the model ``build-model`` generates. This path
binds them to a Model someone already designed, and carries the parts of a dashboard that
decide whether the rebuilt board shows the same numbers. The rule is an ALLOWLIST: a widget,
filter or chip is carried only when every setting on it is one this path reads and has
verified; any other setting (an unrecognised JAQL or filter key, a quick function, a disabled
plotted item, a date value whose day boundary is unknown) makes it NEEDS REVIEW with the reason.

- ``agg``: Sisense ``count`` is COUNT DISTINCT -> ``unique count``; a count over a key the
  Model hides binds to a Model formula ``unique count ( [inst::col] )`` when one exists.
- widget-level filters become search filters (members ``=`` repeated, which ThoughtSpot ORs;
  excludes ``!=`` repeated, which it ANDs; ranges ``>= > <= <``). Never ``in (...)`` /
  ``not in (...)``: ThoughtSpot search ignores both silently (live-verified, 26.9).
- a WidgetsTabber keeps only its active tab's widget when a hidden tab is the same chart (type,
  fields, filters) at another date level (the other grains are one click away in the chart's
  date-bucket control); any other hidden tab becomes a tile of its own.
- top / bottom N is carried (`top N` / `bottom N`) only when it ranks by the widget's only
  measure; a disabled widget or dashboard filter is off in Sisense and is not applied.
- Sisense value titles become ``custom_name``; rich-text widgets and tab-set titles become
  note tiles; the columnar layout becomes the tile grid.
- jump-to-dashboard drills become a details table built from the drill dashboard's widget,
  narrowed on the liveboard with right-click > Filter.
- dashboard filters become chips: see target_chips.py for how each chip is checked against
  each tile, and target_filters.py for which conditions are carried.

Anything that cannot be bound faithfully is reported NEEDS REVIEW with the reason, never
dropped or substituted. ``overrides`` may map a Sisense dim to a Model column
(``field_map``) or a Sisense filter dim to a search fragment (``filter_map``) for the cases
only the Model's author can decide.

Pure functions, no I/O.
"""
from __future__ import annotations

import copy
import re

from ts_cli.sisense.answers import chart_type_for
from ts_cli.sisense.target_chips import build_chips, flag_tile
from ts_cli.sisense.target_drills import drill_tables
from ts_cli.sisense.target_fields import _collect_fields, _dimension, _field_warning
from ts_cli.sisense.target_layout import _note_text, _place, note_tile
from ts_cli.sisense.target_tabs import _GRAIN_SUFFIX, _hidden_tabs, _kept_tabs, tabber_hidden
from ts_cli.sisense.target_filters import (_DATE_VALUE, _FILTER_TERMS, _IN_LIST, _boolean_filter_problem,
                                           _show, _term_problem, _text_value_problem, condition_key, is_all,
                                           top_n, widget_filter)
from ts_cli.sisense.target_model import TargetModel, split_dim
from ts_cli.sisense.functions import AGG_FUNCTIONS, FUNCTION_MAP
from ts_cli.sisense.target_paths import _sisense_table, loop_problem, one_hop_problem, path_problem
from ts_cli.sisense.target_settings import (board_reasons, join_type_problem,
                                            join_type_row, path_instances, physical_problem, value_matching_row)
from ts_cli.tableau.liveboard import agg_label

# Sisense agg -> ThoughtSpot search keyword, from the one aggregation table (functions.py).
# Sisense `count` is a DISTINCT count.
AGG_KEYWORD = {a: FUNCTION_MAP[a] for a in AGG_FUNCTIONS}
_TOKEN = re.compile(r"\[([^\]]+)\]")

def _named_relations(inv: dict) -> list:
    names = {t.get("id"): t.get("jaql_name") for t in inv.get("tables") or [] if t.get("jaql_name")}
    return [dict(r, endpoints=[dict(e, table=names.get(e.get("table"), e.get("table")))
                               for e in r.get("endpoints") or []])
            for r in inv.get("relations") or []]


def _same_name(a: str, b: str) -> bool:
    return re.sub(r"[\s_]+", "", (a or "").lower()) == re.sub(r"[\s_]+", "", (b or "").lower())


def _connected(tables: set, pairs: list) -> bool:
    """Do the pairs join every table into one group?"""
    group = {next(iter(tables))}
    changed = True
    while changed:
        changed = False
        for a, b in pairs:
            if (a in group) != (b in group):
                group |= {a, b}
                changed = True
    return group == tables


def _renamed_columns(inv: dict) -> dict:
    """(table, column name) -> source column id, for every Sisense column renamed from its source."""
    return {(t.get("jaql_name"), c.get("name")): c.get("id") for t in inv.get("tables") or []
            for c in t.get("columns") or [] if c.get("id") and c.get("name") and c["id"] != c["name"]}


def _calculated_columns(inv: dict) -> set:
    """(table, column) for every Sisense CALCULATED column: the only fields a Model formula may
    be bound to by name."""
    out = set()
    for t in inv.get("tables") or []:
        names = [c.get(k) for c in t.get("columns") or [] if c.get("calculated") for k in ("id", "name")]
        out.update((t.get("jaql_name"), n) for n in names + list(t.get("calculated_columns") or []) if n)
    return out


class _Binder:
    def __init__(self, inv: dict, target: TargetModel, overrides: dict):
        self.inv, self.t = inv, target
        # relation endpoints carry Sisense table IDS (sometimes opaque `tq_...`); JAQL dims carry
        # the table's `name` — normalise endpoints to that name so the two can be compared
        self.relations = _named_relations(inv)
        self.field_map = (overrides or {}).get("field_map") or {}
        self.filter_map = (overrides or {}).get("filter_map") or {}
        self.conditions = {}       # Sisense dim -> the distinct filter conditions on it (note_conditions)
        self.calculated = _calculated_columns(inv)
        self.renamed = _renamed_columns(inv)
        self.sis_tables = {t.get("jaql_name"): t for t in inv.get("tables") or []}
        # tables in a Sisense relation that is not one column to one column: not read here
        self.multi_rel = {e.get("table") for r in self.relations if len(r.get("endpoints") or []) != 2
                          for e in r.get("endpoints") or []}
        self._ctx = (set(), True)

    # -- anchors: the fact instances a widget queries ---------------------------------
    def anchors(self, widget: dict) -> list:
        """The fact instances a widget queries: facts it names, else facts reaching all (or
        any) of the instances it names. Also records the widget's instances for the role-copy
        check that every binding of this widget runs (``column``)."""
        groups = self._widget_groups(widget)
        insts = set().union(*groups) if groups else set()
        roots = self.t.roots()
        direct = [r for r in roots if r in insts]
        self._ctx = (insts, bool(direct))
        if direct or not insts:
            return direct
        # facts reaching SOME copy of EVERY table the widget names (a role-played table counts once)
        return [r for r in roots if all(g & self.t.reachable(r) for g in groups)] or \
               [r for r in roots if insts & self.t.reachable(r)]

    def _widget_groups(self, widget: dict) -> list:
        """One set of candidate instances per Sisense table the widget names."""
        dims = [f.get("dim") for f in widget.get("fields", [])] + [sf.get("dim") for sf in widget.get("filters", [])]
        groups = {}
        for dim in filter(None, dims):
            table = split_dim(dim)[0]
            groups[table] = set(self.t.named_instances(table) or self.t.instances_of_base(table))
        return [g for g in groups.values() if g]

    def _widget_instances(self, widget: dict) -> set:
        groups = self._widget_groups(widget)
        return set().union(*groups) if groups else set()

    def column(self, dim: str, anchors: list, measure: bool = False, agg: str = "") -> tuple:
        """Sisense dim -> (model column | None, instance | None, note). A binding that is still a
        guess (made only by name, or one a check could not confirm) comes back with its note even
        though a column was found: the field is kept and its row is NEEDS REVIEW."""
        table, col = split_dim(dim)
        if table in self.multi_rel:
            return None, None, (f"Sisense relates {table} through a relation that is not one column to one "
                                "column, which this converter does not read")
        if dim in self.field_map:            # the map chooses the column; the path checks still run
            name, _, note = self.mapped(dim, agg)
            if not name:
                return None, None, note
            inst = self.t.single_instance(name)
            if inst is None:
                return name, None, (f"field_map column [{name}] reads several (or no) table instances, so its "
                                    "join path cannot be checked against Sisense's")
            return name, inst, self._path_problem(table, inst, anchors) or self._physical(table, inst)
        if (table, col) in self.renamed:
            return None, None, (f"Sisense column {table}.{col} is the source column {self.renamed[(table, col)]} "
                                "renamed; which one the Model column reads is not verified (map it via field_map)")
        inst, note = self.t.resolve_instance(table, anchors, self.relations)
        if not inst:
            return None, None, note
        conflict = self._path_problem(table, inst, anchors)
        if conflict:
            return None, None, conflict
        name = self.t.column(inst, col)
        if name:
            return name, inst, self._plain_binding_problem(table, col, inst) or self._physical(table, inst)
        name = self._calculated(table, col, inst, measure)
        if name:
            return name, inst, (f"Sisense calculated column {table}.{col} is bound to Model formula [{name}] by "
                                "name only; confirm it is the same calculation (map it via field_map)")
        return None, inst, f"{table}.{col} is not exposed on the target model"

    def path_table_problem(self, inst: str) -> str:
        """A table the tile only joins through: the Sisense table standing for it (named like the
        instance or its base) must read the same rows as the Model's Table."""
        graph_names = {t: t for t in self.sis_tables}
        table = _sisense_table(graph_names, inst, self.t.base_of.get(inst))
        if table is None:
            return (f"the tile joins through {inst}, which no Sisense table stands for, so its rows cannot be "
                    "compared with Sisense's")
        return self._physical(table, inst)

    def _physical(self, table: str, inst) -> str:
        """Why Sisense table ``table`` and the Table behind ``inst`` may not read the same rows, or ''."""
        if not inst:
            return ""
        return physical_problem(self.sis_tables.get(table), self.t.table_physical, self.t.base_of.get(inst))

    def _plain_binding_problem(self, table: str, col: str, inst: str) -> str:
        """Why a column found by its warehouse name is still a guess, or ''."""
        if (table, col) in self.calculated:
            return (f"Sisense calculated column {table}.{col} is bound to a plain Model column of the same name; "
                    "confirm it computes the same thing (map it via field_map)")
        if self.t.table_cols and self.t.base_of.get(inst) not in self.t.table_cols:
            return (f"the Table TML for {self.t.base_of.get(inst)} was not supplied, so {table}.{col} was matched by "
                    "Table column name (export with --associated)")
        return ""

    def _path_problem(self, table: str, inst, anchors: list) -> str:
        """Why ``inst`` may not be the copy of ``table`` Sisense joins for the current widget, or ''."""
        if not inst:
            return ""
        insts, has_fact = self._ctx
        known = self.t.path_known(table, inst, anchors, has_fact, self.relations)
        conflict = self.t.role_conflict(table, inst, insts, known, relations=self.relations)
        if not conflict and has_fact:     # the whole path, hop for hop, from each fact that reaches it
            conflict = next((p for a in anchors if inst in self.t.reachable(a)
                             for p in [path_problem(self.t, self.relations, a, inst, table)] if p), "")
        return f"{conflict} (map it via field_map / filter_map)" if conflict else ""

    def _calculated(self, table: str, col: str, inst: str, measure: bool):
        """A Sisense CALCULATED column -> the Model formula of the same (normalised) name on the
        same instance, of the same role: an attribute formula for a grouped field (Sisense groups
        by its row value), a measure formula for a measure. Never a plain column, which could be a
        different value by that name. The match is by name only, so the field reports it."""
        if (table, col) not in self.calculated:
            return None
        name = self.t.column_by_display(col)
        if name in self.t.formula_columns and (name in self.t.measures) == measure and \
                inst in self.t.instances_of.get(name, {inst}):
            return name
        return None

    def no_fact_problem(self, widget: dict, extra: tuple = ()) -> str:
        """For a widget naming no fact table: why ThoughtSpot may relate its tables (plus a chip's
        ``extra`` = (table, bound instance)) differently from Sisense, or ''. Sisense joins them along
        ITS relations: two of them related directly need that same join between the copies actually
        bound, and otherwise one fact Sisense relates to every one of them has to be the path."""
        bound = self._bound_tables(widget, extra)
        if bound is None or len(bound) < 2:
            return ""
        direct = self._direct_pairs(bound)
        unjoined = next((f"{a} and {b}" for a, b in direct if not self._joined(a, b, bound)), None)
        if unjoined:
            return f"Sisense joins {unjoined} directly, which the target model does not join between the copies bound"
        if direct and _connected(set(bound), direct):
            return ""      # every table joined directly, in Sisense and in the Model alike
        many = self._model_facts_problem(bound)
        if many:
            return many
        linking = self._linking_facts(bound)
        if len(linking) != 1:
            return ("the widget names no fact table, and no single fact Sisense relates to all of its tables "
                    f"({', '.join(sorted(bound))}) decides the path")
        return next((p for t, i in sorted(bound.items()) if i
                     for p in [path_problem(self.t, self.relations, linking[0], i, t)] if p), "")

    def _model_facts_problem(self, bound: dict) -> str:
        """More than one Model fact reaching every bound copy: ThoughtSpot's choice, not Sisense's."""
        facts = [r for r in self.t.roots() if all(i in self.t.reachable(r) for i in bound.values() if i)]
        if len(facts) > 1:
            return (f"the target model has {len(facts)} facts linking the widget's tables "
                    f"({', '.join(sorted(facts))}), so which one ThoughtSpot joins through is not Sisense's choice")
        return ""

    def _direct_pairs(self, bound: dict) -> list:
        ends = [{e.get("table") for e in r.get("endpoints") or []} for r in self.relations]
        return [(a, b) for a in sorted(bound) for b in sorted(bound) if a < b and {a, b} in ends]

    def _linking_facts(self, bound: dict) -> list:
        """The Sisense tables related to EVERY bound table (Sisense's shortest paths between them),
        kept only when the Model has that table as a fact joined on the same columns. More than one
        Sisense candidate is a tie in Sisense's own path choice, so the caller reports it."""
        neighbours = {}
        for r in self.relations:
            ends = [e.get("table") for e in r.get("endpoints") or []]
            for t in ends:
                neighbours.setdefault(t, set()).update(set(ends) - {t})
        linking = [t for t, ns in neighbours.items() if t not in bound and all(b in ns for b in bound)]
        if len(linking) != 1:
            return linking            # zero or a tie: not one decided path
        return self._model_fact_for(linking[0], bound) or linking + linking

    def _model_fact_for(self, sis_table: str, bound: dict) -> list:
        """The Model fact standing for a Sisense table, joined to every bound table on the same columns."""
        roots = [r for r in self.t.roots() if _same_name(self.t.base_of.get(r) or r, sis_table)
                 and all(self.t.fk_instances(t, [r], self.relations) for t in bound)]
        return roots if len(roots) == 1 else []

    def sisense_roots(self, widget: dict) -> list:
        """The Sisense tables standing for the facts the widget queries (none for a no-fact widget)."""
        anchors = self.anchors(widget)
        if not self._ctx[1]:
            return []
        names = {t: t for t in self.sis_tables}
        return [r for r in (_sisense_table(names, a, self.t.base_of.get(a)) for a in anchors) if r]

    def sisense_tables(self, widget: dict, extra: str = "") -> set:
        """The Sisense tables a widget (plus a chip's table) reads."""
        dims = [f.get("dim") for f in widget.get("fields", [])] + [sf.get("dim") for sf in widget.get("filters", [])]
        return {split_dim(d)[0] for d in dims if d} | ({extra} - {""})

    def _bound_tables(self, widget: dict, extra: tuple):
        """Sisense table -> the instance it binds to, for a widget naming NO fact (else None)."""
        anchors = self.anchors(widget)
        if self._ctx[1]:
            return None
        dims = [f.get("dim") for f in widget.get("fields", [])] + [sf.get("dim") for sf in widget.get("filters", [])]
        bound = {split_dim(d)[0]: self._bound_instance(d, anchors) for d in dims if d}
        if extra:
            bound[extra[0]] = extra[1]
        return bound

    def _bound_instance(self, dim: str, anchors: list):
        """The instance a widget's dim actually reads: the mapped column's, the filter_map
        fragment's columns' (one instance, else None), or the native resolution."""
        if dim in self.field_map:
            return self.t.single_instance(self.mapped(dim)[0] or "")
        if dim in self.filter_map:
            texts = [self.filter_map[dim]] if isinstance(self.filter_map[dim], str) else \
                [e.get("search") or "" for e in (self.filter_map[dim] if isinstance(self.filter_map[dim], list)
                                                 else [self.filter_map[dim]]) if isinstance(e, dict)]
            insts = set().union(*(self.t.instances_of.get(c, set()) for t in texts for c in _TOKEN.findall(t)))
            return next(iter(insts)) if len(insts) == 1 else None
        return self.t.resolve_instance(split_dim(dim)[0], anchors, self.relations)[0]

    def _joined(self, a: str, b: str, bound: dict) -> bool:
        """The Model joins the two BOUND copies on a column a Sisense relation uses."""
        ia, ib = bound[a], bound[b]
        return bool(ia and ib) and not one_hop_problem(self.t, self.relations, ia, ib, a, b)

    def _mapped_filter_path(self, dim: str, frag: str, anchors: list) -> tuple:
        """A filter_map fragment: every column it reads gets the same path check as a binding."""
        table = split_dim(dim)[0]
        for col in _TOKEN.findall(frag):
            inst = self.t.single_instance(col)
            problem = (f"filter_map column [{col}] reads several (or no) table instances, so its join path "
                       "cannot be checked") if inst is None else self._path_problem(table, inst, anchors)
            if problem:              # the user's own override stays in the query; the row says why to check it
                return frag, None, f"filter_map for {dim}: {problem}"
        return frag, None, ""

    def mapped(self, dim: str, agg: str = "") -> tuple:
        """field_map entry -> (model column | None, None, note). An entry is a column name, or a
        map from Sisense aggregation to column (``""`` for the column itself, grouped or filtered),
        because one Sisense dim can be plotted under several aggregations that need different
        Model columns. A name the Model lacks, or no entry for this use, is refused."""
        entry = self.field_map[dim]
        if isinstance(entry, dict):
            use = (agg or "").lower()
            if use not in entry:
                return None, None, (f"field_map for {dim} has no entry for {use or 'the plain column'} "
                                    f"(it maps {', '.join(sorted(k or '(plain)' for k in entry))})")
            entry = entry[use]
        if isinstance(entry, str) and entry in self.t.columns:
            return entry, None, ""
        return None, None, f"field_map maps {dim} to {entry!r}, which is not a column of the target model"

    def note_conditions(self, widgets: list) -> None:
        """Record every widget filter's condition per dim, so a filter_map entry that does not say
        which condition it replaces is used only where the dim has exactly one."""
        for w in widgets or []:
            for sf in w.get("filters", []):
                if sf.get("dim") and not is_all(sf) and sf.get("kind") != "top_n":
                    self.conditions.setdefault(sf["dim"], set()).add(condition_key(sf.get("raw"), sf.get("level")))

    def _filter_map_entry(self, dim: str, sf: dict) -> tuple:
        """-> (search fragment | None, note). An entry is a fragment, used only when every filter
        on the dim in the dashboard has the same condition, or a list of
        ``{"when": <Sisense filter>, "search": <fragment>}`` keyed by the condition it replaces."""
        entry = self.filter_map[dim]
        if isinstance(entry, str):
            if len(self.conditions.get(dim, set())) > 1:
                return None, (f"filter_map for {dim} is one fragment, but the dashboard filters {dim} with "
                              f"{len(self.conditions[dim])} different conditions; key it by condition "
                              '([{"when": <Sisense filter>, "search": <fragment>}])')
            return entry, ""
        entries = entry if isinstance(entry, list) else [entry]
        key = condition_key(sf.get("raw"), sf.get("level"))
        hit = next((e.get("search") for e in entries if isinstance(e, dict) and isinstance(e.get("when"), dict)
                    and condition_key(e["when"]) == key), None)
        return (hit, "") if hit else (None, f"filter_map for {dim} has no entry for this condition ({_show(sf)})")

    def mapped_filter(self, dim: str, sf: dict = None) -> tuple:
        """filter_map entry for one filter -> (fragment | None, None, note): a fragment for another
        condition, or a column the Model lacks, is refused."""
        frag, note = self._filter_map_entry(dim, sf or {})
        if note:
            return None, None, note
        problem = self._fragment_columns_problem(dim, frag) or self._fragment_problem(dim, frag)
        return (None, None, problem) if problem else (frag, None, "")

    def _fragment_columns_problem(self, dim: str, frag) -> str:
        if not isinstance(frag, str) or not _TOKEN.findall(frag):
            return f"filter_map for {dim} names no [column], so it cannot be checked against the target model"
        bad = [t for t in _TOKEN.findall(frag) if t not in self.t.columns]
        return f"filter_map for {dim} names {', '.join(bad)}, not a column of the target model" if bad else ""

    def _fragment_problem(self, dim: str, frag: str) -> str:
        """Why a filter_map fragment is not carried: the same value and operator rules as a native filter."""
        if _IN_LIST.search(frag):
            return (f"filter_map for {dim} uses `in (...)` / `not in (...)`, which ThoughtSpot search "
                    "ignores silently; write repeated `[col] = v` (ORed) or `[col] != v` (ANDed)")
        if _DATE_VALUE.search(frag) or any(t in self.t.date_columns for t in _TOKEN.findall(frag)):
            return (f"filter_map for {dim} filters a date value or a date column, and no search form "
                    "for a date value is verified")
        if not _FILTER_TERMS.fullmatch(frag):
            return (f"filter_map for {dim} is not a list of `[column] op value` terms (=, !=, <, <=, >, >=), "
                    "the only search filters whose behaviour is verified")
        shape = _term_problem(frag, self.t.boolean_columns, self.t.numeric_columns)
        if shape:
            return f"filter_map for {dim}: {shape}"
        measures = [t for t in _TOKEN.findall(frag) if t in self.t.measures]
        return (f"filter_map for {dim} filters [{measures[0]}], a Model measure, which ThoughtSpot would filter "
                "after aggregating while Sisense filters rows") if measures else ""

    # -- one plotted field -> search token + output column -----------------------------
    def field(self, f: dict, anchors: list) -> dict:
        """One plotted field -> its binding, or ``{"note"}`` when it is not carried. A binding a
        check could not confirm is KEPT with ``warn`` (the row is NEEDS REVIEW), so the tile shows
        what the converter found rather than silently losing a column."""
        dim, agg = f.get("dim"), (f.get("agg") or "").lower()
        unfit = _unfit_field(f, dim, agg)
        if unfit:
            return {"note": unfit}
        measure = f.get("kind") == "measure"
        name, inst, note = self.column(dim, anchors, measure=measure, agg=agg if measure else "")
        if not name:   # a count over a key the Model hides can still bind to a count formula
            if measure and inst and dim not in self.field_map and AGG_KEYWORD.get(agg) in ("unique count", "count"):
                return self._count_field(dim, AGG_KEYWORD[agg], inst)
            return {"note": note}
        if dim in self.field_map:
            b = self._mapped_field(f, name, inst)
        elif not measure:
            b = self._dimension_field(dim, name, "", f.get("level"))
        else:
            b = self._measure_field(dim, agg, name, inst, "")
        return dict(b, warn=note) if note and "note" not in b else b

    def _measure_field(self, dim: str, agg: str, name, inst, note: str) -> dict:
        kw = AGG_KEYWORD.get(agg)
        if not kw:
            return {"note": f"Sisense aggregation '{agg}' on {dim} has no mapped ThoughtSpot keyword"}
        fan_out = self._fan_out(dim, kw, name, inst)
        if fan_out:
            return {"note": fan_out}
        if name and name in self.t.formula_measures:
            return self._formula_measure(name, dim, agg, kw)
        if name:   # explicit keyword: a bare SUM column would come back as "Total <name>" anyway
            token = f"{kw} [{name}]"
            return {"name": name, "token": token, "out": f"{agg_label(token)} {name}", "measure": True}
        if inst and kw in ("unique count", "count"):
            return self._count_field(dim, kw, inst)
        return {"note": note}

    def _fan_out(self, dim: str, kw: str, name, inst) -> str:
        """An additive measure on a non-fact table, in a widget joining other tables: whether
        Sisense and ThoughtSpot repeat its rows the same way across the join is not verified."""
        if name and inst and inst not in self.t.roots() and kw in ("sum", "average", "count") and self._ctx[0] - {inst}:
            return (f"{kw} of {dim} aggregates a non-fact table's column across a join; whether Sisense and "
                    "ThoughtSpot repeat its rows the same way is not verified")
        return ""

    def non_fact_measures(self, widget: dict) -> set:
        """Instances of the widget's additive measures that are not facts (a join to them can repeat
        their rows)."""
        anchors = self.anchors(widget)
        out = set()
        for f in widget.get("fields", []):
            if f.get("kind") == "measure" and AGG_KEYWORD.get((f.get("agg") or "").lower()) in ("sum", "average", "count"):
                inst = self.column(f.get("dim") or "", anchors, measure=True, agg=(f.get("agg") or "").lower())[1]
                if inst and inst not in self.t.roots():
                    out.add(inst)
        return out

    def _dimension_field(self, dim: str, name, note: str, level) -> dict:
        if not name:
            return {"note": note}
        if name in self.t.measures:
            return {"note": f"{dim} is grouped by in Sisense, but Model column [{name}] is a measure, "
                            "which ThoughtSpot would aggregate"}
        return _dimension(name, level)

    def _count_field(self, dim: str, kw: str, inst: str) -> dict:
        table, col = split_dim(dim)
        cm = self.t.count_measure(kw, inst, col)
        fan_out = self._fan_out(dim, kw, cm, inst) if cm else ""
        if fan_out:
            return {"note": fan_out}
        if cm:   # bound through the Table mapping like any column: the same checks apply
            b = {"name": cm, "token": f"[{cm}]", "out": cm, "measure": True}
            guess = self._plain_binding_problem(table, col, inst) or self._physical(table, inst)
            return dict(b, warn=guess) if guess else b
        return {"note": f"{kw} of {table}.{col}: add a Model measure '{kw} ( [{inst}::{col}] )' or map it via field_map"}

    def _mapped_field(self, f: dict, name: str, inst=None) -> dict:
        """A field_map binding as a field, through the same checks as a native one: a grouped
        field mapped onto a measure, or an aggregation the Model formula does not compute, is
        refused (the path checks' findings come back as ``warn`` from ``field``)."""
        dim, agg = f.get("dim"), (f.get("agg") or "").lower()
        if f.get("kind") != "measure":
            return self._dimension_field(dim, name, "", f.get("level"))
        kw = AGG_KEYWORD.get(agg)
        if not kw:
            return {"note": f"Sisense aggregation '{agg}' on {dim} has no mapped ThoughtSpot keyword"}
        fan_out = self._fan_out(dim, kw, name, inst)
        if fan_out:
            return {"note": fan_out}
        if name in self.t.formula_measures:
            return self._formula_measure(name, dim, agg, kw)
        if name not in self.t.measures and kw not in ("unique count", "count"):
            return {"note": f"field_map binds {agg} of {dim} to [{name}], an attribute, which ThoughtSpot "
                            f"would not {kw}"}
        token = f"{kw} [{name}]"
        return {"name": name, "token": token, "out": f"{agg_label(token)} {name}", "measure": True}

    def _formula_measure(self, name: str, dim: str, agg: str, kw: str) -> dict:
        """A measure bound to a Model formula (natively or by field_map): carried only when the
        formula's own outer aggregation is the Sisense one, since the formula's output is used
        as it is and the Sisense aggregation is not applied on top."""
        fa = self.t.formula_agg.get(name)
        if fa != kw:
            how = "mapped by field_map" if dim in self.field_map else "bound"
            return {"note": f"Sisense {agg} of {dim} is {how} to Model formula [{name}], which is "
                            f"{('a ' + fa) if fa else 'not a single ' + kw}; key field_map by aggregation "
                            f"to a column that computes the {kw}"}
        return {"name": name, "token": f"[{name}]", "out": name, "measure": True}

    # -- one widget/drill filter -> search fragment -------------------------------------
    def filter_fragment(self, sf: dict, anchors: list) -> tuple:
        """-> (fragment | None, model column | None, note)."""
        dim = sf.get("dim") or ""
        if dim in self.filter_map and not is_all(sf) and sf.get("kind") != "top_n":
            frag, col, note = self.mapped_filter(dim, sf)
            return (frag, col, note) if note or not frag else self._mapped_filter_path(dim, frag, anchors)
        name, _, note = self.column(dim, anchors)
        if name and note:
            return None, name, f"filter on {dim}: {note}"
        if sf.get("kind") == "top_n":        # the ranking is decided per widget (target_filters.top_n),
            return None, name, ""            # but the widget filters that column itself
        if is_all(sf) and not sf.get("unsupported"):
            return None, name, ""            # "all" = no condition; the widget still owns the column
        if not name:
            return None, None, f"filter on {dim}: {note} (map it via filter_map)"
        frag, problem = self._native_filter(sf, name)
        if problem:
            return None, name, f"filter on {dim}: {problem} (map it via filter_map)"
        return frag, name, ""

    def _native_filter(self, sf: dict, name: str) -> tuple:
        """A widget filter on Model column ``name`` -> (search fragment | None, problem | None)."""
        boolean = name in self.t.boolean_columns
        problem = (_boolean_filter_problem(sf) if boolean else "") or _text_value_problem(sf, name in self.t.numeric_columns)
        if problem:
            return None, problem
        frag, problem = widget_filter(sf, name, boolean_ok=boolean)
        if not problem and name in self.t.measures:
            problem = f"it filters rows of [{name}], a Model measure, which ThoughtSpot would filter after aggregating"
        return frag, problem


def _query_columns(frags: list) -> set:
    return {c for f in frags for c in _TOKEN.findall(f)}


def _collect_filters(widget: dict, binder: _Binder, anchors: list) -> tuple:
    """Widget filters -> (search fragments, columns the widget filters itself, notes). A column
    the widget filters at all -- even with `all`, a filter that is not carried, or one replaced
    by filter_map -- is its own: in Sisense a widget filter takes priority over a dashboard filter
    on the same dimension. Only the columns the emitted fragments READ decide the query's facts
    (``_query_columns``)."""
    frags, own, notes, seen = [], set(), [], {}
    for sf in widget.get("filters", []):
        frag, col, fnote = binder.filter_fragment(sf, anchors)
        if frag:
            frags.append(frag)
        mapped = (sf.get("dim") or "") in binder.filter_map
        # a mapped filter still owns its Sisense dimension's column (a chip on it must not apply)
        cols = {col} if col else set(_TOKEN.findall(frag or "")) | ({binder.column(sf.get("dim") or "", anchors)[0]} - {None}
                                                                    if mapped else set())
        own.update(cols)
        if fnote:
            notes.append(fnote)
        if sf.get("kind") != "top_n" and not is_all(sf):
            for c in cols:
                seen[c] = seen.get(c, 0) + 1
    notes += [f"{n} filters on [{c}]: Sisense applies all of them, which one search cannot express "
              "(repeated `=` would be ORed)" for c, n in seen.items() if n > 1]
    return frags, own, notes


# Sisense shows full values; ThoughtSpot's default number format abbreviates (32.16K), which
# customers reject on migrated boards. Trailing zeroes are dropped, so counts stay integral.
FULL_NUMBER_FORMAT = {"category": "NUMBER", "isCategoryEditable": True, "numberFormatConfig": {
    "unit": "NONE", "decimals": 2.0, "negativeValueFormat": "PREFIX_DASH",
    "toSeparateThousands": True, "removeTrailingZeroes": True}}


def _finish_answer(a: dict, binder: _Binder, ct: str, frags: list, labels: dict, description=None,
                   measures=None) -> dict:
    """Sisense-local additions to an emitted answer: exact binding, filters, titles, mode, format."""
    if binder.t.obj_id:
        a["tables"] = [{"id": binder.t.name, "name": binder.t.name, "obj_id": binder.t.obj_id}]
    if frags:
        a["search_query"] = a["search_query"] + " " + " ".join(frags)
    for ac in a["answer_columns"]:
        if ac["name"] in labels:
            ac["custom_name"] = labels[ac["name"]]
        source = (measures or {}).get(ac["name"])
        # the Model's own format (a percent, a currency) wins over the full-value default
        if source and source not in binder.t.formatted and not ac["name"].lstrip().startswith("%"):
            ac["format"] = copy.deepcopy(FULL_NUMBER_FORMAT)
    if ct in ("GRID_TABLE", "PIVOT_TABLE"):
        a["display_mode"] = "TABLE_MODE"
    if description:
        a["description"] = description
    return a


def _answer_for(widget: dict, binder: _Binder, ctx: dict, title_override=None) -> tuple:
    """Widget -> (answer payload | None, report row, own filter columns, facts it queries)."""
    from ts_cli.tableau.liveboard import build_answer
    title = title_override or widget.get("title") or "Visual"
    ct, status, note = chart_type_for(widget.get("wtype"), widget.get("subtype"))
    anchors = binder.anchors(widget)
    acc = _collect_fields(widget, binder, anchors)
    frags, own, fnotes = _collect_filters(widget, binder, anchors)
    n, rank_frag, rank_notes = top_n(widget, acc["measure_fields"], acc["dimension_fields"])
    notes, info = _widget_notes(widget, status, note, acc["notes"] + fnotes + rank_notes + _source_note(widget, binder))
    row = {"visual": title, "ts_chart": ct, "status": status}
    if not acc["cols"]:
        row.update(status="NEEDS REVIEW", note="; ".join(notes + info) or "no fields mapped")
        return None, row, own, []
    read = acc["cols"] + sorted(_query_columns(frags))
    notes += _join_notes(widget, binder, read) + _settings_notes(binder, anchors, read, acc["cols"] + _null_keeping(frags))
    if notes:
        row["status"] = "NEEDS REVIEW"
    if notes or info:
        row["note"] = "; ".join(notes + info)
    # the ranking goes last, after every filter: ThoughtSpot ranks the filtered rows whatever the
    # token order (live-verified 26.11), and last reads that way too
    rank = f"top {n}" if n else rank_frag
    a = build_answer(title, f"{ctx['key']}", binder.t.name, ctx.get("model_fqn"), acc["cols"], ct,
                     acc["measures"], acc["roles"], _token_map(acc["tokens"]))["answer"]
    a = _finish_answer(a, binder, ct, frags + ([rank] if rank else []), acc["labels"],
                       ctx.get("description"), acc["measure_outs"])
    row["_read"] = read           # for the per-tile join-tree check with every chip (target_chips)
    return a, row, own, binder.t.facts_for(read)


def _unfit_field(f: dict, dim, agg: str) -> str:
    """A field this path does not bind at all: a Sisense formula, or a measure at a date level."""
    if f.get("formula"):
        return (f"formula field '{f.get('title') or '?'}' is a Sisense formula, which this path does not "
                "translate or map; add the measure to the Model and bind it by hand")
    if f.get("kind") == "measure" and f.get("level"):    # e.g. a count of distinct months
        return (f"Sisense {agg or 'measure'} of {dim} at level {f['level']} counts or aggregates date periods, "
                "which this converter does not emit")
    return ""


def _settings_notes(binder, anchors: list, read: list, null_side: list) -> list:
    """The Model's own settings on what this tile reads: a column or Table setting that changes
    its numbers, and a join that is not Sisense's INNER. A LEFT_OUTER join matters on the path to
    a column whose unmatched rows the tile shows (a plotted column or an exclude); a column read
    only by `=` or a range drops them either way. Any other outer join keeps rows of the far side
    and matters on the path to every column the tile reads."""
    t = binder.t
    out = [t.column_problems[c] for c in dict.fromkeys(read) if c in t.column_problems]
    reads = set().union(*(t.instances_of.get(c, set()) for c in read)) if read else set()
    on_path = reads | _joined_through(t, anchors if binder._ctx[1] else [], anchors, reads)
    out += sorted({t.table_problems[t.base_of.get(i)] for i in on_path if t.base_of.get(i) in t.table_problems})
    out += sorted({p for i in on_path - reads for p in [binder.path_table_problem(i)] if p})
    nulls = set().union(*(t.instances_of.get(c, set()) for c in null_side)) if null_side else set()
    joined = join_type_problem(t, anchors, nulls, reads)
    return out + ([joined] if joined else [])


def _joined_through(t, facts: list, linking: list, reads: set) -> set:
    """The instances a tile's query joins through. A widget naming facts joins from them; one
    naming none joins its tables to each other directly where the Model can, else through the facts
    that link them (``linking``), whose settings then change its rows too."""
    if facts:
        return path_instances(t, facts, reads)
    direct = path_instances(t, [], reads)
    if len(reads) > 1 and not reads <= direct:
        return direct | path_instances(t, linking, reads)
    return direct


def _null_keeping(frags: list) -> list:
    """Columns of the filter fragments that keep NULL rows: `!=` (live-verified, 26.11)."""
    return [c for f in frags for c in re.findall(r"\[([^\]]+)\]\s*!=", f)]


def _source_note(widget: dict, binder) -> list:
    dash_source = (binder.inv.get("dashboard") or {}).get("datasource")
    if widget.get("datasource") and dash_source and widget["datasource"] != dash_source:
        return [f"the widget reads data source '{widget['datasource']}', not the dashboard's '{dash_source}'"]
    return []


def _join_notes(widget: dict, binder, read: list) -> list:
    """Widget-level join problems: a no-fact path, a Sisense loop among its tables, several facts."""
    out = []
    path = binder.no_fact_problem(widget) or loop_problem(binder.relations, binder.sisense_tables(widget),
                                                          binder.sisense_roots(widget))
    if path:
        out.append(path)
    if binder.t.spans_facts(read):
        out.append("its columns span facts no single fact reaches (a multi-fact query), which is not "
                   "verified to return Sisense's numbers")
    return out


def _widget_notes(widget: dict, status: str, chart_note: str, problems: list) -> tuple:
    """-> (problems that make the tile NEEDS REVIEW, informative notes)."""
    unsupported = widget.get("unsupported") or []
    notes = ([chart_note] if chart_note and status == "NEEDS REVIEW" else []) + problems + (
        [f"widget carries settings this converter does not read: {', '.join(unsupported)}"] if unsupported else [])
    info = ([f"disabled widget filter(s) in Sisense, not applied: {', '.join(widget['disabled_filters'])}"]
            if widget.get("disabled_filters") else []) + ([chart_note] if chart_note and status != "NEEDS REVIEW" else []) \
        + list(widget.get("info") or [])
    return notes, info


def _token_map(tokens: dict) -> dict:
    """Only non-bare tokens go to the emitter (it renders `[col]` itself)."""
    return {c: t for c, t in tokens.items() if t != f"[{c}]"}


def _widget_tiles(inv, widgets, binder, model_fqn) -> tuple:
    """Widgets -> (report rows, placed, content, drill sources). Hidden tabs are Merged, rich
    text and tab-set titles become notes, everything else an Answer."""
    (hidden, other_tabs), kept_tabs = _hidden_tabs(widgets), _kept_tabs(widgets)
    rows, placed, content, drill_sources, merged = [], {}, {}, {}, []
    for i, w in enumerate(widgets):
        oid = w.get("oid") or f"w{i}"
        if oid in hidden:
            rows.append(_merged_row(w, hidden[oid][0]))
            merged.append((rows[-1], hidden[oid][1]))
        elif w.get("wtype") in ("WidgetsTabber", "richtexteditor"):
            placed[oid], content[oid] = {"kind": "note", "ct": None}, ("note", _note_text(w, inv))
        else:
            title = _GRAIN_SUFFIX.sub("", w.get("title") or "") if oid in kept_tabs else None
            a, row, own, facts = _answer_for(w, binder, {"key": oid, "model_fqn": model_fqn}, title or None)
            if oid in other_tabs:
                row["note"] = "; ".join(filter(None, [row.get("note"), (
                    f"hidden tab of tab set '{other_tabs[oid]}', not a date-grain variant of the shown "
                    "tab, so it is a tile of its own")]))
            rows.append(row)
            if a:
                placed[oid], content[oid] = {"kind": "answer", "ct": row["ts_chart"]}, ("answer", a, own, facts, row, w)
                for tgt in w.get("drill_targets") or []:
                    drill_sources.setdefault(tgt, []).append(w)
    _link_merged(merged, placed, content)
    return rows, placed, content, drill_sources


def _merged_row(w: dict, tab_set: str) -> dict:
    """A hidden grain of a tab set; a weekly grain is flagged (week start)."""
    row = {"visual": w.get("title"), "ts_chart": "(tab)", "status": "Merged",
           "note": f"other grain of tab set '{tab_set}'; change it in the chart's date bucket"}
    warning = next((_field_warning(f) for f in w.get("fields", []) if _field_warning(f)), None)
    if warning:
        row.update(status="NEEDS REVIEW", note=f"{row['note']}; {warning}")
    return row


def _link_merged(merged: list, placed: dict, content: dict) -> None:
    """A grain of a tab with no tile is NEEDS REVIEW; otherwise it is linked to the tile's row,
    whose final status (after the chip checks) it shares."""
    for row, shown in merged:
        if shown not in placed:
            row.update(status="NEEDS REVIEW", note="the tab it is a grain of could not be carried, so there is no tile to merge into")
        else:
            row["_into"] = content[shown][4]


def _assemble(inv, placed, content) -> tuple:
    """Placed tiles -> (visualizations, layout tiles, tiles for the chip checks, answers)."""
    viz, layout, viz_meta, answers = [], [], [], []
    for n, (oid, x, y, w, h) in enumerate(sorted(_place(inv, placed), key=lambda t: (t[2], t[1])), 1):
        vid, item = f"Viz_{n}", content[oid]
        if item[0] == "note":
            viz.append({"id": vid, "note_tile": note_tile(item[1])})
        else:
            viz.append({"id": vid, "answer": item[1]})
            answers.append({"answer": item[1]})
            viz_meta.append({"vid": vid, "own": item[2], "facts": item[3], "title": item[1]["name"],
                             "row": item[4], "widget": item[5]})
        layout.append({"visualization_id": vid, "x": x, "y": y, "height": h, "width": w})
    return viz, layout, viz_meta, answers


def _settings_rows(inv: dict, target: TargetModel, tiles: list, answers: list, chips: list, done: list) -> list:
    """Board-level rows: a Model or Sisense setting that changes every query flags every tile;
    the join-type explanation once when a tile or chip was flagged for it; text value matching
    is one row naming the tiles and chips to compare."""
    rows = []
    for reason in board_reasons(inv, target):
        rows.append({"visual": "(target model settings)", "ts_chart": "-", "status": "NEEDS REVIEW", "note": reason})
        for t in tiles:
            flag_tile(t, reason)
    flagged = any("join not INNER" in (r.get("note") or "") for r in done)
    matching = value_matching_row(answers, chips)
    if matching:                     # every tile it names is NEEDS REVIEW, as for any unverified setting
        for t in tiles:
            if t["title"] in matching["_tiles"] or set(t.get("chips") or ()) & set(matching["_chips"]):
                flag_tile(t, "a text or number filter whose matching against Sisense's is not verified "
                             "(see the filter value matching row)")
        matching = {k: v for k, v in matching.items() if not k.startswith("_")}
    extra = [r for r in (join_type_row(target) if flagged else None, matching) if r]
    return rows + extra


def _warning_rows(inv: dict, drills) -> list:
    """Every parse warning (a skipped relation, an unreadable widget) is a report row, not only stderr."""
    # a drill dashboard export never carries the data model: that warning is expected for it
    warnings = (inv.get("warnings") or []) + [w for d in drills or [] for w in d.get("warnings") or []
                                              if not w.startswith("No 'datamodel'")]
    return [{"visual": "(parse warning)", "ts_chart": "-", "status": "NEEDS REVIEW", "note": w} for w in warnings]


def _board_rows(rows: list, tables) -> list:
    """After the chip checks: a grain merged into a flagged tile shares its risk; a missing Table
    TML export is one board-level row."""
    for row in rows:
        into = row.pop("_into", None)
        if into is not None and into["status"] == "NEEDS REVIEW":
            row.update(status="NEEDS REVIEW", note=f"{row['note']}; the tile it merges into is NEEDS REVIEW")
    if tables:
        return []
    for row in rows:                 # every binding was made by Table column name: none is verified
        if row.get("status") in ("Migrated", "Approximated", "Merged"):
            row.update(status="NEEDS REVIEW", note="; ".join(filter(None, [row.get("note"), (
                "bound without the Model's Table TMLs (export with --associated)")])))
    return [{"visual": "(target model Tables)", "ts_chart": "-", "status": "NEEDS REVIEW",
             "note": "the Model's Table TMLs were not supplied (export with --associated), so warehouse "
                     "columns were matched by Table column name rather than db_column_name"}]


def _add_drills(drills: list, rows: list, placed: dict, content: dict) -> None:
    """Each drill details table: its report row, and (when built) a header note and the tile."""
    for key, a, row, own, facts, dw in drills:
        rows.append(row)
        if a:
            placed[key + ":note"], content[key + ":note"] = {"kind": "note", "ct": None}, ("note", row["visual"])
            placed[key], content[key] = {"kind": "answer", "ct": "GRID_TABLE"}, ("answer", a, own, facts, row, dw)


def _make_binder(inv: dict, target_tml: dict, tables, overrides: dict, drills) -> tuple:
    target = TargetModel(target_tml, tables)
    target.declared_connections = overrides.get("connections") or {}
    binder = _Binder(inv, target, overrides)
    binder.note_conditions((inv.get("widgets") or []) + [w for d in drills or [] for w in d.get("widgets") or []])
    return target, binder


def build_target_liveboard(inv: dict, target_tml: dict, model_fqn=None, overrides=None,
                           drills=None, tables=None) -> dict:
    """Parsed Sisense inventory + target Model TML (+ its Table TMLs, optional) ->
    {answers, liveboard, visual_rows, report_name}."""
    overrides = overrides or {}
    target, binder = _make_binder(inv, target_tml, tables, overrides, drills)
    report_name = overrides.get("report_name") or (inv.get("dashboard") or {}).get("title") or target.name
    fqn = model_fqn or target_tml.get("guid")
    rows, placed, content, drill_sources = _widget_tiles(inv, inv.get("widgets", []) or [], binder, fqn)
    _add_drills(drill_tables(drills, binder, drill_sources, fqn, _answer_for), rows, placed, content)
    viz, layout, tiles, answers = _assemble(inv, placed, content)
    chips, chip_rows = build_chips(inv, binder, tiles)
    chip_rows += _settings_rows(inv, target, tiles, answers, chips, rows + chip_rows)
    chip_rows += _board_rows(rows, tables) + _warning_rows(inv, drills)
    for row in rows:
        row.pop("_read", None)
    lb = {"liveboard": {"name": report_name, "visualizations": viz, "layout": {"tiles": layout}}}
    if chips:
        lb["liveboard"]["filters"] = chips
    return {"answers": answers, "liveboard": lb if viz else None, "visual_rows": rows + chip_rows,
            "report_name": report_name, "filter_chips": len(chips)}
