#!/usr/bin/env python3
"""Extract a structured inventory from an offline Sisense bundle.

Consumes the offline export bundle ``{dashboard, widgets, datamodel}`` (see
``samples/sample_ecommerce_source.json``) and produces a single JSON-serializable
inventory: tables + typed columns + relations (the datamodel side the model path
needs), plus a best-effort parse of widgets and dashboard filters.

Ported from the standalone converter (extract/parse.py + extract/sisense_types.py).
Emits plain dicts (no frozen-dataclass IR) so the inventory round-trips through JSON.
Stdlib only. Anything the parser cannot confidently read is appended to ``warnings``
rather than guessed, so the migration report can surface it — never crashes.

Verified JSON shapes (live Sisense Cloud trial, standalone converter):
- datamodel tables live at datasets[].schema.tables[]; each column has an int `type`
  code (see _SISENSE_TYPE_CODES). dataset/table/column each carry an `oid` AND an `id`.
- relations[].columns is a list of {dataset, table, column} OID triples; resolved here
  via an oid->(table_id, column_id) index built from the datasets.
- widgets are separate from the dashboard; dashboard filters are at dash["filters"][].jaql.
"""
from __future__ import annotations


# --------------------------------------------------------------------------- #
# Data types — Sisense Datamodels v2 column type codes -> normalized token
# --------------------------------------------------------------------------- #
# The normalized lowercase token is mapped to a TML data_type enum by tables._tml_type.
_SISENSE_TYPE_CODES: dict[int, str] = {
    0: "int64",     # BigInt
    2: "bool",      # Boolean
    3: "string",    # Char
    4: "datetime",  # Timestamp (DateTime)
    5: "double",    # Decimal
    6: "double",    # Float
    8: "int64",     # Integer
    13: "double",   # Real
    16: "int64",    # SmallInt
    18: "string",   # VarChar
    19: "datetime",  # Timestamp (legacy, now 4)
    20: "int64",    # TinyInt
    31: "date",     # Date
    32: "string",   # Time
    40: "double",   # Double
    41: "double",   # Numeric
    43: "datetime",  # TimestampWithTimezone
    44: "string",   # TimeWithTimezone
}


def _to_datatype(code) -> str:
    """Map a Sisense type code (int or numeric string) to a normalized type token."""
    try:
        return _SISENSE_TYPE_CODES.get(int(code), "unknown")
    except (TypeError, ValueError):
        return "unknown"


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
def _parse_columns(t: dict, col_by_oid: dict, t_id) -> list:
    """One table's ``columns[]`` -> list of column dicts; records column oid -> (t_id, c_id)."""
    columns: list[dict] = []
    for c in t.get("columns", []) or []:
        c_id = c.get("id") or c.get("name") or c.get("oid")
        columns.append({
            "id": c_id,
            "name": c.get("name") or c.get("displayName") or c_id,
            "data_type": _to_datatype(c.get("type")),
            "calculated": bool(c.get("isCustom")),
            "expression": c.get("expression"),
        })
        if c.get("oid"):
            col_by_oid[c["oid"]] = (t_id, c_id)
    return columns


def _parse_table(t: dict, tables: list, col_by_oid: dict, table_by_oid: dict) -> None:
    """One schema table -> append a table dict and record its oid -> id mapping."""
    t_oid = t.get("oid")
    t_id = t.get("id") or t.get("name") or t_oid
    tables.append({
        "id": t_id,
        "name": t.get("displayName") or t.get("name") or t_id,
        "jaql_name": t.get("name") or t_id,   # the table name JAQL dims use ([name.column])
        "columns": _parse_columns(t, col_by_oid, t_id),
        "sql_expression": t.get("expression") if t.get("type") == "custom" else None,
        # Sisense calculated columns added on the table (`tupleTransformations` add-column):
        # names only, for binding; the model path reads `columns[].calculated` as before
        "calculated_columns": sorted({n for tt in t.get("tupleTransformations") or []
                                      if tt.get("type") == "add-column"
                                      for n in ((tt.get("arguments") or {}).get("id"),
                                                (tt.get("arguments") or {}).get("name")) if n}),
    })
    if t_oid:
        table_by_oid[t_oid] = t_id


