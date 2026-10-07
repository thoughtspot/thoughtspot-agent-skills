"""Parsed Semantic View -> translated ThoughtSpot formulas
(`ts snowflake translate-formulas`).

Pure functions: parse-sv dict in, JSON-ready dict out. No I/O, no network
calls — trivially unit-testable.

Mapping rules: agents/shared/mappings/ts-snowflake/
ts-snowflake-formula-translation.md and ts-from-snowflake-rules.md.

This module is the orchestrator and the per-block (dimension / fact / metric)
translators. Identifier resolution lives in ``sv_resolve``, OVER-window and
semi-additive handling in ``sv_window``, construct naming in ``sv_naming``;
their names are re-exported here so existing imports keep working.
"""
from __future__ import annotations

from typing import Any

from ts_cli.formula_common import (
    UntranslatableError, bare_column_name, week_start_note)
from ts_cli.sv_naming import (  # noqa: F401  (re-exported for callers/tests)
    build_node_id_map,
    construct_formula_id,
    display_title,
    fact_aggregation,
    fact_column_type,
    metric_ref,
)
from ts_cli.sv_resolve import (
    _build_alias_map,
    _build_column_index,
    _build_relationship_pk_map,
    _is_simple_agg,
    _try_simple_agg_column,
    make_resolver,
)
from ts_cli.sv_sql import translate_sql_expr
from ts_cli.sv_window import (
    _AGG_TO_GROUP,
    _extract_over_clause,
    _find_over_split,
    _parse_window_spec,
    _translate_window,
    _unwrap_agg,
    _wrap_semi_additive,
)


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
        "annotations": _with_week_note(annotations or [], ts_expr),
    }


def _with_week_note(annotations: list[str], ts_expr: str | None) -> list[str]:
    """``annotations`` plus the shared Monday-week-start advisory when ``ts_expr``
    calls a week-dependent function (BL-334 item 2) — a review flag, not a skip."""
    note = week_start_note(ts_expr)
    if note and note not in annotations:
        annotations = [*annotations, note]
    return annotations


# --- per-block translators ---------------------------------------------------


