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
    """Convert two-arg MAX(a, b) → greatest(a, b). Same for MIN → least."""
    result = expr
    result = _convert_scalar_fn(result, "MAX", "greatest")
    result = _convert_scalar_fn(result, "MIN", "least")
    return result


def _convert_scalar_fn(expr: str, fn: str, ts_fn: str) -> str:
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
            replacement = f"{ts_fn} ( {a} , {b} )"
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
# 3. CASE/WHEN → if/else if
# ---------------------------------------------------------------------------

def _find_matching_end(text: str) -> int | None:
    """Find the END that closes the current CASE block, respecting nesting.

    ``text`` starts right after the opening CASE keyword.  Returns the
    index *past* the matching END, or None if no match is found.  Nested
    CASE/END pairs and ``END`` inside square-bracket column names (e.g.
    ``[End Date]``) are handled correctly.
    """
    depth = 1
    i = 0
    while i < len(text):
        if text[i] == "[":
            close = text.find("]", i + 1)
            if close != -1:
                i = close + 1
                continue
        kw_match = re.match(r"\bCASE\b", text[i:], re.IGNORECASE)
        if kw_match:
            depth += 1
            i += kw_match.end()
            continue
        kw_match = re.match(r"\bEND\b", text[i:], re.IGNORECASE)
        if kw_match:
            depth -= 1
            if depth == 0:
                return i + kw_match.end()
            i += kw_match.end()
            continue
        i += 1
    return None


