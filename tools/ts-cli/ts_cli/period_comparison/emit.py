"""Turn a period plan into ThoughtSpot TML: a reusable Set, a bucket formula, the
measure formulas and the Answer.

Pure functions apart from reading the packaged Answer template. The Set, the
bucket formula, the measures, the Answer layout (search, columns, table) and the
chart were imported and rendered live (``ts-recipe-answer-period-comparison``
``references/open-items.md``):

* #3 — a Set condition is ``BW`` / ``DATE_FILTER`` / ``EXACT_DATE_RANGE`` with
  ``MM/DD/YYYY`` dates, and the Set binds to the Model as
  ``worksheet: {id: <name>, name: <name>, fqn: <guid>}``. Both forms rendered
  with 300 windows in one group, the cap enforced here.
* #4 / #5 — the measures (``sum_if`` / ``unique_count_if`` in ``safe_divide``)
  compile and render, naming the bucket as ``[<Set name>]`` or
  ``[formula_<bucket name>]``. The user's UI check of the smoke-test Answers saw
  no ``CROSS JOIN`` in the SQL: the sums and distinct-day counts come straight
  from the fact table.
* #6 — the Answer names a reusable Set by name only: no ``cohorts`` key.
* #7 — the bucket is left out of ``search_query`` and ``answer_columns``; the
  measures name it, so the Answer groups by year alone: one row per year, seen
  in the user's UI check of the smoke-test Answers
  (``tools/smoke-tests/smoke_ts_recipe_answer_period_comparison.py``).
* #7 — the chart (CHART_MODE, ADVANCED_COLUMN, ``custom_chart_config``,
  ``custom_visual_props`` and a trimmed ``client_state_v2``, from the user's base
  Answer) imports, and the export keeps its chart type and display mode; the
  user saw it draw: year on the x-axis, the three measures on one y-axis.

The bucket formula and the measures wrap the date column as
``date ( [<date column>] )``, so on a DATE_TIME column they should count days,
not timestamps; a reusable Set's conditions cannot, as they take the bare column.
That is why the skill offers only the formula form on DATE_TIME. Neither form is
verified on a real DATE_TIME column (open item #9). In both forms the
``search_query`` names the bare column: the ``.yearly`` grouping and the year
filter ``between … .12/31/<last>``, whose end bound may drop rows after midnight
on 31 December of the last year in the plan (a dropped year moves it back).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from typing import Literal, Optional

import yaml

from .windows import PlanError, PlanResult, Window

# Conditions (windows) per Set group, and windows per formula branch. Both forms
# rendered live at 300 (open item #3); a query failed between 450 and 600.
MAX_CONDITIONS_PER_GROUP = 300

COMPARISON_MEASURE = "Average Comparison Sales"
VARIANCE_MEASURE = "Variance to Baseline"

BucketForm = Literal["reusable-set", "formula"]
BUCKET_FORMS = ("reusable-set", "formula")


@dataclass(frozen=True)
class Labels:
    """The bucket values: the event group, the comparison group, everything else."""
    event: str
    comparison: str
    other: str


@dataclass(frozen=True)
class ModelRef:
    name: str
    guid: str


# --- names --------------------------------------------------------------------

# Labels sit inside '…' in formulas, and names inside […] references, so a quote
# or a bracket would end one early. Control characters cannot be typed back. In a
# single-quoted literal a lone backslash is dropped (probed live, formula_text.py),
# so a reusable Set's group 'A\B' and the measure's literal 'A\B' (read as 'AB')
# would never match and the measure would read 0. formula_text.ts_string_literal
# could write such text exactly; BL-607 records that option.
_ENDS_EARLY = "which would end it early inside a ThoughtSpot formula"
_FORBIDDEN = {
    "'": ("a single quote", _ENDS_EARLY),
    '"': ("a double quote", _ENDS_EARLY),
    "[": ("a bracket", _ENDS_EARLY),
    "]": ("a bracket", _ENDS_EARLY),
    "\\": ("a backslash", "which ThoughtSpot drops from a quoted formula string, so "
                          "the label would not read as typed and a reusable Set's group "
                          "would not match the measures that compare with it"),
}


def _check_text(value: str, what: str, *, quotes: bool = True) -> None:
    """Raise ``PlanError`` unless ``value`` can be written into a formula.

    ``quotes=False`` allows quote marks and backslashes, for names that only ever sit inside
    ``[…]`` and that come from the Model rather than from the generator.
    """
    if not value or not value.strip():
        raise PlanError(f"The {what} is empty.")
    if value != value.strip():
        raise PlanError(f"The {what} '{value}' starts or ends with a space.")
    if any(ord(ch) < 32 for ch in value):
        raise PlanError(f"The {what} '{value}' holds a line break or control character.")
    for ch, (name, why) in _FORBIDDEN.items():
        if ch in value and (quotes or ch in "[]"):
            raise PlanError(
                f"The {what} {value!r} holds {name} ({ch}), {why}. Remove it "
                "(e.g. \"Mothers Day\", \"Sales and Returns\")."
            )


def validate_labels(labels: Labels) -> None:
    """Raise ``PlanError`` unless the three labels can be written into a formula.

    The labels must also differ ignoring case: ThoughtSpot compares strings
    case-insensitively, so 'Days' and 'days' would be one bucket.
    """
    named = (("event label", labels.event), ("comparison label", labels.comparison),
             ("other label", labels.other))
    for what, value in named:
        _check_text(value, what)
    for i, (what_a, a) in enumerate(named):
        for what_b, b in named[i + 1:]:
            if a.casefold() == b.casefold():
                raise PlanError(
                    f"The {what_a} and the {what_b} are both '{a}'. ThoughtSpot "
                    "compares them ignoring case, so they must differ."
                )


def default_labels(event_display: str, comparison: str, prior_weeks: int) -> Labels:
    """``<Event> Days``, ``<N> Prior Weeks`` / ``Comparison Periods``, ``Not <Event>``."""
    if comparison == "prior-weeks":
        cmp_label = f"{prior_weeks} Prior Week{'' if prior_weeks == 1 else 's'}"
    else:
        cmp_label = "Comparison Periods"
    return Labels(f"{event_display} Days", cmp_label, f"Not {event_display}")


def _measure_names(event_title: str) -> tuple[str, str, str]:
    return (f"Average {event_title} Sales", COMPARISON_MEASURE, VARIANCE_MEASURE)


# --- the plan -----------------------------------------------------------------

def _groups(plan: PlanResult, labels: Labels) -> list[tuple[str, list[Window]]]:
    """(label, windows) for the event group then the comparison group, years ascending.

    Raises ``PlanError`` when the plan still has an undecided clash or a group
    exceeds ``MAX_CONDITIONS_PER_GROUP``.
    """
    validate_labels(labels)
    if plan.needs_clash_decision:
        raise PlanError(
            "Some comparison windows hold a built-in event's anchor day and no clash "
            "choice was given (skip or keep); no TML is written until one is."
        )
    groups = [
        (labels.event, [y.event for y in plan.years]),
        (labels.comparison, [w for y in plan.years for w in y.comparisons]),
    ]
    for label, windows in groups:
        if len(windows) > MAX_CONDITIONS_PER_GROUP:
            raise PlanError(
                f"The '{label}' group has {len(windows)} windows; the limit is "
                f"{MAX_CONDITIONS_PER_GROUP} per group, the most verified to render. "
                "Use fewer years or fewer prior weeks."
            )
    return groups


def _year_span(plan: PlanResult) -> tuple[int, int]:
    """First and last year of the plan, for the Answer's year filter.

    The filter runs from 1 January of the first year to 31 December of the last,
    so every year between them gets a row. A year missing from the middle would
    show as a row of zeros, so the plan's years must be consecutive. (A year
    ``build_plan`` drops is always later than every kept year, so a consecutive
    request stays consecutive; this guards a caller that asks for a gap.)
    """
    years = sorted(y.year for y in plan.years)
    missing = sorted(set(range(years[0], years[-1] + 1)) - set(years))
    if missing:
        raise PlanError(
            "The plan's years (" + ", ".join(str(y) for y in years) + ") are not "
            "consecutive. The Answer's year filter runs from the first to the last, "
            "so " + ", ".join(str(y) for y in missing) + " would show as a row of "
            "zeros. Choose a consecutive run of years."
        )
    return years[0], years[-1]


# --- reusable Set -------------------------------------------------------------

def _condition(window: Window, date_column: str) -> dict:
    return {
        "operator": "BW",
        "column_name": date_column,
        "filter_value_type": "DATE_FILTER",
        "date_filter_values": [{
            "type": "EXACT_DATE_RANGE",
            "oper": "between",
            "date_range": {
                "start_date": window.start.strftime("%m/%d/%Y"),
                "end_date": window.end.strftime("%m/%d/%Y"),
            },
            "date_period": "DAY",
            "for_each_period": "NUM_DATE_PERIODS",
        }],
    }


def cohort_config(plan: PlanResult, labels: Labels, date_column: str) -> dict:
    """The Set's ``config``: two GROUP_BASED groups, one condition per window."""
    groups = [
        {
            "name": label,
            "conditions": [_condition(w, date_column) for w in windows],
            "combine_type": "ANY",
        }
        for label, windows in _groups(plan, labels)
    ]
    return {
        "cohort_type": "SIMPLE",
        "cohort_grouping_type": "GROUP_BASED",
        "anchor_column_id": date_column,
        "groups": groups,
        "null_output_value": labels.other,
        "combine_non_group_values": True,
    }


