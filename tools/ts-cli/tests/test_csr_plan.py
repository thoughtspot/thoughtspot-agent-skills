"""Unit tests for the pure CSR planning engine."""
from __future__ import annotations

import pytest

from ts_cli.csr_plan import (
    CSR_TABLE_DDL,
    OPERATIONS,
    build_csr_steps,
    build_csr_tml,
    build_update_payload,
    csr_tml_filename,
    diff_csr,
    explain_csr_error,
    normalise_fetch_response,
    parse_csr_tml_export,
    parse_rule_flags,
    parse_rule_rows,
)


def test_operations_are_the_three_api_verbs():
    assert OPERATIONS == ("ADD", "REMOVE", "REPLACE")


def test_ddl_names_the_manifest_table_and_keys_all_four_columns():
    assert "TS_COLUMN_SECURITY_RULES" in CSR_TABLE_DDL
    assert "PRIMARY KEY (org_name, table_name, column_name, group_name)" in CSR_TABLE_DDL
    # group_name carries the empty-string sentinel, so it cannot be nullable: a
    # nullable column cannot sit in a primary key.
    assert "group_name   VARCHAR NOT NULL" in CSR_TABLE_DDL


def test_parse_rule_flags_single_column_single_group():
    assert parse_rule_flags(["PROD_NM=Analyst"]) == {"PROD_NM": ["Analyst"]}


def test_parse_rule_flags_multiple_groups_and_whitespace():
    assert parse_rule_flags([" PROD_NM = Analyst , Finance "]) == {
        "PROD_NM": ["Analyst", "Finance"]}


def test_parse_rule_flags_empty_group_list_means_secured_for_nobody():
    assert parse_rule_flags(["COST="]) == {"COST": []}


def test_parse_rule_flags_dedupes_groups_preserving_order():
    assert parse_rule_flags(["COST=A,B,A"]) == {"COST": ["A", "B"]}


def test_parse_rule_flags_merges_repeated_flags_for_one_column():
    assert parse_rule_flags(["COST=A", "COST=B"]) == {"COST": ["A", "B"]}


def test_parse_rule_flags_rejects_missing_equals():
    with pytest.raises(ValueError, match="COL=GROUP"):
        parse_rule_flags(["PROD_NM"])


def test_parse_rule_flags_rejects_empty_column_name():
    with pytest.raises(ValueError, match="column name"):
        parse_rule_flags(["=Analyst"])


def test_parse_rule_rows_normalises_and_keeps_identifier_casing():
    rows = [{"ORG_NAME": "ORG1", "TABLE_NAME": "T2_PUBLISH",
             "COLUMN_NAME": "Prod_Nm", "GROUP_NAME": "Analyst"}]
    assert parse_rule_rows(rows) == [
        {"org_name": "ORG1", "table_name": "T2_PUBLISH",
         "column_name": "Prod_Nm", "group_name": "Analyst"}]


def test_parse_rule_rows_allows_blank_group_as_the_no_access_sentinel():
    rows = [{"org_name": "ORG1", "table_name": "T2", "column_name": "COST",
             "group_name": ""}]
    assert parse_rule_rows(rows) == [
        {"org_name": "ORG1", "table_name": "T2", "column_name": "COST",
         "group_name": ""}]


def test_parse_rule_rows_skips_fully_blank_rows():
    rows = [{"org_name": "", "table_name": "", "column_name": "", "group_name": ""}]
    assert parse_rule_rows(rows) == []


def test_parse_rule_rows_refuses_a_partially_filled_row():
    rows = [{"org_name": "ORG1", "table_name": "", "column_name": "COST",
             "group_name": "Analyst"}]
    with pytest.raises(ValueError, match="table_name"):
        parse_rule_rows(rows)


def test_parse_rule_rows_refuses_a_row_with_no_column_name():
    # CSR declares restricted COLUMNS. A row without one has nothing to restrict,
    # and silently dropping it would leave a column unprotected with no trace.
    rows = [{"org_name": "ORG1", "table_name": "T2", "column_name": "",
             "group_name": "Analyst"}]
    with pytest.raises(ValueError, match="column_name"):
        parse_rule_rows(rows)


