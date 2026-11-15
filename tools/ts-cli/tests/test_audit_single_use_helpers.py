"""H16: hidden formulas used by exactly one other formula (engine/fields_single_use.py)."""
from __future__ import annotations

import pytest

from ts_cli.audit import run_audit
from ts_cli.audit.context import make_context


def _f(fid, name, expr):
    return {"id": fid, "name": name, "expr": expr}


def _col(name, fid, hidden=False):
    props = {"column_type": "MEASURE"}
    if hidden:
        props["is_hidden"] = True
    return {"name": name, "formula_id": fid, "properties": props}


def _h16(formulas, columns, **extra):
    model = {"name": "M", "model_tables": [{"name": "T"}], "formulas": formulas,
             "columns": columns, **extra}
    data = run_audit(None, ["m-1"], ctx=make_context(
        models=[{"guid": "m-1", "model": model}], model_guids=["m-1"]), angles=["H"])
    return sorted((f["severity"], f["detail"]) for f in data["findings"]
                  if f["check_id"] == "H16")


PARENT = _col("Net Sales", "formula_Net")


def test_a_hidden_helper_one_formula_uses_is_reported_with_its_inlined_length():
    found = _h16([_f("formula_Net", "Net Sales", "[formula_Disc] * 2"),
                  _f("formula_Disc", "Discounts", "sum ( [T::D] )")],
                 [PARENT, _col("Discounts", "formula_Disc", hidden=True)])
    # "( sum ( [T::D] ) ) * 2" is 22 characters
    assert found == [("LOW", "Hidden formula 'Discounts' is used only by 'Net Sales'; pasting "
                      "it in removes a level of nesting ('Net Sales' would be 22 characters with every such helper pasted in)")]


def test_a_formula_no_column_shows_counts_as_hidden_and_a_display_name_ref_counts():
    found = _h16([_f("formula_Net", "Net Sales", "[Disc Shown] + [helper_f]"),
                  _f("formula_Helper", "helper_f", "1"),
                  _f("formula_Disc", "disc_f", "2")],
                 [PARENT, _col("Disc Shown", "formula_Disc", hidden=True)])
    assert sorted(d.split("'")[1] for _, d in found) == ["Disc Shown", "helper_f"]


def test_a_helper_its_one_user_references_twice_is_not_reported():
    # pasting it in would write it twice: the helper is doing a job
    assert _h16([_f("formula_Net", "Net Sales", "if ( [formula_D] > 0 ) then [formula_D] else 0"),
                 _f("formula_D", "D", "x")],
                [PARENT, _col("D", "formula_D", hidden=True)]) == []


def test_the_message_names_the_helper_as_people_search_it_and_other_refs_count_as_written():
    found = _h16([_f("formula_Net", "Net Sales", "[formula_d_internal] + [T::COL]"),
                  _f("formula_d_internal", "d_internal", "1")],
                 [PARENT, _col("Discount Shown", "formula_d_internal", hidden=True)])
    # "( 1 ) + [T::COL]" is 16 characters
    assert found == [("LOW", "Hidden formula 'Discount Shown' is used only by 'Net Sales'; pasting "
                      "it in removes a level of nesting ('Net Sales' would be 16 characters with every such helper pasted in)")]


def test_a_visible_helper_a_reused_helper_and_a_root_are_not_reported():
    assert _h16([_f("formula_Net", "Net Sales", "[formula_V] + [formula_R]"),
                 _f("formula_M", "Margin", "[formula_R]"),
                 _f("formula_V", "V", "1"), _f("formula_R", "R", "2")],
                [PARENT, _col("Margin", "formula_M", hidden=True), _col("V", "formula_V"),
                 _col("R", "formula_R", hidden=True)]) == []


def test_a_helper_a_model_filter_or_a_currency_setting_names_is_not_reported():
    formulas = [_f("formula_Net", "Net Sales", "[formula_d_internal]"),
                _f("formula_d_internal", "d_internal", "1")]
    columns = [PARENT, _col("Shown D", "formula_d_internal", hidden=True)]
    # a filter names the column by its display name, not the formula's
    assert _h16(formulas, columns, filters=[{"column": ["Shown D"], "oper": "in"}]) == []
    assert _h16(formulas, columns, filters=[{"column": "Shown D"}]) == []
    assert len(_h16(formulas, columns, filters=[{"column": ["Other"]}, {"oper": "in"}])) == 1
    amount = {"name": "Amount", "column_id": "T::AMOUNT",
              "properties": {"column_type": "MEASURE", "currency_type": {"column": "Shown D"}}}
    assert _h16(formulas, columns + [amount]) == []


