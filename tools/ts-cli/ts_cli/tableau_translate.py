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


# ---------------------------------------------------------------------------
# Pre-0. Strip Tableau // line comments (BL-056)
# ---------------------------------------------------------------------------

def strip_comments(formula: str) -> str:
    """Strip Tableau // line comments, preserving // inside string literals."""
    result: list[str] = []
    in_single = False
    in_double = False
    i = 0
    while i < len(formula):
        c = formula[i]
        if c == "'" and not in_double:
            in_single = not in_single
            result.append(c)
            i += 1
        elif c == '"' and not in_single:
            in_double = not in_double
            result.append(c)
            i += 1
        elif (c == '/' and i + 1 < len(formula) and formula[i + 1] == '/'
              and not in_single and not in_double):
            newline = formula.find('\n', i)
            if newline == -1:
                break
            i = newline
        else:
            result.append(c)
            i += 1
    return ''.join(result).strip()


# ---------------------------------------------------------------------------
# Pre-1. Custom SQL Query alias resolution (BL-057)
# ---------------------------------------------------------------------------

def rewrite_csq_aliases(
    expr: str,
    csq_to_table: dict[str, str],
) -> str:
    """Rewrite [COL (Custom SQL Query N)] → [TABLE::COL].

    csq_to_table: {"Custom SQL Query8": "FORECAST", ...}
    """
    if not csq_to_table:
        return expr

    _CSQ_REF = re.compile(
        r"\[([^\]]+?)\s+\((Custom SQL Query\s*\d+)\)\]",
        re.IGNORECASE,
    )

    def _replace(m: re.Match) -> str:
        col = m.group(1).strip()
        csq = m.group(2).strip()
        csq_norm = re.sub(r"\s+", " ", csq)
        table = csq_to_table.get(csq_norm)
        if table:
            return f"[{table}::{col}]"
        return m.group(0)

    return _CSQ_REF.sub(_replace, expr)


def build_csq_column_map(
    csq_columns: dict[str, set[str]],
    model_tables: dict[str, set[str]],
    threshold: float = 0.8,
) -> tuple[dict[str, str], dict[str, tuple[str, float]]]:
    """Match Custom SQL Query aliases to model tables by column overlap.

    Returns (definitive_map, ambiguous_map).
    definitive_map: {csq_name: table_name} for matches >= threshold.
    ambiguous_map: {csq_name: (best_table, score)} for matches >= 0.5 but < threshold.
    """
    definitive: dict[str, str] = {}
    ambiguous: dict[str, tuple[str, float]] = {}

    for csq_name, csq_cols in csq_columns.items():
        if not csq_cols:
            continue
        best_match = None
        best_score = 0.0
        for table_name, table_cols in model_tables.items():
            overlap = csq_cols & table_cols
            score = len(overlap) / len(csq_cols)
            if score > best_score:
                best_match = table_name
                best_score = score
        if best_match and best_score >= threshold:
            definitive[csq_name] = best_match
        elif best_match and best_score >= 0.5:
            ambiguous[csq_name] = (best_match, best_score)

    return definitive, ambiguous


# ---------------------------------------------------------------------------
# Pre-2. No-keyword LOD: {AGG([col])} → group_aggregate (BL-052)
# ---------------------------------------------------------------------------

_NO_KEYWORD_LOD_AGG_MAP = {
    "COUNTD": "unique count",
    "COUNT": "count",
    "SUM": "sum",
    "AVG": "average",
    "MAX": "max",
    "MIN": "min",
    "MEDIAN": "median",
    "ATTR": "max",
}

def convert_no_keyword_lod(expr: str) -> str:
    """Convert {AGG([col])} (no FIXED/INCLUDE/EXCLUDE) → group_aggregate.

    Only matches braces with no keyword before the aggregate — the keyword forms
    are handled by convert_lod().
    """
    _PATTERN = re.compile(
        r"\{\s*(COUNTD|COUNT|SUM|AVG|MAX|MIN|MEDIAN|ATTR)\s*\((.+?)\)\s*\}",
        re.IGNORECASE,
    )

    def _replace(m: re.Match) -> str:
        agg = m.group(1).upper()
        inner = m.group(2).strip()
        ts_agg = _NO_KEYWORD_LOD_AGG_MAP.get(agg, agg.lower())
        return f"group_aggregate ( {ts_agg} ( {inner} ) , {{}} , query_filters () )"

    return _PATTERN.sub(_replace, expr)


