"""Snowflake Semantic View DDL → structured dict (`ts snowflake parse-sv`).

Pure functions: DDL text in, JSON-ready dict out. No I/O, no network calls.
stdlib only (no PyYAML needed — the input is DDL, not YAML).

Grammar reference: agents/shared/mappings/ts-snowflake/ts-from-snowflake-rules.md
(§"Semantic View DDL Format", lines 9–106).

Reuses the balanced-paren clause extraction helpers from snowflake_ops.py (the
lint-ddl module), which already handle the same DDL surface.
"""
from __future__ import annotations

import json
import re
from typing import Any

from ts_cli.snowflake_ops import (
    _extract_clause,
    _split_top_level,
    _strip_string_literals,
)

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_VIEW_HEADER_RE = re.compile(
    r"create\s+or\s+replace\s+semantic\s+view\s+"
    r"([A-Za-z0-9_\"]+(?:\.[A-Za-z0-9_\"]+){0,2})",
    re.IGNORECASE,
)

_TABLE_ALIAS_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s+as\s+",
    re.IGNORECASE,
)

_SUBQUERY_ALIAS_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s+as\s*\(",
    re.IGNORECASE,
)

_PRIMARY_KEY_RE = re.compile(
    r"\bprimary\s+key\s*\(([^)]+)\)",
    re.IGNORECASE,
)

_UNIQUE_RE = re.compile(
    r"\bunique\s*\(([^)]+)\)",
    re.IGNORECASE,
)

_RANGE_CONSTRAINT_RE = re.compile(
    r"\bconstraint\s+([A-Za-z_][A-Za-z0-9_]*)\s+distinct\s+range\s+between\s+"
    r"([A-Za-z_][A-Za-z0-9_]*)\s+and\s+([A-Za-z_][A-Za-z0-9_]*)\s+exclusive",
    re.IGNORECASE,
)

_COMMENT_RE = re.compile(r"\bcomment\s*=\s*'", re.IGNORECASE)

_SYNONYMS_RE = re.compile(
    r"\bwith\s+synonyms\s*=\s*\(",
    re.IGNORECASE,
)

# Live GET_DDL emits `sample_values ('a', 'b')`; the documented/authored form
# is `with sample values (...)`. Accept both, plus the mixed spellings — the
# underscore form was previously unmatched, so the clause stayed in the entry
# and was mis-read as part of the expression (BL-197).
_SAMPLE_VALUES_RE = re.compile(
    r"\b(?:with\s+)?sample[_\s]values\s*\(",
    re.IGNORECASE,
)

_IS_ENUM_RE = re.compile(r"\bis_enum\b", re.IGNORECASE)

_PRIVATE_RE = re.compile(r"^\s*PRIVATE\b", re.IGNORECASE)

_FILTER_LABEL_RE = re.compile(
    r"\blabels\s*=\s*\(\s*filter\s*\)",
    re.IGNORECASE,
)

_CORTEX_SEARCH_RE = re.compile(
    r"\bwith\s+cortex\s+search\s+service\s+([A-Za-z_][A-Za-z0-9_.]*)",
    re.IGNORECASE,
)

_NON_ADDITIVE_RE = re.compile(
    r"\bnon\s+additive\s+by\s*\(([^)]+)\)",
    re.IGNORECASE,
)

_USING_RE = re.compile(
    r"\bUSING\s+([A-Za-z_][A-Za-z0-9_]*)\b",
    re.IGNORECASE,
)

_RELATIONSHIP_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s+as\s+"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)\s+"
    r"references\s+"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)",
    re.IGNORECASE,
)

_RANGE_REF_RE = re.compile(
    r"\bbetween\s+([A-Za-z_][A-Za-z0-9_]*)\s+and\s+([A-Za-z_][A-Za-z0-9_]*)\s+exclusive",
    re.IGNORECASE,
)

_ASOF_REF_RE = re.compile(
    r"([A-Za-z_][A-Za-z0-9_]*)\s*,\s*ASOF\s+([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)

_AI_SQL_GEN_RE = re.compile(
    r"\bai_sql_generation\s*=\s*'",
    re.IGNORECASE,
)

_AI_QUESTION_CAT_RE = re.compile(
    r"\bai_question_categorization\s*=\s*'",
    re.IGNORECASE,
)

_EXTENSION_RE = re.compile(
    r"\bwith\s+extension\s*\(\s*CA\s*=\s*'",
    re.IGNORECASE,
)

_VERIFIED_QUERY_NAME_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s+AS\s*\(",
    re.IGNORECASE,
)

# Metric expression: left side is TABLE.COL, right side after `as` is the expr
_DIM_METRIC_ENTRY_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\s+as\s+(.+)$",
    re.IGNORECASE | re.DOTALL,
)

