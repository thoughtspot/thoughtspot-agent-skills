"""Tableau → ThoughtSpot formula translation engine.

Pure functions: classification dicts in, translated formula dicts out.
No I/O, no network calls — trivially unit-testable.

The pipeline applies transforms in a fixed order. Each step's output feeds the next.
Reordering or skipping steps produces the errors documented inline.

Pre-transform order (runs before the main pipeline on each formula):
  0. Strip Tableau // line comments (BL-056)
  1. Rewrite Custom SQL Query aliases → table-qualified refs (BL-057)
  2. Convert no-keyword LOD {AGG([col])} → group_aggregate (BL-052)
  3. Detect and rewrite scalar MAX(a,b) / MIN(a,b) (BL-055)
  4. Rewrite date arithmetic DATE()+N → add_days (BL-054)

Post-pipeline transforms (runs after the main pipeline on each formula):
  13b. Strip ifnull(X, 0) for measures — TS handles NULLs automatically (BL-046 #1)
  13c. Convert agg(if...else 0/null) → agg_if (sum_if, count_if, average_if) (BL-046 #2)
"""
from __future__ import annotations

import re

from ts_cli.tableau.parsing import (  # noqa: F401 — re-exported for back-compat
    _extract_function_args,
    _find_last_top_level_else,
    _find_matching_brace,
    _find_matching_end,
    _find_top_level_colon,
    _split_args,
)
from ts_cli.tableau.pre_transforms import (  # noqa: F401
    _NO_KEYWORD_LOD_AGG_MAP,
    _convert_scalar_fn,
    build_csq_column_map,
    convert_no_keyword_lod,
    convert_scalar_max_min,
    rewrite_csq_aliases,
    rewrite_date_arithmetic,
    strip_comments,
)
from ts_cli.tableau.conditionals import (  # noqa: F401
    _AGG_IF_MAP,
    _INNER_IF_END,
    _convert_if_content,
    _parse_if_else_for_agg,
    convert_agg_if,
    convert_boolean_aggregate,
    convert_case_when,
    convert_if_then,
    convert_iif,
    ensure_else_clause,
)
from ts_cli.tableau.functions import (  # noqa: F401
    _DATEADD_UNIT_MAP,
    _DATEDIFF_UNIT_MAP,
    _DATEPART_UNIT_MAP,
    _DATETRUNC_UNIT_MAP,
    _FUNCTION_MAP,
    _build_function_map,
    _convert_dateadd,
    _convert_datediff,
    _convert_datename,
    _convert_datepart,
    _convert_datetrunc,
    _convert_zn,
    map_date_functions,
    map_functions,
)
from ts_cli.tableau.strings_types import (  # noqa: F401
    _CONCAT_OPERAND,
    _CONCAT_PAIR,
    _IN_PAREN,
    _looks_like_string_concat,
    _replace_string_plus_chains,
    convert_int,
    convert_string_concat,
    fix_in_parentheses,
    scope_columns,
)
from ts_cli.tableau.lod import (  # noqa: F401
    _lod_to_group_aggregate,
    _parse_lod_content,
    convert_lod,
    convert_total,
)
from ts_cli.tableau.cleanup import (  # noqa: F401
    complete_rank_args,
    normalize_operator_spacing,
    strip_ifnull_zero,
)
from ts_cli.tableau.dag import (  # noqa: F401 — re-exported for back-compat
    build_calc_id_map,
    build_dependency_dag,
    resolve_cross_references,
)
from ts_cli.tableau.params import (  # noqa: F401
    _PARAM_UNSAFE,
    build_param_renames,
    detect_param_conflicts,
    map_parameter_names,
    sanitise_parameter_name,
    sanitise_parameter_refs,
    strip_parameter_prefix,
)
from ts_cli.tableau.naming import (  # noqa: F401 — re-exported for back-compat
    apply_name_clash_renames,
    detect_name_clashes,
)
from ts_cli.tableau.validate import (  # noqa: F401
    _FORBIDDEN_PATTERNS,
    validate_output,
    validate_pre_import,
)
from ts_cli.tableau.yaml_out import dump_tml_yaml  # noqa: F401


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def translate_single(
    raw_expr: str,
    role: str = "measure",
    scoped_columns: dict[str, str] | None = None,
    param_map: dict[str, str] | None = None,
    formula_names: set[str] | None = None,
    parameter_names: set[str] | None = None,
    csq_to_table: dict[str, str] | None = None,
    date_columns: set[str] | None = None,
) -> tuple[str, list[str], dict[str, int]]:
    """Apply the full translation pipeline to a single formula expression.

    Returns (translated_expr, validation_errors, transform_notes).
    transform_notes: counts of auto-applied transforms (e.g. ifnull_stripped, agg_if_converted).
    """
    notes: dict[str, int] = {}
    expr = raw_expr

    # Pre-0. Strip // line comments (BL-056)
    expr = strip_comments(expr)

    # Pre-1. Rewrite Custom SQL Query aliases (BL-057)
    if csq_to_table:
        expr = rewrite_csq_aliases(expr, csq_to_table)

    # Pre-2. No-keyword LOD (BL-052) — before keyword LOD so braces are consumed
    expr = convert_no_keyword_lod(expr)

    # Pre-3. Scalar MAX/MIN (BL-055) — before function mapping replaces MAX/MIN
    expr = convert_scalar_max_min(expr)

    # Pre-4. Date arithmetic (BL-054) — before date function mapping
    expr = rewrite_date_arithmetic(expr, date_columns=date_columns)

    # 1. Strip parameter prefix
    expr = strip_parameter_prefix(expr)

    # 2. Map internal parameter names to captions
    if param_map:
        expr = map_parameter_names(expr, param_map)

    # 3. LOD expressions (before IF/CASE — LODs may contain those)
    expr = convert_lod(expr)

    # 4. TOTAL()
    expr = convert_total(expr)

    # 5. CASE/WHEN → if/else if
    expr = convert_case_when(expr)

    # 6. IIF
    expr = convert_iif(expr)

    # 7. IF/THEN/END → if()/then/else
    expr = convert_if_then(expr)

    # 8. INT() — before general function mapping
    expr = convert_int(expr)

    # 9. Function mapping
    expr = map_functions(expr)

    # 10. Date function mapping
    expr = map_date_functions(expr)

    # 10d. Boolean aggregation: MAX/MIN/SUM(<comparison>) → agg(if <cmp> then 1 else 0)
    expr = convert_boolean_aggregate(expr)

    # 11. String concatenation
    expr = convert_string_concat(expr, role)

    # 11b. Operator spacing (BL-046 #4)
    expr = normalize_operator_spacing(expr)

    # 11c. rank() argument completion (BL-046 #3)
    expr = complete_rank_args(expr)

    # 12. Column scoping
    if scoped_columns:
        expr = scope_columns(
            expr,
            scoped_columns,
            formula_names=formula_names,
            parameter_names=parameter_names,
        )

    # 12b. Strip ifnull(X, 0) for measures (BL-046 #1)
    if role == "measure":
        stripped = strip_ifnull_zero(expr)
        if stripped != expr:
            notes["ifnull_stripped"] = 1
            expr = stripped

    # 12c. Convert agg(if...then[...else 0/null]) → agg_if (BL-046 #2)
    converted = convert_agg_if(expr)
    if converted != expr:
        notes["agg_if_converted"] = 1
        expr = converted

    # 13. Mandatory else clause (for remaining if/then without else)
    expr = ensure_else_clause(expr, role)

    # 13b. Fix IN (...) → in {...} (ThoughtSpot requires curly braces)
    expr = fix_in_parentheses(expr)

    # 14. Strip orphaned END/CASE/WHEN keywords that survived conversion
    expr = re.sub(r"(?<!\[)\bEND\b(?!\])", "", expr, flags=re.IGNORECASE)
    expr = re.sub(r"(?<!\[)\bCASE\b(?!\])", "", expr, flags=re.IGNORECASE)

    # 14b. Clean up whitespace
    expr = re.sub(r"\s+", " ", expr).strip()

    # 15. Validate
    errors = validate_output(expr)

    return expr, errors, notes


