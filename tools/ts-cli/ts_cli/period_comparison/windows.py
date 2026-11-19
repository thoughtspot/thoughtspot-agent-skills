"""Event and comparison windows, and the per-year plan built from them.

Pure date arithmetic apart from ``load_custom_windows``, which reads one file. The
plan says, for each year, which days are the event and which are its comparison
windows; later modules turn it into ThoughtSpot TML.

``build_plan`` applies these rules. Rules 4 and 6 run first, for every year it
reads: each given window (the event window, and custom comparison ranges) is
checked against rule 4 before rule 6 judges whether the year is finished, so a
date typed into the wrong year is an error, never an unfinished year dropped.
Rules 2, 3, 5 and rule 4 for prior-weeks windows then run on the kept years.

1. Event window = anchor + offset .. anchor + offset + length - 1 (a custom start
   date the same way; a custom range as given).
2. Prior-weeks comparison window k = the event window shifted back k x step days,
   k = 1..N, where step = 7 x ceil(length / 7).
3. A clash is a prior-weeks comparison window holding a built-in event's anchor
   day in the same year, outside the event window (the analysed event's own
   anchor included). ``on_clash`` decides: None reports it, "skip"
   replaces the window with the next earlier non-clashing step, "keep" uses it.
4. Every window must sit inside the event's calendar year.
5. In custom comparison mode, no two windows (event included) may overlap.
6. A year whose latest window has not ended before ``today`` is dropped. As every
   window sits in its own year, a dropped year is always later than every kept
   year, so the kept years of a consecutive request stay consecutive.
   ``today`` is the first day the data does not cover: the run date, or the day
   after ``--data-through``. A year missing from a custom file is an error,
   except the current year under ``last=N`` while its event window is unknown or
   has not ended: its dates may not be known yet, so it is dropped.

``PlanError`` messages reach end users, so they name the year and the dates.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Literal, Optional, Union

import yaml

from .events import BUILTIN_EVENTS, anchor_date

# How far back ``last=N`` looks for finished years before giving up.
_MAX_LOOKBACK_YEARS = 50


class PlanError(ValueError):
    """The requested plan cannot be built. The message is shown to the user."""


class _MissingYearError(PlanError):
    """A custom file has no entry for a year the plan needs."""


@dataclass(frozen=True)
class Window:
    """An inclusive run of days, ``start`` through ``end``."""
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise PlanError(
                f"The window {self.start.isoformat()} to {self.end.isoformat()} "
                "ends before it starts."
            )

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def overlaps(self, other: "Window") -> bool:
        return self.start <= other.end and other.start <= self.end

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end

    def shifted(self, days: int) -> "Window":
        delta = timedelta(days=days)
        return Window(self.start + delta, self.end + delta)

    def __str__(self) -> str:
        return f"{self.start.isoformat()} to {self.end.isoformat()}"


@dataclass(frozen=True)
class Clash:
    """A comparison ``window`` in ``year`` that holds ``event``'s anchor day."""
    year: int
    window: Window
    event: str


@dataclass(frozen=True)
class YearPlan:
    year: int
    event: Window
    comparisons: tuple[Window, ...]
    # (clashing window, replacement) pairs; empty unless on_clash="skip".
    substitutions: tuple[tuple[Window, Window], ...]


CustomEventDates = dict[int, Union[date, list[Window]]]


@dataclass(frozen=True)
class PlanSpec:
    event: str
    offset: int = 0
    length: int = 4
    years: tuple[int, ...] = ()
    last: Optional[int] = None
    comparison: Literal["prior-weeks", "custom"] = "prior-weeks"
    prior_weeks: int = 6
    custom_event: Optional[CustomEventDates] = None
    custom_comparison: Optional[dict[int, list[Window]]] = None
    on_clash: Optional[Literal["skip", "keep"]] = None


@dataclass(frozen=True)
class PlanResult:
    years: tuple[YearPlan, ...]
    step: int
    dropped_years: tuple[int, ...]
    clashes: tuple[Clash, ...]
    needs_clash_decision: bool


