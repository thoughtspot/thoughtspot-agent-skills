"""TWB/TWBX XML parsing: parameter extraction, and table/column/join/
calculated-field discovery from Tableau datasources.

Accepts four Tableau file shapes:
  - ``.twb``  — workbook XML (root ``<workbook>``, datasources are descendants)
  - ``.twbx`` — zipped workbook (contains a ``.twb``)
  - ``.tds``  — a published/standalone datasource (root IS ``<datasource>``)
  - ``.tdsx`` — zipped datasource (contains a ``.tds``)

The ``.tds``/``.tdsx`` shapes matter for published (``sqlproxy``) datasources: the
workbook hides their physical tables + joins, which live only in the datasource's
``.tds``. See ``datasource_elements`` for the root-shape handling.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any, Optional


def load_xml_root(path: str | Path) -> ET.Element:
    """Load the XML root from a ``.twb``/``.twbx``/``.tds``/``.tdsx`` (zip-aware).

    For the zipped forms, extract the inner document: ``.twbx`` → ``.twb``,
    ``.tdsx`` → ``.tds`` (falling back to whichever of the two is present).
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".twbx", ".tdsx"):
        inner = suffix[:-1]  # ".twbx" → ".twb", ".tdsx" → ".tds"
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            name = next((n for n in names if n.endswith(inner)), None)
            if name is None:  # tolerate a .twb packaged as .tdsx or vice versa
                name = next(n for n in names if n.endswith((".twb", ".tds")))
            return ET.parse(z.open(name)).getroot()
    return ET.parse(str(path)).getroot()


def datasource_elements(root: ET.Element) -> list[ET.Element]:
    """Return the datasource elements for either root shape.

    A ``.twb``/``.twbx`` root is ``<workbook>`` with descendant ``<datasource>``
    elements; a standalone ``.tds``/``.tdsx`` root **is** the ``<datasource>``
    itself (``.//datasource`` would not match it).
    """
    if root.tag == "datasource":
        return [root]
    return root.findall(".//datasource")


# ---------------------------------------------------------------------------
# 6. Parameter extraction from TWB XML
# ---------------------------------------------------------------------------

def extract_parameters(root: ET.Element) -> list[dict]:
    """Extract parameters from the Tableau Parameters datasource.

    Returns list of parameter dicts ready for model TML:
      {name, default_value, data_type, description, list_config?}
    """
    params_ds = root.find('.//datasource[@name="Parameters"]')
    if params_ds is None:
        return []

    params = []
    for col in params_ds.findall("./column"):
        name = col.get("caption", col.get("name", ""))
        if name.startswith("["):
            name = name.strip("[]")
        datatype = col.get("datatype", "string")
        value = col.get("value", "").strip('"')
        alias = col.get("alias", "").strip('"')

        ts_type = _tableau_type_to_ts_param(datatype)
        param: dict[str, Any] = {
            "name": name,
            "default_value": alias or value or "",
            "data_type": ts_type,
        }

        members = col.findall(".//member")
        if members:
            choices = []
            for m in members:
                val = m.get("value", "").strip('"')
                display = m.get("alias", val).strip('"')
                if val.startswith("&quot;"):
                    val = val.replace("&quot;", "")
                if display.startswith("&quot;"):
                    display = display.replace("&quot;", "")
                choices.append({"value": val, "display_name": display})
            if choices:
                param["data_type"] = "CHAR"
                param["list_config"] = {"list_choice": choices}

        _range = col.find(".//range")
        if _range is not None:
            param["range_config"] = {
                "min": _range.get("min", ""),
                "max": _range.get("max", ""),
            }

        params.append(param)
    return _normalize_date_params(params)