def test_the_length_limit_is_inclusive_at_250():
    def at(n):  # parent "[formula_D]" -> "( <expr> )": expr of n - 4 characters
        return _h16([_f("formula_Net", "Net Sales", "[formula_D]"),
                     _f("formula_D", "D", "x" * (n - 4))],
                    [PARENT, _col("D", "formula_D", hidden=True)])
    assert len(at(250)) == 1
    assert at(251) == []


def test_a_cycle_and_a_self_reference_are_not_reported():
    assert _h16([_f("formula_A", "A", "[formula_B]"), _f("formula_B", "B", "[formula_A]")],
                [_col("A", "formula_A", hidden=True), _col("B", "formula_B", hidden=True)]) == []
    assert _h16([_f("formula_Net", "Net Sales", "[formula_H] * 2"),
                 _f("formula_H", "H", "[formula_H] + 1")],
                [PARENT, _col("H", "formula_H", hidden=True)]) == []


def _item(model, i):
    return {"obj": model["formulas"][i], "index": i, "parent": {"obj": model}}


def test_malformed_formulas_give_no_value_and_no_error():
    from ts_cli.audit.engine.fields_single_use import _formula_hidden, _inlined_length_field
    model = {"formulas": [_f("formula_Net", "Net Sales", "[formula_D]"),
                          _f("formula_D", "D", ["not", "text"]),
                          {"id": "formula_X", "name": ["a", "list"], "expr": "1"}],
             "columns": [PARENT, _col("D", "formula_D", hidden=True)]}
    # a non-text expression has no length, so no finding
    assert _inlined_length_field(_item(model, 1), None) is None
    # a name that is not text (BL-501) is skipped, not an unhashable-key error
    assert _formula_hidden(_item(model, 2), None) is False


def test_a_name_two_formulas_share_is_not_reported():
    # the tree keeps one formula of a name, so "used only by" could be false and the
    # paste could be the wrong formula
    assert _h16([_f("formula_Net", "Net Sales", "[formula_D2] * 10"),
                 _f("formula_D", "D", "sum ( [T::ONE] )"), _f("formula_D2", "D", "sum ( [T::TWO] )")],
                [PARENT]) == []


def test_a_helper_whose_one_user_is_hidden_and_unused_is_not_reported():
    # remove both instead: pasting into a formula nothing uses is not the fix
    assert _h16([_f("formula_X", "X", "[formula_Y] + 1"), _f("formula_Y", "Y", "2")],
                [_col("X", "formula_X", hidden=True), _col("Y", "formula_Y", hidden=True)]) == []


