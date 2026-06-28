"""Tableau TWB → ThoughtSpot Model TML builder.

Pure functions: TWB XML in, import-ready model TML out.
No I/O beyond the initial XML parse — trivially unit-testable.

This module fills the gap between the formula translator (tableau_translate.py)
and the TML importer. The translator handles per-formula syntax; this module
handles model-level concerns:

  1. formula_ prefix for cross-references
  2. Double-aggregation detection (sum([formula_X]) where X is already aggregated)
  3. sum(if...else 0) → sum_if simplification (re-applied post-assembly)
  4. Table-qualified column references (re-applied post-assembly)
  5. String concat + → concat() (re-applied post-assembly)
  6. Parameter extraction and ordering (params before formulas)
  7. Name collision resolution (column / formula / parameter)
  8. Column/formula clash resolution (drop column, keep formula)
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# 1. Formula cross-reference prefix
# ---------------------------------------------------------------------------

def add_formula_prefix(
    expr: str,
    formula_names: set[str],
    parameter_names: set[str],
) -> str:
    """Rewrite [Name] → [formula_Name] for formula cross-references.

    Skips table-qualified refs ([TABLE::COL]), parameter refs, and refs
    that already have the formula_ prefix.
    """
    def _replace(m: re.Match) -> str:
        ref = m.group(1)
        if "::" in ref:
            return m.group(0)
        if ref in parameter_names:
            return m.group(0)
        if ref.startswith("formula_"):
            return m.group(0)
        if ref in formula_names:
            return f"[formula_{ref}]"
        return m.group(0)

    return re.sub(r"\[([^\]]+)\]", _replace, expr)


# ---------------------------------------------------------------------------
# 2. Double-aggregation detection
# ---------------------------------------------------------------------------

_AGG_FUNCTIONS = re.compile(
    r"\b(sum|average|count|unique\s+count|max|min|sum_if|count_if|average_if|"
    r"unique_count_if|cumulative_sum|cumulative_average|cumulative_max|"
    r"cumulative_min|stddev|variance|moving_sum|moving_average|moving_max|"
    r"moving_min|group_aggregate)\s*\(",
    re.IGNORECASE,
)


def expr_is_aggregated(expr: str) -> bool:
    """Check if an expression contains aggregation functions."""
    return bool(_AGG_FUNCTIONS.search(expr))


def fix_double_aggregation(
    expr: str,
    formula_exprs: dict[str, str],
) -> str:
    """Replace sum([formula_X]) with [formula_X] when X is already aggregated.

    Handles sum, count, average, max, min and their _if variants.
    """
    _WRAPPED_REF = re.compile(
        r"\b(sum|average|count|max|min)\s*\(\s*\[formula_([^\]]+)\]\s*\)",
        re.IGNORECASE,
    )

    def _replace(m: re.Match) -> str:
        ref_name = m.group(2)
        ref_expr = formula_exprs.get(ref_name, "")
        if expr_is_aggregated(ref_expr):
            return f"[formula_{ref_name}]"
        return m.group(0)

    return _WRAPPED_REF.sub(_replace, expr)


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
# 7 & 8. Name collision resolution
# ---------------------------------------------------------------------------

def resolve_name_collisions(
    columns: list[dict],
    formulas: list[dict],
    parameters: list[dict],
) -> tuple[list[dict], list[dict], dict[str, str]]:
    """Detect and resolve name collisions between columns, formulas, parameters.

    Rules:
      - If a formula name matches a parameter name, rename the formula
        (append " Selection" suffix)
      - If a column name matches a formula name, drop the column (keep formula)
      - Returns (cleaned_columns, renamed_formulas, rename_map)

    rename_map: {old_name: new_name} for formulas that were renamed.
    """
    param_names = {p["name"] for p in parameters}
    formula_names = {f["name"] for f in formulas}

    rename_map: dict[str, str] = {}
    for f in formulas:
        if f["name"] in param_names:
            new_name = f["name"] + " Selection"
            rename_map[f["name"]] = new_name
            f["name"] = new_name

    new_formula_names = {f["name"] for f in formulas}
    cleaned_columns = [
        c for c in columns
        if c["name"] not in new_formula_names
    ]
    dropped = len(columns) - len(cleaned_columns)

    return cleaned_columns, formulas, rename_map


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


# ---------------------------------------------------------------------------
# Dependency level computation (must run BEFORE resolve_all_internal_refs)
# ---------------------------------------------------------------------------

def build_formula_levels(
    calcs: list[dict],
    calc_map: dict[str, str],
) -> dict[str, int]:
    """Build dependency levels from raw (pre-resolved) calculated fields.

    Must be called BEFORE resolve_all_internal_refs — it relies on the
    original [Calculation_NNN] and copy-style [Field (copy)_NNN] refs
    still being present in the formula text.

    Matches ALL bracketed refs against the calc_map to detect dependencies,
    unlike build_dependency_dag which only matches [Calculation_\\d+].
    """
    all_captions = {c.get("caption", "") for c in calcs if c.get("caption")}

    bracket_to_caption: dict[str, str] = {}
    for key, caption in calc_map.items():
        bracketed = f"[{key}]" if not key.startswith("[") else key
        bracket_to_caption[bracketed] = caption

    caption_deps: dict[str, set[str]] = {}
    for c in calcs:
        caption = c.get("caption", "")
        formula = c.get("formula", "")
        deps: set[str] = set()
        for ref in re.findall(r"\[[^\]]+\]", formula):
            dep_caption = bracket_to_caption.get(ref)
            if dep_caption and dep_caption != caption and dep_caption in all_captions:
                deps.add(dep_caption)
        caption_deps[caption] = deps

    levels: dict[str, int] = {}
    changed = True
    while changed:
        changed = False
        for caption, deps in caption_deps.items():
            if caption in levels:
                continue
            if not deps:
                levels[caption] = 0
                changed = True
            elif all(d in levels for d in deps):
                max_dep = max(levels[d] for d in deps)
                levels[caption] = max_dep + 1
                changed = True

    for caption in caption_deps:
        if caption not in levels:
            levels[caption] = 0

    return levels


# ---------------------------------------------------------------------------
# Pre-translation: resolve ALL internal references to display names
# ---------------------------------------------------------------------------

def resolve_all_internal_refs(
    calcs: list[dict],
    calc_map: dict[str, str],
) -> list[dict]:
    """Replace ALL internal refs ([Calculation_NNN] and copy-style) with captions.

    Tableau TWBs use two reference styles:
      [Calculation_1234567890] — original calc field
      [Field Name (copy)_1234567890] — copied from another datasource

    The existing translate pipeline only resolves [Calculation_NNN].
    This function resolves BOTH by substituting any bracketed reference
    that matches a calc_map key with the corresponding caption.

    Returns a new list of calcs with resolved formulas (caption field).
    """
    bracket_map = {}
    for internal, caption in calc_map.items():
        bracket_map[f"[{internal}]"] = f"[{caption}]"

    resolved = []
    for c in calcs:
        formula = c.get("formula", "")
        for internal_ref, caption_ref in bracket_map.items():
            if internal_ref in formula:
                formula = formula.replace(internal_ref, caption_ref)
        entry = dict(c)
        entry["formula"] = formula
        resolved.append(entry)
    return resolved


# ---------------------------------------------------------------------------
# Model TML assembly
# ---------------------------------------------------------------------------

def build_model_tml(
    *,
    model_name: str,
    connection_name: str,
    tables: list[dict],
    columns: list[dict],
    joins: list[dict],
    parameters: list[dict],
    translated_formulas: list[dict],
    formula_rename_map: dict[str, str] | None = None,
) -> dict:
    """Assemble a complete ThoughtSpot model TML from parsed + translated data.

    Returns a TML dict ready for YAML serialization and import.
    Parameters are included; formulas have formula_ prefix applied and
    double-aggregation fixed.
    """
    if formula_rename_map is None:
        formula_rename_map = {}

    formula_names = {f["name"] for f in translated_formulas}
    param_names = {p["name"] for p in parameters}

    formula_exprs = {f["name"]: f["expr"] for f in translated_formulas}

    model_tables = _build_model_tables(tables, columns, joins)

    model_formulas = []
    for f in translated_formulas:
        expr = f["expr"]
        expr = add_formula_prefix(expr, formula_names, param_names)
        expr = fix_double_aggregation(expr, formula_exprs)
        model_formulas.append({
            "name": f["name"],
            "id": f"formula_{f['name']}",
            "expr": expr,
        })

    model_columns = _build_model_columns(columns, tables, translated_formulas)

    model_params = _build_model_parameters(parameters)

    tml: dict[str, Any] = {
        "model": {
            "name": model_name,
            "tables": [
                {
                    "name": t["name"],
                    "fqn": f"[{connection_name}].[{t.get('db_table', t['name'])}]" if connection_name else t["name"],
                }
                for t in tables
            ],
            "model_tables": model_tables,
            "formulas": model_formulas,
            "parameters": model_params,
            "columns": model_columns,
        }
    }
    return tml


def _build_model_tables(
    tables: list[dict],
    columns: list[dict],
    joins: list[dict],
) -> list[dict]:
    """Build model_tables[] entries with columns and joins."""
    model_tables = []
    table_names = {t["name"] for t in tables}

    for t in tables:
        mt: dict[str, Any] = {"name": t["name"]}

        table_cols = [
            c for c in columns
            if c.get("table", t["name"]) == t["name"]
        ]
        if table_cols:
            mt["columns"] = [
                {"name": c["db_column_name"]}
                for c in table_cols
            ]

        table_joins = [
            j for j in joins
            if j.get("left_table") == t["name"] or j.get("right_table") == t["name"]
        ]
        if table_joins:
            mt["joins"] = []
            for j in table_joins:
                other = j["right_table"] if j["left_table"] == t["name"] else j["left_table"]
                if other in table_names:
                    mt["joins"].append({
                        "with": other,
                        "type": j["type"],
                        "on": " AND ".join(
                            f"[{t['name']}::{k['left']}] = [{other}::{k['right']}]"
                            for k in j["keys"]
                        ),
                    })

        model_tables.append(mt)
    return model_tables


def _build_model_columns(
    physical_columns: list[dict],
    tables: list[dict],
    formulas: list[dict],
) -> list[dict]:
    """Build the columns[] array for the model TML.

    Includes both physical columns (with column_id TABLE::COL) and
    formula columns (with formula_id).
    """
    model_cols = []

    for c in physical_columns:
        table = c.get("table", "")
        col_name = c.get("db_column_name", c["name"])
        entry: dict[str, Any] = {
            "name": c["name"],
            "column_id": f"{table}::{col_name}" if table else col_name,
            "properties": {
                "column_type": c.get("column_type", "ATTRIBUTE"),
            },
        }
        if c.get("column_type") == "MEASURE":
            entry["properties"]["aggregation"] = "SUM"
        model_cols.append(entry)

    for f in formulas:
        entry = {
            "name": f["name"],
            "formula_id": f"formula_{f['name']}",
            "properties": {
                "column_type": f.get("column_type", "MEASURE"),
            },
        }
        if f.get("column_type") == "MEASURE":
            entry["properties"]["aggregation"] = "SUM"
        model_cols.append(entry)

    return model_cols


def _build_model_parameters(parameters: list[dict]) -> list[dict]:
    """Build the parameters[] array for the model TML."""
    model_params = []
    for p in parameters:
        entry: dict[str, Any] = {
            "name": p["name"],
            "default_value": p.get("default_value", ""),
            "data_type": p.get("data_type", "CHAR"),
        }
        if "list_config" in p:
            entry["data_type"] = "CHAR"
            entry["list_config"] = p["list_config"]
        if "range_config" in p:
            entry["range_config"] = p["range_config"]
        model_params.append(entry)
    return model_params


# ---------------------------------------------------------------------------
# Merge formulas into an existing model
# ---------------------------------------------------------------------------

def merge_formulas_into_model(
    existing_tml: dict,
    translated_formulas: list[dict],
    formula_levels: dict[str, int] | None = None,
    update_existing: bool = False,
) -> dict:
    """Merge translated formulas into an existing model TML for GUID-pinned update.

    For each translated formula:
    - If it matches an existing formula (by formula_id) and ``update_existing``
      is True, update the expression.  Default is False — existing expressions
      are kept as-is because they already have correct table-qualified column
      references that the translator may not reproduce.
    - If it's new, add the formula and its column entry (skipping names that
      collide case-insensitively with existing columns).

    Returns the merged model TML dict ready for import.
    """
    import copy
    merged = copy.deepcopy(existing_tml)
    model = merged["model"]

    if "formulas" not in model:
        model["formulas"] = []
    if "columns" not in model:
        model["columns"] = []
    existing_formulas = {f["id"]: f for f in model["formulas"]}
    existing_col_names_lower = {
        c["name"].lower() for c in model["columns"]
    }

    updated = 0
    skipped_existing = 0
    added = 0
    added_names: list[str] = []
    skipped_collisions: list[str] = []
    for tf in translated_formulas:
        fid = tf["id"]
        if fid in existing_formulas:
            if update_existing:
                existing_formulas[fid]["expr"] = tf["expr"]
                if "name" in tf:
                    existing_formulas[fid]["name"] = tf["name"]
                updated += 1
            else:
                skipped_existing += 1
        else:
            if tf["name"].lower() in existing_col_names_lower:
                skipped_collisions.append(tf["name"])
                continue
            model["formulas"].append(tf)
            col_entry = {
                "name": tf["name"],
                "formula_id": fid,
                "properties": {
                    "column_type": tf.get("column_type", "MEASURE"),
                },
            }
            if tf.get("column_type") == "MEASURE":
                col_entry["properties"]["aggregation"] = "SUM"
            model["columns"].append(col_entry)
            existing_col_names_lower.add(tf["name"].lower())
            added += 1
            added_names.append(tf["name"])

    merged["_merge_stats"] = {
        "updated": updated,
        "skipped_existing": skipped_existing,
        "added": added,
        "added_names": added_names,
        "skipped_collisions": skipped_collisions,
        "existing_total": len(existing_formulas),
    }
    return merged


# ---------------------------------------------------------------------------
# Post-translation bare-reference fix
# ---------------------------------------------------------------------------

def fix_bare_refs(
    expr: str,
    formula_names: set[str],
    parameter_names: set[str],
    column_lookup: dict[str, str],
    table_name: str,
) -> str:
    """Table-qualify bare [COLUMN] refs and prefix [formula_NAME] cross-refs.

    After translation, some references remain bare (no ``::`` qualifier, no
    ``formula_`` prefix).  This pass resolves them:

    - ``[Name]`` where Name is a known formula → ``[formula_Name]``
    - ``[COL]`` where COL (case-insensitive) is a physical column → ``[table::COL]``
    - Parameter refs and already-qualified refs are left unchanged.

    column_lookup maps upper-cased column name → canonical db_column_name.
    """
    import re

    def _replace(m: re.Match) -> str:
        ref = m.group(1)
        if "::" in ref or ref.startswith("formula_"):
            return m.group(0)
        if ref in parameter_names:
            return m.group(0)
        if ref in formula_names:
            return f"[formula_{ref}]"
        if ref.upper() in column_lookup:
            return f"[{table_name}::{column_lookup[ref.upper()]}]"
        return m.group(0)

    return re.sub(r"\[([^\]]+)\]", _replace, expr)


def build_column_lookup(model_tml: dict) -> dict[str, str]:
    """Build upper(name) → db_column_name map from a model's columns.

    Indexes by both the display name and the column_id suffix so either
    form resolves.
    """
    lookup: dict[str, str] = {}
    for c in model_tml.get("model", {}).get("columns", []):
        cid = c.get("column_id", "")
        if "::" in cid:
            _, col = cid.split("::", 1)
            lookup[col.upper()] = col
            lookup[c["name"].upper()] = col
    return lookup


# ---------------------------------------------------------------------------
# Pre-merge filtering
# ---------------------------------------------------------------------------

def filter_unresolvable_formulas(
    formulas: list[dict],
    existing_formula_ids: set[str],
    model_column_names: set[str],
    formula_names: set[str],
    parameter_names: set[str],
) -> tuple[list[str], list[dict]]:
    """Drop new formulas with references that won't resolve in ThoughtSpot.

    Checks for:
    - ``sqlproxy::`` table references (published datasource artifact)
    - ``Custom SQL Query`` references (unmapped CSQ)
    - Bare column names that match physical columns but lack table qualifiers
    - Unresolvable bare references (not a column, formula, or parameter)
    - ``+`` string concatenation that wasn't converted to ``concat()``

    Returns (kept, dropped_names).
    """
    import re
    kept: list[dict] = []
    dropped: list[str] = []
    col_upper = {c.upper() for c in model_column_names}
    formula_upper = {n.upper() for n in formula_names}
    param_upper = {n.upper() for n in parameter_names}

    for f in formulas:
        if f.get("id") in existing_formula_ids:
            kept.append(f)
            continue
        expr = f.get("expr", "")
        if "sqlproxy::" in expr.lower():
            dropped.append(f.get("name", f.get("id", "?")))
            continue
        if "custom sql query" in expr.lower():
            dropped.append(f.get("name", f.get("id", "?")))
            continue
        # + between string literal and ref (unconverted string concat)
        if re.search(r"'\s*\+\s*\[", expr) or re.search(r"\]\s*\+\s*'", expr):
            dropped.append(f.get("name", f.get("id", "?")))
            continue
        # Bare references — unscoped physical columns or unknown names
        # Strip string literals before extracting refs to avoid false
        # positives from brackets inside strings like concat('[', ...)
        expr_no_strings = re.sub(r"'[^']*'", "", expr)
        has_bad_ref = False
        for ref in re.findall(r"\[([^\]]+)\]", expr_no_strings):
            if "::" in ref:
                continue
            if ref.startswith("formula_"):
                continue
            if ref in parameter_names or ref in formula_names:
                continue
            if ref.upper() in param_upper or ref.upper() in formula_upper:
                continue
            has_bad_ref = True
            break
        if has_bad_ref:
            dropped.append(f.get("name", f.get("id", "?")))
            continue
        kept.append(f)

    return kept, dropped


# ---------------------------------------------------------------------------
# Phased import splitting
# ---------------------------------------------------------------------------

def split_for_phased_import(
    model_tml: dict,
    formula_levels: dict[str, int] | None = None,
) -> list[dict]:
    """Split a model TML into phases for multi-pass import.

    Phase 0: tables + columns + joins + parameters (no formulas)
    Phase 1: level-0 formulas (no cross-references)
    Phase 2+: level-1+ formulas (reference earlier levels)

    Each phase is a complete model TML dict with guid field for update.
    """
    base = {k: v for k, v in model_tml.items() if k != "model"}
    model = model_tml["model"]

    if formula_levels is None:
        formula_levels = {f["name"]: 0 for f in model.get("formulas", [])}

    max_level = max(formula_levels.values(), default=0)
    formula_by_name = {f["name"]: f for f in model.get("formulas", [])}
    column_formula_names = {
        c["name"] for c in model.get("columns", [])
        if "formula_id" in c
    }

    phases = []

    phase0_model = dict(model)
    phase0_model["formulas"] = []
    phase0_model["columns"] = [
        c for c in model.get("columns", [])
        if "formula_id" not in c
    ]
    phase0 = dict(base)
    phase0["model"] = phase0_model
    phases.append(phase0)

    cumulative_formulas: list[dict] = []
    cumulative_formula_cols: list[dict] = []

    for level in range(0, max_level + 1):
        level_names = {
            name for name, lvl in formula_levels.items()
            if lvl == level
        }
        level_formulas = [
            formula_by_name[n] for n in level_names
            if n in formula_by_name
        ]
        level_cols = [
            c for c in model.get("columns", [])
            if c.get("name") in level_names and "formula_id" in c
        ]

        cumulative_formulas.extend(level_formulas)
        cumulative_formula_cols.extend(level_cols)

        phase_model = dict(model)
        phase_model["formulas"] = list(cumulative_formulas)
        phase_model["columns"] = [
            c for c in model.get("columns", [])
            if "formula_id" not in c
        ] + list(cumulative_formula_cols)

        phase = dict(base)
        phase["model"] = phase_model
        phases.append(phase)

    return phases
