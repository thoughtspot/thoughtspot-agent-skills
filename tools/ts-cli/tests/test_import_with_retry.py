# tools/ts-cli/tests/test_import_with_retry.py
"""Regression for the GE Aerospace fuel-migration finding: `ts tml import`
deliberately exits 1 on ANY per-item failure, even under `--policy
ALL_OR_NONE`, while still printing valid structured JSON to stdout (see
tml.py: "JSON to stdout even on failure ... The exit code is what changes").
`_import_with_retry` used to check `returncode != 0` before reading stdout,
so it raised SystemExit on the very first recoverable per-item failure
instead of parsing the error, dropping the bad formula, and retrying —
turning a 1-bad-formula-out-of-48 situation into a total import failure.
"""
from __future__ import annotations
import json
from unittest.mock import patch

from ts_cli.commands.tableau import _import_with_retry


def _completed_process(returncode, stdout_obj):
    class _CP:
        pass
    cp = _CP()
    cp.returncode = returncode
    cp.stdout = json.dumps(stdout_obj)
    cp.stderr = ""
    return cp


def _merged_with_two_formulas():
    return {
        "guid": "model-guid-123",
        "model": {
            "formulas": [
                {"id": "formula_Bad One", "name": "Bad One", "expr": "1 = 1"},
                {"id": "formula_Good One", "name": "Good One", "expr": "SUM([x])"},
            ],
            "columns": [
                {"name": "Bad One", "formula_id": "formula_Bad One"},
                {"name": "Good One", "formula_id": "formula_Good One"},
            ],
        },
        "_merge_stats": {"added": 2, "added_names": ["Bad One", "Good One"]},
    }


def test_per_item_failure_with_nonzero_exit_is_parsed_and_retried():
    """The exact live-verified shape: exit 1, but valid JSON with a
    per-item ERROR naming the bad formula. Must drop it and retry — not
    raise SystemExit."""
    merged = _merged_with_two_formulas()
    ds = {"calculated_fields": [{"caption": "Bad One", "formula": "1=1"}]}
    result = {}

    responses = [
        _completed_process(1, [{"response": {"status": {
            "status_code": "ERROR",
            "error_message": "Formula addition failed. Formula: Bad One, Error: "
                              "(If / else if) expects condition to be Boolean.",
        }}}]),
        _completed_process(0, [{"response": {
            "status": {"status_code": "OK"},
            "object": [{"header": {"id_guid": "model-guid-123"}}],
        }}]),
    ]

    with patch("subprocess.run", side_effect=responses):
        _import_with_retry(merged, ds, "model-guid-123", "myprofile", 10, result)

    assert result["import_status"] == "OK"
    assert result.get("formulas_dropped_on_import") == [{
        "name": "Bad One",
        "expr": "1 = 1",
        "error": "(If / else if) expects condition to be Boolean.",
        "original_tableau": "1=1",
    }]
    remaining = {f["name"] for f in merged["model"]["formulas"]}
    assert remaining == {"Good One"}


def test_unparseable_stdout_is_still_treated_as_fatal():
    """A true subprocess-level failure (crash, auth error — not valid JSON
    on stdout) must still raise SystemExit, not loop forever."""
    merged = _merged_with_two_formulas()
    ds = {"calculated_fields": []}
    result = {}

    class _CP:
        returncode = 1
        stdout = "not json"
        stderr = "boom: connection refused"

    with patch("subprocess.run", return_value=_CP()):
        try:
            _import_with_retry(merged, ds, "model-guid-123", "myprofile", 10, result)
            assert False, "expected SystemExit"
        except SystemExit as e:
            assert e.code == 1