def _normalize_date_params(params: list[dict]) -> list[dict]:
    """Convert Tableau date defaults to ThoughtSpot MM/DD/YYYY format.

    Tableau uses #YYYY-MM-DD# or YYYY-MM-DD; ThoughtSpot DATE parameters
    require MM/DD/YYYY.
    """
    for p in params:
        if p.get("data_type") not in ("DATE", "DATE_TIME"):
            continue
        if p.get("default_value"):
            p["default_value"] = _reformat_tableau_date(p["default_value"])
        rc = p.get("range_config")
        if rc:
            if rc.get("min"):
                rc["min"] = _reformat_tableau_date(rc["min"])
            if rc.get("max"):
                rc["max"] = _reformat_tableau_date(rc["max"])
        lc = p.get("list_config")
        if lc:
            for choice in lc.get("list_choice", []):
                if choice.get("value"):
                    choice["value"] = _reformat_tableau_date(choice["value"])
    return params


def _reformat_tableau_date(val: str) -> str:
    """Strip Tableau # delimiters and convert YYYY-MM-DD → MM/DD/YYYY."""
    val = val.strip("#").strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", val)
    if m:
        return f"{m[2]}/{m[3]}/{m[1]}"
    return val


def _tableau_type_to_ts_param(datatype: str) -> str:
    _map = {
        "string": "CHAR",
        "integer": "INT",
        "real": "DOUBLE",
        "boolean": "BOOL",
        "date": "DATE",
        "datetime": "DATE_TIME",
    }
    return _map.get(datatype, "CHAR")


def build_param_name_map(root: ET.Element) -> dict[str, str]:
    """Build internal param name → caption map from TWB XML.

    Maps e.g. "[Parameter 3]" → "Metric" using the caption attribute.
    """
    params_ds = root.find('.//datasource[@name="Parameters"]')
    if params_ds is None:
        return {}
    result = {}
    for col in params_ds.findall("./column"):
        internal = col.get("name", "").strip("[]")
        caption = col.get("caption", "")
        if internal and caption and internal != caption:
            result[internal] = caption
    return result


# ---------------------------------------------------------------------------
# 6b. Native Set detection (BL-131) + 6c. Set -> cohort extraction (BL-067 part 1)
#
# Split into ts_cli.tableau.set_extract (module-per-concern, BL-069 pattern) to
# keep this file's line count in budget. Re-exported here so existing callers/
# tests importing them from ts_cli.tableau.twb keep working unchanged.
# ---------------------------------------------------------------------------

from ts_cli.tableau.set_extract import count_native_sets, extract_sets  # noqa: E402,F401


# ---------------------------------------------------------------------------
# TWB XML parser
# ---------------------------------------------------------------------------

def parse_twb(twb_path: str | Path) -> dict:
    """Parse a TWB or TWBX file and extract all model-relevant data.

    Returns a dict with:
      datasources: list of datasource dicts, each containing:
        name, tables, columns, joins, calculated_fields, calc_map
      parameters: list of parameter dicts
      param_map: internal param name → caption map
    """
    root = load_xml_root(twb_path)

    parameters = extract_parameters(root)
    param_map = build_param_name_map(root)
    param_names = {p["name"] for p in parameters}

    datasources = []
    seen_ds = set()

    for ds in datasource_elements(root):
        ds_name = ds.get("caption", ds.get("name", ""))
        if ds_name == "Parameters":
            continue
        if not ds_name or ds_name in seen_ds:
            continue

        tables = _extract_tables(ds)
        sql_views = _extract_sql_views(ds)
        if not tables and not sql_views:
            continue
        seen_ds.add(ds_name)

        columns = _extract_columns(ds, tables)
        joins = _extract_joins(ds)
        # Modern Tableau stores joins as logical relationships (the "noodle"), not physical
        # <relation join=...>; pick those up too, or a multi-table model imports with no join
        # and ThoughtSpot rejects it. See reference-tableau-model-discovery-algorithm.
        joins += _extract_noodle_joins(ds, sql_views)
        calcs, calc_map = _extract_calculated_fields(ds)
        col_table_map = _build_column_table_map(ds, tables)
        sets = extract_sets(ds)

        datasources.append({
            "name": ds_name,
            "tables": tables,
            "sql_views": sql_views,
            "columns": columns,
            "joins": joins,
            "calculated_fields": calcs,
            "calc_map": calc_map,
            "col_table_map": col_table_map,
            # BL-067: classified native Tableau Sets (see extract_sets) — the
            # structural extraction half of set->cohort conversion; TML emission
            # (build_cohort_tml) is a separate build-model-time step.
            "sets": sets,
        })

    return {
        "datasources": datasources,
        "parameters": parameters,
        "param_map": param_map,
        # BL-131: native Tableau Sets are not auto-converted by build-model's
        # GENERATE pass (set->cohort is an agent-guided Phase-2a/2b/2c step) —
        # surfaced here so the caller can nudge instead of silently skipping.
        "sets_detected": count_native_sets(root),
    }