def _resolve_endpoint(ep: dict, col_by_oid: dict, table_by_oid: dict) -> dict:
    """One relation column ref -> {table, column}, resolving via the oid index when possible."""
    col_ref = ep.get("column")
    resolved = col_by_oid.get(col_ref)
    if resolved:
        return {"table": resolved[0], "column": resolved[1]}
    # already a name/id (synthetic bundle) or unresolved oid
    return {"table": table_by_oid.get(ep.get("table"), ep.get("table")), "column": col_ref}


def _parse_relations(raw: dict, col_by_oid: dict, table_by_oid: dict, warnings: list) -> list:
    """Walk ``relations[]`` -> list of {endpoints, cardinality}; unresolvable relations warned."""
    relations: list[dict] = []
    for rel in raw.get("relations", []) or []:
        endpoints = [_resolve_endpoint(ep, col_by_oid, table_by_oid)
                     for ep in rel.get("columns", []) or []]
        if endpoints:
            relations.append({"endpoints": endpoints,
                              "cardinality": rel.get("type") or "UNKNOWN"})
        else:
            warnings.append("A relation had no resolvable endpoints; skipped.")
    return relations


def parse_datamodel(raw: dict, warnings: list) -> tuple:
    """Sisense v2 datamodel export -> (tables, relations) as plain dicts.

    Tables are at datasets[].schema.tables[]. Relations reference columns by oid, so
    an oid->(table_id, column_id) index resolves each join endpoint to ids that match
    the tables list. Falls back gracefully if a relation already uses names/ids.
    """
    tables: list[dict] = []
    col_by_oid: dict[str, tuple] = {}   # column oid -> (table_id, column_id)
    table_by_oid: dict[str, str] = {}   # table oid  -> table_id

    for ds in raw.get("datasets", []) or []:
        schema = ds.get("schema") or {}
        for t in schema.get("tables", []) or []:
            _parse_table(t, tables, col_by_oid, table_by_oid)

    relations = _parse_relations(raw, col_by_oid, table_by_oid, warnings)
    return tables, relations


# --------------------------------------------------------------------------- #
# Dashboard / widgets (best-effort; the model path does not consume these)
# --------------------------------------------------------------------------- #
def _items(widget: dict):
    for panel in (widget.get("metadata") or {}).get("panels", []) or []:
        pname = panel.get("name") or ""
        for item in panel.get("items", []) or []:
            yield pname, item


def _jaql_to_field(jaql: dict) -> dict | None:
    """One JAQL item -> field dict, or None for gauge-bound / empty items."""
    if not isinstance(jaql, dict):
        return None
    formula = jaql.get("formula")
    has_formula = formula not in (None, "", "0")
    dim = jaql.get("dim")
    agg = jaql.get("agg")
    if not has_formula and not dim:
        return None  # gauge bound or empty
    if has_formula:
        kind = "measure"
        f = {"expression": str(formula), "context": jaql.get("context") or {}}
    elif agg:
        kind, f = "measure", None
    else:
        kind, f = "dimension", None
    out = {"kind": kind, "dim": dim, "agg": agg, "title": jaql.get("title") or "",
           "formula": f, "level": jaql.get("level")}
    for key in ("datatype", "firstday", "dateTimeLevel"):
        if jaql.get(key):
            out[key] = jaql[key]
    return out


def _classify_member(f: dict, dim) -> dict | None:
    if "members" not in f:
        return None
    return {"kind": "member", "dim": dim, "operator": "members",
            "values": list(f.get("members") or []), "raw": f}


def _classify_exclude(f: dict, dim) -> dict | None:
    if "exclude" not in f:
        return None
    return {"kind": "exclude", "dim": dim, "operator": "exclude",
            "values": list((f.get("exclude") or {}).get("members") or []), "raw": f}


def _classify_relative_date(f: dict, dim) -> dict | None:
    if "last" not in f and "next" not in f:
        return None
    op = "last" if "last" in f else "next"
    return {"kind": "relative_date", "dim": dim, "operator": op, "values": [f.get(op)], "raw": f}


