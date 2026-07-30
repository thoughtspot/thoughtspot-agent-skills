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


def _index_constructs(constructs: list[dict]) -> dict[str, dict]:
    """Index one block's constructs under every name they can be referenced by.

    TWO keys per construct, because "the index key" and "the physical column"
    are different concerns and conflating them is what broke both directions:

    - ``alias_table.source_column`` — the **declared** name (the left-hand side
      of ``ALIAS.NAME as …``). This is the SV's own identifier for the construct
      and, for anything renamed, the only name another expression can use.
      Missing it made a reference to a renamed passthrough
      (``STORE_SALES.revenue as store_sales.ss_ext_sales_price``) fall through to
      the assumed-physical branch and emit ``column_id: STORE_SALES::revenue`` —
      a column that does not exist, with every gate green because it is a
      ``TABLE::col`` reference and so invisible to I13 (PR #424 review F1).
    - ``alias_table.alias_name`` — for a passthrough, the physical column it
      aliases; for anything computed this is the declared name again, so the two
      keys coincide and only one entry is written.

    Declared names are written in a second pass so they always win: a construct's
    own identifier must never be shadowed by another construct's physical-column
    alias.
    """
    idx: dict[str, dict] = {}
    for c in constructs:
        alias = c["alias_table"].lower()
        idx[f"{alias}.{c['alias_name'].lower()}"] = c
    for c in constructs:
        alias = c["alias_table"].lower()
        idx[f"{alias}.{c['source_column'].lower()}"] = c
    return idx


def _build_column_index(
    parsed: dict,
) -> tuple[dict[str, dict], dict[str, dict]]:
    """Build fact and metric indexes keyed by (alias, name) lowercase.

    Returns (fact_index, metric_index). See :func:`_index_constructs` for why
    each construct is indexed under two keys."""
    return (_index_constructs(parsed.get("facts", [])),
            _index_constructs(parsed.get("metrics", [])))


def display_title(entry: dict) -> str:
    """The ThoughtSpot display name for an SV construct — first synonym, else
    title-cased name.

    THE one naming path. ``sv_build_model`` mints every formula id as
    ``formula_<display_title>`` and re-exports this function rather than
    restating the rule, because two independent naming paths are exactly what
    BL-178 defect 2 was: the resolver emitted ``[formula_<sql_token>]`` while the
    builder declared ``id: formula_<display title>``, so every metric-on-fact
    reference dangled. Anything that needs to *predict* a minted id must call
    this."""
    synonyms = entry.get("synonyms") or []
    if synonyms:
        return synonyms[0]
    return entry["name"].replace("_", " ").title()


def construct_formula_id(construct: dict) -> str:
    """The `formulas[].id` build-model will mint for a parsed SV construct.

    ``construct`` is a parse-sv dimension/fact/metric dict (declared name in
    ``source_column``); the translated entry that reaches build-model carries the
    same name under ``name``."""
    return "formula_" + display_title(
        {"name": construct["source_column"],
         "synonyms": construct.get("synonyms")})


def _build_table_pair_pk_map(
    parsed: dict,
) -> dict[tuple[str, str], tuple[str, str, str]]:
    """Map an unordered table-name pair -> (parent_table, parent_pk, rel_name).

    Used by double-aggregation resolution (ts-from-snowflake-rules.md "Double
    Aggregation (Metric-on-Metric)", step 1): "identify the relationship
    connecting the inner metric's table to the outer metric's table. The grouping
    key is the primary key column on the parent (TO) side of that relationship."
    The relationship name is carried so the mandated 🔄 review marker can name it.
    """
    out: dict[tuple[str, str], tuple[str, str, str]] = {}
    for r in parsed.get("relationships", []):
        from_table = (r.get("from_table") or "").lower()
        to_table = (r.get("to_table") or "").lower()
        to_col = r.get("to_column") or (r.get("to_cols") or [None])[0]
        if not from_table or not to_table or not to_col:
            continue
        out.setdefault(tuple(sorted((from_table, to_table))),
                       (r["to_table"], to_col, r.get("name") or "?"))
    return out


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


