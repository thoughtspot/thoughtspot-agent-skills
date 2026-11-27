"""Sisense widgets/dashboard -> a build_from_spec spec (+ Sisense-local filter chips).

Ported from the standalone converter (map/content.py). Pure functions, no I/O. Like the
Power BI ``answers.py``, this module only RESOLVES the Sisense side (widget type -> ts_chart,
JAQL panel -> canonical role, date ``level`` -> a monthly/… bucket token, per-attribute
top-N); the actual Answer + tabbed-Liveboard TML is emitted by the shared
``ts_cli.tableau.liveboard.build_from_spec`` (ported from the same converter lineage), so
both conversion skills share one emitter. build_from_spec reads a per-visual ``ts_chart``
(so the Sisense widget-type mapping wins over any mark inference) plus role-tagged fields.

``spec_from_parse`` builds the full spec. ``extract_liveboard_filters`` is the
**Sisense-local injection** piece: the dashboard filter bar has no equivalent in the shared
spec, so its member/exclude/numeric-range presets are turned into ThoughtSpot Liveboard
filter chips here and injected into the emitted liveboard dict AFTER build_from_spec returns
(the command module does the injection). See map/content.py ``liveboard_filters`` /
``_range_generic_filter``.
"""
from __future__ import annotations

# Sisense widget `type` -> ThoughtSpot chart type (build_from_spec enum). Unknown types
# fall back to GRID_TABLE. Uses the current TS enums (GRID_TABLE, not the legacy TABLE;
# STACKED_* for the native stacked variants) — see reference_ts_tml_gotchas.
_CHART_MAP: dict[str, str] = {
    "chart/column": "COLUMN",
    "chart/bar": "BAR",
    "chart/line": "LINE",
    "chart/area": "AREA",
    "chart/pie": "PIE",
    "chart/polar": "COLUMN",       # approx (no polar equivalent)
    "chart/scatter": "SCATTER",
    "chart/bubble": "SCATTER",     # approx (bubble size not carried)
    "chart/boxplot": "GRID_TABLE",  # no clean equivalent -> fall back
    "indicator": "KPI",
    "pivot": "PIVOT_TABLE",
    "pivot2": "PIVOT_TABLE",
    "tablewidget": "GRID_TABLE",
    "tablewidgetagg": "GRID_TABLE",  # table with aggregation: grouped rows, as a ThoughtSpot grid
    "treemap": "TREEMAP",
    "sunburst": "GRID_TABLE",      # approx
    "richtexteditor": None,        # text widget -> no Answer; skip
}
_DEFAULT_CHART = "GRID_TABLE"

# Sisense JAQL panel name -> the canonical role build_from_spec understands
# (Category/Series/Rows/Columns/Values). None => not a plotted column (gauge bounds,
# filters, a KPI secondary badge). "" (unknown panel) => default by field kind later.
_PANEL_ROLE: dict[str, str | None] = {
    "categories": "Category", "x-axis": "Category",
    "rows": "Rows",
    "columns": "Columns",
    "values": "Values", "y-axis": "Values", "value": "Values",
    "break by": "Series", "break by / color": "Series", "color": "Series", "break-by": "Series",
    "size": "Series", "point": "Category",
    "min": None, "max": None, "filters": None, "secondary": None,
}

# Sisense date-dimension `level` -> a ThoughtSpot bucket suffix, attached to the column
# token as `[Col].MONTHLY`. Cyclic parts (day-of-week, etc.) have no clean equivalent.
_DATE_BUCKET_MAP: dict[str, str] = {
    "hours": "HOURLY", "days": "DAILY", "weeks": "WEEKLY",
    "months": "MONTHLY", "quarters": "QUARTERLY", "years": "YEARLY",
}


def _mapped_chart(base: str, wt: str, wtype, st: str, subtype) -> tuple:
    if "100" in st:      # a 100% stack shows each value's SHARE of its total
        return ("STACKED_" + base if base in ("BAR", "COLUMN") else base), "NEEDS REVIEW", \
            f"{subtype} is a 100% stack (shares of each total); it is carried as absolute values"
    if base in ("BAR", "COLUMN") and "stacked" in st:
        return "STACKED_" + base, "Migrated", "stacked subtype"
    if base == "SCATTER" and ("bubble" in st or wt == "chart/bubble"):
        return "SCATTER", "Approximated", "bubble approximated as scatter (size dropped)"
    if wt == "chart/boxplot":    # quartiles / median / whiskers: not the values a table shows
        return base, "NEEDS REVIEW", f"{wtype} shows quartiles and a median; carried as a plain {base}"
    if base in ("TREEMAP",) or wt == "sunburst":
        return base, "Approximated", f"{wtype} approximated as {base}"
    return base, "Migrated", ""