def test_parse_rule_rows_dedupes_identical_rows():
    row = {"org_name": "ORG1", "table_name": "T2", "column_name": "COST",
           "group_name": "Analyst"}
    assert parse_rule_rows([dict(row), dict(row)]) == [row]


def test_payload_replace_is_the_default_operation():
    payload = build_update_payload("T2_PUBLISH", {"PROD_NM": ["Analyst"]})
    assert payload == {
        "identifier": "T2_PUBLISH",
        "clear_csr": False,
        "column_security_rules": [
            {"column_identifier": "PROD_NM", "is_unsecured": False,
             "group_access": [{"operation": "REPLACE",
                               "group_identifiers": ["Analyst"]}]}],
    }


def test_payload_honours_add_and_remove():
    for operation in ("ADD", "REMOVE"):
        payload = build_update_payload("T2", {"COST": ["Finance"]}, operation=operation)
        access = payload["column_security_rules"][0]["group_access"][0]
        assert access["operation"] == operation


def test_payload_rejects_an_unknown_operation():
    with pytest.raises(ValueError, match="ADD, REMOVE, REPLACE"):
        build_update_payload("T2", {"COST": ["Finance"]}, operation="UPSERT")


def test_payload_for_a_column_secured_for_nobody_keeps_an_empty_group_list():
    payload = build_update_payload("T2", {"COST": []})
    access = payload["column_security_rules"][0]["group_access"][0]
    assert access == {"operation": "REPLACE", "group_identifiers": []}


def test_clear_always_ships_the_required_empty_array():
    # `column_security_rules` is a REQUIRED field, which is why `clear_csr: true`
    # alone is rejected. Emitting both is the whole point of this branch.
    assert build_update_payload("T2", {}, clear=True) == {
        "identifier": "T2", "clear_csr": True, "column_security_rules": []}


def test_clear_refuses_to_be_combined_with_rules():
    with pytest.raises(ValueError, match="clear"):
        build_update_payload("T2", {"COST": ["Finance"]}, clear=True)


def test_unsecure_emits_is_unsecured_without_group_access():
    payload = build_update_payload("T2", {}, unsecure=["COST"])
    assert payload["column_security_rules"] == [
        {"column_identifier": "COST", "is_unsecured": True}]


def test_payload_requires_something_to_do():
    with pytest.raises(ValueError, match="nothing to do"):
        build_update_payload("T2", {})


def test_payload_sorts_columns_so_a_dry_run_is_diffable():
    payload = build_update_payload("T2", {"ZED": ["A"], "ALPHA": ["B"]})
    names = [r["column_identifier"] for r in payload["column_security_rules"]]
    assert names == ["ALPHA", "ZED"]


def test_payload_refuses_an_empty_table_identifier():
    with pytest.raises(ValueError, match="table"):
        build_update_payload("", {"COST": ["Finance"]})


def _rows(*triples):
    return [{"org_name": o, "table_name": t, "column_name": c, "group_name": g}
            for o, t, c, g in triples]


def test_steps_group_rows_by_org_and_table():
    rows = _rows(("ORG1", "T2", "COST", "Finance"),
                 ("ORG1", "T2", "PROD_NM", "Analyst"),
                 ("ORG2", "T2", "COST", "Finance"))
    steps = build_csr_steps(rows)
    assert [(s["org_name"], s["table_name"]) for s in steps] == [
        ("ORG1", "T2"), ("ORG2", "T2")]
    assert steps[0]["rules"] == {"COST": ["Finance"], "PROD_NM": ["Analyst"]}


def test_steps_collect_several_groups_onto_one_column():
    rows = _rows(("ORG1", "T2", "COST", "Finance"), ("ORG1", "T2", "COST", "Audit"))
    assert build_csr_steps(rows)[0]["rules"] == {"COST": ["Audit", "Finance"]}


def test_steps_drop_the_blank_group_sentinel_from_the_group_list():
    # A blank group_name means "secured, nobody". It is the ABSENCE of groups, so it
    # must never travel as a literal "" group identifier the platform would reject.
    rows = _rows(("ORG1", "T2", "COST", ""))
    assert build_csr_steps(rows)[0]["rules"] == {"COST": []}


def test_steps_are_sorted_for_a_stable_plan():
    rows = _rows(("ORG2", "T9", "A", "G"), ("ORG1", "T1", "A", "G"))
    steps = build_csr_steps(rows)
    assert [s["org_name"] for s in steps] == ["ORG1", "ORG2"]


