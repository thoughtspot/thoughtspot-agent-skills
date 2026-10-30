"""Unit tests for commands/tableau.py's ``_import_with_retry``.

Covers the three failure modes found in review: an error the parser can't
read must not report success ("fail open"), the drop path must never remove
a formula that pre-existed in the Model (only ones this batch itself added),
and a malformed/unexpected JSON response shape must not crash the process.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

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

    def test_unparseable_error_message_is_not_silently_ok(self):
        merged = _merged(["A"], added_names=["A"])
        result: dict = {}
        msg = "Join between Orders and Returns is invalid"
        with patch("subprocess.run", return_value=_proc(1, _error_response(msg))):
            _import_with_retry(merged, _ds(), "guid-1", "prof", 3, result)
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
            _import_with_retry(merged, _ds(), "guid-1", "prof", 3, result)
        assert result["import_status"] == "ERROR"

    def test_malformed_json_empty_list_does_not_crash(self):
        merged = _merged(["A"], added_names=["A"])
        result: dict = {}
        with patch("subprocess.run", return_value=_proc(1, json.dumps([]))):
            _import_with_retry(merged, _ds(), "guid-1", "prof", 3, result)
        assert result["import_status"] == "ERROR"

    def test_all_added_formulas_dropped_is_not_success(self):
        """SKIPPED (nothing left to import) is also not success."""
        merged = _merged(["New1"], added_names=["New1"])
        result: dict = {}
        msg = "Formula: New1, Error: bad token"
        with patch("subprocess.run", return_value=_proc(1, _error_response(msg))):
            _import_with_retry(merged, _ds(), "guid-1", "prof", 3, result)
        assert result["import_status"] == "SKIPPED"

    def test_import_with_retry_never_raises_systemexit(self):
        """Regression: a premature SystemExit here used to cut build_model_cmd's
        per-datasource loop short, losing every other datasource's result (and
        this one's own JSON) from stdout. The exit decision belongs to the
        caller, made once every datasource has been processed and printed."""
        merged = _merged(["A"], added_names=["A"])
        result: dict = {}
        with patch("subprocess.run", return_value=_proc(1, json.dumps([]))):
            _import_with_retry(merged, _ds(), "guid-1", "prof", 3, result)  # must not raise
        assert result["import_status"] == "ERROR"


class TestBuildModelCmdPrintsBeforeExiting:
    """CLI-level regression test for the bug the unit tests above couldn't see:
    checking `_import_with_retry`'s *return value* in isolation hid the fact
    that its own `SystemExit` used to fire before `build_model_cmd` ever
    printed `all_results` — the skill's Step 7 reads that stdout JSON for
    `import_status`/`formulas_dropped_on_import`; a non-zero exit with no
    stdout left it nothing to read.
    """

    def test_all_results_printed_before_nonzero_exit(self, tmp_path):
        import importlib

        from typer.testing import CliRunner

        cli = importlib.import_module("ts_cli.cli")
        twb = tmp_path / "wb.twb"
        twb.write_text("<workbook/>")
        out = tmp_path / "out"

        parsed = {"datasources": [{"name": "ds_ok"}, {"name": "ds_fail"}], "sets_detected": 0}
        per_ds_results = [
            {"datasource": "ds_ok", "formulas_added": 1, "import_status": "OK"},
            {"datasource": "ds_fail", "formulas_added": 1, "import_status": "ERROR", "import_error": "boom"},
        ]

        with patch("ts_cli.model_builder.parse_twb", return_value=parsed), \
             patch("ts_cli.commands.tableau._process_datasource", side_effect=per_ds_results):
            result = CliRunner().invoke(
                cli.app,
                [
                    "tableau", "build-model", str(twb),
                    "--existing-guid", "guid-1", "--profile", "prof",
                    "--output-dir", str(out),
                ],
            )

        assert result.exit_code == 1, result.stdout
        # CliRunner may mix stdout/stderr depending on the installed Click
        # version — extract just the JSON array `build_model_cmd` printed
        # rather than depending on stream separation.
        output = result.stdout
        payload = json.loads(output[output.index("["):])
        assert [r["datasource"] for r in payload] == ["ds_ok", "ds_fail"]
        assert payload[1]["import_error"] == "boom"