def chart_type_for(wtype, subtype: str = "") -> tuple:
    """Sisense widget type -> (ts_chart, status, note). None ts_chart => skip (text widget).

    A stacked subtype promotes BAR/COLUMN to its native STACKED_* variant; a bubble subtype
    keeps SCATTER (bubble size is not carried). Unknown types default to GRID_TABLE.
    """
    wt = (wtype or "").strip().lower()
    st = (subtype or "").lower()
    if wt in _CHART_MAP:
        base = _CHART_MAP[wt]
        if base is None:
            return None, "Skipped", f"{wtype} is a text/no-chart widget"
        return _mapped_chart(base, wt, wtype, st, subtype)
    if wt in ("", "unknown"):
        return _DEFAULT_CHART, "NEEDS REVIEW", "widget type unknown; defaulted to GRID_TABLE"
    return _DEFAULT_CHART, "NEEDS REVIEW", f"no mapping for widget type '{wtype}' (what it computes is unknown); defaulted to GRID_TABLE"


def _model_col(dim) -> str:
    """Sisense dim '[Table.Column Name]' -> 'Column Name' (the model column display name).

    Strips brackets, the 'Table.' qualifier, and a trailing date-hierarchy tag
    ('Date (Calendar)' -> 'Date') so the ref matches the base model column.
    """
    inner = (dim or "").strip().strip("[]")
    if not inner:
        return ""
    leaf = inner.split(".")[-1].strip()
    # drop a trailing "(...)" date-hierarchy tag
    if leaf.endswith(")") and " (" in leaf:
        leaf = leaf.split(" (")[0].strip()
    return leaf


def _panel_role(panel):
    p = (panel or "").strip().lower()
    return _PANEL_ROLE[p] if p in _PANEL_ROLE else ""


def date_bucket_suffix(level):
    """Sisense date `level` -> a TS bucket suffix ('MONTHLY'); None for cyclic/unmapped levels."""
    return _DATE_BUCKET_MAP.get((level or "").lower())


def _resolve_col(name: str, norm: dict) -> str | None:
    """Match a leaf name against model column display names (case-insensitive), retrying on the
    date-hierarchy base ('Date (Calendar)' already stripped by _model_col; guard anyway)."""
    if not name:
        return None
    hit = norm.get(name.lower())
    if hit:
        return hit
    base = name.split(" (")[0].strip()
    return norm.get(base.lower())


def _resolve_dims(widget: dict, norm: dict) -> tuple:
    """A widget's DIMENSION fields -> (dims, bucket_tokens, missing). Each dim is
    ``{name, role, dim, datatype}``; a date ``level`` becomes a ``[Col].MONTHLY`` token."""
    dims, seen, bucket_tokens, missing = [], set(), {}, []
    for f in widget.get("fields", []):
        role = _panel_role(f.get("panel"))
        if role is None or f.get("kind") == "measure":
            continue
        col = _resolve_col(_model_col(f.get("dim")), norm)
        if not col:
            missing.append(f.get("title") or _model_col(f.get("dim")) or "?")
            continue
        if col in seen:             # same dim used as category + break-by -> keep once
            continue
        seen.add(col)
        dims.append({"name": col, "role": role or "Category", "dim": f.get("dim"),
                     "datatype": f.get("datatype") or ""})
        suf = date_bucket_suffix(f.get("level"))
        if suf:
            bucket_tokens[col] = f"[{col}].{suf}"
    return dims, bucket_tokens, missing


def _measure_fields(widget: dict) -> list:
    """Plotted measure fields (gauge bounds, KPI secondary badges and filters excluded)."""
    return [f for f in widget.get("fields", [])
            if f.get("kind") == "measure" and _panel_role(f.get("panel")) is not None]