def test_steps_prefer_the_guid_as_the_table_identifier_when_known():
    rows = _rows(("ORG1", "T2", "COST", "Finance"))
    tables = [{"org_name": "ORG1", "table_name": "T2", "table_guid": "guid-1",
               "published": False, "secured_columns": []}]
    step = build_csr_steps(rows, tables)[0]
    assert step["table_identifier"] == "guid-1"
    assert step["table_name"] == "T2"


def test_steps_fall_back_to_the_name_when_no_guid_was_resolved():
    rows = _rows(("ORG1", "T2", "COST", "Finance"))
    assert build_csr_steps(rows)[0]["table_identifier"] == "T2"


def test_a_published_table_is_marked_blocked():
    rows = _rows(("ORG1", "T2", "COST", "Finance"))
    tables = [{"org_name": "ORG1", "table_name": "T2", "table_guid": "guid-1",
               "published": True, "secured_columns": []}]
    step = build_csr_steps(rows, tables)[0]
    assert step["blocked"].startswith("CSR_BLOCKED")
    assert "published" in step["blocked"]


def test_an_unpublished_table_is_not_blocked():
    rows = _rows(("ORG1", "T2", "COST", "Finance"))
    tables = [{"org_name": "ORG1", "table_name": "T2", "table_guid": "guid-1",
               "published": False, "secured_columns": []}]
    assert build_csr_steps(rows, tables)[0]["blocked"] == ""


def test_a_table_whose_publication_state_is_unknown_is_blocked():
    # An unreadable gate must not degrade to an open one: only a successful read supports
    # the claim that a table is unpublished.
    rows = _rows(("ORG1", "T2", "COST", "Finance"))
    tables = [{"org_name": "ORG1", "table_name": "T2", "table_guid": "guid-1",
               "published": False, "publication_known": False, "secured_columns": []}]
    step = build_csr_steps(rows, tables)[0]
    assert step["blocked"].startswith("CSR_BLOCKED")
    assert "could not be determined" in step["blocked"]


def test_publication_is_taken_as_known_when_the_caller_says_nothing_about_it():
    # `set` and the pure tests build steps without a resolution pass, so the key's
    # absence must not block.
    rows = _rows(("ORG1", "T2", "COST", "Finance"))
    assert build_csr_steps(rows)[0]["blocked"] == ""


def test_build_csr_steps_refuses_an_unknown_operation():
    # The only validation of `resolve --operation`, and untested until now.
    rows = _rows(("ORG1", "T2", "COST", "Finance"))
    with pytest.raises(ValueError, match="UPSERT"):
        build_csr_steps(rows, operation="UPSERT")


def test_build_csr_steps_names_the_three_valid_operations_when_it_refuses():
    rows = _rows(("ORG1", "T2", "COST", "Finance"))
    with pytest.raises(ValueError, match="ADD, REMOVE, REPLACE"):
        build_csr_steps(rows, operation="replace")


def test_prune_unsecures_only_columns_absent_from_the_manifest():
    rows = _rows(("ORG1", "T2", "COST", "Finance"))
    tables = [{"org_name": "ORG1", "table_name": "T2", "table_guid": "g",
               "published": False, "secured_columns": ["COST", "SALARY", "SSN"]}]
    step = build_csr_steps(rows, tables, prune=True)[0]
    assert step["unsecure"] == ["SALARY", "SSN"]


def test_without_prune_nothing_is_unsecured_however_stale():
    rows = _rows(("ORG1", "T2", "COST", "Finance"))
    tables = [{"org_name": "ORG1", "table_name": "T2", "table_guid": "g",
               "published": False, "secured_columns": ["COST", "SALARY"]}]
    assert build_csr_steps(rows, tables, prune=True) != build_csr_steps(rows, tables)
    assert build_csr_steps(rows, tables)[0]["unsecure"] == []


def test_steps_carry_the_operation_through():
    rows = _rows(("ORG1", "T2", "COST", "Finance"))
    assert build_csr_steps(rows, operation="ADD")[0]["operation"] == "ADD"


# The prose example in the API docs shows a `data` envelope with camelCase keys; the
# response schema shows a bare array with snake_case keys. Both are parsed, because
# which one a given build returns is not knowable from the spec.