@pytest.mark.parametrize("user_expr, helper_expr", [
    # an aggregating helper inside any aggregate-family call
    # (a group or window helper is written `… * 1`: a bare one is refused before the
    # paste guard, which these cases test)
    ("group_sum ( [formula_H] , [T::REGION] )", "group_count ( [T::ID] , [T::CATEGORY] ) * 1"),
    ("moving_sum ( [formula_H] , -1 , 0 , [T::ORDER_DATE] )", "sum ( [T::AMOUNT] )"),
    ("moving_sum ( abs ( [formula_H] ) , -1 , 0 , [T::D] )", "sum ( [T::A] )"),
    ("cumulative_sum ( [formula_H] , [T::D] )", "[formula_Base] * 2"),
    ("sum ( [formula_H] )", "average ( [T::A] )"),
    ("if ( [T::FLAG] = 1 ) then count ( [formula_H] ) else 0", "sum ( [T::A] )"),
    ("if ( [T::X] = 0 or unique count ( [formula_H] ) > 1 ) then 1 else 0", "max ( [T::A] )"),
    ('sql_int_aggregate_op ( "sum({0})" , [formula_H] )', "sum ( [T::A] )"),
    ("group_sum ( [formula_H] , [T::REGION] )", "sum ( [T::AMOUNT] )"),
    ("rank ( [formula_H] , 'desc' )", "group_aggregate ( sum ( [T::M] ) , { [T::A] } , query_filters ( ) ) * 1"),
    ("rank ( [formula_H] , 'desc' )", "sum ( [T::QUANTITY] )"),
    ("rank ( [formula_H] , 'desc' )", "cumulative_sum ( [T::A] , [T::D] )"),
    ("group_aggregate ( [formula_H] , { [T::REGION] } , query_filters ( ) )", "sum ( [T::AMOUNT] )"),
    ("last_value ( [formula_H] , query_groups ( ) , { [T::DATE] } )", "sum ( [T::BALANCE] )"),
    ("moving_sum ( [formula_H] , -1 , 0 , [T::ORDER_DATE] )",
     "group_aggregate ( sum ( [T::AMOUNT] ) , { [T::PK] } , query_filters ( ) ) * 1"),
    ("sum ( [formula_H] )", "group_sum ( [T::AMOUNT] , [T::REGION] ) * 1"),
    ("sum ( [formula_H] )", "sum ( [T::A] ) / group_sum ( [T::A] , [T::R] )"),
    # a row-level helper in any slot of a group, window, rank or last_value call
    ("group_sum ( [T::AMT] , [formula_H] )", "if ( [T::X] > 0 ) then 'a' else 'b'"),
    ("group_aggregate ( sum ( [T::A] ) , { [formula_H] } , query_filters ( ) )", "[T::X] * 2"),
    ("last_value ( sum ( [T::A] ) , query_groups ( ) , { [formula_H] } )", "to_date ( [T::S] )"),
    ("rank ( [formula_H] , 'desc' )", "[T::A] * 2"),
    ("moving_sum ( [formula_H] , -1 , 0 , [T::D] )", "[T::A] * 2"),
    # a bare row-level helper beside an aggregate: it may roll up differently
    ("sum ( [T::X] ) / [formula_H]", "[T::A] * [T::B]"),
    ("[formula_H] + count ( [T::ID] )", "[T::A] * [T::B]"),
    # a reference's name is never read as code: read whole, the apostrophes would pair
    # across `max (` and the helper would look row-level
    ("sum ( [formula_H] )", "[T::OWNER'S TOTAL] * max ( [T::OWNER'S X] )"),
    ("moving_sum ( [formula_H] , -1 , 0 , [T::D] )", "sum ( [T::SALES group_a (EMEA)] )"),
])
def test_a_paste_outside_the_plain_cases_is_not_reported(user_expr, helper_expr):
    assert _h16([_f("formula_Net", "Net Sales", user_expr), _f("formula_H", "H", helper_expr),
                 _f("formula_Base", "Base", "sum ( [T::B] )")],
                [PARENT, _col("H", "formula_H", hidden=True), _col("Base", "formula_Base")]) == []


@pytest.mark.parametrize("user_expr, helper_expr", [
    # a row-level helper inside plain aggregates: sum ( ( [T::A] * 2 ) )
    ("sum ( [formula_H] )", "[T::A] * 2"),
    ("safe_divide ( sum ( [formula_H] ) , count ( [T::ID] ) )", "[T::A] * [T::B]"),
    # a row-level helper in a formula that does not aggregate
    ("[formula_H] + 1", "[T::A] * [T::B]"),
    # an aggregating helper with no aggregate around it
    ("sum ( [T::A] ) + [formula_H] + strlen ( ')(' )", "average ( [T::B] )"),
    ("safe_divide ( [formula_H] , sum ( [T::B] ) )", "sum ( [T::A] )"),
    ("[formula_H] + 1", "sum ( [T::A] ) / group_sum ( [T::A] , [T::R] )"),
    ("concat ( 'O''Neil' , [formula_H] )", "max ( [T::NAME] )"),
    # a backslash-escaped quote does not end the literal (the shared grammar): read
    # with a quotes-only grammar, `sum (` would look like a call around the reference
    ("concat ( 'a\\'sum (' , [formula_H] )", "max ( [T::NAME] )"),
    # a reference whose name reads like a call is not a call: H stays row-level
    ("sum ( [formula_H] )", "[T::SALES group_a (EMEA)] * 2"),
    ("sum ( [formula_H] )", "[T::Max (Q1)] * 2"),
])
def test_a_paste_in_the_plain_cases_is_reported(user_expr, helper_expr):
    assert len(_h16([_f("formula_Net", "Net Sales", user_expr), _f("formula_H", "H", helper_expr)],
                    [PARENT, _col("H", "formula_H", hidden=True)])) == 1


