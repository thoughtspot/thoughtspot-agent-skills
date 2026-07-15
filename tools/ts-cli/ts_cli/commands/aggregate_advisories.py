"""Advisory surfacing helpers for `ts aggregate recommend` — pure, no I/O.

Split out of commands/aggregate.py to stay under the file-size gate (mirrors
aggregate_rls.py). Each returns a list of `{measure, reason, remedy}` dicts the
recommend command folds into candidates.json + stdout so the skill can gate on
them: `routing_ineligible_measures` (plain measure columns that will not route
until promoted to formulas, F9) and `semiadditive_measures` (last_value/
first_value period-end snapshots the advisor does not auto-generate, F5).
"""

def routing_ineligible_measures(model_tml: dict, candidates: list) -> list:
    """F9: measures targeted by candidates that are plain measure columns and so
    will NOT be routed to until promoted to formula measures.

    Aggregate-aware routing on this product fires only for FORMULA measures
    (open-item #0); a plain measure column (`kind == 'raw_measure'`) yields an
    aggregate nothing ever routes to. Reuses `spotql_ops.classify_model_columns`
    (the same classifier `ts spotql classify-columns` exposes) so the skill can
    surface the gap and offer the promotion (plain measure -> `sum([physical])`)
    before generating anything."""
    from ts_cli.spotql_ops import classify_model_columns
    kinds = {c["name"]: c.get("kind") for c in classify_model_columns(model_tml)}
    targeted = {m for c in candidates for m in c.get("measure_columns", []) or []}
    out = []
    for name in sorted(targeted):
        if kinds.get(name) == "raw_measure":
            out.append({
                "measure": name,
                "reason": "plain measure column — aggregate-aware routing fires "
                          "only for formula measures",
                "remedy": f"promote '{name}' to a formula measure "
                          f"(e.g. sum([<physical column>])) on the primary Model "
                          f"before generating aggregates",
            })
    return out


def semiadditive_measures(plans: dict) -> list:
    """Measures classified SEMIADDITIVE (a `last_value`/`first_value` period-end
    snapshot — e.g. an inventory or account balance).

    The advisor deliberately does NOT auto-generate an aggregate for these: a
    correct period-end snapshot needs a windowed `last_value OVER (PARTITION BY
    grain ORDER BY date)` DDL that the flat/positional generators can't emit,
    and flat-summing it would produce wrong numbers. `recommend` surfaces them
    (they are otherwise silently excluded from candidates) with a pointer to the
    hand-build recipe."""
    out = []
    for name, plan in sorted(plans.items()):
        if plan.get("class") == "SEMIADDITIVE":
            out.append({
                "measure": name,
                "reason": "semi-additive (period-end snapshot) — auto-generation "
                          "unsupported; needs a windowed last_value aggregate",
                "remedy": "hand-build a period-end snapshot aggregate — see the "
                          "ts-object-model-aggregates semi-additive recipe",
            })
    return out


_DATE_DTYPES = {"DATE", "DATE_TIME", "DATETIME", "TIMESTAMP", "TIME"}


def _physical_attribute_dims(model_tml: dict, table_tmls: dict) -> set:
    """Physical (column_id-backed) non-date ATTRIBUTE columns — the dims safe to
    consolidate into a combined-grain candidate (F3, `lattice._consolidated_dimsets`).

    Excludes MEASURE columns and formula-backed columns (a `formula_id` with no
    `column_id` — e.g. a `concat(...)` employee-name dimension that can't be
    stored/joined in an aggregate table). Date columns are excluded too, but the
    type must be read from the TABLE TML: Model attribute columns frequently
    carry no `data_type` (so a role-playing date like "Order Date" reads as a
    plain attribute at the Model level and would otherwise be consolidated as a
    raw-date dim, exploding the grain). Resolve each column's physical type via
    its `column_id` (TABLE::COL) against `table_tmls` and drop the date ones."""
    out = set()
    for c in model_tml.get("model", {}).get("columns", []) or []:
        props = c.get("properties", {}) or {}
        cid = c.get("column_id")
        if props.get("column_type") == "MEASURE" or not cid or "::" not in cid:
            continue
        tbl, col = cid.split("::", 1)
        tdoc = (table_tmls.get(tbl) or {}).get("table", {})
        dtype = next(((tc.get("db_column_properties") or {}).get("data_type", "")
                      for tc in tdoc.get("columns", []) or []
                      if col in (tc.get("name"), tc.get("db_column_name"))), "")
        if (dtype or "").upper() in _DATE_DTYPES:
            continue
        out.add(c["name"])
    return out

