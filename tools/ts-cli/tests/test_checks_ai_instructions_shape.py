"""A3 / A5 read a key the `ai/instructions/get` response does not have (BL-292).

The live response, recorded in `agents/cli/ts-audit/references/open-items.md`, is

    {"nl_instructions_info": [{"instructions": [...], "scope": "GLOBAL"}]}

`audit/__init__.py` and `audit/erd.py` both unwrap it correctly. `checks_ai` read
`instr.get("instructions")` off the top level, which is always absent — so the API
half of A3/A5 never fired: a Model coached through the UI or API reported HIGH
"no coaching configured" and lost A5's full AI weight. The existing fixtures
passed `{"instructions": "..."}`, a shape the API never returns, locking it in.
"""
import audit_rule_fixtures as fx
from audit_run_rule import run_rule


def test_a3_sees_instructions_in_the_live_response_shape():
    ctx = fx.instructions_live_shape()
    assert [f for f in run_rule(ctx, "A3") if "coaching instructions" in f.detail] == [], \
        "a coached model must not be reported as uncoached"


def test_a3_still_reports_a_genuinely_uncoached_model():
    ctx = fx.instructions_empty_info()
    assert any("coaching instructions" in f.detail for f in run_rule(ctx, "A3"))


def test_a3_reports_when_the_info_block_carries_no_instructions():
    ctx = fx.instructions_info_without_text()
    assert any("coaching instructions" in f.detail for f in run_rule(ctx, "A3"))


def test_tml_side_still_counts_on_its_own():
    """Either surface satisfies the check; the TML half was never broken."""
    ctx = fx.instructions_tml_only()
    assert [f for f in run_rule(ctx, "A3") if "coaching instructions" in f.detail] == []


def test_a5_credits_the_api_surface():
    """A5 emits a readiness SCORE, so the fix shows as a better score.

    Coached scores 25 points higher than bare — the AI weight the check assigns
    to having instructions at all, and which was unreachable via the API surface.
    """
    coached = run_rule(fx.instructions_live_shape(), "A5")
    bare = run_rule(fx.instructions_empty_info(), "A5")
    assert len(coached) == len(bare) == 1
    assert coached[0].metric > bare[0].metric, \
        "a coached model must score higher than an uncoached one"
    assert coached[0].metric - bare[0].metric == 25