def _resolve_double_aggregation(
    inner_metric: dict,
    outer_table: str,
    parsed: dict,
    alias_map: dict[str, str],
    pair_pk_map: dict[tuple[str, str], tuple[str, str, str]],
    resolving: frozenset,
    annotate: Callable[[str], None],
) -> str | None:
    """Resolve a metric-on-metric reference to a `group_*` expression.

    Implements step 3 of the Identifier Resolution Algorithm as specified in
    ts-from-snowflake-rules.md "Double Aggregation (Metric-on-Metric)": find the
    relationship connecting the inner metric's table to the outer metric's table,
    group over the primary key on the parent (TO) side, and use the `group_*`
    shorthand for the inner metric's aggregation (full `group_aggregate` form when
    no shorthand exists).

    Returns None when there is no safe double aggregation to emit — the two tables
    are not connected by a relationship (no grouping key exists), or the inner
    measure IS the grouping column (see the degeneracy guard below). The caller
    then falls back to the inner metric's formula id.

    ``resolving`` carries the index keys already on the resolution stack; it is
    threaded into the inner resolver so a cyclic SV (metric A over metric B over
    metric A) terminates with a formula-id reference rather than a RecursionError.
    """
    inner_table = (inner_metric.get("alias_table") or "").lower()
    outer = outer_table.lower()
    if not inner_table or inner_table == outer:
        return None
    rel = pair_pk_map.get(tuple(sorted((inner_table, outer))))
    if rel is None:
        return None
    parent_table, parent_pk, rel_name = rel
    group_key_node = alias_map.get(parent_table.lower(), parent_table)
    group_key_ref = f"{group_key_node}::{parent_pk}"
    group_key = f"[{group_key_ref}]"
    inner_name = inner_metric["source_column"]

    # The inner metric's own expression is resolved against ITS table, so a bare
    # identifier inside it binds to the table the metric is declared on. Its own
    # notes are forwarded through `annotate` so an ambiguity inside the inner
    # expression is not swallowed by the nesting.
    inner_notes: list[str] = []
    inner_resolver = make_resolver(
        parsed, inner_metric["alias_table"], annotations=inner_notes,
        _resolving=resolving)
    def _flush() -> None:
        for note in inner_notes:
            annotate(note)

    agg = _is_simple_agg(inner_metric.get("expr"))
    col_info = (_try_simple_agg_column(inner_metric["expr"], inner_resolver)
                if agg is not None else None)
    _flush()

    # Degeneracy guard — grouping a measure by itself. `group_count([X], [X])` is
    # 1 for every group and `group_sum([X], [X])` is X: a plausible-looking
    # formula with wrong numbers, which is worse than no formula at all. Skip the
    # double aggregation and say why rather than emitting it.
    if col_info and f"{col_info[0]}::{col_info[1]}".lower() == group_key_ref.lower():
        annotate(
            f"⚑ metric '{inner_name}' aggregates {group_key_ref}, which is also "
            f"the grouping column implied by relationship '{rel_name}' — double "
            f"aggregation skipped (grouping a measure by itself yields one row "
            f"per group). Verify what the metric is meant to count.")
        return None

    marker = (
        f"🔄 double aggregation: '{inner_name}' grouped by {group_key_ref} via "
        f"relationship '{rel_name}' — verify the grouping key and relationship "
        f"direction against the semantic view's intent "
        f"(ts-from-snowflake-rules.md, Double Aggregation).")

    if col_info is not None and agg is not None:
        group_fn = _AGG_TO_GROUP.get(agg.lower())
        if group_fn and group_fn != "group_aggregate":
            annotate(marker)
            return (f"{group_fn} ( [{col_info[0]}::{col_info[1]}] , "
                    f"{group_key} )")

    # No shorthand (complex inner expression, or an aggregation with no `group_*`
    # equivalent) -> the documented full form. `query_filters()` is mandatory:
    # it propagates user-applied runtime filters into the inner aggregation.
    inner_ts = translate_sql_expr(inner_metric["expr"], inner_resolver)
    _flush()
    if set(re.findall(r"\[([^\[\]]+)\]", inner_ts)) == {group_key_ref}:
        annotate(
            f"⚑ metric '{inner_name}' reads only {group_key_ref}, the grouping "
            f"column implied by relationship '{rel_name}' — double aggregation "
            f"skipped (grouping a measure by itself). Verify the intent.")
        return None
    annotate(marker)
    return f"group_aggregate ( {inner_ts} , {{{group_key}}} , query_filters ( ) )"


