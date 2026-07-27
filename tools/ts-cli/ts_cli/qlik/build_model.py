"""Build ThoughtSpot Table + Model TML (and a mapping report) from the Qlik IR.

Pure functions — return dicts/strings, never write files (the ``ts qlik
build-model`` command does the I/O). Honours the critical TML invariants in the
repo CLAUDE.md:

  * every table column carries ``db_column_name`` (even when equal to ``name``)
  * a table's ``connection:`` block uses ``name:`` only — never ``fqn:``
  * formula columns get a ``columns[]`` entry with ``formula_id:`` matching the
    ``formulas[].id`` (delegated to ``model_builder.build_model_tml``)
  * ``aggregation:`` lives in ``columns[]`` entries only

Formula translation (``functions.translate``) is flag-don't-downgrade: an
expression that can't be faithfully translated is recorded in ``mapping.json``
with status ``NEEDS REVIEW`` and the ORIGINAL Qlik expression kept, never a
plausible-but-wrong substitute (repo "Flag, don't downgrade" convention).
"""

from __future__ import annotations

import re
from typing import Any, Optional

from ts_cli.model_builder import build_model_tml

from . import functions
from .ir import QlikApp, Table

# Qlik field/expr type hints -> ThoughtSpot db_column_properties.data_type.
_TYPE_MAP = {
    "integer": "INT64", "int": "INT64", "num": "DOUBLE", "number": "DOUBLE",
    "double": "DOUBLE", "real": "DOUBLE", "money": "DOUBLE",
    "text": "VARCHAR", "string": "VARCHAR", "ascii": "VARCHAR",
    "date": "DATE", "timestamp": "DATE_TIME", "time": "TIME",
    "bool": "BOOL", "boolean": "BOOL",
}

_STATUS_OK = "OK"
_STATUS_REVIEW = "NEEDS REVIEW"


def build_model_artifacts(
    app: QlikApp,
    *,
    connection_name: str,
    db: str,
    schema: str,
    model_name: Optional[str] = None,
    type_overrides: Optional[dict] = None,
) -> dict[str, Any]:
    """Assemble Table TML(s) + Model TML + a mapping report from a QlikApp.

    Returns::

        {
          "tables":  {filename: table_tml_dict, ...},
          "model":   {"filename": str, "tml": model_tml_dict},
          "mapping": {...},        # measures/variables/renames + NEEDS REVIEW
          "counts":  {...},
        }

    All values are plain dicts; the caller serializes with
    ``ts_cli.tml_common.dump_tml_yaml`` and writes them out.
    """
    model_name = model_name or app.app_name
    warnings: list[str] = []

    # -- Table TMLs (one per IR table) -------------------------------------
    table_docs, table_specs = _build_table_docs(
        app, connection_name, db, schema, type_overrides, warnings)

    # -- Model columns (physical), de-duplicated for unique display names --
    model_columns, col_renames = _model_physical_columns(app.tables)
    for r in col_renames:
        warnings.append(
            f"Duplicate column '{r['from']}' renamed to '{r['to']}' to keep "
            "model column display names unique."
        )

    # -- Measures -> formulas (flag-don't-downgrade) -----------------------
    formulas, measure_map = _translate_measures(app.measures)

    # Drop a physical column whose display name collides with a formula name
    # (the measure wins), so the model never has two columns with one name.
    formula_names = {f["name"] for f in formulas}
    model_columns = [c for c in model_columns if c["name"] not in formula_names]

    model_doc = build_model_tml(
        model_name=model_name,
        connection_name=connection_name,
        tables=table_specs,
        columns=model_columns,
        joins=[],                       # offline IR has no reliable join graph
        parameters=[],                  # Qlik variables are never auto-mapped
        translated_formulas=formulas,
    )

    variable_map = _build_variable_map(app.variables)
    if app.variables:
        warnings.append(
            f"{len(app.variables)} Qlik variable(s) not auto-mapped — see mapping.json."
        )

    # Carry the extractor's own manual/warning notes into the mapping report.
    for n in app.notes:
        if n.severity in ("manual", "warning"):
            warnings.append(f"[{n.area}] {n.message}")

    counts = _build_counts(table_docs, model_columns, formulas, measure_map, variable_map)

    mapping = {
        "model": model_name,
        "connection": connection_name,
        "measures": measure_map,
        "variables": variable_map,
        "columns_renamed": col_renames,
        "warnings": warnings,
        "counts": counts,
    }

    return {
        "tables": table_docs,
        "model": {"filename": f"model.{_slug(model_name)}.tml", "tml": model_doc},
        "mapping": mapping,
        "counts": counts,
    }


def _build_table_docs(
    app: QlikApp,
    connection_name: str,
    db: str,
    schema: str,
    type_overrides: Optional[dict],
    warnings: list[str],
) -> tuple[dict[str, dict], list[dict]]:
    """Build one Table TML per IR table; append any recovery warnings in place."""
    table_docs: dict[str, dict] = {}
    table_specs: list[dict] = []
    for tbl in app.tables:
        conn = tbl.source_connection or connection_name
        doc, _col_types = _build_table_tml_dict(
            tbl, conn, db=tbl.db_name or db, schema=tbl.schema_name or schema,
            type_overrides=type_overrides,
        )
        table_docs[f"table.{_slug(tbl.name)}.tml"] = doc
        table_specs.append({"name": tbl.name, "db_table": tbl.name})
        if not tbl.columns:
            warnings.append(f"Table '{tbl.name}' has no columns recovered.")

    if not app.tables:
        warnings.append(
            "No tables in the IR; cannot build a Model. Recover tables via "
            "--mode engine-artifacts or hand-edit the IR (--overrides)."
        )
    return table_docs, table_specs