def comparison_step(length: int) -> int:
    """Days between successive comparison windows: whole weeks, never < ``length``."""
    if length < 1:
        raise PlanError(f"The event length must be at least 1 day, not {length}.")
    return 7 * -(-length // 7)


# --- spec checks ------------------------------------------------------------

def _check_spec(spec: PlanSpec) -> None:
    _check_choices(spec)
    _check_inputs(spec)


def _check_choices(spec: PlanSpec) -> None:
    """The event, the window shape and the named options."""
    if spec.event != "custom" and spec.event not in BUILTIN_EVENTS:
        known = ", ".join([*BUILTIN_EVENTS, "custom"])
        raise PlanError(f"Unknown event '{spec.event}'. Expected one of: {known}.")
    if spec.length < 1:
        raise PlanError(f"The event length must be at least 1 day, not {spec.length}.")
    if spec.comparison not in ("prior-weeks", "custom"):
        raise PlanError(
            f"Unknown comparison '{spec.comparison}'. Expected prior-weeks or custom."
        )
    if spec.comparison == "prior-weeks" and spec.prior_weeks < 1:
        raise PlanError(
            f"The number of prior weeks must be at least 1, not {spec.prior_weeks}."
        )
    if spec.on_clash not in (None, "skip", "keep"):
        raise PlanError(f"Unknown clash choice '{spec.on_clash}'. Expected skip or keep.")


def _check_inputs(spec: PlanSpec) -> None:
    """The custom dates each mode needs, and exactly one way of choosing years."""
    if spec.event == "custom" and not spec.custom_event:
        raise PlanError("A custom event needs its dates for each year.")
    if spec.comparison == "custom" and not spec.custom_comparison:
        raise PlanError("Custom comparison needs the comparison ranges for each year.")
    if spec.years and spec.last is not None:
        raise PlanError("Give either a list of years or a number of recent years, not both.")
    if not spec.years and spec.last is None:
        raise PlanError("Give either a list of years or a number of recent years.")
    if spec.last is not None and spec.last < 1:
        raise PlanError(f"The number of recent years must be at least 1, not {spec.last}.")


# --- rule 1: event windows --------------------------------------------------

def _expand(start: date, spec: PlanSpec) -> Window:
    first = start + timedelta(days=spec.offset)
    return Window(first, first + timedelta(days=spec.length - 1))


def _event_window(spec: PlanSpec, year: int) -> Window:
    if spec.event != "custom":
        return _expand(anchor_date(spec.event, year), spec)
    given = (spec.custom_event or {}).get(year)
    if given is None:
        raise _MissingYearError(f"The custom event has no dates for {year}.")
    if isinstance(given, date):
        return _expand(given, spec)
    if len(given) != 1:
        raise PlanError(
            f"The custom event for {year} has {len(given)} ranges; give exactly one."
        )
    return given[0]


def _custom_comparisons(spec: PlanSpec, year: int) -> tuple[Window, ...]:
    given = (spec.custom_comparison or {}).get(year)
    if not given:
        raise _MissingYearError(f"The custom comparison has no ranges for {year}.")
    if isinstance(given, date):
        raise PlanError(
            f"The custom comparison for {year} is a single date ({given.isoformat()}); "
            "give [start, end] ranges."
        )
    return tuple(given)


# --- rule 6: which years ----------------------------------------------------

def _is_unfinished(spec: PlanSpec, year: int, event: Window, today: date) -> bool:
    """True when the latest window in ``year`` ends on or after ``today``.

    Prior-weeks windows all precede the event, so the event's end is the latest.
    A custom comparison may sit after the event, so its ranges count too. They
    are read for every year, finished or not, so a missing year always surfaces,
    and checked against rule 4 first: a range typed into a later year would
    otherwise make its year look unfinished, and the year would be dropped.
    """
    latest = event.end
    if spec.comparison == "custom":
        comparisons = _custom_comparisons(spec, year)
        for window in comparisons:
            _check_in_year(year, window, "comparison window")
        latest = max([latest, *(w.end for w in comparisons)])
    return latest >= today


YearsChosen = tuple[list[tuple[int, Window]], list[int]]


def _sort_years(
    spec: PlanSpec, years: list[int], today: date, wanted: int, *, walking_back: bool
) -> YearsChosen:
    """Split ``years`` (in the order given) into finished and unfinished.

    Stops once ``wanted`` finished years are found. Returns (kept (year, event
    window) pairs, dropped years), both ascending. A year missing from a custom
    file raises, except the current year when ``walking_back`` (``last=N``) and
    its event window is unknown (missing from a custom event file) or has not
    ended before ``today``: its dates may not be known yet, so it is dropped.
    """
    kept: list[tuple[int, Window]] = []
    dropped: list[int] = []
    for year in years:
        if len(kept) == wanted:
            break
        event: Optional[Window] = None
        try:
            event = _event_window(spec, year)
            _check_in_year(year, event, "event window")
            unfinished = _is_unfinished(spec, year, event, today)
        except _MissingYearError as exc:
            if not (walking_back and year == today.year):
                raise
            if event is not None and event.end < today:
                # The event is over, so its comparison ranges are knowable:
                # dropping the year would hide a gap in the file.
                raise PlanError(
                    f"{year}: the event window {event} has ended, but the custom "
                    f"comparison has no ranges for {year}. Add {year}'s comparison "
                    "ranges to the file, or choose the years with --years."
                ) from exc
            unfinished = True
        if unfinished:
            dropped.append(year)
        else:
            kept.append((year, event))
    return sorted(kept), sorted(dropped)


def _select_years(spec: PlanSpec, today: date) -> YearsChosen:
    """Apply rule 6 to the requested years, or find the last N finished ones."""
    if spec.years:
        years = sorted(set(spec.years))
        kept, dropped = _sort_years(spec, years, today, len(years), walking_back=False)
        if not kept:
            raise PlanError(
                "None of the requested years has finished yet: "
                + ", ".join(str(y) for y in dropped) + "."
            )
        return kept, dropped

    assert spec.last is not None
    candidates = list(range(today.year, today.year - _MAX_LOOKBACK_YEARS, -1))
    kept, dropped = _sort_years(spec, candidates, today, spec.last, walking_back=True)
    if len(kept) < spec.last:
        found = ", ".join(str(y) for y, _ in sorted(kept)) or "none"
        raise PlanError(
            f"Asked for the last {spec.last} finished years but found only "
            f"{len(kept)} (finished years: {found})."
        )
    return kept, dropped


# --- rules 2-5: one year ----------------------------------------------------

def _clashing_events(spec: PlanSpec, year: int, event: Window, window: Window) -> list[str]:
    """Built-in events whose anchor day in ``year`` falls in ``window``.

    The analysed event's own anchor counts too when it lies outside the event
    window (an offset moved the window off it). For ``event="custom"`` there is
    no own anchor, and every built-in event is checked.
    """
    clashing = []
    for key in BUILTIN_EVENTS:
        anchor = anchor_date(key, year)
        if window.contains(anchor) and not (key == spec.event and event.contains(anchor)):
            clashing.append(key)
    return clashing


def _check_in_year(year: int, window: Window, what: str) -> None:
    if window.start.year != year or window.end.year != year:
        raise PlanError(
            f"{year}: the {what} {window} runs outside calendar year {year}. "
            "Every window must start and end in the event's year, so its days are "
            "counted in that year's row."
        )


def _prior_weeks(
    spec: PlanSpec, year: int, event: Window, step: int
) -> tuple[tuple[Window, ...], tuple[tuple[Window, Window], ...], list[Clash]]:
    n = spec.prior_weeks
    initial = [event.shifted(-k * step) for k in range(1, n + 1)]
    for window in initial:
        _check_in_year(year, window, "comparison window")
    clashes = [Clash(year, w, key)
               for w in initial for key in _clashing_events(spec, year, event, w)]
    if spec.on_clash != "skip" or not clashes:
        return tuple(initial), (), clashes

    clashing = [w for w in initial if _clashing_events(spec, year, event, w)]
    replacements: list[Window] = []
    k = n
    while len(replacements) < len(clashing):
        k += 1
        candidate = event.shifted(-k * step)
        _check_in_year(year, candidate, "replacement comparison window")
        if not _clashing_events(spec, year, event, candidate):
            replacements.append(candidate)
    comparisons = [w for w in initial if w not in clashing] + replacements
    return tuple(comparisons), tuple(zip(clashing, replacements)), clashes


def _check_no_overlap(year: int, event: Window, comparisons: tuple[Window, ...]) -> None:
    labelled = [("event window", event)] + [("comparison window", w) for w in comparisons]
    for i, (name_a, a) in enumerate(labelled):
        for name_b, b in labelled[i + 1:]:
            if a.overlaps(b):
                raise PlanError(
                    f"{year}: the {name_b} {b} overlaps the {name_a} {a}. "
                    "A day can be counted in only one window."
                )


def build_plan(spec: PlanSpec, today: date) -> PlanResult:
    """Build the per-year windows for ``spec``, judged against ``today``.

    ``today`` is the first day with no data (rule 6): a window must end before it.
    """
    _check_spec(spec)
    kept, dropped = _select_years(spec, today)
    step = comparison_step(max(event.days for _, event in kept))

    plans: list[YearPlan] = []
    clashes: list[Clash] = []
    for year, event in kept:  # rule 4 already checked by _sort_years
        if spec.comparison == "custom":
            comparisons = _custom_comparisons(spec, year)
            _check_no_overlap(year, event, comparisons)
            plans.append(YearPlan(year, event, comparisons, ()))
            continue
        comparisons, substitutions, found = _prior_weeks(spec, year, event, step)
        clashes.extend(found)
        plans.append(YearPlan(year, event, comparisons, substitutions))

    return PlanResult(
        years=tuple(plans),
        step=step,
        dropped_years=tuple(dropped),
        clashes=tuple(clashes),
        needs_clash_decision=spec.on_clash is None and bool(clashes),
    )


# --- custom date files ------------------------------------------------------

def _parse_day(value: object, where: str) -> date:
    if isinstance(value, date):  # YAML reads an unquoted 2025-07-08 as a date
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            pass
    raise PlanError(f"{where}: '{value}' is not a date in YYYY-MM-DD form.")


def load_custom_windows(path: Path) -> CustomEventDates:
    """Read per-year dates from a YAML or JSON file.

    A year maps to one start date ``"YYYY-MM-DD"`` (returned as a ``date``, which
    ``build_plan`` expands with offset and length) or to a list of ``[start, end]``
    pairs (returned as ``Window``s, used as given).
    """
    path = Path(path)
    result: CustomEventDates = {}
    for key, value in _read_mapping(path).items():
        try:
            year = int(str(key).strip())
        except ValueError:
            raise PlanError(f"{path}: '{key}' is not a year.") from None
        result[year] = _parse_entry(value, f"{path}, year {year}")
    return result


def _read_mapping(path: Path) -> dict:
    try:
        text = path.read_text()
    except OSError as exc:
        raise PlanError(f"Cannot read {path}: {exc.strerror or exc}.") from None
    is_json = path.suffix.lower() == ".json"
    try:
        data = json.loads(text) if is_json else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise PlanError(f"{path} is not valid {'JSON' if is_json else 'YAML'}: {exc}") from None
    if not isinstance(data, dict) or not data:
        raise PlanError(f"{path} must map each year to a start date or a list of ranges.")
    return data


def _parse_entry(value: object, where: str) -> Union[date, list[Window]]:
    if not isinstance(value, list):
        return _parse_day(value, where)
    if not value:
        raise PlanError(f"{where}: the list of ranges is empty.")
    windows = []
    for pair in value:
        if not isinstance(pair, list) or len(pair) != 2:
            raise PlanError(f"{where}: '{pair}' is not a [start, end] pair.")
        start, end = _parse_day(pair[0], where), _parse_day(pair[1], where)
        try:
            windows.append(Window(start, end))
        except PlanError as exc:
            raise PlanError(f"{where}: {exc}") from None
    return windows
