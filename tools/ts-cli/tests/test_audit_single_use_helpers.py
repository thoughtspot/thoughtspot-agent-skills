"""H15: hidden formulas used by exactly one other formula (fields_human, single-use helpers)."""
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


def _h15(formulas, columns, **extra):
    model = {"name": "M", "model_tables": [{"name": "T"}], "formulas": formulas,
             "columns": columns, **extra}
    data = run_audit(None, ["m-1"], ctx=make_context(
        models=[{"guid": "m-1", "model": model}], model_guids=["m-1"]), angles=["H"])
    return sorted((f["severity"], f["detail"]) for f in data["findings"]
                  if f["check_id"] == "H15")


PARENT = _col("Net Sales", "formula_Net")


def test_a_hidden_helper_one_formula_uses_is_reported_with_its_inlined_length():
    found = _h15([_f("formula_Net", "Net Sales", "[formula_Disc] * 2"),
                  _f("formula_Disc", "Discounts", "sum ( [T::D] )")],
                 [PARENT, _col("Discounts", "formula_Disc", hidden=True)])
    # "( sum ( [T::D] ) ) * 2" is 22 characters
    assert found == [("LOW", "Hidden formula 'Discounts' is used only by 'Net Sales'; pasting "
                      "it in removes a level of nesting ('Net Sales' would be 22 characters with every such helper pasted in)")]


def test_a_formula_no_column_shows_counts_as_hidden_and_a_display_name_ref_counts():
    found = _h15([_f("formula_Net", "Net Sales", "[Disc Shown] + [helper_f]"),
                  _f("formula_Helper", "helper_f", "1"),
                  _f("formula_Disc", "disc_f", "2")],
                 [PARENT, _col("Disc Shown", "formula_Disc", hidden=True)])
    assert sorted(d.split("'")[1] for _, d in found) == ["Disc Shown", "helper_f"]


def test_a_helper_its_one_user_references_twice_is_not_reported():
    # pasting it in would write it twice: the helper is doing a job
    assert _h15([_f("formula_Net", "Net Sales", "if ( [formula_D] > 0 ) then [formula_D] else 0"),
                 _f("formula_D", "D", "x")],
                [PARENT, _col("D", "formula_D", hidden=True)]) == []


def test_the_message_names_the_helper_as_people_search_it_and_other_refs_count_as_written():
    found = _h15([_f("formula_Net", "Net Sales", "[formula_d_internal] + [T::COL]"),
                  _f("formula_d_internal", "d_internal", "1")],
                 [PARENT, _col("Discount Shown", "formula_d_internal", hidden=True)])
    # "( 1 ) + [T::COL]" is 16 characters
    assert found == [("LOW", "Hidden formula 'Discount Shown' is used only by 'Net Sales'; pasting "
                      "it in removes a level of nesting ('Net Sales' would be 16 characters with every such helper pasted in)")]


def test_a_visible_helper_a_reused_helper_and_a_root_are_not_reported():
    assert _h15([_f("formula_Net", "Net Sales", "[formula_V] + [formula_R]"),
                 _f("formula_M", "Margin", "[formula_R]"),
                 _f("formula_V", "V", "1"), _f("formula_R", "R", "2")],
                [PARENT, _col("Margin", "formula_M", hidden=True), _col("V", "formula_V"),
                 _col("R", "formula_R", hidden=True)]) == []


def test_a_helper_a_model_filter_or_a_currency_setting_names_is_not_reported():
    formulas = [_f("formula_Net", "Net Sales", "[formula_d_internal]"),
                _f("formula_d_internal", "d_internal", "1")]
    columns = [PARENT, _col("Shown D", "formula_d_internal", hidden=True)]
    # a filter names the column by its display name, not the formula's
    assert _h15(formulas, columns, filters=[{"column": ["Shown D"], "oper": "in"}]) == []
    assert _h15(formulas, columns, filters=[{"column": "Shown D"}]) == []
    assert len(_h15(formulas, columns, filters=[{"column": ["Other"]}, {"oper": "in"}])) == 1
    amount = {"name": "Amount", "column_id": "T::AMOUNT",
              "properties": {"column_type": "MEASURE", "currency_type": {"column": "Shown D"}}}
    assert _h15(formulas, columns + [amount]) == []


def test_the_length_limit_is_inclusive_at_250():
    def at(n):  # parent "[formula_D]" -> "( <expr> )": expr of n - 4 characters
        return _h15([_f("formula_Net", "Net Sales", "[formula_D]"),
                     _f("formula_D", "D", "x" * (n - 4))],
                    [PARENT, _col("D", "formula_D", hidden=True)])
    assert len(at(250)) == 1
    assert at(251) == []


def test_a_cycle_and_a_self_reference_are_not_reported():
    assert _h15([_f("formula_A", "A", "[formula_B]"), _f("formula_B", "B", "[formula_A]")],
                [_col("A", "formula_A", hidden=True), _col("B", "formula_B", hidden=True)]) == []
    assert _h15([_f("formula_Net", "Net Sales", "[formula_H] * 2"),
                 _f("formula_H", "H", "[formula_H] + 1")],
                [PARENT, _col("H", "formula_H", hidden=True)]) == []


