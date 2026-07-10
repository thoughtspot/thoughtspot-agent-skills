"""Tableau TWB → ThoughtSpot Model TML builder.

Pure functions: parsed TWB data in, import-ready model TML out. No I/O — TWB/TWBX
XML parsing lives in ts_cli/tableau/twb.py (re-exported here for back-compat).

This module fills the gap between the formula translator (tableau_translate.py)
and the TML importer. The translator handles per-formula syntax; this module
handles model-level concerns:

  1. formula_ prefix for cross-references (delegates to ts_cli/formula_common.py)
  2. Double-aggregation detection (sum([formula_X]) where X is already aggregated;
     delegates to ts_cli/formula_common.py)
  3. sum(if...else 0) → sum_if simplification (re-applied post-assembly)
  4. Table-qualified column references (re-applied post-assembly)
  5. String concat + → concat() (re-applied post-assembly)
  6. Parameter extraction and ordering (params before formulas)
  7. Name collision resolution (column / formula / parameter; delegates to
     ts_cli/formula_common.py)
  8. Column/formula clash resolution (drop column, keep formula; delegates to
     ts_cli/formula_common.py)
"""
from __future__ import annotations

import re
from typing import Any

from ts_cli.tableau.dag import (  # noqa: F401 — re-exported for back-compat
    build_formula_levels,
    resolve_all_internal_refs,
)
from ts_cli.formula_common import (  # noqa: F401 — moved (BL-063 PR 5)
    add_formula_prefix,
    expr_is_aggregated,
    fix_double_aggregation,
    resolve_name_collisions,
)
from ts_cli.tableau.twb import (  # noqa: F401 — re-exported for back-compat
    _extract_joins,
    _extract_tables,
    _normalize_date_params,
    build_param_name_map,
    detect_orphan_calcs,
    extract_blends,
    extract_parameters,
    extract_table_calc_addressing,
    parse_twb,
)


# ---------------------------------------------------------------------------
# Model TML assembly
# ---------------------------------------------------------------------------

def _sql_view_model_tables(sql_views: list[dict]) -> list[dict]:
    """model_tables[] entries for SQL Views — referenced by name, columns listed."""
    return [
        {"name": sv["name"], "columns": [{"name": c["name"]} for c in sv.get("columns", [])]}
        for sv in sql_views
    ]


def _sql_view_model_columns(sql_views: list[dict]) -> list[dict]:
    """model.columns[] entries for SQL View columns (column_id = ``SQLViewName::col``)."""
    cols = []
    for sv in sql_views:
        for c in sv.get("columns", []):
            col_type = c.get("column_type", "ATTRIBUTE")
            entry: dict[str, Any] = {
                "name": c["name"],
                "column_id": f"{sv['name']}::{c['name']}",
                "properties": {"column_type": col_type},
            }
            if col_type == "MEASURE":
                entry["properties"]["aggregation"] = "SUM"
            cols.append(entry)
    return cols


def _drop_sql_view_shadowed_columns(columns: list[dict], sql_views: list[dict]) -> list[dict]:
    """Drop physical columns a SQL View already provides (by name). A Custom-SQL
    datasource's ``<column>`` elements ARE the view's columns, so emitting them as
    bare physical columns too would duplicate names (import-fatal)."""
    if not sql_views:
        return columns
    sv_names = {c["name"] for sv in sql_views for c in sv.get("columns", [])}
    return [c for c in columns if c.get("name") not in sv_names]


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
    sql_views: list[dict] | None = None,
) -> dict:
    """Assemble a complete ThoughtSpot model TML from parsed + translated data.

    Returns a TML dict ready for YAML serialization and import.
    Parameters are included; formulas have formula_ prefix applied and
    double-aggregation fixed.

    ``sql_views`` (from Custom SQL relations, see ``_extract_sql_views``) are
    referenced in ``model_tables[]`` by name and their columns added to
    ``model.columns[]``. They are NOT added to the connection-qualified ``tables:``
    list — a SQL View is a separate query-backed object (its own ``sql_view`` TML,
    imported before the model), not a physical warehouse table.
    """
    if formula_rename_map is None:
        formula_rename_map = {}
    if sql_views is None:
        sql_views = []

    formula_names = {f["name"] for f in translated_formulas}
    param_names = {p["name"] for p in parameters}

    formula_exprs = {f["name"]: f["expr"] for f in translated_formulas}

    model_tables = _build_model_tables(tables, columns, joins)
    model_tables.extend(_sql_view_model_tables(sql_views))

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

    # A SQL View owns its output columns; drop physical columns it already provides
    # (see _drop_sql_view_shadowed_columns), then append the SQL View columns.
    model_columns = _build_model_columns(
        _drop_sql_view_shadowed_columns(columns, sql_views), tables, translated_formulas)
    model_columns.extend(_sql_view_model_columns(sql_views))

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


