"""Rewrite content TML onto a different Model. Pure functions, no I/O.

The whole Org migration is this transform. For each content object exactly two things
change: the **data-source reference** and the **column names**. Everything the previous
architecture did (lifting scaffolding, renaming Model columns, repointing) existed to
avoid writing this module, and two live findings showed that avoidance was never possible
(BL-148, BL-149).

**Content TML has no physical anchor.** A Liveboard references columns purely by display
name -- including `table_columns[].column_id`, which is the *display name*, not a
`TBL::COL` binding. Only `tables[].fqn` is stable. That is why a rename cannot be relied
on and why every reference has to be rewritten explicitly.

**Denylist, not allowlist.** A scan of the richest Liveboards on se-thoughtspot (2026-07-28)
found 12 distinct paths holding whole-string column references. Rather than enumerate them
-- which silently misses whatever the platform adds next -- this rewrites *every*
whole-string match and excludes the handful of paths that are user-facing **labels**
(`LABEL_PATHS`). The trade is deliberate: a new reference field is then handled for free,
while a new *label* field would be wrongly rewritten. Labels are rare and additive, and the
coverage check cannot catch that case, so `LABEL_PATHS` is the one thing here that needs
human review when the platform changes.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Mapping, Optional, Tuple

# Paths whose value is a HUMAN LABEL that merely happens to match a column name, never a
# reference. Rewriting these renames the user's chart or filter. Verified against real
# content: three visualization titles matched a column name exactly, and `answer.name`
# produced 134 further SUBSTRING matches ("Sales by Region") -- exactly the class a naive
# find-and-replace mangles.
LABEL_PATHS = frozenset({
    "liveboard.visualizations.[].answer.name",
    "liveboard.filters.[].display_name",
    "liveboard.visualizations.[].answer.chart.chart_columns.[].column_properties.[].name",
    "answer.name",
    "answer.filters.[].display_name",
})

# `client_state_v2` is a JSON *string* carrying chart display state. It holds column names
# in named fields, so it is rewritten by parsing rather than by substring replacement --
# a substring pass over the blob would corrupt unrelated state.
CLIENT_STATE_KEYS = ("client_state_v2",)
_CS_NAME_FIELDS = (("columnProperties", "columnId"),
                   ("systemSeriesColors", "serieName"))

_BRACKET_RE = re.compile(r"\[([^\[\]]+)\]")

# A reference qualified by its source: `Retail - Apparel::Product Type`. Found live
# 2026-07-28 in filters, ordered_chips, view_filters and parameter_overrides -- 82
# occurrences across 45 real Liveboards, alongside the bare form in the SAME field. Both
# have to be handled, and a whole-string match catches only the bare one.
_QUALIFIED_RE = re.compile(r"^(?P<src>[^:]+)::(?P<col>.+)$")

# Fields whose value is a column name wrapped in aggregation or bucket decoration --
# `Total LINEAMOUNT`, `Month(YM)`. The column name is substituted INSIDE the token.
_DECORATED_FIELDS = ("search_output_column",)


def _norm_path(path: List[str]) -> str:
    return ".".join(path)


def substitute_bracketed(text: str, column_map: Mapping[str, str]) -> str:
    """Rewrite `[Old]` tokens, leaving unmapped ones alone.

    `search_query` mixes column tokens with syntax that must survive verbatim
    (`[date].'last 12 months' top 5`, `[formula_Unit Cost]`), so only bracket contents
    present in the map are touched.
    """
    if not text:
        return text
    return _BRACKET_RE.sub(
        lambda m: f"[{column_map.get(m.group(1), m.group(1))}]", text)


def substitute_qualified(value: str, column_map: Mapping[str, str]) -> str:
    """Rewrite the column half of a `Source::Column` reference.

    The source half is left alone: the migration pairs the tenant Model to the published
    one **by name**, so the qualifier does not change -- only the column does.

    Returns the value unchanged when it is not qualified, or when the column half is not
    in the map, so this is safe to attempt on any string.
    """
    m = _QUALIFIED_RE.match(value or "")
    if not m:
        return value
    col = m.group("col")
    if col not in column_map:
        return value
    return f"{m.group('src')}::{column_map[col]}"


def substitute_decorated(value: str, column_map: Mapping[str, str]) -> str:
    """Rewrite a column name that may be wrapped in decoration.

    `Total Segment` -> `Total STRING_1`, `Month(Segment)` -> `Month(STRING_1)`. Exact
    matches are handled first so a column whose name is a substring of another cannot be
    partially rewritten.
    """
    if not value:
        return value
    if value in column_map:
        return column_map[value]
    # Longest first: if both "Order" and "Order Date" are mapped, "Order Date" must win.
    for old in sorted(column_map, key=len, reverse=True):
        pattern = r"(?<![\w])" + re.escape(old) + r"(?![\w])"
        if re.search(pattern, value):
            return re.sub(pattern, column_map[old], value, count=1)
    return value


def rewrite_client_state(blob: str, column_map: Mapping[str, str]) -> str:
    """Rewrite the column references inside a `client_state_v2` JSON string.

    Only the two known name-bearing fields are touched. `axisProperties[].id` is a GUID
    and is deliberately left alone. Unparseable input is returned unchanged rather than
    raising: display state is not worth failing a migration over, and a corrupted blob
    would be worse than a stale one.
    """
    if not blob:
        return blob
    try:
        parsed = json.loads(blob)
    except (ValueError, TypeError):
        return blob
    for section, field in _CS_NAME_FIELDS:
        entries = parsed.get(section)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get(field), str):
                entry[field] = column_map.get(entry[field], entry[field])
    return json.dumps(parsed)


def _rewrite_node(node: Any, path: List[str], column_map: Mapping[str, str]) -> Any:
    if isinstance(node, dict):
        return {k: _rewrite_node(v, path + [k], column_map) for k, v in node.items()}
    if isinstance(node, list):
        return [_rewrite_node(v, path + ["[]"], column_map) for v in node]
    if not isinstance(node, str):
        return node

    key = path[-1] if path else ""
    if key in CLIENT_STATE_KEYS:
        return rewrite_client_state(node, column_map)
    if _norm_path(path) in LABEL_PATHS:
        return node                                   # human label, never a reference
    if key in _DECORATED_FIELDS:
        return substitute_decorated(node, column_map)
    if "[" in node:
        return substitute_bracketed(node, column_map)
    if "::" in node:
        return substitute_qualified(node, column_map)
    return column_map.get(node, node)                 # whole-string reference


def repoint_source(doc: Dict[str, Any], target_guid: str,
                   target_name: Optional[str] = None) -> Dict[str, Any]:
    """Point every `tables[]` entry at the target Model.

    `fqn` is the only stable reference in a content document, so it is the one field that
    must be right. `id` and `name` are updated alongside it because resolution falls back
    to the name when the fqn is dead -- leaving a stale name means a silent
    bind-to-the-wrong-object if a same-named object exists in the target.
    """
    def walk(node, path):
        if isinstance(node, dict):
            return {k: walk(v, path + [k]) for k, v in node.items()}
        if isinstance(node, list):
            if path and path[-1] == "tables":
                out = []
                for entry in node:
                    if isinstance(entry, dict):
                        entry = dict(entry)
                        entry["fqn"] = target_guid
                        if target_name:
                            entry["name"] = target_name
                            entry["id"] = target_name
                    out.append(entry)
                return out
            return [walk(v, path + ["[]"]) for v in node]
        return node
    return walk(doc, [])


def rewrite_content(doc: Dict[str, Any], column_map: Mapping[str, str],
                    target_guid: str, target_name: Optional[str] = None
                    ) -> Dict[str, Any]:
    """The migration, for one Answer or Liveboard: repoint, then rewrite columns."""
    return _rewrite_node(repoint_source(doc, target_guid, target_name), [], column_map)


def rewrite_view(doc: Dict[str, Any], column_map: Mapping[str, str],
                 target_guid: str, target_name: Optional[str] = None
                 ) -> Dict[str, Any]:
    """Repoint a View, PRESERVING what it exposes downstream.

    A View's output column has two independent fields: `search_output_column` binds to the
    search result, `name` is the alias its dependents see. Rewriting the first and leaving
    the second means the View reads a different Model while exposing the same names --
    so **every Answer and Liveboard built on it needs no migration at all**.

    Proven end to end 2026-07-28: a View repointed to a different Model, through a
    different column name, kept its alias AND kept returning data to an untouched Answer.
    """
    out = rewrite_content(doc, column_map, target_guid, target_name)
    body = out.get("view")
    original = (doc.get("view") or {}).get("view_columns") or []
    if isinstance(body, dict):
        for new_col, old_col in zip(body.get("view_columns") or [], original):
            if isinstance(new_col, dict) and isinstance(old_col, dict) and "name" in old_col:
                new_col["name"] = old_col["name"]      # the shield
    return out


# ---------------------------------------------------------------------------
# Coverage — the completeness gate
# ---------------------------------------------------------------------------

def residual_references(doc: Any, source_columns: Mapping[str, str]) -> List[Tuple[str, str]]:
    """`(path, value)` for every surviving source-column reference outside label paths.

    **This is the test that makes the rewrite trustworthy.** The failure mode of a partial
    rewrite is an object that imports cleanly and renders wrong, so "did we catch every
    field?" has to be an assertion rather than a judgement. Re-run it whenever the
    platform adds a field.

    View `name` fields are excluded: preserving them is the point (see `rewrite_view`).
    """
    found: List[Tuple[str, str]] = []
    names = set(source_columns)

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, path + [k])
        elif isinstance(node, list):
            for v in node:
                walk(v, path + ["[]"])
        elif isinstance(node, str):
            p = _norm_path(path)
            if p in LABEL_PATHS or path[-2:] == ["view_columns", "[]"] or (
                    len(path) >= 2 and path[-1] == "name"
                    and path[-3:-1] == ["view_columns", "[]"]):
                return
            qualified = _QUALIFIED_RE.match(node)
            for col in names:
                if (node == col or f"[{col}]" in node
                        or (qualified and qualified.group("col") == col)):
                    found.append((p, node))
                    return

    walk(doc, [])
    return found
