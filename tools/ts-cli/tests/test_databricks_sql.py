# tools/ts-cli/tests/test_databricks_sql.py
"""Unit tests for ts_cli/databricks/mv_sql.py (BL-063 PR3).

One class per transform, mirroring test_tableau_translate.py. resolver is a
plain fake mapping bare/dotted paths onto a TRANSACTIONS table.
"""
from __future__ import annotations

import pytest

from ts_cli.databricks.mv_sql import UntranslatableError, translate_sql_expr


def _resolver(path: str) -> str:
    from ts_cli.databricks.mv_expr import split_dot_path
    segs = split_dot_path(path)
    return f"[TRANSACTIONS::{segs[-1]}]"


def t(sql: str) -> str:
    return translate_sql_expr(sql, _resolver)


class TestCore:
    def test_bare_column(self):
        assert t("unit_price") == "[TRANSACTIONS::unit_price]"

    def test_dotted_column(self):
        assert t("source.unit_price") == "[TRANSACTIONS::unit_price]"

    def test_arithmetic_spacing(self):
        assert t("unit_price * quantity * (1 - discount)") == \
            "[TRANSACTIONS::unit_price] * [TRANSACTIONS::quantity] * ( 1 - [TRANSACTIONS::discount] )"

    def test_comparison_and_string(self):
        assert t("status != 'cancelled'") == "[TRANSACTIONS::status] != 'cancelled'"

    def test_angle_neq_normalized(self):
        assert t("status <> 'x'") == "[TRANSACTIONS::status] != 'x'"

    def test_and_or_lowercased(self):
        assert t("a = 1 AND b = 2 OR c = 3") == \
            "[TRANSACTIONS::a] = 1 and [TRANSACTIONS::b] = 2 or [TRANSACTIONS::c] = 3"

    def test_true_false_null_lowercased(self):
        assert t("flag = TRUE") == "[TRANSACTIONS::flag] = true"
        assert t("flag = FALSE") == "[TRANSACTIONS::flag] = false"

    def test_date_literal_wrapped(self):
        assert t("d >= '2024-05-01'") == \
            "[TRANSACTIONS::d] >= to_date ( '2024-05-01' , 'yyyy-MM-dd' )"

    def test_plain_string_not_wrapped(self):
        assert t("s = 'Premium'") == "[TRANSACTIONS::s] = 'Premium'"

    def test_placeholder_passthrough(self):
        assert t("__MVREF_0__ / __MVREF_1__") == "__MVREF_0__ / __MVREF_1__"

    def test_number_decimal(self):
        assert t("x * 0.5") == "[TRANSACTIONS::x] * 0.5"

    def test_unknown_operator_raises(self):
        with pytest.raises(UntranslatableError, match=r"\|\|"):
            t("a || b")

    def test_unresolvable_column_raises(self):
        def bad(_path):
            raise UntranslatableError("no table mapped")
        with pytest.raises(UntranslatableError, match="no table mapped"):
            translate_sql_expr("x + 1", bad)

    def test_comment_stripped_before_translation(self):
        assert t("unit_price -- the price") == "[TRANSACTIONS::unit_price]"

    def test_empty_expression_raises(self):
        with pytest.raises(UntranslatableError, match="empty"):
            t("   ")

    def test_current_date_bare_and_called(self):
        assert t("CURRENT_DATE") == "today ( )"
        assert t("d < CURRENT_DATE()") == "[TRANSACTIONS::d] < today ( )"