def test_a_helper_whose_column_sets_another_aggregation_is_not_reported():
    col = _col("H", "formula_H", hidden=True)
    col["properties"]["aggregation"] = "AVERAGE"
    formulas = [_f("formula_Net", "Net Sales", "[formula_H] * 2"), _f("formula_H", "H", "[T::P] * [T::Q]")]
    assert _h16(formulas, [PARENT, col]) == []
    col["properties"]["aggregation"] = "SUM"
    assert len(_h16(formulas, [PARENT, col])) == 1


def test_a_helper_another_formula_reads_through_a_second_column_is_not_reported():
    # the tree reads [H two] as a column, so H would look used only by U1
    assert _h16([_f("formula_U1", "U1", "[formula_H] * 2"), _f("formula_U2", "U2", "[H two] + 1"),
                 _f("formula_H", "H", "1")],
                [_col("U1", "formula_U1"), _col("U2", "formula_U2"),
                 _col("H one", "formula_H", hidden=True), _col("H two", "formula_H", hidden=True)]) == []


def test_a_filter_on_any_column_that_shows_the_helper_counts():
    formulas = [_f("formula_Net", "Net Sales", "[formula_H] * 2"), _f("formula_H", "H", "1")]
    columns = [PARENT, _col("H one", "formula_H", hidden=True), _col("H two", "formula_H", hidden=True)]
    assert _h16(formulas, columns, filters=[{"column": ["H two"], "oper": "in"}]) == []
    assert _h16(formulas, columns, filters=[{"column": ["H one"], "oper": "in"}]) == []


def test_a_chain_too_deep_to_measure_is_not_reported_and_does_not_end_the_run():
    n = 1200
    formulas = [_f("formula_Top", "Top", "[formula_C0] + 1")] + [
        _f(f"formula_C{i}", f"C{i}", f"[formula_C{i + 1}] + 1") for i in range(n)] + [
        _f(f"formula_C{n}", f"C{n}", "1")]
    columns = [_col("Top", "formula_Top")] + [
        _col(f"C{i}", f"formula_C{i}", hidden=True) for i in range(n + 1)]
    assert _h16(formulas, columns) == []


def test_a_paste_that_would_raise_p16_is_not_reported():
    helper = "if ( [T::A] = 1 ) then 1 else if ( [T::A] = 2 ) then 2 else 0"
    two = _f("formula_Net", "Net Sales", "if ( [T::B] = 1 ) then [formula_H] else if ( [T::B] = 2 ) then 5 else 0")
    one = _f("formula_Net", "Net Sales", "if ( [T::B] = 1 ) then [formula_H] else 0")
    cols = [PARENT, _col("H", "formula_H", hidden=True)]
    assert _h16([two, _f("formula_H", "H", helper)], cols) == []        # 4 if() calls
    assert len(_h16([one, _f("formula_H", "H", helper)], cols)) == 1    # 3


def test_a_model_with_a_shared_formula_name_reports_nothing():
    # the second Net's use of H is dropped from the tree, so "used only by" would be false
    assert _h16([_f("formula_Net", "Net", "[formula_H] * 2"), _f("formula_Net2", "Net", "[formula_H] + 1"),
                 _f("formula_H", "H", "sum ( [T::A] )")],
                [_col("Net", "formula_Net"), _col("Net Two", "formula_Net2"),
                 _col("H", "formula_H", hidden=True)]) == []


def test_a_chain_no_visible_formula_sits_above_is_not_reported():
    # X (hidden, unused) uses C, C uses B: remove the chain, not paste into it
    assert _h16([_f("formula_X", "X", "[formula_C] + 1"), _f("formula_C", "C", "[formula_B] + 2"),
                 _f("formula_B", "B", "3")],
                [_col(n, f"formula_{n}", hidden=True) for n in ("X", "C", "B")]) == []


