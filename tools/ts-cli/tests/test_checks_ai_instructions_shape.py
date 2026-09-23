"""A3 / A5 read a key the `ai/instructions/get` response does not have (BL-292).

The live response, recorded in `agents/cli/ts-audit/references/open-items.md`, is

    {"nl_instructions_info": [{"instructions": [...], "scope": "GLOBAL"}]}

`audit/__init__.py` and `audit/erd.py` both unwrap it correctly. `checks_ai` read
`instr.get("instructions")` off the top level, which is always absent — so the API
half of A3/A5 never fired: a Model coached through the UI or API reported HIGH
"no coaching configured" and lost A5's full AI weight. The existing fixtures
passed `{"instructions": "..."}`, a shape the API never returns, locking it in.
"""
from ts_cli.audit.checks_ai import check_a3, check_a5
from ts_cli.audit.context import make_context

import pytest

LIVE_SHAPE = {"nl_instructions_info": [
    {"instructions": ["Always filter by [Region] before aggregating"], "scope": "GLOBAL"}
]}


def _model(guid="m-1", **model):
    base = {"name": "Sales", "columns": [
        {"name": "Amount", "column_id": "T::AMOUNT",
         "properties": {"column_type": "MEASURE"}}]}
    base.update(model)
    return {"guid": guid, "model": base}


def test_a3_sees_instructions_in_the_live_response_shape():
    ctx = make_context(models=[_model()], ai_instructions={"m-1": LIVE_SHAPE})
    assert [f for f in check_a3(ctx) if "coaching instructions" in f.detail] == [], \
        "a coached model must not be reported as uncoached"


def test_a3_still_reports_a_genuinely_uncoached_model():
    ctx = make_context(models=[_model()],
                       ai_instructions={"m-1": {"nl_instructions_info": []}})
    assert any("coaching instructions" in f.detail for f in check_a3(ctx))


def test_a3_reports_when_the_info_block_carries_no_instructions():
    ctx = make_context(models=[_model()], ai_instructions={
        "m-1": {"nl_instructions_info": [{"instructions": [], "scope": "GLOBAL"}]}})
    assert any("coaching instructions" in f.detail for f in check_a3(ctx))


def test_tml_side_still_counts_on_its_own():
    """Either surface satisfies the check; the TML half was never broken."""
    ctx = make_context(
        models=[_model(model_instructions={"data_model_instructions": "Use last 30 days"})],
        ai_instructions={"m-1": {"nl_instructions_info": []}})
    assert [f for f in check_a3(ctx) if "coaching instructions" in f.detail] == []


def test_a5_credits_the_api_surface():
    """A5 emits a readiness SCORE, so the fix shows as a better score.

    Coached scores 25 points higher than bare — the AI weight the check assigns
    to having instructions at all, and which was unreachable via the API surface.
    """
    coached = check_a5(make_context(models=[_model()],
                                    ai_instructions={"m-1": LIVE_SHAPE}))
    bare = check_a5(make_context(models=[_model()],
                                 ai_instructions={"m-1": {"nl_instructions_info": []}}))
    assert len(coached) == len(bare) == 1
    assert coached[0].metric > bare[0].metric, \
        "a coached model must score higher than an uncoached one"
    assert coached[0].metric - bare[0].metric == 25