def _build_variable_map(variables) -> list[dict]:
    """One NEEDS REVIEW mapping-report entry per Qlik variable (never auto-mapped)."""
    return [
        {"name": v.name, "definition": v.definition, "status": _STATUS_REVIEW,
         "reason": "Qlik variable not auto-mapped; recreate as a model formula or "
                   "parameter if needed."}
        for v in variables
    ]


def _build_counts(
    table_docs: dict,
    model_columns: list[dict],
    formulas: list[dict],
    measure_map: list[dict],
    variable_map: list[dict],
) -> dict[str, int]:
    measures_review = sum(1 for m in measure_map if m["status"] == _STATUS_REVIEW)
    return {
        "tables": len(table_docs),
        "model_columns": len(model_columns) + len(formulas),
        "measures": len(measure_map),
        "measures_needs_review": measures_review,
        "variables_needs_review": len(variable_map),
        "needs_review_total": measures_review + len(variable_map),
    }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _build_table_tml_dict(
    tbl: Table,
    connection_name: str,
    *,
    db: str,
    schema: str,
    type_overrides: Optional[dict] = None,
) -> tuple[dict, dict]:
    """Return (table_tml_dict, {col_name: ts_type}) for one IR table.

    Every column carries ``db_column_name`` and the connection block uses
    ``name:`` only (TML invariants).
    """
    columns = []
    col_types: dict[str, str] = {}
    for col in tbl.columns:
        ts_type = _lookup_type(type_overrides, tbl.name, col.name) or _map_type(col.data_type)
        col_types[col.name] = ts_type
        columns.append({
            "name": col.name,
            "db_column_name": col.name,
            "properties": {"column_type": "ATTRIBUTE"},
            "db_column_properties": {"data_type": ts_type},
        })
    doc = {
        "table": {
            "name": tbl.name,
            "db": db,
            "schema": schema,
            "db_table": tbl.name,
            "connection": {"name": connection_name},
            "columns": columns,
        }
    }
    return doc, col_types


def _model_physical_columns(tables: list[Table]) -> tuple[list[dict], list[dict]]:
    """Build model column specs with unique display names.

    Returns (columns, renames). Each column spec is the shape
    ``build_model_tml`` expects: ``{name, db_column_name, table, column_type}``.
    ``column_id`` (``table::db_column_name``) stays unique even when a display
    name had to be qualified for a duplicate.
    """
    columns: list[dict] = []
    renames: list[dict] = []
    seen: set[str] = set()

    def unique(name: str, table: str) -> str:
        if name not in seen:
            seen.add(name)
            return name
        qualified = f"{name} ({table})"
        i = 2
        while qualified in seen:
            qualified = f"{name} ({table} {i})"
            i += 1
        seen.add(qualified)
        renames.append({"from": name, "to": qualified, "table": table})
        return qualified

    for tbl in tables:
        for col in tbl.columns:
            columns.append({
                "name": unique(col.name, tbl.name),
                "db_column_name": col.name,
                "table": tbl.name,
                "column_type": "ATTRIBUTE",
            })
    return columns, renames


def _translate_measures(measures) -> tuple[list[dict], list[dict]]:
    """Translate master measures to formulas + a mapping-report entry each.

    Returns (formulas, measure_map). ``formulas`` are ``{name, expr,
    column_type}`` for ``build_model_tml``. Untranslatable expressions are still
    emitted (with the /* TODO review */ marker) but flagged NEEDS REVIEW and the
    original Qlik expression is retained in the map — never downgraded.
    """
    formulas: list[dict] = []
    measure_map: list[dict] = []
    seen: set[str] = set()
    for m in measures:
        name = m.label or m.id
        # keep formula names unique so build_model_tml columns[] stay 1:1
        base, i = name, 2
        while name in seen:
            name = f"{base} ({i})"
            i += 1
        seen.add(name)

        ts_expr, review, reason = functions.translate(m.expression)
        status = _STATUS_REVIEW if review else _STATUS_OK
        formulas.append({"name": name, "expr": ts_expr, "column_type": "MEASURE"})
        measure_map.append({
            "name": name,
            "qlik_expr": m.expression,
            "ts_expr": ts_expr,
            "status": status,
            "reason": reason,
        })
    return formulas, measure_map


def _lookup_type(type_overrides: Optional[dict], table: str, column: str) -> Optional[str]:
    """Case-insensitive lookup into a {table: {column: ts_type}} override map."""
    if not type_overrides:
        return None
    tbl = (type_overrides.get(table) or type_overrides.get(table.upper())
           or type_overrides.get(table.lower()))
    if not tbl:
        return None
    return tbl.get(column) or tbl.get(column.upper()) or tbl.get(column.lower())


def _map_type(qlik_type: str) -> str:
    return _TYPE_MAP.get((qlik_type or "").lower(), "VARCHAR")


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_") or "obj"