def extract_blends(root: ET.Element) -> dict:
    """Build the data-blend graph, keyed by datasource caption.

    Returns {source_caption: [{"target_ds": caption, "column_mappings":
    [{"source_col", "target_col"}]}]}. Federated IDs in the relationship XML are
    resolved to captions so the graph joins to parse_twb's datasources.
    """
    ds_rels = root.find(".//datasource-relationships")
    if ds_rels is None:
        return {}

    fed_to_caption = {
        ds.get("name"): ds.get("caption", ds.get("name", ""))
        for ds in root.findall(".//datasource")
        if ds.get("name")
    }

    dep_map: dict = {}
    for dep in ds_rels.findall("datasource-dependencies"):
        ds_id = dep.get("datasource")
        instance_to_col = {}
        for ci in dep.findall("column-instance"):
            instance_to_col[ci.get("name")] = ci.get("column")
        dep_map[ds_id] = instance_to_col

    graph: dict = {}
    for rel in ds_rels.findall("datasource-relationship"):
        source_ds = rel.get("source")
        target_ds = rel.get("target")
        col_maps = []
        for m in rel.findall("column-mapping/map"):
            src_key = m.get("key", "")
            tgt_key = m.get("value", "")
            src_inst = "[" + src_key.split("].[")[1] if "].[" in src_key else src_key
            tgt_inst = "[" + tgt_key.split("].[")[1] if "].[" in tgt_key else tgt_key
            src_col = dep_map.get(source_ds, {}).get(src_inst, src_inst).strip("[]")
            tgt_col = dep_map.get(target_ds, {}).get(tgt_inst, tgt_inst).strip("[]")
            col_maps.append({"source_col": src_col, "target_col": tgt_col})
        src_caption = fed_to_caption.get(source_ds, source_ds)
        tgt_caption = fed_to_caption.get(target_ds, target_ds)
        graph.setdefault(src_caption, []).append(
            {"target_ds": tgt_caption, "column_mappings": col_maps}
        )
    return graph


def _read_table_calc(tc: ET.Element) -> dict:
    entry = {
        "ordering_type": tc.get("ordering-type", "Rows"),
        "ordering_field": tc.get("ordering-field"),
        "order_fields": [o.get("field") for o in tc.findall("order")],
        "quick_calc_type": tc.get("type"),
        "address_offset": None,
    }
    addr = tc.find("address/value")
    if addr is not None and addr.text:
        entry["address_offset"] = int(addr.text)
    return entry


def extract_table_calc_addressing(root: ET.Element) -> dict:
    """Extract column-level and worksheet-override table-calc addressing.

    ws_overrides take precedence over column_level for a given worksheet.
    """
    column_level: dict = {}
    for column in root.findall(".//datasource//column"):
        calc = column.find("calculation[@class='tableau']")
        if calc is None:
            continue
        tc = calc.find("table-calc")
        if tc is None:
            continue
        column_level[column.get("name")] = _read_table_calc(tc)

    ws_overrides: dict = {}
    for ws in root.findall(".//worksheet"):
        ws_name = ws.get("name")
        ws_overrides[ws_name] = {}
        for ci in ws.findall(".//column-instance"):
            tc = ci.find("table-calc")
            if tc is None:
                continue
            ws_overrides[ws_name][ci.get("column")] = _read_table_calc(tc)

    return {"column_level": column_level, "ws_overrides": ws_overrides}


