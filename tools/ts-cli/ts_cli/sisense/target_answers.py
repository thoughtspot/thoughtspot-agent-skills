"""Sisense dashboard -> Liveboard bound to an EXISTING Model (``build-liveboard --target-model``).

The default path (answers.py) binds widgets to the model ``build-model`` generates. This path
binds them to a Model someone already designed, and carries the parts of a dashboard that
decide whether the rebuilt board shows the same numbers:

- ``agg``: Sisense ``count`` is COUNT DISTINCT -> ``unique count``; a count over a key the
  Model hides binds to a Model formula ``unique count ( [inst::col] )`` when one exists.
- widget-level filters become search filters (members ``=`` repeated, which ThoughtSpot ORs;
  excludes ``!=`` repeated, which it ANDs; ranges ``>= > <= <``). Never ``in (...)`` /
  ``not in (...)``: ThoughtSpot search ignores both silently (live-verified, 26.9).
- a WidgetsTabber keeps only its active tab's widget; the other grains are one click away
  in the chart's own date-bucket control.
- Sisense value titles become ``custom_name``; rich-text widgets and tab-set titles become
  note tiles; the columnar layout becomes the tile grid.
- jump-to-dashboard drills become a details table built from the drill dashboard's widget,
  narrowed on the liveboard with right-click > Filter.
- dashboard filters become chips; a chip on a column a tile filters itself is excluded from
  that tile (a chip REPLACES the tile's own filter, Sisense ANDs them), and a chip that cannot
  reach a tile's facts is flagged.

Anything that cannot be bound faithfully is reported NEEDS REVIEW with the reason, never
dropped or substituted. ``overrides`` may map a Sisense dim to a Model column
(``field_map``) or a Sisense filter dim to a search fragment (``filter_map``) for the cases
only the Model's author can decide.

Pure functions, no I/O.
"""
from __future__ import annotations

import html as _html
import re

from ts_cli.sisense.answers import chart_type_for, date_bucket_suffix
from ts_cli.sisense.target_model import TargetModel, split_dim

# Sisense agg -> ThoughtSpot search keyword. Sisense `count` is a DISTINCT count.
AGG_KEYWORD = {"count": "unique count", "countduplicates": "count", "sum": "sum",
               "avg": "average", "average": "average", "min": "min", "max": "max"}
# Output column name ThoughtSpot gives `<keyword> [X]` (live-verified 26.9).
AGG_OUTPUT_PREFIX = {"unique count": "Unique Number of", "count": "Number of", "sum": "Total",
                     "average": "Average", "min": "Minimum", "max": "Maximum"}
_RANGE_OPS = (("from", ">="), ("fromNotEqual", ">"), ("to", "<="), ("toNotEqual", "<"), ("equals", "="))
_MIN_HEIGHT = {"KPI": 2, "GRID_TABLE": 6, "PIVOT_TABLE": 6}
_PX_PER_ROW = 55
_NOTE_BG = "rgb(0, 132, 169)"
_GRAIN_SUFFIX = re.compile(r"\s*\((daily|weekly|monthly|quarterly|yearly)\)\s*$", re.I)
_TOKEN = re.compile(r"\[([^\]]+)\]")


