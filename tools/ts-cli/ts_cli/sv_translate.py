"""Parsed Semantic View -> translated ThoughtSpot formulas
(`ts snowflake translate-formulas`).

Pure functions: parse-sv dict in, JSON-ready dict out. No I/O, no network
calls — trivially unit-testable.

Mapping rules: agents/shared/mappings/ts-snowflake/
ts-snowflake-formula-translation.md and ts-from-snowflake-rules.md.
"""
from __future__ import annotations

import re
from typing import Any, Callable

from ts_cli.formula_common import UntranslatableError
from ts_cli.sv_sql import translate_sql_expr


# --- identifier resolution --------------------------------------------------

def build_node_id_map(parsed: dict) -> dict[str, str]:
    """Map each SV table alias -> its ThoughtSpot model node id (role-play aware).

    A physical table referenced by more than one SV table is *reused* — a
    role-playing pattern (e.g. one ``USER`` table played as ``CASE_OWNER``,
    ``INCIDENT_OWNER`` and ``INCIDENT_RESOLVED_BY``). Each reused instance whose
    alias differs from the physical name becomes its own node, identified by the
    alias, so column references and joins stay unambiguous. A single-use table
    (or the one instance whose alias equals the physical name) uses the physical
    table name as its node id — no alias needed.

    Returns ``{sv_alias: node_id}``. Keyed by the alias exactly as parsed."""
    tables = parsed.get("tables", [])
    phys_count: dict[str, int] = {}
    for t in tables:
        phys_count[t["name"]] = phys_count.get(t["name"], 0) + 1
    node_of: dict[str, str] = {}
    for t in tables:
        alias, phys = t["alias"], t["name"]
        reused = phys_count[phys] > 1
        node_of[alias] = alias if (reused and alias != phys) else phys
    return node_of


def _build_alias_map(parsed: dict) -> dict[str, str]:
    """Map lowercase table alias -> ThoughtSpot node id (role-play aware).

    Node ids come from :func:`build_node_id_map`, so a reused physical table's
    role-playing instances resolve to distinct nodes (``[ON_BEHALF_ACCOUNT::ID]``
    vs ``[ACCOUNT::ID]``) instead of collapsing onto the shared physical name.

    Also maps the table name itself (lowercased) as a fallback — SV DDL uses
    source table names in some positions (e.g. ``non additive by (TABLE.COL)``),
    not the alias. For a reused physical name the first-seen node wins (bare
    physical-name references to an all-aliased reused table are ambiguous and
    not expected in valid SV DDL)."""
    node_of = build_node_id_map(parsed)
    alias_map: dict[str, str] = {}
    for t in parsed["tables"]:
        node = node_of[t["alias"]]
        alias_map[t["alias"].lower()] = node
        alias_map.setdefault(t["name"].lower(), node)
    return alias_map


def _build_column_index(
    parsed: dict,
) -> tuple[dict[str, dict], dict[str, dict]]:
    """Build fact and metric indexes keyed by (alias, name) lowercase.

    Returns (fact_index, metric_index)."""
    facts: dict[str, dict] = {}
    for f in parsed.get("facts", []):
        key = f"{f['alias_table'].lower()}.{f['alias_name'].lower()}"
        facts[key] = f
    metrics: dict[str, dict] = {}
    for m in parsed.get("metrics", []):
        key = f"{m['alias_table'].lower()}.{m['alias_name'].lower()}"
        metrics[key] = m
    return facts, metrics


def _build_relationship_pk_map(
    parsed: dict,
) -> dict[str, tuple[str, str]]:
    """Map relationship name -> (to_table, pk_column) for USING/group_aggregate.

    The PK is the referenced column on the TO side of the relationship."""
    pk_map: dict[str, tuple[str, str]] = {}
    for r in parsed.get("relationships", []):
        to_table = r["to_table"]
        # parse-sv emits `to_cols` (a list, for composite keys); older callers
        # used a singular `to_column`. Accept either, taking the first key column.
        to_col = r.get("to_column") or (r.get("to_cols") or [None])[0]
        pk_map[r["name"]] = (to_table, to_col)
    return pk_map


