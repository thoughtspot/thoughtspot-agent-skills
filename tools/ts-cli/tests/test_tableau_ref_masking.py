"""#589 review — a function name inside a Tableau [field] reference is not a call.

`map_functions` / `map_date_functions` mask every ``[…]`` reference before their
regexes run (``literals.mask_refs``), so a column called ``[WEEK (prior)]`` or
``[Profit LEN(x)]`` keeps its name.
"""
from __future__ import annotations

import pytest

from ts_cli.tableau.functions import map_date_functions, map_functions
from ts_cli.tableau.literals import mask_refs, unmask_refs


@pytest.mark.parametrize("ref", [
    "[WEEK (prior)]", "[ISOWEEK(x)]", "[Sales WEEK(1)]", "[YEAR (prior)]",
    "[Profit LEN(x)]", "[ISOWEEKDAY(d)]", "[DATETRUNC('week', x)]", "[a]]WEEK(b)]",
])
def test_function_names_inside_a_reference_are_untouched(ref):
    assert map_date_functions(f"{ref} + 1") == f"{ref} + 1"
    assert map_functions(f"{ref} + 1") == f"{ref} + 1"


def test_reference_inside_a_call_is_restored():
    assert map_date_functions("WEEK([WEEK (prior)])", None, "monday") == (
        "( floor ( ( day_number_of_year ( [WEEK (prior)] ) - 1 + ( day_number_of_week "
        "( start_of_year ( [WEEK (prior)] ) ) - 1 ) ) / 7 ) + 1 )")
    assert map_functions("LEN([Profit LEN(x)])").replace(" ", "") == "strlen([ProfitLEN(x)])"


def test_mask_round_trip_with_doubled_bracket():
    masked, refs = mask_refs("[a]]b] + [c]")
    assert "[" not in masked and refs == ["[a]]b]", "[c]"]
    assert unmask_refs(masked, refs) == "[a]]b] + [c]"


def test_end_to_end_translation_keeps_the_reference():
    from ts_cli.tableau_translate import translate_formulas
    res = translate_formulas([{"caption": "F", "name": "[C1]", "role": "measure",
                               "datatype": "real",
                               "formula": "SUM([Sales WEEK(1)]) + SUM([YEAR (prior)])"}])
    expr = res["translated"][0]["expr"]
    assert "Sales WEEK(1)" in expr and "YEAR (prior)" in expr
    assert "DATEPART" not in expr and "floor" not in expr