def _classify_top_n(f: dict, dim) -> dict | None:
    if "top" not in f and "bottom" not in f:
        return None
    op = "top" if "top" in f else "bottom"
    return {"kind": "top_n", "dim": dim, "operator": op, "values": [f.get(op)], "raw": f}


def _classify_range(f: dict, dim) -> dict | None:
    if not any(k in f for k in ("from", "to", "equals", "fromNotEqual", "toNotEqual")):
        return None
    return {"kind": "range", "dim": dim, "operator": "range",
            "values": [f[k] for k in ("from", "to", "equals") if k in f], "raw": f}


# Filter keys each kind is READ for; anything else on a filter is recorded in ``unsupported``
# so a consumer that claims fidelity can refuse it instead of carrying a filter it cannot read.
_COMMON_FILTER_KEYS = frozenset({"explicit", "multiSelection", "level", "all"})
_KIND_FILTER_KEYS = {
    "member": {"members"},
    "exclude": {"exclude", "isCondition"},
    "relative_date": {"last", "next"},
    "top_n": {"top", "bottom", "by"},
    "range": {"from", "to", "fromNotEqual", "toNotEqual", "equals", "isBetween"},
    "unknown": set(),
}


def _unsupported_keys(kind: str, f: dict) -> list:
    keys = set(f) - _COMMON_FILTER_KEYS - _KIND_FILTER_KEYS.get(kind, set())
    if kind == "exclude":
        keys |= {f"exclude.{k}" for k in (f.get("exclude") or {}) if k != "members"}
    return sorted(keys)


# Ordered so the first matching kind wins (member > exclude > relative_date > top_n > range).
_FILTER_CLASSIFIERS = (_classify_member, _classify_exclude, _classify_relative_date,
                       _classify_top_n, _classify_range)


def _classify_filter(jaql: dict) -> dict | None:
    """Map a JAQL item (dim + filter) to a filter dict; UNKNOWN shapes still recorded.

    Each dict carries ``raw`` (the original Sisense filter subdict) so the liveboard-chip
    extractor can reconstruct numeric-range presets (from/to/fromNotEqual/… -> GE/LE/BW/EQ),
    which the flattened ``values`` list cannot express. The model path ignores filters, so
    this is additive.
    """
    if not isinstance(jaql, dict):
        return None
    f = jaql.get("filter") or {}
    dim = jaql.get("dim")
    if not f:
        return None
    for classify in _FILTER_CLASSIFIERS:
        hit = classify(f, dim)
        if hit is not None:
            break
    else:
        hit = {"kind": "unknown", "dim": dim, "operator": ",".join(f.keys()), "values": [], "raw": f}
    if jaql.get("level"):   # a date filter's grain: members are period starts, not days
        hit["level"] = jaql["level"]
    if jaql.get("datatype"):
        hit["datatype"] = jaql["datatype"]
    unsupported = _unsupported_keys(hit["kind"], f)
    if unsupported:
        hit["unsupported"] = unsupported
    return hit


# Panel-item and JAQL keys the parser reads or that only affect presentation. Anything else is
# recorded per widget in ``unsupported`` (a consumer claiming fidelity refuses the widget).
_ITEM_KEYS = frozenset({"jaql", "instanceid", "format", "disabled", "panel", "field", "hierarchies",
                        "categoriesSorting", "originalJaql", "quickFunction"})
_JAQL_KEYS = frozenset({"table", "column", "dim", "datatype", "columnTitle", "tableTitle", "merged",
                        "isDashboardFilter", "datasource", "locale", "title", "collapsed", "panel",
                        "instanceid", "filter", "isPrimary", "level", "agg", "isWidgetFilter", "type",
                        "formula", "context", "sort", "sortDetails", "firstday", "dateTimeLevel"})


def _item_unsupported(item: dict, jaql: dict) -> list:
    return sorted({f"item.{k}" for k in item if k not in _ITEM_KEYS}
                  | {f"jaql.{k}" for k in jaql if k not in _JAQL_KEYS})


