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


# ---------------------------------------------------------------------------
# Value matrix (ts publish resolve)
# ---------------------------------------------------------------------------

from ts_cli.publish_plan import (  # noqa: E402
    build_value_matrix,
    coverage_report,
    expand_pattern,
    parse_pattern_args,
    selectable_clusters,
)

_ORGS = [{"name": "ORG1", "id": 11}, {"name": "ORG2", "id": 22}]


def _cluster(field="schemaName", value="SALES", variable=None, name="apj_schema",
             parameterizable=True, recommended=True):
    return {"field": field, "current_value": value, "suggested_variable": name,
            "variable": variable, "already_parameterized": variable is not None,
            "tables": ["g1"], "table_names": ["T1"], "connection": "APJ",
            "spans_tables": 1, "parameterizable": parameterizable,
            "recommended": recommended}


@pytest.mark.parametrize("template,expected", [
    ("{ORG_UPPER}_DB", "ORG1_DB"),
    ("{ORG_LOWER}_db", "org1_db"),
    ("tenant_{ORG}", "tenant_Org1"),
    ("t{ORG_ID}", "t11"),
    ("{VALUE}", "SALES"),
    ("static", "static"),
])
def test_expand_pattern(template, expected):
    assert expand_pattern(template, "Org1", 11, "SALES") == expected


def test_expand_pattern_rejects_unknown_placeholder():
    with pytest.raises(ValueError, match="TENANT"):
        expand_pattern("{TENANT}_db", "Org1", 11, "SALES")


def test_parse_pattern_args():
    assert parse_pattern_args(["schemaName={ORG_UPPER}", "databaseName=SHARED"]) == {
        "schemaName": "{ORG_UPPER}", "databaseName": "SHARED"}


def test_parse_pattern_args_rejects_malformed():
    with pytest.raises(ValueError, match="field=pattern"):
        parse_pattern_args(["schemaName"])


def test_selectable_clusters_defaults_to_recommended_only():
    clusters = [_cluster(), _cluster(field="tableName", name="apj_table", recommended=False)]
    assert [c["field"] for c in selectable_clusters(clusters)] == ["schemaName"]


def test_selectable_clusters_honours_explicit_fields():
    clusters = [_cluster(), _cluster(field="tableName", name="apj_table", recommended=False)]
    picked = selectable_clusters(clusters, fields=["tableName"])
    assert [c["field"] for c in picked] == ["tableName"]


def test_selectable_clusters_never_returns_unparameterizable():
    clusters = [_cluster(parameterizable=False)]
    assert selectable_clusters(clusters, fields=["schemaName"]) == []


def test_uniform_source_repeats_current_value_for_every_org():
    matrix = build_value_matrix([_cluster()], _ORGS, source="uniform")
    assert matrix["assignments"] == [
        {"variable": "apj_schema", "org": "ORG1", "value": "SALES"},
        {"variable": "apj_schema", "org": "ORG2", "value": "SALES"},
    ]


def test_pattern_source_expands_per_org():
    matrix = build_value_matrix([_cluster()], _ORGS, source="pattern",
                                patterns={"schemaName": "{ORG_UPPER}_SALES"})
    assert [a["value"] for a in matrix["assignments"]] == ["ORG1_SALES", "ORG2_SALES"]


def test_pattern_source_falls_back_to_current_value_when_field_unmatched():
    matrix = build_value_matrix([_cluster()], _ORGS, source="pattern",
                                patterns={"databaseName": "{ORG_UPPER}_DB"})
    assert [a["value"] for a in matrix["assignments"]] == ["SALES", "SALES"]


def test_file_source_uses_supplied_rows():
    rows = [{"org_name": "ORG1", "variable_name": "apj_schema", "value": "A"},
            {"org_name": "ORG2", "variable_name": "apj_schema", "value": "B"}]
    matrix = build_value_matrix([_cluster()], _ORGS, source="file", csv_rows=rows)
    assert [a["value"] for a in matrix["assignments"]] == ["A", "B"]


