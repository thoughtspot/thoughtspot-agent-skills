from ts_cli.aggregate.generate import (build_aggregate_table_spec,
                                       build_aggregate_model_tml,
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
    assert tiny["date_aggregation_info"] == {"column_id": "Order Date",
                                             "bucket": "MONTHLY"}
    assert "projected_rows" not in tiny  # internal field not emitted