def _strip_brackets(s: str) -> str:
    return s.replace("[", "").replace("]", "")


def _is_extract_wrapper(tbl: str) -> bool:
    """True when a relation's ``table`` path is schema-scoped to ``Extract`` —
    Tableau's hyper-extract cache mirror of a table's live source, written
    alongside (and with the same ``<relation type='table'>`` shape as) the real
    relation. Per the skill's Step 3b ("Use the live-source relation; ignore
    the ``[Extract]`` relation"), these must never be treated as physical
    tables in their own right — see BL follow-up #4.

    Only the FIRST bracketed segment (the schema) is checked. The wrapper's own
    identifier commonly re-embeds the live table's full dotted db path plus a
    GUID (e.g. ``[Extract].[agg_booked_monthly (db.schema.agg_booked_monthly)_8E5C...]``),
    so splitting once on the first ``.`` (rather than stripping all brackets and
    splitting on every ``.``) is what keeps this robust to those embedded dots.
    """
    return _strip_brackets(tbl).split(".", 1)[0] == "Extract"


def _wrapper_relation_names(ds: ET.Element) -> set[str]:
    """Relation ``name``s that are hyper-Extract cache wrappers (see
    ``_is_extract_wrapper``) — the single source of truth for "this relation is
    not a physical table."

    Shared by ``_extract_tables`` (skips emitting these as Table TML) and
    ``_metadata_column_records`` (skips the wrapper's own duplicate
    metadata-records so column ownership always resolves from the live
    relation, never the wrapper — see the ``col_table_map`` XREF/dropped-column
    fix: a federated Custom-SQL + hyper-Extract datasource writes its column
    metadata TWICE, once under the live ``<connection>`` and once — mirrored,
    GUID-named — under ``<extract>``'s own ``<connection>``, and a naive
    ``.//metadata-record`` walk over the whole datasource picked up both,
    with the extract's document-order-later copy silently winning).
    """
    return {
        rel.get("name", "")
        for rel in ds.findall(".//relation[@type='table']")
        if rel.get("name") and _is_extract_wrapper(rel.get("table", ""))
    }


def _extract_tables(ds: ET.Element) -> list[dict]:
    """Extract physical table definitions from a datasource.

    Uses the relation ``name`` attribute as the table identity. When a TWB joins
    the same physical table twice, Tableau assigns a distinct ``name`` (e.g.
    ``d_partner1``) while keeping the same ``table`` path. We preserve that alias
    so downstream model TML can reference both table instances independently.

    Hyper-extract cache wrapper relations (``table`` schema-scoped to
    ``[Extract]`` — see ``_is_extract_wrapper``) are skipped entirely: they
    duplicate a real table under a mangled name and are never referenced by
    joins, columns, or formulas (those all key off the live-source table name).
    Emitting them as Table TML would write spurious duplicate tables that
    overwrite each other run-to-run when multiple datasources share one.
    """
    tables = []
    seen = set()
    for rel in ds.findall(".//relation[@type='table']"):
        tbl = rel.get("table", "")
        if _is_extract_wrapper(tbl):
            continue
        rel_name = rel.get("name", "")
        physical_name = _strip_brackets(tbl).split(".")[-1] if tbl else ""
        name = rel_name or physical_name
        if not name or name in seen:
            continue
        seen.add(name)
        entry: dict = {
            "name": name,
            "db_table": _strip_brackets(tbl),
        }
        if rel_name and rel_name != physical_name:
            entry["alias_of"] = physical_name
        tables.append(entry)
    return tables


# XML-encoding artifacts Tableau writes into Custom SQL text bodies.
_SQL_XML_ARTIFACTS = (("<<", "<"), (">>", ">"), ("==", "="))


