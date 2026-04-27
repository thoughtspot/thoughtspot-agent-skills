"""
test_metadata_dependents.py — unit tests for `ts metadata dependents`.

Tests the pure helper functions (_build_dependents_payload and
_normalize_dependents_response) without a live ThoughtSpot connection.
The verified API shape lives in references/open-items.md #1.
"""
from __future__ import annotations

import pytest

from ts_cli.commands.metadata import (
    _build_dependents_payload,
    _normalize_dependents_response,
    _BUCKET_TO_TYPE,
)


# ---------------------------------------------------------------------------
# _build_dependents_payload — request shape must match the verified spec
# ---------------------------------------------------------------------------


class TestBuildDependentsPayload:
    def test_single_guid_payload_shape(self):
        payload = _build_dependents_payload(["abc-123"], "LOGICAL_TABLE")
        assert payload == {
            "metadata": [{"identifier": "abc-123", "type": "LOGICAL_TABLE"}],
            "include_dependent_objects": True,
            "dependent_object_version": "V2",
        }

    def test_multiple_guids_one_payload(self):
        payload = _build_dependents_payload(["a", "b", "c"], "LOGICAL_TABLE")
        assert len(payload["metadata"]) == 3
        assert [m["identifier"] for m in payload["metadata"]] == ["a", "b", "c"]
        assert all(m["type"] == "LOGICAL_TABLE" for m in payload["metadata"])

    def test_logical_column_type_for_sets(self):
        """Set/Cohort dependents are queried as LOGICAL_COLUMN, not COHORT
        (COHORT is rejected by v2 search — see open-items.md #11)."""
        payload = _build_dependents_payload(["set-guid"], "LOGICAL_COLUMN")
        assert payload["metadata"][0]["type"] == "LOGICAL_COLUMN"

    def test_include_dependent_objects_always_true(self):
        payload = _build_dependents_payload(["x"], "LOGICAL_TABLE")
        assert payload["include_dependent_objects"] is True

    def test_dependent_object_version_is_v2(self):
        payload = _build_dependents_payload(["x"], "LOGICAL_TABLE")
        assert payload["dependent_object_version"] == "V2"


# ---------------------------------------------------------------------------
# _normalize_dependents_response — flatten v2 response into one row per dep
# ---------------------------------------------------------------------------


def _make_response(source_guid: str, dependents_by_bucket: dict) -> list:
    """Build a v2-shaped response for a single source.

    `dependents_by_bucket` is e.g.
      {"QUESTION_ANSWER_BOOK": [{"id": "a1", "name": "Ans 1", ...}, ...]}
    """
    return [
        {
            "metadata_id": source_guid,
            "metadata_name": "DM_CUSTOMER",
            "metadata_type": "LOGICAL_TABLE",
            "dependent_objects": {
                "areInaccessibleDependentsReturned": False,
                "hasInaccessibleDependents": False,
                "dependents": {source_guid: dependents_by_bucket},
            },
        }
    ]


class TestNormalizeBuckets:
    def test_empty_response_returns_empty_list(self):
        assert _normalize_dependents_response([]) == []

    def test_no_dependents_returns_empty_list(self):
        resp = _make_response("src-1", {})
        assert _normalize_dependents_response(resp) == []

    def test_question_answer_book_maps_to_answer(self):
        resp = _make_response("src-1", {
            "QUESTION_ANSWER_BOOK": [
                {"id": "a1", "name": "My Answer",
                 "author": "u1", "authorDisplayName": "alice"}
            ],
        })
        rows = _normalize_dependents_response(resp)
        assert len(rows) == 1
        assert rows[0]["type"] == "ANSWER"
        assert rows[0]["raw_bucket"] == "QUESTION_ANSWER_BOOK"
        assert rows[0]["guid"] == "a1"
        assert rows[0]["name"] == "My Answer"
        assert rows[0]["source_guid"] == "src-1"
        assert rows[0]["author_id"] == "u1"
        assert rows[0]["author_display_name"] == "alice"

    def test_pinboard_answer_book_maps_to_liveboard(self):
        resp = _make_response("src-1", {
            "PINBOARD_ANSWER_BOOK": [
                {"id": "lb1", "name": "Q4 Dashboard",
                 "author": "u2", "authorDisplayName": "bob"}
            ],
        })
        rows = _normalize_dependents_response(resp)
        assert rows[0]["type"] == "LIVEBOARD"
        assert rows[0]["raw_bucket"] == "PINBOARD_ANSWER_BOOK"

    def test_logical_table_passes_through(self):
        """LOGICAL_TABLE covers Models/Views/Tables — caller distinguishes via subtype."""
        resp = _make_response("src-1", {
            "LOGICAL_TABLE": [
                {"id": "m1", "name": "Customer Model",
                 "author": "u3", "authorDisplayName": "carol"}
            ],
        })
        rows = _normalize_dependents_response(resp)
        assert rows[0]["type"] == "LOGICAL_TABLE"

    def test_cohort_maps_to_set(self):
        resp = _make_response("src-1", {
            "COHORT": [
                {"id": "s1", "name": "Top Customers",
                 "author": "u4", "authorDisplayName": "dave"}
            ],
        })
        rows = _normalize_dependents_response(resp)
        assert rows[0]["type"] == "SET"
        assert rows[0]["raw_bucket"] == "COHORT"

    def test_feedback_maps_to_feedback(self):
        resp = _make_response("src-1", {
            "FEEDBACK": [
                {"id": "f1", "name": "by customer zipcode",
                 "author": "u5", "authorDisplayName": "ed"}
            ],
        })
        rows = _normalize_dependents_response(resp)
        assert rows[0]["type"] == "FEEDBACK"


