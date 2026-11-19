"""ts recipe — generate the ThoughtSpot objects for an analytical recipe.

Offline: no command here calls the ThoughtSpot API. Each writes TML files for a
later `ts tml import`, so the skill can show what it generated before anything
lands. JSON goes to stdout, diagnostics to stderr.
"""
from __future__ import annotations

import dataclasses
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import typer

from ts_cli.period_comparison.emit import (
    BUCKET_FORMS, Labels, ModelRef, answer_tml, default_labels, dump_tml, reusable_set_tml,
)
from ts_cli.period_comparison.events import BUILTIN_EVENTS
from ts_cli.period_comparison.windows import (
    PlanError, PlanResult, PlanSpec, Window, build_plan, load_custom_windows,
)

app = typer.Typer(help="Generate the ThoughtSpot objects for an analytical recipe (offline).",
                  no_args_is_help=True)

# Exit codes. A Typer usage error (a missing required option) also exits 2, but
# prints no JSON on stdout; a clash always does.
EXIT_ERROR = 1
EXIT_NEEDS_CLASH_DECISION = 2

_LABEL_KEYS = ("event", "comparison", "other")
# Split "event=…,comparison=…" only at a comma that starts the next key, so a
# label may itself hold a comma.
_LABEL_SPLIT = re.compile(r",\s*(?=(?:event|comparison|other)\s*=)")
_YEARS = re.compile(r"\s*(\d{4})\s*(?:-\s*(\d{4})\s*)?")
# Characters a file name cannot safely carry: path separators and control characters.
_UNSAFE_IN_FILE_NAME = re.compile(r"[/\\\x00-\x1f\x7f]")


def _parse_years(text: str) -> tuple[int, ...]:
    """``2025`` or ``2020-2030`` (inclusive)."""
    match = _YEARS.fullmatch(text)
    if not match:
        raise PlanError(f"--years '{text}' is not a year or a range such as 2020-2030.")
    first, last = int(match[1]), int(match[2] or match[1])
    if last < first:
        raise PlanError(f"--years '{text}' ends before it starts.")
    return tuple(range(first, last + 1))


def _parse_labels(text: str, defaults: Labels) -> Labels:
    """``event=…,comparison=…,other=…``; a part left out keeps its default."""
    given: dict[str, str] = {}
    for part in _LABEL_SPLIT.split(text.strip()):
        key, sep, value = part.partition("=")
        key = key.strip()
        if not sep or key not in _LABEL_KEYS:
            raise PlanError(
                f"--labels: '{part}' is not one of event=…, comparison=… or other=…."
            )
        if key in given:
            raise PlanError(f"--labels gives the {key} label twice.")
        given[key] = value.strip()
    return dataclasses.replace(defaults, **given)