def _decode_sql_artifacts(sql: str) -> str:
    """Undo the XML-encoding artifacts Tableau writes into Custom SQL text bodies
    (``<<``→``<``, ``>>``→``>``, ``==``→``=``). These encodings never nest, so one
    left-to-right pass per artifact is sufficient (order-independent)."""
    for artifact, repl in _SQL_XML_ARTIFACTS:
        sql = sql.replace(artifact, repl)
    return sql


def _sql_view_column_meta(ds: ET.Element) -> dict[str, dict]:
    """caption/role by logical (local) name, from non-calculated ``<column>`` elements."""
    meta: dict[str, dict] = {}
    for col in ds.findall("./column"):
        if col.find("calculation") is not None:
            continue
        local = col.get("name", "").strip("[]")
        if local:
            meta[local] = {
                "caption": col.get("caption", local),
                "role": col.get("role", "dimension"),
            }
    return meta


def _sql_view_columns_by_parent(ds: ET.Element) -> dict[str, list]:
    """Group ``<metadata-record class='column'>`` output columns by parent relation name,
    in ONE pass over the datasource (avoids re-scanning metadata records per relation).
    Keyed by the bracketed relation name, e.g. ``[Custom SQL Query]``."""
    col_meta = _sql_view_column_meta(ds)
    by_parent: dict[str, list] = {}
    for mr in ds.findall(".//metadata-record[@class='column']"):
        parent = mr.findtext("parent-name") or ""
        remote = (mr.findtext("remote-name") or "").strip()
        if not parent or not remote:
            continue
        cols = by_parent.setdefault(parent, [])
        if any(c["sql_output_column"] == remote for c in cols):
            continue
        local = (mr.findtext("local-name") or "").strip("[]")
        meta = col_meta.get(local, {})
        role = meta.get("role", "dimension")
        cols.append({
            "name": meta.get("caption", local or remote),
            "sql_output_column": remote,
            "column_type": "MEASURE" if role == "measure" else "ATTRIBUTE",
            "data_type": _tableau_type_to_ts((mr.findtext("local-type") or "string").strip()),
        })
    return by_parent


def _extract_sql_views(ds: ET.Element) -> list[dict]:
    """Extract Custom SQL relations (``<relation type='text'>``) as SQL View specs.

    Tableau stores a Custom SQL query as a ``type='text'`` relation whose element text
    is the raw SQL; its output columns live in ``<metadata-record class='column'>``
    entries whose ``parent-name`` matches the relation name. Returns one dict per
    relation: ``{"name", "sql_query", "columns": [{"name", "sql_output_column",
    "column_type", "data_type"}]}``. Column ``column_type`` (MEASURE/ATTRIBUTE) is
    enriched from the datasource ``<column>`` elements' ``role``.
    """
    cols_by_parent = _sql_view_columns_by_parent(ds)
    views = []
    seen_names: set[str] = set()
    for rel in ds.findall(".//relation[@type='text']"):
        name = rel.get("name", "")
        sql_query = _decode_sql_artifacts(rel.text or "").strip()
        if not name or not sql_query or name in seen_names:
            continue
        seen_names.add(name)
        views.append({
            "name": name,
            "sql_query": sql_query,
            "columns": cols_by_parent.get(f"[{name}]", []),
        })
    return views


