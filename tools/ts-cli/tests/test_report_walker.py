# tools/ts-cli/tests/test_report_walker.py
"""Tests for report.walker — per-source-type dep walk."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from ts_cli.report.walker import (
    dependents_query_type_for,
    walk_dependents,
)
from ts_cli.report.schema import SourceDescriptor


class TestDependentsQueryTypeFor:
    def test_table_uses_logical_table(self):
        src = SourceDescriptor(input="x", guid="g", type="LOGICAL_TABLE", name="x", parent=None)
        assert dependents_query_type_for(src) == "LOGICAL_TABLE"

    def test_column_uses_logical_column(self):
        src = SourceDescriptor(input="x", guid="g", type="LOGICAL_COLUMN", name="x",
                               parent={"guid": "t", "name": "T", "type": "LOGICAL_TABLE"})
        assert dependents_query_type_for(src) == "LOGICAL_COLUMN"

    def test_set_uses_logical_column(self):
        """Sets are queried as LOGICAL_COLUMN — see open-items.md #11."""
        src = SourceDescriptor(input="x", guid="g", type="LOGICAL_COLUMN", name="x", parent=None)
        assert dependents_query_type_for(src) == "LOGICAL_COLUMN"


from ts_cli.report.walker import walk_dependents_recursive


def _resp(json_):
    r = MagicMock()
    r.json.return_value = json_
    return r


def _v2_dependents(source_guid, by_bucket):
    """Build a v2-shaped response for one source GUID."""
    return [{
        "metadata_id": source_guid,
        "metadata_name": "x",
        "metadata_type": "LOGICAL_TABLE",
        "dependent_objects": {
            "areInaccessibleDependentsReturned": False,
            "hasInaccessibleDependents": False,
            "dependents": {source_guid: by_bucket},
        },
    }]


class TestWalkDependentsRecursive:
    def test_table_to_model_one_hop(self):
        """Source has 1 direct Model dependent; Model has 0 further deps."""
        client = MagicMock()
        client.post.side_effect = [
            _resp(_v2_dependents("tbl", {"LOGICAL_TABLE": [{"id": "mdl", "name": "M", "author": "u", "authorDisplayName": "U"}]})),
            _resp(_v2_dependents("mdl", {})),
        ]
        src = SourceDescriptor(input="tbl", guid="tbl", type="LOGICAL_TABLE", name="x", parent=None)
        out = walk_dependents_recursive(src, client, max_depth=3)
        assert len(out) == 1
        assert out[0]["guid"] == "mdl"
        assert out[0]["hops"] == 1

    def test_table_to_model_to_answer_two_hops(self):
        client = MagicMock()
        client.post.side_effect = [
            _resp(_v2_dependents("tbl", {"LOGICAL_TABLE": [{"id": "mdl", "name": "M", "author": "u", "authorDisplayName": "U"}]})),
            _resp(_v2_dependents("mdl", {"QUESTION_ANSWER_BOOK": [{"id": "ans", "name": "A", "author": "u", "authorDisplayName": "U"}]})),
            _resp(_v2_dependents("ans", {})),
        ]
        src = SourceDescriptor(input="tbl", guid="tbl", type="LOGICAL_TABLE", name="x", parent=None)
        out = walk_dependents_recursive(src, client, max_depth=3)
        guids = sorted(d["guid"] for d in out)
        assert guids == ["ans", "mdl"]
        hops = {d["guid"]: d["hops"] for d in out}
        assert hops["mdl"] == 1
        assert hops["ans"] == 2

    def test_depth_limit_respected(self):
        client = MagicMock()
        client.post.side_effect = [
            _resp(_v2_dependents("tbl", {"LOGICAL_TABLE": [{"id": "mdl", "name": "M", "author": "u", "authorDisplayName": "U"}]})),
            _resp(_v2_dependents("mdl", {"QUESTION_ANSWER_BOOK": [{"id": "ans", "name": "A", "author": "u", "authorDisplayName": "U"}]})),
        ]
        src = SourceDescriptor(input="tbl", guid="tbl", type="LOGICAL_TABLE", name="x", parent=None)
        out = walk_dependents_recursive(src, client, max_depth=1)
        # Only 1 hop: just the Model. Answer not walked.
        assert len(out) == 1
        assert out[0]["guid"] == "mdl"
        assert client.post.call_count == 1
