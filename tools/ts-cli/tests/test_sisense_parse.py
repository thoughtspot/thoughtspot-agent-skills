"""Unit tests for ts_cli.sisense.parsing — offline bundle -> inventory.

Pure functions, no live cluster. A tiny synthetic bundle (datamodel side) exercises:
oid-triple relation resolution, Sisense type-code mapping, calculated-column detection,
and graceful handling of a missing datamodel (warning, no crash).
"""
from ts_cli.sisense.parsing import parse_inventory


def test_dashboard_filter_classification():
    # The dashboard filter bar -> classified SourceFilters (member/exclude/range/top_n),
    # each carrying `raw` so the chip extractor can reconstruct numeric-range presets.
    bundle = {"dashboard": {"title": "D", "filters": [
        {"jaql": {"dim": "[t.Country]", "filter": {"members": ["US", "CA"]}}},
        {"jaql": {"dim": "[t.Region]", "filter": {"exclude": {"members": ["XX"]}}}},
        {"jaql": {"dim": "[t.Revenue]", "filter": {"from": 10, "toNotEqual": 100}}},
        {"jaql": {"dim": "[t.Category]", "filter": {"top": 5, "by": {}}}},
        {"jaql": {"dim": "[t.Weird]", "filter": {"someUnknownOp": 1}}},
    ]}}
    fils = parse_inventory(bundle)["dashboard"]["filters"]
    kinds = [f["kind"] for f in fils]
    assert kinds == ["member", "exclude", "range", "top_n", "unknown"]
    assert fils[0]["values"] == ["US", "CA"]
    assert fils[1]["values"] == ["XX"]
    assert fils[2]["raw"] == {"from": 10, "toNotEqual": 100}   # raw preserved for chip presets
    assert fils[4]["kind"] == "unknown"                        # nothing silently dropped


def _bundle():
    return {
        "datamodel": {
            "title": "Shop",
            "relations": [
                {"columns": [
                    {"dataset": "ds1", "table": "t_cat", "column": "oid_cat_id"},
                    {"dataset": "ds2", "table": "t_fact", "column": "oid_fact_cat"},
                ]},
            ],
            "datasets": [
                {"oid": "ds1", "schema": {"tables": [
                    {"oid": "t_cat", "id": "Category.csv", "name": "Category", "type": "base",
                     "columns": [
                         {"oid": "oid_cat_name", "id": "Category", "name": "Category", "type": 18},
                         {"oid": "oid_cat_id", "id": "Category ID", "name": "Category ID", "type": 8},
                     ]},
                ]}},
                {"oid": "ds2", "schema": {"tables": [
                    {"oid": "t_fact", "id": "Commerce.csv", "name": "Commerce", "type": "base",
                     "columns": [
                         {"oid": "oid_fact_cat", "id": "Category ID", "name": "Category ID", "type": 8},
                         {"oid": "oid_rev", "id": "Revenue", "name": "Revenue", "type": 5},
                         {"oid": "oid_dt", "id": "Date", "name": "Date", "type": 31},
                         {"oid": "oid_calc", "id": "Net", "name": "Net", "type": 5,
                          "isCustom": True, "expression": "sum([Revenue])"},
                     ]},
                ]}},
            ],
        },
    }


def test_tables_and_columns():
    inv = parse_inventory(_bundle())
    by_id = {t["id"]: t for t in inv["tables"]}
    assert set(by_id) == {"Category.csv", "Commerce.csv"}
    assert by_id["Category.csv"]["name"] == "Category"
    cols = {c["name"]: c for c in by_id["Commerce.csv"]["columns"]}
    assert cols["Revenue"]["data_type"] == "double"       # type 5 (Decimal)
    assert cols["Category ID"]["data_type"] == "int64"    # type 8 (Integer)
    assert cols["Date"]["data_type"] == "date"            # type 31 (Date)


def test_calculated_column_detected():
    inv = parse_inventory(_bundle())
    fact = next(t for t in inv["tables"] if t["id"] == "Commerce.csv")
    net = next(c for c in fact["columns"] if c["name"] == "Net")
    assert net["calculated"] is True
    assert net["expression"] == "sum([Revenue])"


def test_relation_oid_resolution():
    inv = parse_inventory(_bundle())
    assert len(inv["relations"]) == 1
    eps = {ep["table"]: ep["column"] for ep in inv["relations"][0]["endpoints"]}
    # oids resolved back to (table_id, column_id)
    assert eps == {"Category.csv": "Category ID", "Commerce.csv": "Category ID"}


def test_counts_and_source():
    inv = parse_inventory(_bundle())
    assert inv["source"] == "Shop"
    assert inv["counts"]["tables"] == 2
    assert inv["counts"]["relations"] == 1
    assert inv["counts"]["columns"] == 6


def test_missing_datamodel_warns_no_crash():
    inv = parse_inventory({"dashboard": {}, "widgets": []})
    assert inv["tables"] == []
    assert any("datamodel" in w for w in inv["warnings"])


def test_unknown_type_code_falls_back():
    b = {"datamodel": {"datasets": [{"schema": {"tables": [
        {"oid": "t", "id": "T.csv", "name": "T",
         "columns": [{"oid": "c", "id": "X", "name": "X", "type": 9999}]}]}}]}}
    inv = parse_inventory(b)
    assert inv["tables"][0]["columns"][0]["data_type"] == "unknown"