def _metadata_column_records(ds: ET.Element) -> dict[str, dict[str, str]]:
    """Index ``<metadata-record class='column'>`` entries by ``local-name``.

    Each entry carries the column's real warehouse identity: ``remote_name``
    (the physical column name — see agents/cli/ts-convert-from-tableau
    references/step-3-parse-fields.md "remote-name ... use for db_column_name")
    and ``table`` (owning table, from ``parent-name``). Shared by
    ``_extract_columns`` and ``_build_column_table_map`` so both derive
    physical identity from the same source of truth.

    When a column's display caption collides across tables in one datasource,
    Tableau disambiguates by baking `` (table_name)`` into BOTH the internal
    ``<column name=...>`` and the caption (e.g. ``LineItemId (agg_booked_monthly)``)
    — but ``remote-name`` stays the clean physical name (``LineItemId``) in
    every case, colliding or not, which is exactly why it — not the internal
    name — belongs in ``db_column_name``.

    A federated Custom-SQL + hyper-Extract datasource writes each column's
    metadata-record TWICE: once under the live ``<connection>`` (``parent-name``
    = the real relation, e.g. ``[Custom SQL Query]``) and once more, mirrored,
    under ``<extract>``'s own ``<connection>`` (``parent-name`` = the Extract
    wrapper's GUID-mangled relation name, e.g. ``[_9BBB0...]`` — see
    ``_is_extract_wrapper``). Both sit under this same ``<datasource>``, so a
    plain ``.//metadata-record`` walk finds both for one ``local-name``; records
    owned by a wrapper relation are skipped here so the live copy — the one
    ``_extract_tables`` actually emits as a physical table — always wins,
    regardless of document order. Without this, ``table`` (and ``remote_name``,
    which the extract's mirror can itself have internally disambiguated, e.g.
    ``Sales Person1``) resolve to a relation ``_extract_tables`` excludes,
    dangling the column's eventual ``column_id`` ("XREF: column_id not found")
    and dropping it from the emitted Table TML.

    ``table`` is ``parent`` verbatim (bracket-stripped) — NOT ``parent.split(".")``
    — because ``parent-name`` is always a single relation ``name`` reference (the
    same identifier ``_extract_tables`` uses), never a dotted schema-qualified
    path; a file-backed relation's own name can legitimately embed a literal
    ``.`` (e.g. a CSV extract's Tableau-assigned ``some_file.csv1``), which a
    ``.split(".")[-1]`` would wrongly truncate to ``csv1`` — a table
    ``_extract_tables`` never emits, dangling ``column_id`` the same way the
    wrapper-name bug above did.
    """
    wrapper_names = _wrapper_relation_names(ds)
    idx: dict[str, dict[str, str]] = {}
    for rec in ds.findall(".//metadata-record[@class='column']"):
        local_name = (rec.findtext("local-name") or "").strip("[]")
        if not local_name:
            continue
        parent = (rec.findtext("parent-name") or "").strip("[]")
        if parent in wrapper_names:
            continue
        entry = idx.setdefault(local_name, {})
        remote_name = (rec.findtext("remote-name") or "").strip()
        if remote_name:
            entry["remote_name"] = remote_name
        if parent:
            entry["table"] = parent
    return idx


def _extract_columns(ds: ET.Element, tables: list[dict]) -> list[dict]:
    """Extract physical column definitions from a datasource.

    ``db_column_name`` comes from the matching metadata-record's ``remote-name``
    — the real warehouse column — never from the internal Tableau ``<column
    name=...>`` identifier, which Tableau disambiguates with a `` (table_name)``
    suffix on any caption collision (see ``_metadata_column_records``). Using
    that suffixed internal name as db_column_name would bind the Table TML to
    a column that does not exist in the warehouse ("column not found" at
    import) and break join cross-references between the colliding tables.

    ``table`` is likewise stamped from the metadata-record's owning table when
    available, so multi-table ``column_id`` values are ``TABLE::col``-qualified
    from the source of truth rather than left for (fragile, caption-based)
    downstream ownership guessing — and so the many-columns-same-clean-name
    case (the collision above) doesn't collide into duplicate bare
    ``column_id`` values once the disambiguation suffix is gone.
    """
    meta = _metadata_column_records(ds)
    columns = []
    for col in ds.findall("./column"):
        if col.find("calculation") is not None:
            continue
        name_raw = col.get("name", "")
        if not name_raw or name_raw.startswith("[Calculation_"):
            continue

        name = name_raw.strip("[]")
        caption = col.get("caption", name)
        role = col.get("role", "dimension")
        datatype = col.get("datatype", "string")

        column_type = "MEASURE" if role == "measure" else "ATTRIBUTE"
        ts_type = _tableau_type_to_ts(datatype)

        rec = meta.get(name, {})
        entry: dict[str, Any] = {
            "name": caption,
            "db_column_name": rec.get("remote_name") or name,
            "column_type": column_type,
            "data_type": ts_type,
        }
        if rec.get("table"):
            entry["table"] = rec["table"]
        columns.append(entry)
    return columns