def test_file_source_leaves_a_gap_when_a_row_is_missing():
    rows = [{"org_name": "ORG1", "variable_name": "apj_schema", "value": "A"}]
    matrix = build_value_matrix([_cluster()], _ORGS, source="file", csv_rows=rows)
    assert matrix["coverage"]["complete"] is False
    assert matrix["coverage"]["missing"] == [{"variable": "apj_schema", "org": "ORG2"}]


def test_matrix_reuses_the_existing_variable_name_when_already_parameterized():
    matrix = build_value_matrix([_cluster(variable="already_bound")], _ORGS, source="uniform")
    assert matrix["variables"][0]["name"] == "already_bound"
    assert matrix["variables"][0]["exists"] is True


def test_matrix_marks_new_variables_for_creation():
    matrix = build_value_matrix([_cluster()], _ORGS, source="uniform")
    assert matrix["variables"] == [{
        "name": "apj_schema", "type": "TABLE_MAPPING", "field": "schemaName",
        "tables": ["g1"], "exists": False, "sensitive": False,
    }]


def test_coverage_report_is_complete_when_every_org_has_a_value():
    assignments = [{"variable": "v", "org": "ORG1", "value": "x"},
                   {"variable": "v", "org": "ORG2", "value": "y"}]
    report = coverage_report(assignments, ["v"], _ORGS)
    assert report == {"complete": True, "missing": []}


def test_coverage_report_flags_a_blank_value_as_missing():
    assignments = [{"variable": "v", "org": "ORG1", "value": ""},
                   {"variable": "v", "org": "ORG2", "value": "y"}]
    report = coverage_report(assignments, ["v"], _ORGS)
    assert report["missing"] == [{"variable": "v", "org": "ORG1"}]


# ---------------------------------------------------------------------------
# Apply plan / rollback (ts publish apply, ts publish rollback)
# ---------------------------------------------------------------------------

from ts_cli.publish_plan import build_apply_plan, rollback_steps  # noqa: E402

_CLOSURE = {
    "root": {"guid": "model-1", "name": "M"},
    "tables": [{"guid": "g1", "name": "T1", "connection": "APJ", "fields": {
        "databaseName": {"value": "AGENT_SKILLS", "variable": None},
        "schemaName": {"value": "ALIAS_TESTS", "variable": None},
    }}],
}
_MATRIX = {
    "orgs": ["ORG1"],
    "variables": [{"name": "apj_schema", "type": "TABLE_MAPPING", "field": "schemaName",
                   "tables": ["g1"], "exists": False, "sensitive": False}],
    "assignments": [{"variable": "apj_schema", "org": "ORG1", "value": "TENANT1"}],
}


def test_apply_plan_creates_assigns_and_parameterizes():
    plan = build_apply_plan(_CLOSURE, _MATRIX)
    assert plan["create_variables"] == [
        {"name": "apj_schema", "type": "TABLE_MAPPING", "sensitive": False}]
    assert plan["assign_values"] == _MATRIX["assignments"]
    assert plan["parameterize"] == [{"metadata_identifier": "g1", "metadata_type": "LOGICAL_TABLE",
                                     "field_names": ["schemaName"], "variable": "apj_schema"}]
    assert plan["publish"] is None


def test_apply_plan_records_the_original_value_for_rollback():
    plan = build_apply_plan(_CLOSURE, _MATRIX)
    assert plan["rollback"]["parameterized"] == [{
        "metadata_identifier": "g1", "metadata_type": "LOGICAL_TABLE",
        "field_name": "schemaName", "original_value": "ALIAS_TESTS"}]


def test_apply_plan_only_lists_variables_it_creates_for_deletion():
    matrix = {**_MATRIX, "variables": [{**_MATRIX["variables"][0], "exists": True}]}
    plan = build_apply_plan(_CLOSURE, matrix)
    assert plan["create_variables"] == []
    assert plan["rollback"]["created_variables"] == []


def test_apply_plan_skips_a_field_already_bound_to_a_token():
    closure = {"root": {"guid": "m"}, "tables": [{"guid": "g1", "fields": {
        "schemaName": {"value": "${apj_schema}", "variable": "apj_schema"}}}]}
    plan = build_apply_plan(closure, _MATRIX)
    assert plan["parameterize"] == []
    assert plan["rollback"]["parameterized"] == []