def build_sql_view_tml(
    *,
    name: str,
    connection_name: str,
    sql_query: str,
    columns: list[dict],
) -> dict:
    """Assemble a SQL View TML dict from a Custom SQL relation spec.

    ``columns`` entries follow the parse shape from ``_extract_sql_views``:
    ``{name, sql_output_column, column_type, data_type}``. Emits the ``sql_view:``
    structure (see agents/shared/schemas/thoughtspot-sql-view-tml.md): ``connection.name``
    is required, ``sql_query`` holds the raw SQL, and each column carries
    ``sql_output_column`` + ``properties.column_type`` (MEASURE columns also get an
    aggregation). Returns a TML dict ready for YAML serialization and import.
    """
    sql_view_columns = []
    for c in columns:
        col_type = c.get("column_type", "ATTRIBUTE")
        entry: dict[str, Any] = {
            "name": c["name"],
            "sql_output_column": c["sql_output_column"],
            "data_type": c.get("data_type", "VARCHAR"),
            "properties": {"column_type": col_type},
        }
        if col_type == "MEASURE":
            entry["properties"]["aggregation"] = c.get("aggregation", "SUM")
        sql_view_columns.append(entry)

    return {
        "sql_view": {
            "name": name,
            "connection": {"name": connection_name},
            "sql_query": sql_query,
            "sql_view_columns": sql_view_columns,
        }
    }


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
    single_table = tables[0]["name"] if len(tables) == 1 else None

    for c in physical_columns:
        table = c.get("table") or single_table or ""
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
    col_table_map: dict[str, str] | None = None,
) -> str:
    """Table-qualify bare [COLUMN] refs and prefix [formula_NAME] cross-refs.

    After translation, some references remain bare (no ``::`` qualifier, no
    ``formula_`` prefix).  This pass resolves them:

    - ``[Name]`` where Name is a known formula → ``[formula_Name]``
    - ``[COL]`` where COL (case-insensitive) is a physical column → ``[table::COL]``
    - Parameter refs and already-qualified refs are left unchanged.

    column_lookup maps upper-cased column name → canonical db_column_name.

    col_table_map (optional) maps upper-cased column name → a fully-qualified
    ``TABLE::col`` id, for the multi-table case where a bare column does not
    belong to ``table_name`` (the anchor). When a ref resolves here it is
    qualified to its real owning table; otherwise the single-table
    ``table_name`` fallback applies. Only columns whose base name is
    unambiguous across the model's tables belong in this map — ambiguous
    (shared) columns are deliberately omitted so they fall back to the anchor.
    """
    import re

    ctm = col_table_map or {}

    def _replace(m: re.Match) -> str:
        ref = m.group(1)
        if "::" in ref or ref.startswith("formula_"):
            return m.group(0)
        if ref in parameter_names:
            return m.group(0)
        if ref in formula_names:
            return f"[formula_{ref}]"
        if ref.upper() in ctm:
            return f"[{ctm[ref.upper()]}]"
        if ref.upper() in column_lookup:
            return f"[{table_name}::{column_lookup[ref.upper()]}]"
        return m.group(0)

    return re.sub(r"\[([^\]]+)\]", _replace, expr)