def reusable_set_tml(plan: PlanResult, labels: Labels, date_column: str, set_name: str,
                     model: ModelRef, set_guid: Optional[str]) -> dict:
    """The reusable Set document; ``set_guid`` (root ``guid``) updates one in place."""
    _check_text(set_name, "Set name")
    doc: dict = {}
    if set_guid:
        doc["guid"] = set_guid
    doc["cohort"] = {
        "name": set_name,
        "worksheet": {"id": model.name, "name": model.name, "fqn": model.guid},
        "config": cohort_config(plan, labels, date_column),
    }
    return doc


# --- formulas -----------------------------------------------------------------

def _date_ref(date_column: str) -> str:
    return f"date ( [{date_column}] )"


def _in_window(window: Window, date_column: str) -> str:
    d = _date_ref(date_column)
    return (f"( {d} >= to_date ( '{window.start.isoformat()}' , '%Y-%m-%d' ) and "
            f"{d} <= to_date ( '{window.end.isoformat()}' , '%Y-%m-%d' ) )")


def bucket_formula_expr(plan: PlanResult, labels: Labels, date_column: str) -> str:
    """One line: ``if ( <event windows> ) then '<event>' else if ( … ) … else '<other>'``."""
    (ev_label, ev_windows), (cmp_label, cmp_windows) = _groups(plan, labels)

    def any_of(windows: list[Window]) -> str:
        return "( " + " or ".join(_in_window(w, date_column) for w in windows) + " )"

    return (f"if {any_of(ev_windows)} then '{ev_label}' "
            f"else if {any_of(cmp_windows)} then '{cmp_label}' "
            f"else '{labels.other}'")


