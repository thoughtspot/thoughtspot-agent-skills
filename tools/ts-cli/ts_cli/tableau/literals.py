"""Literal masking for Tableau formula translation.

Pure functions, no I/O. String and date-range (``#...#``) literals are masked
into opaque placeholder tokens before the translation pipeline runs, so
keyword-cleanup passes (THEN-folding, bare END/CASE strip, keyword
validation) never see literal *content* and cannot corrupt or misclassify it.
Without this, ``IF [Status] = "END" THEN 1 ELSE 0 END`` gets its literal
``"END"`` mistaken for the block-closing ``END`` keyword.

Call ``mask_literals`` immediately after comment-stripping and before any
other pass; call ``unmask_literals`` at the very end, after output
validation, to restore the literal's final ThoughtSpot form (single-quoted
string, or ``to_date(...)`` for a date literal).
"""
from __future__ import annotations

import re

# Placeholder uses SOH (\x01) delimiters: a control character that (a) never
# appears in real Tableau formulas, (b) is not a \w character so it can't be
# absorbed into an identifier/keyword regex elsewhere in the pipeline, and
# (c) survives the pipeline's `re.sub(r"\s+", " ", expr)` whitespace collapse
# untouched (it isn't whitespace).
_PLACEHOLDER_TMPL = "\x01L{n}\x01"

# Exported as a string fragment so other modules (conditionals.py, strings_types.py)
# can splice it into their own regexes as an alternative "this is a masked literal"
# branch, without importing the compiled pattern object.
PLACEHOLDER_RE = r"\x01L\d+\x01"

_PLACEHOLDER_MATCH = re.compile(PLACEHOLDER_RE)

# Single left-to-right scan: strings are tried BEFORE the date literal so a
# '#' that happens to sit inside a string (e.g. 'ID#123') is never mistaken
# for a date-literal delimiter — re.sub only considers a new alternative at a
# position once the leftmost match consumes past it, so a quote encountered
# before a '#' always wins the scan.
# Doubled-quote escaping: a source literal escapes an embedded quote by
# doubling it ('it''s', "she said ""hi"""), matched via the [^']|'' / [^"]|""
# alternation below.
_LITERAL_RE = re.compile(
    r"(?P<sq>'(?:[^']|'')*')"
    r"|(?P<dq>\"(?:[^\"]|\"\")*\")"
    r"|(?P<date>#[^#]*#)"
)


def mask_literals(expr: str) -> tuple[str, dict[str, dict[str, str]]]:
    """Replace every string and ``#...#`` date literal with an opaque token.

    Returns (masked_expr, registry). registry maps placeholder -> {"kind":
    "str"|"date", "raw": <original literal text, quotes/hashes included>}.
    """
    registry: dict[str, dict[str, str]] = {}

    def _mask(m: re.Match) -> str:
        token = _PLACEHOLDER_TMPL.format(n=len(registry))
        kind = "date" if m.group("date") is not None else "str"
        registry[token] = {"kind": kind, "raw": m.group(0)}
        return token

    masked = _LITERAL_RE.sub(_mask, expr)
    return masked, registry


def is_string_placeholder(token: str, registry: dict[str, dict[str, str]]) -> bool:
    """True if `token` (after stripping whitespace) is a placeholder for a
    string literal (not a date literal) in `registry`."""
    entry = registry.get(token.strip())
    return bool(entry) and entry.get("kind") == "str"


def literal_value(token: str, registry: dict[str, dict[str, str]]) -> str | None:
    """Return the unescaped interior text of a string-literal placeholder.

    Lets a downstream pass that needs to inspect a literal's actual VALUE for
    classification (e.g. Tableau's ``DATEADD('year', ...)`` unit argument)
    resolve it without unmasking the surrounding expression. Returns None if
    `token` isn't a recognised string-literal placeholder (e.g. it's a date
    placeholder, or not a placeholder at all).
    """
    entry = registry.get(token.strip())
    if not entry or entry.get("kind") != "str":
        return None
    raw = entry["raw"]
    quote = raw[0]
    return raw[1:-1].replace(quote + quote, quote)


def _string_literal_to_ts(raw: str) -> str:
    """Convert a raw Tableau string literal (single- or double-quoted, with
    surrounding quote characters) to ThoughtSpot's single-quoted form.

    Un-escapes the source's doubled-quote escape back to a single character,
    then re-escapes any interior single quote for single-quoted TS output
    (a no-op round-trip when the source was already single-quoted, since both
    dialects double-escape the same way).
    """
    quote = raw[0]
    interior = raw[1:-1]
    interior = interior.replace(quote + quote, quote)
    interior = interior.replace("'", "''")
    return f"'{interior}'"


def _date_literal_to_ts(raw: str) -> str:
    """Convert a raw Tableau ``#...#`` date literal to ``to_date(...)``.

    ``#2024-01-01#`` -> ``to_date ( '2024-01-01' , 'yyyy-MM-dd' )``
    ``#2024-01-01 12:30:00#`` -> ``to_date ( '2024-01-01 12:30:00' , 'yyyy-MM-dd HH:mm:ss' )``
    """
    inner = raw[1:-1].strip()
    fmt = "yyyy-MM-dd HH:mm:ss" if (":" in inner or " " in inner) else "yyyy-MM-dd"
    return f"to_date ( '{inner}' , '{fmt}' )"


def unmask_literals(expr: str, registry: dict[str, dict[str, str]]) -> str:
    """Restore every placeholder in `expr` to its final ThoughtSpot literal form."""

    def _unmask(m: re.Match) -> str:
        entry = registry.get(m.group(0))
        if not entry:
            return m.group(0)
        if entry["kind"] == "date":
            return _date_literal_to_ts(entry["raw"])
        return _string_literal_to_ts(entry["raw"])

    return _PLACEHOLDER_MATCH.sub(_unmask, expr)
