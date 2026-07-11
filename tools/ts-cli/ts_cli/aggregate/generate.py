"""Aggregate Table/Model TML + aggregated_models association patch (pure, no I/O).

The aggregated_models emission shape follows the 26.6 docs example and is
unverified on a live cluster — skill Open Item #2. Ordering is most-aggregated-
first (spec: correct under first-match routing, harmless under auto-pick).

Reuse, not reimplementation: this module deliberately does NOT hand-assemble
TML dicts that ts_cli.commands.tables._build_table_tml and
ts_cli.model_builder.build_model_tml already build (data-type normalization,
db_column_name wiring, formula_ prefixing, double-aggregation collapse,
formula_id wiring). See build_aggregate_model_tml's docstring for the one
place this module had to reconcile its input shape against what those
functions actually consume (Step 3b of the task-6 brief).
"""
from __future__ import annotations

import copy


def _sql_type(display_name: str, model_tml: dict, default: str = "DOUBLE") -> str:
    for c in model_tml["model"].get("columns", []) or []:
        if c["name"] == display_name:
            return c.get("data_type", default)
    return default


def _grain_columns(candidate: dict, model_tml: dict):
    """(name, data_type, column_type) for dims + date column of the grain."""
    out = [(d, _sql_type(d, model_tml, "VARCHAR"), "ATTRIBUTE")
           for d in candidate["dimensions"]]
    if candidate.get("date_column"):
        out.append((candidate["date_column"], "DATE", "ATTRIBUTE"))
    return out


def _component_columns(candidate: dict, plans: dict):
    """(alias, plan, comp) for every stored component of decomposable measures."""
    out = []
    for m in candidate.get("measure_columns", []):
        plan = plans.get(m)
        if plan and plan["decomposable"]:
            for comp in plan["components"]:
                out.append((comp["alias"], plan, comp))
    return out


def build_aggregate_table_spec(candidate: dict, plans: dict, model_tml: dict,
                               db: str, schema: str, table_name: str,
                               connection_name: str) -> dict:
    """Spec dict for ts_cli.commands.tables._build_table_tml / `ts tables create`.

    Grain columns (dimensions + date) are ATTRIBUTE; each stored component of a
    decomposable measure is a MEASURE column carrying its `reagg` aggregation
    (the aggregation that correctly re-combines partial results across the
    grain — e.g. SUM over a pre-summed column, SUM over a pre-counted column
    for COUNT/AVG components). Keys match `_build_table_tml`'s spec contract
    exactly: name/data_type/column_type/aggregation.
    """
    columns = []
    for name, dtype, _ in _grain_columns(candidate, model_tml):
        columns.append({"name": name, "data_type": dtype,
                        "column_type": "ATTRIBUTE"})
    for alias, _plan, comp in _component_columns(candidate, plans):
        dtype = "INT64" if comp["func"] == "COUNT" else "DOUBLE"
        columns.append({"name": alias, "data_type": dtype,
                        "column_type": "MEASURE", "aggregation": comp["reagg"]})
    return {"name": table_name, "db": db, "schema": schema,
            "db_table": table_name, "connection_name": connection_name,
            "columns": columns}