def _item(model, i):
    return {"obj": model["formulas"][i], "index": i, "parent": {"obj": model}}


def test_malformed_formulas_give_no_value_and_no_error():
    from ts_cli.audit.engine.fields_human import _formula_hidden, _inlined_length_field
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
    assert _h15([_f("formula_Net", "Net Sales", "[formula_D2] * 10"),
                 _f("formula_D", "D", "sum ( [T::ONE] )"), _f("formula_D2", "D", "sum ( [T::TWO] )")],
                [PARENT]) == []


def test_a_helper_whose_one_user_is_hidden_and_unused_is_not_reported():
    # remove both instead: pasting into a formula nothing uses is not the fix
    assert _h15([_f("formula_X", "X", "[formula_Y] + 1"), _f("formula_Y", "Y", "2")],
                [_col("X", "formula_X", hidden=True), _col("Y", "formula_Y", hidden=True)]) == []


@pytest.mark.parametrize("user_expr, helper_expr", [
    # thoughtspot-formula-patterns.md, group functions rule 2: no group inside a group
    ("group_sum ( [formula_H] , [T::REGION] )", "group_count ( [T::ID] , [T::CATEGORY] )"),
    # rule 4: no raw aggregate inside a window function
    ("moving_sum ( [formula_H] , -1 , 0 , [T::ORDER_DATE] )", "sum ( [T::AMOUNT] )"),
    # an aggregate reached through another formula still aggregates
    ("cumulative_sum ( [formula_H] , [T::D] )", "[formula_Base] * 2"),
    # anything as a group function's grouping column
    ("group_sum ( [T::AMT] , [formula_H] )", "if ( [T::X] > 0 ) then 'a' else 'b'"),
    # an aggregate inside an aggregate
    ("sum ( [formula_H] )", "average ( [T::A] )"),
])
def test_a_paste_thoughtspot_would_reject_is_not_reported(user_expr, helper_expr):
    assert _h15([_f("formula_Net", "Net Sales", user_expr), _f("formula_H", "H", helper_expr),
                 _f("formula_Base", "Base", "sum ( [T::B] )")],
                [PARENT, _col("H", "formula_H", hidden=True), _col("Base", "formula_Base")]) == []


@pytest.mark.parametrize("user_expr, helper_expr", [
    # a row-level helper inside an aggregate is fine: sum ( ( [T::A] * 2 ) )
    ("sum ( [formula_H] )", "[T::A] * 2"),
    # an aggregate after a closed call, and a bracket in a quoted literal
    ("sum ( [T::A] ) + [formula_H] + strlen ( ')(' )", "average ( [T::B] )"),
])
def test_a_paste_outside_those_calls_is_reported(user_expr, helper_expr):
    assert len(_h15([_f("formula_Net", "Net Sales", user_expr), _f("formula_H", "H", helper_expr)],
                    [PARENT, _col("H", "formula_H", hidden=True)])) == 1


def test_the_limit_counts_every_helper_of_one_formula_together():
    helpers = [_f(f"formula_H{i}", f"H{i}", "x" * 60) for i in range(5)]
    user = _f("formula_Net", "Net Sales", " + ".join(f"[formula_H{i}]" for i in range(5)))
    cols = [PARENT] + [_col(f"H{i}", f"formula_H{i}", hidden=True) for i in range(5)]
    # each alone would pass (4 * 13 + 4 * 3 + 64 = 128); all five pasted is
    # 5 * 64 + 4 * 3 = 332, so none of them is reported
    assert _h15([user] + helpers, cols) == []
    # three, beside two columns: 3 * 64 + 4 * 3 + 2 * 6 = 216
    user3 = _f("formula_Net", "Net Sales", " + ".join(f"[formula_H{i}]" for i in range(3)) +
               " + [T::A] + [T::B]")
    found = _h15([user3] + helpers[:3], cols[:4])
    assert len(found) == 3
    assert {d.split("would be ")[1].split(" ")[0] for _, d in found} == {"216"}


def test_a_chain_is_measured_in_the_formula_it_ends_up_in():
    # B is pasted into C, C into Top: both findings name Top and its full length
    found = _h15([_f("formula_Top", "Top", "[formula_C] * 2"),
                  _f("formula_C", "C", "[formula_B] + 1"), _f("formula_B", "B", "y")],
                 [_col("Top", "formula_Top"), _col("C", "formula_C", hidden=True),
                  _col("B", "formula_B", hidden=True)])
    # "( ( y ) + 1 ) * 2" is 17 characters
    assert [d.split("; ")[1] for _, d in found] == [
        "pasting it in removes a level of nesting ('Top' would be 17 characters with every "
        "such helper pasted in)"] * 2
