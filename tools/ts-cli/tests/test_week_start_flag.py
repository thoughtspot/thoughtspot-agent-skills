"""BL-334 item 2 — the Monday-week-start advisory, one note across every translator.

Every translation built on a week-dependent ThoughtSpot function silently assumes a
Monday week start. Translators do not emit a calendar argument (the Model's calendar
is the default); they flag the assumption with ``formula_week.week_start_note``.
Each reporting path is tested for: the note appears for a week-dependent formula,
does NOT appear for a month truncation, and never changes the status.
"""
from __future__ import annotations

import pytest

from ts_cli.formula_week import (
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


# ================================================== review fixes (PR #582 review)

from ts_cli.formula_week import (  # noqa: E402
    WEEK_DIFF_DAYS_PREFIX,
    WEEK_START_MISMATCH_PREFIX,
    is_week_review_note,
    week_diff_days_note,
    week_start_mismatch_note,
)


class TestNoteWording:
    def test_case_insensitive(self):
        assert week_dependent_functions("START_OF_WEEK ( [d] )") == ["start_of_week"]
        assert week_start_note("Day_Number_Of_Week ( [d] )")

    def test_start_of_week_carries_the_warehouse_caveat(self):
        note = week_start_note("start_of_week ( [d] )")
        assert "DATE_TRUNC(week, d)" in note and "WEEK_START" in note
        assert "item 3" in note

    def test_day_number_of_week_is_hedged_not_asserted(self):
        note = week_start_note("day_number_of_week ( [d] )")
        assert "independent of WEEK_START" in note and "unverified" in note
        assert "item 4" in note
        assert "values differ" not in note
        assert "DATE_TRUNC" not in note  # tailored: only the clause for what was found

    def test_week_number_clause_names_only_what_was_found(self):
        note = week_start_note("week_number_of_month ( [d] )")
        assert "week_number_of_month" in note and "week_number_of_year" not in note

    def test_mismatch_and_diff_days_are_review_class(self):
        mm = week_start_mismatch_note("the source", 6)
        assert mm.startswith(WEEK_START_MISMATCH_PREFIX) and "Sunday" in mm
        assert week_start_mismatch_note("x", "sunday") == week_start_mismatch_note("x", 6)
        dd = week_diff_days_note("( diff_days ( [b] , [a] ) / 7 )")
        assert dd and dd.startswith(WEEK_DIFF_DAYS_PREFIX)
        assert is_week_review_note(mm) and is_week_review_note(dd)
        assert not is_week_review_note(week_start_note("start_of_week ( [d] )"))
        assert week_diff_days_note("diff_days ( [b] , [a] ) / 2") is None


class TestFormulaTranslateDedupe:
    def test_diff_weeks_gets_one_coherent_week_trap(self):
        from ts_cli.formula_translate.traps import detect_traps
        traps = detect_traps("tableau", "x", "diff_weeks ( [T::b] , [T::a] )")
        assert sum("diff_weeks" in t and "Monday" in t for t in traps) == 1

    def test_tableau_known_mismatch_downgrades(self):
        from ts_cli.formula_translate.engine import translate
        from ts_cli.formula_translate.adapters import APPROXIMATED, TRANSLATED
        r = translate("DATETRUNC('week', [d], 'sunday')", "tableau")
        assert r["status"] == APPROXIMATED
        assert any(t.startswith(WEEK_START_MISMATCH_PREFIX) for t in r["traps"])
        r = translate("DATETRUNC('week', [d], 'monday')", "tableau")
        assert r["status"] == TRANSLATED

    def test_diff_days_over_7_downgrades(self):
        from ts_cli.formula_translate.engine import translate
        from ts_cli.formula_translate.adapters import APPROXIMATED
        r = translate("DATEDIFF('week', [a], [b])", "tableau")
        assert r["status"] == APPROXIMATED
        assert any(t.startswith(WEEK_DIFF_DAYS_PREFIX) for t in r["traps"])


class TestTableauReview:
    def _one(self, formula, **kw):
        from ts_cli.tableau_translate import translate_formulas
        calcs = [{"caption": "F", "name": "[Calculation_1]", "role": "dimension",
                  "datatype": "integer", "formula": formula}]
        return translate_formulas(calcs, **kw)

    def test_datediff_week_needs_review_like_formula_translate(self):
        res = self._one("DATEDIFF('week', [a], [b])")
        rec = res["translated"][0]
        assert rec["review_required"] is True
        assert any(n.startswith(WEEK_DIFF_DAYS_PREFIX) for n in rec["review_notes"])
        assert res["stats"]["review_required"] == 1
        from ts_cli.tableau.validate import validate_pre_import
        assert any(w.startswith(WEEK_DIFF_DAYS_PREFIX)
                   for i in validate_pre_import(res["translated"]) for w in i["warnings"])

    @pytest.mark.parametrize("formula, kw", [
        ("DATETRUNC('week', [d], 'sunday')", {}),
        ("DATETRUNC('week', [d])", {"week_start": "sunday"}),
        ("DATEPART('week', [d])", {"week_start": "sunday"}),
    ])
    def test_known_non_monday_start_is_a_mismatch(self, formula, kw):
        res = self._one(formula, **kw)
        rec = res["translated"][0]
        assert rec["review_required"] is True
        assert any(n.startswith(WEEK_START_MISMATCH_PREFIX) and "Sunday" in n
                   for n in rec["review_notes"])
        assert res["stats"]["week_start_mismatch"] == 1

    @pytest.mark.parametrize("formula, kw", [
        ("DATETRUNC('week', [d])", {}),                       # unknown start: advisory
        ("DATETRUNC('week', [d])", {"week_start": "monday"}),
        ("DATETRUNC('week', [d], 'monday')", {"week_start": "sunday"}),  # literal wins
    ])
    def test_unknown_or_monday_start_is_advisory_only(self, formula, kw):
        rec = self._one(formula, **kw)["translated"][0]
        assert "review_required" not in rec
        assert any(n.startswith(WEEK_START_NOTE_PREFIX) for n in rec["review_notes"])

    @pytest.mark.parametrize("fn", ["ISOWEEK", "ISOYEAR", "ISOQUARTER", "WEEK"])
    def test_iso_and_week_functions_are_skipped_not_passed_through(self, fn):
        res = self._one(f"{fn}([Order Date])")
        assert res["translated"] == []
        assert fn in res["skipped"][0]["reason"]

    def test_isoweekday_still_translates(self):
        res = self._one("ISOWEEKDAY([Order Date])")
        assert res["translated"][0]["expr"] == "day_number_of_week ( [Order Date] )"


class TestQlikWeekStart:
    @pytest.mark.parametrize("expr, fwd", [
        ("WeekStart(D)", None), ("WeekStart(D)", 0), ("WeekStart(D, 0)", None),
        ("WeekStart(D, 0, 0)", 6),  # a literal Monday argument beats the app setting
    ])
    def test_monday_or_unknown_start_translates(self, expr, fwd):
        from ts_cli.qlik.functions import translate
        out, review, _ = translate(expr, first_week_day=fwd)
        assert out == "start_of_week(D)" and not review

    @pytest.mark.parametrize("expr, fwd", [
        ("WeekStart(D, 0, 6)", None), ("WeekStart(D)", 6), ("Max(WeekStart(D))", 6),
    ])
    def test_known_non_monday_start_needs_review(self, expr, fwd):
        from ts_cli.qlik.functions import translate
        out, review, reason = translate(expr, first_week_day=fwd)
        assert review and WEEK_START_MISMATCH_PREFIX in reason and "Sunday" in reason
        assert "start_of_week" not in out  # never the invalid start_of_week(D,0,6)

    @pytest.mark.parametrize("expr", ["WeekStart(D, -1)", "WeekStart(D, n)",
                                      "WeekStart(D, 0, x)"])
    def test_offset_or_non_literal_needs_review(self, expr):
        from ts_cli.qlik.functions import translate
        out, review, reason = translate(expr)
        assert review and "start_of_week" not in out

    def test_build_model_status_is_needs_review(self):
        from ts_cli.qlik.build_model import _translate_measures
        m = type("M", (), {"label": "W", "id": "m1",
                           "expression": "Max(WeekStart(OrderDate, 0, 6))"})()
        _, mapping = _translate_measures([m])
        assert mapping[0]["status"] == "NEEDS REVIEW"


class TestDatabricksInliningAndFilter:
    def _parsed(self, measures, filter_sql=None):
        return {"version": "1.1", "comment": None,
                "source": {"kind": "table_fqn", "raw": "c.s.t", "parts": ["c", "s", "t"],
                           "needs_live_check": True},
                "joins": [], "dimensions": [], "measures": measures, "filter": filter_sql,
                "materialization": None, "warnings": [], "unsupported": []}

    def _measure(self, name, expr, kind, **kw):
        base = {"name": name, "expr": expr, "kind": kind, "expr_kind": kind,
                "agg_function": None, "physical_ref": None, "distinct": False,
                "cross_refs": [], "lod_refs": [], "display_name": None,
                "comment": None, "synonyms": [], "format": None, "window": None}
        base.update(kw)
        return base

    def test_cross_measure_flagged_after_inlining(self):
        from ts_cli.databricks.mv_translate import WEEK_START_KIND, translate_metric_view
        measures = [
            self._measure("mon_rev", "MAX(DATE_TRUNC('WEEK', dt))", "complex"),
            self._measure("half", "MEASURE(mon_rev) / 2", "complex_cross_measure",
                          cross_refs=["mon_rev"]),
        ]
        out = translate_metric_view(self._parsed(measures), {"source": "T"})
        half = next(e for e in out["translated"] if e["name"] == "half")
        assert "start_of_week" in half["ts_expr"]
        assert [a["kind"] for a in half["annotations"]].count(WEEK_START_KIND) == 1

    def test_filter_carries_annotations(self):
        from ts_cli.databricks.mv_translate import WEEK_START_KIND, translate_filter
        f = translate_filter("DATE_TRUNC('WEEK', dt) = DATE '2026-01-05'", {"source": "T"})
        assert [a["kind"] for a in f["annotations"]] == [WEEK_START_KIND]
        assert translate_filter("status = 'x'", {"source": "T"})["annotations"] == []


# ================================================== re-review fixes (PR #582)

class TestReReview:
    def _one(self, formula, **kw):
        from ts_cli.tableau_translate import translate_formulas
        calcs = [{"caption": "F", "name": "[Calculation_1]", "role": "measure",
                  "datatype": "real", "formula": formula}]
        return translate_formulas(calcs, **kw)

    @pytest.mark.parametrize("formula", [
        "DATEDIFF('day', [a], [b]) / 7",
        "DATEDIFF('day', [a], [b]) / 7.0",
        "FLOOR(DATEDIFF('day', [a], [b]) / 7)",
    ])
    def test_exact_day_division_is_not_review_required(self, formula):
        res = self._one(formula)
        rec = res["translated"][0]
        assert "review_required" not in rec
        assert not any(n.startswith(WEEK_DIFF_DAYS_PREFIX) for n in rec.get("review_notes", []))
        assert res["stats"]["review_required"] == 0

    def test_exact_day_division_is_not_downgraded_in_formula_translate(self):
        from ts_cli.formula_translate.engine import translate
        from ts_cli.formula_translate.adapters import TRANSLATED
        r = translate("DATEDIFF('day', [a], [b]) / 7", "tableau")
        assert r["status"] == TRANSLATED
        assert not any(t.startswith(WEEK_DIFF_DAYS_PREFIX) for t in r["traps"])

    def test_review_required_reaches_validation_warnings(self):
        from ts_cli.tableau.validate import validate_pre_import
        res = self._one("DATEDIFF('week', [a], [b])")
        issues = validate_pre_import(res["translated"])
        assert issues and issues[0]["review_required"] is True
        res = self._one("DATETRUNC('week', [d])")  # advisory only
        assert all("review_required" not in i for i in validate_pre_import(res["translated"]))

    @pytest.mark.parametrize("expr", ["WeekStart(D, -1)", "WeekStart(D, 0, vFWD)"])
    def test_qlik_offset_reason_wins_over_mismatch(self, expr):
        from ts_cli.qlik.functions import translate
        out, review, reason = translate(expr, first_week_day=6)
        assert review and WEEK_START_MISMATCH_PREFIX not in reason
        assert "period offset" in reason

    def test_databricks_start_of_week_clause_is_dialect_aware(self):
        dbx = week_start_note("start_of_week ( [d] )", "databricks")
        assert "WEEK_START" not in dbx and "Snowflake" not in dbx
        assert "fixes to Monday" in dbx and "Model calendar" in dbx
        assert "WEEK_START" in week_start_note("start_of_week ( [d] )")

    def test_databricks_paths_use_the_databricks_clause(self):
        from ts_cli.databricks.mv_translate import translate_filter
        f = translate_filter("DATE_TRUNC('WEEK', dt) = DATE '2026-01-05'", {"source": "T"})
        assert "WEEK_START" not in f["annotations"][0]["detail"]
        from ts_cli.formula_translate.engine import translate
        r = translate("DATE_TRUNC('WEEK', order_date)", "databricks")
        week = [t for t in r["traps"] if t.startswith(WEEK_START_NOTE_PREFIX)]
        assert week and "fixes to Monday" in week[0]