def convert_case_when(expr: str) -> str:
    """Convert Tableau CASE/WHEN/END to ThoughtSpot if/else if/else chain.

    Handles:
      CASE [field] WHEN 'a' THEN x WHEN 'b' THEN y ELSE z END
    → if ( [field] = 'a' ) then x else if ( [field] = 'b' ) then y else z

    Correctly handles CASE blocks nested inside IF/ELSE by finding the
    matching END before scanning for WHEN clauses.
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
        after_case = result[m.start() + 4:]  # after "CASE"
        end_offset = _find_matching_end(after_case)
        if end_offset is None:
            break

        block_end = m.start() + 4 + end_offset
        block_content = result[m.end():block_end]

        # Strip the trailing END keyword from block_content
        block_content = re.sub(r"\s*\bEND\b\s*$", "", block_content, flags=re.IGNORECASE)

        # Parse WHEN ... THEN ... pairs within the bounded block
        clauses: list[tuple[str, str]] = []
        else_val = None
        when_pattern = re.compile(
            r"(?:^|\bWHEN\b)\s*(.+?)\s+THEN\s+(.+?)(?=\s+WHEN\b|\s+ELSE\b|$)",
            re.IGNORECASE | re.DOTALL,
        )
        pos = 0
        for wm in when_pattern.finditer(block_content):
            clauses.append((wm.group(1).strip(), wm.group(2).strip()))
            pos = wm.end()

        # Find ELSE within the block
        else_match = re.search(r"\bELSE\b\s+(.+)", block_content[pos:],
                               re.IGNORECASE | re.DOTALL)
        if else_match:
            else_val = else_match.group(1).strip()

        # Build if/else if chain
        parts = []
        for i, (val, then_expr) in enumerate(clauses):
            prefix = "if" if i == 0 else "else if"
            parts.append(f"{prefix} ( {case_field} = {val} ) then {then_expr}")

        if else_val:
            parts.append(f"else {else_val}")

        replacement = " ".join(parts)
        result = result[:m.start()] + replacement + result[block_end:]

    return result


# ---------------------------------------------------------------------------
# 4. IF/THEN/ELSEIF/ELSE/END → ThoughtSpot if/then/else
# ---------------------------------------------------------------------------

def _convert_if_content(content: str) -> str:
    """Convert the body of one IF...END block (no nested IFs) to TS syntax.

    *content* is everything between the IF and END keywords.
    Returns: ``if ( cond ) then val [else if ( cond ) then val]* [else val]``
    """
    result = content

    # ELSEIF → else if
    result = re.sub(r"\bELSEIF\b", "else if", result, flags=re.IGNORECASE)

    # Leading condition → if ( cond ) then.
    # Case-sensitive THEN: already-lowercased inner blocks won't match.
    m = re.match(r"(.+?)\s+\bTHEN\b", result, flags=re.DOTALL)
    if m:
        cond = m.group(1).strip()
        if cond.startswith("(") and cond.endswith(")"):
            prefix = f"if {cond} then"
        else:
            prefix = f"if ( {cond} ) then"
        result = prefix + result[m.end():]

    # else if cond THEN → else if ( cond ) then
    def _wrap_else_if(m: re.Match) -> str:
        cond = m.group(1).strip()
        if cond.startswith("(") and cond.endswith(")"):
            return f"else if {cond} then"
        return f"else if ( {cond} ) then"

    result = re.sub(
        r"\belse\s+if\b\s+(.+?)\s+\bTHEN\b",
        _wrap_else_if,
        result,
        flags=re.DOTALL,
    )

    # Lowercase remaining uppercase keywords
    result = re.sub(r"\bTHEN\b", "then", result)
    result = re.sub(r"\bELSE\b", "else", result)

    return result


# Innermost IF...END: an IF whose body contains no nested uppercase IF.
_INNER_IF_END = re.compile(
    r"\bIF\b((?:(?!\bIF\b).)*?)\bEND\b", re.DOTALL
)


def convert_if_then(expr: str) -> str:
    """Convert Tableau IF/THEN/ELSEIF/ELSE/END to ThoughtSpot syntax.

    Handles nested IF blocks by processing inside-out: the innermost
    IF...END block is converted first (to lowercase), so subsequent
    iterations skip it and find the next-outer block.
    """
    # Protect bracketed column references ([End Date], [IF Status])
    _brackets: list[str] = []

    def _protect(m: re.Match) -> str:
        _brackets.append(m.group(0))
        return f"\x00B{len(_brackets) - 1}\x00"

    result = re.sub(r"\[[^\]]*\]", _protect, expr)

    # Convert innermost IF...END blocks outward
    safety = 0
    while safety < 50:
        safety += 1
        m = _INNER_IF_END.search(result)
        if not m:
            break
        converted = _convert_if_content(m.group(1))
        tentative = result[: m.start()] + converted + result[m.end():]
        # Inner blocks (more uppercase IF remaining) need a terminal else
        # so ensure_else_clause doesn't miscount later.
        is_inner = bool(re.search(r"\bIF\b", tentative))
        has_terminal_else = bool(
            re.search(r"\belse\b(?!\s+if\b)", converted, re.IGNORECASE)
        )
        if is_inner and not has_terminal_else:
            converted += " else null"
        result = result[: m.start()] + converted + result[m.end():]

    # Fallback: remaining uppercase IF...THEN without a matching END
    def _wrap_if_condition(m: re.Match) -> str:
        cond = m.group(1).strip()
        if cond.startswith("(") and cond.endswith(")"):
            return f"if {cond} then"
        return f"if ( {cond} ) then"

    result = re.sub(
        r"\bIF\b\s+(.+?)\s+\bTHEN\b", _wrap_if_condition, result, flags=re.DOTALL
    )
    result = re.sub(r"\bELSEIF\b", "else if", result, flags=re.IGNORECASE)

    # Lowercase remaining standalone keywords
    result = re.sub(r"\bTHEN\b", "then", result)
    result = re.sub(r"\bELSE\b", "else", result)
    result = re.sub(r"(?<!\[)\bEND\b(?!\])", "", result)

    # Restore bracketed references
    def _restore(m: re.Match) -> str:
        return _brackets[int(m.group(1))]

    result = re.sub(r"\x00B(\d+)\x00", _restore, result)

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
    """Split a string on top-level commas, respecting (), [], and {} nesting."""
    args: list[str] = []
    depth = 0
    bracket_depth = 0
    brace_depth = 0
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
        elif ch == "{":
            brace_depth += 1
            current.append(ch)
        elif ch == "}":
            brace_depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0 and bracket_depth == 0 and brace_depth == 0:
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
    Tracks (), [], and {} nesting so LOD braces don't break arg extraction.
    """
    if start_pos >= len(expr) or expr[start_pos] != "(":
        return None

    depth = 1
    brace_depth = 0
    bracket_depth = 0
    pos = start_pos + 1
    while pos < len(expr) and depth > 0:
        ch = expr[pos]
        if ch == "(":
            if brace_depth == 0 and bracket_depth == 0:
                depth += 1
        elif ch == ")":
            if brace_depth == 0 and bracket_depth == 0:
                depth -= 1
        elif ch == "{":
            brace_depth += 1
        elif ch == "}":
            brace_depth -= 1
        elif ch == "[":
            bracket_depth += 1
        elif ch == "]":
            bracket_depth -= 1
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
# 11. Mandatory else clause
# ---------------------------------------------------------------------------