# ---------------------------------------------------------------------------
# Pre-3. Scalar MAX(a,b) / MIN(a,b) detection (BL-055)
# ---------------------------------------------------------------------------

def convert_scalar_max_min(expr: str) -> str:
    """Convert two-arg MAX(a, b) → if(a > b) then a else b. Same for MIN."""
    result = expr
    result = _convert_scalar_fn(result, "MAX", ">")
    result = _convert_scalar_fn(result, "MIN", "<")
    return result


def _convert_scalar_fn(expr: str, fn: str, op: str) -> str:
    _PAT = re.compile(rf"\b{fn}\s*\(", re.IGNORECASE)

    result = expr
    safety = 0
    while safety < 50:
        m = _PAT.search(result)
        if not m:
            break
        safety += 1

        extracted = _extract_function_args(result, m.end() - 1)
        if not extracted:
            break
        args, end_pos = extracted

        if len(args) == 2:
            a = args[0].strip()
            b = args[1].strip()
            if b == "0":
                replacement = f"if ( {a} {op} 0 ) then {a} else 0"
            else:
                replacement = f"if ( {a} {op} {b} ) then {a} else {b}"
            result = result[:m.start()] + replacement + result[end_pos:]
        elif len(args) == 1:
            break

    return result


# ---------------------------------------------------------------------------
# Pre-4. Date arithmetic: DATE()+N → add_days (BL-054)
# ---------------------------------------------------------------------------

def rewrite_date_arithmetic(expr: str, date_columns: set[str] | None = None) -> str:
    """Rewrite date +/- integer patterns to add_days().

    Only rewrites when one side is clearly a date:
    - DATE([col]) + N / DATE([col]) - N (always — DATE() call is explicit)
    - [date_col] + N / [date_col] - N (only if col is in date_columns set)
    """
    date_columns = date_columns or set()
    date_columns_upper = {c.upper() for c in date_columns}

    # Pattern 1: DATE(...) +/- N — always a date
    _DATE_CALL = re.compile(
        r"(date\s*\([^)]+\))\s*([+-])\s*(\d+)",
        re.IGNORECASE,
    )

    def _replace_date_call(m: re.Match) -> str:
        date_expr = m.group(1).strip()
        operator = m.group(2)
        n = m.group(3)
        if operator == "-":
            return f"add_days ( {date_expr} , -{n} )"
        return f"add_days ( {date_expr} , {n} )"

    result = _DATE_CALL.sub(_replace_date_call, expr)

    # Pattern 2: [col] +/- N where col is a known date column
    if date_columns_upper:
        _COL_ARITH = re.compile(
            r"\[([^\]]+)\]\s*([+-])\s*(\d+)",
        )

        def _replace_col(m: re.Match) -> str:
            col = m.group(1).strip()
            col_name = col.split("::")[-1] if "::" in col else col
            if col_name.upper() in date_columns_upper:
                operator = m.group(2)
                n = m.group(3)
                if operator == "-":
                    return f"add_days ( [{col}] , -{n} )"
                return f"add_days ( [{col}] , {n} )"
            return m.group(0)

        result = _COL_ARITH.sub(_replace_col, result)

    return result


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
    """Build [Calculation_NNN] → caption map from formula list."""
    result: dict[str, str] = {}
    for f in formulas:
        name = f.get("name", "")
        caption = f.get("caption", "")
        if name and name.startswith("Calculation_") and caption:
            result[f"[{name}]"] = caption
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
# 3. CASE/WHEN → if/else if
# ---------------------------------------------------------------------------

