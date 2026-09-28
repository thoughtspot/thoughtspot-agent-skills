# tools/smoke-tests/smoke_ts_link_semantic_layer.py
"""Smoke test for ts-link-semantic-layer.

Tier: Pure — no live ThoughtSpot or warehouse connection required, no `ts` on PATH.
Builds a spec shaped like the Databricks Metric View and Snowflake Semantic View metadata
the skill reads (Step 4), runs it through the `ts link build` builder in both aggregation
modes, and checks the invariants the skill promises: a formula-free single-table Model,
AGGREGATE vs standard aggregations, non-numeric measures skipped, instructions kept out
of TML.

Usage:
    python3 tools/smoke-tests/smoke_ts_link_semantic_layer.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "ts-cli"))

from ts_cli.link_build import LinkSpecError, build_link_tml  # noqa: E402

SPEC = {
    "connection": "TS-DBX", "db": "agent_skills", "schema": "business_forecast",
    "db_table": "business_reporting_mv",
    "description": "Business daily reporting KPIs.",
    "instructions": "Use traveller_preferred dimensions for revenue.",
    "columns": [
        {"name": "date", "data_type": "date", "kind": "attribute", "description": "Reporting date."},
        {"name": "month", "data_type": "timestamp_ltz", "kind": "attribute"},
        {"name": "vertical", "data_type": "string", "kind": "attribute",
         "synonyms": ["product line"]},
        {"name": "revenue_gbp", "data_type": "decimal(28,2)", "kind": "measure",
         "expr": "SUM(revenue_gbp) FILTER (WHERE observation = 'current')"},
        {"name": "employee_count", "data_type": "NUMBER(38,0)", "kind": "measure",
         "expr": "COUNT(DISTINCT employee_id)"},
        {"name": "last_available_date", "data_type": "date", "kind": "measure",
         "expr": "MAX(CASE WHEN observation = 'current' THEN dt END)"},
    ],
}


def test_aggregate_mode_thin_model():
    table, model, report = build_link_tml(SPEC, aggregation_mode="aggregate", model_name="Semantic SQL - BR")
    m = model["model"]
    assert "formulas" not in m and m["model_tables"] == [{"name": "business_reporting_mv"}]
    measures = [c for c in table["table"]["columns"] if c["properties"]["column_type"] == "MEASURE"]
    assert {c["properties"]["aggregation"] for c in measures} == {"AGGREGATE"}
    assert all("db_column_name" in c for c in table["table"]["columns"])
    types = {c["name"]: c["db_column_properties"]["data_type"] for c in table["table"]["columns"]}
    assert types["month"] == "DATE_TIME" and types["employee_count"] == "INT64"
    print(f"  {report['columns']} columns, {report['measures']} measures, all AGGREGATE, no formulas")


def test_standard_mode_logical_aggregations():
    table, _, _ = build_link_tml(SPEC, aggregation_mode="standard", model_name="S")
    aggs = {c["name"]: c["properties"].get("aggregation") for c in table["table"]["columns"]
            if c["properties"]["column_type"] == "MEASURE"}
    assert aggs == {"revenue_gbp": "SUM", "employee_count": "COUNT_DISTINCT"}, aggs
    print("  standard mode: SUM (through FILTER) and COUNT_DISTINCT inferred")


def test_non_numeric_measure_skipped():
    table, _, report = build_link_tml(SPEC, aggregation_mode="aggregate", model_name="S")
    assert "last_available_date" not in {c["name"] for c in table["table"]["columns"]}
    assert [s["name"] for s in report["skipped"]] == ["last_available_date"]
    print("  DATE measure skipped and reported")


def test_metadata_and_instructions():
    _, model, report = build_link_tml(SPEC, aggregation_mode="aggregate", model_name="S")
    m = model["model"]
    vertical = next(c for c in m["columns"] if c["column_id"].endswith("::vertical"))
    assert vertical["properties"]["synonyms"] == ["product line"]
    assert m["description"] == "Business daily reporting KPIs."
    assert "model_instructions" not in m, "instructions must go through the API, not TML"
    assert report["instructions"] == ["Use traveller_preferred dimensions for revenue."]
    print("  synonyms + description carried; instructions routed to the API")


def test_standard_mode_refuses_ratio():
    spec = dict(SPEC, columns=SPEC["columns"][:3] + [
        {"name": "cvr", "data_type": "double", "kind": "measure", "expr": "SUM(a) / NULLIF(SUM(b), 0)"}])
    try:
        build_link_tml(spec, aggregation_mode="standard", model_name="S")
    except LinkSpecError as exc:
        assert "cvr" in str(exc)
        print("  ratio measure refused in standard mode (no guessed SUM)")
        return
    raise AssertionError("standard mode accepted a ratio without an explicit aggregation")


if __name__ == "__main__":
    for fn in (test_aggregate_mode_thin_model,
               test_standard_mode_logical_aggregations,
               test_non_numeric_measure_skipped,
               test_metadata_and_instructions,
               test_standard_mode_refuses_ratio):
        print(f"{fn.__name__}:")
        fn()
    print("All smoke tests passed.")
