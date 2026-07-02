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
from typing import Any

from ts_cli.tableau.parsing import (  # noqa: F401 — re-exported for back-compat
    _extract_function_args,
    _find_last_top_level_else,
    _find_matching_brace,
    _find_matching_end,
    _find_top_level_colon,
    _split_args,
    _split_on_plus,
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


# ---------------------------------------------------------------------------
# 1. Dependency DAG — cross-reference resolution
# ---------------------------------------------------------------------------

def build_dependency_dag(
    formulas: list[dict],
) -> dict[str, dict]:
    """Build a map from formula caption → {formula, deps, level, resolved_expr}.

    Each formula dict must have 'caption' and 'formula' keys.
    A dependency is any [Calculation_NNNN] reference in the formula text.
    """
    _CALC_REF = re.compile(r"\[Calculation_\d+\]", re.IGNORECASE)

    by_name: dict[str, dict] = {}
    by_calc_id: dict[str, str] = {}

    for f in formulas:
        caption = f.get("caption", "")
        raw = f.get("formula", "")
        name = f.get("name", caption)
        # 'name' in classification.json is the Tableau internal name (e.g. Calculation_123)
        # 'caption' is the display name
        if name and name.startswith("Calculation_"):
            by_calc_id[f"[{name}]"] = caption

        by_name[caption] = {
            "formula": f,
            "raw": raw,
            "deps": set(),
            "level": -1,
            "resolved_expr": None,
        }

    # Find dependencies
    for caption, entry in by_name.items():
        refs = _CALC_REF.findall(entry["raw"])
        for ref in refs:
            dep_caption = by_calc_id.get(ref)
            if dep_caption and dep_caption != caption:
                entry["deps"].add(dep_caption)
            elif ref.strip("[]") != caption:
                # Unknown calc ref — record as unresolvable
                entry["deps"].add(ref)

    # Topological sort — assign levels
    changed = True
    while changed:
        changed = False
        for caption, entry in by_name.items():
            if entry["level"] >= 0:
                continue
            if not entry["deps"]:
                entry["level"] = 0
                changed = True
            elif all(
                by_name.get(d, {}).get("level", -1) >= 0
                for d in entry["deps"]
                if not d.startswith("[Calculation_")
            ):
                max_dep = max(
                    (by_name[d]["level"] for d in entry["deps"]
                     if d in by_name and by_name[d]["level"] >= 0),
                    default=0,
                )
                entry["level"] = max_dep + 1
                changed = True

    # Mark remaining as circular or unresolvable
    for entry in by_name.values():
        if entry["level"] < 0:
            entry["level"] = -1  # circular / unresolvable

    return by_name


def resolve_cross_references(
    expr: str,
    dag: dict[str, dict],
    by_calc_id: dict[str, str],
    max_depth: int = 10,
) -> str:
    """Replace [Calculation_NNN] references with the referenced formula's expression.

    Inlines recursively up to max_depth. Returns the resolved expression.
    """
    _CALC_REF = re.compile(r"\[Calculation_\d+\]", re.IGNORECASE)

    for _ in range(max_depth):
        refs = _CALC_REF.findall(expr)
        if not refs:
            break
        replaced_any = False
        for ref in refs:
            dep_caption = by_calc_id.get(ref)
            # Fallback: try normalized (case-insensitive) lookup
            if dep_caption is None:
                norm_ref = re.sub(r"\s+", " ", ref).lower()
                dep_caption = by_calc_id.get(norm_ref)
            if dep_caption and dep_caption in dag:
                dep_entry = dag[dep_caption]
                replacement = dep_entry.get("resolved_expr") or dep_entry["raw"]
                if replacement and "[Calculation_" not in replacement:
                    expr = expr.replace(ref, f"({replacement})")
                    replaced_any = True
                elif replacement:
                    # Try partial replacement
                    expr = expr.replace(ref, f"({replacement})")
                    replaced_any = True
            else:
                # Can't resolve — replace with display name if available
                caption = by_calc_id.get(ref)
                if caption:
                    expr = expr.replace(ref, f"[{caption}]")
                    replaced_any = True
        if not replaced_any:
            break

    return expr


def build_calc_id_map(formulas: list[dict]) -> dict[str, str]:
    """Build [Calculation_NNN] → caption map from formula list.

    Stores both the original-case key and a normalized (lowercase, whitespace-
    collapsed) key so that lookups are case-insensitive and whitespace-tolerant.
    """
    result: dict[str, str] = {}
    for f in formulas:
        name = f.get("name", "")
        caption = f.get("caption", "")
        if name and name.startswith("Calculation_") and caption:
            key = f"[{name}]"
            result[key] = caption
            # Also store normalized version for case-insensitive matching
            norm_key = re.sub(r"\s+", " ", key).lower()
            if norm_key != key.lower():
                result[norm_key] = caption
    return result


# ---------------------------------------------------------------------------
# 2. Parameter handling
# ---------------------------------------------------------------------------

def strip_parameter_prefix(expr: str) -> str:
    """[Parameters].[X] → [X]"""
    return re.sub(
        r"\[Parameters\]\.\[([^\]]+)\]",
        r"[\1]",
        expr,
        flags=re.IGNORECASE,
    )


def map_parameter_names(
    expr: str,
    param_map: dict[str, str],
) -> str:
    """Replace internal parameter names with display captions.

    param_map: {"Parameter 3 1": "Metric"} — internal name → caption.
    """
    for internal, caption in param_map.items():
        expr = expr.replace(f"[{internal}]", f"[{caption}]")
    return expr


# ---------------------------------------------------------------------------
# 8. String concatenation: + on strings → concat()
# ---------------------------------------------------------------------------

def convert_string_concat(expr: str, role: str = "dimension") -> str:
    """Convert string + concatenation to concat().

    Only applies when the formula role is 'dimension' (string context)
    or the expression contains STR() / to_string() / string literals adjacent to +.

    Works at any nesting depth: finds contiguous chains of
    ``operand + operand`` where at least one operand is a string literal,
    and wraps the chain in ``concat()``.
    """
    if role == "measure" and "to_string" not in expr.lower() and "str(" not in expr.lower():
        return expr

    if "+" not in expr:
        return expr

    return _replace_string_plus_chains(expr, role)


_CONCAT_OPERAND = (
    r"(?:"
    r"\[[^\]]+\]"                   # [column ref]
    r"|'[^']*'"                     # 'string literal'
    r"|to_string\s*\([^)]*\)"       # to_string(...)
    r")"
)

_CONCAT_PAIR = re.compile(
    rf"({_CONCAT_OPERAND})\s*\+\s*({_CONCAT_OPERAND})",
    re.IGNORECASE,
)


def _replace_string_plus_chains(expr: str, role: str) -> str:
    """Replace ``a + 'x' + b`` chains with ``concat(a, 'x', b)`` at any depth.

    Uses iterative regex matching: finds pairs of operands around ``+`` where
    at least one is a string literal (or the role is ``dimension``), collects
    the full chain, and replaces with ``concat()``.  Merges adjacent results
    so ``concat(a, b) + c`` collapses to ``concat(a, b, c)``.
    """
    result = expr
    safety = 0
    while safety < 50:
        m = _CONCAT_PAIR.search(result)
        if not m:
            break
        left, right = m.group(1).strip(), m.group(2).strip()
        has_string = role == "dimension" or "'" in left or "'" in right
        if not has_string:
            break
        safety += 1
        # Extend chain rightward: keep matching + OPERAND after the pair
        chain = [left, right]
        end = m.end()
        ext = re.compile(r"\s*\+\s*" + _CONCAT_OPERAND, re.IGNORECASE)
        while True:
            em = ext.match(result, end)
            if not em:
                break
            chain.append(em.group(0).split("+", 1)[1].strip())
            end = em.end()
        inner = " , ".join(chain)
        result = result[:m.start()] + f"concat ( {inner} )" + result[end:]
    return result


def _looks_like_string_concat(parts: list[str], role: str) -> bool:
    """Heuristic: does this + look like string concatenation?"""
    if role == "dimension":
        return True
    for p in parts:
        stripped = p.strip()
        if stripped.startswith("'") and stripped.endswith("'"):
            return True
        if "to_string" in stripped.lower():
            return True
    return False


# ---------------------------------------------------------------------------
# 9. Type conversions
# ---------------------------------------------------------------------------

def convert_int(expr: str) -> str:
    """Convert Tableau INT(x) to ThoughtSpot equivalent.

    INT truncates toward zero: floor for positive, ceil for negative.
    """
    _INT = re.compile(r"\bINT\s*\(", re.IGNORECASE)

    result = expr
    safety = 0
    while safety < 20:
        m = _INT.search(result)
        if not m:
            break
        safety += 1

        extracted = _extract_function_args(result, m.end() - 1)
        if not extracted:
            break
        args, end_pos = extracted
        if args:
            inner = args[0].strip()
            replacement = f"if ( {inner} >= 0 ) then floor ( {inner} ) else ceil ( {inner} )"
            result = result[:m.start()] + replacement + result[end_pos:]

    return result


# ---------------------------------------------------------------------------
# 10. Column scoping: [COL] → [TABLE::COL]
# ---------------------------------------------------------------------------

def scope_columns(
    expr: str,
    scoped_columns: dict[str, str],
    formula_names: set[str] | None = None,
    parameter_names: set[str] | None = None,
) -> str:
    """Replace bare [COLUMN] references with [TABLE::COLUMN].

    scoped_columns: { "COLUMN_NAME": "TABLE_NAME" }
    formula_names: set of formula display names (don't scope these)
    parameter_names: set of parameter names (don't scope these)
    """
    formula_names = formula_names or set()
    parameter_names = parameter_names or set()

    _COL_REF = re.compile(r"\[([^\]]+)\]")

    _TABLE_SUFFIX = re.compile(r"^(.+?)\s+\(([^)]+)\)$")

    def _replace_col(m: re.Match) -> str:
        ref = m.group(1)
        # Already scoped (has ::)
        if "::" in ref:
            return m.group(0)
        # Is a formula reference
        if ref in formula_names:
            return m.group(0)
        # Is a parameter reference
        if ref in parameter_names:
            return m.group(0)
        # Look up table
        table = scoped_columns.get(ref)
        if table:
            # Strip "(table)" suffix — the TABLE:: prefix provides the scoping
            suffix_match = _TABLE_SUFFIX.match(ref)
            if suffix_match and suffix_match.group(2) == table:
                return f"[{table}::{suffix_match.group(1)}]"
            return f"[{table}::{ref}]"
        return m.group(0)

    return _COL_REF.sub(_replace_col, expr)


# ---------------------------------------------------------------------------
# 10b. Fix IN (...) → in {...}
# ---------------------------------------------------------------------------

_IN_PAREN = re.compile(r"\bin\s*\(", re.IGNORECASE)


def fix_in_parentheses(expr: str) -> str:
    """Replace IN (...) with in {...} — ThoughtSpot requires curly braces for set membership."""
    result = expr
    safety = 0
    while safety < 20:
        m = _IN_PAREN.search(result)
        if not m:
            break
        # Skip "not in (" — ThoughtSpot doesn't support NOT IN
        before = result[:m.start()].rstrip()
        if before.lower().endswith("not"):
            safety += 1
            # Move past this match to avoid infinite loop
            result = result[:m.end()] + result[m.end():]
            break
        safety += 1
        paren_start = m.end() - 1
        extracted = _extract_function_args(result, paren_start)
        if not extracted:
            break
        args, end_pos = extracted
        items = ", ".join(a.strip() for a in args)
        replacement = f"in {{ {items} }}"
        result = result[:m.start()] + replacement + result[end_pos:]
    return result


# ---------------------------------------------------------------------------
# 12. LOD expression conversion
# ---------------------------------------------------------------------------

def _parse_lod_content(content: str) -> tuple[str, str, str] | None:
    """Parse the content between matched { } into (keyword, dims, agg_expr).

    Returns None if the content doesn't look like an LOD expression.
    """
    stripped = content.strip()
    keyword_match = re.match(
        r"(FIXED|INCLUDE|EXCLUDE)\s+", stripped, re.IGNORECASE,
    )
    if keyword_match:
        keyword = keyword_match.group(1).upper()
        rest = stripped[keyword_match.end():]
    else:
        keyword = ""
        rest = stripped

    colon_pos = _find_top_level_colon(rest)
    if colon_pos < 0:
        return None

    dims_raw = rest[:colon_pos].strip()
    agg_expr = rest[colon_pos + 1:].strip()

    if not agg_expr:
        return None

    return keyword, dims_raw, agg_expr


def _lod_to_group_aggregate(keyword: str, dims_raw: str, agg_expr: str) -> str:
    """Build a group_aggregate() call from parsed LOD components."""
    if dims_raw:
        dims = [d.strip() for d in _split_args(dims_raw)]
        dims_str = " , ".join(dims)
    else:
        dims_str = ""

    if keyword == "FIXED" or keyword == "":
        if dims_str:
            return f"group_aggregate ( {agg_expr} , {{ {dims_str} }} , {{}} )"
        else:
            return f"group_aggregate ( {agg_expr} , {{}} , {{}} )"
    elif keyword == "INCLUDE":
        if dims_str:
            return f"group_aggregate ( {agg_expr} , query_groups () + {{ {dims_str} }} , query_filters () )"
        else:
            return f"group_aggregate ( {agg_expr} , query_groups () , query_filters () )"
    elif keyword == "EXCLUDE":
        if dims_str:
            return f"group_aggregate ( {agg_expr} , query_groups () - {{ {dims_str} }} , query_filters () )"
        else:
            return f"group_aggregate ( {agg_expr} , query_groups () , query_filters () )"

    return f"group_aggregate ( {agg_expr} , {{}} , {{}} )"


def convert_lod(expr: str) -> str:
    """Convert Tableau LOD expressions to ThoughtSpot group_aggregate().

    Uses bracket-depth matching instead of regex to handle:
    - LODs with Calculation_*/formula refs in dimension lists
    - LODs with boolean expressions in aggregates
    - LODs inside IF branches (composition)

    Nested LODs (group_aggregate inside group_aggregate) are decomposed:
    the inner LOD is converted first, producing a flat group_aggregate call
    that ThoughtSpot can evaluate. ThoughtSpot does not support nested
    group_aggregate — if the result still nests after conversion, the
    caller's validate_pre_import() will flag it.
    """
    result = expr
    safety = 0
    while safety < 50:
        # Find the innermost { first (so nested LODs are resolved inside-out)
        last_open = -1
        for i, c in enumerate(result):
            if c == "{":
                last_open = i
            elif c == "}" and last_open >= 0:
                break
        else:
            if last_open < 0:
                break
            close = _find_matching_brace(result, last_open)
            if close < 0:
                break

        if last_open < 0:
            break

        close = _find_matching_brace(result, last_open)
        if close < 0:
            break

        safety += 1
        content = result[last_open + 1:close]
        parsed = _parse_lod_content(content)

        if parsed is None:
            break

        keyword, dims_raw, agg_expr = parsed
        replacement = _lod_to_group_aggregate(keyword, dims_raw, agg_expr)
        result = result[:last_open] + replacement + result[close + 1:]

    return result


# ---------------------------------------------------------------------------
# 13. TOTAL() conversion
# ---------------------------------------------------------------------------

def convert_total(expr: str) -> str:
    """Convert Tableau TOTAL(agg) to ThoughtSpot group_aggregate(agg, {}, query_filters())."""
    _TOTAL = re.compile(r"\bTOTAL\s*\(", re.IGNORECASE)

    result = expr
    safety = 0
    while safety < 20:
        m = _TOTAL.search(result)
        if not m:
            break
        safety += 1

        extracted = _extract_function_args(result, m.end() - 1)
        if not extracted:
            break
        args, end_pos = extracted
        if args:
            inner = args[0].strip()
            replacement = f"group_aggregate ( {inner} , {{}} , query_filters () )"
            result = result[:m.start()] + replacement + result[end_pos:]

    return result


# ---------------------------------------------------------------------------
# 14. Division-by-zero guard
# ---------------------------------------------------------------------------

def guard_division(expr: str) -> str:
    """Wrap bare division in safe_divide where the denominator could be zero.

    Pattern: expr / expr → safe_divide(expr, expr)
    Only applies to top-level divisions (not inside function calls).
    """
    # Simple heuristic: look for [col] / [col] or ) / ( patterns
    # We won't do this automatically — it's too easy to break complex expressions.
    # Instead, flag it for review.
    return expr


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


# ---------------------------------------------------------------------------
# 16. Parameter name conflict detection
# ---------------------------------------------------------------------------

def detect_param_conflicts(
    formulas: list[dict],
    parameters: list[dict],
) -> dict[str, str]:
    """Detect formula names that collide with parameter names.

    Returns: { formula_caption: "conflict_reason" }
    """
    param_names = set()
    for p in parameters:
        caption = p.get("caption", p.get("name", ""))
        if caption:
            param_names.add(caption)

    conflicts: dict[str, str] = {}
    for f in formulas:
        caption = f.get("caption", "")
        if caption in param_names:
            raw = f.get("formula", "").strip()
            # Check if it's a pass-through (just returns the parameter)
            stripped = strip_parameter_prefix(raw)
            if stripped.strip() == f"[{caption}]" or stripped.strip() == caption:
                conflicts[caption] = "pass-through — omit formula, use parameter directly"
            else:
                conflicts[caption] = "name collision — rename formula"

    return conflicts


# ---------------------------------------------------------------------------
# 17. Operator spacing (BL-046 #4 / BL-050 #6)
# ---------------------------------------------------------------------------

_BINARY_OPS = re.compile(
    r"(?<=[^\s=!<>])([+\-*/=]|!=|>=|<=|<>|<(?!=)|>(?!=))(?=[^\s=])",
)

def normalize_operator_spacing(expr: str) -> str:
    """Ensure spaces around binary operators.

    ThoughtSpot requires spaces: [A] - [B], not [A]-[B].
    Preserves operators inside strings, brackets, and function names.
    """
    result: list[str] = []
    in_single = False
    in_double = False
    in_bracket = 0
    i = 0

    while i < len(expr):
        c = expr[i]

        if c == "'" and not in_double:
            in_single = not in_single
            result.append(c)
            i += 1
            continue
        if c == '"' and not in_single:
            in_double = not in_double
            result.append(c)
            i += 1
            continue
        if in_single or in_double:
            result.append(c)
            i += 1
            continue

        if c == '[':
            in_bracket += 1
            result.append(c)
            i += 1
            continue
        if c == ']':
            in_bracket -= 1
            result.append(c)
            i += 1
            continue
        if in_bracket > 0:
            result.append(c)
            i += 1
            continue

        if c in ('+', '-', '*', '/') and c != '-':
            # Check for multi-char ops
            if c == '/' and i + 1 < len(expr) and expr[i + 1] == '/':
                result.append(c)
                i += 1
                continue
            left = ''.join(result).rstrip()
            if left and left[-1] not in ('(', ',', ' '):
                if not result[-1:] == [' ']:
                    result.append(' ')
            result.append(c)
            if i + 1 < len(expr) and expr[i + 1] != ' ':
                result.append(' ')
            i += 1
            continue
        if c == '-':
            # Distinguish unary minus from binary minus
            left_stripped = ''.join(result).rstrip()
            if left_stripped and left_stripped[-1] in (')', ']', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9'):
                if not result[-1:] == [' ']:
                    result.append(' ')
                result.append(c)
                if i + 1 < len(expr) and expr[i + 1] != ' ':
                    result.append(' ')
                i += 1
                continue

        result.append(c)
        i += 1

    return ''.join(result)


# ---------------------------------------------------------------------------
# 18. rank() argument completion (BL-046 #3 / BL-050 #7)
# ---------------------------------------------------------------------------

def complete_rank_args(expr: str) -> str:
    """Ensure rank() has two arguments: expression and sort order.

    ThoughtSpot rank(expr) fails — must be rank(expr, 'asc'|'desc').
    Defaults to 'desc' when not specified (matches Tableau default).
    """
    _RANK = re.compile(r"\brank\s*\(", re.IGNORECASE)

    result = expr
    safety = 0
    while safety < 20:
        m = _RANK.search(result)
        if not m:
            break
        safety += 1

        extracted = _extract_function_args(result, m.end() - 1)
        if not extracted:
            break
        args, end_pos = extracted

        if len(args) == 1:
            inner = args[0].strip()
            replacement = f"rank ( {inner} , 'desc' )"
            result = result[:m.start()] + replacement + result[end_pos:]
        else:
            break

    return result


# ---------------------------------------------------------------------------
# 19. Parameter name sanitisation (BL-050 #6)
# ---------------------------------------------------------------------------

_PARAM_UNSAFE = re.compile(r"[/\\:*?\"<>|]")

def sanitise_parameter_name(name: str) -> str:
    """Remove characters not allowed in ThoughtSpot parameter names."""
    return _PARAM_UNSAFE.sub(" ", name).strip()


def sanitise_parameter_refs(
    expr: str,
    param_renames: dict[str, str],
) -> str:
    """Rewrite formula references to use sanitised parameter names.

    param_renames: {"Platform/Placement": "Platform Placement", ...}
    """
    for old_name, new_name in param_renames.items():
        expr = expr.replace(f"[{old_name}]", f"[{new_name}]")
    return expr


def build_param_renames(parameters: list[dict]) -> dict[str, str]:
    """Detect parameters needing sanitisation and build a rename map.

    Returns: { original_name: sanitised_name } for names that changed.
    """
    renames: dict[str, str] = {}
    for p in parameters:
        caption = p.get("caption", p.get("name", ""))
        if caption and _PARAM_UNSAFE.search(caption):
            renames[caption] = sanitise_parameter_name(caption)
    return renames


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
# 21. Strip ifnull(X, 0) wrapping for measures (BL-046 #1)
# ---------------------------------------------------------------------------

def strip_ifnull_zero(expr: str) -> str:
    """Strip ifnull(X, 0) → X.

    ThoughtSpot handles NULL aggregation automatically. Wrapping measures
    in ifnull(..., 0) is unnecessary and can change semantics (e.g., AVG
    with zeros vs excluded NULLs).
    """
    _IFNULL = re.compile(r"\bifnull\s*\(", re.IGNORECASE)
    result = expr
    safety = 0
    offset = 0
    while safety < 50:
        m = _IFNULL.search(result, offset)
        if not m:
            break
        safety += 1
        extracted = _extract_function_args(result, m.end() - 1)
        if not extracted:
            offset = m.end()
            continue
        args, end_pos = extracted
        if len(args) == 2 and args[1].strip() == '0':
            inner = args[0].strip()
            result = result[:m.start()] + inner + result[end_pos:]
        else:
            offset = end_pos
    return result


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


# ---------------------------------------------------------------------------
# TML YAML serialization — proper quoting for formula expressions
# ---------------------------------------------------------------------------

def dump_tml_yaml(data: dict) -> str:
    """Serialize a TML dict to YAML with proper quoting for formula expressions.

    Handles two problems that plain yaml.dump gets wrong for TML:
    1. Formula expressions contain : [] {} # which YAML misinterprets
    2. Long expressions get line-wrapped, producing invalid multi-line TML

    Values matching TML-sensitive patterns are double-quoted automatically.
    """
    import yaml

    class _QuotedStr(str):
        pass

    def _quoted_representer(dumper: yaml.Dumper, val: str) -> yaml.ScalarNode:
        return dumper.represent_scalar("tag:yaml.org,2002:str", val, style='"')

    _NEEDS_QUOTING = re.compile(r"[\[\]{}:#>|&*!%@`]|^\s|^'|^\"")

    def _quote_values(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {_quote_values(k): _quote_values(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_quote_values(v) for v in obj]
        if isinstance(obj, str) and _NEEDS_QUOTING.search(obj):
            return _QuotedStr(obj)
        return obj

    class _TmlDumper(yaml.Dumper):
        pass

    _TmlDumper.add_representer(_QuotedStr, _quoted_representer)

    quoted_data = _quote_values(data)
    return yaml.dump(
        quoted_data,
        Dumper=_TmlDumper,
        default_flow_style=False,
        allow_unicode=True,
        width=100000,
    )