def convert_case_when(expr: str) -> str:
    """Convert Tableau CASE/WHEN/END to ThoughtSpot if/else if/else chain.

    Handles:
      CASE [field] WHEN 'a' THEN x WHEN 'b' THEN y ELSE z END
    → if ( [field] = 'a' ) then x else if ( [field] = 'b' ) then y else z
    """
    _CASE = re.compile(
        r"\bCASE\b\s+(.+?)\s+WHEN\b",
        re.IGNORECASE | re.DOTALL,
    )

    result = expr
    safety = 0
    while safety < 20:
        m = _CASE.search(result)
        if not m:
            break
        safety += 1

        case_field = m.group(1).strip()
        rest = result[m.end():]

        # Parse WHEN ... THEN ... pairs
        clauses: list[tuple[str, str]] = []
        else_val = None
        pos = 0
        when_pattern = re.compile(
            r"(?:^|\bWHEN\b)\s*(.+?)\s+THEN\s+(.+?)(?=\s+WHEN\b|\s+ELSE\b|\s+END\b)",
            re.IGNORECASE | re.DOTALL,
        )
        for wm in when_pattern.finditer(rest):
            clauses.append((wm.group(1).strip(), wm.group(2).strip()))
            pos = wm.end()

        # Find ELSE
        else_match = re.search(r"\bELSE\b\s+(.+?)\s+END\b", rest[pos:], re.IGNORECASE | re.DOTALL)
        if else_match:
            else_val = else_match.group(1).strip()
            end_pos = m.start() + len("CASE") + len(m.group(1)) + len(" WHEN") + pos + else_match.end()
        else:
            end_match = re.search(r"\bEND\b", rest[pos:], re.IGNORECASE)
            if end_match:
                end_pos = m.start() + len("CASE") + len(m.group(1)) + len(" WHEN") + pos + end_match.end()
            else:
                break

        # Build if/else if chain
        parts = []
        for i, (val, then_expr) in enumerate(clauses):
            prefix = "if" if i == 0 else "else if"
            parts.append(f"{prefix} ( {case_field} = {val} ) then {then_expr}")

        if else_val:
            parts.append(f"else {else_val}")

        replacement = " ".join(parts)
        result = result[:m.start()] + replacement + result[end_pos:]

    return result


# ---------------------------------------------------------------------------
# 4. IF/THEN/ELSEIF/ELSE/END → ThoughtSpot if/then/else
# ---------------------------------------------------------------------------

def convert_if_then(expr: str) -> str:
    """Convert Tableau IF/THEN/ELSEIF/ELSE/END to ThoughtSpot syntax.

    - Strip END keyword
    - ELSEIF → else if
    - Wrap conditions in parentheses: IF cond THEN → if ( cond ) then
    """
    result = expr

    # ELSEIF → else if (must happen before IF conversion)
    result = re.sub(r"\bELSEIF\b", "else if", result, flags=re.IGNORECASE)

    # Strip END keyword — but NOT inside square brackets (e.g. [End Date])
    # Use negative lookbehind for [ to avoid corrupting column references
    result = re.sub(r"(?<!\[)\bEND\b(?!\])\s*$", "", result, flags=re.IGNORECASE).rstrip()
    result = re.sub(r"(?<!\[)\bEND\b(?!\])(?=\s*[)\]/,])", "", result, flags=re.IGNORECASE)
    result = re.sub(r"(?<!\[)\bEND\b(?!\])", "", result, flags=re.IGNORECASE)

    # IF ... THEN → if ( ... ) then
    # Match IF followed by content up to THEN
    def _wrap_if_condition(m: re.Match) -> str:
        cond = m.group(1).strip()
        # Don't double-wrap if already parenthesized
        if cond.startswith("(") and cond.endswith(")"):
            return f"if {cond} then"
        return f"if ( {cond} ) then"

    result = re.sub(
        r"\bIF\b\s+(.+?)\s+\bTHEN\b",
        _wrap_if_condition,
        result,
        flags=re.IGNORECASE,
    )

    # else if ... then → else if ( ... ) then
    def _wrap_else_if_condition(m: re.Match) -> str:
        cond = m.group(1).strip()
        if cond.startswith("(") and cond.endswith(")"):
            return f"else if {cond} then"
        return f"else if ( {cond} ) then"

    result = re.sub(
        r"\belse\s+if\b\s+(.+?)\s+\bthen\b",
        _wrap_else_if_condition,
        result,
        flags=re.IGNORECASE,
    )

    # Lowercase THEN, ELSE
    result = re.sub(r"\bTHEN\b", "then", result)
    result = re.sub(r"\bELSE\b", "else", result)

    return result


