from ts_cli.aggregate.generate import (build_aggregate_table_spec,
                                       build_aggregate_model_tml,
                                       date_aggregation_info_to_grains,
                                       patch_association)
from ts_cli.aggregate.measures import classify_measure

PLANS = {"Sales": classify_measure("Sales", aggregation="SUM"),
         "Avg Sale": classify_measure("Avg Sale", expr="average ( [Sales] )")}
CAND = {"id": "cand_1", "dimensions": ["Category"], "date_column": "Order Date",
        "bucket": "MONTHLY", "measure_columns": ["Sales", "Avg Sale"],
        "covered": [0], "flags": []}
MODEL = {"model": {"name": "Sales Model", "columns": [
    {"name": "Category", "column_id": "DIM::CATEGORY",
     "properties": {"column_type": "ATTRIBUTE"}},
    {"name": "Order Date", "column_id": "FACT::ORDER_DT", "data_type": "DATE",
     "properties": {"column_type": "ATTRIBUTE"}},
    {"name": "Sales", "column_id": "FACT::AMOUNT",
     "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
]}}


def test_table_spec_feeds_ts_tables_create():
    spec = build_aggregate_table_spec(CAND, PLANS, MODEL, db="SALESDB",
                                      schema="PUBLIC", table_name="SALES_AGG_MONTH_CATEGORY",
                                      connection_name="SF Prod")
    assert spec["connection_name"] == "SF Prod"
    assert spec["db_table"] == "SALES_AGG_MONTH_CATEGORY"
    names = [c["name"] for c in spec["columns"]]
    assert "Category" in names and "Order Date" in names
    assert "sales_sum" in names and "avg_sale_sum" in names and "avg_sale_cnt" in names
    comp = [c for c in spec["columns"] if c["name"] == "sales_sum"][0]
    assert comp["column_type"] == "MEASURE" and comp["aggregation"] == "SUM"
    # the spec round-trips through the existing table builder (reuse, not reimplementation)
    from ts_cli.commands.tables import _build_table_tml
    tml_yaml = _build_table_tml(spec)
    assert "db_column_name" in tml_yaml and "SF Prod" in tml_yaml


def test_component_types_follow_source_column_types():
    # F8: SUM over an INT column must be INT64, not DOUBLE — else `ts tables
    # create` fails the CDW type check ("DataType DOUBLE does not match ...").
    # Component types are read from the base Table TMLs, not guessed.
    model = {"model": {"name": "M", "columns": [
        {"name": "Category", "column_id": "DIM::CATEGORY",
         "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "Sales", "column_id": "FACT::AMOUNT",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
        {"name": "Units", "column_id": "FACT::QTY",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
    ]}}
    tables = {
        "FACT": {"table": {"columns": [
            {"name": "AMOUNT", "db_column_name": "AMOUNT",
             "db_column_properties": {"data_type": "DOUBLE"}},
            {"name": "QTY", "db_column_name": "QTY",
             "db_column_properties": {"data_type": "INT64"}}]}},
        "DIM": {"table": {"columns": [
            {"name": "CATEGORY", "db_column_name": "CATEGORY",
             "db_column_properties": {"data_type": "VARCHAR"}}]}},
    }
    cand = {"id": "c", "dimensions": ["Category"], "date_column": None,
            "bucket": None, "measure_columns": ["Sales", "Units"],
            "covered": [0], "flags": []}
    plans = {"Sales": classify_measure("Sales", aggregation="SUM"),
             "Units": classify_measure("Units", aggregation="SUM")}
    spec = build_aggregate_table_spec(cand, plans, model, db="D", schema="S",
                                      table_name="T", connection_name="C",
                                      table_tmls=tables)
    by = {c["name"]: c for c in spec["columns"]}
    assert by["units_sum"]["data_type"] == "INT64"   # SUM(int) stays integer
    assert by["sales_sum"]["data_type"] == "DOUBLE"   # SUM(double) stays double


def test_component_type_resolves_from_formula_measure_source():
    # Formula measure (no column_id) — type resolved via the [TABLE::col] ref.
    model = {"model": {"name": "M", "columns": [
        {"name": "Category", "column_id": "DIM::CATEGORY",
         "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "Units", "formula_id": "f_u",
         "properties": {"column_type": "MEASURE"}}],
        "formulas": [{"id": "f_u", "name": "Units", "expr": "sum ( [FACT::QTY] )"}]}}
    tables = {"FACT": {"table": {"columns": [
        {"name": "QTY", "db_column_name": "QTY",
         "db_column_properties": {"data_type": "INT64"}}]}}}
    cand = {"id": "c", "dimensions": ["Category"], "date_column": None,
            "bucket": None, "measure_columns": ["Units"], "covered": [0], "flags": []}
    plans = {"Units": classify_measure("Units", expr="sum ( [FACT::QTY] )")}
    spec = build_aggregate_table_spec(cand, plans, model, db="D", schema="S",
                                      table_name="T", connection_name="C",
                                      table_tmls=tables)
    comp = [c for c in spec["columns"] if c["name"].endswith("_sum")][0]
    assert comp["data_type"] == "INT64"


def test_component_type_falls_back_to_double_without_table_tmls():
    # Backward compat: no table_tmls → SUM/MIN/MAX default to DOUBLE as before.
    spec = build_aggregate_table_spec(CAND, PLANS, MODEL, db="D", schema="S",
                                      table_name="T", connection_name="C")
    assert [c for c in spec["columns"]
            if c["name"] == "sales_sum"][0]["data_type"] == "DOUBLE"


def test_model_tml_names_match_primary_exactly_and_spotter_enabled():
    tml = build_aggregate_model_tml(CAND, PLANS, MODEL,
                                    agg_table_name="SALES_AGG_MONTH_CATEGORY",
                                    model_name="Sales Model (Monthly Agg)",
                                    connection_name="SF Prod")
    m = tml["model"]
    # NOTE: corrected from the task-6 brief's illustrative assertion
    # `m["properties"]["is_spotter_enabled"] is True`. Verified against
    # agents/shared/schemas/thoughtspot-model-tml.md ("aggregated_models" section
    # + top-level field-reference table: "spotter_config.is_spotter_enabled") and
    # the live precedent in ts_cli/databricks/mv_build_model.py
    # (`props["spotter_config"] = {"is_spotter_enabled": ...}`) — the flag lives
    # nested under `properties.spotter_config`, never flat under `properties`.
    # A flat `is_spotter_enabled` would be inert: nothing else in this repo
    # (e.g. audit/checks_perf.py's spotter-enabled check) reads that path.
    assert m["properties"]["spotter_config"]["is_spotter_enabled"] is True
    col_names = [c["name"] for c in m["columns"]]
    assert "Category" in col_names and "Order Date" in col_names
    # Task 17 (routing fix): a live aggregate-aware cluster proved routing
    # fires ONLY for formula measures. "Sales" (a direct SUM) must therefore
    # be a FORMULA-backed column (formula_id, no column_id) — not a plain
    # MEASURE column carrying a column_id — with its stored component hidden.
    sales_col = next(c for c in m["columns"] if c["name"] == "Sales")
    assert "formula_id" in sales_col and "column_id" not in sales_col
    hidden = [c["name"] for c in m["columns"]
              if (c.get("properties") or {}).get("is_hidden")]
    assert "sales_sum" in hidden
    assert "avg_sale_sum" in hidden and "avg_sale_cnt" in hidden
    f_sales = [f for f in m["formulas"] if f["name"] == "Sales"][0]
    assert f_sales["expr"] == "sum ( [sales_sum] )"
    f = [f for f in m["formulas"] if f["name"] == "Avg Sale"][0]
    assert f["expr"] == "sum ( [avg_sale_sum] ) / sum ( [avg_sale_cnt] )"


def test_sum_min_max_formula_survives_dump_and_lint_clean():
    # Task 17 guard: the emitted model TML must round-trip through
    # tml_common.dump_tml_yaml + tml_lint.lint_tml with NO findings, and each
    # formula's expr must stay exactly `<func> ( [<alias>] )` — not get
    # mangled by fix_double_aggregation (which only rewrites sum([formula_X])
    # references, and our stored-component aliases are plain physical
    # columns, never formula names, so they must never match that rewrite).
    import yaml as _yaml

    from ts_cli.tml_common import dump_tml_yaml
    from ts_cli.tml_lint import lint_tml

    plans = {"Sales": classify_measure("Sales", aggregation="SUM"),
             "Peak Price": classify_measure("Peak Price", aggregation="MAX"),
             "Low Price": classify_measure("Low Price", aggregation="MIN"),
             "Avg Sale": classify_measure("Avg Sale", expr="average ( [Sales] )")}
    cand = {"id": "c3", "dimensions": ["Category"], "date_column": "Order Date",
            "bucket": "MONTHLY",
            "measure_columns": ["Sales", "Peak Price", "Low Price", "Avg Sale"],
            "covered": [0], "flags": []}
    tml = build_aggregate_model_tml(cand, plans, MODEL, agg_table_name="AGG_T",
                                    model_name="M (Agg)", connection_name="SF Prod")

    yaml_text = dump_tml_yaml(tml)
    round_tripped = _yaml.safe_load(yaml_text)
    assert lint_tml(round_tripped) == []

    formulas = {f["name"]: f["expr"] for f in round_tripped["model"]["formulas"]}
    assert formulas["Sales"] == "sum ( [sales_sum] )"
    assert formulas["Peak Price"] == "max ( [peak_price_max] )"
    assert formulas["Low Price"] == "min ( [low_price_min] )"
    assert formulas["Avg Sale"] == "sum ( [avg_sale_sum] ) / sum ( [avg_sale_cnt] )"


def test_multi_date_grain_columns_in_table_spec_and_model_tml():
    # Task 15: a candidate with a multi-date date_grains list must yield a
    # grain column for EVERY date, in both the table spec and the model TML
    # (generalized _grain_columns), not just the first/shim date_column.
    plans = {"Sales": classify_measure("Sales", aggregation="SUM")}
    cand = {"id": "cand_2", "dimensions": ["Category"],
            "date_grains": [{"column": "Order Date", "bucket": "MONTHLY"},
                            {"column": "Shipped Date", "bucket": None}],
            "measure_columns": ["Sales"], "covered": [0], "flags": []}
    model = {"model": {"name": "Sales Model", "columns": MODEL["model"]["columns"] + [
        {"name": "Shipped Date", "column_id": "FACT::SHIPPED_DT", "data_type": "DATE",
         "properties": {"column_type": "ATTRIBUTE"}}]}}
    spec = build_aggregate_table_spec(cand, plans, model, db="SALESDB", schema="PUBLIC",
                                      table_name="AGG_T", connection_name="SF Prod")
    names = [c["name"] for c in spec["columns"]]
    assert "Order Date" in names and "Shipped Date" in names

    tml = build_aggregate_model_tml(cand, plans, model, agg_table_name="AGG_T",
                                    model_name="M (Agg)", connection_name="SF Prod")
    col_names = [c["name"] for c in tml["model"]["columns"]]
    assert "Order Date" in col_names and "Shipped Date" in col_names


def test_patch_association_multi_date_grains_no_bucket():
    # Task 15: two-grain entry (one bucketed, one raw) -> date_aggregation_info
    # has two entries, the raw one emitting bucket: NO_BUCKET (the emission-
    # only string for internal bucket=None; NOT added to lattice.BUCKETS).
    primary = {"guid": "p", "model": {"name": "Sales Model"}}
    entries = [
        {"id": "multi-agg", "projected_rows": 100,
         "date_grains": [{"column": "Transaction Date", "bucket": "DAILY"},
                         {"column": "Shipped Date", "bucket": None}]},
    ]
    patched = patch_association(primary, entries)
    info = patched["model"]["aggregated_models"][0]["date_aggregation_info"]
    assert info == [{"column_id": "Transaction Date", "bucket": "DAILY"},
                    {"column_id": "Shipped Date", "bucket": "NO_BUCKET"}]


def test_patch_association_single_date_shim_unchanged():
    # Task 15 regression guard: the pre-existing single-date shim form
    # (date_column/bucket, no date_grains key) must still emit the exact same
    # single-entry list as before Task 15.
    primary = {"guid": "p", "model": {"name": "Sales Model"}}
    entries = [{"id": "agg", "date_column": "Order Date", "bucket": "MONTHLY",
                "projected_rows": 86}]
    patched = patch_association(primary, entries)
    assert patched["model"]["aggregated_models"][0]["date_aggregation_info"] == \
        [{"column_id": "Order Date", "bucket": "MONTHLY"}]


def test_association_sorted_most_aggregated_first():
    primary = {"guid": "p", "model": {"name": "Sales Model"}}
    entries = [
        {"id": "wide-agg", "date_column": None, "bucket": None, "projected_rows": 50000},
        {"id": "tiny-agg", "date_column": "Order Date", "bucket": "MONTHLY",
         "projected_rows": 86},
        {"id": "unprofiled", "date_column": None, "bucket": None, "projected_rows": None},
    ]
    patched = patch_association(primary, entries)
    ids = [e["id"] for e in patched["model"]["aggregated_models"]]
    assert ids == ["tiny-agg", "wide-agg", "unprofiled"]  # smallest first, None last
    tiny = patched["model"]["aggregated_models"][0]
    # date_aggregation_info is a LIST item per the authoritative schema doc
    # (agents/shared/schemas/thoughtspot-model-tml.md § aggregated_models shows
    # `- column_id: ...`), not a bare dict. Full shape still unverified live —
    # skill Open Item #2 (Task 11).
    assert tiny["date_aggregation_info"] == [{"column_id": "Order Date",
                                              "bucket": "MONTHLY"}]
    assert "projected_rows" not in tiny  # internal field not emitted


def test_date_aggregation_info_to_grains_round_trip():
    # Task 16: date_aggregation_info_to_grains is the inverse of
    # patch_association's emission mapping (NO_BUCKET <-> None). This is the
    # helper `_patch_and_write_primary` needs to reconstruct an EXISTING
    # aggregated_models entry's date_grains from its already-emitted
    # date_aggregation_info — without it, re-patching a primary silently
    # strips every existing entry's date association (Task 16 bug).
    primary = {"guid": "p", "model": {"name": "M"}}
    grains = [{"column": "Transaction Date", "bucket": "DAILY"},
              {"column": "Shipped Date", "bucket": None}]

    # emit ∘ parse == identity, including the raw (NO_BUCKET) grain.
    patched = patch_association(primary, [{"id": "agg", "date_grains": grains,
                                           "projected_rows": 10}])
    entry = patched["model"]["aggregated_models"][0]
    assert date_aggregation_info_to_grains(entry) == grains

    # parse ∘ emit == identity: a raw TML entry parsed back to grains and
    # re-emitted through patch_association reproduces the same
    # date_aggregation_info byte-for-byte.
    raw_entry = {"id": "agg2", "date_aggregation_info": [
        {"column_id": "Order Date", "bucket": "MONTHLY"},
        {"column_id": "Ship Date", "bucket": "NO_BUCKET"},
    ]}
    parsed_grains = date_aggregation_info_to_grains(raw_entry)
    re_emitted = patch_association(primary, [{"id": raw_entry["id"],
                                              "date_grains": parsed_grains,
                                              "projected_rows": None}])
    assert (re_emitted["model"]["aggregated_models"][0]["date_aggregation_info"]
            == raw_entry["date_aggregation_info"])

    # A dateless existing entry (no date_aggregation_info) round-trips to no
    # grains — unchanged.
    assert date_aggregation_info_to_grains({"id": "dateless"}) == []


def test_patch_association_dedups_by_id_last_wins():
    # Task 16 (idempotence): re-generating an already-imported aggregate
    # deterministically produces the same id; the re-exported primary already
    # carries that entry, so it appears twice in `entries`. patch_association
    # must dedup by id with the LAST (freshly generated) entry winning — one
    # entry, carrying the new grains, not a stale duplicate.
    primary = {"guid": "p", "model": {"name": "M", "aggregated_models": []}}
    entries = [
        {"id": "X", "date_grains": [{"column": "D", "bucket": "MONTHLY"}],
         "projected_rows": None},          # stale existing entry
        {"id": "X", "date_grains": [{"column": "D", "bucket": "DAILY"}],
         "projected_rows": 50},            # fresh new entry — must win
    ]
    patched = patch_association(primary, entries)
    aggs = patched["model"]["aggregated_models"]
    assert len(aggs) == 1
    assert aggs[0]["id"] == "X"
    assert aggs[0]["date_aggregation_info"] == [{"column_id": "D", "bucket": "DAILY"}]


def test_date_aggregation_info_to_grains_missing_bucket_and_column():
    # Task 16 (robustness): a hand-authored / externally-exported primary entry
    # whose grain omits `bucket` must not KeyError — a missing bucket (like an
    # explicit None or "NO_BUCKET") maps to internal None. A grain missing
    # `column_id` is skipped rather than emitting a column-less grain.
    entry = {"id": "x", "date_aggregation_info": [
        {"column_id": "Order Date"},                       # bucket omitted -> None
        {"column_id": "Ship Date", "bucket": "NO_BUCKET"},  # -> None
        {"column_id": "Due Date", "bucket": None},          # -> None
        {"bucket": "MONTHLY"},                              # no column_id -> skipped
    ]}
    assert date_aggregation_info_to_grains(entry) == [
        {"column": "Order Date", "bucket": None},
        {"column": "Ship Date", "bucket": None},
        {"column": "Due Date", "bucket": None},
    ]


def test_min_max_primary_measure_becomes_formula_over_reagg_component():
    # Task 17 (routing fix): a MIN/MAX primary measure must become a FORMULA
    # over its stored MIN/MAX component (routing fires only for formula
    # measures on a live aggregate-aware cluster) — never a plain MEASURE
    # column, which would anyway have carried the wrong aggregation
    # (_build_model_columns hardcodes SUM for every MEASURE column;
    # SUM-of-monthly-maxes would be wrong numbers).
    plans = {"Peak Price": classify_measure("Peak Price", aggregation="MAX"),
             "Sales": classify_measure("Sales", aggregation="SUM"),
             "Orders": classify_measure("Orders", aggregation="COUNT"),
             "Avg Sale": classify_measure("Avg Sale", expr="average ( [Sales] )")}
    cand = {"id": "c2", "dimensions": ["Category"], "date_column": "Order Date",
            "bucket": "MONTHLY",
            "measure_columns": ["Peak Price", "Sales", "Orders", "Avg Sale"],
            "covered": [0], "flags": []}
    tml = build_aggregate_model_tml(cand, plans, MODEL,
                                    agg_table_name="AGG_T",
                                    model_name="M (Agg)", connection_name="SF Prod")
    cols = {c["name"]: c for c in tml["model"]["columns"]}
    formulas = {f["name"]: f for f in tml["model"]["formulas"]}

    # MAX primary measure -> formula over its stored MAX component, no plain
    # column under "Peak Price".
    assert "column_id" not in cols["Peak Price"] and "formula_id" in cols["Peak Price"]
    assert formulas["Peak Price"]["expr"] == "max ( [peak_price_max] )"
    assert cols["peak_price_max"]["properties"]["aggregation"] == "MAX"
    assert cols["peak_price_max"]["properties"]["is_hidden"] is True

    # SUM primary measure: same shape, reagg SUM.
    assert "column_id" not in cols["Sales"] and "formula_id" in cols["Sales"]
    assert formulas["Sales"]["expr"] == "sum ( [sales_sum] )"
    assert cols["sales_sum"]["properties"]["aggregation"] == "SUM"

    # COUNT decomposes to a formula ("Orders" = sum([orders_cnt])) over a summed
    # count component; the component (reagg SUM) is unaffected.
    assert cols["orders_cnt"]["properties"]["aggregation"] == "SUM"
    # AVG components (hidden, summed) — unaffected
    assert cols["avg_sale_sum"]["properties"]["aggregation"] == "SUM"
    assert cols["avg_sale_cnt"]["properties"]["aggregation"] == "SUM"

    # The table spec's MAX component column is already correct and stays MAX.
    spec = build_aggregate_table_spec(cand, plans, MODEL, db="D", schema="S",
                                      table_name="AGG_T", connection_name="SF Prod")
    scols = {c["name"]: c for c in spec["columns"]}
    assert scols["peak_price_max"]["aggregation"] == "MAX"


def test_ratio_measure_flows_through_generate_end_to_end():
    # F5: a safe_divide ratio must produce two hidden component sums in the
    # table spec AND a safe_divide formula in the model (routable aggregate
    # measure) — the walker handles the multi-component SELECT (AgentQL rejects
    # it and falls back).
    model = {"model": {"name": "M", "columns": [
        {"name": "Category", "column_id": "FACT::CATEGORY",
         "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "ARPU", "formula_id": "f_arpu",
         "properties": {"column_type": "MEASURE"}}],
        "formulas": [{"id": "f_arpu", "name": "ARPU",
                      "expr": "safe_divide ( sum ( [FACT::AMOUNT] ) , sum ( [FACT::QTY] ) )"}]}}
    cand = {"id": "c", "dimensions": ["Category"], "date_column": None,
            "bucket": None, "measure_columns": ["ARPU"], "covered": [0], "flags": []}
    plans = {"ARPU": classify_measure(
        "ARPU", expr="safe_divide ( sum ( [FACT::AMOUNT] ) , sum ( [FACT::QTY] ) )")}
    spec = build_aggregate_table_spec(cand, plans, model, db="D", schema="S",
                                      table_name="T", connection_name="C")
    names = {c["name"] for c in spec["columns"]}
    assert "arpu_num" in names and "arpu_den" in names
    tml = build_aggregate_model_tml(cand, plans, model, agg_table_name="T",
                                    model_name="T (M)", connection_name="C")
    arpu_formula = [f for f in tml["model"]["formulas"] if f["name"] == "ARPU"][0]
    assert arpu_formula["expr"].startswith("safe_divide (")


def test_ratio_components_typed_per_source_column_not_first_ref():
    # F8 refinement: a ratio's numerator and denominator reference DIFFERENT
    # columns; each component must be typed from its OWN source_column
    # (num=DOUBLE from a float col, den=INT64 from an int col), not both from
    # the measure's first ref (which would type the int den as DOUBLE and fail
    # `ts tables create`).
    model = {"model": {"name": "M", "columns": [
        {"name": "Category", "column_id": "DIM::CATEGORY",
         "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "ARPU", "formula_id": "f",
         "properties": {"column_type": "MEASURE"}}],
        "formulas": [{"id": "f", "name": "ARPU",
                      "expr": "safe_divide ( sum ( [FACT::AMOUNT] ) , sum ( [FACT::QTY] ) )"}]}}
    tables = {"FACT": {"table": {"columns": [
        {"name": "AMOUNT", "db_column_name": "AMOUNT",
         "db_column_properties": {"data_type": "DOUBLE"}},
        {"name": "QTY", "db_column_name": "QTY",
         "db_column_properties": {"data_type": "INT64"}}]}}}
    cand = {"id": "c", "dimensions": ["Category"], "date_column": None,
            "bucket": None, "measure_columns": ["ARPU"], "covered": [0], "flags": []}
    plans = {"ARPU": classify_measure(
        "ARPU", expr="safe_divide ( sum ( [FACT::AMOUNT] ) , sum ( [FACT::QTY] ) )")}
    spec = build_aggregate_table_spec(cand, plans, model, db="D", schema="S",
                                      table_name="T", connection_name="C",
                                      table_tmls=tables)
    by = {c["name"]: c["data_type"] for c in spec["columns"]}
    assert by["arpu_num"] == "DOUBLE" and by["arpu_den"] == "INT64"
