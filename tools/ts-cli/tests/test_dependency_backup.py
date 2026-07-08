"""Unit tests for ts_cli.dependency.backup — pure helpers behind
`ts dependency backup`/`rollback` (BL-083 PR1). No I/O; no live connection needed.
"""
from __future__ import annotations

from ts_cli.dependency.backup import (
    DELETE_ORDER,
    V2_TYPE_MAP,
    backup_filename,
    build_manifest,
    delete_sort_key,
    restore_policy_for,
    rollback_order,
    rollback_sort_key,
)


# ---------------------------------------------------------------------------
# backup_filename
# ---------------------------------------------------------------------------

class TestBackupFilename:
    def test_basic_shape(self):
        assert backup_filename("model", "abc-123", "Orders Model") == "model_abc-123_Orders Model.json"

    def test_replaces_forward_slash(self):
        result = backup_filename("answer", "guid-1", "Revenue / Cost")
        assert "/" not in result
        assert result == "answer_guid-1_Revenue _ Cost.json"

    def test_replaces_backslash(self):
        result = backup_filename("answer", "guid-1", "Path\\To\\Thing")
        assert "\\" not in result

    def test_truncates_to_60_chars(self):
        long_name = "X" * 100
        result = backup_filename("table", "guid-1", long_name)
        # filename = f"{type}_{guid}_{safe[:60]}.json"
        safe_part = result[len("table_guid-1_"):-len(".json")]
        assert len(safe_part) == 60

    def test_short_name_not_padded(self):
        result = backup_filename("view", "guid-1", "Short")
        assert result == "view_guid-1_Short.json"


# ---------------------------------------------------------------------------
# DELETE_ORDER / delete_sort_key
# ---------------------------------------------------------------------------

class TestDeleteOrder:
    def test_liveboard_first(self):
        assert DELETE_ORDER["LIVEBOARD"] == 0

    def test_table_last(self):
        assert DELETE_ORDER["TABLE"] == 5

    def test_set_and_cohort_share_rank(self):
        assert DELETE_ORDER["SET"] == DELETE_ORDER["COHORT"] == 2

    def test_model_and_worksheet_share_rank(self):
        assert DELETE_ORDER["MODEL"] == DELETE_ORDER["WORKSHEET"] == 4

    def test_sort_order_end_to_end(self):
        objs = [
            {"type": "TABLE", "name": "t"},
            {"type": "LIVEBOARD", "name": "lb"},
            {"type": "ANSWER", "name": "a"},
            {"type": "MODEL", "name": "m"},
            {"type": "SET", "name": "s"},
            {"type": "VIEW", "name": "v"},
        ]
        ordered = sorted(objs, key=delete_sort_key)
        assert [o["type"] for o in ordered] == ["LIVEBOARD", "ANSWER", "SET", "VIEW", "MODEL", "TABLE"]

    def test_unknown_type_sorts_last(self):
        objs = [{"type": "TABLE"}, {"type": "SOME_UNKNOWN_TYPE"}]
        ordered = sorted(objs, key=delete_sort_key)
        assert ordered[-1]["type"] == "SOME_UNKNOWN_TYPE"

    def test_case_insensitive(self):
        assert delete_sort_key({"type": "liveboard"}) == DELETE_ORDER["LIVEBOARD"]


# ---------------------------------------------------------------------------
# V2_TYPE_MAP
# ---------------------------------------------------------------------------

class TestV2TypeMap:
    def test_answer_and_liveboard_map_to_self(self):
        assert V2_TYPE_MAP["ANSWER"] == "ANSWER"
        assert V2_TYPE_MAP["LIVEBOARD"] == "LIVEBOARD"

    def test_model_worksheet_view_table_map_to_logical_table(self):
        for t in ("MODEL", "WORKSHEET", "VIEW", "TABLE"):
            assert V2_TYPE_MAP[t] == "LOGICAL_TABLE"

    def test_set_and_cohort_map_to_logical_column(self):
        assert V2_TYPE_MAP["SET"] == "LOGICAL_COLUMN"
        assert V2_TYPE_MAP["COHORT"] == "LOGICAL_COLUMN"

    def test_covers_every_delete_order_type(self):
        # Every type that can be deleted must have a v2 type mapping.
        assert set(DELETE_ORDER.keys()) <= set(V2_TYPE_MAP.keys())