def make_resolver(
    parsed: dict,
    default_alias: str,
) -> Callable[[str], str]:
    """Build a resolver: SQL identifier -> [TABLE::col] or [formula_xxx].

    Resolution order per ts-from-snowflake-rules.md Identifier Resolution
    Algorithm:
    1. Physical column on table_alias's table -> [TABLE::col]
    2. FACT (matching alias.name) -> [formula_<name>]
    3. METRIC (matching alias.name) -> [formula_<name>]
    4. FAIL -> UntranslatableError
    """
    alias_map = _build_alias_map(parsed)
    fact_idx, metric_idx = _build_column_index(parsed)

    def resolve(ident: str) -> str:
        parts = ident.split(".")
        if len(parts) == 1:
            col = parts[0]
            table = alias_map.get(default_alias.lower())
            if not table:
                raise UntranslatableError(
                    f"no table for bare identifier '{col}' "
                    f"(default alias '{default_alias}' not found)")
            return f"[{table}::{col}]"
        if len(parts) == 2:
            alias, col = parts[0].lower(), parts[1]
            key = f"{alias}.{col.lower()}"
            if key in fact_idx:
                return f"[formula_{col}]"
            if key in metric_idx:
                return f"[formula_{col}]"
            table = alias_map.get(alias)
            if not table:
                raise UntranslatableError(
                    f"unknown table alias '{parts[0]}' in reference "
                    f"'{ident}'")
            return f"[{table}::{col}]"
        raise UntranslatableError(
            f"cannot resolve multi-part identifier '{ident}'")

    return resolve


# --- window expression handling ----------------------------------------------

_OVER_RE = re.compile(r"\bOVER\s*\(", re.IGNORECASE)

_AGG_TO_GROUP = {
    "sum": "group_sum", "count": "group_count",
    "average": "group_average", "min": "group_min", "max": "group_max",
    "unique count": "group_unique_count",
    "median": "group_aggregate", "stddev": "group_aggregate",
    "variance": "group_aggregate",
}

_AGG_TO_CUMULATIVE = {
    "sum": "cumulative_sum", "average": "cumulative_average",
    "min": "cumulative_min", "max": "cumulative_max",
}

_AGG_TO_MOVING = {
    "sum": "moving_sum", "average": "moving_average",
    "min": "moving_min", "max": "moving_max",
}


def _skip_string_literal(expr: str, i: int, n: int) -> int:
    """Advance past a single-quoted string literal starting at position i.

    Returns the index after the closing quote."""
    i += 1
    while i < n:
        if expr[i] == "'" and i + 1 < n and expr[i + 1] == "'":
            i += 2
            continue
        if expr[i] == "'":
            return i + 1
        i += 1
    return i


def _find_over_split(expr: str) -> int | None:
    """Find the position of OVER keyword outside string literals and parens.

    Returns the char index of the 'O' in OVER, or None if not found."""
    depth = 0
    i = 0
    n = len(expr)
    while i < n:
        ch = expr[i]
        if ch == "'":
            i = _skip_string_literal(expr, i, n)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and expr[i:i + 4].upper() == "OVER":
            after = i + 4
            while after < n and expr[after] in " \t\n\r":
                after += 1
            if after < n and expr[after] == "(":
                return i
        i += 1
    return None


def _extract_over_clause(expr: str, over_pos: int) -> tuple[str, str]:
    """Split expr at OVER position into (agg_sql, window_spec_inner).

    Returns the SQL before OVER and the content inside OVER(...)."""
    agg_sql = expr[:over_pos].rstrip()
    rest = expr[over_pos + 4:].lstrip()
    if not rest.startswith("("):
        raise UntranslatableError("OVER without opening paren")
    depth = 0
    for i, ch in enumerate(rest):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                inner = rest[1:i].strip()
                return agg_sql, inner
    raise UntranslatableError("OVER clause: unbalanced parentheses")


def _clause_boundaries(upper: str) -> tuple:
    """Find regex match positions for PARTITION BY, ORDER BY, ROWS."""
    pb = re.search(r"\bPARTITION\s+BY\b", upper)
    ob = re.search(r"\bORDER\s+BY\b", upper)
    rows = re.search(r"\bROWS\b", upper)
    return pb, ob, rows