def _widget_top_n(widget: dict) -> int | None:
    """A per-attribute TOP rank on the widget -> the integer N (build_from_spec appends
    `top N`); None when absent, unparseable or a bottom rank (``_rank_note`` reports those)."""
    for sf in widget.get("filters", []) or []:
        if sf.get("kind") == "top_n" and sf.get("operator") == "top":
            vals = sf.get("values") or []
            try:
                return int(vals[0])
            except (TypeError, ValueError, IndexError):
                return None
    return None


def _rank_note(widget: dict) -> str:
    """A top/bottom rank the default path does not carry -> the reason, else ''."""
    for sf in widget.get("filters", []) or []:
        if sf.get("kind") == "top_n" and (sf.get("operator") != "top" or not _widget_top_n(widget)):
            return f"{sf.get('operator')} {sf.get('values')} ranking is not carried"
    return ""


# Chart types valid with no measure; anything else with zero measures -> NEEDS REVIEW.
_NO_MEASURE_OK = frozenset({"GRID_TABLE", "PIVOT_TABLE", "KPI"})


def _note_join(note: str, msg: str) -> str:
    return (note + "; " + msg) if note else msg


_STATUS_RANK = {"Migrated": 0, "Approximated": 1, "NEEDS REVIEW": 2}


def _worse(a: str, b: str) -> str:
    return a if _STATUS_RANK.get(a, 0) >= _STATUS_RANK.get(b, 0) else b


def _widget_columns(widget, ct, ctx):
    """Resolve a widget into answer columns -> dict (see _widget_answer)."""
    from ts_cli.sisense.widget_fields import build_scope, flatten_pivot, measure_formulas
    dims, bucket_tokens, missing = _resolve_dims(widget, ctx["norm"])
    scope, search, notes, ok = build_scope(widget, ctx["dash_filters"], ctx["norm"],
                                           ctx["lb_cols"])
    formulas, plain, mstatus, mnotes, mmissing = measure_formulas(
        _measure_fields(widget), scope, ctx["norm"], ctx["measures"])
    notes += mnotes
    if ct == "PIVOT_TABLE":
        ct, dims, formulas, plain, pnote = flatten_pivot(widget, dims, formulas, plain,
                                                         ctx["norm"])
        notes.append(pnote)
    return {"ct": ct, "dims": dims, "formulas": formulas, "plain": plain,
            "bucket_tokens": bucket_tokens, "search": search, "notes": notes,
            "missing": missing + mmissing,
            "status": _worse(mstatus, "Migrated" if ok else "NEEDS REVIEW")}


def _widget_answer(widget, idx, tab, model_name, model_fqn, ctx, build_answer):
    """One Sisense widget -> (answer_obj|None, tile_item|None, report_row).

    Drives the shared emitter's ``build_answer`` with OUR resolved ``ts_chart`` and status,
    rather than letting build_from_spec re-infer the chart from a mark (main's emitter ignores
    a per-visual ts_chart and hardcodes "Migrated"). So the Sisense widget-type mapping and the
    Approximated / NEEDS REVIEW signal both survive into the migration report. Widget measures
    become Answer formulas and widget filters search tokens or measure conditions
    (``widget_fields``); the formulas are attached to the emitted Answer.
    """
    ct, status, note = chart_type_for(widget.get("wtype"), widget.get("subtype"))
    if widget.get("text_card"):                       # a BloX banner: text, no data
        ct, status, note = None, "Skipped", "BloX card with no data fields (a text banner, not a data visual)"
    # An untitled widget (every Sisense indicator) is named after its first measure.
    first = next((f.get("title") for f in _measure_fields(widget) if f.get("title")), None)
    title = widget.get("title") or first or f"Visual {idx + 1}"
    if ct is None:                                    # text/no-chart widget -> skip
        return None, None, {"page": tab, "visual": title, "ts_chart": "(skipped)",
                            "status": "Skipped", "note": note}
    r = _widget_columns(widget, ct, ctx)
    ct = r["ct"]
    fnames = [f["name"] for f in r["formulas"]]
    cols = [d["name"] for d in r["dims"]] + r["plain"] + fnames
    if not cols:
        return None, None, {"page": tab, "visual": title, "ts_chart": ct,
                            "status": "NEEDS REVIEW",
                            "note": _note_join(note, "no fields mapped to model columns")}
    roles = [d["role"] for d in r["dims"]] + ["Values"] * (len(r["plain"]) + len(fnames))
    status, note = _review(ct, status, note, r, fnames)
    if _rank_note(widget):                            # flag, never turn a bottom N into a top N
        status = "NEEDS REVIEW"
        note = _note_join(note, _rank_note(widget))
    a_obj = build_answer(title, f"{tab}-{idx}", model_name, model_fqn, cols, ct,
                         set(ctx["measures"]) | set(fnames), roles, r["bucket_tokens"],
                         _widget_top_n(widget))
    _decorate(a_obj["answer"], ct, r)
    return a_obj, {"answer": a_obj["answer"], "tile": None}, \
        {"page": tab, "visual": title, "ts_chart": ct, "status": status, "note": note}


