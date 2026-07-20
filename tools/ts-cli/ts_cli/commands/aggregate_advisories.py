"""Advisory surfacing helpers for `ts aggregate recommend` — pure, no I/O.

Split out of commands/aggregate.py to stay under the file-size gate (mirrors
aggregate_rls.py). Each returns a list of `{measure, reason, remedy}` dicts the
recommend command folds into candidates.json + stdout so the skill can gate on
them: `routing_ineligible_measures` (plain measure columns that will not route
until promoted to formulas, F9) and `semiadditive_measures` (last_value/
first_value period-end snapshots the advisor does not auto-generate, F5).
"""

import re


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
_DATE_JOIN_RE = re.compile(r"\[([^\]:]+::[^\]]+)\]\s*=\s*\[([^\]:]+::[^\]]+)\]")


def _colid_dtype(cid: str, table_tmls: dict) -> str:
    """Physical data_type (upper) for a `TABLE::COL` column_id, via the Table TML."""
    if "::" not in cid:
        return ""
    tbl, col = cid.split("::", 1)
    tdoc = (table_tmls.get(tbl) or {}).get("table", {})
    for tc in tdoc.get("columns", []) or []:
        if col in (tc.get("name"), tc.get("db_column_name")):
            return ((tc.get("db_column_properties") or {}).get("data_type") or "").upper()
    return ""


def _join_on_conditions(model_tml: dict, table_tmls: dict) -> list:
    """Every join `on` string — inline `model_tables[].joins` and table
    `joins_with` (both carry the same `[T::col] = [T::col]` shape)."""
    m = model_tml.get("model", {})
    ons = [j["on"] for t in m.get("model_tables", []) or []
           for j in t.get("joins", []) or [] if j.get("on")]
    ons += [jw["on"] for tdoc in table_tmls.values()
            for jw in (tdoc.get("table", {}) or {}).get("joins_with", []) or [] if jw.get("on")]
    return ons


def _date_join_graph(model_tml: dict, table_tmls: dict) -> dict:
    """Undirected adjacency of date column_ids that join to one another."""
    graph: dict = {}
    for on in _join_on_conditions(model_tml, table_tmls):
        for a, b in _DATE_JOIN_RE.findall(on):
            if (_colid_dtype(a, table_tmls) in _DATE_DTYPES
                    and _colid_dtype(b, table_tmls) in _DATE_DTYPES):
                graph.setdefault(a, set()).add(b)
                graph.setdefault(b, set()).add(a)
    return graph


def conformed_dates(model_tml: dict, table_tmls: dict) -> list:
    """Role-playing / conformed date columns (F12): a date column that MULTIPLE
    other date columns join to (a shared date-dimension column, e.g.
    "Transaction Date" that both "Order Date" and "Balance Date" conform to).

    Surfaced by `recommend` so the user keys a date-bucketed / snapshot aggregate
    on the CONFORMED date — one aggregate then serves queries phrased via any of
    the role-playing dates, and (per column-name routing) a combined multi-fact
    monthly grain can route. Reports each date column that is the hub of >= 2
    role-playing dates and is itself a Model column."""
    id2name = {c["column_id"]: c["name"]
               for c in model_tml.get("model", {}).get("columns", []) or []
               if c.get("column_id")}
    out = []
    for cid, roles in _date_join_graph(model_tml, table_tmls).items():
        if len(roles) >= 2 and cid in id2name:
            out.append({
                "conformed": id2name[cid],
                "role_playing": sorted(id2name[r] for r in roles if r in id2name),
                "note": "date columns conform to one shared date dimension — key a "
                        "date-bucketed/snapshot aggregate on the conformed date so it "
                        "serves queries via any role-playing date and can route.",
            })
    return out


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