# Unqualified DERIVED metric: `NAME as <expr>` with no table prefix on the
# left. Valid Semantic View grammar and the ONLY way to express a ratio that
# spans two unrelated facts -- a metric qualified on a table may reference only
# metrics on directly related entities (Snowflake 010211). Previously every such
# metric fell through both patterns below and landed in unsupported[] as
# "could not parse metric entry" (BL-213).
_DERIVED_METRIC_ENTRY_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s+as\s+(.+)$",
    re.IGNORECASE | re.DOTALL,
)

# Table.COL pattern for the left-hand side (before `as` or modifiers)
_TABLE_DOT_COL_RE = re.compile(
    r"([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)",
)


# ---------------------------------------------------------------------------
# String-literal extraction (preserving content, unlike _strip_string_literals)
# ---------------------------------------------------------------------------

def _extract_string_literal(text: str, start: int) -> tuple[str, int]:
    """Extract a single-quoted string literal starting at position `start`
    (which must point to the opening quote). Returns (content, end_pos)
    where end_pos is the index after the closing quote. Handles Snowflake's
    doubled-quote escaping ('' -> ')."""
    i = start + 1
    n = len(text)
    parts: list[str] = []
    while i < n:
        ch = text[i]
        if ch == "'":
            if i + 1 < n and text[i + 1] == "'":
                parts.append("'")
                i += 2
                continue
            return "".join(parts), i + 1
        parts.append(ch)
        i += 1
    return "".join(parts), n


def _extract_comment(entry: str) -> tuple[str | None, str]:
    """Extract comment='...' from an entry, returning (comment_text, entry_without_comment)."""
    m = _COMMENT_RE.search(entry)
    if not m:
        return None, entry
    content, end = _extract_string_literal(entry, m.end() - 1)
    cleaned = entry[:m.start()].rstrip() + entry[end:]
    return content, cleaned


def _extract_synonyms(entry: str) -> tuple[list[str], str]:
    """Extract with synonyms=('a','b',...) from an entry."""
    m = _SYNONYMS_RE.search(entry)
    if not m:
        return [], entry
    paren_start = m.end() - 1
    depth = 1
    i = paren_start + 1
    n = len(entry)
    while i < n and depth > 0:
        if entry[i] == "(":
            depth += 1
        elif entry[i] == ")":
            depth -= 1
        i += 1
    inner = entry[paren_start + 1:i - 1]
    syns: list[str] = []
    pos = 0
    while pos < len(inner):
        inner_stripped = inner[pos:].lstrip()
        if not inner_stripped:
            break
        pos = len(inner) - len(inner_stripped)
        if inner[pos] == "'":
            val, end = _extract_string_literal(inner, pos)
            syns.append(val)
            pos = end
            rest = inner[pos:].lstrip()
            if rest.startswith(","):
                pos = len(inner) - len(rest) + 1
            else:
                pos = len(inner) - len(rest)
        else:
            break
    cleaned = entry[:m.start()].rstrip() + entry[i:]
    return syns, cleaned


def _extract_sample_values(entry: str) -> tuple[list[str], str]:
    """Extract with sample values ('v1','v2',...) from an entry."""
    m = _SAMPLE_VALUES_RE.search(entry)
    if not m:
        return [], entry
    paren_start = m.end() - 1
    depth = 1
    i = paren_start + 1
    n = len(entry)
    while i < n and depth > 0:
        if entry[i] == "(":
            depth += 1
        elif entry[i] == ")":
            depth -= 1
        i += 1
    inner = entry[paren_start + 1:i - 1]
    vals: list[str] = []
    pos = 0
    while pos < len(inner):
        inner_stripped = inner[pos:].lstrip()
        if not inner_stripped:
            break
        pos = len(inner) - len(inner_stripped)
        if inner[pos] == "'":
            val, end = _extract_string_literal(inner, pos)
            vals.append(val)
            pos = end
            rest = inner[pos:].lstrip()
            if rest.startswith(","):
                pos = len(inner) - len(rest) + 1
            else:
                pos = len(inner) - len(rest)
        else:
            break
    cleaned = entry[:m.start()].rstrip() + entry[i:]
    return vals, cleaned


