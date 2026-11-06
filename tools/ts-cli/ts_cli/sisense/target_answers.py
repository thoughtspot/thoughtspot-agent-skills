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

from ts_cli.sisense.answers import chart_type_for, date_bucket_suffix
from ts_cli.sisense.target_chips import build_chips
from ts_cli.sisense.target_drills import drill_tables
from ts_cli.sisense.target_layout import _note_text, _place, note_tile
from ts_cli.sisense.target_tabs import _GRAIN_SUFFIX, _hidden_tabs, _kept_tabs, tabber_hidden
from ts_cli.sisense.target_filters import is_all, top_n, widget_filter
from ts_cli.sisense.target_model import TargetModel, split_dim
from ts_cli.tableau.liveboard import agg_label

# Sisense agg -> ThoughtSpot search keyword. Sisense `count` is a DISTINCT count.
AGG_KEYWORD = {"count": "unique count", "countduplicates": "count", "sum": "sum",
               "avg": "average", "average": "average", "min": "min", "max": "max"}
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
        self.calculated = _calculated_columns(inv)
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

    def column(self, dim: str, anchors: list, measure: bool = False) -> tuple:
        """Sisense dim -> (model column | None, instance | None, note). A binding made only by
        name (a Sisense calculated column to a Model formula) comes back with that note even
        though a column was found: it is a guess the Model's author has to confirm."""
        table, col = split_dim(dim)
        if table in self.multi_rel:
            return None, None, (f"Sisense relates {table} through a relation that is not one column to one "
                                "column, which this converter does not read")
        if dim in self.field_map:            # the map chooses the column; the path checks still run
            name, _, note = self.mapped(dim)
            inst = self.t.single_instance(name) if name else None
            return (name, inst, self._path_problem(table, inst, anchors) or note) if name else (None, None, note)
        inst, note = self.t.resolve_instance(table, anchors, self.relations)
        if not inst:
            return None, None, note
        conflict = self._path_problem(table, inst, anchors)
        if conflict:
            return None, None, conflict
        name = self.t.column(inst, col)
        if name:
            return name, inst, ""
        name = self._calculated(table, col, inst, measure)
        if name:
            return name, inst, (f"Sisense calculated column {table}.{col} is bound to Model formula [{name}] by "
                                "name only; confirm it is the same calculation (map it via field_map)")
        return None, inst, f"{table}.{col} is not exposed on the target model"

    def _path_problem(self, table: str, inst, anchors: list) -> str:
        """Why ``inst`` may not be the copy of ``table`` Sisense joins for the current widget, or ''."""
        if not inst:
            return ""
        insts, has_fact = self._ctx
        known = self.t.path_known(table, inst, anchors, has_fact, self.relations)
        conflict = self.t.role_conflict(table, inst, insts, known, relations=self.relations)
        return f"{conflict} (map it via field_map / filter_map)" if conflict else ""

    def _calculated(self, table: str, col: str, inst: str, measure: bool):
        """A Sisense CALCULATED column -> the Model ATTRIBUTE formula of the same (normalised) name
        on the same instance; never any other column, which could be a different measure by that
        name, and never a measure formula (Sisense groups by a calculated column's row value).
        The match is by name only, so the field reports it (``calculated_by_name``)."""
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
        if len(self._linking_facts(bound)) != 1:
            return ("the widget names no fact table, and no single fact Sisense relates to all of its tables "
                    f"({', '.join(sorted(bound))}) decides the path")
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
            return self.t.single_instance(self.field_map[dim])
        if dim in self.filter_map:
            insts = set().union(*(self.t.instances_of.get(c, set()) for c in _TOKEN.findall(self.filter_map[dim])))
            return next(iter(insts)) if len(insts) == 1 else None
        return self.t.resolve_instance(split_dim(dim)[0], anchors, self.relations)[0]

    def _joined(self, a: str, b: str, bound: dict) -> bool:
        """The Model joins the two BOUND copies on a column a Sisense relation uses."""
        ia, ib = bound[a], bound[b]
        return bool(ia and ib and (ib in self.t.fk_instances(b, [ia], self.relations)
                                   or ia in self.t.fk_instances(a, [ib], self.relations)))

    def mapped(self, dim: str) -> tuple:
        """field_map entry -> (model column | None, None, note): a name the Model lacks is refused."""
        name = self.field_map[dim]
        if name in self.t.columns:
            return name, None, ""
        return None, None, f"field_map maps {dim} to '{name}', which is not a column of the target model"

    def mapped_filter(self, dim: str) -> tuple:
        """filter_map entry -> (fragment | None, None, note): a column the Model lacks is refused."""
        frag = self.filter_map[dim]
        if not _TOKEN.findall(frag):
            return None, None, f"filter_map for {dim} names no [column], so it cannot be checked against the target model"
        bad = [t for t in _TOKEN.findall(frag) if t not in self.t.columns]
        if bad:
            return None, None, f"filter_map for {dim} names {', '.join(bad)}, not a column of the target model"
        return frag, None, ""

    # -- one plotted field -> search token + output column -----------------------------
    def field(self, f: dict, anchors: list) -> dict:
        dim, agg = f.get("dim"), (f.get("agg") or "").lower()
        if f.get("formula"):
            return {"note": f"formula field '{f.get('title') or '?'}' needs a Model measure (map it via field_map)"}
        name, inst, note = self.column(dim, anchors, measure=f.get("kind") == "measure")
        if name and note:                     # bound by name only: reported, not carried
            return {"note": note}
        if f.get("kind") != "measure":
            return self._dimension_field(dim, name, note, f.get("level"))
        kw = AGG_KEYWORD.get(agg)
        if not kw:
            return {"note": f"Sisense aggregation '{agg}' on {dim} has no mapped ThoughtSpot keyword"}
        if name and name in self.t.formula_measures:
            return self._formula_measure(name, dim, agg, kw)
        fan_out = self._fan_out(dim, kw, name, inst)
        if fan_out:
            return {"note": fan_out}
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
        if cm:
            return {"name": cm, "token": f"[{cm}]", "out": cm, "measure": True}
        return {"note": f"{kw} of {table}.{col}: add a Model measure '{kw} ( [{inst}::{col}] )' or map it via field_map"}

    def _formula_measure(self, name: str, dim: str, agg: str, kw: str) -> dict:
        """A measure bound to a Model formula: carried only when the formula's own aggregation
        is the Sisense one (or the binding was mapped by hand)."""
        fa = self.t.formula_agg.get(name)
        if dim not in self.field_map and fa != kw:
            return {"note": f"Sisense {agg} of {dim} binds to Model formula [{name}], which is "
                            f"{('a ' + fa) if fa else 'not a single ' + kw} (map it via field_map if it is the same measure)"}
        return {"name": name, "token": f"[{name}]", "out": name, "measure": True}

    # -- one widget/drill filter -> search fragment -------------------------------------
    def filter_fragment(self, sf: dict, anchors: list) -> tuple:
        """-> (fragment | None, model column | None, note)."""
        dim = sf.get("dim") or ""
        if dim in self.filter_map:
            return self.mapped_filter(dim)
        name, _, note = self.column(dim, anchors)
        if name and note:
            return None, name, f"filter on {dim}: {note}"
        if sf.get("kind") == "top_n":        # the ranking is decided per widget (target_filters.top_n),
            return None, name, ""            # but the widget filters that column itself
        if is_all(sf):
            return None, name, ""            # "all" = no condition; the widget still owns the column
        if not name:
            return None, None, f"filter on {dim}: {note} (map it via filter_map)"
        frag, problem = widget_filter(sf, name)
        if not problem and name in self.t.measures:
            problem = (f"it filters rows of [{name}], a Model measure, which ThoughtSpot would filter "
                       "after aggregating")
        if problem:
            return None, name, f"filter on {dim}: {problem} (map it via filter_map)"
        return frag, name, ""