def _parse_date(text: str, option: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise PlanError(f"{option} '{text}' is not a date in YYYY-MM-DD form.") from None


def _first_day_without_data(data_through: Optional[str], today: Optional[str]) -> date:
    """The day every window must end before (``build_plan``'s ``today``).

    ``--data-through D`` gives the day after D, so a window ending on D is kept.
    Without it, the run date: a window ending today is not complete yet. The
    hidden ``--today`` keeps its older meaning, the run date, for the tests.
    """
    if data_through is not None and today is not None:
        raise PlanError("Give --data-through or the hidden --today, not both.")
    if data_through is not None:
        return _parse_date(data_through, "--data-through") + timedelta(days=1)
    if today is not None:
        return _parse_date(today, "--today")
    return date.today()


def _file_stem(name: str) -> str:
    """``name`` made safe as a file name; the TML keeps the name as given."""
    stem = _UNSAFE_IN_FILE_NAME.sub("_", name).strip()
    if stem.startswith("."):
        stem = "_" + stem[1:]
    return stem or "_"


def _span(window: Window) -> list[str]:
    return [window.start.isoformat(), window.end.isoformat()]


def _plan_json(plan: PlanResult, files: list[str]) -> dict:
    return {
        "years": [
            {
                "year": y.year,
                "event": _span(y.event),
                "comparisons": [_span(w) for w in y.comparisons],
                "substitutions": [{"replaced": _span(old), "with": _span(new)}
                                  for old, new in y.substitutions],
            }
            for y in plan.years
        ],
        "step": plan.step,
        "dropped_years": list(plan.dropped_years),
        "clashes": [{"year": c.year, "window": _span(c.window), "event": c.event}
                    for c in plan.clashes],
        "needs_clash_decision": plan.needs_clash_decision,
        "files": files,
    }


def _fail(message: str) -> None:
    typer.echo(json.dumps({"error": message}, indent=2))
    raise typer.Exit(EXIT_ERROR)


def _check_options(*, event: str, event_name: Optional[str], event_dates: Optional[Path],
                   comparison: str, comparison_dates: Optional[Path], bucket: str,
                   set_guid: Optional[str]) -> None:
    """Option combinations the plan builder cannot see."""
    if bucket not in BUCKET_FORMS:
        raise PlanError(
            f"Unknown bucket form '{bucket}'. Expected one of: {', '.join(BUCKET_FORMS)}."
        )
    if set_guid and bucket != "reusable-set":
        raise PlanError("--set-guid applies only to --bucket reusable-set.")
    if event_dates is not None and event != "custom":
        raise PlanError("--event-dates applies only to --event custom.")
    if comparison_dates is not None and comparison != "custom":
        raise PlanError("--comparison-dates applies only to --comparison custom.")
    if event == "custom" and not event_name:
        raise PlanError("A custom event needs --event-name, used in its labels and measure.")


def _report_clashes(plan: PlanResult) -> None:
    for c in plan.clashes:
        print(f"{c.year}: comparison window {c.window} holds {BUILTIN_EVENTS[c.event]}.",
              file=sys.stderr)
    print("Re-run with --on-clash skip or --on-clash keep. No files written.", file=sys.stderr)


def _build_documents(plan: PlanResult, labels: Labels, *, bucket: str, title: str,
                     answer_name: str, bucket_name: str, model: ModelRef, date_column: str,
                     measure_column: str, answer_guid: Optional[str],
                     set_guid: Optional[str]) -> list[tuple[str, str]]:
    """Every (file name, TML text) to write, the Set first: import order.

    Built in full before anything is written, so a builder's error leaves
    nothing on disk.
    """
    documents: list[tuple[str, str]] = []
    if bucket == "reusable-set":
        cohort = reusable_set_tml(plan, labels, date_column, bucket_name, model, set_guid)
        documents.append((f"{_file_stem(bucket_name)}.cohort.tml", dump_tml(cohort)))
    answer = answer_tml(
        plan, labels, bucket=bucket,  # type: ignore[arg-type]
        answer_name=answer_name, bucket_name=bucket_name, model=model,
        date_column=date_column, measure_column=measure_column, event_title=title,
        answer_guid=answer_guid)
    documents.append((f"{_file_stem(answer_name)}.answer.tml", dump_tml(answer)))
    return documents


def _write_all(out_dir: Path, documents: list[tuple[str, str]]) -> list[str]:
    """Write every (file name, text); on a failure, remove what this call wrote."""
    written: list[Path] = []
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        for file_name, text in documents:
            path = out_dir / file_name
            path.write_text(text, encoding="utf-8")
            written.append(path)
    except OSError as exc:
        for path in written:
            path.unlink(missing_ok=True)
        raise PlanError(f"Cannot write to {out_dir}: {exc.strerror or exc}.") from None
    return [str(p) for p in written]


@app.command("period-comparison")
def period_comparison(
    model_name: str = typer.Option(..., "--model-name", help="Name of the Model the Answer searches"),
    model_guid: str = typer.Option(..., "--model-guid", help="GUID of that Model"),
    date_column: str = typer.Option(
        ..., "--date-column", help="Model date column, as the Model spells it, e.g. \"Order Date\""),
    measure_column: str = typer.Option(
        ..., "--measure-column", help="Model sales column, as the Model spells it, e.g. \"Amount\""),
    event: str = typer.Option(..., "--event", help=f"{' | '.join([*BUILTIN_EVENTS, 'custom'])}"),
    event_name: Optional[str] = typer.Option(
        None, "--event-name",
        help="Display name for labels and the measure name; required for custom. "
             "Default: the built-in event's name"),
    event_dates: Optional[Path] = typer.Option(
        None, "--event-dates",
        help="Custom event only: YAML/JSON mapping each year to a start date or a list of "
             "(start, end) date ranges"),
    offset: int = typer.Option(0, "--offset", help="Event window start, in days from the anchor day"),
    length: int = typer.Option(4, "--length", help="Event window length in days"),
    years: Optional[str] = typer.Option(None, "--years", help="2025 or 2020-2030; or use --last"),
    last: Optional[int] = typer.Option(None, "--last", help="The last N finished years"),
    comparison: str = typer.Option("prior-weeks", "--comparison", help="prior-weeks | custom"),
    prior_weeks: int = typer.Option(6, "--prior-weeks", help="Comparison windows per year (prior-weeks)"),
    comparison_dates: Optional[Path] = typer.Option(
        None, "--comparison-dates",
        help="Custom comparison only: YAML/JSON mapping each year to a list of (start, end) date ranges"),
    on_clash: Optional[str] = typer.Option(
        None, "--on-clash",
        help="skip | keep: what to do with a comparison window holding a built-in event's "
             "anchor day (another event's, or this event's own when --offset moves off it). "
             "Without it, clashes are reported and nothing is written (exit 2)"),
    bucket: str = typer.Option("formula", "--bucket", help="formula | reusable-set"),
    name: Optional[str] = typer.Option(
        None, "--name", help="Answer name. Default: \"<event name> Period Comparison\""),
    set_name: Optional[str] = typer.Option(
        None, "--set-name",
        help="Bucket name: the reusable Set, or the Answer's bucket formula. "
             "Default: \"<event name> Period\""),
    labels: Optional[str] = typer.Option(
        None, "--labels", help="event=…,comparison=…,other=…; parts left out keep their defaults"),
    answer_guid: Optional[str] = typer.Option(None, "--answer-guid", help="Update this Answer in place"),
    set_guid: Optional[str] = typer.Option(
        None, "--set-guid", help="Update this reusable Set in place (reusable-set only)"),
    output: Path = typer.Option(..., "-o", "--output", help="Directory to write the TML files to"),
    data_through: Optional[str] = typer.Option(
        None, "--data-through",
        help="YYYY-MM-DD: the last day the Model's data is loaded through. A year with a "
             "window ending after it is dropped (dropped_years). Default: the day before "
             "the run date"),
    today: Optional[str] = typer.Option(None, "--today", hidden=True),
) -> None:
    """Event-period comparison Answer: average daily sales in an event vs its comparison windows, per year.

    Writes <name>.answer.tml and, for --bucket reusable-set, <set name>.cohort.tml
    (import the Set first). Prints the windows per year as JSON. Exit 1 on an
    error ({"error": …}); exit 2, writing nothing, when a comparison window holds a
    built-in event's anchor day (another event's, or this event's own when --offset
    moves off it) and --on-clash is not given.
    """
    try:
        _check_options(event=event, event_name=event_name, event_dates=event_dates,
                       comparison=comparison, comparison_dates=comparison_dates,
                       bucket=bucket, set_guid=set_guid)
        title = event_name or BUILTIN_EVENTS.get(event, event)
        spec = PlanSpec(
            event=event, offset=offset, length=length,
            years=_parse_years(years) if years is not None else (), last=last,
            comparison=comparison, prior_weeks=prior_weeks,
            custom_event=load_custom_windows(event_dates) if event_dates else None,
            custom_comparison=(load_custom_windows(comparison_dates)  # type: ignore[arg-type]
                               if comparison_dates else None),
            on_clash=on_clash,  # type: ignore[arg-type]
        )
        plan = build_plan(spec, _first_day_without_data(data_through, today))
        if plan.needs_clash_decision:
            _report_clashes(plan)
            typer.echo(json.dumps(_plan_json(plan, []), indent=2))
            raise typer.Exit(EXIT_NEEDS_CLASH_DECISION)

        chosen = default_labels(title, comparison, prior_weeks)
        if labels is not None:
            chosen = _parse_labels(labels, chosen)
        documents = _build_documents(
            plan, chosen, bucket=bucket, title=title,
            answer_name=name or f"{title} Period Comparison",
            bucket_name=set_name or f"{title} Period",
            model=ModelRef(name=model_name, guid=model_guid),
            date_column=date_column, measure_column=measure_column,
            answer_guid=answer_guid, set_guid=set_guid)
        files = _write_all(output, documents)
    except PlanError as exc:
        _fail(str(exc))
        return

    print(f"Wrote {len(files)} file(s) to {output}.", file=sys.stderr)
    typer.echo(json.dumps(_plan_json(plan, files), indent=2))