def _parse_partition_cols(spec: str, start: int, end: int) -> list[str]:
    text = spec[start:end].strip()
    return [c.strip() for c in text.split(",") if c.strip()]


def _parse_order_cols(spec: str, start: int, end: int) -> list[dict]:
    text = spec[start:end].strip()
    cols: list[dict] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        direction = "asc"
        for t in tokens[1:]:
            if t.upper() in ("ASC", "DESC"):
                direction = t.lower()
        cols.append({"col": tokens[0], "dir": direction})
    return cols


def _parse_frame(spec: str, start: int) -> str | None:
    text = spec[start:].strip().upper()
    if "UNBOUNDED PRECEDING" in text:
        return "cumulative"
    if "PRECEDING" in text:
        return "moving"
    return "other"


def _parse_window_spec(spec: str) -> dict[str, Any]:
    """Parse the inner content of OVER(...) into structured components."""
    if not spec.strip():
        return {"partition_by": [], "order_by": [], "frame": None}

    pb, ob, rows = _clause_boundaries(spec.upper())

    partition = []
    if pb:
        end = ob.start() if ob else (rows.start() if rows else len(spec))
        partition = _parse_partition_cols(spec, pb.end(), end)

    order = []
    if ob:
        end = rows.start() if rows else len(spec)
        order = _parse_order_cols(spec, ob.end(), end)

    frame = _parse_frame(spec, rows.end()) if rows else None

    return {"partition_by": partition, "order_by": order, "frame": frame}


def _unwrap_agg(ts_expr: str) -> tuple[str, str]:
    """Extract (agg_function_name, inner_args) from translated TS agg expr.

    E.g. 'sum ( [T::x] )' -> ('sum', '[T::x]')."""
    m = re.match(r"^(\w[\w ]*?)\s*\(\s*(.*)\s*\)$", ts_expr, re.DOTALL)
    if not m:
        raise UntranslatableError(
            f"cannot unwrap aggregate from '{ts_expr}' for window translation")
    return m.group(1).strip(), m.group(2).strip()


def _translate_window(
    ts_agg_expr: str,
    window_spec: dict[str, Any],
    resolver: Callable[[str], str],
) -> str:
    """Translate an aggregate + OVER window spec to TS formula."""
    agg_fn, inner = _unwrap_agg(ts_agg_expr)
    partition = window_spec["partition_by"]
    order = window_spec["order_by"]
    frame = window_spec["frame"]

    if frame == "cumulative" and order:
        fn = _AGG_TO_CUMULATIVE.get(agg_fn)
        if fn is None:
            raise UntranslatableError(
                f"cumulative window for '{agg_fn}' not mapped")
        order_col = resolver(order[0]["col"])
        return f"{fn} ( {inner} , {order_col} )"

    if frame in ("moving",) and order:
        fn = _AGG_TO_MOVING.get(agg_fn)
        if fn is None:
            raise UntranslatableError(
                f"moving window for '{agg_fn}' not mapped")
        order_col = resolver(order[0]["col"])
        return f"{fn} ( {inner} , -1 , 0 , {order_col} )"

    group_fn = _AGG_TO_GROUP.get(agg_fn)
    if group_fn is None:
        raise UntranslatableError(
            f"window function for '{agg_fn}' not mapped")
    if not partition:
        return f"{group_fn} ( {inner} )"
    resolved_parts = [resolver(p) for p in partition]
    parts_str = " , ".join(resolved_parts)
    return f"{group_fn} ( {inner} , {parts_str} )"


# --- semi-additive wrapping --------------------------------------------------

def _wrap_semi_additive(
    ts_expr: str,
    semi_additive: dict[str, str],
    resolver: Callable[[str], str],
) -> str:
    """Wrap a translated expression with last_value/first_value for
    semi-additive metrics.

    asc -> last_value (latest value); desc -> first_value (earliest value)."""
    order_col = resolver(semi_additive["order_col"])
    direction = semi_additive.get("direction", "asc")
    fn = "last_value" if direction == "asc" else "first_value"
    return f"{fn} ( {ts_expr} , query_groups ( ) , {{{order_col}}} )"