def _dimension(name: str, level) -> dict:
    suf = date_bucket_suffix(level)
    if level and not suf:
        return {"note": f"date level {level} on [{name}] has no ThoughtSpot bucket, so its grain is not carried"}
    token = f"[{name}].{suf.lower()}" if suf else f"[{name}]"
    out = f"{_bucket_out(suf)}({name})" if suf else name
    return {"name": name, "token": token, "out": out, "measure": False, "bucketed": bool(suf)}


def _bucket_out(suf: str) -> str:
    return {"HOURLY": "Hour", "DAILY": "Day", "WEEKLY": "Week", "MONTHLY": "Month",
            "QUARTERLY": "Quarter", "YEARLY": "Year"}[suf]


_ROLE_OF_PANEL = {"categories": "Category", "x-axis": "Category", "rows": "Rows", "columns": "Columns",
                  "break by": "Series", "break-by": "Series", "break by / color": "Series", "color": "Series",
                  "point": "Category"}
_UNPLOTTED_PANELS = ("filters", "min", "max")      # gauge bounds; `secondary` is a shown value


def _label_for(f: dict, b: dict):
    """Sisense title -> custom_name, unless it is just the column (or a bucketed date)."""
    title = (f.get("title") or "").strip()
    if not title or b.get("bucketed") or title.lower() == b["out"].lower():
        return None
    if not b["measure"] and title.replace("_", "").lower() == split_dim(f.get("dim"))[1].replace("_", "").lower():
        return None
    return title


