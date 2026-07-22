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
        "columns": _parse_columns(t, col_by_oid, t_id),
        "sql_expression": t.get("expression") if t.get("type") == "custom" else None,
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
    return {"kind": kind, "dim": dim, "agg": agg, "title": jaql.get("title") or "",
            "formula": f, "level": jaql.get("level")}


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
            return hit
    return {"kind": "unknown", "dim": dim, "operator": ",".join(f.keys()), "values": [], "raw": f}


def parse_widget(widget: dict, warnings: list) -> dict:
    fields: list[dict] = []
    filters: list[dict] = []
    try:
        for pname, item in _items(widget):
            jaql = item.get("jaql") or {}
            field = _jaql_to_field(jaql)
            if field:
                field["panel"] = pname
                fields.append(field)
            if jaql.get("filter"):
                sf = _classify_filter(jaql)
                if sf:
                    filters.append(sf)
    except Exception as e:  # never let one malformed widget abort the parse
        warnings.append(f"Could not fully parse widget {widget.get('oid', '?')}: {e}")
    return {
        "oid": widget.get("oid") or "",
        "title": widget.get("title") or "",
        "wtype": widget.get("type") or "",
        "subtype": widget.get("subtype") or "",
        "fields": fields,
        "filters": filters,
    }


def parse_dashboard(raw: dict, warnings: list) -> dict:
    dash_filters: list[dict] = []
    for f in raw.get("filters", []) or []:
        sf = _classify_filter(f.get("jaql") or f)
        if sf:
            dash_filters.append(sf)
    return {
        "oid": raw.get("oid") or raw.get("_id") or "",
        "title": raw.get("title") or "",
        "datasource": (raw.get("datasource") or {}).get("title") or "",
        "filters": dash_filters,
    }


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
