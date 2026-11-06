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
import html as _html
import re

from ts_cli.sisense.answers import chart_type_for, date_bucket_suffix
from ts_cli.sisense.target_chips import build_chips
from ts_cli.sisense.target_filters import is_all, top_n, widget_filter
from ts_cli.sisense.target_model import TargetModel, split_dim
from ts_cli.tableau.liveboard import agg_label

# Sisense agg -> ThoughtSpot search keyword. Sisense `count` is a DISTINCT count.
AGG_KEYWORD = {"count": "unique count", "countduplicates": "count", "sum": "sum",
               "avg": "average", "average": "average", "min": "min", "max": "max"}
_MIN_HEIGHT = {"KPI": 2, "GRID_TABLE": 6, "PIVOT_TABLE": 6}
_PX_PER_ROW = 55
_NOTE_BG = "rgb(0, 132, 169)"
_GRAIN_SUFFIX = re.compile(r"\s*\((daily|weekly|monthly|quarterly|yearly)\)\s*$", re.I)
_TOKEN = re.compile(r"\[([^\]]+)\]")

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
        names = {t.get("id"): t.get("jaql_name") for t in inv.get("tables") or [] if t.get("jaql_name")}
        self.relations = [dict(r, endpoints=[dict(e, table=names.get(e.get("table"), e.get("table")))
                                             for e in r.get("endpoints") or []])
                          for r in inv.get("relations") or []]
        self.field_map = (overrides or {}).get("field_map") or {}
        self.filter_map = (overrides or {}).get("filter_map") or {}
        self.calculated = _calculated_columns(inv)
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

    def column(self, dim: str, anchors: list) -> tuple:
        """Sisense dim -> (model column | None, instance | None, note)."""
        if dim in self.field_map:
            return self.mapped(dim)
        table, col = split_dim(dim)
        inst, note = self.t.resolve_instance(table, anchors, self.relations)
        if not inst:
            return None, None, note
        insts, has_fact = self._ctx
        known = self.t.path_known(table, inst, anchors, has_fact, self.relations)
        conflict = self.t.role_conflict(table, inst, insts, known, relations=self.relations)
        if conflict:
            return None, None, f"{conflict} (map it via field_map / filter_map)"
        name = self.t.column(inst, col) or self._calculated(table, col, inst)
        return name, inst, "" if name else f"{table}.{col} is not exposed on the target model"

    def _calculated(self, table: str, col: str, inst: str):
        """A Sisense CALCULATED column -> the Model FORMULA of the same (normalised) name on the
        same instance; never any other column, which could be a different measure by that name."""
        if (table, col) not in self.calculated:
            return None
        name = self.t.column_by_display(col)
        if name in self.t.formula_columns and inst in self.t.instances_of.get(name, {inst}):
            return name
        return None

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
        name, inst, note = self.column(dim, anchors)
        if f.get("kind") != "measure":
            return _dimension(name, f.get("level")) if name else {"note": note}
        kw = AGG_KEYWORD.get(agg)
        if not kw:
            return {"note": f"Sisense aggregation '{agg}' on {dim} has no mapped ThoughtSpot keyword"}
        if name and name in self.t.formula_measures:
            return self._formula_measure(name, dim, agg, kw)
        if name:   # explicit keyword: a bare SUM column would come back as "Total <name>" anyway
            token = f"{kw} [{name}]"
            return {"name": name, "token": token, "out": f"{agg_label(token)} {name}", "measure": True}
        if inst and kw in ("unique count", "count"):
            table, col = split_dim(dim)
            cm = self.t.count_measure(kw, inst, col)
            if cm:
                return {"name": cm, "token": f"[{cm}]", "out": cm, "measure": True}
            return {"note": f"{kw} of {table}.{col}: add a Model measure '{kw} ( [{inst}::{col}] )' or map it via field_map"}
        return {"note": note}

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
        if sf.get("kind") == "top_n":        # the ranking is decided per widget (target_filters.top_n),
            return None, name, ""            # but the widget filters that column itself
        if is_all(sf):
            return None, name, ""            # "all" = no condition; the widget still owns the column
        if not name:
            return None, None, f"filter on {dim}: {note} (map it via filter_map)"
        frag, problem = widget_filter(sf, name)
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


