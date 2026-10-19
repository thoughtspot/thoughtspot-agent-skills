"""Unit tests for commands/tableau.py's ``_import_with_retry``.

Covers the three failure modes found in review: an error the parser can't
read must not report success ("fail open"), the drop path must never remove
a formula that pre-existed in the Model (only ones this batch itself added),
and a malformed/unexpected JSON response shape must not crash the process.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from ts_cli.commands.tableau import _import_with_retry


def _merged(formula_names: list[str], added_names: list[str]) -> dict:
    formulas = [{"id": f"formula_{n}", "name": n, "expr": "1"} for n in formula_names]
    columns = [
        {"name": n, "formula_id": f"formula_{n}", "properties": {"column_type": "MEASURE"}}
        for n in formula_names
    ]
    return {
        "model": {"formulas": formulas, "columns": columns},
        "_merge_stats": {
            "updated": 0,
            "skipped_existing": 0,
            "added": len(added_names),
            "added_names": list(added_names),
            "skipped_collisions": [],
            "existing_total": len(formula_names) - len(added_names),
        },
    }


def _ds() -> dict:
    return {"calculated_fields": []}


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


def _ok_response() -> str:
    return json.dumps([{"response": {"status": {"status_code": "OK"}}}])


def _error_response(msg: str) -> str:
    return json.dumps([{"response": {"status": {"status_code": "ERROR", "error_message": msg}}}])


class TestSuccessPath:
    def test_ok_status_sets_result_and_does_not_raise(self):
        merged = _merged(["A"], added_names=[])
        result: dict = {}
        with patch("subprocess.run", return_value=_proc(0, _ok_response())):
            _import_with_retry(merged, _ds(), "guid-1", "prof", 3, result)
        assert result["import_status"] == "OK"


class TestFailsOpenBugs:
    """The three ways the retry previously reported success (or crashed) on
    a genuine failure."""

    def test_unparseable_error_message_exits_nonzero_not_silently_ok(self):
        merged = _merged(["A"], added_names=["A"])
        result: dict = {}
        msg = "Join between Orders and Returns is invalid"
        with patch("subprocess.run", return_value=_proc(1, _error_response(msg))):
            with pytest.raises(SystemExit) as exc_info:
                _import_with_retry(merged, _ds(), "guid-1", "prof", 3, result)
        assert exc_info.value.code != 0
        assert result["import_status"] == "ERROR"

    def test_error_naming_an_existing_not_added_formula_is_not_dropped(self):
        """A probe: send ['Existing', 'New1', 'New2'] as the formulas, with
        only New1/New2 in added_names (Existing pre-dated this batch). An
        error naming 'Existing' must not cause it to be silently removed and
        the retry to "succeed" without it."""
        merged = _merged(["Existing", "New1", "New2"], added_names=["New1", "New2"])
        result: dict = {}
        msg = "Formula: Existing, Error: some failure"
        with patch("subprocess.run", return_value=_proc(1, _error_response(msg))):
            with pytest.raises(SystemExit):
                _import_with_retry(merged, _ds(), "guid-1", "prof", 3, result)
        remaining = {f["name"] for f in merged["model"]["formulas"]}
        assert "Existing" in remaining, "a pre-existing formula must never be dropped"
        assert result["import_status"] == "ERROR"

    def test_error_naming_an_added_formula_is_dropped_and_retried_to_ok(self):
        merged = _merged(["New1", "New2"], added_names=["New1", "New2"])
        result: dict = {}
        msg = "Formula: New1, Error: bad token"
        responses = [_proc(1, _error_response(msg)), _proc(0, _ok_response())]
        with patch("subprocess.run", side_effect=responses):
            _import_with_retry(merged, _ds(), "guid-1", "prof", 3, result)
        remaining = {f["name"] for f in merged["model"]["formulas"]}
        assert remaining == {"New2"}
        assert result["import_status"] == "OK"
        assert result["formulas_dropped_on_import"][0]["name"] == "New1"

    def test_malformed_json_dict_instead_of_list_does_not_crash(self):
        merged = _merged(["A"], added_names=["A"])
        result: dict = {}
        with patch("subprocess.run", return_value=_proc(1, json.dumps({"oops": "not a list"}))):
            with pytest.raises(SystemExit):
                _import_with_retry(merged, _ds(), "guid-1", "prof", 3, result)
        assert result["import_status"] == "ERROR"

    def test_malformed_json_empty_list_does_not_crash(self):
        merged = _merged(["A"], added_names=["A"])
        result: dict = {}
        with patch("subprocess.run", return_value=_proc(1, json.dumps([]))):
            with pytest.raises(SystemExit):
                _import_with_retry(merged, _ds(), "guid-1", "prof", 3, result)
        assert result["import_status"] == "ERROR"

    def test_all_added_formulas_dropped_still_exits_nonzero(self):
        """SKIPPED (nothing left to import) is also not success."""
        merged = _merged(["New1"], added_names=["New1"])
        result: dict = {}
        msg = "Formula: New1, Error: bad token"
        with patch("subprocess.run", return_value=_proc(1, _error_response(msg))):
            with pytest.raises(SystemExit):
                _import_with_retry(merged, _ds(), "guid-1", "prof", 3, result)
        assert result["import_status"] == "SKIPPED"