# ---------------------------------------------------------------------------
# 5. IIF(test, a, b) → if (test) then a else b
# ---------------------------------------------------------------------------

def convert_iif(expr: str) -> str:
    """Convert Tableau IIF(test, a, b) to ThoughtSpot if/then/else."""
    _IIF = re.compile(r"\bIIF\s*\(", re.IGNORECASE)

    result = expr
    safety = 0
    while safety < 20:
        m = _IIF.search(result)
        if not m:
            break
        safety += 1

        # Find matching close paren
        start = m.end()
        depth = 1
        pos = start
        while pos < len(result) and depth > 0:
            if result[pos] == "(":
                depth += 1
            elif result[pos] == ")":
                depth -= 1
            pos += 1

        if depth != 0:
            break

        inner = result[start:pos - 1]
        # Split on top-level commas (not inside parens)
        args = _split_args(inner)
        if len(args) >= 3:
            test = args[0].strip()
            a = args[1].strip()
            b = args[2].strip()
            replacement = f"if ( {test} ) then {a} else {b}"
            result = result[:m.start()] + replacement + result[pos:]

    return result


def _split_args(s: str) -> list[str]:
    """Split a string on top-level commas, respecting parentheses and brackets."""
    args: list[str] = []
    depth = 0
    bracket_depth = 0
    current: list[str] = []
    in_string = False
    string_char = ""

    for ch in s:
        if in_string:
            current.append(ch)
            if ch == string_char:
                in_string = False
            continue

        if ch in ("'", '"'):
            in_string = True
            string_char = ch
            current.append(ch)
        elif ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "[":
            bracket_depth += 1
            current.append(ch)
        elif ch == "]":
            bracket_depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0 and bracket_depth == 0:
            args.append("".join(current))
            current = []
        else:
            current.append(ch)

    if current:
        args.append("".join(current))
    return args


# ---------------------------------------------------------------------------
# 6. Function mapping
# ---------------------------------------------------------------------------

_FUNCTION_MAP: list[tuple[re.Pattern, str | callable]] = []


def _build_function_map() -> list[tuple[re.Pattern, Any]]:
    """Build regex → replacement pairs for Tableau → ThoughtSpot functions."""
    mappings: list[tuple[str, str | Any]] = [
        # Null handling
        (r"\bZN\s*\(", "_ZN_HANDLER"),
        (r"\bIFNULL\s*\(", "ifnull ( "),
        (r"\bISNULL\s*\(", "isnull ( "),

        # Aggregates
        (r"\bCOUNTD\s*\(", "unique count ( "),
        (r"\bAVG\s*\(", "average ( "),
        (r"\bATTR\s*\(", "("),  # ATTR just strips to the inner ref
        (r"\bSTDEV\s*\(", "stddev ( "),
        (r"\bMEDIAN\s*\(", "median ( "),
        (r"\bSUM\s*\(", "sum ( "),
        (r"\bMIN\s*\(", "min ( "),
        (r"\bMAX\s*\(", "max ( "),
        (r"\bCOUNT\s*\(", "count ( "),

        # String
        (r"\bCONTAINS\s*\(", "contains ( "),
        (r"\bLEN\s*\(", "strlen ( "),
        (r"\bTRIM\s*\(", "trim ( "),
        (r"\bREPLACE\s*\(", "replace ( "),

        # LEFT/RIGHT/MID are handled specially
        (r"\bLEFT\s*\(", "_LEFT_HANDLER"),
        (r"\bRIGHT\s*\(", "_RIGHT_HANDLER"),
        (r"\bMID\s*\(", "_MID_HANDLER"),

        (r"\bFIND\s*\(", "strpos ( "),
        (r"\bUPPER\s*\(", "_UPPER_HANDLER"),
        (r"\bLOWER\s*\(", "_LOWER_HANDLER"),
        (r"\bSTARTSWITH\s*\(", "_STARTSWITH_HANDLER"),

        # Math
        (r"\bABS\s*\(", "abs ( "),
        (r"\bROUND\s*\(", "round ( "),
        (r"\bCEILING\s*\(", "ceil ( "),
        (r"\bFLOOR\s*\(", "floor ( "),
        (r"\bLOG\s*\(", "log10 ( "),
        (r"\bLN\s*\(", "ln ( "),
        (r"\bPOWER\s*\(", "pow ( "),
        (r"\bSQRT\s*\(", "sqrt ( "),
        (r"\bEXP\s*\(", "exp ( "),
        (r"\bSQUARE\s*\(", "_SQUARE_HANDLER"),

        # Type conversion
        (r"\bFLOAT\s*\(", "to_double ( "),
        (r"\bSTR\s*\(", "to_string ( "),

        # Date
        (r"\bTODAY\s*\(\s*\)", "today ( )"),
        (r"\bNOW\s*\(\s*\)", "now ( )"),
        (r"\bYEAR\s*\(", "year ( "),
        (r"\bMONTH\s*\(", "month_number ( "),
        (r"\bDAY\s*\(", "day ( "),
        (r"\bDATE\s*\(", "date ( "),
    ]

    compiled = []
    for pattern, replacement in mappings:
        compiled.append((re.compile(pattern, re.IGNORECASE), replacement))
    return compiled


