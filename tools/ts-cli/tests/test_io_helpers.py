"""Tests for ts_cli.io_helpers — shared I/O helpers."""
from __future__ import annotations

import json

import pytest

from ts_cli.io_helpers import (
    _clean_error_message,
    _extract_status_error,
    load_json_file,
)


class TestLoadJsonFile:
    def test_loads_valid_json(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text(json.dumps({"key": "value"}))
        assert load_json_file(f, "test") == {"key": "value"}

    def test_loads_list(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text(json.dumps([1, 2, 3]))
        assert load_json_file(f, "test") == [1, 2, 3]

    def test_missing_file_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="test not found"):
            load_json_file(tmp_path / "missing.json", "test")

    def test_invalid_json_raises_value_error(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not json")
        with pytest.raises(ValueError, match="Invalid JSON in test"):
            load_json_file(f, "test")

    def test_expect_dict_passes_for_dict(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text(json.dumps({"a": 1}))
        assert load_json_file(f, "test", expect_dict=True) == {"a": 1}

    def test_expect_dict_rejects_list(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text(json.dumps([1, 2]))
        with pytest.raises(TypeError, match="must be a JSON object"):
            load_json_file(f, "test", expect_dict=True)

    def test_accepts_str_path(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text(json.dumps(42))
        assert load_json_file(str(f), "test") == 42


class TestCleanErrorMessage:
    def test_strips_html(self):
        assert _clean_error_message("<b>Error</b> happened") == "Error happened"

    def test_collapses_whitespace(self):
        assert _clean_error_message("a   b\n\nc") == "a b c"

    def test_caps_length(self):
        assert len(_clean_error_message("x" * 2000)) == 1000

    def test_handles_none(self):
        assert _clean_error_message(None) == ""


class TestExtractStatusError:
    def test_returns_error_message(self):
        result = [{"response": {"status": {
            "status_code": "ERROR",
            "error_message": "bad thing",
        }}}]
        assert _extract_status_error(result) == "bad thing"

    def test_returns_none_for_ok(self):
        result = [{"response": {"status": {"status_code": "OK"}}}]
        assert _extract_status_error(result) is None

    def test_returns_none_for_empty_list(self):
        assert _extract_status_error([]) is None

    def test_returns_none_for_none(self):
        assert _extract_status_error(None) is None

    def test_returns_none_for_non_list(self):
        assert _extract_status_error("string") is None

    def test_returns_none_for_non_dict_element(self):
        assert _extract_status_error(["string"]) is None
