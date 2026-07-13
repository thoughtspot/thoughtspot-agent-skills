"""Build a SpotQL SELECT for an aggregate candidate's grain, and wrap
ThoughtSpot's compiled warehouse SQL as aggregate-table DDL (pure, no I/O).

Task 18 pivoted aggregate DDL generation away from the hand-rolled join
walker in sqlgen.py, which resolves joins itself and gets role-playing /
ambiguous-path dimensions wrong (live-proven: it grouped revenue by
inventory-balance month instead of order month — silently wrong aggregates).
ThoughtSpot's own SQL generation for the same grain is correct because it has
the full semantic model. `build_spotql` constructs the SpotQL statement for a
candidate's grain; the I/O layer (`commands/aggregate.py`) sends it to
`ts spotql generate-sql` against the primary Model (reusing
`ts_cli.commands.spotql`'s client path — never reimplemented here);
`wrap_as_ddl` turns the returned `executable_sql` into aggregate-table DDL.
`sqlgen.build_select` remains as a fallback for when SpotQL generation is
unavailable or errors — see `commands/aggregate.py`.

Task 19 (this module's current shape) corrects two invalid-SpotQL bugs Task
18 shipped, both proven on a live aggregate-aware cluster (2026-07-14):

1. **Measures are referenced by the primary measure's display name, never a
   real aggregate function over a physical column/component name.**
   `SUM("t1"."DM_ORDER_DETAIL::LINE_TOTAL")` -> `QUERY_GEN_ERROR`. SpotQL is a
   semantic-layer language over display names, not physical column
   references — a measure column/formula already carries its own aggregation
   in the model, so selecting it bare (`"t1"."Line Total"`) at the candidate's
   grain yields the correctly-aggregated value; wrapping it in another
   aggregate function is both invalid syntax and (were it valid) would
   double-aggregate. This only has an unambiguous single-expression form for a
   measure whose rewrite plan stores exactly ONE component (direct SUM/MIN/
   MAX/COUNT) — see `_measure_rows`/`UnsupportedMeasureError` for AVG/RATIO.
2. **Dates are selected as the RAW column by display name — no bucket
   function.** `start_of_month("t1"."Order Date")` -> `QUERY_GEN_ERROR`.
   SpotQL has no date-truncation/bucketing UDF at all (confirmed live, not
   just per the forbidden-DATE_TRUNC docs cited below). Bucketing now happens
   entirely in `wrap_as_ddl`'s outer aggregating SELECT, via a per-dialect
   DATE_TRUNC over the compiled `ca_N` column (reusing `sqlgen._date_trunc`).

`build_spotql` returns a structured column-descriptor list (not just a plain
alias list) in SELECT order, so `wrap_as_ddl` knows each output column's role:

    {"alias": str, "kind": "dim" | "date" | "measure",
     "bucket": str | None, "reagg": str | None}

`wrap_as_ddl` maps ThoughtSpot's positional `ca_N` columns onto these
descriptors. When any date descriptor carries a bucket, it emits an outer
*aggregating* SELECT — `DATE_TRUNC(bucket, ca_N)` for that date, `reagg(ca_N)`
for each measure, GROUP BY dims + the DATE_TRUNC expressions — because
`build_spotql`'s own GROUP BY is only ever at the RAW date grain (SpotQL
cannot bucket), so a coarser target grain needs this second aggregation pass.
This exact shape was proven live end-to-end: raw-date SpotQL (measure by
name) -> join-correct detail SQL -> `CREATE TABLE AS SELECT dims,
DATE_TRUNC('MONTH', ca_date), SUM(ca_measure) FROM (spotql_sql) src GROUP BY
dims, DATE_TRUNC(...)` -> a 192-row monthly aggregate whose total equalled
the ungrouped detail total exactly (594,188,083.19). When no date descriptor
has a bucket, `wrap_as_ddl` still does the old pass-through positional
rename — SpotQL's own GROUP BY already lands on the final target grain, so no
second aggregation is needed.

Scope: this only handles measures whose rewrite plan decomposes to exactly
one stored component — direct SUM/MIN/MAX/COUNT. AVG/RATIO plans store TWO
components (numerator/denominator), and SpotQL has no way to select a
formula's separate components by name (only the whole formula, which yields
the ratio, not the parts) — `_measure_rows` raises `UnsupportedMeasureError`
for these rather than emit a guess at invalid SpotQL; see that class's
docstring. `agents/cli/ts-object-model-aggregates/references/open-items.md`
#14 tracks AVG/RATIO SpotQL-component expressibility as an explicit follow-up.

Bucket values (`HOURLY`/`DAILY`/`WEEKLY`/`MONTHLY`/`QUARTERLY`/`YEARLY`) are
carried through unchanged from the candidate's date grain — they're never
turned into a SpotQL expression here; `wrap_as_ddl` is the only place they
become a DATE_TRUNC call, via `sqlgen._date_trunc`'s per-dialect mapping.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from ts_cli.aggregate.sqlgen import _date_trunc, build_ddl

_ALIAS = "t1"


class UnsupportedMeasureError(Exception):
    """A candidate references a measure whose rewrite plan stores more than
    one component (AVG/RATIO — numerator + denominator). SpotQL references a
    semantic measure/formula by its display name only: selecting the whole
    formula by name yields the ratio, not the separate components a
    decomposable aggregate table needs stored individually, and there is no
    SpotQL syntax to reach into a formula and select just its numerator or
    denominator. Rather than emit a guess that `ts spotql generate-sql` would
    reject (or, worse, one that happens to parse but computes the wrong
    thing), `build_spotql` raises this so the candidate falls back to
    `sqlgen.build_select` (see `commands/aggregate.py`'s `_spotql_ddl_or_none`
    / `_spotql_profile_sql_or_none`, which already catch any exception from
    `build_spotql` and fall back with a logged note) — a deliberate, expected
    skip for this measure class, not a bug."""


# A select-row: expr, an alias to render (`AS alias_sql`) or None, the output
# alias for the returned descriptor, whether it's a GROUP BY term, its
# descriptor kind, and (kind-dependent) its bucket/reagg.
class _Row:
    __slots__ = ("expr", "alias_sql", "alias", "group", "kind", "bucket", "reagg")

    def __init__(self, expr, alias_sql, alias, group, kind, bucket=None, reagg=None):
        self.expr = expr
        self.alias_sql = alias_sql
        self.alias = alias
        self.group = group
        self.kind = kind
        self.bucket = bucket
        self.reagg = reagg


def _sq(ident: str) -> str:
    """Quote a SpotQL identifier. SpotQL identifiers are always double-quoted
    regardless of the target warehouse dialect — this is SpotQL syntax, not
    warehouse SQL; the warehouse dialect only matters once ThoughtSpot
    compiles this statement (see `wrap_as_ddl`, which quotes per-dialect)."""
    return '"' + ident.replace('"', '""') + '"'


def _col(name: str) -> str:
    return f"{_sq(_ALIAS)}.{_sq(name)}"


def _cand_date_grains(candidate: dict) -> list:
    """Candidate's date grains, with the single-date `date_column`/`bucket`
    shim fallback. Deliberately duplicated (not imported) to keep this
    module self-contained — the same convention sqlgen.py/lattice.py/
    generate.py each follow for their own copy of this helper."""
    grains = candidate.get("date_grains")
    if grains is not None:
        return grains
    col = candidate.get("date_column")
    return [{"column": col, "bucket": candidate.get("bucket")}] if col else []


def _dim_rows(candidate: dict) -> List[_Row]:
    return [_Row(_col(d), None, d, True, "dim")
            for d in candidate.get("dimensions", []) or []]


def _date_rows(candidate: dict) -> List[_Row]:
    """Raw date column, by display name, unaliased (spotql-rules.md: never
    alias a plain Model column) — no bucket function. SpotQL has no
    date-truncation UDF (module docstring); bucketing + re-aggregation is
    entirely `wrap_as_ddl`'s job, driven by the `bucket` carried on the
    returned descriptor."""
    rows: List[_Row] = []
    for g in _cand_date_grains(candidate):
        col_name = g["column"]
        rows.append(_Row(_col(col_name), None, col_name, True, "date",
                         bucket=g.get("bucket")))
    return rows


def _measure_rows(candidate: dict, plans: dict) -> List[_Row]:
    """One select item per decomposable measure, referencing the measure's
    OWN display name (`plan["name"]`) — never a physical column wrapped in a
    real aggregate function (module docstring: that shape is invalid SpotQL
    and would double-aggregate anyway; the model already carries the
    measure's aggregation).

    Only valid for a plan with exactly one stored component (direct SUM/MIN/
    MAX/COUNT): selecting the measure by name yields that single component's
    value unambiguously, aliased as the component's own alias so ca_N <->
    output descriptor <-> table-spec column stay 1:1 with
    generate.build_aggregate_table_spec/_component_columns. A plan with two
    components (AVG/RATIO) has no such unambiguous single-name reference —
    see `UnsupportedMeasureError`.

    Iterates `measure_columns` in the same order generate._component_columns
    does, so a candidate that reaches SpotQL generation keeps the same
    output-column order the aggregate Table spec declares."""
    rows: List[_Row] = []
    for m in candidate.get("measure_columns", []) or []:
        plan = plans.get(m)
        if not plan or not plan.get("decomposable"):
            continue
        components = plan["components"]
        if len(components) != 1:
            raise UnsupportedMeasureError(
                f"measure '{m}' ({plan['class']}) decomposes into "
                f"{len(components)} stored components — SpotQL can only "
                "reference a semantic measure/formula by its whole display "
                "name, which yields the ratio, not the separate numerator/"
                "denominator an aggregate table needs stored individually. "
                "Scoped out of the SpotQL path (falls back to "
                "sqlgen.build_select); see open-items.md #14.")
        comp = components[0]
        rows.append(_Row(_col(plan["name"]), _sq(comp["alias"]), comp["alias"],
                         False, "measure", reagg=comp["reagg"]))
    return rows


def build_spotql(candidate: dict, plans: dict, source_name: str) -> Tuple[str, List[dict]]:
    """SpotQL SELECT over the primary's semantic columns for `candidate`'s
    grain: dimensions (quoted, unaliased), raw date columns (quoted,
    unaliased, no bucket function — see module docstring), and one item per
    decomposable measure covering `candidate["measure_columns"]`, referenced
    by display name and aliased to its stored component's alias.

    Returns `(spotql, descriptors)` — `descriptors` is the ordered list
    (dims, then dates, then measures) of
    `{"alias", "kind", "bucket", "reagg"}` dicts `wrap_as_ddl`
    position-maps against ThoughtSpot's `ca_N` columns.

    Raises `UnsupportedMeasureError` (not caught here — the caller's
    best-effort `build_spotql` -> `generate-sql` -> `wrap_as_ddl` chain in
    `commands/aggregate.py` already catches any exception and falls back to
    `sqlgen.build_select`) if any measure in `candidate["measure_columns"]`
    decomposes to more than one stored component (AVG/RATIO).
    """
    rows = _dim_rows(candidate) + _date_rows(candidate) + _measure_rows(candidate, plans)

    select_items = [f"{r.expr} AS {r.alias_sql}" if r.alias_sql else r.expr for r in rows]
    group_items = [r.expr for r in rows if r.group]
    descriptors = [{"alias": r.alias, "kind": r.kind, "bucket": r.bucket, "reagg": r.reagg}
                   for r in rows]

    lines = ["SELECT", "  " + ",\n  ".join(select_items),
             f"FROM {_sq(source_name)} AS {_sq(_ALIAS)}"]
    if group_items:
        lines.append("GROUP BY " + ", ".join(group_items))
    return "\n".join(lines), descriptors


_TRAILING_LIMIT = re.compile(r"\s+LIMIT\s+\d+\s*;?\s*\Z", re.IGNORECASE)


def _strip_trailing_limit(sql: str) -> str:
    return _TRAILING_LIMIT.sub("", sql.rstrip())


# Dialect quoting for the wrapper's OUTER select list (the aggregate table's
# real physical column names) — deliberately duplicated from sqlgen._q
# rather than imported, matching this package's established
# self-contained-module convention (see e.g. the _cand_date_grains shim
# independently copied into sqlgen.py/lattice.py/generate.py).
_QUOTE = {"snowflake": '"', "databricks": "`", "bigquery": "`"}
_QUOTE_ESCAPE = {"snowflake": '""', "databricks": "``", "bigquery": "\\`"}


def _dq(dialect: str, ident: str) -> str:
    q = _QUOTE[dialect]
    return f"{q}{ident.replace(q, _QUOTE_ESCAPE[dialect])}{q}"


def _select_and_group_items(descriptors: List[dict], dialect: str,
                            bucketed: bool) -> Tuple[List[str], List[str]]:
    """Per-descriptor outer SELECT item + (when `bucketed`) its GROUP BY term.

    `bucketed=False`: pure positional rename, `ca_N AS alias` for every
    descriptor, no GROUP BY term ever — `build_spotql`'s own GROUP BY already
    landed on the final target grain (today's pass-through wrapper shape).

    `bucketed=True`: at least one date descriptor carries a bucket, so
    `build_spotql`'s GROUP BY was only ever at the raw date grain — this
    emits the second, coarser-grain aggregation pass: `DATE_TRUNC(bucket,
    ca_N)` for a bucketed date (also a GROUP BY term), `reagg(ca_N)` for a
    measure (never a GROUP BY term), and a bare positional rename + GROUP BY
    term for everything else (dims, and any date grain without its own
    bucket — a multi-date candidate can mix bucketed and raw grains)."""
    select_items, group_items = [], []
    for i, d in enumerate(descriptors):
        ca = _dq(dialect, f"ca_{i + 1}")
        alias = _dq(dialect, d["alias"])
        if not bucketed:
            select_items.append(f"{ca} AS {alias}")
            continue
        if d["kind"] == "measure":
            select_items.append(f"{d['reagg']}({ca}) AS {alias}")
        elif d["kind"] == "date" and d.get("bucket"):
            expr = _date_trunc(dialect, d["bucket"], ca)
            select_items.append(f"{expr} AS {alias}")
            group_items.append(expr)
        else:
            select_items.append(f"{ca} AS {alias}")
            group_items.append(ca)
    return select_items, group_items


def wrap_as_ddl(ts_executable_sql: str, descriptors: List[dict], target: str,
                dialect: str, materialization: str = "auto",
                target_lag: Optional[str] = "1 hour",
                warehouse: Optional[str] = None) -> str:
    """Wrap ThoughtSpot's compiled `ts_executable_sql` — positional `ca_1`,
    `ca_2`, ... columns in `build_spotql`'s SELECT order, plus a trailing
    `LIMIT` — as aggregate-table DDL.

    Strips the trailing LIMIT, then maps `ca_N` -> `descriptors[N-1]` by
    position. If any descriptor carries a `bucket`, emits an outer
    AGGREGATING select (DATE_TRUNC + reagg + GROUP BY — see
    `_select_and_group_items`); otherwise the plain positional-rename
    pass-through (today's shape, no GROUP BY — `build_spotql`'s own GROUP BY
    already lands on the target grain). References the inner derived columns
    as QUOTED `ca_N`: ThoughtSpot emits them quoted-lowercase
    (`"ta_1"."X" "ca_1"`), which is case-sensitive on the warehouse — an
    unquoted `ca_1` folds to `CA_1` on Snowflake and fails to bind ("invalid
    identifier") at execution.

    Reuses `sqlgen.build_ddl` for the materialization shape (dynamic table /
    mview / ctas per dialect), including the Snowflake
    materialized-view-can't-join guard and the warehouse rule, and
    `sqlgen._date_trunc` for the per-dialect DATE_TRUNC mapping.
    """
    inner = _strip_trailing_limit(ts_executable_sql)
    bucketed = any(d.get("bucket") for d in descriptors)
    select_items, group_items = _select_and_group_items(descriptors, dialect, bucketed)

    lines = ["SELECT " + ",\n       ".join(select_items),
             f"FROM (\n{inner}\n) {_dq(dialect, 'src')}"]
    if group_items:
        lines.append("GROUP BY " + ", ".join(group_items))
    wrapper_select = "\n".join(lines)

    return build_ddl(wrapper_select, target, dialect,
                     materialization=materialization,
                     target_lag=target_lag or "1 hour",
                     warehouse=warehouse)