def _literal(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "\\'") + "'"


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

    # -- anchors: the fact instances a widget queries ---------------------------------
    def anchors(self, widget: dict) -> list:
        """The fact instances a widget queries: facts it names, else facts reaching all (or
        any) of the instances it names."""
        insts = self._widget_instances(widget)
        roots = self.t.roots()
        direct = [r for r in roots if r in insts]
        if direct or not insts:
            return direct
        return [r for r in roots if insts <= self.t.reachable(r)] or \
               [r for r in roots if insts & self.t.reachable(r)]

    def _widget_instances(self, widget: dict) -> set:
        dims = [f.get("dim") for f in widget.get("fields", [])] + [sf.get("dim") for sf in widget.get("filters", [])]
        insts = set()
        for dim in filter(None, dims):
            table = split_dim(dim)[0]
            insts.update(self.t.named_instances(table) or self.t.instances_of_base(table))
        return insts

    def column(self, dim: str, anchors: list) -> tuple:
        """Sisense dim -> (model column | None, instance | None, note)."""
        if dim in self.field_map:
            return self.field_map[dim], None, ""
        table, col = split_dim(dim)
        inst, note = self.t.resolve_instance(table, anchors, self.relations)
        if not inst:
            return None, None, note
        name = self.t.column(inst, col)
        if not name:   # a Sisense calculated column is a Model formula, bound by its name
            name = self.t.column_by_display(col)
            if name and inst not in self.t.instances_of.get(name, {inst}):
                name = None
        return name, inst, "" if name else f"{table}.{col} is not exposed on the target model"

    # -- one plotted field -> search token + output column -----------------------------
    def field(self, f: dict, anchors: list) -> dict:
        dim, agg = f.get("dim"), (f.get("agg") or "").lower()
        if f.get("formula"):
            return {"note": f"formula field '{f.get('title') or '?'}' needs a Model measure (map it via field_map)"}
        name, inst, note = self.column(dim, anchors)
        if f.get("kind") != "measure":
            if not name:
                return {"note": note}
            suf = date_bucket_suffix(f.get("level"))
            token = f"[{name}].{suf.lower()}" if suf else f"[{name}]"
            out = f"{_bucket_out(suf)}({name})" if suf else name
            return {"name": name, "token": token, "out": out, "measure": False, "bucketed": bool(suf)}
        kw = AGG_KEYWORD.get(agg)
        if not kw:
            return {"note": f"Sisense aggregation '{agg}' on {dim} has no mapped ThoughtSpot keyword"}
        if name and name in self.t.formula_measures:
            return {"name": name, "token": f"[{name}]", "out": name, "measure": True}
        if name:   # explicit keyword: a bare SUM column would come back as "Total <name>" anyway
            return {"name": name, "token": f"{kw} [{name}]", "out": f"{AGG_OUTPUT_PREFIX[kw]} {name}", "measure": True}
        if inst and kw in ("unique count", "count"):
            table, col = split_dim(dim)
            cm = self.t.count_measure(kw, inst, col)
            if cm:
                return {"name": cm, "token": f"[{cm}]", "out": cm, "measure": True}
            return {"note": f"{kw} of {table}.{col}: add a Model measure '{kw} ( [{inst}::{col}] )' or map it via field_map"}
        return {"note": note}

    # -- one widget/drill filter -> search fragment -------------------------------------
    def filter_fragment(self, sf: dict, anchors: list) -> tuple:
        """-> (fragment | None, model column | None, note)."""
        dim = sf.get("dim") or ""
        if dim in self.filter_map:
            return self.filter_map[dim], None, ""
        kind = sf.get("kind")
        if kind == "top_n":
            return None, None, ""            # carried as `top N` by the emitter
        name, _, note = self.column(dim, anchors)
        if not name:
            return None, None, f"filter on {dim}: {note} (map it via filter_map)"
        frag = _search_filter(kind, name, sf.get("raw") or {}, sf.get("values") or [])
        if frag:
            return frag, name, ""
        if kind == "member" and (sf.get("raw") or {}).get("all"):
            return None, None, ""            # "all" = no filter
        return None, None, f"filter on {dim} ({kind}) has no deterministic search form"


def _search_filter(kind: str, name: str, raw: dict, vals: list):
    """One Sisense filter on a resolved column -> search fragment, or None.
    Repeated `=` is ORed and repeated `!=` ANDed by ThoughtSpot (live-verified)."""
    if kind == "member" and vals:
        return " ".join(f"[{name}] = {_literal(v)}" for v in vals)
    if kind == "exclude" and vals:
        return " ".join(f"[{name}] != {_literal(v)}" for v in vals)
    if kind == "range":
        parts = [f"[{name}] {op} {_literal(raw[k])}" for k, op in _RANGE_OPS if raw.get(k) is not None]
        return " ".join(parts) or None
    return None


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


