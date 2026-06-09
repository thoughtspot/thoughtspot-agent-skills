# tools/ts-cli/tests/test_report_resolver.py
"""Tests for report.resolver — input parsing and ambiguity handling."""
from __future__ import annotations

import pytest

from ts_cli.report.resolver import (
    looks_like_guid,
    InputKind,
    classify_input,
)


class TestLooksLikeGuid:
    def test_canonical_uuid(self):
        assert looks_like_guid("baa451a6-02a0-42d1-8347-8cd4af13b505") is True

    def test_uppercase_uuid(self):
        assert looks_like_guid("BAA451A6-02A0-42D1-8347-8CD4AF13B505") is True

    def test_three_part_name_is_not_guid(self):
        assert looks_like_guid("DB.SCHEMA.TABLE") is False

    def test_one_part_name_is_not_guid(self):
        assert looks_like_guid("MyModel") is False

    def test_empty_string(self):
        assert looks_like_guid("") is False


class TestClassifyInput:
    def test_guid(self):
        assert classify_input("baa451a6-02a0-42d1-8347-8cd4af13b505") == InputKind.GUID

    def test_three_part(self):
        assert classify_input("DB.SCHEMA.TABLE") == InputKind.THREE_PART_NAME

    def test_four_part(self):
        assert classify_input("DB.SCHEMA.TABLE.COLUMN") == InputKind.FOUR_PART_NAME

    def test_two_part(self):
        assert classify_input("Model.column") == InputKind.TWO_PART_NAME

    def test_one_part(self):
        assert classify_input("MyModel") == InputKind.ONE_PART_NAME


from unittest.mock import MagicMock

from ts_cli.report.resolver import (
    SourceUnresolvedError,
    SourceAmbiguousError,
    resolve_source,
)
from ts_cli.report.schema import SourceDescriptor


def _mk_client(search_returns):
    """Return a mock ThoughtSpotClient whose .post() returns search_returns."""
    client = MagicMock()
    resp = MagicMock()
    resp.json.return_value = search_returns
    client.post.return_value = resp
    return client


def _mk_hit(guid, name, type_="LOGICAL_TABLE", subtype="ONE_TO_ONE_LOGICAL"):
    return {
        "metadata_id": guid,
        "metadata_name": name,
        "metadata_type": type_,
        "metadata_header": {"id": guid, "name": name, "type": subtype, "subType": ""},
    }


class TestResolveSourceGuid:
    def test_resolve_guid_returns_descriptor(self):
        guid = "baa451a6-02a0-42d1-8347-8cd4af13b505"
        client = _mk_client([_mk_hit(guid, "DB.SCH.T")])
        desc = resolve_source(guid, client)
        assert isinstance(desc, SourceDescriptor)
        assert desc.guid == guid
        assert desc.type == "LOGICAL_TABLE"
        assert desc.input == guid


class TestResolveSourceThreePartName:
    def test_resolves_unique_match(self):
        client = _mk_client([_mk_hit("g-1", "DB.SCH.T")])
        desc = resolve_source("DB.SCH.T", client)
        assert desc.guid == "g-1"
        assert desc.name == "DB.SCH.T"

    def test_no_match_raises_unresolved(self):
        client = _mk_client([])
        with pytest.raises(SourceUnresolvedError):
            resolve_source("DB.SCH.MISSING", client)

    def test_multiple_matches_raises_ambiguous(self):
        client = _mk_client([
            _mk_hit("g-1", "DB.SCH.T"),
            _mk_hit("g-2", "DB.SCH.T"),
        ])
        with pytest.raises(SourceAmbiguousError) as excinfo:
            resolve_source("DB.SCH.T", client)
        assert len(excinfo.value.candidates) == 2


class TestResolveSourceOnePart:
    def test_one_part_name_uses_name_pattern(self):
        """Bare name like 'MyModel' must use name_pattern search, not identifier."""
        client = MagicMock()
        resp = MagicMock()
        resp.json.return_value = [_mk_hit("g-1", "MyModel")]
        client.post.return_value = resp
        desc = resolve_source("MyModel", client)
        assert desc.guid == "g-1"
        # Verify name_pattern was used (not identifier)
        call_body = client.post.call_args[1]["json"]
        assert "name_pattern" in str(call_body)
        assert "identifier" not in str(call_body)

    def test_one_part_no_match_raises_unresolved(self):
        client = _mk_client([])
        with pytest.raises(SourceUnresolvedError):
            resolve_source("MissingModel", client)


class TestResolveSourceTwoPart:
    def test_two_part_name_uses_name_pattern(self):
        client = MagicMock()
        resp = MagicMock()
        resp.json.return_value = [_mk_hit("g-1", "Schema.Model")]
        client.post.return_value = resp
        desc = resolve_source("Schema.Model", client)
        assert desc.guid == "g-1"
        call_body = client.post.call_args[1]["json"]
        assert "name_pattern" in str(call_body)


class TestResolveFourPartColumn:
    def test_resolves_column_on_table(self, monkeypatch):
        """DB.SCH.TBL.COL → resolve table first, then look up column on it."""
        table_hit = _mk_hit("tbl-1", "DB.SCH.TBL")
        column = {"header": {"id": "col-1", "name": "COL"}}
        detail_resp = [{
            "metadata_id": "tbl-1",
            "metadata_name": "DB.SCH.TBL",
            "metadata_type": "LOGICAL_TABLE",
            "metadata_detail": {"columns": [column]},
            "metadata_header": {"id": "tbl-1", "name": "DB.SCH.TBL"},
        }]

        client = MagicMock()
        resp1, resp2 = MagicMock(), MagicMock()
        resp1.json.return_value = [table_hit]
        resp2.json.return_value = detail_resp
        client.post.side_effect = [resp1, resp2]

        desc = resolve_source("DB.SCH.TBL.COL", client)
        assert desc.type == "LOGICAL_COLUMN"
        assert desc.guid == "col-1"
        assert desc.name == "COL"
        assert desc.parent == {"guid": "tbl-1", "name": "DB.SCH.TBL", "type": "LOGICAL_TABLE"}

    def test_column_not_found_raises(self, monkeypatch):
        table_hit = _mk_hit("tbl-1", "DB.SCH.TBL")
        detail_resp = [{
            "metadata_id": "tbl-1",
            "metadata_name": "DB.SCH.TBL",
            "metadata_detail": {"columns": []},
            "metadata_header": {"id": "tbl-1", "name": "DB.SCH.TBL"},
        }]
        client = MagicMock()
        resp1, resp2 = MagicMock(), MagicMock()
        resp1.json.return_value = [table_hit]
        resp2.json.return_value = detail_resp
        client.post.side_effect = [resp1, resp2]

        with pytest.raises(SourceUnresolvedError):
            resolve_source("DB.SCH.TBL.MISSING", client)