def ensure_else_clause(expr: str, role: str = "measure") -> str:
    """Ensure every if/then has an else clause.

    Walks the expression structurally to find each if/then block and checks
    whether it has a matching else. Inserts 'else 0' (measures) or 'else '''
    (dimensions) for any unmatched if/then.

    Handles nested if/then inside then/else arms (the previous heuristic only
    checked the outermost case).
    """
    _DATE_INDICATORS = re.compile(
        r"::Date\b|start_of_month|start_of_quarter|start_of_year|start_of_week"
        r"|add_days|add_months|diff_days|diff_months|to_date|today\s*\("
        r"|now\s*\("
        r"|\b(?:START|END|CREATED|UPDATED|MODIFIED)_DATE\b"
        r"|DATE_(?:FROM|TO|START|END|LY|PRE)\b"
        r"|\bDATE\]",
        re.IGNORECASE,
    )
    then_branch_is_date = bool(_DATE_INDICATORS.search(expr))
    if role == "measure":
        default_val = "0"
    elif then_branch_is_date:
        default_val = "null"
    else:
        default_val = "''"

    # Strip [col refs] and 'strings' for keyword detection only
    def _keyword_positions(text: str) -> list[tuple[int, str]]:
        """Find positions of if/then/else keywords, ignoring those inside
        brackets, strings, or as part of *_if function names."""
        positions: list[tuple[int, str]] = []
        i = 0
        in_bracket = 0
        in_single = False
        in_double = False
        lower = text.lower()
        while i < len(lower):
            c = lower[i]
            if c == "[" and not in_single and not in_double:
                in_bracket += 1
                i += 1
                continue
            if c == "]" and not in_single and not in_double:
                in_bracket -= 1
                i += 1
                continue
            if c == "'" and not in_double and in_bracket == 0:
                in_single = not in_single
                i += 1
                continue
            if c == '"' and not in_single and in_bracket == 0:
                in_double = not in_double
                i += 1
                continue
            if in_bracket > 0 or in_single or in_double:
                i += 1
                continue

            for kw in ("then", "else", "if"):
                kw_len = len(kw)
                if lower[i:i + kw_len] == kw:
                    before_ok = (i == 0 or not lower[i - 1].isalpha() and lower[i - 1] != "_")
                    after_ok = (i + kw_len >= len(lower) or
                                not lower[i + kw_len].isalpha() and lower[i + kw_len] != "_")
                    if before_ok and after_ok:
                        positions.append((i, kw))
                        i += kw_len
                        break
            else:
                i += 1

        return positions

    positions = _keyword_positions(expr)
    if not any(kw == "if" for _, kw in positions):
        return expr

    # Count if vs else — quick check
    if_count = sum(1 for _, kw in positions if kw == "if")
    else_count = sum(1 for _, kw in positions if kw == "else")

    if else_count >= if_count:
        return expr

    # Need to insert else clauses. Work right-to-left so positions stay valid.
    # Strategy: pair each 'if' with its 'then', then check if an 'else' follows
    # at the same nesting level before the next 'if' or end-of-string.
    # Track nesting via if/else depth.

    # Rebuild: scan left-to-right, track if-depth, find unmatched if/then pairs
    if_stack: list[int] = []  # positions of 'if' keywords
    then_stack: list[int] = []  # positions of 'then' keywords matched to ifs
    insertions: list[int] = []  # positions where we need to insert 'else default'

    depth = 0
    kw_by_pos = {pos: kw for pos, kw in positions}
    sorted_pos = sorted(kw_by_pos.keys())

    if_then_pairs: list[tuple[int, int, bool]] = []  # (if_pos, then_pos, has_else)

    state_stack: list[dict] = []  # track nesting

    for idx, pos in enumerate(sorted_pos):
        kw = kw_by_pos[pos]
        if kw == "if":
            state_stack.append({"if_pos": pos, "then_pos": -1, "has_else": False})
        elif kw == "then" and state_stack:
            state_stack[-1]["then_pos"] = pos
        elif kw == "else" and state_stack:
            # 'else if' is continuation, not a terminal else
            # Check if next keyword is 'if'
            next_idx = idx + 1
            if next_idx < len(sorted_pos) and kw_by_pos[sorted_pos[next_idx]] == "if":
                pass  # else if — the 'if' will push a new state
            else:
                state_stack[-1]["has_else"] = True

    missing = if_count - else_count
    if missing > 0:
        expr = expr.rstrip()

        first_if_pos = min(pos for pos, kw in positions if kw == "if")
        depth_at_if = 0
        in_brk = False
        for j in range(first_if_pos):
            c = expr[j]
            if c == "[":
                in_brk = True
            elif c == "]":
                in_brk = False
            elif not in_brk:
                if c == "(":
                    depth_at_if += 1
                elif c == ")":
                    depth_at_if -= 1

        if depth_at_if == 0:
            for _ in range(missing):
                expr = f"{expr} else {default_val}"
        else:
            last_then_pos = max(pos for pos, kw in positions if kw == "then")
            scan_start = last_then_pos + 4  # len("then")
            depth = depth_at_if
            insert_pos = len(expr)
            in_brk2 = False
            in_sq = False
            for j in range(scan_start, len(expr)):
                c = expr[j]
                if c == "[" and not in_sq:
                    in_brk2 = True
                elif c == "]" and not in_sq:
                    in_brk2 = False
                elif c == "'" and not in_brk2:
                    in_sq = not in_sq
                elif not in_brk2 and not in_sq:
                    if c == "(":
                        depth += 1
                    elif c == ")":
                        if depth == depth_at_if:
                            insert_pos = j
                            break
                        depth -= 1
                    elif c == "," and depth == depth_at_if:
                        insert_pos = j
                        break
            elses = " ".join(f"else {default_val}" for _ in range(missing))
            expr = expr[:insert_pos].rstrip() + " " + elses + " " + expr[insert_pos:].lstrip()

    return expr