_SNAKE = [{
    "table_guid": "tg-1", "obj_id": "oid-1",
    "column_security_rules": [
        {"column": {"id": "c1", "name": "SALARY"},
         "groups": [{"id": "g1", "name": "HR"}, {"id": "g2", "name": "Finance"}],
         "source_table_details": {"id": "st-1", "name": "EMPLOYEE"}}]}]

_CAMEL = {"data": [{
    "guid": "tg-1", "objId": "oid-1",
    "columnSecurityRules": [
        {"column": {"id": "c1", "name": "SALARY"},
         "groups": [{"id": "g1", "name": "HR"}, {"id": "g2", "name": "Finance"}],
         "sourceTableDetails": {"id": "st-1", "name": "EMPLOYEE"}}]}]}


def test_normalise_parses_the_snake_case_bare_array():
    assert normalise_fetch_response(_SNAKE) == [
        {"table_guid": "tg-1", "obj_id": "oid-1", "column_id": "c1",
         "column_name": "SALARY", "group_names": ["Finance", "HR"],
         "source_table_name": "EMPLOYEE"}]


def test_normalise_parses_the_camel_case_data_envelope_identically():
    assert normalise_fetch_response(_CAMEL) == normalise_fetch_response(_SNAKE)


def test_normalise_sorts_group_names_so_a_diff_is_not_order_sensitive():
    assert normalise_fetch_response(_SNAKE)[0]["group_names"] == ["Finance", "HR"]


def test_normalise_tolerates_a_table_with_no_rules():
    assert normalise_fetch_response([{"table_guid": "tg-1"}]) == []


def test_normalise_tolerates_null_groups():
    data = [{"table_guid": "tg", "column_security_rules": [
        {"column": {"id": "c", "name": "COST"}, "groups": None}]}]
    assert normalise_fetch_response(data)[0]["group_names"] == []


def test_normalise_tolerates_junk():
    assert normalise_fetch_response(None) == []
    assert normalise_fetch_response({}) == []
    assert normalise_fetch_response("nonsense") == []


def _row(name, groups):
    return {"table_guid": "tg", "obj_id": "", "column_id": "c",
            "column_name": name, "group_names": groups, "source_table_name": ""}


def test_diff_reports_an_added_rule():
    diff = diff_csr([], [_row("SALARY", ["HR"])])
    assert diff["added"] == [_row("SALARY", ["HR"])]
    assert diff["removed"] == [] and diff["changed"] == []


def test_diff_reports_a_removed_rule():
    diff = diff_csr([_row("SALARY", ["HR"])], [])
    assert diff["removed"] == [_row("SALARY", ["HR"])]


def test_diff_reports_a_changed_group_list():
    diff = diff_csr([_row("SALARY", ["HR"])], [_row("SALARY", ["HR", "Finance"])])
    assert diff["changed"] == [
        {"table_guid": "tg", "column_name": "SALARY",
         "before_groups": ["HR"], "after_groups": ["HR", "Finance"]}]


def test_diff_of_an_unchanged_state_is_empty_everywhere():
    rows = [_row("SALARY", ["HR"])]
    assert diff_csr(rows, list(rows)) == {"added": [], "removed": [], "changed": []}


def test_explain_translates_the_feature_flag_403():
    body = '{"error":{"code":10023,"message":"Column Security rule feature is disabled"}}'
    message = explain_csr_error(body, 403)
    assert "feature-flagged" in message
    assert "10.12" in message
    assert "permission" not in message.lower()


def test_explain_translates_a_403_without_10023_as_a_permissions_problem():
    message = explain_csr_error('{"error":{"message":"Forbidden"}}', 403)
    assert "DATAMANAGEMENT" in message


def test_explain_translates_the_access_form_of_code_10023():
    # Live-verified 2026-07-27: reading CSR from a target Org returned this exact
    # shape on a cluster where the feature is demonstrably ON (an owning-Org CSR
    # update had just succeeded). Code 10023 here means an access failure, not the
    # feature flag -- the same bare number, a completely different problem.
    body = ('{"error":{"message":{"debug":{"code":10023,"type":"...",'
           '"debug":"[\\"User does not have access to rea[d]...\\"]"}}}}')
    message = explain_csr_error(body, 500)
    assert message is not None
    assert "access" in message.lower()
    assert "feature-flagged" not in message
    assert "per-Org" in message