# ---------------------------------------------------------------------------
# restore_policy_for
# ---------------------------------------------------------------------------

class TestRestorePolicyFor:
    def test_table_is_partial(self):
        assert restore_policy_for("table") == "PARTIAL"

    def test_table_case_insensitive(self):
        assert restore_policy_for("TABLE") == "PARTIAL"

    def test_model_is_all_or_none(self):
        assert restore_policy_for("model") == "ALL_OR_NONE"

    def test_answer_is_all_or_none(self):
        assert restore_policy_for("answer") == "ALL_OR_NONE"

    def test_liveboard_is_all_or_none(self):
        assert restore_policy_for("liveboard") == "ALL_OR_NONE"

    def test_unknown_type_defaults_all_or_none(self):
        assert restore_policy_for("worksheet") == "ALL_OR_NONE"
        assert restore_policy_for("view") == "ALL_OR_NONE"
        assert restore_policy_for("something_else") == "ALL_OR_NONE"


# ---------------------------------------------------------------------------
# rollback_sort_key / rollback_order
# ---------------------------------------------------------------------------

class TestRollbackOrder:
    def test_sort_key_is_delete_order_rank(self):
        # Root-first restore: rank == DELETE_ORDER, sorted descending in rollback_order.
        assert rollback_sort_key({"type": "table"}) == 5
        assert rollback_sort_key({"type": "model"}) == 4
        assert rollback_sort_key({"type": "answer"}) == 1
        assert rollback_sort_key({"type": "liveboard"}) == 0
        assert rollback_sort_key({"type": "mystery"}) == -1  # unknown restores last

    def test_source_table_restored_before_dependents(self):
        entries = [
            {"type": "answer", "name": "dependent_answer"},
            {"type": "model", "name": "dependent_model"},
            {"type": "table", "name": "source_table"},
        ]
        ordered = [e["name"] for e in rollback_order(entries)]
        # Root-first: table before model before answer (a dependent can only be
        # restored once the object it references exists again — open-items #25).
        assert ordered[0] == "source_table"
        assert ordered.index("dependent_model") < ordered.index("dependent_answer")

    def test_stable_within_a_tier(self):
        entries = [{"type": "table", "name": "a"}, {"type": "table", "name": "b"}]
        ordered = rollback_order(entries)
        assert [e["name"] for e in ordered] == ["a", "b"]  # manifest order preserved

    def test_does_not_mutate_input(self):
        entries = [{"type": "table", "name": "a"}, {"type": "model", "name": "b"}]
        original_order = list(entries)
        rollback_order(entries)
        assert entries == original_order

    def test_empty_list(self):
        assert rollback_order([]) == []


# ---------------------------------------------------------------------------
# build_manifest
# ---------------------------------------------------------------------------

class TestBuildManifest:
    def test_shape(self):
        manifest = build_manifest(
            created="20260704_120000",
            profile="prod",
            base_url="https://example.thoughtspot.cloud",
            operation="REMOVE",
            source={"guid": "src-1", "name": "Orders Model", "type": "MODEL"},
            fix_count=2,
            delete_count=1,
        )
        assert manifest["created"] == "20260704_120000"
        assert manifest["profile"] == "prod"
        assert manifest["base_url"] == "https://example.thoughtspot.cloud"
        assert manifest["operation"] == "REMOVE"
        assert manifest["source_object"] == {"guid": "src-1", "name": "Orders Model", "type": "MODEL"}
        assert manifest["fix_count"] == 2
        assert manifest["delete_count"] == 1
        assert manifest["objects"] == []

    def test_objects_list_is_independent_per_call(self):
        # Regression guard against a shared mutable-default-argument bug.
        m1 = build_manifest(
            created="t1", profile="p", base_url="u", operation="REMOVE",
            source={}, fix_count=0, delete_count=0,
        )
        m1["objects"].append({"guid": "x"})
        m2 = build_manifest(
            created="t2", profile="p", base_url="u", operation="REMOVE",
            source={}, fix_count=0, delete_count=0,
        )
        assert m2["objects"] == []