def measure_formulas(bucket_ref: str, labels: Labels, measure_column: str,
                     date_column: str, event_title: str) -> list[dict]:
    """Average daily sales in the event and comparison buckets, and their difference.

    Row-level ``sum_if`` / ``unique_count_if`` over ``bucket_ref`` (``[<Set name>]``
    or ``[formula_<bucket name>]``); the denominator counts days with data.
    """
    validate_labels(labels)
    _check_text(event_title, "event title")
    event_name, cmp_name, var_name = _measure_names(event_title)

    def average(label: str) -> str:
        cond = f"{bucket_ref} = '{label}'"
        return (f"safe_divide ( sum_if ( {cond} , [{measure_column}] ) , "
                f"unique_count_if ( {cond} , {_date_ref(date_column)} ) )")

    return [
        {"id": f"formula_{event_name}", "name": event_name, "expr": average(labels.event)},
        {"id": f"formula_{cmp_name}", "name": cmp_name, "expr": average(labels.comparison)},
        {"id": f"formula_{var_name}", "name": var_name,
         "expr": f"[formula_{event_name}] - [formula_{cmp_name}]"},
    ]


# --- Answer -------------------------------------------------------------------

_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
# Template mappings written out as the JSON strings ThoughtSpot stores.
_JSON_SUFFIX = "_json"


