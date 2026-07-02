"""Pre-import and output validation for translated Tableau formulas.

Pure functions, no I/O. Flags forbidden syntax patterns and structural
issues (unbalanced brackets, orphaned if/then/else, unresolved refs) before
a formula is sent to ThoughtSpot import.
"""
from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# 15. Validation
# ---------------------------------------------------------------------------

_FORBIDDEN_PATTERNS = [
    (re.compile(r"(?<!\[)\bEND\b(?!\])", re.IGNORECASE), "bare 'END' keyword"),
    (re.compile(r"(?<!\[)\bCASE\b(?!\])", re.IGNORECASE), "bare 'CASE' keyword"),
    (re.compile(r"(?<!\[)\bWHEN\b(?!\])", re.IGNORECASE), "bare 'WHEN' keyword"),
    (re.compile(r"\bunique_count\b"), "'unique_count' (should be 'unique count')"),
    (re.compile(r"\bdate_trunc\b", re.IGNORECASE), "'date_trunc' (should be 'start_of_*')"),
    (re.compile(r"\bELSEIF\b", re.IGNORECASE), "'ELSEIF' (should be 'else if')"),
]


def validate_output(expr: str) -> list[str]:
    """Check for forbidden patterns in a translated expression.

    Returns a list of validation error strings. Empty = clean.
    """
    errors: list[str] = []
    for pattern, desc in _FORBIDDEN_PATTERNS:
        if pattern.search(expr):
            errors.append(f"Contains {desc}")
    return errors


def validate_pre_import(
    translated: list[dict],
    column_names: set[str] | None = None,
    formula_names: set[str] | None = None,
) -> list[dict]:
    """Pre-import structural validation to catch issues before ThoughtSpot import.

    Checks each translated formula for common patterns that cause import failures.
    Returns a list of {name, warnings: [str]} for formulas with issues.
    """
    column_names = column_names or set()
    formula_names = formula_names or set()
    col_upper = {c.upper() for c in column_names}
    formula_upper = {f.upper() for f in formula_names}
    all_names_upper = col_upper | formula_upper

    issues: list[dict] = []

    for entry in translated:
        name = entry.get("name", "")
        expr = entry.get("expr", "")
        warnings: list[str] = []

        # Check for unbalanced parentheses
        depth = 0
        for c in expr:
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            if depth < 0:
                break
        if depth != 0:
            warnings.append(f"Unbalanced parentheses (depth={depth})")

        # Check for unbalanced brackets
        b_depth = 0
        for c in expr:
            if c == "[":
                b_depth += 1
            elif c == "]":
                b_depth -= 1
        if b_depth != 0:
            warnings.append(f"Unbalanced brackets (depth={b_depth})")

        # if/then/else structural validation (BL-046 #5)
        # Strip [col refs] and 'strings' to avoid false matches
        expr_stripped = re.sub(r'\[[^\]]*\]', '', expr)
        expr_stripped = re.sub(r"'[^']*'", '', expr_stripped)
        lower_s = expr_stripped.lower()

        # Use negative lookbehind to exclude *_if functions (sum_if, count_if, etc.)
        if_count = len(re.findall(r'(?<![a-zA-Z_])\bif\b', lower_s))
        then_count = len(re.findall(r'(?<![a-zA-Z_])\bthen\b', lower_s))
        else_count = len(re.findall(r'(?<![a-zA-Z_])\belse\b', lower_s))

        if if_count > 0:
            if then_count < if_count:
                warnings.append(f"if without matching then ({if_count} if, {then_count} then)")
            if else_count < if_count:
                warnings.append(f"if/then without else ({if_count} if, {else_count} else)")
        if else_count > if_count:
            warnings.append(f"Orphaned else clause ({else_count} else, {if_count} if)")

        # Check for unresolved Custom SQL Query references
        if "Custom SQL Query" in expr:
            warnings.append("Unresolved Custom SQL Query alias")

        # Check for nested group_aggregate (ThoughtSpot limitation)
        ga_positions = [m.start() for m in re.finditer(r'\bgroup_aggregate\s*\(', expr)]
        if len(ga_positions) >= 2:
            warnings.append(
                "Nested group_aggregate — ThoughtSpot does not support "
                "group_aggregate inside another group_aggregate. "
                "Decompose into separate formulas."
            )

        # Check for bare Tableau aggregate keywords
        if re.search(r"\bCOUNTD\b", expr):
            warnings.append("Unrewritten COUNTD (should be 'unique count')")

        # IN with parentheses instead of curly braces
        if re.search(r'\bin\s*\(', expr, re.IGNORECASE):
            if not re.search(r'\bnot\s+in\s*\(', expr, re.IGNORECASE):
                warnings.append("IN uses parentheses — ThoughtSpot requires curly braces: in {a, b, c}")

        # Non-existent ThoughtSpot functions
        if re.search(r'\badd_quarters\s*\(', expr, re.IGNORECASE):
            warnings.append("add_quarters() does not exist — use add_months(expr, N*3)")
        if re.search(r'\badd_years\s*\(', expr, re.IGNORECASE):
            warnings.append("add_years() does not exist — use add_months(expr, N*12)")

        # Bare date literal not wrapped in to_date()
        bare_date = re.search(r"'(\d{4}-\d{2}-\d{2})'", expr)
        if bare_date:
            before = expr[:bare_date.start()]
            if not before.rstrip().lower().endswith("to_date("):
                warnings.append(
                    f"Bare date literal '{bare_date.group(1)}' — "
                    "wrap in to_date('YYYY-MM-DD', 'yyyy-MM-dd')"
                )

        # max(boolean_expr)=false pattern — ThoughtSpot can't aggregate a boolean
        if re.search(r'\bmax\s*\([^)]*=[^)]*\)\s*=\s*false', expr, re.IGNORECASE):
            warnings.append(
                "max([col]='value')=false pattern — rewrite as "
                "count_if([col] != 'value') = 0 or similar"
            )

        # Name clash with existing column
        if name.upper() in col_upper:
            warnings.append(f"Formula name '{name}' clashes with column name")

        if warnings:
            issues.append({"name": name, "warnings": warnings})

    return issues
