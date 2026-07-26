"""Smoke test for the ts-publish-orgs skill.

Exercises the pure-function pipeline end to end: exported closures → merge →
cluster → value matrix → apply plan → rollback steps. No live ThoughtSpot or
Snowflake connection required.

The assertions encode behaviour that was verified live and that the published
ThoughtSpot documentation gets wrong or leaves unsaid, so a regression here means
the skill would produce a plan that breaks something.
"""
from ts_cli.publish_plan import (
    build_apply_plan,
    build_clusters,
    build_value_matrix,
    extract_table_fields,
    merge_closures,
    parse_object_rows,
    parse_value_rows,
    publish_targets,
    rollback_steps,
    selectable_clusters,
)


def _table(name, guid, schema="ALIAS_TESTS", connection="APJ"):
    return {"guid": guid, "table": {"name": name, "db": "AGENT_SKILLS", "schema": schema,
                                    "db_table": name, "connection": {"name": connection}}}


def _closure(guid, name, typ, tables):
    return {"root": {"guid": guid, "name": name, "type": typ},
            "tables": [extract_table_fields(t) for t in tables],
            "owner_org": "Primary"}


def test_full_pipeline_liveboard_and_answer_to_plan():
    """A Liveboard and an Answer on one Model: the realistic publish job."""
    tables = [_table("T1_PUBLISH", "t1"), _table("T2_PUBLISH", "t2")]
    merged = merge_closures([
        _closure("lb", "T1_LIVEBOARD", "liveboard", tables),
        _closure("an", "T1_SAVED_ANSWER", "answer", tables),
    ])

    # Tables shared by both roots appear once, or they would be parameterized twice.
    assert sorted(t["guid"] for t in merged["tables"]) == ["t1", "t2"]

    # Both tables share a schema, so ONE variable serves both. A variable holds one
    # value per scope, so the unit of parameterization is the distinct value.
    schema = [c for c in merged["clusters"] if c["field"] == "schemaName"]
    assert len(schema) == 1
    assert sorted(schema[0]["tables"]) == ["t1", "t2"]

    clusters = selectable_clusters(merged["clusters"])
    assert {c["field"] for c in clusters} == {"databaseName", "schemaName"}

    orgs = [{"name": "ORG1", "id": 11}, {"name": "ORG2", "id": 22}]
    matrix = build_value_matrix(clusters, orgs, source="pattern",
                                patterns={"schemaName": "{ORG_UPPER}_SALES"},
                                owner_org=merged["owner_org"])

    # The owner Org is always covered, and always at its CURRENT value: parameterizing
    # without it breaks the source object, and a pattern there would repoint Primary.
    by_org = {(a["variable"], a["org"]): a["value"] for a in matrix["assignments"]}
    assert by_org[("apj_schema", "Primary")] == "ALIAS_TESTS"
    assert by_org[("apj_schema", "ORG1")] == "ORG1_SALES"
    assert matrix["coverage"]["complete"] is True

    plan = build_apply_plan(merged, matrix, publish_orgs=["ORG1", "ORG2"])

    # Each root publishes under its own type, one call per type.
    assert {p["type"] for p in plan["publish"]} == {"LIVEBOARD", "ANSWER"}

    # Rollback records every field's ORIGINAL value: unparameterize substitutes a
    # value rather than clearing the field, so without it there is no way back.
    originals = {(r["metadata_identifier"], r["field_name"]): r["original_value"]
                 for r in plan["rollback"]["parameterized"]}
    assert originals[("t1", "schemaName")] == "ALIAS_TESTS"
    assert originals[("t1", "databaseName")] == "AGENT_SKILLS"

    # Undo order: unpublish first, then restore values, then delete variables.
    actions = [s["action"] for s in rollback_steps(plan["rollback"])]
    assert actions[0] == "unpublish"
    assert actions[-1] == "delete_variables"
    assert "unparameterize" in actions


def test_falcon_backed_tables_are_never_selectable():
    """A Table with no connection cannot be parameterized; proposing one is a dead end."""
    merged = merge_closures([_closure("m", "M", "model", [_table("F", "f", connection=None)])])
    assert all(c["parameterizable"] is False for c in merged["clusters"])
    assert selectable_clusters(merged["clusters"], fields=["schemaName"]) == []


def test_coverage_gap_is_reported_not_silently_dropped():
    """Publishing fails closed on a gap, so the plan must surface it first."""
    clusters = build_clusters([extract_table_fields(_table("T", "t"))])
    orgs = [{"name": "ORG1", "id": 11}, {"name": "ORG2", "id": 22}]
    rows = [{"org_name": "ORG1", "variable_name": "apj_schema", "value": "A"}]
    matrix = build_value_matrix(selectable_clusters(clusters), orgs,
                                source="file", csv_rows=rows)
    assert matrix["coverage"]["complete"] is False
    assert {"variable": "apj_schema", "org": "ORG2"} in matrix["coverage"]["missing"]


def test_manifest_parsing_round_trip():
    """CSV and DB rows reach the planner in one shape, whatever the header case."""
    objects = parse_object_rows([
        {"IDENTIFIER": "guid-a", "TYPE": "liveboard", "WITH_DEPENDENTS": "true"},
        {"identifier": "guid-b"},
        {"identifier": "guid-a"},  # duplicate, dropped
    ])
    assert objects == [
        {"identifier": "guid-a", "type": "LIVEBOARD", "with_dependents": True},
        {"identifier": "guid-b", "type": None, "with_dependents": False},
    ]

    values = parse_value_rows([
        {"ORG_NAME": "ORG1", "VARIABLE_NAME": "apj_schema", "VALUE": "TENANT_A"},
        {"org_name": "", "variable_name": "", "value": ""},  # blank line, skipped
    ])
    assert values == [{"org_name": "ORG1", "variable_name": "apj_schema",
                       "value": "TENANT_A"}]


def test_publish_targets_cover_every_root_type():
    merged = merge_closures([
        _closure("lb", "LB", "liveboard", [_table("T", "t")]),
        _closure("an", "AN", "answer", [_table("T", "t")]),
        _closure("m", "M", "model", [_table("T", "t")]),
    ])
    assert publish_targets(merged) == [
        {"identifier": "lb", "type": "LIVEBOARD"},
        {"identifier": "an", "type": "ANSWER"},
        {"identifier": "m", "type": "LOGICAL_TABLE"},
    ]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  PASS  {name}")
    print("\nAll ts-publish-orgs smoke tests passed.")
