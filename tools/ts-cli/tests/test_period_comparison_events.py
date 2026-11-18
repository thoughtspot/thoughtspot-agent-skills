# tools/ts-cli/tests/test_period_comparison_events.py
from datetime import date

import pytest

from ts_cli.period_comparison.events import BUILTIN_EVENTS, anchor_date, easter_sunday


@pytest.mark.parametrize("year,expected", [(2020, date(2020, 11, 27)), (2024, date(2024, 11, 29)),
    (2028, date(2028, 11, 24)), (2029, date(2029, 11, 23)), (2030, date(2030, 11, 29))])
def test_black_friday(year, expected):
    assert anchor_date("black-friday", year) == expected


def test_cyber_monday():
    assert anchor_date("cyber-monday", 2025) == date(2025, 12, 1)


def test_christmas_and_boxing_day():
    assert anchor_date("christmas", 2025) == date(2025, 12, 25)
    assert anchor_date("boxing-day", 2025) == date(2025, 12, 26)


@pytest.mark.parametrize("year,expected", [(2019, date(2019, 4, 21)), (2024, date(2024, 3, 31)),
    (2025, date(2025, 4, 20)), (2038, date(2038, 4, 25)),
    # 1981 and 2049 take the m=1 correction branch; 2285 is the earliest date Easter can fall on.
    (1981, date(1981, 4, 19)), (2049, date(2049, 4, 18)), (2285, date(2285, 3, 22))])
def test_easter(year, expected):
    assert easter_sunday(year) == expected


def test_easter_anchor_matches_easter_sunday():
    assert anchor_date("easter", 2025) == easter_sunday(2025)


def test_unknown_event():
    with pytest.raises(KeyError):
        anchor_date("diwali", 2025)


def test_builtin_events_display_names():
    assert BUILTIN_EVENTS == {
        "black-friday": "Black Friday",
        "cyber-monday": "Cyber Monday",
        "christmas": "Christmas",
        "boxing-day": "Boxing Day",
        "easter": "Easter",
    }


def test_every_builtin_event_resolves():
    for key in BUILTIN_EVENTS:
        assert isinstance(anchor_date(key, 2025), date)
