"""Low-level Tableau expression scanners shared by all transform modules.

Pure functions, no I/O. These are private helpers (underscore names kept for
back-compat with test imports via ts_cli.tableau_translate).
"""
from __future__ import annotations

import re


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