def test_apply_plan_includes_publish_when_orgs_given():
    # publish is a list: the API takes one type per call, and a selection can mix
    # a Liveboard, an Answer and a Model.
    plan = build_apply_plan(_CLOSURE, _MATRIX, publish_orgs=["ORG1"])
    assert plan["publish"] == [{"identifiers": ["model-1"], "type": "LOGICAL_TABLE",
                                "orgs": ["ORG1"]}]


def test_rollback_order_is_unpublish_then_unparameterize_then_delete():
    plan = build_apply_plan(_CLOSURE, _MATRIX, publish_orgs=["ORG1"])
    actions = [s["action"] for s in rollback_steps(plan["rollback"])]
    assert actions == ["unpublish", "unparameterize", "delete_variables"]


def test_rollback_skips_a_field_with_no_recorded_original():
    record = {"parameterized": [{"metadata_identifier": "g1", "field_name": "schemaName",
                                 "original_value": None}]}
    step = rollback_steps(record)[0]
    assert step["action"] == "skip"
    assert "no recorded original value" in step["reason"]


# ---------------------------------------------------------------------------
# Owner-org coverage — regression for a live-found bug
# ---------------------------------------------------------------------------

def test_owner_org_is_always_covered():
    # Live-found: parameterizing replaces the static db/schema with tokens, so if
    # the owner (Primary) org has no value the FQN collapses and the SOURCE object
    # breaks — Snowflake returns "Object 'T1_PUBLISH' does not exist". ThoughtSpot's
    # publish validation only checks TARGET orgs, so nothing else catches this.
    matrix = build_value_matrix([_cluster()], _ORGS, source="uniform", owner_org="Primary")
    assert {a["org"] for a in matrix["assignments"]} == {"Primary", "ORG1", "ORG2"}
    assert matrix["orgs"][0] == "Primary"


def test_owner_org_keeps_its_current_value_even_under_a_pattern():
    # A pattern must never repoint the source org: publishing should not change
    # what Primary reads.
    matrix = build_value_matrix([_cluster()], _ORGS, source="pattern",
                                patterns={"schemaName": "{ORG_UPPER}_X"}, owner_org="Primary")
    by_org = {a["org"]: a["value"] for a in matrix["assignments"]}
    assert by_org["Primary"] == "SALES"        # unchanged current value
    assert by_org["ORG1"] == "ORG1_X"


def test_owner_org_not_duplicated_when_already_requested():
    orgs = [{"name": "Primary", "id": 0}, {"name": "ORG1", "id": 11}]
    matrix = build_value_matrix([_cluster()], orgs, source="uniform", owner_org="Primary")
    assert matrix["orgs"] == ["Primary", "ORG1"]
    assert len([a for a in matrix["assignments"] if a["org"] == "Primary"]) == 1


def test_owner_org_counts_towards_coverage():
    matrix = build_value_matrix([_cluster()], _ORGS, source="uniform", owner_org="Primary")
    assert matrix["coverage"]["complete"] is True


# ---------------------------------------------------------------------------
# Root publish type — regression: apply published everything as LOGICAL_TABLE
# ---------------------------------------------------------------------------

from ts_cli.publish_plan import publish_type_for_root  # noqa: E402


@pytest.mark.parametrize("root_type,expected", [
    ("liveboard", "LIVEBOARD"),
    ("pinboard", "LIVEBOARD"),
    ("answer", "ANSWER"),
    ("model", "LOGICAL_TABLE"),
    ("worksheet", "LOGICAL_TABLE"),
    ("table", "LOGICAL_TABLE"),
    ("view", "LOGICAL_TABLE"),
    ("LIVEBOARD", "LIVEBOARD"),   # case-insensitive
    (None, "LOGICAL_TABLE"),      # unknown falls back to the data-layer type
])
def test_publish_type_for_root(root_type, expected):
    assert publish_type_for_root(root_type) == expected


