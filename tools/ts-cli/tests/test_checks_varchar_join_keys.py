"""P6 / D2 — the VARCHAR join-key checks, which could not return a finding.

2026-09-22 audit finding 14.1. Two independent killers, both reproduced here:

1. The `on` clause is split on `=`/`,` without stripping the TML brackets, then
   looked up in a map keyed by bare `column_id`. `"[ORDERS::CUST_ID]"` never
   equals `"ORDERS::CUST_ID"`, so `varchar_keys` was always empty.
2. Even with brackets stripped, the type was read from
   `columns[].db_column_properties.data_type` on the MODEL. Model columns carry
   no data type — the schema's own currency anchor records "no data_type on
   formulas[]/columns[]". It lives on the TABLE the column resolves to.

Either alone makes the check inert; it shipped with both. `check_d2` was a
verbatim clone and had the same pair. (The legacy checks were deleted when the rule catalog replaced them; the
tests run the P6 and D2 catalog rules.)
"""
import audit_rule_fixtures as fx
from audit_run_rule import run_rule

import pytest

# The contexts are named builders in audit_rule_fixtures (perf.py), whose legacy P6 and
# D2 answers test_audit_pinned_findings.py holds the catalog to.


@pytest.mark.parametrize("cid", ["P6", "D2"])
def test_bracketed_join_key_is_found(cid):
    """Real TML writes `[TABLE::COL]`. This is the shape that returned nothing."""
    findings = run_rule(fx.join_keys_varchar(), cid)
    assert len(findings) == 1, "a VARCHAR join key must be reported"
    assert findings[0].check_id == cid
    assert "CUST_ID" in findings[0].detail


@pytest.mark.parametrize("rule_id", ["P6", "D2"])
def test_integer_join_key_is_not_reported(rule_id):
    assert run_rule(fx.join_keys_integer(), rule_id) == []


@pytest.mark.parametrize("rule_id", ["P6", "D2"])
def test_type_comes_from_the_table_not_the_model(rule_id):
    """Model columns carry no data type; putting one there must not fake a pass."""
    # the model column claims INT64 — a lie, and ignored
    assert len(run_rule(fx.join_keys_type_on_model_ignored(), rule_id)) == 1, \
        "the TABLE's VARCHAR is what counts"


@pytest.mark.parametrize("rule_id", ["P6", "D2"])
def test_composite_key_counts_both_varchar_sides(rule_id):
    varchar = [f for f in run_rule(fx.join_keys_composite(), rule_id)
               if "join key" in f.detail]
    assert len(varchar) == 1
    assert varchar[0].metric == 2


def test_d2_multi_column_count_is_pairs_not_split_fragments():
    """D2 also flags composite joins, and undercounted them.

    The old `=`/`,` split did not separate `and`, so a two-key join produced
    three fragments and reported `3 // 2 = 1` key.
    """
    multi = [f for f in run_rule(fx.join_keys_composite(), "D2")
             if "Multi-column" in f.detail]
    assert len(multi) == 1
    assert multi[0].metric == 2, "two key pairs, not one"


def test_d2_single_key_join_is_not_multi_column():
    assert [f for f in run_rule(fx.join_keys_varchar(), "D2")
            if "Multi-column" in f.detail] == []


@pytest.mark.parametrize("rule_id", ["P6", "D2"])
def test_missing_table_tml_reports_nothing_rather_than_guessing(rule_id):
    """No table for the fqn → the type is unknown, which is not the same as INT."""
    assert run_rule(fx.join_keys_table_missing(), rule_id) == []