def _collect_fields(widget: dict, binder: _Binder, anchors: list) -> dict:
    """Plotted fields -> {cols, roles, tokens, measures, measure_outs, labels, notes}."""
    acc = {"cols": [], "roles": [], "tokens": {}, "measures": set(), "measure_outs": {}, "labels": {},
           "notes": [], "measure_fields": [], "dimension_fields": []}
    for f in widget.get("fields", []):
        panel = (f.get("panel") or "").lower()
        if panel in _UNPLOTTED_PANELS:
            continue
        problem = _field_problem(f, panel)
        if problem:
            acc["notes"].append(problem)
            continue
        b = binder.field(f, anchors)
        if "note" in b:
            acc["notes"].append(b["note"])
            continue
        _add_field(acc, f, b, panel, binder)
    return acc


def _add_field(acc: dict, f: dict, b: dict, panel: str, binder) -> None:
    """One bound field into the answer accumulator; a second use of a column is reported."""
    if _field_warning(f):
        acc["notes"].append(_field_warning(f))
    if f.get("percent") and b["measure"] and b["name"] not in binder.t.formatted:
        acc["notes"].append(f"Sisense shows {f.get('title') or b['name']} as a percent; Model column "
                            f"[{b['name']}] has no format of its own, so it would show as a plain number")
    if b["name"] in acc["cols"]:
        if acc["tokens"][b["name"]] != b["token"]:   # same column, another aggregation or grain
            acc["notes"].append(f"{b['token']} is not carried: the answer already uses [{b['name']}] "
                                f"as {acc['tokens'][b['name']]}, and one answer carries one use per column")
        return
    acc["cols"].append(b["name"])
    acc["roles"].append("Values" if b["measure"] else (_ROLE_OF_PANEL.get(panel) or "Category"))
    acc["tokens"][b["name"]] = b["token"]
    if b["measure"]:
        acc["measures"].add(b["name"])
        acc["measure_outs"][b["out"]] = b["name"]
        acc["measure_fields"].append(f)
    else:
        acc["dimension_fields"].append(f)
    label = _label_for(f, b)
    if label:
        acc["labels"][b["out"]] = label


def _query_columns(frags: list) -> set:
    return {c for f in frags for c in _TOKEN.findall(f)}


def _field_problem(f: dict, panel: str):
    """Why a plotted field cannot be carried as a plain column, or None."""
    what = f.get("title") or f.get("dim") or "?"
    if f.get("disabled"):
        return f"field {what} is disabled in Sisense; not carried"
    if f.get("quick_function"):
        return f"field {what} applies the Sisense quick function {f['quick_function']}, which is not carried"
    if panel == "secondary":
        return f"the secondary value {what} is not carried"
    return None