def make_resolver(
    parsed: dict,
    default_alias: str,
    *,
    annotations: list[str] | None = None,
    _resolving: frozenset = frozenset(),
) -> Callable[[str], str]:
    """Build a resolver: SQL identifier -> [TABLE::col], [formula_id] or group_*.

    Resolution order per ts-from-snowflake-rules.md Identifier Resolution
    Algorithm (:585-593) — physical column FIRST:

    1. Physical column on table_alias's table -> ``[TABLE::col]``. A fact or
       metric declared under that name which is itself a **passthrough** of a
       physical column (``expr is None``) is an alias for that column and takes
       this step too — a passthrough fact becomes a plain ``columns[]`` entry and
       a passthrough metric is skipped outright (it carries no aggregation), so in
       neither case does a formula exist to reference. An identifier no
       fact/metric declares is assumed physical and resolves the same way.
    1b. DIMENSION -> still the physical-column layer, so part of step 1, but it
       is a **declared** construct and its shape decides the target: see
       :func:`_dimension_ref` for the three-way split (passthrough -> the column
       ``alias_name`` names; bare-column rename -> the column the EXPRESSION
       names; computed -> ``[formula_<id>]``). It is probed after the
       fact/metric indexes and before the assumed-physical fallback — a renamed
       dimension that skipped this branch emitted a column that does not exist
       (the second half of BL-178; cross-index ambiguity is BL-195).
    2. FACT -> ``[formula_<id>]``, the id build-model mints (see
       :func:`construct_formula_id`) — NOT the SQL token, and not the bare
       display name.
    3. METRIC -> double aggregation via ``group_*`` when a relationship connects
       the two tables (see :func:`_resolve_double_aggregation`); otherwise the
       inner metric's ``[formula_<id>]``.
    4. FAIL -> UntranslatableError.

    Steps 1 and 2 were inverted, and step 2/3 emitted ``[formula_<sql_token>]``
    against ids minted from the display name, so **every** metric reference in the
    emitted Model TML dangled while `ts tml lint` reported clean — BL-178,
    `docs/reviews/2026-07-29-ossie-tpcds-fidelity.md` F9. `ts tml lint`'s I13 now
    gates the resulting property.

    ``annotations``, when supplied, collects review markers the caller must
    surface: the 🔄 double-aggregation marker the rules file mandates, and ⚑
    warnings for the two ambiguous shapes the resolver cannot settle on its own
    (a renamed passthrough referenced by its declared name, and a degenerate
    grouping). Passing None discards them.

    ``_resolving`` is private: step 3 builds a nested resolver for the inner
    metric's own expression, so this carries the index keys already on the stack
    and breaks a cycle (metric A over metric B over metric A) by falling back to
    a formula-id reference instead of recursing forever.
    """
    alias_map = _build_alias_map(parsed)
    fact_idx, metric_idx = _build_column_index(parsed)
    dim_idx = _index_constructs(parsed.get("dimensions", []))
    pair_pk_map = _build_table_pair_pk_map(parsed)

    def _annotate(note: str) -> None:
        if annotations is not None and note not in annotations:
            annotations.append(note)

    def _physical_ref(construct: dict, ref_col: str) -> str:
        """The physical column a passthrough construct aliases.

        When the construct was reached by its DECLARED name and that name differs
        from the physical column, the reference is ambiguous in a way this
        resolver cannot settle: the SV namespace says it means the construct, but
        a physical column of the declared name may also exist on the table and
        there is no column inventory here to check (the rules file's step 1 inputs
        list Table TML exports, which `translate-formulas` never receives). It
        resolves to the construct — the only column known to exist — and flags
        both candidates so the ambiguity lands in the translation log rather than
        silently in the numbers.
        """
        table = alias_map.get(construct["alias_table"].lower(),
                              construct["source_table"])
        physical = construct["alias_name"]
        if ref_col.lower() != physical.lower():
            _annotate(
                f"⚑ reference '{construct['alias_table']}.{ref_col}' resolves to "
                f"the semantic view's '{construct['source_column']}', which "
                f"aliases physical column {table}::{physical}. If a physical "
                f"column named '{ref_col}' also exists on {table}, confirm which "
                f"one the expression means.")
        return f"[{table}::{physical}]"

    def _dimension_ref(dim: dict, ref_col: str) -> str:
        """Resolve a reference to a declared dimension — three shapes.

        A dimension is the physical-column layer, so this is still step 1, but
        which column (or formula) it lands on depends on the shape `parse-sv`
        reported — and `_translate_dimension` makes exactly the same three-way
        split, so the two must agree:

        1. passthrough (``expr is None``) -> the column ``alias_name`` names;
        2. bare-column rename (``CASE_ID as ID``) -> the column the EXPRESSION
           names, not ``alias_name`` (which is the declared name for this shape);
        3. computed -> a formula, referenced by the minted id.

        Without this, a renamed dimension referenced by its declared name fell
        through to the assumed-physical branch and emitted a column that does not
        exist — `DM_CATEGORY.CATEGORY as dm_category.CATEGORY_NAME` referenced as
        `PARTITION BY dm_category.category` emitted `[DM_CATEGORY::category]`
        against a real column of `CATEGORY_NAME` (the dunder worked example's own
        shape). Same silent-until-import class as BL-178, and invisible to
        `ts tml lint`, which sees no dangling `[formula_*]` — see BL-195.
        """
        expr = dim.get("expr")
        if expr is None:
            return _physical_ref(dim, ref_col)
        bare = expr.strip()
        if _BARE_COLUMN_RE.match(bare):
            table = alias_map.get(dim["alias_table"].lower(),
                                  dim["source_table"])
            if ref_col.lower() != bare.lower():
                _annotate(
                    f"⚑ reference '{dim['alias_table']}.{ref_col}' resolves to "
                    f"the semantic view's '{dim['source_column']}', which "
                    f"renames physical column {table}::{bare}. If a physical "
                    f"column named '{ref_col}' also exists on {table}, confirm "
                    f"which one the expression means.")
            return f"[{table}::{bare}]"
        return f"[{construct_formula_id(dim)}]"

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
            fact = fact_idx.get(key)
            metric = metric_idx.get(key)

            # Step 1 — a passthrough construct IS the physical column it aliases.
            if fact is not None and fact.get("expr") is None:
                return _physical_ref(fact, col)
            if metric is not None and metric.get("expr") is None:
                return _physical_ref(metric, col)

            # Step 2 — a computed fact is a formula; reference it by minted id.
            if fact is not None:
                return f"[{construct_formula_id(fact)}]"

            # Step 3 — metric-on-metric.
            if metric is not None:
                if key not in _resolving:
                    grouped = _resolve_double_aggregation(
                        metric, default_alias, parsed, alias_map, pair_pk_map,
                        _resolving | {key}, _annotate)
                    if grouped is not None:
                        return grouped
                return f"[{construct_formula_id(metric)}]"

            # Step 1 (continued) — a declared dimension, whose shape decides
            # which column or formula it resolves to.
            dim = dim_idx.get(key)
            if dim is not None:
                return _dimension_ref(dim, col)

            # Step 1 (continued) — no construct declares this name, so it is a
            # physical column on the aliased table.
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