def test_a_formula_a_visible_column_shows_is_not_hidden():
    # two columns surface H: the hidden one first, then a visible one
    assert _h16([_f("formula_Net", "Net Sales", "[formula_H] * 2"), _f("formula_H", "H", "1")],
                [PARENT, _col("H (old)", "formula_H", hidden=True), _col("Discount", "formula_H")]) == []


def test_the_limit_counts_every_helper_of_one_formula_together():
    helpers = [_f(f"formula_H{i}", f"H{i}", "x" * 60) for i in range(5)]
    user = _f("formula_Net", "Net Sales", " + ".join(f"[formula_H{i}]" for i in range(5)))
    cols = [PARENT] + [_col(f"H{i}", f"formula_H{i}", hidden=True) for i in range(5)]
    # each alone would pass (4 * 13 + 4 * 3 + 64 = 128); all five pasted is
    # 5 * 64 + 4 * 3 = 332, so none of them is reported
    assert _h16([user] + helpers, cols) == []
    # three, beside two columns: 3 * 64 + 4 * 3 + 2 * 6 = 216
    user3 = _f("formula_Net", "Net Sales", " + ".join(f"[formula_H{i}]" for i in range(3)) +
               " + [T::A] + [T::B]")
    found = _h16([user3] + helpers[:3], cols[:4])
    assert len(found) == 3
    assert {d.split("would be ")[1].split(" ")[0] for _, d in found} == {"216"}


def test_a_chain_is_measured_in_the_formula_it_ends_up_in():
    # B is pasted into C, C into Top: both findings name Top and its full length
    found = _h16([_f("formula_Top", "Top", "[formula_C] * 2"),
                  _f("formula_C", "C", "[formula_B] + 1"), _f("formula_B", "B", "y")],
                 [_col("Top", "formula_Top"), _col("C", "formula_C", hidden=True),
                  _col("B", "formula_B", hidden=True)])
    # "( ( y ) + 1 ) * 2" is 17 characters
    assert [d.split("; ")[1] for _, d in found] == [
        "pasting it in removes a level of nesting ('Top' would be 17 characters with every "
        "such helper pasted in)"] * 2


@pytest.mark.parametrize("helper_expr", [
    "group_sum ( [T::AMT] , [T::REGION] )",
    "( group_sum ( [T::AMT] , [T::REGION] ) )",
    "( last_value ( sum ( [T::BAL] ) , query_groups ( ) , { [T::DATE] } ) )",
    "group_aggregate ( sum ( [T::A] ) , { [T::R] } , query_filters ( ) + { [T::S] = 'x)' } )",
    "group_max ( [T::AMOUNT (USD] , [T::REGION] )",
    "last_value ( sum ( [T::BAL] ) , query_groups ( ) , { [T::DATE] } )",
    "group_aggregate ( sum ( [T::A] ) , { [T::R] } , query_filters ( ) )",
])
def test_a_bare_window_or_group_helper_is_not_reported(helper_expr):
    """Also in redundant brackets, and with a bracket inside a name or a literal."""
    # its column aggregation is applied to its result: pasting drops it
    assert _h16([_f("formula_Net", "Net Sales", "[formula_H] / 1000"), _f("formula_H", "H", helper_expr)],
                [PARENT, _col("H", "formula_H", hidden=True)]) == []


def test_a_malformed_formula_id_is_skipped_not_fatal():
    bad = _col("Odd", "formula_X")
    bad["formula_id"] = ["not", "text"]
    found = _h16([_f("formula_Net", "Net Sales", "[formula_D] * 2"), _f("formula_D", "D", "1")],
                 [PARENT, _col("D", "formula_D", hidden=True), bad])
    assert len(found) == 1


def test_a_model_where_a_formula_is_read_through_a_second_column_reports_nothing():
    # the aggregate Agg is read through "Agg two", which the shared index does not
    # resolve: Net Sales would look row-level and H's bare paste beside it would pass
    cols = [PARENT, _col("H", "formula_H", hidden=True),
            _col("Agg one", "formula_Agg"), _col("Agg two", "formula_Agg", hidden=True)]
    formulas = [_f("formula_H", "H", "[T::A] * [T::B]"), _f("formula_Agg", "Agg", "sum ( [T::C] )")]
    assert _h16(formulas + [_f("formula_Net", "Net Sales", "[formula_H] + [Agg two]")], cols) == []
    # through the first column it resolves: Net Sales aggregates, so the bare paste is refused
    assert _h16(formulas + [_f("formula_Net", "Net Sales", "[formula_H] + [Agg one]")], cols) == []
    assert len(_h16(formulas + [_f("formula_Net", "Net Sales", "sum ( [formula_H] ) + [Agg one]")],
                    cols)) == 1


