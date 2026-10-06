"""Snowflake Semantic View identifier resolution.

Split out of ``sv_translate`` (with ``sv_window``) when that module reached the
1000-line gate. Everything here answers "what does this SQL identifier refer to
in the emitted Model?" — ``[TABLE::col]``, ``[formula_<id>]`` or a ``group_*``
double aggregation — per the Identifier Resolution Algorithm in
ts-from-snowflake-rules.md: the alias and construct indexes, the relationship
key maps, metric-on-metric resolution, :func:`make_resolver`, and the
simple-``AGG(col)`` classifier that resolution and metric translation share.
Names are re-exported from ``sv_translate`` so callers and tests import
unchanged.

Pure functions, no I/O.
"""
from __future__ import annotations

import re
from typing import Callable

from ts_cli.formula_common import UntranslatableError, bare_column_name
from ts_cli.sv_naming import build_node_id_map, construct_formula_id, metric_ref
from ts_cli.sv_sql import translate_sql_expr
from ts_cli.sv_window import _AGG_TO_GROUP

# --- identifier resolution --------------------------------------------------

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
    # An unqualified derived metric owns no entity, so it has no alias_table and
    # cannot be referenced as TABLE.NAME. It belongs in no table-scoped index
    # (BL-213); indexing it would also crash on the None alias.
    scoped = [c for c in constructs if c.get("alias_table")]
    idx: dict[str, dict] = {}
    for c in scoped:
        alias = c["alias_table"].lower()
        idx[f"{alias}.{c['alias_name'].lower()}"] = c
    for c in scoped:
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
    *, promote_synonym: bool = False,
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
        promote_synonym=promote_synonym, _resolving=resolving)
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
    promote_synonym: bool = False,
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
        bare = bare_column_name(expr, dim.get("alias_table"))
        if bare:
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
        return f"[{construct_formula_id(dim, promote_synonym=promote_synonym)}]"

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
                return f"[{construct_formula_id(fact, promote_synonym=promote_synonym)}]"

            # Step 3 — metric-on-metric.
            if metric is not None:
                if key not in _resolving:
                    grouped = _resolve_double_aggregation(
                        metric, default_alias, parsed, alias_map, pair_pk_map,
                        _resolving | {key}, _annotate,
                        promote_synonym=promote_synonym)
                    if grouped is not None:
                        return grouped
                return metric_ref(resolve, construct_formula_id(metric, promote_synonym=promote_synonym))

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

    resolve.metric_refs = set()  # metric refs handed out (sv_naming.metric_ref)
    return resolve



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
