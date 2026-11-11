"""Tableau string-concatenation, type-conversion, and scoping transforms.

Pure functions, no I/O. Converts Tableau's ``+``-based string concatenation
to ``concat()``, ``INT()`` truncation to ``floor``/``ceil``, bare column
references to table-scoped references, and ``IN (...)`` set membership to
ThoughtSpot's ``in {...}`` syntax.
"""
from __future__ import annotations

import re

from ts_cli.tableau.literals import PLACEHOLDER_RE, is_string_placeholder
from ts_cli.tableau.parsing import _extract_function_args


# ---------------------------------------------------------------------------
# 8. String concatenation: + on strings → concat()
# ---------------------------------------------------------------------------

def convert_string_concat(
    expr: str, role: str = "dimension", registry: dict | None = None,
    datatype: str | None = None,
) -> str:
    """Convert string + concatenation to concat().

    Only applies when the formula role is 'dimension' (string context)
    or the expression contains STR() / to_string() / string literals adjacent to +.

    Works at any nesting depth: finds contiguous chains of
    ``operand + operand`` where at least one operand is a string literal,
    and wraps the chain in ``concat()``.

    `registry` is the literal-masking registry from literals.mask_literals
    (see translate_single) — by the time this runs, a real quoted string
    literal like '%' has already been replaced by an opaque placeholder
    token, so "is this operand a string?" is decided by looking the
    placeholder up in `registry` rather than searching for a literal quote
    character.

    `datatype` is the formula's own declared Tableau type (string/integer/
    real/boolean/date/datetime), separate from `role` (dimension/measure is
    about aggregation behavior, not type — a dimension can be a date or a
    number used as a grouping key, not only a string). It gates which operand
    shapes are eligible to join a `+` chain: see `_concat_operand_pattern`.
    """
    if role == "measure" and "to_string" not in expr.lower() and "str(" not in expr.lower():
        return expr

    if "+" not in expr:
        return expr

    return _replace_string_plus_chains(expr, role, registry, datatype)


def _concat_operand_pattern(datatype: str | None) -> str:
    """Build the `+`-operand regex alternation.

    The base set (`[ref]`, `'literal'`, `to_string(...)`, a masked literal
    placeholder) is unconditional — these shapes are either unambiguously
    string-typed already or a column reference `role == "dimension"` already
    covers. Accepting ANY function call (e.g. `DATEDIFF(...)`, `YEAR(...)`)
    is gated on `datatype == "string"`: without that gate, a `+` between two
    non-string function calls in a dimension-role formula — ordinary numeric
    arithmetic, e.g. `DATEDIFF('day', [Start], [End]) + [Offset Days]` — got
    misread as string concatenation and wrapped in `concat()`, which rejects
    non-text arguments and fails every such formula at import.
    """
    base = (
        r"\[[^\]]+\]"                   # [column ref]
        r"|'[^']*'"                     # 'string literal'
        r"|to_string\s*\([^)]*\)"       # to_string(...)
        rf"|{PLACEHOLDER_RE}"           # masked string/date literal placeholder
        rf"|{_WRAP_TOKEN_RE}"           # a masked wrapper-call token (see _mask_wrapper_call_interiors)
    )
    if datatype == "string":
        base += r"|[A-Za-z_][A-Za-z_0-9]*\s*\((?:[^()]|\([^()]*\))*\)"  # any fn call, 1 level deep
    return rf"(?:{base})"


_WRAP_CALL_NAMES = ("to_string", "str")
_WRAP_TOKEN_RE = r"__WRAP\d+__"
_NESTED_WRAP_CALL_RE = re.compile(
    rf"\b(?:{'|'.join(_WRAP_CALL_NAMES)})\s*\(", re.IGNORECASE
)


def _has_string_evidence(text: str, registry: dict | None) -> bool:
    """True if `text` contains unambiguous string-literal evidence — a masked
    string-literal placeholder, or (defensively) a raw quote outside any
    `[field ref]` — marking a `+` touching it as concatenation, not arithmetic.
    """
    if registry is not None:
        for token in re.findall(PLACEHOLDER_RE, text):
            if is_string_placeholder(token, registry):
                return True
    return "'" in _without_refs(text)