# ---------------------------------------------------------------------------
# Table parsing
# ---------------------------------------------------------------------------

def _extract_unique_keys(entry: str) -> tuple[list[str], str]:
    """Strip every `unique (...)` clause from a table entry, returning the keys
    and the remaining text.

    A logical table may declare SEVERAL unique keys, and it must when it carries
    more than one offset column that a role-played alias joins on
    (`unique (DATE_7_DAYS_AGO) unique (DATE_28_DAYS_AGO) unique (...)`) --
    Snowflake requires every referenced key to be a primary or unique key of the
    entity. Only the FIRST clause used to be consumed, so the rest stayed in the
    entry text and were swallowed into the table NAME, e.g.
    `DM_DATE_DIM unique (DATE_28_DAYS_AGO) unique (DATE_364_DAYS_AGO)`, breaking
    every downstream lookup keyed on that name (BL-214).
    """
    cols: list[str] = []
    while True:
        m = _UNIQUE_RE.search(entry)
        if not m:
            return cols, entry
        cols.extend(c.strip() for c in m.group(1).split(","))
        entry = entry[:m.start()].rstrip() + entry[m.end():]


def _parse_table_entry(raw: str) -> dict[str, Any]:
    """Parse a single entry from the tables() clause."""
    entry = raw.strip()
    result: dict[str, Any] = {
        "fqn": "",
        "alias": "",
        "primary_key": [],
        "comment": None,
        "synonyms": [],
        "is_subquery": False,
        "subquery_sql": None,
    }

    comment, entry = _extract_comment(entry)
    result["comment"] = comment

    synonyms, entry = _extract_synonyms(entry)
    result["synonyms"] = synonyms

    range_constraint: dict[str, str] | None = None
    m_range = _RANGE_CONSTRAINT_RE.search(entry)
    if m_range:
        range_constraint = {
            "name": m_range.group(1),
            "start": m_range.group(2),
            "end": m_range.group(3),
        }
        entry = entry[:m_range.start()].rstrip() + entry[m_range.end():]

    unique_cols, entry = _extract_unique_keys(entry)

    if range_constraint:
        result["range_constraint"] = range_constraint
    if unique_cols:
        result["unique_cols"] = unique_cols

    pk: list[str] = []
    m_pk = _PRIMARY_KEY_RE.search(entry)
    if m_pk:
        pk = [c.strip() for c in m_pk.group(1).split(",")]
        entry = entry[:m_pk.start()].rstrip() + entry[m_pk.end():]
    result["primary_key"] = pk

    m_subq = _SUBQUERY_ALIAS_RE.match(entry)
    if m_subq:
        alias = m_subq.group(1)
        result["alias"] = alias
        result["name"] = alias
        result["is_subquery"] = True
        paren_content = entry[m_subq.end() - 1:]
        depth = 0
        sql_end = len(paren_content)
        for idx, ch in enumerate(paren_content):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    sql_end = idx
                    break
        result["subquery_sql"] = paren_content[1:sql_end].strip()
        result["fqn"] = f"({result['subquery_sql']})"
        return result

    m_alias = _TABLE_ALIAS_RE.match(entry)
    if m_alias:
        result["alias"] = m_alias.group(1)
        fqn = entry[m_alias.end():].strip()
    else:
        fqn = entry.strip()

    fqn = fqn.strip()
    result["fqn"] = fqn

    parts = fqn.split(".")
    last = parts[-1].strip('"')
    result["name"] = last

    if not result["alias"]:
        result["alias"] = last

    return result


# ---------------------------------------------------------------------------
# Relationship parsing
# ---------------------------------------------------------------------------

def _parse_relationship_entry(raw: str) -> dict[str, Any] | None:
    """Parse a single entry from the relationships() clause."""
    entry = raw.strip()
    m = _RELATIONSHIP_RE.match(entry)
    if not m:
        return None

    name = m.group(1)
    from_table = m.group(2)
    from_cols_raw = m.group(3)
    to_table = m.group(4)
    to_cols_raw = m.group(5)

    join_style = "equi"
    from_cols: list[str] = [c.strip() for c in from_cols_raw.split(",")]

    m_range = _RANGE_REF_RE.search(to_cols_raw)
    if m_range:
        join_style = "range"
        to_cols = [m_range.group(1), m_range.group(2)]
    else:
        m_asof = _ASOF_REF_RE.search(to_cols_raw)
        if m_asof:
            join_style = "asof"
            to_cols = [m_asof.group(1), m_asof.group(2)]
        else:
            to_cols = [c.strip() for c in to_cols_raw.split(",")]

    return {
        "name": name,
        "from_table": from_table,
        "from_cols": from_cols,
        "to_table": to_table,
        "to_cols": to_cols,
        "join_style": join_style,
    }