_BARE_COLUMN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def _translate_dimension(
    dim: dict, parsed: dict, alias_map: dict[str, str],
) -> dict[str, Any]:
    """Translate one dimension entry.

    A dimension is emitted as a direct **column** (column_id) — not a formula —
    both when it has no expression and when its expression is a bare physical
    column reference (a simple rename such as ``CASE_ID as ID``). Renames are
    columns in ThoughtSpot, and a table needs at least one real column selected
    or it imports with a cross-join warning. Only genuine expressions
    (``STATUS IN (...)``, functions) become formulas."""
    table = alias_map.get(dim["alias_table"].lower(), dim["source_table"])
    expr = dim["expr"]
    if expr is None:
        return _entry(
            dim["source_column"], "dimension", "column", "ATTRIBUTE", dim,
            table=table, column=dim["alias_name"])
    if _BARE_COLUMN_RE.match(expr.strip()):
        return _entry(
            dim["source_column"], "dimension", "column", "ATTRIBUTE", dim,
            table=table, column=expr.strip())
    annotations: list[str] = []
    resolver = make_resolver(
        parsed, dim["alias_table"], annotations=annotations)
    ts_expr = translate_sql_expr(dim["expr"], resolver)
    return _entry(
        dim["source_column"], "dimension", "formula", "ATTRIBUTE", dim,
        ts_expr=ts_expr, annotations=annotations)


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
    annotations: list[str] = []
    resolver = make_resolver(
        parsed, fact["alias_table"], annotations=annotations)
    ts_expr = translate_sql_expr(fact["expr"], resolver)
    return _entry(
        fact["source_column"], "fact", "formula", "ATTRIBUTE", fact,
        ts_expr=ts_expr, annotations=annotations)


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
    """Translate one metric entry.

    A metric with no expression (``ALIAS.NAME as other.COLUMN`` — a bare
    physical-column right-hand side) declares no aggregation, so there is nothing
    to translate: it is refused loudly here rather than reaching
    ``translate_sql_expr(None, …)`` and surfacing as a raw ``AttributeError``
    (PR #424 review F8). Documented step 4 — the orchestrator records it in
    ``skipped[]`` with a reason the user can act on.
    """
    annotations: list[str] = []
    expr = metric["expr"]
    if expr is None:
        raise UntranslatableError(
            f"metric '{metric['source_column']}' has no aggregate expression "
            f"(right-hand side is the bare column "
            f"'{metric['alias_table']}.{metric['alias_name']}') — declare it in "
            f"dimensions() or facts(), or give the metric an aggregation")
    resolver = make_resolver(
        parsed, metric["alias_table"], annotations=annotations)
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
                aggregation=col_info[2], annotations=annotations)

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