def test_the_if_count_reads_reference_names_as_p16_does():
    # P16 counts `if (` in the raw text, a reference's name included: 3 here + 1 = 4
    found = _h16([_f("formula_Net", "Net Sales",
                     "if ( [T::B] = 1 ) then [formula_H] else if ( [T::B] = 2 ) then [T::Margin if (net)] else 0"),
                  _f("formula_H", "H", "if ( [T::A] = 1 ) then 1 else 0")],
                 [PARENT, _col("H", "formula_H", hidden=True)])
    assert found == []


@pytest.mark.parametrize("agg_columns", [
    # the visible column second: the tree labels Agg "Agg two", the index knows "Agg one"
    [("Agg one", True), ("Agg two", False)],
    [("Agg one", False), ("Agg two", True)],
])
def test_a_formula_read_through_any_surfacing_column_name_blocks_the_model(agg_columns):
    cols = [PARENT, _col("H", "formula_H", hidden=True)] + [
        _col(n, "formula_Agg", hidden=h) for n, h in agg_columns]
    base = [_f("formula_Agg", "Agg", "sum ( [T::C] )")]
    for name in ("Agg one", "Agg two"):
        # H row-level beside an aggregate read by column name (through the first column the
        # index resolves Agg, so Net Sales aggregates and the bare paste is refused anyway)
        assert _h16(base + [_f("formula_H", "H", "[T::A] * [T::B]"),
                            _f("formula_Net", "Net Sales", f"[formula_H] + [{name}]")], cols) == []
        # an aggregate read by column name inside H, pasted into sum
        assert _h16(base + [_f("formula_H", "H", f"[{name}] * 2"),
                            _f("formula_Net", "Net Sales", "sum ( [formula_H] )")], cols) == []


def test_a_helper_with_a_number_for_a_column_name_is_not_reported_as_used_once():
    h = _col(2024, "formula_H", hidden=True)
    assert _h16([_f("formula_U1", "U1", "[formula_H] * 2"), _f("formula_U2", "U2", "[2024] + 1"),
                 _f("formula_H", "H", "1")],
                [_col("U1", "formula_U1"), _col("U2", "formula_U2"), h]) == []


def _hc(name, fid):
    return _col(name, fid, hidden=True)


@pytest.mark.parametrize("formulas, columns", [
    # a formula named like another formula's id: the index's answer depends on list order
    ([_f("formula_X", "X", "sum ( [T::A] )"), _f("formula_formula_X", "formula_X", "1"),
      _f("formula_U", "U", "[formula_X] * 2")],
     [_col("U", "formula_U"), _hc("X", "formula_X"), _hc("formula_X", "formula_formula_X")]),
    # a case variant of the helper's id, name or column name
    *[([_f("formula_U1", "U1", "[formula_H] * 2"), _f("formula_U2", "U2", f"{ref} + 1"),
        _f("formula_H", "H", "1")],
       [_col("U1", "formula_U1"), _col("U2", "formula_U2"), _hc("H shown", "formula_H")])
      for ref in ("[FORMULA_H]", "[formula_h]", "[h]", "[h shown]")],
    # a column named like another formula
    ([_f("formula_Rev", "Revenue", "sum ( [T::A] )"), _f("formula_Rev2", "Revenue v2", "sum ( [T::B] )"),
      _f("formula_M", "Margin", "[Revenue] - sum ( [T::COST] )")],
     [_col("Margin", "formula_M"), _hc("Revenue (old)", "formula_Rev"), _hc("Revenue", "formula_Rev2")]),
    # two formulas with one id
    ([_f("formula_U", "U", "[formula_D] * 2"), _f("formula_D", "D", "1"), _f("formula_D", "D2", "2")],
     [_col("U", "formula_U"), _hc("D", "formula_D")]),
])
def test_a_model_that_spells_a_formula_ambiguously_reports_nothing(formulas, columns):
    assert _h16(formulas, columns) == []