# ---------------------------------------------------------------------------
# Dimension / fact / metric entry parsing
# ---------------------------------------------------------------------------

def _strip_modifiers(entry: str) -> tuple[str, dict[str, Any]]:
    """Strip comment, synonyms, sample_values, is_enum, filter label,
    cortex search, PRIVATE from an entry and return (cleaned, modifiers)."""
    mods: dict[str, Any] = {
        "comment": None,
        "synonyms": [],
        "sample_values": [],
        "is_enum": False,
        "is_filter": False,
        "is_private": False,
        "cortex_search_service": None,
    }

    m_priv = _PRIVATE_RE.match(entry)
    if m_priv:
        mods["is_private"] = True
        entry = entry[m_priv.end():].lstrip()

    comment, entry = _extract_comment(entry)
    mods["comment"] = comment

    synonyms, entry = _extract_synonyms(entry)
    mods["synonyms"] = synonyms

    sample_values, entry = _extract_sample_values(entry)
    mods["sample_values"] = sample_values

    if _IS_ENUM_RE.search(entry):
        mods["is_enum"] = True
        entry = _IS_ENUM_RE.sub("", entry).strip()

    m_filter = _FILTER_LABEL_RE.search(entry)
    if m_filter:
        mods["is_filter"] = True
        entry = entry[:m_filter.start()].rstrip() + entry[m_filter.end():]

    m_search = _CORTEX_SEARCH_RE.search(entry)
    if m_search:
        mods["cortex_search_service"] = m_search.group(1)
        entry = entry[:m_search.start()].rstrip() + entry[m_search.end():]

    return entry.strip(), mods


def _extract_semi_additive(cleaned: str) -> tuple[dict[str, str] | None, str]:
    """Extract `non additive by (...)` from cleaned text, returning
    (semi_additive_dict, remaining_text)."""
    m = _NON_ADDITIVE_RE.search(cleaned)
    if not m:
        return None, cleaned
    inner = m.group(1).strip()
    parts = inner.split()
    order_col = parts[0] if parts else ""
    direction = "asc"
    nulls = "last"
    for i, p in enumerate(parts):
        if p.lower() in ("asc", "desc"):
            direction = p.lower()
        if p.lower() == "nulls" and i + 1 < len(parts):
            nulls = parts[i + 1].lower()
    left = cleaned[:m.start()].rstrip()
    right = cleaned[m.end():].lstrip()
    cleaned = left + (" " + right if right else "")
    return {"order_col": order_col, "direction": direction, "nulls": nulls}, cleaned


def _extract_using(cleaned: str) -> tuple[str | None, str]:
    """Extract `USING <rel_name>` from cleaned text."""
    m = _USING_RE.search(cleaned)
    if not m:
        return None, cleaned
    rel = m.group(1)
    left = cleaned[:m.start()].rstrip()
    right = cleaned[m.end():].lstrip()
    return rel, left + (" " + right if right else "")


def _resolve_rhs_alias(
    rhs: str, default_table: str, default_col: str,
) -> tuple[str, str, str | None]:
    """Resolve alias_table, alias_name, expr from the right-hand side of `as`.

    Returns (alias_table, alias_name, expr) — expr is None for a plain
    `alias.NAME` form, and the full RHS text for anything more complex.

    ``alias_table``/``alias_name`` name the construct **as it can be referenced**:

    - A bare ``alias.NAME`` right-hand side is a physical-column alias, so the
      pair is that column and ``expr`` is None.
    - Anything computed keeps the **declared** left-hand-side name, because that
      is the only name another metric can reference the construct by.
      ``sv_translate._build_column_index`` keys both ``fact_idx`` and
      ``metric_idx`` on ``alias_table.alias_name``, so deriving the pair from the
      first qualified token of the expression indexed a computed construct under
      a *physical column of its own table* — producing a reference to the wrong
      column, or a metric that resolved its inner reference to itself
      (BL-178 defect 3; `docs/reviews/2026-07-29-ossie-tpcds-fidelity.md` F9).
      The declared table is also the correct resolver default for bare
      identifiers in the expression: ``COUNT(EMPLOYEE_ID)`` on
      ``EMPLOYEES.HEADCOUNT`` means ``EMPLOYEES.EMPLOYEE_ID``, whatever tables
      the rest of the expression qualifies.
    """
    alias_dot = re.match(
        r"([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\s*$", rhs)
    if alias_dot:
        return alias_dot.group(1), alias_dot.group(2), None

    return default_table.lower(), default_col, rhs