def _mask_wrapper_call_interiors(
    expr: str, role: str = "dimension", registry: dict | None = None, datatype: str | None = None,
) -> tuple[str, dict[str, str]]:
    """Replace each top-level ``to_string(...)``/``str(...)`` call with an
    opaque placeholder token, so the concat-chain scan below never sees a raw
    `+` inside one directly — what the call's argument actually needs decides
    what the token restores to:

    - Purely arithmetic (``to_string(sum([a]) + sum([b]))``, no string-literal
      evidence in the argument) — restores to the original call, verbatim;
      ThoughtSpot stringifying an arithmetic result needs no concat().
    - String concatenation (``STR([First] + ' ' + [Last])`` — a masked
      string-literal placeholder or quote in the argument) — the argument is
      itself recursively run through the concat-chain conversion (handling a
      nested wrapper call inside it the same way, to any depth), so the token
      restores to ``to_string ( concat ( ... ) )`` rather than a raw `+`.

    A call whose argument still has an un-tokenized nested wrapper call inside
    it (parens still present) is skipped and retried on the next pass, once
    that inner call has already collapsed to a flat token — otherwise this
    call's own un-masked ``name(`` text plus the inner call's own parens would
    look like one unbalanced, nested span to the single-level
    ``to_string\\s*\\([^)]*\\)`` pattern the operand scan uses elsewhere.
    Returns (masked_expr, restore_map).
    """
    restore: dict[str, str] = {}
    result = expr
    idx = 0
    progress = True
    while progress:
        progress = False
        for name in _WRAP_CALL_NAMES:
            call = re.compile(rf"\b{name}\s*\(", re.IGNORECASE)
            # Search again after each replacement: masking shortens the string, so
            # positions found up front go stale for every later call.
            pos = 0
            while (m := call.search(result, pos)) is not None:
                open_paren_pos = m.end() - 1
                pos = m.end()
                extracted = _extract_function_args(result, open_paren_pos)
                if extracted is None:
                    continue
                args, end_pos = extracted
                if not args or "+" not in args[0]:
                    continue  # nothing to hide
                inner = args[0]
                if _NESTED_WRAP_CALL_RE.search(inner):
                    continue  # nested to_string(...)/str(...) not yet flattened — retry next pass
                token = f"__WRAP{idx}__"
                idx += 1
                whole_call = result[m.start():end_pos]
                if _has_string_evidence(inner, registry):
                    converted = _replace_string_plus_chains(inner, role, registry, datatype).strip()
                    open_part = result[m.start():open_paren_pos + 1]  # e.g. "to_string ("
                    restore[token] = f"{open_part} {converted} )"
                else:
                    restore[token] = whole_call  # arithmetic — untouched, original spacing kept
                result = result[:m.start()] + token + result[end_pos:]
                pos = m.start() + len(token)
                progress = True
    return result, restore


def _replace_string_plus_chains(
    expr: str, role: str, registry: dict | None = None, datatype: str | None = None,
) -> str:
    """Replace ``a + 'x' + b`` chains with ``concat(a, 'x', b)`` at any depth.

    Uses iterative regex matching: finds pairs of operands around ``+`` where
    at least one is a string literal (or the role is ``dimension`` on a
    string-typed — or type-unknown — formula), collects the full chain, and
    replaces with ``concat()``.  Merges adjacent results so ``concat(a, b) +
    c`` collapses to ``concat(a, b, c)``.
    """
    operand = _concat_operand_pattern(datatype)
    concat_pair = re.compile(rf"({operand})\s*\+\s*({operand})", re.IGNORECASE)
    result, restore = _mask_wrapper_call_interiors(expr, role, registry, datatype)
    safety = 0
    while safety < 50:
        m = concat_pair.search(result)
        if not m:
            break
        left, right = m.group(1).strip(), m.group(2).strip()
        has_string = (
            (role == "dimension" and datatype in (None, "string"))
            # a quote in a [field name] is not a string literal (#583 review)
            or "'" in _without_refs(left) or "'" in _without_refs(right)
            or (registry is not None and (
                is_string_placeholder(left, registry)
                or is_string_placeholder(right, registry)
            ))
        )
        if not has_string:
            break
        safety += 1
        # Extend chain rightward: keep matching + OPERAND after the pair
        chain = [left, right]
        end = m.end()
        ext = re.compile(r"\s*\+\s*" + operand, re.IGNORECASE)
        while True:
            em = ext.match(result, end)
            if not em:
                break
            chain.append(em.group(0).split("+", 1)[1].strip())
            end = em.end()
        inner = " , ".join(chain)
        result = result[:m.start()] + f"concat ( {inner} )" + result[end:]
    # Fixed-point substitution: a converted wrapper-call token's own restore
    # text can itself reference an earlier token (a nested wrapper call), so
    # one pass in insertion order is not always enough to resolve them all.
    changed = True
    while changed:
        changed = False
        for token, original in restore.items():
            if token in result:
                result = result.replace(token, original)
                changed = True
    return result


def _without_refs(operand: str) -> str:
    return re.sub(r"\[[^\]]*\]", "", operand)


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
            # Parenthesised: bare, `INT(x) * 2` read as `if … else ceil ( x ) * 2` and
            # doubled only the negative branch — a silent wrong answer (#579 review)
            replacement = f"( if ( {inner} >= 0 ) then floor ( {inner} ) else ceil ( {inner} ) )"
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