_FUNCTION_MAP = _build_function_map()


def map_functions(expr: str) -> str:
    """Apply function name mappings from Tableau to ThoughtSpot."""
    result = expr

    for pattern, replacement in _FUNCTION_MAP:
        if isinstance(replacement, str) and not replacement.startswith("_"):
            result = pattern.sub(replacement, result)

    # ZN(x) → ifnull ( x , 0 )
    result = _convert_zn(result)

    return result


def _convert_zn(expr: str) -> str:
    """Convert ZN(x) → ifnull(x, 0)."""
    _ZN = re.compile(r"\bZN\s*\(", re.IGNORECASE)

    result = expr
    safety = 0
    while safety < 50:
        m = _ZN.search(result)
        if not m:
            break
        safety += 1

        start = m.end()
        depth = 1
        pos = start
        while pos < len(result) and depth > 0:
            if result[pos] == "(":
                depth += 1
            elif result[pos] == ")":
                depth -= 1
            pos += 1

        if depth != 0:
            break

        inner = result[start:pos - 1].strip()
        replacement = f"ifnull ( {inner} , 0 )"
        result = result[:m.start()] + replacement + result[pos:]

    return result


# ---------------------------------------------------------------------------
# 7. Date function mapping
# ---------------------------------------------------------------------------

_DATETRUNC_UNIT_MAP = {
    "month": "start_of_month",
    "quarter": "start_of_quarter",
    "week": "start_of_week",
    "year": "start_of_year",
    "day": "date",
}

_DATEPART_UNIT_MAP = {
    "month": "month_number",
    "year": "year",
    "day": "day",
    "quarter": "quarter_number",
    "dayofyear": "day_number_of_year",
    "weekday": "day_of_week",
    "hour": "hour_of_day",
    "week": "week_number_of_year",
}

_DATEDIFF_UNIT_MAP = {
    "day": "diff_days",
    "month": "diff_months",
    "year": "diff_years",
}

_DATEADD_UNIT_MAP = {
    "day": "add_days",
    "month": "add_months",
    "year": "add_years",
}


def map_date_functions(expr: str) -> str:
    """Convert Tableau date functions to ThoughtSpot equivalents."""
    result = expr

    # DATETRUNC('unit', date) → start_of_unit ( date )
    result = _convert_datetrunc(result)

    # DATEDIFF('unit', start, end) → diff_unit ( end , start )  [reversed args]
    result = _convert_datediff(result)

    # DATEADD('unit', n, date) → add_unit ( date , n )  [reordered]
    result = _convert_dateadd(result)

    # DATEPART('unit', date) → unit_func ( date )
    result = _convert_datepart(result)

    # DATENAME('month', date) → month ( date )
    result = _convert_datename(result)

    return result


def _extract_function_args(expr: str, start_pos: int) -> tuple[list[str], int] | None:
    """Extract arguments from a function call starting at the open paren position.

    Returns (args_list, end_pos_after_close_paren) or None if unbalanced.
    """
    if start_pos >= len(expr) or expr[start_pos] != "(":
        return None

    depth = 1
    pos = start_pos + 1
    while pos < len(expr) and depth > 0:
        if expr[pos] == "(":
            depth += 1
        elif expr[pos] == ")":
            depth -= 1
        pos += 1

    if depth != 0:
        return None

    inner = expr[start_pos + 1:pos - 1]
    args = _split_args(inner)
    return (args, pos)