def _build_result(
    source_table: str | None, source_column: str,
    alias_table: str | None, alias_name: str,
    expr: str | None, block_type: str, mods: dict[str, Any],
    semi_additive: dict[str, str] | None,
    using_relationship: str | None,
) -> dict[str, Any]:
    """Assemble the final column entry dict."""
    result: dict[str, Any] = {
        "source_table": source_table,
        "source_column": source_column,
        "alias_table": alias_table,
        "alias_name": alias_name,
        "expr": expr,
        "block": block_type,
        **mods,
    }
    if semi_additive:
        result["semi_additive"] = semi_additive
    if using_relationship:
        result["using_relationship"] = using_relationship
    return result


def _parse_column_entry(raw: str, block_type: str) -> dict[str, Any] | None:
    """Parse a dimension, fact, or metric entry.

    block_type is one of 'dimensions', 'facts', 'metrics'.
    """
    entry = raw.strip()
    if not entry:
        return None

    cleaned, mods = _strip_modifiers(entry)
    semi_additive, cleaned = _extract_semi_additive(cleaned)
    using_relationship, cleaned = _extract_using(cleaned)

    if mods["is_filter"]:
        m_lhs = _TABLE_DOT_COL_RE.match(cleaned)
        if m_lhs:
            rest = cleaned[m_lhs.end():].strip()
            expr = rest[3:].strip() if rest.lower().startswith("as ") else (rest or None)
            return _build_result(
                m_lhs.group(1), m_lhs.group(2),
                m_lhs.group(1).lower(), m_lhs.group(2),
                expr if expr else None, block_type, mods,
                semi_additive, using_relationship)

    m_entry = _DIM_METRIC_ENTRY_RE.match(cleaned)
    if not m_entry:
        # An unqualified derived metric has no owning entity, so there is no
        # TABLE.COL to match. Metrics block only -- a dimension or fact must
        # name its table.
        if block_type == "metrics":
            m_derived = _DERIVED_METRIC_ENTRY_RE.match(cleaned)
            if m_derived and "." not in m_derived.group(1):
                result = _build_result(
                    None, m_derived.group(1), None, m_derived.group(1),
                    m_derived.group(2).strip(), block_type, mods,
                    semi_additive, using_relationship)
                result["is_derived"] = True
                return result
        m_lhs = _TABLE_DOT_COL_RE.match(cleaned)
        if m_lhs:
            rest = cleaned[m_lhs.end():].strip()
            expr = rest[3:].strip() if rest.lower().startswith("as ") else None
            return _build_result(
                m_lhs.group(1), m_lhs.group(2),
                m_lhs.group(1).lower(), m_lhs.group(2),
                expr, block_type, mods, semi_additive, using_relationship)
        return None

    source_table = m_entry.group(1)
    source_column = m_entry.group(2)
    rhs = m_entry.group(3).strip()
    alias_table, alias_name, expr = _resolve_rhs_alias(
        rhs, source_table, source_column)

    return _build_result(
        source_table, source_column, alias_table, alias_name,
        expr, block_type, mods, semi_additive, using_relationship)


# ---------------------------------------------------------------------------
# Verified queries parsing
# ---------------------------------------------------------------------------