def _extract_joins(ds: ET.Element) -> list[dict]:
    """Extract join definitions from a datasource."""
    joins = []
    for rel in ds.findall(".//relation[@join]"):
        join_type = rel.get("join", "inner").upper()
        clauses = rel.findall(".//clause")
        join_keys = []
        for clause in clauses:
            exprs = clause.findall(".//expression")
            if len(exprs) >= 2:
                left = exprs[0].get("op", "")
                right = exprs[1].get("op", "")
                if left.startswith("[") and right.startswith("["):
                    join_keys.append({
                        "left": left.strip("[]"),
                        "right": right.strip("[]"),
                    })
        if join_keys:
            children = rel.findall("./relation[@type='table']")
            left_table = right_table = ""
            if len(children) >= 2:
                left_table = children[0].get("name", "") or _strip_brackets(children[0].get("table", "")).split(".")[-1]
                right_table = children[1].get("name", "") or _strip_brackets(children[1].get("table", "")).split(".")[-1]
            joins.append({
                "type": join_type,
                "left_table": left_table,
                "right_table": right_table,
                "keys": join_keys,
            })
    return joins


def _detail_id_count(view: dict) -> int:
    """Count detail-grain id columns (`*_id` / `* id`) in a view's output.

    The MANY side of a join has finer grain — it carries more identifier columns
    (e.g. driver-events has fleet_account_id AND driver_id; the account-level KI
    breakdown has only fleet_account_id). Robust where GROUP-BY arity isn't (pivot
    CTEs group positionally). The join key counts too, but the finer table has strictly
    more, so the comparison still orders them correctly."""
    n = 0
    for c in view.get("columns", []):
        name = (c.get("sql_output_column") or c.get("name") or "").lower().strip()
        if re.search(r"(^|[ _])id$", name):
            n += 1
    return n


def _extract_noodle_joins(ds: ET.Element, sql_views: list[dict]) -> list[dict]:
    """Extract logical-relationship ("noodle") joins from `<relationships>`.

    Modern Tableau stores joins as logical relationships in
    `<object-graph>/<relationships>`, NOT as physical `<relation join=...>`. Each
    `<relationship>/<expression op="=">` holds two column refs of the form
    `[<col> (<Table Name>)]`; the parenthesised suffix identifies each side's table.

    Tableau defers cardinality to query time, so it is (almost always) absent from the
    file. We infer the MANY side from CTE grain — the table whose Custom SQL has more
    terms in its final `GROUP BY` is finer-grained (MANY). This is a heuristic; a
    post-build double-count check is the proof (see reference-tableau-model-discovery-algorithm).
    """
    grain = {v.get("name"): _detail_id_count(v) for v in sql_views}
    ref_re = re.compile(r"^(.*?)\s*\((.+)\)\s*$")

    def parse_ref(op: str) -> tuple[str, Optional[str]]:
        s = (op or "").strip().strip("[]")
        m = ref_re.match(s)
        return (m.group(1).strip(), m.group(2).strip()) if m else (s, None)

    joins = []
    for rel in ds.findall(".//relationships/relationship"):
        eq = rel.find("./expression[@op='=']")
        if eq is None:
            continue
        exprs = eq.findall("./expression")
        if len(exprs) < 2:
            continue
        lcol, ltab = parse_ref(exprs[0].get("op", ""))
        rcol, rtab = parse_ref(exprs[1].get("op", ""))
        if not (ltab and rtab):
            continue
        # MANY side = finer grain (more detail id columns). Orient left=MANY, right=ONE.
        la, ra = grain.get(ltab, 0), grain.get(rtab, 0)
        if ra > la:                       # right is finer → right is MANY → swap
            ltab, rtab, lcol, rcol = rtab, ltab, rcol, lcol
        joins.append({
            "type": "INNER",
            "left_table": ltab,           # MANY side
            "right_table": rtab,          # ONE side
            "keys": [{"left": lcol, "right": rcol}],
            "cardinality": "MANY_TO_ONE",
            "_source": "noodle",
        })
    return joins