def _strip_html(s: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", s or "", flags=re.I)
    return _html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def note_tile(text: str) -> dict:
    """A section-header note tile (format copied from an exported Liveboard)."""
    safe = _html.escape(text)
    return {"html_parsed_string": (
        '<h2 class="theme-module__editor-h2" style="text-align: center;"><b><strong class="theme-module__editor-text-bold" '
        f'style="color: rgb(255, 255, 255); white-space: pre-wrap;">{safe}</strong></b></h2>'
        f'<div class="pinboard-note-tile-module__noteTileBg editor-module__bgNode" style="background-color: {_NOTE_BG};"></div>')}


def _field_key(f: dict) -> str:
    """Everything about a plotted field except its title and date level (and week start, which
    only means something at a weekly level)."""
    return repr(sorted((k, repr(v)) for k, v in f.items() if k not in ("level", "title", "firstday")))


def _shape(w: dict) -> tuple:
    """A widget's plotted fields (date level left out), its filters and every setting that
    changes its numbers, exactly."""
    filters = sorted(repr(sorted((k, repr(v)) for k, v in sf.items())) for sf in w.get("filters", []))
    settings = repr([(k, w.get(k)) for k in ("subtype", "ignore", "filters_mode", "unsupported", "disabled_filters")])
    return (w.get("wtype"), tuple(sorted(_field_key(f) for f in w.get("fields", []))), tuple(filters), settings)


def _levels(w: dict) -> tuple:
    return tuple(sorted((_field_key(f), (f.get("level") or "").lower(), (f.get("firstday") or ""))
                        for f in w.get("fields", [])))


def _grain_variant(hidden: dict, shown: dict) -> bool:
    """One chart at another date grain: same type, fields and filters, a different date level."""
    return _shape(hidden) == _shape(shown) and _levels(hidden) != _levels(shown)


def _hidden_tabs(widgets: list) -> tuple:
    """(grain variants: oid -> (tab-set title, shown oid), other hidden tabs: oid -> tab-set
    title) for every widget a WidgetsTabber hides. Only a hidden widget with the same type, fields and filters as a shown
    one and a different date level is a grain variant; any other hidden tab is a chart of its own."""
    by_oid = {w.get("oid"): w for w in widgets}
    grain, other = {}, {}
    for w in widgets:
        if w.get("tabber"):
            _classify_tabs(w, by_oid, grain, other)
    return grain, other


def _classify_tabs(w: dict, by_oid: dict, grain: dict, other: dict) -> None:
    tb, title = w["tabber"], w.get("title") or ""
    keep = set((tb["tabs"][tb["active"]]["show"] if tb["tabs"] else []))
    shown = [by_oid[o] for o in keep if o in by_oid]
    hidden = [o for tab in tb["tabs"] for o in tab["show"] if o not in keep and o in by_oid]
    for oid in hidden:
        hit = next((s.get("oid") for s in shown if _grain_variant(by_oid[oid], s)), None)
        if hit:
            grain[oid] = (title, hit)
        else:
            other[oid] = title


def tabber_hidden(widgets: list) -> dict:
    """oid -> tab-set title for every hidden widget that is a date-grain variant of a shown one."""
    return {oid: title for oid, (title, _) in _hidden_tabs(widgets)[0].items()}


_ROLE_OF_PANEL = {"categories": "Category", "x-axis": "Category", "rows": "Rows", "columns": "Columns",
                  "break by": "Series", "break by / color": "Series", "color": "Series"}
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
    if (f.get("level") or "").lower() == "weeks" and f.get("firstday"):
        return (f"field {what} buckets weeks starting on {f['firstday']} in Sisense; ThoughtSpot's weekly "
                "bucket follows the cluster's week start, so confirm they match")
    return None


def _collect_filters(widget: dict, binder: _Binder, anchors: list) -> tuple:
    """Widget filters -> (search fragments, columns the widget filters itself, notes). A column
    the widget filters at all -- even with `all` or a filter that is not carried -- is its own:
    in Sisense a widget filter takes priority over a dashboard filter on the same dimension."""
    frags, own, notes, seen = [], set(), [], {}
    for sf in widget.get("filters", []):
        frag, col, fnote = binder.filter_fragment(sf, anchors)
        if frag:
            frags.append(frag)
        own.update([col] if col else _TOKEN.findall(frag or ""))
        if fnote:
            notes.append(fnote)
        if col and sf.get("kind") != "top_n" and not is_all(sf):
            seen[col] = seen.get(col, 0) + 1
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
    unsupported = widget.get("unsupported") or []
    notes = (([note] if note else []) + acc["notes"] + fnotes + rank_notes
             + ([f"widget carries settings this converter does not read: {', '.join(unsupported)}"] if unsupported else []))
    info = ([f"disabled widget filter(s) in Sisense, not applied: {', '.join(widget['disabled_filters'])}"]
            if widget.get("disabled_filters") else [])
    row = {"visual": title, "ts_chart": ct, "status": status}
    if not acc["cols"]:
        row.update(status="NEEDS REVIEW", note="; ".join(notes + info) or "no fields mapped")
        return None, row, own, []
    if notes:
        row["status"] = "NEEDS REVIEW"
    if notes or info:
        row["note"] = "; ".join(notes + info)
    extra = ctx.get("extra_filters", [])
    own |= {c for f in extra for c in _TOKEN.findall(f)}
    a = build_answer(title, f"{ctx['key']}", binder.t.name, ctx.get("model_fqn"), acc["cols"], ct,
                     acc["measures"], acc["roles"], _token_map(acc["tokens"]), n)["answer"]
    a = _finish_answer(a, binder, ct, frags + extra + ([rank_frag] if rank_frag else []), acc["labels"],
                       ctx.get("description"), acc["measure_outs"])
    return a, row, own, binder.t.facts_for(acc["cols"] + sorted(own))


def _token_map(tokens: dict) -> dict:
    """Only non-bare tokens go to the emitter (it renders `[col]` itself)."""
    return {c: t for c, t in tokens.items() if t != f"[{c}]"}


def _tile_height(ct, px):
    return max(_MIN_HEIGHT.get(ct, 5), round((px or 0) / _PX_PER_ROW))


def _layout_rows(inv: dict, placed: dict) -> list:
    """Dashboard layout -> [(col_index, col_pct, [(oid, width_pct, height_px)])] keeping placed oids."""
    out = []
    for row in (inv.get("dashboard") or {}).get("layout") or []:
        items = [(it["oid"], it["width_pct"], it["height_px"]) for it in row["items"] if it["oid"] in placed]
        if items:
            out.append((row["col"], row["items"][0]["col_pct"], items))
    return out


def _place(inv: dict, placed: dict) -> list:
    """placed: oid -> {'kind','ct'}; -> [(oid, x, y, w, h)] on a 12-column grid. Widgets the
    layout does not mention are appended full-width at the end, in widget order."""
    tiles, y_of, x_of = [], {}, {}
    col_x = 0
    for ci, col_pct, items in _layout_rows(inv, placed):
        if ci not in x_of:
            x_of[ci] = col_x
            col_x += round(12 * col_pct / 100)
            y_of[ci] = 0
        span = round(12 * col_pct / 100) or 12
        total = sum(w for _, w, _ in items) or 100
        widths = [max(1, round(span * w / total)) for _, w, _ in items]
        widths[-1] = span - sum(widths[:-1])     # rows always fill their column
        x = x_of[ci]
        heights = [1 if placed[oid]["kind"] == "note" else _tile_height(placed[oid]["ct"], px)
                   for oid, _, px in items]
        h = max(heights)
        for (oid, _, _), w in zip(items, widths):
            tiles.append((oid, x, y_of[ci], w, h if placed[oid]["kind"] != "note" else 1))
            x += w
        y_of[ci] += h
    seen = {t[0] for t in tiles}
    y = max(y_of.values(), default=0)
    for oid, p in placed.items():
        if oid not in seen:
            h = 1 if p["kind"] == "note" else _tile_height(p["ct"], 0) + 2
            tiles.append((oid, 0, y, 12, h))
            y += h
    return tiles


def _shared_filters(binder: _Binder, widgets: list) -> tuple:
    """(search fragments EVERY source widget carries, note). Sisense passes a source widget's
    filters to the drill, so one that is not carried, or not shared by every source, means the
    details table differs from Sisense for clicks from that source -> the note says which."""
    common, per_source, dropped = None, [], []
    for w in widgets:
        frs, missing = _source_filters(binder, w)
        per_source.append((w.get("title") or "?", frs))
        dropped += [f"{w.get('title') or '?'}: {d}" for d in missing]
        common = frs if common is None else common & frs
    common = common or set()
    dropped += [f"{t}: {f}" for t, frs in per_source for f in sorted(frs - common)]
    note = ("filters Sisense passes to this drill from its source widgets are not carried: " + "; ".join(dropped)
            if dropped else "")
    return sorted(common), note


def _source_filters(binder: _Binder, w: dict) -> tuple:
    """A drill source widget's filters -> (carried fragments, dims of those not carried)."""
    anchors = binder.anchors(w)
    frs, missing = set(), []
    for sf in w.get("filters", []):
        if sf.get("kind") == "top_n" or is_all(sf):
            continue
        frag, _, fnote = binder.filter_fragment(sf, anchors)
        if frag:
            frs.add(frag)
        elif fnote:
            missing.append(sf.get("dim") or "?")
    return frs, missing


def _drill_description(src_widgets: list, target_title: str) -> str:
    sources = ", ".join(sorted({w.get("title") or "" for w in src_widgets}))
    return (f"Right-click a value in {sources} and choose Filter to narrow this list "
            f"(replaces the Sisense drill to {target_title}).")


def _drill_tables(drills, binder, sources, model_fqn):
    """Distinct drill targets -> [(key, answer, row, own, facts, widget)]: one details table per
    target, built from the drill dashboard's first widget, carrying the filters EVERY source
    widget shares. The table is a tile like any other, so dashboard chips are checked against it."""
    out = []
    by_title = {(d.get("dashboard") or {}).get("title"): d for d in drills or []}
    for target, src_widgets in sources.items():
        d = by_title.get(target)
        if not d:
            out.append((f"drill:{target}", None, {"visual": f"drill -> {target}", "ts_chart": "GRID_TABLE",
                        "status": "NEEDS REVIEW", "note": f"drill dashboard '{target}' not supplied (--drill)"},
                        set(), [], {}))
            continue
        with_fields = [w for w in d.get("widgets", []) if w.get("fields")]
        if not with_fields:
            out.append((f"drill:{target}", None, {"visual": f"drill -> {target}", "ts_chart": "GRID_TABLE",
                        "status": "NEEDS REVIEW", "note": f"drill dashboard '{target}' has no widget with fields"},
                        set(), [], {}))
            continue
        out.append(_drill_table(d, target, with_fields, binder, src_widgets, model_fqn))
    return out


def _drill_table(d: dict, target: str, with_fields: list, binder, src_widgets: list, model_fqn) -> tuple:
    """One drill dashboard -> (key, answer, row, own, facts, widget) from its first widget with
    fields; the widget's own filters and the drill dashboard's own filters both apply to it."""
    dw = with_fields[0]
    # the drill dashboard's OWN filters: how a jump-to-dashboard combines them with what the
    # source passes is not verified, so any with a condition is reported, never applied
    own_dash = [sf.get("dim") or "?" for sf in (d.get("dashboard") or {}).get("filters") or [] if not is_all(sf)]
    detail = dict(dw, wtype="tablewidget")
    shared, shared_note = _shared_filters(binder, src_widgets)
    ctx = {"key": f"drill-{target}", "model_fqn": model_fqn, "extra_filters": shared,
           "description": _drill_description(src_widgets, dw.get("title") or target)}
    a, row, own, facts = _answer_for(detail, binder, ctx, title_override=dw.get("title") or target)
    rest = [w.get("title") or "?" for w in with_fields[1:]]
    problems = ([f"drill dashboard '{target}' has more widgets than its details table carries: {', '.join(rest)}"]
                if rest else []) + ([shared_note] if shared_note else []) + (
        [f"drill dashboard '{target}' has its own dashboard filters, not carried: {', '.join(own_dash)}"]
        if own_dash else [])
    if problems:
        row.update(status="NEEDS REVIEW", note="; ".join(filter(None, [row.get("note")] + problems)))
    return f"drill:{target}", a, row, own, facts, detail


def _widget_tiles(inv, widgets, binder, model_fqn) -> tuple:
    """Widgets -> (report rows, placed, content, drill sources). Hidden tabs are Merged, rich
    text and tab-set titles become notes, everything else an Answer."""
    (hidden, other_tabs), kept_tabs = _hidden_tabs(widgets), _kept_tabs(widgets)
    rows, placed, content, drill_sources, merged = [], {}, {}, {}, []
    for i, w in enumerate(widgets):
        oid = w.get("oid") or f"w{i}"
        if oid in hidden:
            row = {"visual": w.get("title"), "ts_chart": "(tab)", "status": "Merged",
                   "note": f"other grain of tab set '{hidden[oid][0]}'; change it in the chart's date bucket"}
            rows.append(row)
            merged.append((row, hidden[oid][1]))
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
    for row, shown in merged:                      # a grain of a tab that produced no tile
        if shown not in placed:
            row.update(status="NEEDS REVIEW", note="the tab it is a grain of could not be carried, so there is no tile to merge into")
    return rows, placed, content, drill_sources


def _kept_tabs(widgets: list) -> set:
    """Widget oids shown by each tab set's ACTIVE tab."""
    out = set()
    for w in widgets:
        tb = w.get("tabber") or {}
        if tb.get("tabs"):
            out.update(tb["tabs"][tb["active"]]["show"])
    return out


def _note_text(w: dict, inv: dict) -> str:
    text = w.get("title") if w.get("wtype") == "WidgetsTabber" else _strip_html((w.get("richtext") or {}).get("html"))
    return text or (inv.get("dashboard") or {}).get("title") or ""


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


def build_target_liveboard(inv: dict, target_tml: dict, model_fqn=None, overrides=None,
                           drills=None, tables=None) -> dict:
    """Parsed Sisense inventory + target Model TML (+ its Table TMLs, optional) ->
    {answers, liveboard, visual_rows, report_name}."""
    overrides = overrides or {}
    target = TargetModel(target_tml, tables)
    binder = _Binder(inv, target, overrides)
    report_name = overrides.get("report_name") or (inv.get("dashboard") or {}).get("title") or target.name
    rows, placed, content, drill_sources = _widget_tiles(inv, inv.get("widgets", []) or [], binder,
                                                         model_fqn or target_tml.get("guid"))
    for key, a, row, own, facts, dw in _drill_tables(drills, binder, drill_sources,
                                                     model_fqn or target_tml.get("guid")):
        rows.append(row)
        if a:
            placed[key + ":note"], content[key + ":note"] = {"kind": "note", "ct": None}, ("note", row["visual"])
            placed[key], content[key] = {"kind": "answer", "ct": "GRID_TABLE"}, ("answer", a, own, facts, row, dw)
    viz, layout, tiles, answers = _assemble(inv, placed, content)
    chips, chip_rows = build_chips(inv, binder, tiles)
    lb = {"liveboard": {"name": report_name, "visualizations": viz, "layout": {"tiles": layout}}}
    if chips:
        lb["liveboard"]["filters"] = chips
    return {"answers": answers, "liveboard": lb if viz else None, "visual_rows": rows + chip_rows,
            "report_name": report_name, "filter_chips": len(chips)}
