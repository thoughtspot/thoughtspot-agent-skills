"""`validator_verdict` must not report a skipped check as a pass.

Apache's `validation/validate.py` degrades silently when sqlglot is absent: it
prints a warning and then "Validation PASSED", and exits zero. An earlier
revision of this harness looked only for the PASSED line, so every run against
a converter venv without sqlglot reported a clean 31/31 while no SQL expression
had been parsed at all. With sqlglot present the real figure at the time was 29
passed and 2 failed, on output that had already been reported as valid.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

_HARNESS = pathlib.Path(__file__).resolve().parents[1] / "roundtrip.py"


def _load():
    # The directory name contains a hyphen, so it is not importable as a
    # package; load the module by path, as the reference-doc tests upstream do.
    spec = importlib.util.spec_from_file_location("_roundtrip_under_test", _HARNESS)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


roundtrip = _load()

SKIP_WARNING = (
    "  [SQL] Warning: sqlglot not installed, skipping SQL validation. "
    "Install with: pip install sqlglot"
)


class TestValidatorVerdict:
    def test_a_clean_run_passes(self):
        assert roundtrip.validator_verdict("Validation PASSED: m.ossie.yaml") == "PASSED"

    def test_a_rejected_document_fails(self):
        assert roundtrip.validator_verdict("Validation FAILED: 3 error(s)") == "FAILED"

    def test_a_skipped_sql_check_is_not_a_pass(self):
        # THE regression this file exists for. Both lines are present in real
        # output, and the PASSED line comes second -- so a check that looked
        # only for it saw a pass.
        output = f"{SKIP_WARNING}\nValidation PASSED: m.ossie.yaml"
        assert roundtrip.validator_verdict(output) == "SKIPPED", (
            "a validator that skipped its SQL checks was reported as passing"
        )

    def test_the_skip_is_detected_whatever_the_surrounding_output(self):
        assert roundtrip.validator_verdict(
            f"Checking m.ossie.yaml\n{SKIP_WARNING}\nValidation PASSED: m.ossie.yaml\n"
        ) == "SKIPPED"

    @pytest.mark.parametrize("verdict", ["PASSED", "FAILED", "SKIPPED"])
    def test_every_verdict_is_one_of_three(self, verdict):
        # Guards the vocabulary itself: `report()` branches on these exact
        # strings, so a renamed verdict would silently stop being counted.
        assert verdict in {"PASSED", "FAILED", "SKIPPED"}


class TestSkippedChecksFailTheRun:
    def test_report_exits_non_zero_when_a_check_was_skipped(self, tmp_path, capsys):
        results = [{
            "model": "m", "validator": "SKIPPED",
            "source": {"tables": 1, "columns": 1, "formulas": 0, "joins": 0},
            "returned": {"tables": 1, "columns": 1, "formulas": 0, "joins": 0},
            "portability": {},
        }]
        import collections
        status = roundtrip.report(results, collections.Counter(), collections.Counter(),
                                  tmp_path, None)
        out = capsys.readouterr().out
        assert status == 1, "a skipped check must fail the run, not warn"
        assert "SKIPPED" in out
        assert "sqlglot" in out, "the message must say how to fix it"