def build_aggregate_model_tml(candidate: dict, plans: dict, model_tml: dict,
                              agg_table_name: str, model_name: str,
                              connection_name: str) -> dict:
    """Adapter over model_builder.build_model_tml + aggregate-specific post-pass.

    Reuses the conversion substrate's assembly (formula_ prefixing, double-agg
    fix, formula_id wiring) rather than hand-building the model dict.

    Step 3b reconciliation (read _build_model_tables / _build_model_columns in
    ts_cli/model_builder.py before touching this): the task-6 brief's illustrative
    column dict used a `db_column` key. The real functions need `db_column_name`:
    `_build_model_tables` does `c["db_column_name"]` with NO default (KeyError
    without it), and `_build_model_columns` does
    `c.get("db_column_name", c["name"])`. `column_type` must be a flat key on
    each column dict (not nested under `properties`) — that's what
    `_build_model_columns` reads. Both functions turned out adaptable (not
    "too Tableau-shaped"), so this stays an adapter, not hand-assembly.

    Known reuse limitation (not exercised by this task's SUM/AVG fixtures):
    `_build_model_columns` hardcodes `aggregation: SUM` for every MEASURE
    column regardless of any per-column aggregation passed in. A MIN/MAX
    single-component measure's aggregate-model column would therefore read
    `aggregation: SUM` in the *model* TML even though its physical column in
    the aggregate *table* (see build_aggregate_table_spec) correctly carries
    MIN/MAX. Fixing this means changing shared model_builder.py, which other
    skills (Tableau conversion) depend on — out of scope here; flagged for a
    follow-up rather than silently worked around.
    """
    from ts_cli.model_builder import build_model_tml

    tables = [{"name": agg_table_name, "db_table": agg_table_name}]
    columns, translated_formulas = [], []
    hidden_aliases = set()
    for name, dtype, _ in _grain_columns(candidate, model_tml):
        columns.append({"name": name, "table": agg_table_name,
                        "db_column_name": name, "data_type": dtype,
                        "column_type": "ATTRIBUTE"})
    emitted_formula = set()
    for alias, plan, comp in _component_columns(candidate, plans):
        if plan["model_expr"] is None:
            # Single direct-additive component (SUM/MIN/MAX primary measure):
            # expose it under the primary's own display name — no formula needed.
            columns.append({"name": plan["name"], "table": agg_table_name,
                            "db_column_name": alias, "data_type": "DOUBLE",
                            "column_type": "MEASURE", "aggregation": comp["reagg"]})
            continue
        # Stored component of a decomposed measure (AVG/COUNT/RATIO): hidden,
        # recombined via the formula below.
        columns.append({"name": alias, "table": agg_table_name,
                        "db_column_name": alias, "data_type": "DOUBLE",
                        "column_type": "MEASURE", "aggregation": comp["reagg"]})
        hidden_aliases.add(alias)
        if plan["name"] not in emitted_formula:
            emitted_formula.add(plan["name"])
            translated_formulas.append({"name": plan["name"],
                                        "expr": plan["model_expr"]})

    tml = build_model_tml(model_name=model_name,
                          connection_name=connection_name,
                          tables=tables, columns=columns, joins=[],
                          parameters=[],
                          translated_formulas=translated_formulas)

    # Aggregate-specific post-pass.
    #
    # is_spotter_enabled lives under properties.spotter_config, never flat
    # under properties — verified against
    # agents/shared/schemas/thoughtspot-model-tml.md (top-level field-reference
    # table: "spotter_config.is_spotter_enabled") and the live precedent in
    # ts_cli/databricks/mv_build_model.py:build_model_tml_dbx
    # (`props["spotter_config"] = {"is_spotter_enabled": ...}`), which
    # ts_cli/audit/checks_perf.py also reads back from that same nested path.
    # A flat `properties.is_spotter_enabled` (as in the task-6 brief's
    # illustrative Step 3 code/test) would be inert TML noise, not an actual
    # Spotter-enable — corrected here and in the test.
    tml["model"].setdefault("properties", {})["spotter_config"] = {
        "is_spotter_enabled": True,
    }
    for c in tml["model"]["columns"]:
        if c["name"] in hidden_aliases:
            c.setdefault("properties", {})["is_hidden"] = True
    return tml


def patch_association(primary_tml: dict, entries: list) -> dict:
    """Set model.aggregated_models, most-aggregated (smallest projected_rows) first.

    entries: [{"id": guid_or_name, "date_column": str|None, "bucket": str|None,
               "projected_rows": int|None}]. Emits {id, optional
    date_aggregation_info: {column_id, bucket}}; projected_rows is an internal
    sort key, stripped before emission.

    This shape is unverified against live TML (skill Open Item #2) —
    implemented per the task-6 brief's spec, including the single-dict
    date_aggregation_info form (the schema doc at
    agents/shared/schemas/thoughtspot-model-tml.md shows a LIST under
    date_aggregation_info; both are plausible until verified live — Open
    Item #2 covers reconciling this).
    """
    patched = copy.deepcopy(primary_tml)
    ordered = sorted(entries, key=lambda e: (e.get("projected_rows") is None,
                                             e.get("projected_rows") or 0))
    block = []
    for e in ordered:
        item = {"id": e["id"]}
        if e.get("date_column") and e.get("bucket"):
            item["date_aggregation_info"] = {"column_id": e["date_column"],
                                             "bucket": e["bucket"]}
        block.append(item)
    patched["model"]["aggregated_models"] = block
    return patched