def _parse_verified_queries(text: str) -> list[dict[str, Any]]:
    """Parse the ai_verified_queries (...) clause body."""
    entries = _split_top_level(text)
    queries: list[dict[str, Any]] = []
    for entry in entries:
        entry = entry.strip()
        m = _VERIFIED_QUERY_NAME_RE.match(entry)
        if not m:
            continue
        name = m.group(1)
        body = entry[m.end():]
        if body.rstrip().endswith(")"):
            body = body.rstrip()[:-1]

        question: str | None = None
        sql: str | None = None
        verified_at: int | None = None
        verified_by: str | None = None
        onboarding: bool | None = None

        q_m = re.search(r"\bQUESTION\s+'", body, re.IGNORECASE)
        if q_m:
            question, _ = _extract_string_literal(body, q_m.end() - 1)

        s_m = re.search(r"\bSQL\s+'", body, re.IGNORECASE)
        if s_m:
            sql, _ = _extract_string_literal(body, s_m.end() - 1)

        v_m = re.search(r"\bVERIFIED_AT\s+(\d+)", body, re.IGNORECASE)
        if v_m:
            verified_at = int(v_m.group(1))

        vb_m = re.search(r"\bVERIFIED_BY\s+'", body, re.IGNORECASE)
        if vb_m:
            verified_by, _ = _extract_string_literal(body, vb_m.end() - 1)

        o_m = re.search(r"\bONBOARDING_QUESTION\s+(TRUE|FALSE)", body, re.IGNORECASE)
        if o_m:
            onboarding = o_m.group(1).upper() == "TRUE"

        queries.append({
            "name": name,
            "question": question,
            "sql": sql,
            "verified_at": verified_at,
            "verified_by": verified_by,
            "onboarding_question": onboarding,
        })

    return queries


# ---------------------------------------------------------------------------
# Top-level comment extraction (outside any block)
# ---------------------------------------------------------------------------

def _extract_top_level_comment(ddl: str) -> str | None:
    """Extract the top-level comment='...' that appears after all blocks
    but before `with extension`/`ai_*` clauses.

    Searches the region between the last known block keyword's closing paren
    and the first post-block keyword (`with extension`, `ai_sql_generation`,
    etc.), or end-of-DDL if neither exists."""
    block_kws = ("tables", "relationships", "facts", "dimensions", "metrics",
                 "ai_verified_queries")
    last_block_end = 0
    for kw in block_kws:
        pattern = re.compile(r"\b" + kw + r"\s*\(", re.IGNORECASE)
        m = pattern.search(ddl)
        if not m:
            continue
        depth = 1
        i = m.end()
        n = len(ddl)
        while i < n:
            ch = ddl[i]
            if ch == "'":
                _, i = _extract_string_literal(ddl, i)
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    last_block_end = max(last_block_end, i + 1)
                    break
            i += 1

    tail = ddl[last_block_end:]

    boundary_patterns = [_EXTENSION_RE, _AI_SQL_GEN_RE, _AI_QUESTION_CAT_RE]
    earliest_boundary = len(tail)
    for bp in boundary_patterns:
        bm = bp.search(tail)
        if bm:
            earliest_boundary = min(earliest_boundary, bm.start())

    search_region = tail[:earliest_boundary]
    m = _COMMENT_RE.search(search_region)
    if not m:
        return None
    abs_pos = last_block_end + m.end() - 1
    content, _ = _extract_string_literal(ddl, abs_pos)
    return content


# ---------------------------------------------------------------------------
# Custom instructions extraction
# ---------------------------------------------------------------------------

def _extract_ai_instruction(ddl: str, pattern: re.Pattern[str]) -> str | None:
    """Extract an ai_sql_generation='...' or ai_question_categorization='...' value."""
    m = pattern.search(ddl)
    if not m:
        return None
    content, _ = _extract_string_literal(ddl, m.end() - 1)
    return content


# ---------------------------------------------------------------------------
# Extension JSON extraction
# ---------------------------------------------------------------------------

def _extract_extension_json(ddl: str) -> dict[str, Any] | None:
    """Extract with extension (CA='...') JSON."""
    m = _EXTENSION_RE.search(ddl)
    if not m:
        return None
    content, _ = _extract_string_literal(ddl, m.end() - 1)
    try:
        return json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return {"raw": content}


# ---------------------------------------------------------------------------
# View name parsing
# ---------------------------------------------------------------------------

