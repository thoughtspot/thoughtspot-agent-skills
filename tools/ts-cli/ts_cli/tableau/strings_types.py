"""Tableau string-concatenation, type-conversion, and scoping transforms.

Pure functions, no I/O. Converts Tableau's ``+``-based string concatenation
to ``concat()``, ``INT()`` truncation to ``floor``/``ceil``, bare column
references to table-scoped references, and ``IN (...)`` set membership to
ThoughtSpot's ``in {...}`` syntax.
"""
from __future__ import annotations

import re

from ts_cli.tableau.parsing import _extract_function_args


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

    # Mask single-quoted string literals so a '[' inside a literal (e.g. a
    # concat label like '[' + ...) doesn't let the column-ref regex latch onto
    # the literal's bracket and swallow the real [COL] ref that follows.
    # Odd-indexed split segments are the literals; scope only the even ones.
    parts = re.split(r"('[^']*')", expr)
    for i in range(0, len(parts), 2):
        parts[i] = _COL_REF.sub(_replace_col, parts[i])
    return "".join(parts)


# ---------------------------------------------------------------------------
# 10b. Fix IN (...) → in {...}
# ---------------------------------------------------------------------------

_IN_PAREN = re.compile(r"\bin\s*\(", re.IGNORECASE)


def fix_in_parentheses(expr: str) -> str:
    """Replace IN (...) with in {...} — ThoughtSpot requires curly braces for set membership."""
    result = expr
    search_start = 0
    safety = 0
    while safety < 20:
        m = _IN_PAREN.search(result, search_start)
        if not m:
            break
        safety += 1
        # Skip "not in (" — ThoughtSpot doesn't support NOT IN
        before = result[:m.start()].rstrip()
        if before.lower().endswith("not"):
            # Leave this occurrence alone but keep scanning past it —
            # a later, unrelated IN (...) may still need conversion.
            search_start = m.end()
            continue
        paren_start = m.end() - 1
        extracted = _extract_function_args(result, paren_start)
        if not extracted:
            search_start = m.end()
            continue
        args, end_pos = extracted
        items = ", ".join(a.strip() for a in args)
        replacement = f"in {{ {items} }}"
        result = result[:m.start()] + replacement + result[end_pos:]
        search_start = m.start() + len(replacement)
    return result