class TestNormalizeMixedAndMultiSource:
    def test_mixed_bucket_response(self):
        resp = _make_response("src-1", {
            "LOGICAL_TABLE":        [{"id": "m1", "name": "Model A"}],
            "QUESTION_ANSWER_BOOK": [{"id": "a1", "name": "Answer X"},
                                     {"id": "a2", "name": "Answer Y"}],
            "PINBOARD_ANSWER_BOOK": [{"id": "lb1", "name": "LB One"}],
            "COHORT":               [{"id": "s1", "name": "Set Z"}],
        })
        rows = _normalize_dependents_response(resp)
        assert len(rows) == 5
        types = sorted(r["type"] for r in rows)
        assert types == ["ANSWER", "ANSWER", "LIVEBOARD", "LOGICAL_TABLE", "SET"]

    def test_multiple_sources_in_one_response(self):
        resp = _make_response("src-1", {
            "QUESTION_ANSWER_BOOK": [{"id": "a1", "name": "Ans 1"}],
        }) + _make_response("src-2", {
            "QUESTION_ANSWER_BOOK": [{"id": "a2", "name": "Ans 2"}],
        })
        rows = _normalize_dependents_response(resp)
        assert len(rows) == 2
        assert {r["source_guid"] for r in rows} == {"src-1", "src-2"}

    def test_unknown_bucket_passes_through_as_type(self):
        """Future-proof: if the API adds a new bucket, the normalizer doesn't drop it."""
        resp = _make_response("src-1", {
            "FUTURE_BUCKET": [{"id": "x1", "name": "Mystery"}],
        })
        rows = _normalize_dependents_response(resp)
        assert len(rows) == 1
        assert rows[0]["type"] == "FUTURE_BUCKET"
        assert rows[0]["raw_bucket"] == "FUTURE_BUCKET"

    def test_missing_optional_fields_become_none(self):
        resp = _make_response("src-1", {
            "QUESTION_ANSWER_BOOK": [{"id": "a1", "name": "Ans"}],
        })
        rows = _normalize_dependents_response(resp)
        assert rows[0]["author_id"] is None
        assert rows[0]["author_display_name"] is None


class TestNormalizeDefensive:
    def test_non_list_input_returns_empty(self):
        """Defensive: API contract says list, but be safe."""
        assert _normalize_dependents_response({}) == []
        assert _normalize_dependents_response(None) == []
        assert _normalize_dependents_response("not-a-list") == []

    def test_missing_dependent_objects_key(self):
        resp = [{"metadata_id": "src-1", "metadata_name": "X"}]
        assert _normalize_dependents_response(resp) == []

    def test_dependents_keyed_by_different_guid(self):
        """If the response keys dependents by a different GUID, we should still
        find them — but currently we look up by metadata_id. This documents the
        contract: dependents must be keyed by metadata_id."""
        resp = [{
            "metadata_id": "src-1",
            "dependent_objects": {
                "dependents": {"different-guid": {
                    "QUESTION_ANSWER_BOOK": [{"id": "a1", "name": "Ans"}]
                }}
            }
        }]
        # Lookup by metadata_id finds nothing; this is intentional to keep source_guid
        # accurate. If this contract changes, update _normalize_dependents_response.
        assert _normalize_dependents_response(resp) == []


# ---------------------------------------------------------------------------
# _BUCKET_TO_TYPE — regression guard
# ---------------------------------------------------------------------------


class TestBucketTypeMap:
    def test_all_known_buckets_mapped(self):
        """If a bucket is added to the v2 response that needs special handling,
        add it here. Unknown buckets pass through with the bucket name as type."""
        assert _BUCKET_TO_TYPE["QUESTION_ANSWER_BOOK"] == "ANSWER"
        assert _BUCKET_TO_TYPE["PINBOARD_ANSWER_BOOK"] == "LIVEBOARD"
        assert _BUCKET_TO_TYPE["LOGICAL_TABLE"] == "LOGICAL_TABLE"
        assert _BUCKET_TO_TYPE["COHORT"] == "SET"
        assert _BUCKET_TO_TYPE["FEEDBACK"] == "FEEDBACK"