# --- column classification ---------------------------------------------------

_SIMPLE_AGG_RE = re.compile(
    r"^(SUM|COUNT|AVG|MIN|MAX|MEDIAN|STDDEV|VARIANCE)\s*\(",
    re.IGNORECASE)

_SIMPLE_AGG_MAP = {
    "SUM": "SUM", "COUNT": "COUNT", "AVG": "AVERAGE",
    "MIN": "MIN", "MAX": "MAX",
    "MEDIAN": "MEDIAN", "STDDEV": "STDDEV", "VARIANCE": "VARIANCE",
}


def _is_simple_agg(expr: str | None) -> str | None:
    """Check if expr is a simple AGG(col) pattern, return TS aggregation name.

    Returns None if not a simple single-column aggregate."""
    if expr is None:
        return None
    m = _SIMPLE_AGG_RE.match(expr.strip())
    if not m:
        return None
    fn = m.group(1).upper()
    inner = expr[m.end():].strip()
    depth = 1
    for i, ch in enumerate(inner):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                col_part = inner[:i].strip()
                rest = inner[i + 1:].strip()
                if rest:
                    return None
                if re.match(r"^[A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?$",
                            col_part):
                    return _SIMPLE_AGG_MAP.get(fn)
                return None
    return None


# --- entry builders ----------------------------------------------------------

def _entry(
    name: str, role: str, output_kind: str, column_type: str,
    source: dict, *,
    table: str | None = None, column: str | None = None,
    ts_expr: str | None = None, aggregation: str | None = None,
    annotations: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "role": role,
        "output_kind": output_kind,
        "column_type": column_type,
        "table": table,
        "column": column,
        "ts_expr": ts_expr,
        "aggregation": aggregation,
        "comment": source.get("comment"),
        "synonyms": source.get("synonyms") or [],
        "is_private": source.get("is_private", False),
        "annotations": annotations or [],
    }


# --- per-block translators ---------------------------------------------------

def _translate_dimension(
    dim: dict, parsed: dict, alias_map: dict[str, str],
) -> dict[str, Any]:
    """Translate one dimension entry."""
    table = alias_map.get(dim["alias_table"].lower(), dim["source_table"])
    if dim["expr"] is None:
        return _entry(
            dim["source_column"], "dimension", "column", "ATTRIBUTE", dim,
            table=table, column=dim["alias_name"])
    resolver = make_resolver(parsed, dim["alias_table"])
    ts_expr = translate_sql_expr(dim["expr"], resolver)
    return _entry(
        dim["source_column"], "dimension", "formula", "ATTRIBUTE", dim,
        ts_expr=ts_expr)


def _translate_fact(
    fact: dict, parsed: dict, alias_map: dict[str, str],
) -> dict[str, Any]:
    """Translate one fact entry. Facts are intermediate computed columns —
    always formulas, classified as ATTRIBUTE (non-aggregated) or MEASURE."""
    if fact["expr"] is None:
        table = alias_map.get(fact["alias_table"].lower(), fact["source_table"])
        return _entry(
            fact["source_column"], "fact", "column", "ATTRIBUTE", fact,
            table=table, column=fact["alias_name"])
    resolver = make_resolver(parsed, fact["alias_table"])
    ts_expr = translate_sql_expr(fact["expr"], resolver)
    return _entry(
        fact["source_column"], "fact", "formula", "ATTRIBUTE", fact,
        ts_expr=ts_expr)