def build_col_table_map(
    model_tml: dict, anchor_table: str | None = None
) -> dict[str, str]:
    """Map upper(name) → ``TABLE::col``, choosing the owning table per column.

    For a multi-table model, ``fix_bare_refs`` needs to know which table a
    bare column belongs to — the anchor-only fallback mis-qualifies columns
    that live in a joined table (e.g. ``PERIOD_TYPE`` on a metrics table gets
    wrongly prefixed with the promotion-master anchor).

    Ownership rules per column base name (the ``::`` suffix):

    - Owned by exactly ONE table → qualify to that table.
    - Owned by two or more tables (shared join keys / repeated attributes):
      qualify to the ``anchor_table`` if it is one of the owners (a shared
      column resolves to the same value on either side of the join, and the
      anchor is the safe default); otherwise qualify to the first owner in
      model-column order. This last case is what rescues a column like
      ``CUSTOMER_ID`` that is shared by two *joined* tables but absent from the
      anchor — qualifying it to the anchor would fail at import.

    Both the column_id suffix and the display name are indexed so either
    reference form resolves.
    """
    homes: dict[str, list[str]] = {}
    disp: dict[str, str] = {}
    for c in model_tml.get("model", {}).get("columns", []):
        cid = c.get("column_id", "")
        if "::" not in cid:
            continue
        _, col = cid.split("::", 1)
        homes.setdefault(col.upper(), []).append(cid)
        disp[cid] = c.get("name", col)

    lookup: dict[str, str] = {}
    for col_upper, ids in homes.items():
        if len(ids) == 1:
            chosen = ids[0]
        else:
            # ambiguous — prefer the anchor when it owns the column, else the
            # first owner in model-column order.
            chosen = next(
                (i for i in ids if i.split("::", 1)[0] == anchor_table), ids[0]
            )
        lookup[col_upper] = chosen
        name = disp.get(chosen, "")
        if name:
            lookup[name.upper()] = chosen
    return lookup


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

    Catches, deterministically (no import round-trips), the failure classes
    that otherwise get peeled off one-per-cycle by the import-retry loop:

    - ``sqlproxy::`` table references (published datasource artifact)
    - Bare ``(Custom SQL Query N)`` refs (unmapped CSQ artifact). A QUALIFIED
      ``[SQL View::col]`` ref is NOT dropped — Custom SQL is emitted as a SQL View,
      so it resolves via the ``::``-in-``col_upper`` check when the column exists.
    - Bare column names that match physical columns but lack table qualifiers
    - Unresolvable bare references (not a column, formula, or parameter)
    - ``+`` string concatenation that wasn't converted to ``concat()``
    - **Qualified ``[TABLE::COL]`` refs whose column does not exist in the
      model** (e.g. a formula that references ``REVENUE_FORECAST`` when no
      table provides it). Previously these passed the filter and failed at
      import.
    - **Transitive cascade** — a formula that references ``[formula_X]`` where
      ``X`` was itself dropped. Computed to a fixpoint here rather than
      discovered one import round-trip at a time.

    ``model_column_names`` is the set of physical column base names (the part
    after ``::``) that exist across the model's tables.

    Returns (kept, dropped_names).
    """
    col_upper = {c.upper() for c in model_column_names}
    formula_upper = {n.upper() for n in formula_names}
    param_upper = {n.upper() for n in parameter_names}

    kept: list[dict] = []
    dropped: list[str] = []
    for f in formulas:
        if f.get("id") in existing_formula_ids:
            kept.append(f)
            continue
        if _formula_is_unresolvable(
            f.get("expr", ""), col_upper, formula_names, parameter_names,
            formula_upper, param_upper,
        ):
            dropped.append(f.get("name", f.get("id", "?")))
        else:
            kept.append(f)

    return _cascade_drop_dependents(kept, dropped)


def _formula_is_unresolvable(
    expr: str,
    col_upper: set[str],
    formula_names: set[str],
    parameter_names: set[str],
    formula_upper: set[str],
    param_upper: set[str],
) -> bool:
    """True if a formula expr has a reference that won't resolve at import."""
    import re
    low = expr.lower()
    # sqlproxy:: = published-datasource artifact (not resolvable here).
    # NOTE: "custom sql query" is intentionally NOT blanket-dropped — Custom SQL is
    # now emitted as a SQL View (build_sql_view_tml), so a QUALIFIED ref like
    # [Custom SQL Query::VIEWS] resolves via the ::-in-col_upper check below when the
    # SQL View column exists. A BARE Tableau CSQ ref (e.g. [COL (Custom SQL Query6)])
    # still fails the bare-ref fallback and is dropped.
    if "sqlproxy::" in low:
        return True
    # + between a string literal and a ref (unconverted string concat)
    if re.search(r"'\s*\+\s*\[", expr) or re.search(r"\]\s*\+\s*'", expr):
        return True
    # Strip string literals first so a '[' inside a literal isn't read as a ref.
    expr_no_strings = re.sub(r"'[^']*'", "", expr)
    for ref in re.findall(r"\[([^\]]+)\]", expr_no_strings):
        if ref.startswith("formula_"):
            continue  # cross-formula ref — validated in the cascade pass
        if "::" in ref:
            # qualified column ref — column must exist in the model
            if ref.split("::", 1)[1].upper() not in col_upper:
                return True
            continue
        if ref in parameter_names or ref in formula_names:
            continue
        if ref.upper() in param_upper or ref.upper() in formula_upper:
            continue
        return True  # bare, unknown ref
    return False


def _cascade_drop_dependents(
    kept: list[dict], dropped: list[str]
) -> tuple[list[dict], list[str]]:
    """Drop any kept formula referencing [formula_X] where X was dropped.

    Iterates to a fixpoint. Only dropped formulas trigger this — a ref to a
    pre-existing model formula (not in our new set) is fine.
    """
    import re
    dropped_set = set(dropped)
    changed = True
    while changed:
        changed = False
        survivors: list[dict] = []
        for f in kept:
            refs = re.findall(r"\[formula_([^\]]+)\]", f.get("expr", ""))
            if any(r in dropped_set for r in refs):
                nm = f.get("name", f.get("id", "?"))
                dropped.append(nm)
                dropped_set.add(nm)
                changed = True
            else:
                survivors.append(f)
        kept = survivors
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


# ---------------------------------------------------------------------------
# Re-exports
# ---------------------------------------------------------------------------
#
# ts_cli.tableau.build_model imports add_formula_prefix / build_column_lookup /
# fix_bare_refs / fix_double_aggregation from THIS module at its own import
# time, so a plain top-level `from ts_cli.tableau.build_model import
# build_blend_plan` here creates a genuine two-way circular import (whichever
# module starts loading first hits the other one mid-initialization, before
# the needed name is defined). A PEP 562 module `__getattr__` defers the
# cross-import until first attribute access, by which point both modules
# have finished loading regardless of which one was imported first.

def __getattr__(name: str):
    if name == "build_blend_plan":
        from ts_cli.tableau.build_model import build_blend_plan
        return build_blend_plan
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