def _parse_view_name(ddl: str) -> dict[str, str | None]:
    """Extract database, schema, name from the CREATE header."""
    m = _VIEW_HEADER_RE.search(ddl)
    if not m:
        return {"database": None, "schema": None, "name": None, "fqn": None}

    raw = m.group(1)
    parts = raw.split(".")
    parts = [p.strip('"') for p in parts]

    if len(parts) >= 3:
        return {"database": parts[0], "schema": parts[1], "name": parts[2],
                "fqn": raw}
    elif len(parts) == 2:
        return {"database": None, "schema": parts[0], "name": parts[1],
                "fqn": raw}
    else:
        return {"database": None, "schema": None, "name": parts[0],
                "fqn": raw}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _parse_column_block(
    ddl: str, block_name: str,
    unsupported: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Extract and parse a column-style block (dimensions, facts, or metrics)."""
    result: list[dict[str, Any]] = []
    text = _extract_clause(ddl, block_name)
    if text is None:
        return result
    for raw_entry in _split_top_level(text):
        parsed = _parse_column_entry(raw_entry, block_name)
        if parsed:
            result.append(parsed)
        elif raw_entry.strip():
            unsupported.append({
                "block": block_name,
                "raw": raw_entry.strip(),
                "reason": f"could not parse {block_name.rstrip('s')} entry",
            })
    return result


def _parse_relationships_block(
    ddl: str,
    unsupported: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Extract and parse the relationships block."""
    result: list[dict[str, Any]] = []
    text = _extract_clause(ddl, "relationships")
    if text is None:
        return result
    for raw_entry in _split_top_level(text):
        parsed = _parse_relationship_entry(raw_entry)
        if parsed:
            result.append(parsed)
        else:
            unsupported.append({
                "block": "relationships",
                "raw": raw_entry.strip(),
                "reason": "could not parse relationship entry",
            })
    return result


def _parse_tables_block(ddl: str) -> list[dict[str, Any]]:
    """Extract and parse the tables block."""
    stripped = _strip_string_literals(ddl)
    tables_text = _extract_clause(stripped, "tables")
    if tables_text is None:
        return []
    raw_tables_text = _extract_clause(ddl, "tables")
    return [_parse_table_entry(e) for e in _split_top_level(raw_tables_text or "")]


def _collect_unverified_warnings(
    columns: list[dict[str, Any]], warnings: list[str],
) -> None:
    """Append warnings for sample_values / is_enum clauses whose DDL shape
    has not been verified against a live GET_DDL round-trip."""
    for col in columns:
        if col.get("sample_values"):
            warnings.append(
                f"sample_values on {col['source_table']}.{col['source_column']}: "
                f"DDL clause shape unverified against live GET_DDL (BL-100 prerequisite)")
        if col.get("is_enum"):
            warnings.append(
                f"is_enum on {col['source_table']}.{col['source_column']}: "
                f"DDL clause shape unverified against live GET_DDL (BL-100 prerequisite)")


def parse_sv_ddl(ddl: str) -> dict[str, Any]:
    """Parse a Snowflake Semantic View DDL string into a structured dict.

    The output shape mirrors the Databricks ``parse_metric_view`` contract:
    structured JSON with ``tables``, ``relationships``, ``dimensions``,
    ``metrics``, ``facts``, ``verified_queries``, ``custom_instructions``,
    ``warnings``, and ``unsupported``.
    """
    warnings: list[str] = []
    unsupported: list[dict[str, str]] = []

    view = _parse_view_name(ddl)

    tables = _parse_tables_block(ddl)
    relationships = _parse_relationships_block(ddl, unsupported)
    facts = _parse_column_block(ddl, "facts", unsupported)
    dimensions = _parse_column_block(ddl, "dimensions", unsupported)
    metrics = _parse_column_block(ddl, "metrics", unsupported)

    top_comment = _extract_top_level_comment(ddl)

    ai_sql = _extract_ai_instruction(ddl, _AI_SQL_GEN_RE)
    ai_question = _extract_ai_instruction(ddl, _AI_QUESTION_CAT_RE)
    custom_instructions: dict[str, str | None] | None = None
    if ai_sql is not None or ai_question is not None:
        custom_instructions = {
            "ai_sql_generation": ai_sql,
            "ai_question_categorization": ai_question,
        }

    vq_text = _extract_clause(ddl, "ai_verified_queries")
    verified_queries = _parse_verified_queries(vq_text) if vq_text else []

    extension = _extract_extension_json(ddl)

    _collect_unverified_warnings(dimensions, warnings)
    _collect_unverified_warnings(facts, warnings)

    return {
        "view_name": view["fqn"],
        "database": view["database"],
        "schema": view["schema"],
        "name": view["name"],
        "comment": top_comment,
        "tables": tables,
        "relationships": relationships,
        "dimensions": dimensions,
        "metrics": metrics,
        "facts": facts,
        "custom_instructions": custom_instructions,
        "verified_queries": verified_queries,
        "extension": extension,
        "warnings": warnings,
        "unsupported": unsupported,
    }