def _convert_datetrunc(expr: str) -> str:
    _PAT = re.compile(r"\bDATETRUNC\s*\(", re.IGNORECASE)
    result = expr
    safety = 0
    while safety < 20:
        m = _PAT.search(result)
        if not m:
            break
        safety += 1
        extracted = _extract_function_args(result, m.end() - 1)
        if not extracted:
            break
        args, end_pos = extracted
        if len(args) >= 2:
            unit = args[0].strip().strip("'\"").lower()
            date_expr = args[1].strip()
            ts_func = _DATETRUNC_UNIT_MAP.get(unit, f"start_of_{unit}")
            replacement = f"{ts_func} ( {date_expr} )"
            result = result[:m.start()] + replacement + result[end_pos:]
    return result


def _convert_datediff(expr: str) -> str:
    _PAT = re.compile(r"\bDATEDIFF\s*\(", re.IGNORECASE)
    result = expr
    safety = 0
    while safety < 20:
        m = _PAT.search(result)
        if not m:
            break
        safety += 1
        extracted = _extract_function_args(result, m.end() - 1)
        if not extracted:
            break
        args, end_pos = extracted
        if len(args) >= 3:
            unit = args[0].strip().strip("'\"").lower()
            start_date = args[1].strip()
            end_date = args[2].strip()
            ts_func = _DATEDIFF_UNIT_MAP.get(unit)
            if ts_func:
                # Note: arg order REVERSED — TS takes (end, start)
                replacement = f"{ts_func} ( {end_date} , {start_date} )"
            elif unit == "hour":
                replacement = f"diff_time ( {end_date} , {start_date} ) / 3600"
            elif unit == "minute":
                replacement = f"diff_time ( {end_date} , {start_date} ) / 60"
            elif unit == "week":
                replacement = f"diff_days ( {end_date} , {start_date} ) / 7"
            else:
                replacement = f"diff_{unit}s ( {end_date} , {start_date} )"
            result = result[:m.start()] + replacement + result[end_pos:]
    return result


def _convert_dateadd(expr: str) -> str:
    _PAT = re.compile(r"\bDATEADD\s*\(", re.IGNORECASE)
    result = expr
    safety = 0
    while safety < 20:
        m = _PAT.search(result)
        if not m:
            break
        safety += 1
        extracted = _extract_function_args(result, m.end() - 1)
        if not extracted:
            break
        args, end_pos = extracted
        if len(args) >= 3:
            unit = args[0].strip().strip("'\"").lower()
            n = args[1].strip()
            date_expr = args[2].strip()
            ts_func = _DATEADD_UNIT_MAP.get(unit, f"add_{unit}s")
            # Note: arg order changes — TS takes (date, n)
            replacement = f"{ts_func} ( {date_expr} , {n} )"
            result = result[:m.start()] + replacement + result[end_pos:]
    return result


def _convert_datepart(expr: str) -> str:
    _PAT = re.compile(r"\bDATEPART\s*\(", re.IGNORECASE)
    result = expr
    safety = 0
    while safety < 20:
        m = _PAT.search(result)
        if not m:
            break
        safety += 1
        extracted = _extract_function_args(result, m.end() - 1)
        if not extracted:
            break
        args, end_pos = extracted
        if len(args) >= 2:
            unit = args[0].strip().strip("'\"").lower()
            date_expr = args[1].strip()
            ts_func = _DATEPART_UNIT_MAP.get(unit, unit)
            replacement = f"{ts_func} ( {date_expr} )"
            result = result[:m.start()] + replacement + result[end_pos:]
    return result


def _convert_datename(expr: str) -> str:
    _PAT = re.compile(r"\bDATENAME\s*\(", re.IGNORECASE)
    result = expr
    safety = 0
    while safety < 20:
        m = _PAT.search(result)
        if not m:
            break
        safety += 1
        extracted = _extract_function_args(result, m.end() - 1)
        if not extracted:
            break
        args, end_pos = extracted
        if len(args) >= 2:
            unit = args[0].strip().strip("'\"").lower()
            date_expr = args[1].strip()
            if unit == "month":
                replacement = f"month ( {date_expr} )"
            else:
                replacement = f"{unit} ( {date_expr} )"
            result = result[:m.start()] + replacement + result[end_pos:]
    return result