def _parse_item(pname: str, item: dict, acc: dict) -> None:
    """One panel item -> fields / filters. A disabled FILTER is off in Sisense (no filtering),
    so it is recorded in ``disabled_filters`` and not applied; a disabled plotted item is kept
    with ``disabled: true`` for the consumer to decide."""
    jaql = item.get("jaql") or {}
    acc["unsupported"].update(_item_unsupported(item, jaql))
    field = _jaql_to_field(jaql)
    if field:
        field["panel"] = pname
        if item.get("quickFunction"):
            field["quick_function"] = item["quickFunction"]
        if item.get("disabled") and pname.lower() != "filters":
            field["disabled"] = True
        mask = (item.get("format") or {}).get("mask") or {}
        if mask.get("percent"):
            field["percent"] = True
        acc["fields"].append(field)
    if jaql.get("filter"):
        if item.get("disabled"):
            acc["disabled_filters"].append(jaql.get("dim") or jaql.get("title") or "?")
            return
        sf = _classify_filter(jaql)
        if sf:
            acc["filters"].append(sf)


def parse_widget(widget: dict, warnings: list) -> dict:
    acc = {"fields": [], "filters": [], "disabled_filters": [], "unsupported": set()}
    try:
        for pname, item in _items(widget):
            _parse_item(pname, item, acc)
    except Exception as e:  # never let one malformed widget abort the parse
        warnings.append(f"Could not fully parse widget {widget.get('oid', '?')}: {e}")
    out = {
        "oid": widget.get("oid") or "",
        "title": widget.get("title") or "",
        "wtype": widget.get("type") or "",
        "subtype": widget.get("subtype") or "",
        "fields": acc["fields"],
        "filters": acc["filters"],
    }
    for key in ("disabled_filters", "unsupported"):
        if acc[key]:
            out[key] = sorted(acc[key]) if key == "unsupported" else acc[key]
    out.update(_widget_extras(widget))
    out.update(_dashboard_filter_settings(widget))
    return out


def _dashboard_filter_settings(widget: dict) -> dict:
    """How dashboard filters reach this widget: ``filters_mode`` (Sisense ``filter`` slices,
    ``select`` is Highlight) and ``ignore`` ({all, dimensions, ids}) — only when not the default."""
    out: dict = {}
    mode = (widget.get("options") or {}).get("dashboardFiltersMode")
    if mode and mode != "filter":
        out["filters_mode"] = mode
    ig = (widget.get("metadata") or {}).get("ignore") or {}
    if ig.get("all") or ig.get("dimensions") or ig.get("ids"):
        out["ignore"] = {"all": bool(ig.get("all")), "dimensions": list(ig.get("dimensions") or []),
                         "ids": list(ig.get("ids") or [])}
    return out


def _widget_extras(widget: dict) -> dict:
    """Presentation keys the liveboard layer needs: tab-set config, rich-text content and
    jump-to-dashboard drill targets. Only present when the widget carries them."""
    wtype, style = widget.get("type") or "", widget.get("style") or {}
    extras: dict = {}
    if wtype == "WidgetsTabber":
        extras["tabber"] = _tabber(style)
    if wtype == "richtexteditor":
        content = style.get("content") or {}
        extras["richtext"] = {"html": content.get("html") or "", "bg_color": content.get("bgColor") or ""}
    targets = _drill_targets(widget.get("drillToDashboardConfig") or {})
    if targets:
        extras["drill_targets"] = targets
    return extras


def _tabber(style: dict) -> dict:
    tabs = [{"title": t.get("title") or "", "show": list(t.get("displayWidgetIds") or [])}
            for t in style.get("tabs") or []]
    try:
        active = int(style.get("activeTab") or 0)
    except (TypeError, ValueError):
        active = 0
    return {"tabs": tabs, "active": active if 0 <= active < len(tabs) else 0}


def _drill_targets(drill: dict) -> list:
    if drill.get("enabled", True) is False:
        return []
    return [t for t in (d.get("dashboardTitle") or d.get("caption") or ""
                        for d in drill.get("dashboardIds") or [] if isinstance(d, dict)) if t]


