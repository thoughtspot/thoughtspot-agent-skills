"""Databricks Metric View YAML -> structured dict (`ts databricks parse-mv`).

Pure functions: YAML text in, JSON-ready dict out. No I/O, no network calls —
trivially unit-testable. stdlib + PyYAML only (Genie-vendorable — see
package docstring).

Schema reference: agents/shared/schemas/databricks-metric-view.md.
Classification rules: agents/shared/mappings/ts-databricks/ts-from-databricks-rules.md.
"""
from __future__ import annotations

import re

_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def strip_sql_comments(expr: str) -> str:
    """Strip -- line and /* */ block comments before classification.

    Naive w.r.t. comment markers inside string literals — acceptable per the
    rules file (classification only; the raw expr is preserved separately).
    """
    return _BLOCK_COMMENT_RE.sub(" ", _LINE_COMMENT_RE.sub("", expr)).strip()


def _split_fqn(s: str) -> list[str]:
    """Split a dotted identifier on '.', respecting backtick-quoted segments."""
    parts: list[str] = []
    buf: list[str] = []
    in_backtick = False
    for ch in s:
        if ch == "`":
            in_backtick = not in_backtick
        elif ch == "." and not in_backtick:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


_IDENT_SEGMENT_RE = re.compile(r"^[A-Za-z_][\w$]*$")


def classify_source(raw: str) -> dict | None:
    """Classify a `source:` value into one of the documented source forms.

    Returns {"kind": "sql_query", ...} or {"kind": "table_fqn", ...}, or None
    when the value matches neither (caller records an unsupported[] entry).
    An FQN cannot be distinguished from an MV-on-MV source offline, so every
    table_fqn carries needs_live_check: True — the SKILL step runs the live
    information_schema.tables check and fails loud on METRIC_VIEW.
    """
    stripped = raw.strip()
    if not stripped:
        return None
    low = stripped.lower()
    if low.startswith(("(select", "(with")) or low.startswith(("select ", "with ")):
        return {"kind": "sql_query", "raw": stripped,
                "parenthesized": stripped.startswith("(")}
    parts = _split_fqn(stripped)
    for part in parts:
        # A backtick-quoted segment (now unquoted by _split_fqn) may hold any
        # non-empty text; a bare segment must be a plain identifier.
        bare = part if "`" not in stripped else None
        if not part:
            return None
        if bare is not None and not _IDENT_SEGMENT_RE.match(part):
            return None
    return {"kind": "table_fqn", "raw": stripped,
            "parts": parts if len(parts) == 3 else None,
            "needs_live_check": True}