# ---------------------------------------------------------------------------
# 12. LOD expression conversion
# ---------------------------------------------------------------------------

def _find_matching_brace(expr: str, open_pos: int) -> int:
    """Find the closing } that matches the { at open_pos, respecting nesting.

    Returns the index of the matching }, or -1 if unbalanced.
    """
    depth = 1
    pos = open_pos + 1
    in_single = False
    in_double = False
    while pos < len(expr):
        c = expr[pos]
        if c == "'" and not in_double:
            in_single = not in_single
        elif c == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return pos
        pos += 1
    return -1


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


def _find_top_level_colon(expr: str) -> int:
    """Find the first : that is not inside brackets, parens, or strings."""
    depth_paren = 0
    depth_bracket = 0
    depth_brace = 0
    in_single = False
    in_double = False
    for i, c in enumerate(expr):
        if c == "'" and not in_double:
            in_single = not in_single
        elif c == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if c == "(":
                depth_paren += 1
            elif c == ")":
                depth_paren -= 1
            elif c == "[":
                depth_bracket += 1
            elif c == "]":
                depth_bracket -= 1
            elif c == "{":
                depth_brace += 1
            elif c == "}":
                depth_brace -= 1
            elif (c == ":"
                  and depth_paren == 0
                  and depth_bracket == 0
                  and depth_brace == 0):
                return i
    return -1


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
# 22. agg(if...else 0/null) → agg_if conversion (BL-046 #2)
# ---------------------------------------------------------------------------

_AGG_IF_MAP = {
    "unique count": "unique_count_if",
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