# ---------------------------------------------------------------------------
# 8. String concatenation: + on strings → concat()
# ---------------------------------------------------------------------------

def convert_string_concat(expr: str, role: str = "dimension") -> str:
    """Convert string + concatenation to concat().

    Only applies when the formula role is 'dimension' (string context)
    or the expression contains STR() / to_string() / string literals adjacent to +.
    """
    if role == "measure" and "to_string" not in expr.lower() and "str(" not in expr.lower():
        return expr

    # Detect string + patterns:
    # - 'literal' + expr
    # - expr + 'literal'
    # - to_string(...) + expr
    _STR_PLUS = re.compile(
        r"((?:'[^']*'|to_string\s*\([^)]*\)|\[[^\]]+\])\s*)\+(\s*(?:'[^']*'|to_string\s*\([^)]*\)|\[[^\]]+\]))",
        re.IGNORECASE,
    )

    if not _STR_PLUS.search(expr):
        return expr

    # Split on top-level + and rebuild as concat()
    # This is a simplified approach — handles common patterns
    parts = _split_on_plus(expr)
    if len(parts) > 1 and _looks_like_string_concat(parts, role):
        inner = " , ".join(p.strip() for p in parts)
        return f"concat ( {inner} )"

    return expr


def _split_on_plus(expr: str) -> list[str]:
    """Split expression on top-level + operators (not inside parens/brackets/strings)."""
    parts: list[str] = []
    depth = 0
    bracket_depth = 0
    in_string = False
    current: list[str] = []

    for i, ch in enumerate(expr):
        if in_string:
            current.append(ch)
            if ch == "'":
                in_string = False
            continue

        if ch == "'":
            in_string = True
            current.append(ch)
        elif ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "[":
            bracket_depth += 1
            current.append(ch)
        elif ch == "]":
            bracket_depth -= 1
            current.append(ch)
        elif ch == "+" and depth == 0 and bracket_depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)

    if current:
        parts.append("".join(current))
    return parts


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
            return f"[{table}::{ref}]"
        return m.group(0)

    return _COL_REF.sub(_replace_col, expr)


# ---------------------------------------------------------------------------
# 11. Mandatory else clause
# ---------------------------------------------------------------------------

def ensure_else_clause(expr: str, role: str = "measure") -> str:
    """Ensure every if/then has an else clause.

    Adds 'else 0' for measures, 'else ''' for dimensions.
    """
    default_val = "0" if role == "measure" else "''"

    # Pattern: then X <end-or-nothing> without else
    # Look for 'then ... )' or 'then ... $' without 'else'
    # This is a heuristic — handles the common outermost case
    if "if" in expr.lower() and "then" in expr.lower():
        if "else" not in expr.lower():
            # Add else before the end
            expr = expr.rstrip()
            expr = f"{expr} else {default_val}"

    return expr


# ---------------------------------------------------------------------------
# 12. LOD expression conversion
# ---------------------------------------------------------------------------

def convert_lod(expr: str) -> str:
    """Convert Tableau LOD expressions to ThoughtSpot group_aggregate().

    Handles FIXED, INCLUDE, EXCLUDE keywords.
    """
    _LOD = re.compile(
        r"\{\s*(FIXED|INCLUDE|EXCLUDE)?\s*(.*?)\s*:\s*(.+?)\s*\}",
        re.IGNORECASE | re.DOTALL,
    )

    def _replace_lod(m: re.Match) -> str:
        keyword = (m.group(1) or "").upper().strip()
        dims_raw = m.group(2).strip()
        agg_expr = m.group(3).strip()

        # Parse dimension list
        if dims_raw:
            dims = [d.strip() for d in dims_raw.split(",")]
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

        return m.group(0)

    return _LOD.sub(_replace_lod, expr)


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

        if_count = len(re.findall(r'\bif\b', lower_s))
        then_count = len(re.findall(r'\bthen\b', lower_s))
        else_count = len(re.findall(r'\belse\b', lower_s))

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

        # Check for bare Tableau aggregate keywords
        if re.search(r"\bCOUNTD\b", expr):
            warnings.append("Unrewritten COUNTD (should be 'unique count')")

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
# 22. agg(if...else 0/null) → agg_if conversion (BL-046 #2)
# ---------------------------------------------------------------------------

