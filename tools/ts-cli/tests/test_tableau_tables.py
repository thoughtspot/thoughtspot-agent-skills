"""Unit tests for ts_cli.tableau.tables.build_table_tml — pure Table-TML assembly
for the Tableau converter. Mirrors ts_cli.powerbi.tables' contract (see CLAUDE.md
"Critical TML invariants" and agents/shared/schemas/thoughtspot-table-tml.md).
"""
from ts_cli.tableau.tables import build_table_tml


def test_build_table_tml_shape_and_invariants():
    table = {"name": "Orders", "columns": [
        {"name": "Order ID", "data_type": "integer", "column_type": "ATTRIBUTE"},
        {"name": "Sales", "data_type": "double", "column_type": "MEASURE", "aggregation": "SUM"},
        {"name": "Order Date", "data_type": "datetime", "column_type": "ATTRIBUTE"},
    ]}
    obj, dropped = build_table_tml(table, "APJ_TAB", "DB", "PUBLIC")
    t = obj["table"]
    assert obj["obj_id"].endswith("-tableau")
    assert t["connection"] == {"name": "APJ_TAB"}
    assert "fqn" not in str(t["connection"])
    assert t["db"] == "DB" and t["schema"] == "PUBLIC"
    cols = {c["name"]: c for c in t["columns"]}
    assert all("db_column_name" in c for c in t["columns"])
    assert cols["Order Date"]["db_column_properties"]["data_type"] == "DATE_TIME"
    assert cols["Sales"]["properties"]["aggregation"] == "SUM"
    assert dropped == []


def test_build_table_tml_display_name_and_db_table_default():
    table = {"name": "Orders", "columns": [
        {"name": "Order ID", "data_type": "integer", "column_type": "ATTRIBUTE"},
    ]}
    obj, _ = build_table_tml(table, "APJ_TAB", "DB", "PUBLIC")
    t = obj["table"]
    assert t["name"] == "Orders"
    assert t["db_table"] == "Orders"  # _dbname("Orders") with no spaces/punctuation


# ---------------------------------------------------------------------------
# Fix #C — db_table prefers the parser's own db_table field (a dotted
# db.schema.table path — see twb.py._extract_tables) over re-slugging `name`.
# Live-reproduced on Ads Commercial Dashboard: `d_partner1` is a Tableau-
# assigned ALIAS for a physical table joined twice — its logical `name` is
# "d_partner1" but the parser's `db_table` field says the real warehouse
# table is "dev_trusted_gold.bar_media.d_partner". Before this fix,
# build_table_tml re-slugged `name` and emitted `db_table: d_partner1` — a
# table that does not exist in the warehouse (only `d_partner` does).
# ---------------------------------------------------------------------------

def test_build_table_tml_prefers_parsed_db_table_over_name_reslug_for_aliased_table():
    table = {
        "name": "d_partner1",
        "db_table": "dev_trusted_gold.bar_media.d_partner",
        "alias_of": "d_partner",
        "columns": [{"name": "Region", "data_type": "string", "column_type": "ATTRIBUTE"}],
    }
    obj, _ = build_table_tml(table, "APJ_TAB", "DB", "PUBLIC")
    assert obj["table"]["db_table"] == "d_partner"  # NOT "d_partner1"
    assert obj["table"]["name"] == "d_partner1"      # display name is untouched


def test_build_table_tml_parsed_db_table_last_segment_only_no_dotted_path_leak():
    # db_table must never end up as the full db.schema.table path — db/schema
    # are already their own separate Table TML fields.
    table = {"name": "Orders", "db_table": "dev_trusted_gold.bar_media.Orders", "columns": []}
    obj, _ = build_table_tml(table, "CONN", "DB", "SCHEMA")
    assert obj["table"]["db_table"] == "Orders"
    assert "." not in obj["table"]["db_table"]


