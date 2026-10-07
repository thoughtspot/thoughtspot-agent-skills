"""BL-334 item 2 — the Monday-week-start advisory, one note across every translator.

Every translation built on a week-dependent ThoughtSpot function silently assumes a
Monday week start. Translators do not emit a calendar argument (the Model's calendar
is the default); they flag the assumption with ``formula_common.week_start_note``.
Each reporting path is tested for: the note appears for a week-dependent formula,
does NOT appear for a month truncation, and never changes the status.
"""
from __future__ import annotations

import pytest

from ts_cli.formula_common import (
    WEEK_START_NOTE_PREFIX,
    week_dependent_functions,
    week_start_note,
)


def _is_week_note(text: str) -> bool:
    return text.startswith(WEEK_START_NOTE_PREFIX)


# ---------------------------------------------------------------- the helper

class TestHelper:
    @pytest.mark.parametrize("expr, fns", [
        ("start_of_week ( [T::d] )", ["start_of_week"]),
        ("day_number_of_week ( [T::d] )", ["day_number_of_week"]),
        ("mod(day_number_of_week(OrderDate), 7)", ["day_number_of_week"]),
        ("week_number_of_year ( [T::d] ) + week_number_of_month ( [T::d] )",
         ["week_number_of_year", "week_number_of_month"]),
        ("week_number_of_quarter ( [T::d] )", ["week_number_of_quarter"]),
        ("diff_weeks ( [T::b] , [T::a] )", ["diff_weeks"]),
        # repeated calls are reported once, first-seen order
        ("start_of_week ( [a] ) = start_of_week ( [b] ) and day_number_of_week ( [a] ) = 1",
         ["start_of_week", "day_number_of_week"]),
    ])
    def test_detects_week_dependent_calls(self, expr, fns):
        assert week_dependent_functions(expr) == fns
        note = week_start_note(expr)
        assert note and _is_week_note(note)
        assert all(f in note for f in fns)

    @pytest.mark.parametrize("expr", [
        "start_of_month ( [T::d] )",
        "start_of_quarter ( [T::d] )",
        "day_of_week ( [T::d] )",      # the day NAME does not move with the week start
        "is_weekend ( [T::d] )",
        "add_weeks ( [T::d] , 2 )",
        "'start_of_week ( x )'",        # a string literal, not a call
        "[T::start_of_week (legacy)]",  # a column name, not a call
        "",
        None,
    ])
    def test_not_flagged(self, expr):
        assert week_dependent_functions(expr) == []
        assert week_start_note(expr) is None

    def test_note_says_no_calendar_argument_and_cites_bl334(self):
        note = week_start_note("start_of_week ( [T::d] )")
        assert "Model's calendar" in note and "No calendar argument" in note
        assert "BL-334" in note


# ---------------------------------------------------- ts formula translate traps

class TestFormulaTranslateTraps:
    def test_trap_is_the_shared_note_and_does_not_downgrade(self):
        from ts_cli.formula_translate.engine import translate
        from ts_cli.formula_translate.adapters import TRANSLATED
        r = translate("DATE_TRUNC('week', order_date)", "snowflake")
        assert r["status"] == TRANSLATED
        assert week_start_note(r["formula"]) in r["traps"]

    def test_month_truncation_has_no_week_trap(self):
        from ts_cli.formula_translate.traps import detect_traps
        traps = detect_traps("snowflake", "DATE_TRUNC('month', d)", "start_of_month ( [T::d] )")
        assert not any(_is_week_note(t) for t in traps)

    def test_week_note_is_not_a_downgrade_prefix(self):
        from ts_cli.formula_translate.traps import is_downgrade
        assert not is_downgrade(week_start_note("start_of_week ( [T::d] )"))

    def test_excel_networkdays_flagged(self):
        from ts_cli.formula_translate.engine import translate
        r = translate("=NETWORKDAYS(A1, B1)", "excel")
        assert "day_number_of_week" in (r["formula"] or "")
        assert any(_is_week_note(t) for t in r["traps"])


# ---------------------------------------------------------------- Tableau