def test_apply_plan_publishes_a_liveboard_as_liveboard():
    # Regression: the publish step reused object_type (LOGICAL_TABLE, correct for
    # the tables being parameterized) for the ROOT as well, so a Liveboard closure
    # was published with the wrong type.
    closure = {"root": {"guid": "lb-1", "name": "LB", "type": "liveboard"},
               "tables": _CLOSURE["tables"]}
    plan = build_apply_plan(closure, _MATRIX, publish_orgs=["ORG1"])
    assert [p["type"] for p in plan["publish"]] == ["LIVEBOARD"]
    # the tables underneath are still parameterized as logical tables
    assert plan["parameterize"][0]["metadata_type"] == "LOGICAL_TABLE"


def test_apply_plan_publishes_an_answer_as_answer():
    closure = {"root": {"guid": "a-1", "name": "A", "type": "answer"},
               "tables": _CLOSURE["tables"]}
    plan = build_apply_plan(closure, _MATRIX, publish_orgs=["ORG1"])
    assert [p["type"] for p in plan["publish"]] == ["ANSWER"]


def test_rollback_unpublishes_with_the_same_type():
    closure = {"root": {"guid": "lb-1", "type": "liveboard"}, "tables": _CLOSURE["tables"]}
    plan = build_apply_plan(closure, _MATRIX, publish_orgs=["ORG1"])
    unpublish = rollback_steps(plan["rollback"])[0]
    assert unpublish["action"] == "unpublish"
    assert unpublish["type"] == "LIVEBOARD"


# ---------------------------------------------------------------------------
# Multi-root closures — any anchor type, walk down always
# ---------------------------------------------------------------------------

from ts_cli.publish_plan import merge_closures, publish_targets  # noqa: E402


def _closure(guid, name, typ, tables):
    return {"root": {"guid": guid, "name": name, "type": typ}, "tables": tables,
            "owner_org": "Primary"}


_T_A = {"guid": "tA", "name": "A", "connection": "APJ", "fields": {
    "schemaName": {"value": "SALES", "variable": None}}}
_T_B = {"guid": "tB", "name": "B", "connection": "APJ", "fields": {
    "schemaName": {"value": "SALES", "variable": None}}}


def test_merge_closures_dedupes_shared_tables():
    # A Liveboard and an Answer on the same Model resolve the same Table. It must
    # appear once, or it would be parameterized twice.
    merged = merge_closures([_closure("lb", "LB", "liveboard", [_T_A]),
                             _closure("an", "AN", "answer", [_T_A])])
    assert [t["guid"] for t in merged["tables"]] == ["tA"]
    assert [r["guid"] for r in merged["roots"]] == ["lb", "an"]


def test_merge_closures_unions_distinct_tables():
    merged = merge_closures([_closure("lb", "LB", "liveboard", [_T_A]),
                             _closure("m", "M", "model", [_T_B])])
    assert sorted(t["guid"] for t in merged["tables"]) == ["tA", "tB"]


def test_merge_closures_clusters_across_all_roots():
    # Two roots sharing a schema value still need only ONE variable.
    merged = merge_closures([_closure("lb", "LB", "liveboard", [_T_A]),
                             _closure("m", "M", "model", [_T_B])])
    schema = [c for c in merged["clusters"] if c["field"] == "schemaName"]
    assert len(schema) == 1
    assert sorted(schema[0]["tables"]) == ["tA", "tB"]


def test_merge_closures_keeps_owner_org():
    merged = merge_closures([_closure("lb", "LB", "liveboard", [_T_A])])
    assert merged["owner_org"] == "Primary"


def test_merge_closures_rejects_an_empty_set():
    with pytest.raises(ValueError, match="at least one"):
        merge_closures([])


def test_publish_targets_derives_a_type_per_root():
    merged = merge_closures([_closure("lb", "LB", "liveboard", [_T_A]),
                             _closure("an", "AN", "answer", [_T_A]),
                             _closure("m", "M", "model", [_T_B])])
    assert publish_targets(merged) == [
        {"identifier": "lb", "type": "LIVEBOARD"},
        {"identifier": "an", "type": "ANSWER"},
        {"identifier": "m", "type": "LOGICAL_TABLE"},
    ]