def translate_formulas(
    formulas: list[dict],
    scoped_columns: dict[str, str] | None = None,
    param_map: dict[str, str] | None = None,
    parameters: list[dict] | None = None,
    calc_id_map: dict[str, str] | None = None,
    csq_to_table: dict[str, str] | None = None,
    date_columns: set[str] | None = None,
) -> dict:
    """Translate a batch of Tableau formulas to ThoughtSpot syntax.

    Input: list of formula dicts with keys: caption, formula, datatype, role, name
    Output: {
        "translated": [{"name": str, "expr": str, "column_type": str, "level": int}],
        "skipped": [{"name": str, "reason": str, "level": int}],
        "stats": {"total": int, "translated": int, "skipped": int, "levels": {}}
    }
    """
    parameters = parameters or []
    scoped_columns = scoped_columns or {}

    # Build dependency DAG
    dag = build_dependency_dag(formulas)
    if not calc_id_map:
        calc_id_map = build_calc_id_map(formulas)

    # Detect parameter conflicts
    param_conflicts = detect_param_conflicts(formulas, parameters)

    # Sanitise parameter names (BL-050 #6)
    param_renames = build_param_renames(parameters)

    # Detect column/formula name clashes (BL-050 #9)
    formula_names = {f.get("caption", "") for f in formulas if f.get("caption")}
    column_names = set(scoped_columns.keys()) if scoped_columns else set()
    name_clashes = detect_name_clashes(formula_names, column_names)

    # Collect formula and parameter names for column scoping
    parameter_names = {
        p.get("caption", p.get("name", ""))
        for p in parameters
        if p.get("caption") or p.get("name")
    }

    # Process formulas in topological order (level 0 first, then 1, etc.)
    translated: list[dict] = []
    skipped: list[dict] = []
    level_counts: dict[int, int] = {}
    transform_counts: dict[str, int] = {}

    max_level = max((e["level"] for e in dag.values()), default=0)

    for level in range(0, max_level + 1):
        level_formulas = [
            (caption, entry) for caption, entry in dag.items()
            if entry["level"] == level
        ]

        for caption, entry in level_formulas:
            level_counts[level] = level_counts.get(level, 0) + 1
            f = entry["formula"]
            raw = entry["raw"]

            # Skip parameter-conflict pass-throughs
            if caption in param_conflicts and "pass-through" in param_conflicts[caption]:
                skipped.append({
                    "name": caption,
                    "reason": f"parameter pass-through — {param_conflicts[caption]}",
                    "level": level,
                    "original": raw,
                })
                continue

            # Strip comments before resolution so commented-out refs don't block
            raw_clean = strip_comments(raw)

            # Resolve cross-references
            resolved = resolve_cross_references(raw_clean, dag, calc_id_map)
            entry["resolved_expr"] = resolved

            # Check for unresolved references
            if re.search(r"\[Calculation_\d+\]", resolved, re.IGNORECASE):
                skipped.append({
                    "name": caption,
                    "reason": "unresolved cross-reference",
                    "level": level,
                    "original": raw,
                })
                continue

            # Apply parameter name sanitisation to resolved expression
            if param_renames:
                resolved = sanitise_parameter_refs(resolved, param_renames)

            # Translate
            role = f.get("role", "measure")
            expr, errors, notes = translate_single(
                resolved,
                role=role,
                scoped_columns=scoped_columns,
                param_map=param_map,
                formula_names=formula_names,
                parameter_names=parameter_names,
                csq_to_table=csq_to_table,
                date_columns=date_columns,
            )

            for note_key, note_count in notes.items():
                transform_counts[note_key] = transform_counts.get(note_key, 0) + note_count

            if errors:
                skipped.append({
                    "name": caption,
                    "reason": f"validation: {'; '.join(errors)}",
                    "level": level,
                    "original": raw,
                    "attempted_expr": expr,
                })
            else:
                column_type = "MEASURE" if role == "measure" else "ATTRIBUTE"
                output_name = name_clashes.get(caption, caption)
                # Update cross-references to renamed formulas
                if name_clashes:
                    expr = apply_name_clash_renames(expr, name_clashes)
                translated.append({
                    "name": output_name,
                    "expr": expr,
                    "column_type": column_type,
                    "level": level,
                })

    # Handle circular / unresolvable (level -1)
    for caption, entry in dag.items():
        if entry["level"] < 0:
            level_counts[-1] = level_counts.get(-1, 0) + 1
            skipped.append({
                "name": caption,
                "reason": "circular or unresolvable dependency",
                "level": -1,
                "original": entry["raw"],
            })

    return {
        "translated": translated,
        "skipped": skipped,
        "stats": {
            "total": len(formulas),
            "translated": len(translated),
            "skipped": len(skipped),
            "levels": level_counts,
            "param_conflicts": len(param_conflicts),
            "param_renames": len(param_renames),
            "name_clashes": len(name_clashes),
            "ifnull_stripped": transform_counts.get("ifnull_stripped", 0),
            "agg_if_conversions": transform_counts.get("agg_if_converted", 0),
        },
    }
