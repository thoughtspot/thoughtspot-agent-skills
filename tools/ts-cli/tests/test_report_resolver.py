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