def _try_simple_agg_column(
    expr: str, resolver: Callable[[str], str],
) -> tuple[str, str, str] | None:
    """If expr is a simple AGG(col), resolve to (table, column, aggregation).

    Returns None if not a simple pattern or if the col resolves to a formula."""
    agg = _is_simple_agg(expr)
    if agg is None:
        return None
    m = _SIMPLE_AGG_RE.match(expr)
    inner_text = expr[m.end():]
    depth = 1
    for i, ch in enumerate(inner_text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                col_ref = inner_text[:i].strip()
                break
    else:
        return None
    resolved = resolver(col_ref)
    rm = re.match(r"\[([^:]+)::([^\]]+)\]", resolved)
    if rm:
        return rm.group(1), rm.group(2), agg
    return None


def _apply_using(
    ts_expr: str,
    using: str,
    rel_pk_map: dict[str, tuple[str, str]],
    alias_map: dict[str, str],
    annotations: list[str],
) -> str:
    """Wrap a translated metric expr with group_aggregate for USING."""
    rel_info = rel_pk_map.get(using)
    if not rel_info:
        return ts_expr
    to_table, to_col = rel_info
    ts_table = alias_map.get(to_table.lower(), to_table)
    agg_fn, inner = _unwrap_agg(ts_expr)
    group_fn = _AGG_TO_GROUP.get(agg_fn, "group_aggregate")
    annotations.append(
        f"USING {using}: group_aggregate via {to_table}.{to_col}")
    return (f"{group_fn} ( {inner} , "
            f"{{[{ts_table}::{to_col}]}} , query_filters ( ) )")


def _translate_metric(
    metric: dict,
    parsed: dict,
    alias_map: dict[str, str],
    rel_pk_map: dict[str, tuple[str, str]],
) -> dict[str, Any]:
    """Translate one metric entry."""
    resolver = make_resolver(parsed, metric["alias_table"])
    expr = metric["expr"]
    annotations: list[str] = []
    semi = metric.get("semi_additive")
    using = metric.get("using_relationship")

    over_pos = _find_over_split(expr) if expr else None
    if over_pos is not None:
        agg_sql, window_inner = _extract_over_clause(expr, over_pos)
        ts_agg = translate_sql_expr(agg_sql, resolver)
        ts_expr = _translate_window(
            ts_agg, _parse_window_spec(window_inner), resolver)
        if semi:
            ts_expr = _wrap_semi_additive(ts_expr, semi, resolver)
        return _entry(
            metric["source_column"], "metric", "formula", "MEASURE",
            metric, ts_expr=ts_expr, annotations=annotations)

    if not semi and not using:
        col_info = _try_simple_agg_column(expr, resolver)
        if col_info:
            return _entry(
                metric["source_column"], "metric", "column", "MEASURE",
                metric, table=col_info[0], column=col_info[1],
                aggregation=col_info[2])

    ts_expr = translate_sql_expr(expr, resolver)
    if using:
        ts_expr = _apply_using(
            ts_expr, using, rel_pk_map, alias_map, annotations)
    if semi:
        ts_expr = _wrap_semi_additive(ts_expr, semi, resolver)
    return _entry(
        metric["source_column"], "metric", "formula", "MEASURE",
        metric, ts_expr=ts_expr, annotations=annotations)


# --- orchestrator ------------------------------------------------------------

def translate_sv_formulas(parsed: dict) -> dict[str, Any]:
    """Translate all formulas from a parsed Semantic View into ThoughtSpot syntax.

    Returns {translated: [...], skipped: [...], stats: {...}}.
    """
    alias_map = _build_alias_map(parsed)
    rel_pk_map = _build_relationship_pk_map(parsed)

    translated: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    for dim in parsed.get("dimensions", []):
        try:
            translated.append(_translate_dimension(dim, parsed, alias_map))
        except UntranslatableError as e:
            skipped.append({
                "name": dim["source_column"],
                "block": "dimensions",
                "reason": str(e),
            })

    for fact in parsed.get("facts", []):
        try:
            translated.append(_translate_fact(fact, parsed, alias_map))
        except UntranslatableError as e:
            skipped.append({
                "name": fact["source_column"],
                "block": "facts",
                "reason": str(e),
            })

    for metric in parsed.get("metrics", []):
        try:
            translated.append(
                _translate_metric(metric, parsed, alias_map, rel_pk_map))
        except UntranslatableError as e:
            skipped.append({
                "name": metric["source_column"],
                "block": "metrics",
                "reason": str(e),
            })

    total = (len(parsed.get("dimensions", []))
             + len(parsed.get("facts", []))
             + len(parsed.get("metrics", [])))

    return {
        "translated": translated,
        "skipped": skipped,
        "stats": {
            "total": total,
            "translated": len(translated),
            "skipped": len(skipped),
        },
    }