def test_a_filter_names_a_column_case_aside():
    formulas = [_f("formula_Net", "Net Sales", "[formula_d_internal]"), _f("formula_d_internal", "d_internal", "1")]
    columns = [PARENT, _col("Shown D", "formula_d_internal", hidden=True)]
    assert _h16(formulas, columns, filters=[{"column": ["shown d"], "oper": "in"}]) == []


@pytest.mark.parametrize("formula_id", [["formula_D"], {"a": 1}])
def test_a_formula_id_that_is_not_text_does_not_end_an_h_run(formula_id):
    found = _h16([_f("formula_Net", "Net Sales", "[formula_D] * 2"), _f("formula_D", "D", "1"),
                  {"id": formula_id, "name": "Odd", "expr": "2"}],
                 [PARENT, _col("D", "formula_D", hidden=True)])
    assert len(found) == 1


@pytest.mark.parametrize("extra", [
    {"columns": [{"name": "Revenue", "column_id": "T::REVENUE", "properties": {"column_type": "MEASURE"}}]},
    {"parameters": [{"name": "Revenue", "data_type": "DOUBLE"}]},
    {"columns": [{"name": "formula_Revenue", "column_id": "T::X", "properties": {"column_type": "MEASURE"}}]},
])
def test_a_formula_spelled_like_a_physical_column_or_parameter_blocks_the_model(extra):
    columns = [PARENT, _col("Revenue calc", "formula_Revenue", hidden=True)] + extra.get("columns", [])
    kw = {"parameters": extra["parameters"]} if "parameters" in extra else {}
    assert _h16([_f("formula_Net", "Net Sales", "[Revenue] * 2"),
                 _f("formula_Revenue", "Revenue", "sum ( [T::A] )")], columns, **kw) == []


def test_names_compare_with_edge_spaces_trimmed():
    assert _h16([_f("formula_U1", "U1", "[formula_H] * 2"), _f("formula_U2", "U2", "[Disc ] + 1"),
                 _f("formula_H", "H", "1")],
                [_col("U1", "formula_U1"), _col("U2", "formula_U2"), _col("Disc ", "formula_H", hidden=True)]) == []


def test_a_formula_with_no_name_blocks_the_model():
    assert _h16([_f("formula_Net", "Net Sales", "[formula_H] * 2"), _f("formula_H", "H", "1"),
                 _f("formula_E", "", "[formula_H] * 3")],
                [PARENT, _col("H", "formula_H", hidden=True)]) == []


@pytest.mark.parametrize("extra", [
    {"constraints": {"constraint": [{"date_range_condition": {"column": "Order Day", "type": "LAST_N"}}]}},
    {"joins_with": [{"name": "j", "with": "Budget", "on": "[M::Order Day] = [Budget::Day]", "type": "INNER"}]},
])
def test_a_helper_a_constraint_or_model_join_names_is_not_reported(extra):
    formulas = [_f("formula_Net", "Net Sales", "[formula_D] + 1"), _f("formula_D", "D", "to_date ( [T::TS] )")]
    columns = [PARENT, _col("Order Day", "formula_D", hidden=True)]
    assert len(_h16(formulas, columns)) == 1
    assert _h16(formulas, columns, **extra) == []


def test_in_a_chain_the_limit_is_measured_on_the_top_formula():
    """The product owner's ruling (2026-11-14): with every such helper pasted in, all the
    way down, a result over 250 reports none of its helpers, even one that would fit one
    level down."""
    top = _f("formula_Top", "Top", "[formula_C] * 2 + " + " + ".join(f"[T::TOP{i}]" for i in range(12)))
    c = _f("formula_C", "C", "[formula_B] + " + " + ".join(f"[T::C{i}]" for i in range(14)))
    b = _f("formula_B", "B", "1")
    cols = [_col("Top", "formula_Top"), _col("C", "formula_C", hidden=True), _col("B", "formula_B", hidden=True)]
    assert _h16([top, c, b], cols) == []
    cols[1] = _col("C", "formula_C")  # C visible: B's target is C, within the limit
    assert len(_h16([top, c, b], cols)) == 1