def test_explain_10023_feature_flag_and_access_forms_do_not_bleed_into_each_other():
    feature = explain_csr_error(
        '{"error":{"code":10023,"message":"Column Security rule feature is disabled"}}',
        403)
    access = explain_csr_error(
        '{"error":{"code":10023,"debug":"User does not have access to read"}}', 500)
    assert feature != access
    # Distinct, unique markers rather than the word "access" alone: the feature-flag
    # message legitimately says "not an access-control problem", so a bare substring
    # check on "access" would pass even if the two messages bled into each other.
    assert "feature-flagged" in feature and "feature-flagged" not in access
    assert "10.12" in feature and "10.12" not in access
    assert "per-Org" in access and "per-Org" not in feature
    assert "lacks access" in access and "lacks access" not in feature


def test_explain_returns_none_for_a_bare_code_10023_with_no_disambiguating_text():
    # Code 10023 is overloaded (feature flag vs access failure); with neither the
    # disabled-form nor the access-form text present, this must not guess either way.
    # status_code=500 (not 403) so the unrelated generic-403 fallback doesn't fire.
    assert explain_csr_error('{"error":{"code":10023}}', 500) is None


def test_explain_translates_the_missing_table_reference():
    # A genuinely EMPTY name -- the doubled space is the empty interpolation. The
    # document really is missing its `table:` reference.
    body = 'Error Code: 14502 Referenced table with name  not found'
    message = explain_csr_error(body, 400)
    assert "table:" in message
    assert "T2_PUBLISH" not in message


def test_explain_distinguishes_a_named_but_absent_table_from_a_missing_reference():
    # Live-verified 2026-07-27: this exact body comes from importing a CSR document
    # into an Org that does not have T2_PUBLISH -- the `table:` reference is fine, the
    # table just is not there. Sending the operator to edit `table:` would be wrong.
    body = ('[{"response": {"status": {"error_message": "Referenced table with name '
           'T2_PUBLISH not found.", "status_code": "ERROR", "error_code": 14502}}, '
           '"request_index": 0}]')
    message = explain_csr_error(body, 400)
    assert "T2_PUBLISH" in message
    assert "portable" in message
    # Must not bleed into the empty-reference wording.
    assert "missing its `table:` reference" not in message


def test_explain_named_and_empty_table_messages_do_not_bleed_into_each_other():
    empty = explain_csr_error(
        'Error Code: 14502 Referenced table with name  not found', 400)
    named = explain_csr_error(
        'Error Code: 14502 Referenced table with name T3 not found.', 400)
    assert empty != named
    assert "T3" in named and "T3" not in empty
    assert "missing its `table:` reference" in empty
    assert "missing its `table:` reference" not in named


def test_explain_translates_unsecuring_a_never_secured_column():
    # Live-verified 2026-07-27: `is_unsecured: true` on a column with no rule today is
    # a genuine HTTP 400, not a harmless no-op. Body is the raw response text, quoted
    # verbatim from observation.
    body = ('{"error":{"message":{"debug":{"code":10002,"debug":"[\\"Column '
            '\'PROD_CAT_L1\' is not secured, cannot mark as unsecured\\"]"}}}}')
    message = explain_csr_error(body, 400)
    assert message is not None
    assert "PROD_CAT_L1" in message
    assert "resolve" in message
    assert "--prune" in message


def test_explain_translates_a_clear_csr_rejection():
    body = "column_security_rules is required"
    assert "clear_csr" in explain_csr_error(body, 400)


def test_explain_does_not_match_the_feature_flag_code_inside_a_longer_number():
    # `10023` unanchored also matches inside `1002345`, which would explain an unrelated
    # failure as the feature flag -- a confident paraphrase of something unrecognised,
    # which is exactly what the None contract exists to avoid.
    assert explain_csr_error('{"error":{"code":1002345,"message":"nope"}}', 500) is None


def test_explain_does_not_match_the_missing_table_code_inside_a_longer_number():
    assert explain_csr_error('{"error":{"code":145021,"message":"nope"}}', 400) is None