def test_apply_plan_publishes_every_root_grouped_by_type():
    merged = merge_closures([_closure("lb", "LB", "liveboard", [_T_A]),
                             _closure("an", "AN", "answer", [_T_A])])
    matrix = {"orgs": ["ORG1"], "variables": [
        {"name": "apj_schema", "type": "TABLE_MAPPING", "field": "schemaName",
         "tables": ["tA"], "exists": False, "sensitive": False}],
        "assignments": [{"variable": "apj_schema", "org": "ORG1", "value": "X"}]}
    plan = build_apply_plan(merged, matrix, publish_orgs=["ORG1"])
    by_type = {p["type"]: p["identifiers"] for p in plan["publish"]}
    assert by_type == {"LIVEBOARD": ["lb"], "ANSWER": ["an"]}


def test_rollback_unpublishes_every_root():
    merged = merge_closures([_closure("lb", "LB", "liveboard", [_T_A]),
                             _closure("an", "AN", "answer", [_T_A])])
    matrix = {"orgs": ["ORG1"], "variables": [], "assignments": []}
    plan = build_apply_plan(merged, matrix, publish_orgs=["ORG1"])
    actions = [s for s in rollback_steps(plan["rollback"]) if s["action"] == "unpublish"]
    assert {a["type"] for a in actions} == {"LIVEBOARD", "ANSWER"}


# ---------------------------------------------------------------------------
# Manifest-driven selection (file / DB table), mirroring `ts alias --source db`
# ---------------------------------------------------------------------------

from ts_cli.publish_plan import parse_object_rows, parse_value_rows  # noqa: E402


def test_parse_object_rows_minimal():
    rows = [{"identifier": "guid-a"}, {"identifier": "guid-b"}]
    assert parse_object_rows(rows) == [
        {"identifier": "guid-a", "type": None, "with_dependents": False},
        {"identifier": "guid-b", "type": None, "with_dependents": False},
    ]


def test_parse_object_rows_reads_type_and_dependents():
    rows = [{"identifier": "g", "type": "liveboard", "with_dependents": "true"}]
    assert parse_object_rows(rows) == [
        {"identifier": "g", "type": "LIVEBOARD", "with_dependents": True}]


@pytest.mark.parametrize("raw,expected", [
    ("true", True), ("TRUE", True), ("yes", True), ("Y", True), ("1", True),
    ("false", False), ("no", False), ("0", False), ("", False), (None, False),
])
def test_parse_object_rows_truthiness(raw, expected):
    rows = [{"identifier": "g", "with_dependents": raw}]
    assert parse_object_rows(rows)[0]["with_dependents"] is expected


def test_parse_object_rows_is_case_insensitive_on_headers():
    # A DB cursor typically returns upper-case column names.
    rows = [{"IDENTIFIER": "g", "TYPE": "answer", "WITH_DEPENDENTS": "Y"}]
    assert parse_object_rows(rows) == [
        {"identifier": "g", "type": "ANSWER", "with_dependents": True}]


def test_parse_object_rows_dedupes_preserving_order():
    rows = [{"identifier": "b"}, {"identifier": "a"}, {"identifier": "b"}]
    assert [r["identifier"] for r in parse_object_rows(rows)] == ["b", "a"]


def test_parse_object_rows_rejects_a_row_with_no_identifier():
    with pytest.raises(ValueError, match="identifier"):
        parse_object_rows([{"type": "ANSWER"}])


def test_parse_value_rows_normalises_headers():
    rows = [{"ORG_NAME": "ORG1", "VARIABLE_NAME": "apj_schema", "VALUE": "A"}]
    assert parse_value_rows(rows) == [
        {"org_name": "ORG1", "variable_name": "apj_schema", "value": "A"}]


def test_parse_value_rows_skips_blank_rows():
    rows = [{"org_name": "", "variable_name": "", "value": ""},
            {"org_name": "ORG1", "variable_name": "v", "value": "x"}]
    assert len(parse_value_rows(rows)) == 1


def test_parse_value_rows_rejects_an_incomplete_row():
    with pytest.raises(ValueError, match="org_name"):
        parse_value_rows([{"variable_name": "v", "value": "x"}])
