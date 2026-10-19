"""Tableau LOD (Level of Detail) and TOTAL() conversion transforms.

Pure functions, no I/O. Converts Tableau's LOD expressions ({FIXED/INCLUDE/
EXCLUDE ... : agg}) to ThoughtSpot's group_aggregate(), and TOTAL(agg) to
group_aggregate(agg, {}, query_filters()).
"""
from __future__ import annotations

import re

from ts_cli.tableau.literals import _REF_RE
from ts_cli.tableau.parsing import (
    _extract_function_args,
    _find_top_level_colon,
    _split_args,
)


# ---------------------------------------------------------------------------
# 12. LOD expression conversion
# ---------------------------------------------------------------------------

def _parse_lod_content(content: str) -> tuple[str, str, str] | None:
    """Parse the content between matched { } into (keyword, dims, agg_expr).

    Returns None if the content doesn't look like an LOD expression.
    """
    stripped = content.strip()
    # `\s*` (not `\s+`): a grand-total LOD's keyword may be followed
    # immediately by the colon with NO whitespace (`{FIXED: agg}`) — the
    # dimension list, when present, still supplies its own separating space
    # (`{FIXED [Dim] : agg}`). Requiring `\s+` here caused the keyword match to
    # fail on the no-space form, falling through to treat "FIXED" itself as a
    # dimension and emitting invalid `{ FIXED }` TML syntax.
    keyword_match = re.match(
        r"(FIXED|INCLUDE|EXCLUDE)\s*", stripped, re.IGNORECASE,
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


def _find_next_parseable_lod_pair(expr: str) -> tuple[int, int, tuple] | None:
    """Find the innermost {...} pair whose content parses as real LOD syntax.

    One left-to-right scan, stack-based: each `}` closes whatever `{` is
    currently on top of the stack (standard bracket matching), which gives
    the innermost pair first when LODs are genuinely nested, and simply the
    next pair in sequence when they are not (sibling LODs, e.g. one per
    if/else-if branch). If that pair's content does NOT parse as LOD syntax
    — e.g. an earlier sibling's own conversion already emitted a
    `{ [dims] }` set-literal, which becomes the next brace pair this scan
    sees — the walk continues rather than stopping; because the stack still
    holds any genuinely outer, still-unclosed `{` from before this one, a
    real outer LOD the failed pair happened to sit inside is not lost either.

    A `[` is never read as a brace-relevant character — a `[ref]` can contain
    a literal, unescaped `[` (only a literal `]` needs Tableau's `]]` escape,
    per `_REF_RE`), e.g. a field named "Ratio [x" is written `[Ratio [x]`.
    Matching `_REF_RE` at each `[` and jumping straight to its end consumes
    the whole ref atomically, so a bracket that's part of a name is never
    confused for real `{}` nesting.

    Returns (open_pos, close_pos, parsed), or None if nothing in the
    expression parses as LOD content.
    """
    stack: list[int] = []
    in_single = in_double = False
    pos = 0
    while pos < len(expr):
        c = expr[pos]
        if c == "'" and not in_double:
            in_single = not in_single
        elif c == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if c == "[":
                m = _REF_RE.match(expr, pos)
                if m:
                    pos = m.end()
                    continue
            elif c == "{":
                stack.append(pos)
            elif c == "}" and stack:
                open_pos = stack.pop()
                content = expr[open_pos + 1:pos]
                parsed = _parse_lod_content(content)
                if parsed is not None:
                    return open_pos, pos, parsed
        pos += 1
    return None


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
        found = _find_next_parseable_lod_pair(result)
        if found is None:
            break

        safety += 1
        open_pos, close_pos, parsed = found
        keyword, dims_raw, agg_expr = parsed
        replacement = _lod_to_group_aggregate(keyword, dims_raw, agg_expr)
        result = result[:open_pos] + replacement + result[close_pos + 1:]

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