def _dashboard_filter(f: dict, dash_filters: list, disabled: list) -> None:
    """One dashboard filter (a cascading group has no jaql of its own, only levels[]) -> one
    entry per level; a switched-off one performs no filtering in Sisense, so it is listed apart."""
    for jaql in f.get("levels") or [f.get("jaql") or f]:
        if f.get("disabled") or jaql.get("disabled"):
            disabled.append(jaql.get("dim") or jaql.get("title") or "?")
            continue
        sf = _classify_filter(jaql)
        if sf:
            sf["instanceids"] = [i for i in (f.get("instanceid"), jaql.get("instanceid")) if i]
            dash_filters.append(sf)


def parse_dashboard(raw: dict, warnings: list) -> dict:
    dash_filters: list[dict] = []
    disabled: list = []
    for f in raw.get("filters", []) or []:
        _dashboard_filter(f, dash_filters, disabled)
    out = {
        "oid": raw.get("oid") or raw.get("_id") or "",
        "title": raw.get("title") or "",
        "datasource": (raw.get("datasource") or {}).get("title") or "",
        "filters": dash_filters,
        "layout": _parse_layout(raw.get("layout") or {}),
    }
    if disabled:
        out["disabled_filters"] = disabled
    return out


def _px(h) -> int:
    """Sisense element height ('140px' or 140) -> pixels; 0 when unreadable."""
    try:
        return int(float(str(h).replace("px", "").strip()))
    except (TypeError, ValueError):
        return 0


def _parse_layout(layout: dict) -> list:
    """Sisense columnar layout -> rows of placed widgets, top to bottom.

    Each row is ``[{"oid", "width_pct", "height_px", "col_pct"}]`` where ``width_pct`` is the
    subcell width within its layout column and ``col_pct`` the layout column's own width; a
    multi-column dashboard lists each column's rows in turn (``col`` index on each row).
    """
    rows = []
    for ci, col in enumerate(layout.get("columns") or []):
        col_pct = float(col.get("width") or 100)
        for cell in col.get("cells") or []:
            row = []
            for sub in cell.get("subcells") or []:
                width = float(sub.get("width") or 100)
                for el in sub.get("elements") or []:
                    if el.get("widgetid"):
                        row.append({"oid": el["widgetid"], "width_pct": width,
                                    "height_px": _px(el.get("height")), "col_pct": col_pct})
            if row:
                rows.append({"col": ci, "items": row})
    return rows


def parse_inventory(bundle: dict) -> dict:
    """Parse an offline Sisense bundle into a structured inventory.

    Pure function (dict in, dict out; no argv / stdout). ``bundle`` is the loaded
    ``{dashboard, widgets, datamodel}`` JSON. Returns
    ``{source, tables, relations, widgets, dashboard, counts, warnings}`` — the shape
    ``ts sisense build-model`` consumes. Anything the parser cannot confidently read is
    appended to ``warnings`` rather than guessed.
    """
    warnings: list = []
    if not isinstance(bundle, dict):
        return {"source": "", "tables": [], "relations": [], "widgets": [],
                "dashboard": {}, "counts": {"tables": 0, "columns": 0, "relations": 0,
                                            "widgets": 0},
                "warnings": ["Bundle is not a JSON object."]}

    datamodel = bundle.get("datamodel") or {}
    if not datamodel:
        warnings.append("No 'datamodel' in bundle; no tables/relations extracted.")
    tables, relations = parse_datamodel(datamodel, warnings)

    dashboard_raw = bundle.get("dashboard") or {}
    dashboard = parse_dashboard(dashboard_raw, warnings) if dashboard_raw else {}

    widgets_raw = bundle.get("widgets")
    if widgets_raw is None:
        widgets_raw = dashboard_raw.get("widgets") or []
    widgets = [parse_widget(w, warnings) for w in widgets_raw or []]

    source = (datamodel.get("title") or datamodel.get("name")
              or dashboard.get("title") or "model")

    return {
        "source": source,
        "tables": tables,
        "relations": relations,
        "widgets": widgets,
        "dashboard": dashboard,
        "counts": {
            "tables": len(tables),
            "columns": sum(len(t["columns"]) for t in tables),
            "relations": len(relations),
            "widgets": len(widgets),
        },
        "warnings": warnings,
    }