def tabber_hidden(widgets: list) -> dict:
    """oid -> tab-set title for every widget a WidgetsTabber hides (all tabs but the active)."""
    hidden = {}
    for w in widgets:
        tb = w.get("tabber")
        if not tb:
            continue
        keep = set((tb["tabs"][tb["active"]]["show"] if tb["tabs"] else []))
        for tab in tb["tabs"]:
            for oid in tab["show"]:
                if oid not in keep:
                    hidden[oid] = w.get("title") or ""
    return hidden


_ROLE_OF_PANEL = {"categories": "Category", "x-axis": "Category", "rows": "Rows", "columns": "Columns",
                  "break by": "Series", "break by / color": "Series", "color": "Series"}
_UNPLOTTED_PANELS = ("filters", "min", "max", "secondary")


def _label_for(f: dict, b: dict):
    """Sisense title -> custom_name, unless it is just the column (or a bucketed date)."""
    title = (f.get("title") or "").strip()
    if not title or b.get("bucketed") or title.lower() == b["out"].lower():
        return None
    if not b["measure"] and title.replace("_", "").lower() == split_dim(f.get("dim"))[1].replace("_", "").lower():
        return None
    return title


def _collect_fields(widget: dict, binder: _Binder, anchors: list) -> dict:
    """Plotted fields -> {cols, roles, tokens, measures, labels, notes}."""
    acc = {"cols": [], "roles": [], "tokens": {}, "measures": set(), "labels": {}, "notes": []}
    for f in widget.get("fields", []):
        panel = (f.get("panel") or "").lower()
        if panel in _UNPLOTTED_PANELS:
            continue
        b = binder.field(f, anchors)
        if "note" in b:
            acc["notes"].append(b["note"])
            continue
        if b["name"] in acc["cols"]:
            continue
        acc["cols"].append(b["name"])
        acc["roles"].append("Values" if b["measure"] else (_ROLE_OF_PANEL.get(panel) or "Category"))
        acc["tokens"][b["name"]] = b["token"]
        if b["measure"]:
            acc["measures"].add(b["name"])
        label = _label_for(f, b)
        if label:
            acc["labels"][b["out"]] = label
    return acc


def _collect_filters(widget: dict, binder: _Binder, anchors: list) -> tuple:
    """Widget filters -> (search fragments, columns the widget filters itself, notes)."""
    frags, own, notes = [], set(), []
    for sf in widget.get("filters", []):
        frag, col, fnote = binder.filter_fragment(sf, anchors)
        if frag:
            frags.append(frag)
            own.update([col] if col else _TOKEN.findall(frag))
        if fnote:
            notes.append(fnote)
    return frags, own, notes


def _top_n(widget: dict):
    return next((int(sf["values"][0]) for sf in widget.get("filters", [])
                 if sf.get("kind") == "top_n" and str((sf.get("values") or [""])[0]).isdigit()), None)


def _finish_answer(a: dict, binder: _Binder, ct: str, frags: list, labels: dict, description=None) -> dict:
    """Sisense-local additions to an emitted answer: exact binding, filters, titles, mode."""
    if binder.t.obj_id:
        a["tables"] = [{"id": binder.t.name, "name": binder.t.name, "obj_id": binder.t.obj_id}]
    if frags:
        a["search_query"] = a["search_query"] + " " + " ".join(frags)
    for ac in a["answer_columns"]:
        if ac["name"] in labels:
            ac["custom_name"] = labels[ac["name"]]
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
    notes = ([note] if note else []) + acc["notes"] + fnotes
    row = {"visual": title, "ts_chart": ct, "status": status}
    if not acc["cols"]:
        row.update(status="NEEDS REVIEW", note="; ".join(notes) or "no fields mapped")
        return None, row, own, []
    if notes:
        row.update(status="NEEDS REVIEW", note="; ".join(notes))
    a = build_answer(title, f"{ctx['key']}", binder.t.name, ctx.get("model_fqn"), acc["cols"], ct,
                     acc["measures"], acc["roles"], _token_map(acc["tokens"]), _top_n(widget))["answer"]
    a = _finish_answer(a, binder, ct, frags + ctx.get("extra_filters", []), acc["labels"], ctx.get("description"))
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


