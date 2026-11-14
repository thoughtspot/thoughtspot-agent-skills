"""H15: hidden formulas used by exactly one other formula (fields_human, single-use helpers)."""
from __future__ import annotations

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
                      "it in removes a level of nesting ('Net Sales' would be 22 characters)")]


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
                      "it in removes a level of nesting ('Net Sales' would be 16 characters)")]


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


def test_formulas_sharing_a_name_report_once():
    found = _h15([_f("formula_Net", "Net Sales", "[formula_D]"),
                  _f("formula_D", "D", "1"), _f("formula_D2", "D", "2")],
                 [PARENT])
    assert len(found) == 1
