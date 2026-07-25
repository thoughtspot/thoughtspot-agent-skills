"""Unit tests for the publish planning engine (ts_cli/publish_plan.py).

Field-variance clustering is the core of `ts publish export`. Its shape follows
from the live finding that one variable holds one value per scope and that
`field_names[]` writes the same token into every field listed, so the model is
one variable per DISTINCT VALUE, shared by every table needing that value.
"""
from __future__ import annotations

import pytest

from ts_cli.publish_plan import (
    build_clusters,
    extract_table_fields,
    parse_variable_token,
    slugify,
    suggest_variable_name,
)


def _table(name, guid, db="AGENT_SKILLS", schema="ALIAS_TESTS", db_table=None, connection="APJ"):
    return {"guid": guid, "table": {"name": name, "db": db, "schema": schema,
                                    "db_table": db_table or name,
                                    "connection": {"name": connection}}}


# ---------------------------------------------------------------------------
# Token parsing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("${apj_schema}", "apj_schema"),
    ("  ${apj_schema}  ", "apj_schema"),
    ("ALIAS_TESTS", None),
    ("", None),
    (None, None),
    ("${}", None),
    ("prefix_${x}", None),  # only a whole-value token counts as parameterized
])
def test_parse_variable_token(raw, expected):
    assert parse_variable_token(raw) == expected


# ---------------------------------------------------------------------------
# Field extraction
# ---------------------------------------------------------------------------

def test_extract_table_fields_reads_all_three_attributes():
    fields = extract_table_fields(_table("T1", "g1"))
    assert fields["name"] == "T1"
    assert fields["connection"] == "APJ"
    assert fields["fields"]["databaseName"] == {"value": "AGENT_SKILLS", "variable": None}
    assert fields["fields"]["schemaName"] == {"value": "ALIAS_TESTS", "variable": None}
    assert fields["fields"]["tableName"] == {"value": "T1", "variable": None}


def test_extract_table_fields_detects_existing_parameterization():
    fields = extract_table_fields(_table("T1", "g1", schema="${apj_schema}"))
    assert fields["fields"]["schemaName"] == {"value": "${apj_schema}", "variable": "apj_schema"}


def test_extract_table_fields_tolerates_missing_keys():
    fields = extract_table_fields({"guid": "g", "table": {"name": "T"}})
    assert fields["fields"]["databaseName"]["value"] is None


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

def test_shared_schema_across_tables_yields_one_cluster():
    tables = [extract_table_fields(_table(f"T{i}", f"g{i}")) for i in range(1, 4)]
    clusters = build_clusters(tables)
    schema = [c for c in clusters if c["field"] == "schemaName"]
    assert len(schema) == 1
    assert schema[0]["current_value"] == "ALIAS_TESTS"
    assert schema[0]["tables"] == ["g1", "g2", "g3"]
    assert schema[0]["spans_tables"] == 3


def test_distinct_values_yield_separate_clusters():
    tables = [
        extract_table_fields(_table("T1", "g1", schema="SALES")),
        extract_table_fields(_table("T2", "g2", schema="SALES")),
        extract_table_fields(_table("REF", "g3", schema="SHARED_REF")),
    ]
    schema = sorted([c for c in build_clusters(tables) if c["field"] == "schemaName"],
                    key=lambda c: c["current_value"])
    assert [c["current_value"] for c in schema] == ["SALES", "SHARED_REF"]
    assert schema[0]["tables"] == ["g1", "g2"]
    assert schema[1]["tables"] == ["g3"]


def test_table_name_clusters_are_per_table_and_not_recommended():
    # Each table has its own name, so tableName never clusters. It is also the
    # field that is almost never a tenant discriminator.
    tables = [extract_table_fields(_table(f"T{i}", f"g{i}")) for i in range(1, 4)]
    table_clusters = [c for c in build_clusters(tables) if c["field"] == "tableName"]
    assert len(table_clusters) == 3
    assert all(c["recommended"] is False for c in table_clusters)


def test_database_and_schema_are_recommended():
    tables = [extract_table_fields(_table("T1", "g1"))]
    by_field = {c["field"]: c for c in build_clusters(tables)}
    assert by_field["databaseName"]["recommended"] is True
    assert by_field["schemaName"]["recommended"] is True
    assert by_field["databaseName"]["parameterizable"] is True


def test_falcon_backed_table_is_not_parameterizable():
    # No connection block means a Falcon-backed table. The docs say default
    # system tables cannot be parameterized, so recommending one is a dead end.
    tables = [extract_table_fields(_table("T1", "g1", connection=None))]
    by_field = {c["field"]: c for c in build_clusters(tables)}
    assert by_field["schemaName"]["parameterizable"] is False
    assert by_field["schemaName"]["recommended"] is False


def test_already_parameterized_cluster_is_flagged_and_not_re_suggested():
    tables = [extract_table_fields(_table("T1", "g1", schema="${apj_schema}"))]
    cluster = [c for c in build_clusters(tables) if c["field"] == "schemaName"][0]
    assert cluster["already_parameterized"] is True
    assert cluster["variable"] == "apj_schema"
    assert cluster["suggested_variable"] is None


def test_parameterized_and_static_values_do_not_merge():
    tables = [
        extract_table_fields(_table("T1", "g1", schema="${apj_schema}")),
        extract_table_fields(_table("T2", "g2", schema="ALIAS_TESTS")),
    ]
    schema = [c for c in build_clusters(tables) if c["field"] == "schemaName"]
    assert len(schema) == 2


def test_fields_with_no_value_are_skipped():
    tables = [extract_table_fields({"guid": "g", "table": {"name": "T"}})]
    assert build_clusters(tables) == []


# ---------------------------------------------------------------------------
# Variable naming
# ---------------------------------------------------------------------------

def test_slugify():
    assert slugify("My Connection") == "my_connection"
    assert slugify("APJ-Prod.01") == "apj_prod_01"
    assert slugify("__weird__") == "weird"


def test_suggested_name_is_connection_plus_field():
    tables = [extract_table_fields(_table("T1", "g1"))]
    by_field = {c["field"]: c for c in build_clusters(tables)}
    assert by_field["schemaName"]["suggested_variable"] == "apj_schema"
    assert by_field["databaseName"]["suggested_variable"] == "apj_db"


def test_suggested_name_disambiguates_when_a_field_has_several_values():
    tables = [
        extract_table_fields(_table("T1", "g1", schema="SALES")),
        extract_table_fields(_table("REF", "g2", schema="SHARED_REF")),
    ]
    names = {c["current_value"]: c["suggested_variable"]
             for c in build_clusters(tables) if c["field"] == "schemaName"}
    assert names == {"SALES": "apj_sales_schema", "SHARED_REF": "apj_shared_ref_schema"}


def test_suggested_name_avoids_collision_with_existing_variables():
    tables = [extract_table_fields(_table("T1", "g1"))]
    clusters = build_clusters(tables, existing_variables={"apj_schema"})
    schema = [c for c in clusters if c["field"] == "schemaName"][0]
    assert schema["suggested_variable"] == "apj_schema_2"


def test_suggest_variable_name_avoids_collisions_within_one_run():
    taken = set()
    first = suggest_variable_name("APJ", "schemaName", "SALES", taken, disambiguate=False)
    taken.add(first)
    second = suggest_variable_name("APJ", "schemaName", "OTHER", taken, disambiguate=False)
    assert first == "apj_schema"
    assert second == "apj_schema_2"
