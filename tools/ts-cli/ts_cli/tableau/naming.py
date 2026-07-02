"""Name-collision detection and resolution across columns, formulas, and
parameters produced during Tableau → ThoughtSpot conversion.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# 20. Column/formula name clash detection (BL-046 #7 / BL-050 #9)
# ---------------------------------------------------------------------------

def detect_name_clashes(
    formula_names: set[str],
    column_names: set[str],
) -> dict[str, str]:
    """Detect case-insensitive collisions between formula and column names.

    Returns: { formula_name: suggested_rename }
    """
    col_upper = {c.upper(): c for c in column_names}
    clashes: dict[str, str] = {}
    for fname in formula_names:
        if fname.upper() in col_upper:
            clashes[fname] = f"Formula {fname}"
    return clashes


def apply_name_clash_renames(expr: str, name_clashes: dict[str, str]) -> str:
    """Update ``[formula_X]`` references in *expr* when X was renamed by name-clash detection."""
    for original, renamed in name_clashes.items():
        old_ref = f"[formula_{original}]"
        new_ref = f"[formula_{renamed}]"
        if old_ref in expr:
            expr = expr.replace(old_ref, new_ref)
    return expr


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
