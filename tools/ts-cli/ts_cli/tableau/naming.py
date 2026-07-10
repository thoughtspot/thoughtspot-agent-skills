"""Name-collision detection and resolution across columns, formulas, and
parameters produced during Tableau → ThoughtSpot conversion.
"""
from __future__ import annotations

from ts_cli.formula_common import resolve_name_collisions  # noqa: F401 — moved (BL-063 PR 5)


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