class TestTableau:
    def _translate(self, formula):
        from ts_cli.tableau_translate import translate_formulas
        calcs = [{"caption": "F", "name": "[Calculation_1]", "role": "dimension",
                  "datatype": "date", "formula": formula}]
        return translate_formulas(calcs)

    def test_datetrunc_week_carries_review_note_and_warning(self):
        res = self._translate("DATETRUNC('week', [Order Date])")
        rec = res["translated"][0]
        assert "start_of_week" in rec["expr"]
        assert any(_is_week_note(n) for n in rec["review_notes"])
        from ts_cli.tableau.validate import validate_pre_import
        issues = validate_pre_import(res["translated"])
        assert any(_is_week_note(w) for i in issues for w in i["warnings"])

    def test_datetrunc_month_has_no_note(self):
        rec = self._translate("DATETRUNC('month', [Order Date])")["translated"][0]
        assert "start_of_month" in rec["expr"]
        assert "review_notes" not in rec


# ---------------------------------------------------------------- Snowflake SV

_SV_DDL = """
create or replace semantic view SV_W
  tables ( F )
  relationships ( )
  dimensions (
    F.WK as DATE_TRUNC('week', F.ORDER_DATE),
    F.MO as DATE_TRUNC('month', F.ORDER_DATE)
  )
  metrics ( F.REV as SUM(F.AMOUNT) );
"""


class TestSnowflakeSV:
    def test_week_dimension_annotated_month_not(self):
        from ts_cli.sv_parse import parse_sv_ddl
        from ts_cli.sv_translate import translate_sv_formulas
        out = translate_sv_formulas(parse_sv_ddl(_SV_DDL))
        by = {e["name"]: e for e in out["translated"]}
        assert "start_of_week" in by["WK"]["ts_expr"]
        assert any(_is_week_note(a) for a in by["WK"]["annotations"])
        assert not any(_is_week_note(a) for a in by["MO"]["annotations"])
        assert not out["skipped"]  # advisory only — nothing skipped


# ---------------------------------------------------------------- Databricks MV

class TestDatabricksMV:
    def test_week_dimension_annotated_month_not(self):
        from ts_cli.databricks.mv_translate import WEEK_START_KIND, translate_metric_view

        def dim(name, expr):
            return {"name": name, "expr": expr, "kind": "computed", "display_name": None,
                    "comment": None, "synonyms": [], "inner_agg": None,
                    "inner_expr": None, "partition_by": []}
        parsed = {"version": "1.1", "comment": None,
                  "source": {"kind": "table_fqn", "raw": "c.s.t", "parts": ["c", "s", "t"],
                             "needs_live_check": True},
                  "joins": [], "dimensions": [dim("wk", "DATE_TRUNC('WEEK', dt)"),
                                              dim("mo", "DATE_TRUNC('MONTH', dt)")],
                  "measures": [], "filter": None,
                  "materialization": None, "warnings": [], "unsupported": []}
        out = translate_metric_view(parsed, {"source": "T"})
        by = {e["name"]: e for e in out["translated"]}
        assert "start_of_week" in by["wk"]["ts_expr"]
        week = [a for a in by["wk"]["annotations"] if a["kind"] == WEEK_START_KIND]
        assert len(week) == 1 and _is_week_note(week[0]["detail"])
        assert not any(a["kind"] == WEEK_START_KIND for a in by["mo"]["annotations"])
        assert not out["skipped"]


# ---------------------------------------------------------------- Qlik

class TestQlik:
    def _measure(self, expr):
        return type("M", (), {"label": "M", "id": "m1", "expression": expr})()

    def test_weekstart_review_note_status_unchanged(self):
        from ts_cli.qlik.build_model import _translate_measures
        _, mapping = _translate_measures([self._measure("Max(WeekStart(OrderDate))")])
        assert mapping[0]["status"] == "OK"
        assert any(_is_week_note(n) for n in mapping[0]["review_notes"])

    def test_monthstart_has_no_note(self):
        from ts_cli.qlik.build_model import _translate_measures
        _, mapping = _translate_measures([self._measure("Max(MonthStart(OrderDate))")])
        assert "review_notes" not in mapping[0]
