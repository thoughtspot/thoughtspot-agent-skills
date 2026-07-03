"""Tableau TWB → ThoughtSpot Model TML builder.

Pure functions: parsed TWB data in, import-ready model TML out. No I/O — TWB/TWBX
XML parsing lives in ts_cli/tableau/twb.py (re-exported here for back-compat).

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
from typing import Any

from ts_cli.tableau.dag import (  # noqa: F401 — re-exported for back-compat
    build_formula_levels,
    resolve_all_internal_refs,
)
from ts_cli.tableau.naming import resolve_name_collisions  # noqa: F401
from ts_cli.tableau.twb import (  # noqa: F401 — re-exported for back-compat
    _extract_joins,
    _extract_tables,
    _normalize_date_params,
    build_param_name_map,
    extract_parameters,
    parse_twb,
)


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
) -> tuple[list[dict], list[str]]:
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
