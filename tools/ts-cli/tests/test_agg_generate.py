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
    assert "Sales" in col_names           # direct-additive measure keeps column name
    hidden = [c["name"] for c in m["columns"]
              if (c.get("properties") or {}).get("is_hidden")]
    assert "avg_sale_sum" in hidden and "avg_sale_cnt" in hidden
    f = [f for f in m["formulas"] if f["name"] == "Avg Sale"][0]
    assert f["expr"] == "sum ( [avg_sale_sum] ) / sum ( [avg_sale_cnt] )"


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


def test_min_max_primary_measure_keeps_reagg_in_model_column():
    # A MIN/MAX single-component primary measure must carry its reagg (MIN/MAX)
    # on the aggregate MODEL column, not the SUM that _build_model_columns
    # hardcodes — SUM-of-monthly-maxes would be wrong numbers. Fixed in
    # build_aggregate_model_tml's post-pass (locally, not in shared model_builder).
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
    # MAX primary measure → model column aggregation MAX (not SUM)
    assert cols["Peak Price"]["properties"]["aggregation"] == "MAX"
    # SUM primary measure unaffected
    assert cols["Sales"]["properties"]["aggregation"] == "SUM"
    # COUNT decomposes to a formula ("Orders" = sum([orders_cnt])) over a summed
    # count component; the component (reagg SUM) is unaffected by the override.
    assert cols["orders_cnt"]["properties"]["aggregation"] == "SUM"
    # AVG components (hidden, summed) — unaffected
    assert cols["avg_sale_sum"]["properties"]["aggregation"] == "SUM"
    assert cols["avg_sale_cnt"]["properties"]["aggregation"] == "SUM"

    # The table spec's MAX component column is already correct and stays MAX.
    spec = build_aggregate_table_spec(cand, plans, MODEL, db="D", schema="S",
                                      table_name="AGG_T", connection_name="SF Prod")
    scols = {c["name"]: c for c in spec["columns"]}
    assert scols["peak_price_max"]["aggregation"] == "MAX"
