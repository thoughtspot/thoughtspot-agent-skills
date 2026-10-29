"""Two guards that could not do their job (BL-302, BL-303).

P5 (retired 2026-10; its logic is kept in the catalog, so the guard is recorded here
for when it is revived) suppressed its finding when the model carries a rolling date window. The
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


# ── P5 — retired 2026-10 ───────────────────────────────────────────────────

def test_p5_is_retired_and_silent_on_a_fact_model_with_no_constraints():
    """Retired: a date limit on fact tables is a design choice, not a defect."""
    assert run_rule(fx.guard_fact_model_unconstrained(), "P5") == []
    assert run_rule(fx.guard_fact_model_other_constraint(), "P5") == []


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