def _shared_filters(binder: _Binder, widgets: list) -> list:
    """Search fragments EVERY widget carries (the drill's context common to all its sources)."""
    common = None
    for w in widgets:
        frs = {binder.filter_fragment(sf, binder.anchors(w))[0] for sf in w.get("filters", [])} - {None}
        common = frs if common is None else common & frs
    return sorted(common or [])


def _drill_description(src_widgets: list, target_title: str) -> str:
    sources = ", ".join(sorted({w.get("title") or "" for w in src_widgets}))
    return (f"Right-click a value in {sources} and choose Filter to narrow this list "
            f"(replaces the Sisense drill to {target_title}).")


def _drill_tables(inv, drills, binder, sources):
    """Distinct drill targets -> [(key, answer, row)]: one details table per target, built from
    the drill dashboard's first widget, carrying the filters EVERY source widget shares."""
    out = []
    by_title = {(d.get("dashboard") or {}).get("title"): d for d in drills or []}
    for target, src_widgets in sources.items():
        d = by_title.get(target)
        if not d:
            out.append((f"drill:{target}", None, {"visual": f"drill -> {target}", "ts_chart": "GRID_TABLE",
                        "status": "NEEDS REVIEW", "note": f"drill dashboard '{target}' not supplied (--drill)"}))
            continue
        dw = next((w for w in d.get("widgets", []) if w.get("fields")), None)
        if not dw:
            continue
        detail = dict(dw, wtype="tablewidget", filters=[])
        ctx = {"key": f"drill-{target}", "extra_filters": _shared_filters(binder, src_widgets),
               "description": _drill_description(src_widgets, dw.get("title") or target)}
        a, row, _, _ = _answer_for(detail, binder, ctx, title_override=dw.get("title") or target)
        out.append((f"drill:{target}", a, row))
    return out


def _review(visual: str, note: str) -> dict:
    return {"visual": visual, "ts_chart": "FILTER", "status": "NEEDS REVIEW", "note": note}


def _chip_column(sf: dict, binder: _Binder, anchor_sets: list) -> tuple:
    """Dashboard filter -> (model column | None, instance | None, note)."""
    dim = sf.get("dim") or ""
    if dim in binder.field_map:
        return binder.field_map[dim], None, ""
    table, col = split_dim(dim)
    inst, note = binder.t.resolve_chip_instance(table, anchor_sets, binder.relations)
    name = binder.t.column(inst, col) if inst else None
    if inst and not name:
        note = f"{table}.{col} is not exposed on the target model"
    return name, inst, note


def _chip(sf: dict, name: str, inst, binder: _Binder, viz_meta: list) -> tuple:
    """One resolved dashboard filter -> (chip, review rows)."""
    chip = {"column": [name], "is_mandatory": False, "is_single_value": False, "display_name": ""}
    vals = [str(v) for v in sf.get("values") or []]
    if vals and sf.get("kind") in ("member", "exclude"):
        chip.update(oper="in" if sf["kind"] == "member" else "not in", values=vals)
    excluded = [vid for vid, own, _, _ in viz_meta if name in own]
    if excluded:
        chip["excluded_visualizations"] = excluded
    unreached = _unreached(inst, binder, viz_meta, excluded) if inst else []
    rows = [_review(f"filter chip {name}", "does not reach the facts of: " + "; ".join(unreached))] if unreached else []
    return chip, rows


def _unreached(inst: str, binder: _Binder, viz_meta: list, excluded: list) -> list:
    """Titles of tiles whose facts cannot reach the chip's instance."""
    out = []
    for vid, _, facts, title in viz_meta:
        if facts and vid not in excluded and not any(inst in binder.t.reachable(a) for a in facts):
            out.append(title)
    return out