_AGG_IF_MAP = {
    "sum": "sum_if",
    "count": "count_if",
    "average": "average_if",
}


def _find_last_top_level_else(s: str) -> int:
    """Find the position of the last top-level 'else' keyword."""
    depth = 0
    bracket_depth = 0
    in_string = False
    last_pos = -1
    i = 0
    while i < len(s):
        c = s[i]
        if in_string:
            if c == "'":
                in_string = False
            i += 1
            continue
        if c == "'":
            in_string = True
            i += 1
            continue
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
        elif c == '[':
            bracket_depth += 1
        elif c == ']':
            bracket_depth -= 1
        elif depth == 0 and bracket_depth == 0 and i + 4 <= len(s):
            if (s[i:i + 4].lower() == 'else'
                    and (i == 0 or not s[i - 1].isalnum())
                    and (i + 4 >= len(s) or not s[i + 4].isalnum())):
                last_pos = i
        i += 1
    return last_pos


def _parse_if_else_for_agg(s: str) -> tuple[str, str, str | None] | None:
    """Parse 'if ( condition ) then expr [else val]' using balanced parens.

    Returns (condition, then_expr, else_val) or None.
    else_val is None when there is no else clause (implicit null).
    """
    s = s.strip()
    if not re.match(r'^if\s*\(', s, re.IGNORECASE):
        return None

    paren_start = s.index('(')
    depth = 1
    pos = paren_start + 1
    while pos < len(s) and depth > 0:
        if s[pos] == '(':
            depth += 1
        elif s[pos] == ')':
            depth -= 1
        pos += 1
    if depth != 0:
        return None

    condition = s[paren_start + 1:pos - 1].strip()
    rest = s[pos:].strip()

    then_match = re.match(r'^then\s+', rest, re.IGNORECASE)
    if not then_match:
        return None

    after_then = rest[then_match.end():]
    last_else_pos = _find_last_top_level_else(after_then)
    if last_else_pos < 0:
        return condition, after_then.strip(), None

    then_expr = after_then[:last_else_pos].strip()
    else_val = after_then[last_else_pos + 4:].strip()
    return condition, then_expr, else_val


def convert_agg_if(expr: str) -> str:
    """Convert agg(if(cond) then expr [else 0/null]) → agg_if(cond, expr).

    Handles both explicit else 0/null and missing else (implicit null).
    ThoughtSpot's _if aggregates (sum_if, count_if, average_if) are simpler
    and eliminate the missing-else error class entirely.
    """
    for agg_name, if_name in _AGG_IF_MAP.items():
        pat = re.compile(rf"\b{agg_name}\s*\(", re.IGNORECASE)
        result = expr
        safety = 0
        offset = 0
        while safety < 50:
            m = pat.search(result, offset)
            if not m:
                break
            safety += 1
            extracted = _extract_function_args(result, m.end() - 1)
            if not extracted:
                offset = m.end()
                continue
            args, end_pos = extracted
            if len(args) == 1:
                inner = args[0].strip()
                parsed = _parse_if_else_for_agg(inner)
                if parsed:
                    condition, then_expr, else_val = parsed
                    if else_val is None or else_val.lower() in ('0', 'null'):
                        replacement = f"{if_name} ( {condition} , {then_expr} )"
                        result = result[:m.start()] + replacement + result[end_pos:]
                        continue
            offset = end_pos
        expr = result
    return expr


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

    # 14. Clean up whitespace
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
                })
                continue

            # Resolve cross-references
            resolved = resolve_cross_references(raw, dag, calc_id_map)
            entry["resolved_expr"] = resolved

            # Check for unresolved references
            if re.search(r"\[Calculation_\d+\]", resolved, re.IGNORECASE):
                skipped.append({
                    "name": caption,
                    "reason": "unresolved cross-reference",
                    "level": level,
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
                    "attempted_expr": expr,
                })
            else:
                column_type = "MEASURE" if role == "measure" else "ATTRIBUTE"
                output_name = name_clashes.get(caption, caption)
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
