"""TWB/TWBX XML parsing: parameter extraction, and table/column/join/
calculated-field discovery from Tableau datasources.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any


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
    path = Path(twb_path)
    if path.suffix.lower() == ".twbx":
        with zipfile.ZipFile(path) as z:
            twb_name = next(n for n in z.namelist() if n.endswith(".twb"))
            root = ET.parse(z.open(twb_name)).getroot()
    else:
        root = ET.parse(str(path)).getroot()

    parameters = extract_parameters(root)
    param_map = build_param_name_map(root)
    param_names = {p["name"] for p in parameters}

    datasources = []
    seen_ds = set()

    for ds in root.findall(".//datasource"):
        ds_name = ds.get("caption", ds.get("name", ""))
        if ds_name == "Parameters":
            continue
        if not ds_name or ds_name in seen_ds:
            continue

        tables = _extract_tables(ds)
        if not tables:
            continue
        seen_ds.add(ds_name)

        columns = _extract_columns(ds, tables)
        joins = _extract_joins(ds)
        calcs, calc_map = _extract_calculated_fields(ds)
        col_table_map = _build_column_table_map(ds, tables)

        datasources.append({
            "name": ds_name,
            "tables": tables,
            "columns": columns,
            "joins": joins,
            "calculated_fields": calcs,
            "calc_map": calc_map,
            "col_table_map": col_table_map,
        })

    return {
        "datasources": datasources,
        "parameters": parameters,
        "param_map": param_map,
    }


def _strip_brackets(s: str) -> str:
    return s.replace("[", "").replace("]", "")


def _extract_tables(ds: ET.Element) -> list[dict]:
    """Extract physical table definitions from a datasource.

    Uses the relation ``name`` attribute as the table identity. When a TWB joins
    the same physical table twice, Tableau assigns a distinct ``name`` (e.g.
    ``d_partner1``) while keeping the same ``table`` path. We preserve that alias
    so downstream model TML can reference both table instances independently.
    """
    tables = []
    seen = set()
    for rel in ds.findall(".//relation[@type='table']"):
        rel_name = rel.get("name", "")
        tbl = rel.get("table", "")
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


def _extract_columns(ds: ET.Element, tables: list[dict]) -> list[dict]:
    """Extract physical column definitions from a datasource."""
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

        columns.append({
            "name": caption,
            "db_column_name": name,
            "column_type": column_type,
            "data_type": ts_type,
        })
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

    for col in ds.findall(".//metadata-record[@class='column']"):
        local_name = (col.findtext("local-name") or "").strip("[]")
        parent = (col.findtext("parent-name") or "").strip("[]")
        if local_name and parent:
            table = parent.split(".")[-1]
            col_map[local_name] = table

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