def _review(ct, status, note, r, fnames) -> tuple:
    """Fold a widget's resolution notes and gaps into its (status, note)."""
    status = _worse(status, r["status"])
    if ct not in _NO_MEASURE_OK and not (r["plain"] or fnames):   # flag, don't downgrade
        status = "NEEDS REVIEW"
        note = _note_join(note, f"{ct} needs a measure but none mapped")
    for n in r["notes"]:
        note = _note_join(note, n)
    if r["missing"]:
        status = _worse(status, "NEEDS REVIEW")
        note = _note_join(note, "unmapped field(s): " + ", ".join(r["missing"]))
    return status, note


def _decorate(ans: dict, ct: str, r: dict) -> None:
    """Widget filters, formulas and the grid display mode onto an emitted Answer."""
    if ct == "GRID_TABLE":
        # A GRID_TABLE in CHART_MODE imports cleanly but its Liveboard tile returns "No data
        # source found for the query"; TABLE_MODE renders (live-verified 2026-11-26).
        ans["display_mode"] = "TABLE_MODE"
    if r["search"]:
        ans["search_query"] = (ans["search_query"] + " " + " ".join(r["search"])).strip()
    if r["formulas"]:
        ans["formulas"] = r["formulas"]


def _widget_ctx(inv: dict, column_names, measure_names) -> dict:
    """What every widget resolves against: the Model's names and the Liveboard filters."""
    chips = extract_liveboard_filters(inv, column_names, measure_names)
    return {"norm": {n.lower(): n for n in (column_names or [])},
            "measures": set(measure_names or []),
            "dash_filters": (inv.get("dashboard") or {}).get("filters") or [],
            "lb_cols": {c["column"][0] for c in chips}}


def build_liveboard_result(inv: dict, model_name: str, model_fqn=None, column_names=None,
                           measure_names=None, overrides=None) -> dict:
    """Parsed Sisense inventory -> ``{answers, liveboard, visual_rows, report_name}``.

    Mirrors the shared ``build_from_spec`` output contract, but emits each widget's Answer via
    the emitter's ``build_answer`` using the Sisense-resolved ``ts_chart`` (COLUMN/PIE/KPI/…)
    directly, so the chart type and the Approximated/NEEDS-REVIEW status are honoured on the
    current ``main`` emitter without depending on the (unmerged) ts_chart-aware variant.
    """
    from ts_cli.tableau.liveboard import build_answer, build_liveboard

    overrides = overrides or {}
    dash = inv.get("dashboard") or {}
    report_name = overrides.get("report_name") or dash.get("title") or model_name
    tab = dash.get("title") or report_name

    ctx = _widget_ctx(inv, column_names, measure_names)
    answers, items, rows = [], [], []
    for i, w in enumerate(inv.get("widgets", []) or []):
        a_obj, item, row = _widget_answer(w, i, tab, model_name, model_fqn, ctx,
                                          build_answer)
        if a_obj:
            answers.append(a_obj)
        if item:
            items.append(item)
        rows.append(row)
    liveboard = build_liveboard(report_name, [(tab, items)]) if items else None
    return {"answers": answers, "liveboard": liveboard, "visual_rows": rows,
            "report_name": report_name}