def _chips(inv, binder, viz_meta):
    """Dashboard filters -> (chips, report rows). viz_meta: [(viz_id, own_cols, facts, title)]."""
    chips, rows = [], []
    anchor_sets = [m[2] for m in viz_meta if m[2]]
    for sf in (inv.get("dashboard") or {}).get("filters", []) or []:
        if sf.get("kind") == "top_n":
            continue
        name, inst, note = _chip_column(sf, binder, anchor_sets)
        if not name:
            rows.append(_review(f"filter chip {sf.get('dim') or ''}", note))
            continue
        chip, chip_rows = _chip(sf, name, inst, binder, viz_meta)
        rows += chip_rows + ([_review(f"filter chip {name}", note)] if note else [])
        chips.append(chip)
    return chips, rows


def _widget_tiles(inv, widgets, binder, model_fqn) -> tuple:
    """Widgets -> (report rows, placed, content, drill sources). Hidden tabs are Merged, rich
    text and tab-set titles become notes, everything else an Answer."""
    hidden, kept_tabs = tabber_hidden(widgets), _kept_tabs(widgets)
    rows, placed, content, drill_sources = [], {}, {}, {}
    for i, w in enumerate(widgets):
        oid = w.get("oid") or f"w{i}"
        if oid in hidden:
            rows.append({"visual": w.get("title"), "ts_chart": "(tab)", "status": "Merged",
                         "note": f"other grain of tab set '{hidden[oid]}'; change it in the chart's date bucket"})
        elif w.get("wtype") in ("WidgetsTabber", "richtexteditor"):
            placed[oid], content[oid] = {"kind": "note", "ct": None}, ("note", _note_text(w, inv))
        else:
            title = _GRAIN_SUFFIX.sub("", w.get("title") or "") if oid in kept_tabs else None
            a, row, own, facts = _answer_for(w, binder, {"key": oid, "model_fqn": model_fqn}, title or None)
            rows.append(row)
            if a:
                placed[oid], content[oid] = {"kind": "answer", "ct": row["ts_chart"]}, ("answer", a, own, facts)
                for tgt in w.get("drill_targets") or []:
                    drill_sources.setdefault(tgt, []).append(w)
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
    """Placed tiles -> (visualizations, layout tiles, viz_meta, answers)."""
    viz, layout, viz_meta, answers = [], [], [], []
    for n, (oid, x, y, w, h) in enumerate(sorted(_place(inv, placed), key=lambda t: (t[2], t[1])), 1):
        vid, item = f"Viz_{n}", content[oid]
        if item[0] == "note":
            viz.append({"id": vid, "note_tile": note_tile(item[1])})
        else:
            viz.append({"id": vid, "answer": item[1]})
            answers.append({"answer": item[1]})
            viz_meta.append((vid, item[2], item[3], item[1]["name"]))
        layout.append({"visualization_id": vid, "x": x, "y": y, "height": h, "width": w})
    return viz, layout, viz_meta, answers


def build_target_liveboard(inv: dict, target_tml: dict, model_fqn=None, overrides=None,
                           drills=None) -> dict:
    """Parsed Sisense inventory + target Model TML -> {answers, liveboard, visual_rows, report_name}."""
    overrides = overrides or {}
    target = TargetModel(target_tml)
    binder = _Binder(inv, target, overrides)
    report_name = overrides.get("report_name") or (inv.get("dashboard") or {}).get("title") or target.name
    rows, placed, content, drill_sources = _widget_tiles(inv, inv.get("widgets", []) or [], binder,
                                                         model_fqn or target_tml.get("guid"))
    for key, a, row in _drill_tables(inv, drills, binder, drill_sources):
        rows.append(row)
        if a:
            placed[key + ":note"], content[key + ":note"] = {"kind": "note", "ct": None}, ("note", row["visual"])
            placed[key], content[key] = {"kind": "answer", "ct": "GRID_TABLE"}, ("answer", a, set(), [])
    viz, layout, viz_meta, answers = _assemble(inv, placed, content)
    chips, chip_rows = _chips(inv, binder, viz_meta)
    lb = {"liveboard": {"name": report_name, "visualizations": viz, "layout": {"tiles": layout}}}
    if chips:
        lb["liveboard"]["filters"] = chips
    return {"answers": answers, "liveboard": lb if viz else None, "visual_rows": rows + chip_rows,
            "report_name": report_name, "filter_chips": len(chips)}
