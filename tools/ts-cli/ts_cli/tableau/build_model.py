"""Pure helpers behind ``ts tableau build-model`` (BL-069 follow-up).

Extracted from the ~440-line ``build_model_cmd`` so each piece is unit-testable
in isolation. Pure functions, no I/O — subprocess calls and stderr echoes stay
in ``ts_cli/commands/tableau.py``.
"""
from __future__ import annotations

import re

from ts_cli.model_builder import (
    add_formula_prefix,
    build_column_lookup,
    fix_bare_refs,
    fix_double_aggregation,
)

_CSQ_SUFFIX = re.compile(r"\s*\(Custom SQL Query\d*\)\s*$")
_CSQ_IN_REF = re.compile(r"\[([^\]]+?)\s+\(\s*Custom SQL Query\d*\)\]")


def fix_sqlproxy_scoping(
    scoped_columns: dict[str, str],
    existing_tml: dict,
) -> tuple[dict[str, str], str]:
    """Remap ``sqlproxy`` table scopes to actual model tables.

    Published-datasource TWBs scope columns to the ``sqlproxy`` pseudo-table.
    When merging into an existing model, derive the real column→table map from
    the model's ``column_id`` entries (``TABLE::COLUMN``).

    Returns ``(fixed_scoped, message)`` — message is "" when nothing needed
    fixing, otherwise a human-readable summary for the caller to echo.
    """
    if not any(t == "sqlproxy" for t in scoped_columns.values()):
        return scoped_columns, ""

    model_tables = existing_tml["model"].get("model_tables", [])
    if len(model_tables) == 1:
        return _force_single_table(scoped_columns, existing_tml)
    return _remap_multi_table(scoped_columns, existing_tml)


def _force_single_table(
    scoped_columns: dict[str, str],
    existing_tml: dict,
) -> tuple[dict[str, str], str]:
    """Single-table model: force ALL columns to the one table."""
    single_table = existing_tml["model"]["model_tables"][0]["name"]
    fixed_scoped: dict[str, str] = {}
    for col_key in scoped_columns:
        base = _CSQ_SUFFIX.sub("", col_key)
        fixed_scoped[col_key] = single_table
        if base != col_key:
            fixed_scoped[base] = single_table
    for col in existing_tml["model"]["columns"]:
        cid = col.get("column_id", "")
        if "::" in cid:
            _, cname = cid.split("::", 1)
            if cname not in {k.upper() for k in fixed_scoped}:
                fixed_scoped[cname] = single_table
    return fixed_scoped, f"Single-table model: forced all columns → {single_table}"


def _remap_multi_table(
    scoped_columns: dict[str, str],
    existing_tml: dict,
) -> tuple[dict[str, str], str]:
    """Multi-table model: remap sqlproxy scopes via ``column_id`` lookup."""
    col_to_table: dict[str, str] = {}
    for col in existing_tml["model"]["columns"]:
        col_id = col.get("column_id", "")
        if "::" in col_id:
            tbl, cname = col_id.split("::", 1)
            col_to_table[cname.upper()] = tbl
    fixed_scoped = {}
    for col_key, tbl in scoped_columns.items():
        base = _CSQ_SUFFIX.sub("", col_key)
        lookup = base.upper()
        actual_tbl = col_to_table.get(lookup, tbl) if tbl == "sqlproxy" else tbl
        fixed_scoped[col_key] = actual_tbl
        if base != col_key and lookup in col_to_table and base not in fixed_scoped:
            fixed_scoped[base] = col_to_table[lookup]
    for cname, tbl in col_to_table.items():
        if cname not in {k.upper() for k in fixed_scoped}:
            fixed_scoped[cname] = tbl
    remapped = sum(
        1 for k in fixed_scoped
        if k in scoped_columns and fixed_scoped[k] != scoped_columns[k]
    )
    return fixed_scoped, f"Remapped {remapped}/{len(scoped_columns)} sqlproxy columns"


def strip_csq_suffixes(formulas: list[dict]) -> int:
    """Strip `` (Custom SQL QueryN)`` suffixes from bracketed refs, in place.

    Returns the number of formulas whose expression changed.
    """
    changed = 0
    for f in formulas:
        new_expr = _CSQ_IN_REF.sub(r"[\1]", f["expr"])
        if new_expr != f["expr"]:
            f["expr"] = new_expr
            changed += 1
    return changed


def collect_existing_model_context(existing_tml: dict) -> dict:
    """Extract the name/id sets and lookups the merge flow needs from a model TML."""
    model = existing_tml["model"]
    model_tables = model.get("model_tables", [])
    return {
        "existing_ids": {f["id"] for f in model.get("formulas", [])},
        "existing_cols": {
            c.get("column_id", "").split("::")[-1]
            for c in model.get("columns", [])
            if "::" in c.get("column_id", "")
        },
        "formula_names": {f["name"] for f in model.get("formulas", [])},
        "param_names": {p["name"] for p in model.get("parameters", [])},
        "col_lookup": build_column_lookup(existing_tml),
        "primary_table": model_tables[0]["name"] if model_tables else None,
    }


def prepare_formulas_for_merge(
    cleaned_formulas: list[dict],
    ctx: dict,
) -> tuple[list[dict], int]:
    """CSQ-strip, bare-ref fix, ``formula_`` prefix, and double-agg fix.

    Mutates ``cleaned_formulas`` expressions in place (matching the original
    inline behavior), then builds the ``{expr, id, name}`` dicts the merge
    consumes. Returns ``(formula_dicts, bare_fixed_count)``.
    """
    strip_csq_suffixes(cleaned_formulas)

    new_formula_names = {f["name"] for f in cleaned_formulas}
    all_formula_names = ctx["formula_names"] | new_formula_names
    param_names = ctx["param_names"]

    bare_fixed = 0
    # "is not None", not truthy — the original gated on model_tables being
    # non-empty, so an empty-string table name must still run the loop
    if ctx["primary_table"] is not None:
        for f in cleaned_formulas:
            before = f["expr"]
            f["expr"] = fix_bare_refs(
                f["expr"], all_formula_names, param_names,
                ctx["col_lookup"], ctx["primary_table"],
            )
            if f["expr"] != before:
                bare_fixed += 1

    formula_exprs = {f["name"]: f["expr"] for f in cleaned_formulas}
    formula_dicts = []
    for f in cleaned_formulas:
        expr = add_formula_prefix(f["expr"], all_formula_names, param_names)
        expr = fix_double_aggregation(expr, formula_exprs)
        formula_dicts.append({
            "expr": expr,
            "id": f"formula_{f['name']}",
            "name": f["name"],
        })
    return formula_dicts, bare_fixed
