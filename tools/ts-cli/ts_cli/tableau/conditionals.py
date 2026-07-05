"""Tableau conditional-logic transforms — CASE/IF/IIF and agg_if conversion.

Pure functions, no I/O. Converts Tableau's conditional constructs (CASE/WHEN,
IF/THEN/ELSEIF/ELSE, IIF) into ThoughtSpot if/then/else syntax, ensures every
if/then has a matching else clause, and folds agg(if...else 0/null) patterns
into ThoughtSpot's *_if aggregates (sum_if, count_if, average_if, unique_count_if).
"""
from __future__ import annotations

import re

from ts_cli.tableau.parsing import (
    _extract_function_args,
    _find_last_top_level_else,
    _find_matching_end,
    _split_args,
)


# ---------------------------------------------------------------------------
# Boolean aggregation: MAX/MIN/SUM(<comparison>) → agg(if <cmp> then 1 else 0)
# ---------------------------------------------------------------------------

# agg ( [col] <op> 'literal'|number ) — a bare comparison as the sole arg.
_BOOL_AGG = re.compile(
    r"\b(max|min|sum)\s*\(\s*"
    r"(\[[^\]]+\]\s*(?:<=|>=|<>|!=|=|<|>)\s*(?:'[^']*'|-?\d[\d.]*))"
    r"\s*\)",
    re.IGNORECASE,
)


def convert_boolean_aggregate(expr: str) -> str:
    """Rewrite Tableau boolean aggregation to valid ThoughtSpot syntax.

    Tableau allows ``MAX([x]='v')`` — aggregating a boolean comparison (true if
    any row matches). ThoughtSpot rejects a bare comparison inside ``max()``.
    Rewrite the inner comparison to a 0/1 indicator:

        MAX([LEVEL]='brand')          → max ( if ( [LEVEL]='brand' ) then 1 else 0 )
        { FIXED [id]: MAX([x]='y') }  → group_aggregate ( max ( if ( [x]='y' ) then 1 else 0 ) , … )

    When any conversion fires, a trailing boolean test on the aggregate result
    (``… ) = false`` / ``= true``) is normalised to the numeric ``= 0`` / ``= 1``
    (the aggregate now returns 0/1, so ``= false`` would be invalid).
    """
    new_expr, n = _BOOL_AGG.subn(
        lambda m: f"{m.group(1)} ( if ( {m.group(2)} ) then 1 else 0 )", expr,
    )
    if n:
        new_expr = re.sub(r"\)\s*=\s*false\b", ") = 0", new_expr, flags=re.IGNORECASE)
        new_expr = re.sub(r"\)\s*=\s*true\b", ") = 1", new_expr, flags=re.IGNORECASE)
    return new_expr


# ---------------------------------------------------------------------------
# 3. CASE/WHEN → if/else if
# ---------------------------------------------------------------------------

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
    # Case-INSENSITIVE THEN: Tableau is case-insensitive, so a source-authored
    # inner IF may use lowercase `then` — it still needs its condition wrapped.
    # Re-processing an already-converted block is not a risk here: the caller's
    # _INNER_IF_END regex only feeds this function uppercase `IF…END` blocks,
    # and the `startswith("(")` guard below prevents double-wrapping a cond
    # that is already parenthesised.
    m = re.match(r"(.+?)\s+\bTHEN\b", result, flags=re.DOTALL | re.IGNORECASE)
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
        flags=re.DOTALL | re.IGNORECASE,
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
# 22. agg(if...else 0/null) → agg_if conversion (BL-046 #2)
# ---------------------------------------------------------------------------

_AGG_IF_MAP = {
    "unique count": "unique_count_if",
    "sum": "sum_if",
    "count": "count_if",
    "average": "average_if",
}


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
