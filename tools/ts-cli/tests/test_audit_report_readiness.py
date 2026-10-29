"""The Spotter readiness score in the report (A5 until 2026-10, now a figure, not a
finding): carried in the payload, and shown in the Model header and the heatmap."""
import pytest

import audit_rule_fixtures as fx
import report_browser
from ts_cli.audit import run_audit
from ts_cli.audit.report import compact_payload, render_report


def _audit(angles):
    ctx = fx.registry_populated_context()
    # the dependents in the shape the report reads (`guid`, as build_context stores them)
    ctx.dependents = {"m-1": [{"guid": "a-1", "type": "ANSWER", "name": "A"}]}
    return run_audit(None, [], angles, "general", ctx=ctx)


def test_the_payload_carries_the_score_and_level_when_a_ran():
    data = _audit(["A", "P"])
    assert not any(f["check_id"] == "A5" for f in data["findings"])
    [model] = data["corpus"]["models"]
    [cm] = compact_payload(data)["C"]["m"]
    assert cm["rs"] == {"s": model["spotter_readiness"]["score"],
                        "l": model["spotter_readiness"]["level"]}


def test_no_score_without_the_ai_readiness_category():
    data = _audit(["P"])
    assert "spotter_readiness" not in data["corpus"]["models"][0]
    assert "rs" not in compact_payload(data)["C"]["m"][0]


@pytest.mark.skipif(report_browser.CHROME is None, reason="needs headless Chrome")
def test_the_heatmap_and_model_header_show_the_score(tmp_path):
    data = _audit(["A", "P"])
    score = round(data["corpus"]["models"][0]["spotter_readiness"]["score"])
    page = render_report(data)
    home = report_browser.render(page, tmp_path)
    assert home["errors"] == []
    assert "Spotter readiness" in home["text"]
    guid = data["corpus"]["models"][0]["guid"]
    header = report_browser.render(page, tmp_path, route=f"model/{guid}")
    assert header["errors"] == []
    assert f"{score}/100Spotter readiness" in header["text"]