def _extract_calculated_fields(ds: ET.Element) -> tuple[list[dict], dict[str, str]]:
    """Extract calculated fields + build calc_map from a datasource.

    Returns (calcs_list, calc_map).
    calcs_list: classification-format dicts for translate_formulas.
    calc_map: {[Calculation_NNN]: caption} for cross-reference resolution.
    """
    calcs = []
    calc_map = {}
    ds_name = ds.get("caption", ds.get("name", ""))

    for col in ds.findall("./column"):
        calc_el = col.find("calculation")
        if calc_el is None:
            continue
        name_raw = col.get("name", "")
        caption = col.get("caption", name_raw.strip("[]"))
        formula = calc_el.get("formula", "")
        if not formula:
            continue

        role = col.get("role", "measure")
        datatype = col.get("datatype", "string")

        internal = name_raw.strip("[]")
        calc_map[internal] = caption
        # Also store bracketed form for translate_formulas compatibility
        calc_map[f"[{internal}]"] = caption

        calcs.append({
            "name": internal if internal.startswith("Calculation_") else caption,
            "caption": caption,
            "formula": formula,
            "role": role,
            "datatype": datatype,
            "datasource": ds_name,
            "internal_name": internal,
        })
    return calcs, calc_map


def _build_column_table_map(ds: ET.Element, tables: list[dict]) -> dict[str, str]:
    """Build column→table map from datasource metadata-records.

    Also includes columns from <column> elements that have
    table-qualified names like [TABLE].[COL].
    """
    col_map: dict[str, str] = {}

    for local_name, rec in _metadata_column_records(ds).items():
        if rec.get("table"):
            col_map[local_name] = rec["table"]

    for col in ds.findall("./column"):
        name = col.get("name", "").strip("[]")
        if "." in name:
            parts = name.rsplit(".", 1)
            table = parts[0].strip("[]")
            column = parts[1].strip("[]")
            if table and column:
                col_map[column] = table

    return col_map


def _tableau_type_to_ts(datatype: str) -> str:
    _map = {
        "string": "VARCHAR",
        "integer": "INT64",
        "real": "DOUBLE",
        "boolean": "BOOL",
        "date": "DATE",
        "datetime": "DATE_TIME",
    }
    return _map.get(datatype, "VARCHAR")


def detect_orphan_calcs(datasource: dict) -> list[str]:
    """Return captions of calcs that reference a table not in this datasource
    (direct), plus calcs that transitively depend on a direct orphan."""
    ds_tables = {t["name"].upper() for t in datasource.get("tables", [])}
    calc_map = datasource.get("calc_map", {})
    calcs = datasource.get("calculated_fields", [])
    orphans: set[str] = set()

    for calc in calcs:
        for ref in re.findall(r"\[([^\]]+)::", calc.get("formula", "")):
            if ref.upper() not in ds_tables:
                orphans.add(calc["caption"])
                break

    changed = True
    while changed:
        changed = False
        for calc in calcs:
            if calc["caption"] in orphans:
                continue
            for internal in re.findall(r"\[Calculation_\d+\]", calc.get("formula", "")):
                ref_caption = calc_map.get(internal) or calc_map.get(internal.strip("[]"))
                if ref_caption in orphans:
                    orphans.add(calc["caption"])
                    changed = True
                    break
    return sorted(orphans)