def test_explain_still_matches_the_codes_as_they_really_appear():
    # Word-anchoring must not break the real forms: punctuation is a word boundary.
    # (10023 alone, with neither disambiguating text, is intentionally None -- see
    # test_explain_returns_none_for_a_bare_code_10023_with_no_disambiguating_text --
    # so the word-boundary check for 10023 rides along with the access-form test.)
    assert "access" in explain_csr_error(
        '{"error":{"code":10023,"debug":"does not have access"}}', 500).lower()
    assert "table:" in explain_csr_error("Error Code: 14502, import failed", 400)


def test_explain_returns_none_for_an_unrecognised_body():
    # None means the caller surfaces the raw error, rather than a confident paraphrase
    # of something we do not actually recognise.
    assert explain_csr_error("some new failure nobody has seen", 500) is None


def test_explain_tolerates_an_empty_body():
    assert explain_csr_error("", None) is None


def test_filename_matches_the_platform_export_name():
    assert csr_tml_filename("T2_PUBLISH") == "T2_PUBLISH_CSR.column_security_rules.tml"


def test_tml_carries_the_mandatory_table_reference():
    # Omitting `table:` fails the import with code 14502 and a message naming an empty
    # table. It is the single most load-bearing field in the document.
    doc = build_csr_tml("T2_PUBLISH", {"PROD_NM": ["Analyst"]})
    assert doc["column_security_rules"]["table"] == {"name": "T2_PUBLISH"}


def test_tml_declares_only_restricted_columns_with_their_groups():
    doc = build_csr_tml("T2", {"PROD_NM": ["Analyst", "Finance"]})
    assert doc["column_security_rules"]["rules"] == [
        {"column_name": "PROD_NM",
         "accessible_groups": {"group_name": ["Analyst", "Finance"]}}]


def test_tml_sorts_rules_and_groups_for_a_stable_document():
    doc = build_csr_tml("T2", {"ZED": ["B", "A"], "ALPHA": ["C"]})
    rules = doc["column_security_rules"]["rules"]
    assert [r["column_name"] for r in rules] == ["ALPHA", "ZED"]
    assert rules[1]["accessible_groups"]["group_name"] == ["A", "B"]


def test_tml_for_a_column_secured_for_nobody_has_an_empty_group_list():
    doc = build_csr_tml("T2", {"COST": []})
    assert doc["column_security_rules"]["rules"][0]["accessible_groups"] == {
        "group_name": []}


def test_tml_omits_guid_unless_given():
    # `guid:` at the document root is what makes an import an in-place update. Omitting
    # it on a first import is deliberate; including a stale one is an error.
    assert "guid" not in build_csr_tml("T2", {"COST": ["A"]})
    assert build_csr_tml("T2", {"COST": ["A"]}, guid="g-1")["guid"] == "g-1"


def test_tml_refuses_an_empty_table_name():
    with pytest.raises(ValueError, match="table"):
        build_csr_tml("", {"COST": ["A"]})


def test_parse_export_pulls_the_csr_document_out_of_a_tml_export_response():
    edocs = [
        {"info": {"type": "logical_table", "name": "T2"}, "edoc": "table:\n  name: T2\n"},
        {"info": {"type": "column_security_rules", "name": "T2_CSR", "id": "g-9"},
         "edoc": ("column_security_rules:\n"
                  "  table:\n    name: T2\n"
                  "  rules:\n"
                  "  - column_name: PROD_NM\n"
                  "    accessible_groups:\n      group_name:\n      - Analyst\n")},
    ]
    parsed = parse_csr_tml_export(edocs)
    assert len(parsed) == 1
    assert parsed[0]["table_name"] == "T2"
    assert parsed[0]["rules"] == {"PROD_NM": ["Analyst"]}
    assert parsed[0]["guid"] == "g-9"
    assert "column_security_rules" in parsed[0]["yaml"]


def test_parse_export_returns_empty_when_no_csr_document_came_back():
    # The export flag is Beta. A cluster without it returns the table and nothing else,
    # and that must read as "no CSR here", not as a crash.
    edocs = [{"info": {"type": "logical_table"}, "edoc": "table:\n  name: T2\n"}]
    assert parse_csr_tml_export(edocs) == []


def test_parse_export_tolerates_junk():
    assert parse_csr_tml_export(None) == []
    assert parse_csr_tml_export([{"info": None, "edoc": None}]) == []
