"""Tableau LOD (Level of Detail) and TOTAL() conversion transforms.

Pure functions, no I/O. Converts Tableau's LOD expressions ({FIXED/INCLUDE/
EXCLUDE ... : agg}) to ThoughtSpot's group_aggregate(), and TOTAL(agg) to
group_aggregate(agg, {}, query_filters()).
"""
from __future__ import annotations

import re

from ts_cli.tableau.parsing import (
    _extract_function_args,
    _find_matching_brace,
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