def _translate_dimension(
    dim: dict, parsed: dict, alias_map: dict[str, str],
    *, promote_synonym: bool = False,
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
    bare = bare_column_name(expr, dim.get("alias_table"))
    if bare:
        return _entry(
            dim["source_column"], "dimension", "column", "ATTRIBUTE", dim,
            table=table, column=bare)
    annotations: list[str] = []
    resolver = make_resolver(
        parsed, dim["alias_table"], annotations=annotations,
        promote_synonym=promote_synonym)
    ts_expr = translate_sql_expr(dim["expr"], resolver)
    return _entry(
        dim["source_column"], "dimension", "formula", "ATTRIBUTE", dim,
        ts_expr=ts_expr, annotations=annotations)


# Functions whose result is a string, date or boolean — a fact built from one of
# these is not summable, whatever block it was declared in.
def _translate_fact(
    fact: dict, parsed: dict, alias_map: dict[str, str],
    *, promote_synonym: bool = False,
) -> dict[str, Any]:
    """Translate one fact entry. Facts are row-level values from the SV's
    ``facts()`` block, classified MEASURE or ATTRIBUTE by
    :func:`fact_column_type` (BL-181)."""
    col_type = fact_column_type(fact)
    agg, annotations = fact_aggregation(fact, col_type, parsed)
    if fact["expr"] is None:
        table = alias_map.get(fact["alias_table"].lower(), fact["source_table"])
        return _entry(
            fact["source_column"], "fact", "column", col_type, fact,
            table=table, column=fact["alias_name"], aggregation=agg,
            annotations=annotations)
    resolver = make_resolver(
        parsed, fact["alias_table"], annotations=annotations,
        promote_synonym=promote_synonym)
    ts_expr = translate_sql_expr(fact["expr"], resolver)
    return _entry(
        fact["source_column"], "fact", "formula", col_type, fact,
        ts_expr=ts_expr, aggregation=agg, annotations=annotations)


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


def _derived_resolver(
    parsed: dict, annotations: list[str], *, promote_synonym: bool = False,
):
    """Resolver for an unqualified derived metric's expression.

    A derived metric combines metrics that have each already aggregated on their
    own entity, so a reference must point at whatever that metric is EMITTED as,
    not at a double aggregation:

    * a simple ``AGG(col)`` metric becomes a plain ``columns[]`` entry with an
      aggregation, so there is no formula id to point at AND a display-name
      reference is rejected by ThoughtSpot's formula parser — its own aggregate
      is inlined instead: ``sum ( [DM_ORDER_DETAIL::LINE_TOTAL] )``;
    * anything else becomes a formula, so the reference is the minted id —
      ``[formula_Avg Order Value]``.

    The generic resolver always emits ``[formula_<id>]`` for a metric (step 3),
    which dangles against a simple-agg metric because no such formula exists —
    the BL-178 failure shape that ``ts tml lint`` I13 now rejects. That path was
    previously unreachable for unrelated entities because Snowflake refuses a
    qualified metric that references one (010211); a derived metric is the first
    construct that can reach it, so it needs its own mapping (BL-213).
    """
    _, metric_idx = _build_column_index(parsed)
    generic = make_resolver(
        parsed, "", annotations=annotations, promote_synonym=promote_synonym)

    def resolve(ident: str) -> str:
        m = metric_idx.get(ident.lower())
        if m is not None:
            if _is_simple_agg(m.get("expr")) is not None:
                # A simple AGG(col) metric is emitted as a plain columns[] entry
                # carrying an aggregation, NOT a formula — so there is no id to
                # reference, and a ThoughtSpot formula cannot reference another
                # column by DISPLAY NAME either (`[Amount]` is rejected:
                # "Search did not find ... Expecting one of the valid keywords").
                # Inline the metric's own aggregate over the physical column,
                # which is the form every working formula in a converted Model
                # uses: `sum ( [DM_ORDER_DETAIL::LINE_TOTAL] )`.
                # Against the INNER metric's own table: under `generic`
                # (alias "") a bare column silently skips the metric (17.1).
                inner = make_resolver(parsed, m.get("alias_table") or "",
                    annotations=annotations, promote_synonym=promote_synonym)
                return translate_sql_expr(m["expr"], inner)
            return metric_ref(resolve, construct_formula_id(m, promote_synonym=promote_synonym))
        return generic(ident)

    resolve.metric_refs = generic.metric_refs  # one shared set (BL-331)
    return resolve


def _translate_metric(
    metric: dict,
    parsed: dict,
    alias_map: dict[str, str],
    rel_pk_map: dict[str, tuple[str, str]],
    *, promote_synonym: bool = False,
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

    if metric.get("is_derived"):
        # An unqualified derived metric owns no entity: it is purely a function
        # of other metrics, each of which aggregates on its own table. That is
        # what lets it span two UNRELATED facts, and it maps directly onto a
        # ThoughtSpot formula over the referenced measures. Every reference in
        # one is table-qualified, so the resolver's default alias is never
        # consulted (BL-213).
        if expr is None:
            raise UntranslatableError(
                f"derived metric '{metric['source_column']}' has no expression")
        resolver = _derived_resolver(
            parsed, annotations, promote_synonym=promote_synonym)
        ts_expr = translate_sql_expr(expr, resolver)
        return _entry(
            metric["source_column"], "metric", "formula", "MEASURE",
            metric, ts_expr=ts_expr, annotations=annotations)

    if expr is None:
        raise UntranslatableError(
            f"metric '{metric['source_column']}' has no aggregate expression "
            f"(right-hand side is the bare column "
            f"'{metric['alias_table']}.{metric['alias_name']}') — declare it in "
            f"dimensions() or facts(), or give the metric an aggregation")
    resolver = make_resolver(
        parsed, metric["alias_table"], annotations=annotations,
        promote_synonym=promote_synonym)
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

def translate_sv_formulas(
    parsed: dict, *, promote_synonym: bool = False,
) -> dict[str, Any]:
    """Translate all formulas from a parsed Semantic View into ThoughtSpot syntax.

    Returns {translated, skipped, stats, options}. ``options`` records the
    naming decision so ``build-model`` reads it rather than being told a second
    time — two independent naming paths is precisely what BL-178 defect 2 was.
    """
    alias_map = _build_alias_map(parsed)
    rel_pk_map = _build_relationship_pk_map(parsed)

    translated: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    for dim in parsed.get("dimensions", []):
        try:
            translated.append(_translate_dimension(
                dim, parsed, alias_map, promote_synonym=promote_synonym))
        except UntranslatableError as e:
            skipped.append({
                "name": dim["source_column"],
                "block": "dimensions",
                "reason": str(e),
            })

    for fact in parsed.get("facts", []):
        try:
            translated.append(_translate_fact(
                fact, parsed, alias_map, promote_synonym=promote_synonym))
        except UntranslatableError as e:
            skipped.append({
                "name": fact["source_column"],
                "block": "facts",
                "reason": str(e),
            })

    for metric in parsed.get("metrics", []):
        try:
            translated.append(_translate_metric(
                metric, parsed, alias_map, rel_pk_map,
                promote_synonym=promote_synonym))
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
        "options": {"promote_first_synonym": promote_synonym},
        "stats": {
            "total": total,
            "translated": len(translated),
            "skipped": len(skipped),
        },
    }
