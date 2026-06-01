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
        client = _mk_client([_mk_hit("g-1", "DB.SCH.T")])
        desc = resolve_source("g-1", client)
        assert isinstance(desc, SourceDescriptor)
        assert desc.guid == "g-1"
        assert desc.type == "LOGICAL_TABLE"
        assert desc.input == "g-1"


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