# --------------------------------------------------------------------------- #
# Sisense-local injection: dashboard filter bar -> Liveboard filter chips
# --------------------------------------------------------------------------- #
def _range_generic_filter(raw: dict):
    """Sisense numeric range dict -> a ThoughtSpot generic_filter {oper, values}, or None.

    from/to are inclusive bounds (GE/LE); fromNotEqual/toNotEqual are exclusive (GT/LT);
    a two-sided range becomes BETWEEN (BW_INC inclusive / BW exclusive); `equals` becomes EQ.
    Ported verbatim from map/content.py._range_generic_filter.
    """
    r = raw or {}
    if r.get("equals") is not None:
        return {"oper": "EQ", "values": [r["equals"]]}
    lo, lo_ex = r.get("from"), r.get("fromNotEqual")
    hi, hi_ex = r.get("to"), r.get("toNotEqual")
    lo_val = lo if lo is not None else lo_ex        # lower bound present (either inclusivity)
    hi_val = hi if hi is not None else hi_ex        # upper bound present (either inclusivity)
    # Two-sided: keep BOTH bounds — never drop one (a mixed inclusive/exclusive range must
    # not silently collapse to an open-ended single bound). ThoughtSpot exposes BW_INC
    # (both-inclusive) and BW (both-exclusive); a mixed range uses BW_INC and the exact
    # boundary inclusivity is a known fidelity gap tracked in open-items (verify live).
    if lo_val is not None and hi_val is not None:
        both_exclusive = lo is None and hi is None
        return {"oper": "BW" if both_exclusive else "BW_INC", "values": [lo_val, hi_val]}
    for val, op in ((lo, "GE"), (lo_ex, "GT"), (hi, "LE"), (hi_ex, "LT")):
        if val is not None:
            return {"oper": op, "values": [val]}
    return None


def _resolve_exposed_col(dim, cols: set, measures: set, check_exposure: bool):
    """Filter dim -> the model column display name to chip on, or None to skip the filter.

    Retries the date-hierarchy base ('Date (Calendar)' -> 'Date') before giving up; when
    exposure checking is off, any non-empty resolved column is kept."""
    col = _model_col(dim)
    if not col:
        return None
    if not check_exposure or col in cols or col in measures:
        return col
    base = col.split(" (")[0].strip()
    if base in cols or base in measures:
        return base
    return None


def _chip_from_filter(sf: dict, col: str) -> dict:
    """One resolved Sisense filter -> a ThoughtSpot Liveboard filter chip.

    member -> generic_filter IN; exclude -> NOT_IN; numeric range -> GE/GT/LE/LT/BW_INC/BW/EQ.
    Any other preset (all / relative-date / unknown) yields a bare interactive chip."""
    chip = {"column": [col], "is_mandatory": False,
            "is_single_value": False, "display_name": ""}
    kind = sf.get("kind")
    values = sf.get("values") or []
    # member/exclude use the exported-Liveboard shape (top-level `oper` + `values`), live-verified
    # to filter every tile; ranges keep generic_filter until verified (open-items #5)
    if kind == "member" and values:
        chip.update(oper="in", values=[str(v) for v in values])
    elif kind == "exclude" and values:
        chip.update(oper="not in", values=[str(v) for v in values])
    elif kind == "range":
        gf = _range_generic_filter(sf.get("raw"))
        if gf:
            chip["generic_filter"] = gf
    return chip


def extract_liveboard_filters(inv: dict, column_names=None, measure_names=None) -> list:
    """Sisense DASHBOARD-level filters (the interactive filter bar) -> ThoughtSpot Liveboard
    filter chips that apply across every viz. member -> generic_filter IN; exclude -> NOT_IN;
    numeric range -> GE/GT/LE/LT/BW_INC/BW/EQ. A top-N is per-viz (baked into a widget answer),
    not a liveboard chip, so it is skipped here.

    When ``column_names``/``measure_names`` are supplied, a filter whose column is not exposed
    on the model is dropped (matches map/content.py); when omitted, every resolvable filter
    becomes a chip. An 'all'/relative-date/unrecognized preset still yields a bare interactive
    chip (column only) so nothing is silently dropped. Ported from content.py.liveboard_filters.
    """
    cols = {c for c in (column_names or [])}
    measures = {m for m in (measure_names or [])}
    check_exposure = bool(cols or measures)
    out = []
    for sf in (inv.get("dashboard") or {}).get("filters", []) or []:
        if sf.get("kind") == "top_n":
            continue
        col = _resolve_exposed_col(sf.get("dim"), cols, measures, check_exposure)
        if col is None:
            continue
        out.append(_chip_from_filter(sf, col))
    return out