def _load_template() -> dict:
    text = (resources.files(__package__) / "templates" / "answer.yaml").read_text(
        encoding="utf-8")
    return yaml.safe_load(text)


def _fill(node, values: dict[str, str]):
    """Replace ``{name}`` in every key and string; one pass, so values are not re-read."""
    def sub(text: str) -> str:
        return _PLACEHOLDER.sub(lambda m: values[m.group(1)], text)

    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            value = _fill(value, values)
            if isinstance(key, str) and key.endswith(_JSON_SUFFIX):
                key = key[: -len(_JSON_SUFFIX)]
                value = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
            out[sub(key) if isinstance(key, str) else key] = value
        return out
    if isinstance(node, list):
        return [_fill(item, values) for item in node]
    if isinstance(node, str):
        return sub(node)
    return node


def _check_distinct(names: list[str]) -> None:
    seen: dict[str, str] = {}
    for name in names:
        if name.casefold() in seen:
            raise PlanError(
                f"Two formulas in the Answer would both be named '{name}'. "
                "Choose another bucket name or event title."
            )
        seen[name.casefold()] = name


def answer_tml(plan: PlanResult, labels: Labels, *, bucket: BucketForm, answer_name: str,
               bucket_name: str, model: ModelRef, date_column: str, measure_column: str,
               event_title: str, answer_guid: Optional[str] = None) -> dict:
    """The Answer: year by the three measures, filtered to the plan's years.

    ``bucket_name`` is the reusable Set's name, or the name of the Answer formula
    that holds the bucket. Either way the bucket appears only inside the measures
    (open item #7), and a reusable Set is named, never listed in ``cohorts``
    (open item #6). ``answer_guid`` (root ``guid``) updates an Answer in place.
    """
    if bucket not in BUCKET_FORMS:
        raise PlanError(
            f"Unknown bucket form '{bucket}'. Expected one of: {', '.join(BUCKET_FORMS)}."
        )
    if not answer_name.strip():
        raise PlanError("The Answer name is empty.")
    _check_text(bucket_name, "bucket name")
    for what, value in (("date column", date_column), ("measure column", measure_column)):
        _check_text(value, what, quotes=False)

    measure_names = _measure_names(event_title)
    if bucket == "formula":
        _check_distinct([bucket_name, *measure_names])
        bucket_formula = {"id": f"formula_{bucket_name}", "name": bucket_name,
                          "expr": bucket_formula_expr(plan, labels, date_column)}
        formulas = [bucket_formula, *measure_formulas(
            f"[formula_{bucket_name}]", labels, measure_column, date_column, event_title)]
    else:
        _check_distinct(list(measure_names))
        _groups(plan, labels)  # the cap applies to the Set the measures name
        formulas = measure_formulas(
            f"[{bucket_name}]", labels, measure_column, date_column, event_title)

    first, last = _year_span(plan)
    values = {
        "answer_name": answer_name,
        "model_name": model.name,
        "model_guid": model.guid,
        "date_column": date_column,
        "year_column": f"Year({date_column})",
        "measure_event": measure_names[0],
        "measure_comparison": measure_names[1],
        "measure_variance": measure_names[2],
        "first_year": str(first),
        "last_year": str(last),
    }
    answer = _fill(_load_template()["answer"], values)
    answer["formulas"] = formulas

    doc: dict = {}
    if answer_guid:
        doc["guid"] = answer_guid
    doc["answer"] = answer
    return doc


# --- output -------------------------------------------------------------------

def dump_tml(doc: dict) -> str:
    """YAML with keys in insertion order and long strings on one line."""
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True,
                          default_flow_style=False, width=float("inf"))