def _field_warning(f: dict):
    """Why a carried field may not match Sisense exactly (the field stays; the tile is flagged)."""
    what = f.get("title") or f.get("dim") or "?"
    if f.get("dateTimeLevel"):
        return f"field {what} has Sisense date-time level {f['dateTimeLevel']}, which is not carried"
    if (f.get("level") or "").lower() == "weeks":
        start = f"starting on {f['firstday']}" if f.get("firstday") else "with the Sisense server's week start"
        return (f"field {what} buckets weeks {start}; ThoughtSpot's weekly bucket follows the cluster's "
                "week start, so confirm they match")
    return None


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
    dash_source = (binder.inv.get("dashboard") or {}).get("datasource")
    other_source = ([f"the widget reads data source '{widget['datasource']}', not the dashboard's '{dash_source}'"]
                    if widget.get("datasource") and dash_source and widget["datasource"] != dash_source else [])
    notes, info = _widget_notes(widget, status, note, acc["notes"] + fnotes + rank_notes + other_source)
    row = {"visual": title, "ts_chart": ct, "status": status}
    if not acc["cols"]:
        row.update(status="NEEDS REVIEW", note="; ".join(notes + info) or "no fields mapped")
        return None, row, own, []
    read = acc["cols"] + sorted(_query_columns(frags))
    path = binder.no_fact_problem(widget)
    if path:
        notes.append(path)
    if binder.t.spans_facts(read):
        notes.append("its columns span facts no single fact reaches (a multi-fact query), which is not "
                     "verified to return Sisense's numbers")
    if notes:
        row["status"] = "NEEDS REVIEW"
    if notes or info:
        row["note"] = "; ".join(notes + info)
    a = build_answer(title, f"{ctx['key']}", binder.t.name, ctx.get("model_fqn"), acc["cols"], ct,
                     acc["measures"], acc["roles"], _token_map(acc["tokens"]), n)["answer"]
    a = _finish_answer(a, binder, ct, frags + ([rank_frag] if rank_frag else []), acc["labels"],
                       ctx.get("description"), acc["measure_outs"])
    return a, row, own, binder.t.facts_for(read)


def _widget_notes(widget: dict, status: str, chart_note: str, problems: list) -> tuple:
    """-> (problems that make the tile NEEDS REVIEW, informative notes)."""
    unsupported = widget.get("unsupported") or []
    notes = ([chart_note] if chart_note and status == "NEEDS REVIEW" else []) + problems + (
        [f"widget carries settings this converter does not read: {', '.join(unsupported)}"] if unsupported else [])
    info = ([f"disabled widget filter(s) in Sisense, not applied: {', '.join(widget['disabled_filters'])}"]
            if widget.get("disabled_filters") else []) + ([chart_note] if chart_note and status != "NEEDS REVIEW" else [])
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
    weekly = next((_field_warning(f) for f in w.get("fields", []) if (f.get("level") or "").lower() == "weeks"), None)
    if weekly:
        row.update(status="NEEDS REVIEW", note=f"{row['note']}; {weekly}")
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


def build_target_liveboard(inv: dict, target_tml: dict, model_fqn=None, overrides=None,
                           drills=None, tables=None) -> dict:
    """Parsed Sisense inventory + target Model TML (+ its Table TMLs, optional) ->
    {answers, liveboard, visual_rows, report_name}."""
    overrides = overrides or {}
    target = TargetModel(target_tml, tables)
    binder = _Binder(inv, target, overrides)
    report_name = overrides.get("report_name") or (inv.get("dashboard") or {}).get("title") or target.name
    fqn = model_fqn or target_tml.get("guid")
    rows, placed, content, drill_sources = _widget_tiles(inv, inv.get("widgets", []) or [], binder, fqn)
    _add_drills(drill_tables(drills, binder, drill_sources, fqn, _answer_for), rows, placed, content)
    viz, layout, tiles, answers = _assemble(inv, placed, content)
    chips, chip_rows = build_chips(inv, binder, tiles)
    chip_rows += _board_rows(rows, tables) + _warning_rows(inv, drills)
    lb = {"liveboard": {"name": report_name, "visualizations": viz, "layout": {"tiles": layout}}}
    if chips:
        lb["liveboard"]["filters"] = chips
    return {"answers": answers, "liveboard": lb if viz else None, "visual_rows": rows + chip_rows,
            "report_name": report_name, "filter_chips": len(chips)}
