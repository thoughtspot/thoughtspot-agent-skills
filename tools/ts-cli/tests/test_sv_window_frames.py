"""Window frames in the Snowflake Semantic View translator: moving offsets (the N in
`N PRECEDING` was dropped), the default frame of an ORDER BY (a running total, not a
grand total), and a fixed PARTITION BY (BL-242: dropped, turning YTD into lifetime)."""
from __future__ import annotations

import pytest

from ts_cli.formula_common import UntranslatableError
from ts_cli.sv_window import _parse_window_spec, _translate_window


def _tw(spec: str, agg: str = "sum ( [T::x] )") -> str:
    return _translate_window(agg, _parse_window_spec(spec), lambda c: f"[T::{c}]")


@pytest.mark.parametrize("spec,ts", [
    ("ORDER BY d ROWS BETWEEN 2 PRECEDING AND CURRENT ROW", "moving_sum ( [T::x] , 2 , 0 , [T::d] )"),
    ("ORDER BY d ROWS BETWEEN 6 PRECEDING AND CURRENT ROW", "moving_sum ( [T::x] , 6 , 0 , [T::d] )"),
    ("ORDER BY d ROWS 3 PRECEDING", "moving_sum ( [T::x] , 3 , 0 , [T::d] )"),
    ("ORDER BY d ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING", "moving_sum ( [T::x] , 1 , 1 , [T::d] )"),
    ("ORDER BY d ROWS BETWEEN CURRENT ROW AND 2 FOLLOWING", "moving_sum ( [T::x] , 0 , 2 , [T::d] )"),
    ("ORDER BY d ROWS BETWEEN 1 PRECEDING AND 1 PRECEDING", "moving_sum ( [T::x] , 1 , -1 , [T::d] )"),
])
def test_moving_offsets_follow_the_frame(spec, ts):
    assert _tw(spec) == ts


@pytest.mark.parametrize("spec", [
    "ORDER BY d",                                                    # SQL default frame
    "ORDER BY d ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW",
    "ORDER BY d RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW",
    "PARTITION BY EXCLUDING d ORDER BY d ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW",
])
def test_running_total(spec):
    assert _tw(spec) == "cumulative_sum ( [T::x] , [T::d] )"


@pytest.mark.parametrize("spec,why", [
    ("PARTITION BY y ORDER BY d ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW", "PARTITION BY"),
    ("PARTITION BY y ORDER BY d ROWS BETWEEN 2 PRECEDING AND CURRENT ROW", "PARTITION BY"),
    ("ORDER BY d DESC ROWS BETWEEN 2 PRECEDING AND CURRENT ROW", "DESC"),
    ("ORDER BY d, e ROWS BETWEEN 2 PRECEDING AND CURRENT ROW", "several columns"),
    ("ORDER BY d RANGE BETWEEN INTERVAL 7 DAYS PRECEDING AND CURRENT ROW", "RANGE"),
    ("ORDER BY d ROWS BETWEEN 2 PRECEDING AND UNBOUNDED FOLLOWING", "UNBOUNDED FOLLOWING"),
])
def test_unmappable_windows_are_refused(spec, why):
    with pytest.raises(UntranslatableError, match=why):
        _tw(spec)


def test_unordered_partition_is_still_a_group_function():
    assert _tw("PARTITION BY r") == "group_sum ( [T::x] , [T::r] )"
