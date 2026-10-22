"""Two guards that could not do their job (BL-302, BL-303).

P5 suppresses its finding when the model carries a rolling date window. The
schema: *"The outer key is `constraints:`, which contains a single `constraint:`
list (not a list at the top level)"* — a **mapping**. `for c in constraints`
therefore yields the key string `"constraint"`, which never contains
`date_range_condition`, so a model with a genuine window was still reported as
having none. The existing fixture passed a list, which is the shape that hid it.

H5 reports a set with no consumers. It read `ctx.dependents[set_guid]`, but
`build_context` only fetches dependents for models and tables — a SET guid is
never a key — so `if not set_deps` was always true and every set in the
environment was reported an orphan, with a detail asserting a lookup that never
happened.
"""
import audit_rule_fixtures as fx
from audit_run_rule import run_rule

# The P5 contexts are named builders in audit_rule_fixtures (perf.py), whose legacy P5
# answers test_audit_pinned_findings.py pins.


# ── P5 — the real exported shape must suppress ─────────────────────────────

def test_p5_reports_a_fact_model_with_no_constraints():
    assert len(run_rule(fx.guard_fact_model_unconstrained(), "P5")) == 1


def test_p5_is_suppressed_by_the_real_mapping_shape():
    """The shape an export actually produces — previously ignored."""
    assert run_rule(fx.guard_fact_model_date_window(), "P5") == []


def test_p5_is_still_suppressed_by_a_list_shape():
    """A hand-built fixture may pass a list; keep tolerating it."""
    assert run_rule(fx.guard_fact_model_listed_window(), "P5") == []


def test_p5_is_not_suppressed_by_an_unrelated_constraint():
    assert len(run_rule(fx.guard_fact_model_other_constraint(), "P5")) == 1


# ── H5 — only speak about sets whose dependents were actually fetched ──────

# The H5 contexts are named builders in audit_rule_fixtures (human.py, guard_set_*).

def test_h5_is_silent_when_the_sets_dependents_were_never_fetched():
    """`build_context` does not query dependents for sets, so absence of a key
    means "not looked up" — not "no consumers". Reporting an orphan from that
    is an assertion the check never earned."""
    assert run_rule(fx.guard_set_never_looked_up(), "H5") == []


def test_h5_reports_a_set_fetched_and_found_to_have_no_consumers():
    findings = run_rule(fx.guard_set_looked_up_no_consumers(), "H5")
    assert len(findings) == 1
    assert findings[0].object_guid == "set-1"


def test_h5_stays_silent_on_a_set_with_consumers():
    assert run_rule(fx.guard_set_looked_up_with_consumers(), "H5") == []
