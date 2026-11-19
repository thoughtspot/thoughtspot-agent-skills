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
# A control-character-delimited token, like literals.py's PLACEHOLDER_RE
# (`\x01L\d+\x01`) and _REF_PLACEHOLDER_RE (`\x02R\d+\x02`) — not a plain
# `__WRAPN__` string. A real (if unusual) Tableau field named `[__WRAP0__]`
# collided with that literal substring: the restore map's own value for the
# token contained the token's own text again (`[__WRAP0__]` survives inside
# its converted `concat(...)` form), so the fixed-point substitution loop
# below kept finding and re-expanding it forever. A control character
# cannot appear in Tableau formula text at all, so no real field name can
# ever collide with it.
_WRAP_TOKEN_RE = r"\x03W\d+\x03"
_NESTED_WRAP_CALL_RE = re.compile(
    rf"\b(?:{'|'.join(_WRAP_CALL_NAMES)})\s*\(", re.IGNORECASE
)
# The operand shapes that are string-typed on their own (no datatype/role
# gating needed) — used both to build the full operand pattern and, matched
# in isolation, to tell a "safe" operand apart from one that only qualifies
# via the datatype=='string' "any function call" alternative below.
_BASE_OPERAND_ONLY_RE = re.compile(rf"^(?:{_concat_operand_pattern(None)})$", re.IGNORECASE)
_QUOTED_LITERAL_RE = re.compile(r"^'[^']*'$")


def _has_string_evidence(text: str, registry: dict | None) -> bool:
    """True if `text` contains unambiguous string-literal evidence — a masked
    string-literal placeholder, or (defensively) a raw quote outside any
    `[field ref]` — marking a `+` touching it as concatenation, not arithmetic.

    Deliberately permissive (a substring scan over the whole text): used only
    to decide whether a wrapper call's argument is worth recursing into at
    all, never to decide string-ness of one specific `+` pair — see
    `_operand_is_string_literal` for that stricter, per-operand decision.
    """
    if registry is not None:
        for token in re.findall(PLACEHOLDER_RE, text):
            if is_string_placeholder(token, registry):
                return True
    return "'" in _without_refs(text)


def _operand_is_string_literal(operand: str, registry: dict | None) -> bool:
    """True only if `operand` ITSELF is a string literal (or its placeholder)
    — not merely text that happens to contain a quote somewhere inside
    unrelated nested content, e.g. a quoted comparison buried inside a
    `SUM(...)` call's own filter argument. Unlike `_has_string_evidence`,
    this must be precise: it decides whether one specific `+` pair is real
    string concatenation, so a false positive silently wraps arithmetic in
    `concat()`, which ThoughtSpot rejects.
    """
    stripped = operand.strip()
    if registry is not None and is_string_placeholder(stripped, registry):
        return True
    return bool(_QUOTED_LITERAL_RE.match(_without_refs(stripped)))


_CONCAT_CALL_START_RE = re.compile(r"concat\s*\(", re.IGNORECASE)


def _is_whole_concat_call(text: str) -> bool:
    """True only if `text`, in its entirety, is a single `concat(...)` call —
    not merely text that happens to start with one.

    Round-5 review nit: `STR([a] + 'x' = [b])`'s argument converts to
    `concat ( [a] , 'x' ) = [b]` — a boolean comparison whose LEFT side is a
    concat() call, not a bare concat() call itself. A `.startswith("concat (")`
    check wrongly treated that as "the whole argument is a concat()" and
    dropped the `STR(...)` wrapper, losing the stringification `=` needs.
    """
    m = _CONCAT_CALL_START_RE.match(text)
    if not m:
        return False
    extracted = _extract_function_args(text, m.end() - 1)
    if extracted is None:
        return False
    _, end_pos = extracted
    return text[end_pos:].strip() == ""


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
      nested wrapper call inside it the same way, to any depth). The
      recursive conversion runs with role forced to ``"measure"``, not the
      caller's own role: a wrapper call's argument is, by construction, being
      converted FROM a non-string type, so a bare ``[ref] + [ref]`` pair in
      there must never be read as string concatenation just because the
      overall formula happens to be a string-typed dimension (round-4 review:
      ``STR(IIF([Flag] = 'Y', [a] + [b], 0))`` wrongly concat()-ed the numeric
      branch because the unrelated `'Y'` elsewhere in the argument satisfied
      the old evidence check, and the dimension/datatype fallback alone
      green-lit the bare-ref pair).
      When the argument converts to a `concat()` call, the token restores to
      that `concat()` call directly, with NO `to_string()`/`str()` wrapper
      around it — ThoughtSpot's `to_string` rejects a Text argument (round-3
      review point 1), so wrapping would just produce a different rejection.

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
                token = f"\x03W{idx}\x03"
                idx += 1
                whole_call = result[m.start():end_pos]
                if _has_string_evidence(inner, registry):
                    converted = _replace_string_plus_chains(inner, "measure", registry, datatype).strip()
                    if _is_whole_concat_call(converted):
                        restore[token] = converted  # drop the wrapper — see docstring
                    else:
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
    # `safety` counts CONVERSIONS only, matching main's original cap (50) — a
    # rejection doesn't need its own budget: round-6 review found counting
    # every loop pass (rejections included) here made a long IF/CASE ladder
    # with many rejected numeric pairs run out of passes roughly
    # quadratically (every successful conversion rescans from 0, re-rejecting
    # every earlier numeric pair again before reaching new territory) — an
    # 18-branch ladder already exhausted a 200-pass budget. Rejections are
    # already bounded on their own: `search_start` strictly increases on
    # every rejection (m.start(2) is always past the previous search_start),
    # so the scan terminates within the string's own length regardless of
    # how many conversions follow.
    safety = 0
    search_start = 0
    while safety < 50:
        m = concat_pair.search(result, search_start)
        if not m:
            break
        left, right = m.group(1).strip(), m.group(2).strip()
        # Round-4 review (regression): with the datatype=='string' "any
        # function call" operand alternative below, a pair of plain function
        # calls (`LEN([First]) + LEN([Last])` in a numeric condition, or
        # `SUM([a]) + SUM([b])`) matched the operand pattern, and the
        # dimension/datatype fallback alone — with no actual string evidence
        # — was enough to wrap them in concat(), which rejects non-text
        # arguments. The fallback may only fire when BOTH operands are
        # already one of the unconditional base shapes (ref/literal/
        # to_string()/placeholder/wrap-token); a pair involving a "any
        # function call" operand needs real per-operand string evidence.
        left_is_base = bool(_BASE_OPERAND_ONLY_RE.fullmatch(left))
        right_is_base = bool(_BASE_OPERAND_ONLY_RE.fullmatch(right))
        has_string = (
            _operand_is_string_literal(left, registry)
            or _operand_is_string_literal(right, registry)
            or (
                left_is_base and right_is_base
                and role == "dimension" and datatype in (None, "string")
            )
        )
        if not has_string:
            # Round-5 review (blocking #1): a no-evidence pair earlier in the
            # expression (e.g. a numeric `LEN([a]) + [n]` ahead of a genuine
            # `[First] + ' ' + [Last]`) must not abort the whole scan — only
            # this ONE pair is arithmetic. Re-anchor the search at the right
            # operand's own start (not just past the whole rejected pair) so
            # it's still eligible to pair with whatever follows it.
            search_start = m.start(2)
            continue
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
        search_start = 0  # the string changed; rescan from the top
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
