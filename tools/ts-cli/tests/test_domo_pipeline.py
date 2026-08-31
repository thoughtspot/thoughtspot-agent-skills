"""End-to-end through the real CLI, asserting the cross-stage contract.

Every earlier round tested the two build stages in-process, which cannot catch the
thing that actually went wrong four times: `build-model` and `build-liveboard` are
separate CLI invocations, and what binds them is a file on disk. These tests drive the
commands, then assert the property that matters — every column an Answer names exists
in the Model that was written beside it, on the right table — plus the guards that stop
the two drifting apart.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml
from typer.testing import CliRunner

from ts_cli.cli import app

try:
    runner = CliRunner(mix_stderr=False)
except TypeError:
    runner = CliRunner()

BUNDLES = [
    str(Path(__file__).parent / "fixtures" / "domo"),
    str(Path(__file__).parent / "fixtures" / "domo_edge"),
]
_REF = re.compile(r"\[([^\[\]]+)\]")


import pytest


@pytest.fixture(params=BUNDLES, ids=["domo", "domo_edge"])
def bundle_id(request):
    return request.param


def _run(tmp_path, bundle):
    """build-model then build-liveboard then report, as a user would."""
    common = ["--connection", "SF", "--database", "DB", "--schema", "S"]
    r1 = runner.invoke(app, ["domo", "build-model", bundle, *common,
                             "--model-name", "M", "--output-dir", str(tmp_path)])
    assert r1.exit_code == 0, r1.stdout + getattr(r1, "stderr", "")
    r2 = runner.invoke(app, ["domo", "build-liveboard", bundle, "--model-name", "M",
                             "--output-dir", str(tmp_path)])
    assert r2.exit_code == 0, r2.stdout + getattr(r2, "stderr", "")
    r3 = runner.invoke(app, ["domo", "report", "--output-dir", str(tmp_path)])
    assert r3.exit_code == 0, r3.stdout + getattr(r3, "stderr", "")
    model_file = next(f for f in tmp_path.glob("*.model.tml"))
    return (json.loads((tmp_path / "mapping.json").read_text()),
            json.loads((tmp_path / "liveboard_mapping.json").read_text()),
            yaml.safe_load(model_file.read_text()),
            yaml.safe_load(next(tmp_path.glob("*.liveboard.tml")).read_text()),
            (tmp_path / "migration_report.md").read_text())


class TestCrossStageBinding:
    """The invariant, across the process boundary rather than within one."""

    def test_every_answer_column_exists_in_the_written_model(self, tmp_path, bundle_id):
        _m, _lb, model, liveboard, _rpt = _run(tmp_path, bundle_id)
        exposed = {c["name"] for c in model["model"]["columns"]}
        missing = []
        for viz in liveboard["liveboard"]["visualizations"]:
            for col in viz["answer"]["answer_columns"]:
                if col["name"] not in exposed:
                    missing.append((viz["answer"]["name"], col["name"]))
        assert not missing, f"Answer columns absent from the Model on disk: {missing}"

    def test_every_search_query_ref_exists_in_the_written_model(self, tmp_path, bundle_id):
        _m, _lb, model, liveboard, _rpt = _run(tmp_path, bundle_id)
        exposed = {c["name"] for c in model["model"]["columns"]}
        for viz in liveboard["liveboard"]["visualizations"]:
            for ref in _REF.findall(viz["answer"]["search_query"]):
                assert ref in exposed, (
                    f"{viz['answer']['name']}: search_query names [{ref}], "
                    "which the Model does not expose")

    def test_the_index_is_shared_not_rederived(self, tmp_path, bundle_id):
        _m, lb, _model, _liveboard, _rpt = _run(tmp_path, bundle_id)
        assert lb["index_rederived"] is False, (
            "build-liveboard re-derived the namespace instead of loading the one "
            "build-model wrote — the two can then disagree")

    def test_both_stages_agree_on_the_bundle(self, tmp_path, bundle_id):
        m, lb, _model, _liveboard, _rpt = _run(tmp_path, bundle_id)
        assert m["bundle_digest"] == lb["bundle_digest"]


class TestOutputIsSelfConsistent:
    def test_no_live_formula_carries_a_domo_backtick(self, tmp_path, bundle_id):
        _m, _lb, model, _liveboard, _rpt = _run(tmp_path, bundle_id)
        live = [f["id"] for f in model["model"]["formulas"]
                if "`" in f["expr"] and not f["expr"].strip().startswith("/*")]
        assert not live, f"unimportable formula bodies: {live}"

    def test_every_formula_id_referenced_exists(self, tmp_path, bundle_id):
        _m, _lb, model, _liveboard, _rpt = _run(tmp_path, bundle_id)
        ids = {f["id"] for f in model["model"]["formulas"]}
        for f in model["model"]["formulas"]:
            if f["expr"].strip().startswith("/*"):
                continue
            for ref in re.findall(r"\[(formula_[^\]]+)\]", f["expr"]):
                assert ref in ids, f"{f['id']} references missing {ref}"

    def test_no_reference_is_ambiguous_between_a_column_and_a_formula_id(
        self, tmp_path, bundle_id
    ):
        """EXISTENCE is not IDENTITY, and asserting the first hid five bugs.

        `test_every_formula_id_referenced_exists` above checks a `[formula_X]` ref
        resolves to *something*. That is satisfiable by the wrong object: a Domo column
        named `formula_Net` and a Beast Mode named `Net` both produced the string
        `formula_Net` — one as a column, one as a generated id — so a reference authored
        against the money column bound to `sum([Qty])` instead, imported cleanly, and
        reported `Migrated` (PR #440 review, round 5; the fifth path in this class, and
        the fifth time a test asserting existence read as a test asserting correctness).

        The Model-level invariant that forecloses it: no string may name both a column
        and a formula id, so no reference can be ambiguous in the first place.
        """
        m = model_of = _run(tmp_path, bundle_id)[2]["model"]
        display_names = {c["name"] for c in model_of["columns"]}
        formula_ids = {f["id"] for f in model_of["formulas"]}
        clash = display_names & formula_ids
        assert not clash, (
            f"these strings name BOTH a column and a formula id, so any reference to "
            f"them is ambiguous: {sorted(clash)}")

        # And nothing the Model exposes may carry the generated-id prefix, which is
        # what makes the ambiguity possible.
        assert not [n for n in display_names if n.startswith("formula_")], (
            "a column display name carries the reserved 'formula_' prefix")
        del m

    def test_mapping_rows_describe_what_was_emitted(self, tmp_path, bundle_id):
        """The mapping is what the report reads, so it must match the TML exactly."""
        m, lb, model, liveboard, _rpt = _run(tmp_path, bundle_id)
        emitted_joins = sum(len(t.get("joins", []))
                            for t in model["model"]["model_tables"])
        assert len(m["joins"]) == emitted_joins, (
            "mapping lists joins that were never emitted — this is how the report came "
            "to claim 'Relationships: 7' over a model with none")
        assert len(m["beast_modes"]) == len(model["model"]["formulas"])
        converted = [c for c in lb["cards"] if c["status"] != "Skipped"]
        assert len(converted) == len(liveboard["liveboard"]["visualizations"])
        assert len(m["datasets"]) == len(model["model"]["model_tables"])

    def test_report_does_not_contradict_the_mapping(self, tmp_path, bundle_id):
        m, lb, _model, _liveboard, report = _run(tmp_path, bundle_id)
        flagged = [c for c in lb["cards"] if c["status"] != "Migrated"]
        if flagged:
            assert "Risk score:** Low —" not in report, (
                "report headlines Low risk while cards are flagged")
            review = report.split("## Manual review")[1]
            for c in flagged[:3]:
                assert c["title"] in review, f"{c['title']} flagged but not in review"

    def test_running_twice_is_idempotent(self, tmp_path, bundle_id):
        """Same bundle, same output — the determinism claim, end to end."""
        first = _run(tmp_path, bundle_id)
        second = _run(tmp_path, bundle_id)
        # viz_guid is uuid4 by design; everything naming-related must be identical.
        assert first[0]["name_index"] == second[0]["name_index"]
        assert first[2]["model"]["columns"] == second[2]["model"]["columns"]
        assert first[2]["model"]["formulas"] == second[2]["model"]["formulas"]


class TestLintClean:
    def test_emitted_tml_passes_ts_tml_lint(self, tmp_path, bundle_id):
        _run(tmp_path, bundle_id)
        result = runner.invoke(app, ["tml", "lint", "--dir", str(tmp_path)])
        assert result.exit_code == 0, result.stdout + getattr(result, "stderr", "")
