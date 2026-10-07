"""#589 re-review follow-ups: the exact-start week note and the Qlik source scan.

1. The mixed (Monday + exact) note adds the "day_number_of_week is exact" clause only
   when the output actually calls day_number_of_week.
2. ``qlik.weeks`` finds Weekday() / WeekStart() calls outside string literals and
   field names, so a name or string that looks like a call is no exact start.
3. The Qlik reason reads "an unsupported literal …" / "a non-literal …".
"""
from __future__ import annotations

import pytest

from ts_cli.formula_week import (
    WEEK_START_EXACT_PREFIX,
    WEEK_START_NOTE_PREFIX,
    week_start_note,
)
from ts_cli.qlik.weeks import _week_calls, known_week_starts


class TestMixedNote:
    def test_no_exact_clause_without_day_number_of_week(self):
        note = week_start_note("start_of_week(D)", exact_starts=[6])
        assert note.startswith(WEEK_START_NOTE_PREFIX)
        assert "day_number_of_week" not in note and "exact for a" not in note

    def test_exact_clause_when_day_number_of_week_is_called(self):
        note = week_start_note("start_of_week(D) - mod(day_number_of_week(D), 7)",
                               exact_starts=[6])
        assert note.startswith(WEEK_START_NOTE_PREFIX)
        assert "day_number_of_week is exact for a Sunday week start" in note

    def test_exact_only(self):
        assert week_start_note("mod(day_number_of_week(D), 7)",
                               exact_starts=[6]).startswith(WEEK_START_EXACT_PREFIX)


class TestQlikScanIgnoresOpaqueText:
    @pytest.mark.parametrize("expr", [
        "If([Weekday(x)]>1, WeekStart([d],0,0))",
        "WeekStart([d],0,0) & 'weekday(z)'",
        "WeekStart([d],0,0) & \"Weekday(q)\"",
        "[WeekStart(a, 0, 6)] + WeekStart([d],0,0)",
    ])
    def test_no_false_exact_start(self, expr):
        # The only real call is a Monday WeekStart → start_of_week: no exact start,
        # even with FirstWeekDay = 6 (Sunday).
        assert known_week_starts(expr, 6) == []

    def test_real_calls_still_found_and_args_keep_their_text(self):
        calls = list(_week_calls("WeekStart([Order, Date], 0, 6) + Weekday('a,b')"))
        assert calls == [("weekstart", ["[Order, Date]", " 0", " 6"]),
                         ("weekday", ["'a,b'"])]
        assert known_week_starts("If([x]>1, WeekStart([d], 0, 6))", None) == [6]

    def test_end_to_end_note_is_not_exact(self):
        from ts_cli.formula_translate.engine import translate
        r = translate("If([Weekday(x)]>1, WeekStart([d],0,0))", "qlik", first_week_day=6)
        assert not any(t.startswith(WEEK_START_EXACT_PREFIX) for t in r["traps"])


@pytest.mark.parametrize("expr, says", [
    ("WeekStart(D, 1.5)", "with an unsupported literal period offset '1.5'"),
    ("WeekStart(D, 0, 7)", "with an unsupported literal first week day '7'"),
    ("WeekStart(D, vN)", "with a non-literal period offset 'vN'"),
    ("WeekStart(D, [n])", "with a non-literal period offset '[n]'"),
])
def test_reason_grammar(expr, says):
    from ts_cli.qlik.functions import translate
    _, review, reason = translate(expr, first_week_day=6)
    assert review and says in reason
    assert "a unsupported" not in reason
