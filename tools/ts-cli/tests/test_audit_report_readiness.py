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


def test_the_level_is_graded_on_the_raw_score(monkeypatch):
    """79.96 is Needs work, as A5 graded it, though it shows as 80.0 rounded."""
    import ts_cli.audit as audit
    monkeypatch.setattr(audit, "readiness_score", lambda item, ctx: 79.96)
    [model] = _audit(["A"])["corpus"]["models"]
    assert model["spotter_readiness"] == {"score": 80.0, "level": "needs_work"}


def test_a_numeric_column_name_does_not_raise():
    """YAML types `name: 2024` as an int; the name-quality regex must still get a str."""
    from ts_cli.audit.engine import scopes
    from ts_cli.audit.engine.code_rules import readiness_score
    ctx = fx.registry_populated_context()
    ctx.models[0]["model"]["columns"].append({"name": 2024, "properties": {}})
    [item] = scopes.iterate(ctx, "model")
    assert 0 <= readiness_score(item, ctx) <= 100


def test_the_readiness_header_is_not_a_category_filter():
    """An `angle-col` header navigates to a category view on click; the score's
    column has no category, so it must not carry that class."""
    import re
    page = render_report(_audit(["A", "P"]))
    js = page[page.index("function buildHeatmap"):]
    [header] = re.findall(r"<th class=\"([a-z-]+)\"[^>]*>Spotter readiness</th>", js)
    assert header != "angle-col"
