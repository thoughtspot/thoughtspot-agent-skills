"""P6 / D2 — the VARCHAR join-key checks, which could not return a finding.

2026-09-22 audit finding 14.1. Two independent killers, both reproduced here:

1. The `on` clause is split on `=`/`,` without stripping the TML brackets, then
   looked up in a map keyed by bare `column_id`. `"[ORDERS::CUST_ID]"` never
   equals `"ORDERS::CUST_ID"`, so `varchar_keys` was always empty.
2. Even with brackets stripped, the type was read from
   `columns[].db_column_properties.data_type` on the MODEL. Model columns carry
   no data type — the schema's own currency anchor records "no data_type on
   formulas[]/columns[]". It lives on the TABLE the column resolves to.

Either alone makes the check inert; it shipped with both. `check_d2` is a
verbatim clone and had the same pair.
"""
import audit_rule_fixtures as fx
from ts_cli.audit.checks_data import check_d2
from ts_cli.audit.checks_perf import check_p6

import pytest

# The contexts are named builders in audit_rule_fixtures (perf.py), so the P6 (and later D2)
# catalog rules' equivalence tests run over exactly these inputs.


@pytest.mark.parametrize("check,cid", [(check_p6, "P6"), (check_d2, "D2")])
def test_bracketed_join_key_is_found(check, cid):
    """Real TML writes `[TABLE::COL]`. This is the shape that returned nothing."""
    findings = check(fx.join_keys_varchar())
    assert len(findings) == 1, "a VARCHAR join key must be reported"
    assert findings[0].check_id == cid
    assert "CUST_ID" in findings[0].detail


@pytest.mark.parametrize("check", [check_p6, check_d2])
def test_integer_join_key_is_not_reported(check):
    assert check(fx.join_keys_integer()) == []


@pytest.mark.parametrize("check", [check_p6, check_d2])
def test_type_comes_from_the_table_not_the_model(check):
    """Model columns carry no data type; putting one there must not fake a pass."""
    # the model column claims INT64 — a lie, and ignored
    assert len(check(fx.join_keys_type_on_model_ignored())) == 1, \
        "the TABLE's VARCHAR is what counts"


@pytest.mark.parametrize("check", [check_p6, check_d2])
def test_composite_key_counts_both_varchar_sides(check):
    varchar = [f for f in check(fx.join_keys_composite())
               if "join key" in f.detail]
    assert len(varchar) == 1
    assert varchar[0].metric == 2


def test_d2_multi_column_count_is_pairs_not_split_fragments():
    """D2 also flags composite joins, and undercounted them.

    The old `=`/`,` split did not separate `and`, so a two-key join produced
    three fragments and reported `3 // 2 = 1` key.
    """
    multi = [f for f in check_d2(fx.join_keys_composite())
             if "Multi-column" in f.detail]
    assert len(multi) == 1
    assert multi[0].metric == 2, "two key pairs, not one"


def test_d2_single_key_join_is_not_multi_column():
    assert [f for f in check_d2(fx.join_keys_varchar())
            if "Multi-column" in f.detail] == []


@pytest.mark.parametrize("check", [check_p6, check_d2])
def test_missing_table_tml_reports_nothing_rather_than_guessing(check):
    """No table for the fqn → the type is unknown, which is not the same as INT."""
    assert check(fx.join_keys_table_missing()) == []