def test_build_table_tml_table_map_still_wins_over_parsed_db_table():
    table = {"name": "d_partner1", "db_table": "dev_trusted_gold.bar_media.d_partner", "columns": []}
    obj, _ = build_table_tml(
        table, "CONN", "DB", "SCHEMA", table_map={"d_partner1": "EXPLICIT_OVERRIDE"},
    )
    assert obj["table"]["db_table"] == "EXPLICIT_OVERRIDE"


def test_build_table_tml_no_parsed_db_table_falls_back_to_name_slug():
    # Hand-built table dicts (e.g. unit tests, other converters) with no
    # `db_table` field at all must keep today's re-slug fallback.
    table = {"name": "Sales Orders", "columns": []}
    obj, _ = build_table_tml(table, "CONN", "DB", "SCHEMA")
    assert obj["table"]["db_table"] == "Sales_Orders"


def test_build_table_tml_type_map_covers_all_spec_values():
    table = {"name": "Types", "columns": [
        {"name": "A", "data_type": "int"},
        {"name": "B", "data_type": "float"},
        {"name": "C", "data_type": "decimal"},
        {"name": "D", "data_type": "text"},
        {"name": "E", "data_type": "bool"},
        {"name": "F", "data_type": "date"},
        {"name": "G", "data_type": "timestamp"},
        {"name": "H", "data_type": "something-unknown"},
        {"name": "I"},  # missing data_type entirely
    ]}
    obj, _ = build_table_tml(table, "CONN", "DB", "SCHEMA")
    dt = {c["name"]: c["db_column_properties"]["data_type"] for c in obj["table"]["columns"]}
    assert dt["A"] == "INT64"
    assert dt["B"] == "DOUBLE"
    assert dt["C"] == "DOUBLE"
    assert dt["D"] == "VARCHAR"
    assert dt["E"] == "BOOL"
    assert dt["F"] == "DATE"
    assert dt["G"] == "DATE_TIME"
    assert dt["H"] == "VARCHAR"
    assert dt["I"] == "VARCHAR"


def test_build_table_tml_infers_role_when_column_type_absent():
    table = {"name": "Orders", "columns": [
        {"name": "Order ID", "data_type": "integer"},          # key -> ATTRIBUTE despite numeric
        {"name": "Sales", "data_type": "double"},               # numeric non-key -> MEASURE/SUM
        {"name": "Customer Name", "data_type": "string"},       # non-numeric -> ATTRIBUTE
    ]}
    obj, _ = build_table_tml(table, "CONN", "DB", "SCHEMA")
    cols = {c["name"]: c for c in obj["table"]["columns"]}
    assert cols["Order ID"]["properties"]["column_type"] == "ATTRIBUTE"
    assert "aggregation" not in cols["Order ID"]["properties"]
    assert cols["Sales"]["properties"]["column_type"] == "MEASURE"
    assert cols["Sales"]["properties"]["aggregation"] == "SUM"
    assert cols["Customer Name"]["properties"]["column_type"] == "ATTRIBUTE"
    assert "aggregation" not in cols["Customer Name"]["properties"]


def test_build_table_tml_column_type_from_parse_wins_over_inference():
    # column_type already classified by the parser is authoritative even if the
    # heuristic would have guessed differently (e.g. a numeric ID kept as a MEASURE).
    table = {"name": "Orders", "columns": [
        {"name": "Order ID", "data_type": "integer", "column_type": "MEASURE", "aggregation": "COUNT"},
    ]}
    obj, _ = build_table_tml(table, "CONN", "DB", "SCHEMA")
    col = obj["table"]["columns"][0]
    assert col["properties"]["column_type"] == "MEASURE"
    assert col["properties"]["aggregation"] == "COUNT"


