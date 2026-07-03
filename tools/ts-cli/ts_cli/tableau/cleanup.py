"""Tableau formula output-cleanup transforms.

Pure functions, no I/O. Post-pipeline cosmetic/correctness fixes applied to
translated formula text: operator spacing normalisation, rank() argument
completion, and ifnull(X, 0) stripping.
"""
from __future__ import annotations

import re

from ts_cli.tableau.parsing import _extract_function_args


# ---------------------------------------------------------------------------
# 17. Operator spacing (BL-046 #4 / BL-050 #6)
# ---------------------------------------------------------------------------

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
