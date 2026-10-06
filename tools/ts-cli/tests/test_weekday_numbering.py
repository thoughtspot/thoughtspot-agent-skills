"""BL-334 item 1 — weekday NUMBER translations must not rename to day_number_of_week.

ThoughtSpot `day_number_of_week ( d )` is fixed 1 = Monday ... 7 = Sunday: it
compiled to `(MOD((DATEDIFF(day, DATE '1970-01-01', d) + 3), 7) + 1)` on
se-thoughtspot (live probe, 2026-10-06). Every source below numbers its weekdays
from a different first day and/or base, so each translator must shift through
`formula_common.ts_weekday_number`.

Each test asserts the emitted formula string AND evaluates it with a small Python
model of ThoughtSpot `day_number_of_week` / `mod` over all seven days of the week
of 2026-10-04 (Sunday) ... 2026-10-10 (Saturday), comparing with the source's
DOCUMENTED numbering, written out literally per day rather than derived — so a
wrong offset cannot cancel out against a wrong expectation.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

import pytest

from ts_cli.formula_common import ts_weekday_number
from ts_cli.sv_sql import translate_sql_expr as sf_translate
from ts_cli.databricks.mv_sql import translate_sql_expr as dbx_translate
from ts_cli.tableau.functions import map_date_functions
from ts_cli.qlik.functions import parse_first_week_day, translate as qlik_translate

WEEK = [date(2026, 10, 4) + timedelta(days=i) for i in range(7)]  # Sun .. Sat
DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def _ts_day_number_of_week(d: date) -> int:
    """Model of ThoughtSpot day_number_of_week — its compiled SQL, verbatim."""
    days = (d - date(1970, 1, 1)).days
    return ((days + 3) % 7) + 1


def test_model_matches_the_live_probe_points():
    # se-thoughtspot 2026-10-06: Sun 10-04 = 7, Mon 10-05 = 1, Sat 10-10 = 6,
    # Wed 2020-01-01 = 3.
    assert _ts_day_number_of_week(date(2026, 10, 4)) == 7
    assert _ts_day_number_of_week(date(2026, 10, 5)) == 1
    assert _ts_day_number_of_week(date(2026, 10, 10)) == 6
    assert _ts_day_number_of_week(date(2020, 1, 1)) == 3


_DNW_RE = re.compile(r"day_number_of_week\s*\(\s*[^()]*?\s*\)")


def _evaluate(formula: str, d: date) -> int:
    """Evaluate a ThoughtSpot weekday formula for date ``d``.

    Substitutes the modelled day_number_of_week value, then evaluates the
    remaining integer arithmetic with ThoughtSpot `mod` (non-negative operands
    here, so Python `%` agrees)."""
    body = _DNW_RE.sub(str(_ts_day_number_of_week(d)), formula)
    assert "day_number_of_week" not in body, formula
    assert re.fullmatch(r"[\d\s()+\-,mod]*", body), f"unexpected tokens: {body!r}"
    return eval(body, {"__builtins__": {}}, {"mod": lambda a, b: a % b})


def _numbering(formula: str) -> list[int]:
    return [_evaluate(formula, d) for d in WEEK]


# Documented source numberings, Sun .. Sat, written out literally.
SUN0 = [0, 1, 2, 3, 4, 5, 6]   # Snowflake DAYOFWEEK (WEEK_START = 0 default)
SUN1 = [1, 2, 3, 4, 5, 6, 7]   # Databricks DAYOFWEEK / DOW, Tableau default
ISO = [7, 1, 2, 3, 4, 5, 6]    # Mon = 1 .. Sun = 7 (DAYOFWEEKISO, DAYOFWEEK_ISO)
MON0 = [6, 0, 1, 2, 3, 4, 5]   # Databricks WEEKDAY, Qlik Weekday default

_R = lambda c: f"[{c}]"  # noqa: E731 — trivial column resolver


def _assert_not_bare_rename(formula: str, col: str) -> None:
    """Regression guard: a non-ISO source is never a plain day_number_of_week."""
    assert formula.replace(" ", "") != f"day_number_of_week({col})".replace(" ", "")


# ---------------------------------------------------------------- the helper

@pytest.mark.parametrize("first_day,base,expected", [
    ("sunday", 0, SUN0), ("sunday", 1, SUN1),
    ("monday", 1, ISO), ("monday", 0, MON0),
])
def test_helper_numbering(first_day, base, expected):
    assert _numbering(ts_weekday_number("[d]", first_day=first_day, base=base)) \
        == expected


@pytest.mark.parametrize("first_idx", range(7))
@pytest.mark.parametrize("base", [0, 1])
def test_helper_every_first_day(first_idx, base):
    """Any first day: the first day numbers `base`, then +1 per day."""
    formula = ts_weekday_number("[d]", first_day=first_idx, base=base)
    for d in WEEK:
        offset = (d.isoweekday() - 1 - first_idx) % 7  # Monday-based
        assert _evaluate(formula, d) == offset + base, (formula, d)


def test_helper_compact_style_is_the_same_value():
    for first in range(7):
        for base in (0, 1):
            spaced = ts_weekday_number("[d]", first_day=first, base=base)
            compact = ts_weekday_number("[d]", first_day=first, base=base,
                                        compact=True)
            assert " ( " not in compact
            assert _numbering(spaced) == _numbering(compact)


def test_helper_rejects_bad_input():
    with pytest.raises(ValueError):
        ts_weekday_number("[d]", first_day="funday", base=1)
    with pytest.raises(ValueError):
        ts_weekday_number("[d]", first_day=7, base=1)
    with pytest.raises(ValueError):
        ts_weekday_number("[d]", first_day=0, base=2)


# ---------------------------------------------------------------- Snowflake

class TestSnowflake:
    @pytest.mark.parametrize("sql", ["DAYOFWEEK(o.d)", "EXTRACT(DOW FROM o.d)",
                                     "EXTRACT(dayofweek FROM o.d)",
                                     "EXTRACT(weekday FROM o.d)",
                                     "EXTRACT(dw FROM o.d)"])
    def test_dayofweek_is_sunday_zero(self, sql):
        out = sf_translate(sql, _R)
        assert out == "mod ( day_number_of_week ( [o.d] ) , 7 )"
        assert _numbering(out) == SUN0
        _assert_not_bare_rename(out, "[o.d]")

    @pytest.mark.parametrize("sql", ["DAYOFWEEKISO(o.d)",
                                     "EXTRACT(dayofweekiso FROM o.d)",
                                     "EXTRACT(dow_iso FROM o.d)"])
    def test_dayofweekiso_is_a_rename(self, sql):
        out = sf_translate(sql, _R)
        assert out == "day_number_of_week ( [o.d] )"
        assert _numbering(out) == ISO

    def test_dayofweek_in_a_comparison(self):
        # Snowflake DAYOFWEEK(d) = 0 is Sunday; must stay Sunday.
        out = sf_translate("DAYOFWEEK(o.d) = 0", _R)
        assert out == "mod ( day_number_of_week ( [o.d] ) , 7 ) = 0"


# ---------------------------------------------------------------- Databricks

class TestDatabricks:
    @pytest.mark.parametrize("sql", ["DAYOFWEEK(o.d)", "EXTRACT(DOW FROM o.d)",
                                     "EXTRACT(DAYOFWEEK FROM o.d)"])
    def test_dayofweek_is_sunday_one(self, sql):
        out = dbx_translate(sql, _R)
        assert out == "( mod ( day_number_of_week ( [o.d] ) , 7 ) + 1 )"
        assert _numbering(out) == SUN1
        _assert_not_bare_rename(out, "[o.d]")

    @pytest.mark.parametrize("sql", ["EXTRACT(DAYOFWEEK_ISO FROM o.d)",
                                     "EXTRACT(DOW_ISO FROM o.d)"])
    def test_dayofweek_iso_is_a_rename(self, sql):
        out = dbx_translate(sql, _R)
        assert out == "day_number_of_week ( [o.d] )"
        assert _numbering(out) == ISO

    def test_weekday_is_monday_zero(self):
        out = dbx_translate("WEEKDAY(o.d)", _R)
        assert out == "( day_number_of_week ( [o.d] ) - 1 )"
        assert _numbering(out) == MON0

    def test_composes_inside_arithmetic(self):
        out = dbx_translate("DAYOFWEEK(o.d) * 2", _R)
        assert out == "( mod ( day_number_of_week ( [o.d] ) , 7 ) + 1 ) * 2"


# ---------------------------------------------------------------- Tableau

class TestTableau:
    def test_weekday_default_is_sunday_one(self):
        out = map_date_functions("DATEPART('weekday', [Date])")
        assert out == "( mod ( day_number_of_week ( [Date] ) , 7 ) + 1 )"
        assert _numbering(out) == SUN1
        assert "day_of_week" not in out  # the old mapping returned the NAME

    def test_weekday_explicit_monday(self):
        out = map_date_functions("DATEPART('weekday', [Date], 'monday')")
        assert out == "day_number_of_week ( [Date] )"
        assert _numbering(out) == ISO

    def test_weekday_explicit_sunday(self):
        out = map_date_functions("DATEPART('weekday', [Date], 'sunday')")
        assert _numbering(out) == SUN1

    def test_weekday_non_literal_start_left_for_review(self):
        expr = "DATEPART('weekday', [Date], [Week Start])"
        assert map_date_functions(expr) == expr

    def test_datasource_week_start_is_used_and_not_flagged(self):
        notes: dict = {}
        out = map_date_functions("DATEPART('weekday', [Date])", None,
                                 week_start="monday", notes=notes)
        assert _numbering(out) == ISO
        assert notes == {}

    def test_sunday_assumption_is_counted(self):
        notes: dict = {}
        map_date_functions("DATEPART('weekday', [Date])", None, notes=notes)
        assert notes == {"weekday_week_start_assumed": 1}

    def test_explicit_start_beats_datasource_and_is_not_flagged(self):
        notes: dict = {}
        out = map_date_functions("DATEPART('weekday', [Date], 'sunday')", None,
                                 week_start="monday", notes=notes)
        assert _numbering(out) == SUN1 and notes == {}

    @pytest.mark.parametrize("expr", ["ISOWEEKDAY([Date])",
                                      "DATEPART('iso-weekday', [Date])"])
    def test_iso_weekday_is_a_rename(self, expr):
        from ts_cli.tableau_translate import translate_single
        out, errors, notes = translate_single(expr, role="attribute")
        assert out == "day_number_of_week ( [Date] )" and not errors
        assert _numbering(out) == ISO and notes == {}

    def test_assumption_reaches_the_translated_record(self):
        from ts_cli.tableau_translate import translate_formulas
        calcs = [{"caption": "Wd", "name": "[Calculation_1]", "role": "dimension",
                  "datatype": "integer",
                  "formula": "DATEPART('weekday', [Order Date])"}]
        res = translate_formulas(calcs)
        rec = res["translated"][0]
        assert "Sunday" in rec["review_notes"][0]
        assert res["stats"]["weekday_week_start_assumed"] == 1
        from ts_cli.tableau.validate import validate_pre_import
        issues = validate_pre_import(res["translated"])
        assert any("Sunday" in w for i in issues for w in i["warnings"])
        res = translate_formulas(calcs, week_start="monday")
        assert validate_pre_import(res["translated"]) == []
        assert "review_notes" not in res["translated"][0]
        assert _numbering(res["translated"][0]["expr"]) == ISO


class TestTableauWeekStartParse:
    def _ds(self, inner: str):
        import xml.etree.ElementTree as ET
        return ET.fromstring(f"<datasource name='ds'>{inner}</datasource>")

    def test_reads_date_options_start_of_week(self):
        from ts_cli.tableau.twb import _datasource_week_start
        ds = self._ds("<date-options fiscal-year-start='april' start-of-week='monday' />")
        assert _datasource_week_start(ds) == "monday"

    @pytest.mark.parametrize("inner", ["", "<date-options fiscal-year-start='april' />",
                                       "<date-options start-of-week='lundi' />"])
    def test_absent_or_unrecognised_is_none(self, inner):
        from ts_cli.tableau.twb import _datasource_week_start
        assert _datasource_week_start(self._ds(inner)) is None


# ---------------------------------------------------------------- Qlik

class TestQlik:
    """Qlik Weekday() numbers 0-6 from the app's FirstWeekDay (0 = Mon ...
    6 = Sun), set by `SET FirstWeekDay=n;` in the load script — US apps
    typically 6, so there is no safe default (BL-334 review)."""

    def test_first_week_day_0_is_monday_zero(self):
        out, review, _ = qlik_translate("Weekday(OrderDate)", first_week_day=0)
        assert out == "(day_number_of_week(OrderDate) - 1)"
        assert not review
        assert _numbering(out) == MON0

    def test_first_week_day_6_is_sunday_zero(self):
        out, review, _ = qlik_translate("Weekday(OrderDate)", first_week_day=6)
        assert out == "mod(day_number_of_week(OrderDate), 7)"
        assert not review
        assert _numbering(out) == SUN0
        # help.qlik.com: with SET FirstWeekDay=6, weekday('10/12/1971') = 2 (Tue).
        assert _evaluate(out, date(1971, 10, 12)) == 2

    def test_first_week_day_absent_is_flagged_not_assumed(self):
        out, review, reason = qlik_translate("Weekday(OrderDate)")
        assert review
        assert "FirstWeekDay" in reason
        assert "day_number_of_week" not in out  # never a guessed origin

    def test_absent_first_week_day_flagged_inside_if(self):
        _, review, reason = qlik_translate(
            "If(Weekday(OrderDate) = 5, Sum(Sales), 0)")
        assert review and "FirstWeekDay" in reason

    def test_explicit_second_argument_wins(self):
        # weekday('10/12/1971', 6) returns 2 for a Tuesday, whatever the app says.
        out, review, _ = qlik_translate("Weekday(OrderDate, 6)", first_week_day=0)
        assert not review
        assert _numbering(out) == SUN0
        assert _evaluate(out, date(1971, 10, 12)) == 2

    def test_weekday_non_literal_first_day_flagged(self):
        _, review, _ = qlik_translate("Weekday(OrderDate, x)", first_week_day=0)
        assert review


class TestQlikFirstWeekDayParse:
    @pytest.mark.parametrize("script,expected", [
        ("SET ThousandSep=',';\nSET FirstWeekDay=6;\nSET BrokenWeeks=1;", 6),
        ("SET FirstWeekDay=0;", 0),
        ("  set firstweekday = 6 ;", 6),
        ("SET FirstWeekDay=6;\nLOAD * INLINE [a];\nSET FirstWeekDay=0;", 0),
        ("SET DateFormat='M/D/YYYY';", None),
        ("", None),
        (None, None),
    ])
    def test_parse(self, script, expected):
        assert parse_first_week_day(script) == expected

    def test_build_model_threads_the_script_setting(self):
        from ts_cli.qlik.build_model import _translate_measures
        from ts_cli.qlik.ir import QlikApp
        app = QlikApp(app_name="t", source_file="t")
        assert hasattr(app, "load_script")
        m = type("M", (), {"label": "Wd", "id": "m1",
                           "expression": "Weekday(OrderDate)"})()
        formulas, mapping = _translate_measures(
            [m], parse_first_week_day("SET FirstWeekDay=6;"))
        assert _numbering(formulas[0]["expr"]) == SUN0
        _, mapping = _translate_measures([m], None)
        assert mapping[0]["status"] != "OK" and "FirstWeekDay" in mapping[0]["reason"]