def test_build_table_tml_table_map_and_column_map_override_physical_names_only():
    table = {"name": "Sales Orders", "columns": [
        {"name": "Order ID", "data_type": "integer", "column_type": "ATTRIBUTE"},
        {"name": "Sales Amount", "data_type": "double", "column_type": "MEASURE", "aggregation": "SUM"},
    ]}
    table_map = {"Sales Orders": "FCT_SALES_ORDERS"}
    column_map = {"Sales Orders": {"Sales Amount": "SALES_AMT"}}
    obj, dropped = build_table_tml(
        table, "APJ_TAB", "DB", "PUBLIC",
        table_map=table_map, column_map=column_map,
    )
    t = obj["table"]
    # display name stays the Tableau name; only the physical db_table is remapped
    assert t["name"] == "Sales Orders"
    assert t["db_table"] == "FCT_SALES_ORDERS"
    cols = {c["name"]: c for c in t["columns"]}
    assert cols["Sales Amount"]["name"] == "Sales Amount"
    assert cols["Sales Amount"]["db_column_name"] == "SALES_AMT"
    # unmapped column falls back to the derived physical name, not dropped
    assert cols["Order ID"]["db_column_name"] == "Order_ID"
    assert dropped == []


def test_build_table_tml_unmapped_column_is_not_dropped():
    # v1 has no drop_unmapped param (YAGNI — mirrors powerbi's default drop_unmapped=False):
    # a column absent from column_map keeps its derived physical name and is never dropped.
    table = {"name": "Orders", "columns": [
        {"name": "Order ID", "data_type": "integer", "column_type": "ATTRIBUTE"},
    ]}
    obj, dropped = build_table_tml(
        table, "CONN", "DB", "SCHEMA",
        column_map={"Orders": {}},  # present but empty — "Order ID" is unmapped
    )
    assert [c["name"] for c in obj["table"]["columns"]] == ["Order ID"]
    assert dropped == []


def test_build_table_tml_duplicate_display_names_both_pass_through():
    # No dedup/collision logic in v1 (mirrors powerbi/tables.py, which has none either):
    # two columns sharing a display name both come through unchanged.
    table = {"name": "Orders", "columns": [
        {"name": "Amount", "data_type": "double", "column_type": "MEASURE", "aggregation": "SUM"},
        {"name": "Amount", "data_type": "double", "column_type": "MEASURE", "aggregation": "AVERAGE"},
    ]}
    obj, dropped = build_table_tml(table, "CONN", "DB", "SCHEMA")
    names = [c["name"] for c in obj["table"]["columns"]]
    assert names == ["Amount", "Amount"]
    assert dropped == []


def test_build_table_tml_obj_id_slugifies_name():
    table = {"name": "Sales & Orders!", "columns": [
        {"name": "X", "data_type": "integer", "column_type": "ATTRIBUTE"},
    ]}
    obj, _ = build_table_tml(table, "CONN", "DB", "SCHEMA")
    assert obj["obj_id"] == "sales-orders-tableau"


def test_canonical_ts_data_types_pass_through():
    """Canonical TS data types (emitted by real parse output) should pass through unchanged."""
    table = {"name": "Orders", "columns": [
        {"name": "ID", "data_type": "INT64", "column_type": "ATTRIBUTE"},
        {"name": "Amount", "data_type": "DOUBLE", "column_type": "ATTRIBUTE"},
        {"name": "Active", "data_type": "BOOL", "column_type": "ATTRIBUTE"},
        {"name": "Birth Date", "data_type": "DATE", "column_type": "ATTRIBUTE"},
        {"name": "Created At", "data_type": "DATE_TIME", "column_type": "ATTRIBUTE"},
        {"name": "Description", "data_type": "VARCHAR", "column_type": "ATTRIBUTE"},
    ]}
    obj, _ = build_table_tml(table, "CONN", "DB", "SCHEMA")
    dt = {c["name"]: c["db_column_properties"]["data_type"] for c in obj["table"]["columns"]}
    assert dt["ID"] == "INT64"
    assert dt["Amount"] == "DOUBLE"
    assert dt["Active"] == "BOOL"
    assert dt["Birth Date"] == "DATE"
    assert dt["Created At"] == "DATE_TIME"
    assert dt["Description"] == "VARCHAR"
