"""ts calendar — build, validate and register ThoughtSpot custom calendars."""
from __future__ import annotations

import csv as _csv
import json
import sys
from datetime import date as _date
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import typer

from ts_cli.client import ThoughtSpotClient, resolve_profile
from ts_cli.custom_calendar.anchors import resolve_anchor
from ts_cli.custom_calendar.compare import (
    LABEL_DIMENSIONS, compare_anchors, compare_labels,
)
from ts_cli.custom_calendar.emit import snowflake_ddl, write_csv
from ts_cli.custom_calendar.grid import build_years
from ts_cli.custom_calendar.labels import default_month_names
from ts_cli.custom_calendar.rows import COLUMNS_10, COLUMNS_30, build_rows, columns_for
from ts_cli.custom_calendar.spec import (
    DAYS_EN, MONTHS_EN, CalendarSpec, LabelSpec, leap_index, parse_day_of_week,
    periods_per_year, validate_labels, validate_spec,
)
from ts_cli.custom_calendar.validate import validate_rows, validate_set_labels

app = typer.Typer(help="Custom calendar generation and registration.")

_profile_option = typer.Option(None, "--profile", "-p", envvar="TS_PROFILE",
                               help="Profile name (default: first profile or TS_PROFILE env var)")


def _parse_month(name: str) -> int:
    try:
        return MONTHS_EN.index(name.strip().capitalize()) + 1
    except ValueError:
        raise typer.BadParameter(
            f"Unknown month '{name}'. Expected one of: {', '.join(MONTHS_EN)}"
        ) from None


def build_spec_from_options(
    start_month: str, start_day: str, pattern: str, anchor: str,
    first_year: int, last_year: int, leap_week_period: str,
    year_prefix: str, quarter_prefix: str,
    year_basis: str, monthly_basis: str, quarterly_basis: str,
    fiscal_year_number: str, month_names: Optional[str], day_names: Optional[str],
) -> Tuple[CalendarSpec, LabelSpec]:
    """Turn CLI options into validated spec objects. Pure."""
    try:
        leap: object = "last" if leap_week_period == "last" else int(leap_week_period)
        spec = CalendarSpec(
            start_month=_parse_month(start_month),
            start_day_of_week=parse_day_of_week(start_day),
            pattern=pattern, anchor_rule=anchor,
            first_year=first_year, last_year=last_year, leap_week_period=leap,
        )
        # Validate the spec BEFORE deriving default month names from its pattern —
        # default_month_names() does a raw PATTERNS[pattern] lookup that raises
        # KeyError (not ValueError) for an unknown pattern, which would otherwise
        # escape as an unhandled exception instead of a clean CLI error.
        validate_spec(spec)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None

    kwargs: Dict[str, object] = dict(
        year_prefix=year_prefix, quarter_prefix=quarter_prefix,
        year_basis=year_basis, monthly_basis=monthly_basis,
        quarterly_basis=quarterly_basis, fiscal_year_number=fiscal_year_number,
    )
    if month_names:
        kwargs["month_names"] = tuple(m.strip() for m in month_names.split(","))
    else:
        # LabelSpec defaults to 12 English month names, which fails validation for
        # a 13-period pattern. Pick the pattern-appropriate default instead.
        kwargs["month_names"] = default_month_names(spec.pattern)
    if day_names:
        kwargs["day_names"] = tuple(d.strip() for d in day_names.split(","))
    labels = LabelSpec(**kwargs)

    try:
        validate_labels(labels, periods_per_year(spec))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None
    return spec, labels


def preview_payload(spec: CalendarSpec, labels: LabelSpec) -> Dict[str, object]:
    """Year/period shape only — no rows."""
    li = leap_index(spec)
    years = []
    for fy in build_years(spec):
        years.append({
            "year": fy.number,
            "start": fy.start.isoformat(),
            "end": (fy.end_exclusive).isoformat(),
            "weeks": fy.weeks,
            "period_weeks": [p.weeks for p in fy.periods],
            "long_period": li + 1 if fy.weeks > 52 else None,
        })
    return {"pattern": spec.pattern, "anchor_rule": spec.anchor_rule,
            "periods_per_year": periods_per_year(spec), "years": years}


# Shared option objects so `preview` and `generate` cannot drift apart.
_O = dict(
    start_month=typer.Option(..., "--start-month", help="Fiscal year start month, e.g. February"),
    start_day=typer.Option(..., "--start-day", help="Start day of week, e.g. Monday"),
    pattern=typer.Option("4-5-4", "--pattern", help="4-4-5 | 4-5-4 | 5-4-4 | 13x4"),
    anchor=typer.Option("nearest", "--anchor", help="nearest | first | fixed52"),
    first_year=typer.Option(..., "--first-year", help="First fiscal year"),
    last_year=typer.Option(..., "--last-year", help="Last fiscal year (inclusive)"),
    leap=typer.Option("last", "--leap-week-period",
                      help="Period absorbing a 53rd week: 'last' or an ordinal"),
    year_prefix=typer.Option(
        "", "--year-prefix",
        help="e.g. FY — warning: ThoughtSpot's year filter accepts YYYY only, so a "
             "prefixed year cannot be typed into it (date-range and dynamic filters "
             "still work). --quarter-prefix is unaffected."),
    quarter_prefix=typer.Option("", "--quarter-prefix", help="e.g. Q"),
    year_basis=typer.Option("fiscal", "--year-basis", help="fiscal | gregorian"),
    monthly_basis=typer.Option("fiscal", "--monthly-basis", help="fiscal | gregorian"),
    quarterly_basis=typer.Option("fiscal", "--quarterly-basis", help="fiscal | gregorian"),
    fy_number=typer.Option("start", "--fiscal-year-number", help="start | end"),
    month_names=typer.Option(
        None, "--month-names",
        help="Comma-separated period labels — warning: a label that is not a month "
             "name (e.g. 'Period 01') cannot be selected in a ThoughtSpot filter "
             "widget (date-range and dynamic filters still work)."),
    day_names=typer.Option(None, "--day-names", help="Comma-separated day labels, Sunday first"),
)


@app.command("preview")
def preview_cmd(
    start_month: str = _O["start_month"], start_day: str = _O["start_day"],
    pattern: str = _O["pattern"], anchor: str = _O["anchor"],
    first_year: int = _O["first_year"], last_year: int = _O["last_year"],
    leap_week_period: str = _O["leap"],
    year_prefix: str = _O["year_prefix"], quarter_prefix: str = _O["quarter_prefix"],
    year_basis: str = _O["year_basis"], monthly_basis: str = _O["monthly_basis"],
    quarterly_basis: str = _O["quarterly_basis"], fiscal_year_number: str = _O["fy_number"],
    month_names: Optional[str] = _O["month_names"], day_names: Optional[str] = _O["day_names"],
) -> None:
    """Print the year and period shape without generating rows.

    Use this as the confirmation gate before `generate` — it shows which years
    are 53 weeks and which period absorbs the extra week.

    Output: JSON to stdout.

    Examples:

    \b
      ts calendar preview --start-month February --start-day Monday \\
        --pattern 4-5-4 --anchor nearest --first-year 2015 --last-year 2026
    """
    spec, labels = build_spec_from_options(
        start_month, start_day, pattern, anchor, first_year, last_year,
        leap_week_period, year_prefix, quarter_prefix, year_basis,
        monthly_basis, quarterly_basis, fiscal_year_number, month_names, day_names)
    print(json.dumps(preview_payload(spec, labels), indent=2))


@app.command("generate")
def generate_cmd(
    start_month: str = _O["start_month"], start_day: str = _O["start_day"],
    pattern: str = _O["pattern"], anchor: str = _O["anchor"],
    first_year: int = _O["first_year"], last_year: int = _O["last_year"],
    leap_week_period: str = _O["leap"],
    year_prefix: str = _O["year_prefix"], quarter_prefix: str = _O["quarter_prefix"],
    year_basis: str = _O["year_basis"], monthly_basis: str = _O["monthly_basis"],
    quarterly_basis: str = _O["quarterly_basis"], fiscal_year_number: str = _O["fy_number"],
    month_names: Optional[str] = _O["month_names"], day_names: Optional[str] = _O["day_names"],
    columns: int = typer.Option(
        30, "--columns",
        help="10 or 30. Only 30 can be REGISTERED: ThoughtSpot's createCalendar "
             "rejects a 10-column table on 10.12+ even with correct types "
             "(verified live 2026-09-16). Use 10 only as an intermediate artifact."),
    out: str = typer.Option(..., "--out", help="CSV output path"),
    ddl: Optional[str] = typer.Option(
        None, "--ddl",
        help="Also write the Snowflake CREATE TABLE statement for this shape to this "
             "path — quoted lower-case columns, which the API requires. "
             "Needs --database and --schema."),
    database: Optional[str] = typer.Option(None, "--database", help="Database name for --ddl"),
    schema: Optional[str] = typer.Option(None, "--schema", help="Schema name for --ddl"),
    table: Optional[str] = typer.Option(
        None, "--table", help="Table name for --ddl (default: the --out file stem)"),
    discriminator_column: Optional[str] = typer.Option(
        None, "--discriminator-column", help="RLS discriminator column name"),
    discriminator_value: Optional[str] = typer.Option(
        None, "--discriminator-value", help="RLS discriminator literal for this variant"),
) -> None:
    """Generate a calendar as CSV.

    Output: the CSV at --out; a JSON summary to stdout. Diagnostics to stderr.

    Examples:

    \b
      ts calendar generate --start-month February --start-day Monday \\
        --pattern 4-5-4 --anchor nearest --first-year 2015 --last-year 2026 \\
        --out retail.csv

      ts calendar generate --start-month February --start-day Monday \\
        --first-year 2015 --last-year 2026 --out retail.csv \\
        --ddl retail.sql --database CUSTOM_CALENDAR --schema PUBLIC
    """
    spec, labels = build_spec_from_options(
        start_month, start_day, pattern, anchor, first_year, last_year,
        leap_week_period, year_prefix, quarter_prefix, year_basis,
        monthly_basis, quarterly_basis, fiscal_year_number, month_names, day_names)
    if bool(discriminator_column) != bool(discriminator_value):
        raise typer.BadParameter(
            "--discriminator-column and --discriminator-value must be given together")
    if ddl and not (database and schema):
        raise typer.BadParameter("--ddl requires --database and --schema")
    if not ddl and (database or schema or table):
        raise typer.BadParameter(
            "--database, --schema and --table only apply with --ddl")

    cols = columns_for(columns)
    rows = build_rows(spec, labels, columns=columns)
    disc = (discriminator_column, discriminator_value) if discriminator_column else None
    with open(out, "w", encoding="utf-8", newline="") as fh:
        write_csv(rows, cols, fh, discriminator=disc)
    print(f"Wrote {len(rows)} rows to {out}", file=sys.stderr)

    summary: Dict[str, object] = {"rows": len(rows), "columns": len(cols), "path": out}
    if ddl:
        statement = snowflake_ddl(table or Path(out).stem, cols, database=database,
                                  schema=schema, discriminator=discriminator_column)
        Path(ddl).write_text(statement + "\n", encoding="utf-8")
        print(f"Wrote DDL to {ddl}", file=sys.stderr)
        summary["ddl_path"] = ddl
    print(json.dumps(summary))


@app.command("compare")
def compare_cmd(
    vary: str = typer.Option(..., "--vary",
                             help="anchor | " + " | ".join(LABEL_DIMENSIONS)),
    start_month: str = _O["start_month"], start_day: str = _O["start_day"],
    pattern: str = _O["pattern"], anchor: str = _O["anchor"],
    first_year: int = _O["first_year"], last_year: int = _O["last_year"],
    leap_week_period: str = _O["leap"],
    year_prefix: str = _O["year_prefix"], quarter_prefix: str = _O["quarter_prefix"],
    month_names: Optional[str] = _O["month_names"], day_names: Optional[str] = _O["day_names"],
    max_samples: int = typer.Option(10, "--max-samples",
                                    help="Cap on sample differing rows"),
) -> None:
    """Show what one option choice actually changes, before generating a calendar.

    Reports only disagreements. "0 of 364 rows differ" is a useful answer — it
    means the choice is irrelevant for this calendar.

    --vary anchor also reports first_divergence: the first year where the anchor
    rules stop agreeing. Any test range shorter than that will make the native
    ThoughtSpot API look correct when it is not.

    Output: JSON to stdout.

    Examples:

    \b
      ts calendar compare --vary year-basis --start-month December \\
        --start-day Monday --pattern 4-4-5 --anchor first \\
        --first-year 2024 --last-year 2024

      ts calendar compare --vary anchor --start-month February \\
        --start-day Monday --pattern 4-5-4 --anchor nearest \\
        --first-year 2015 --last-year 2026
    """
    spec, labels = build_spec_from_options(
        start_month, start_day, pattern, anchor, first_year, last_year,
        leap_week_period, year_prefix, quarter_prefix, "fiscal", "fiscal",
        "fiscal", "start", month_names, day_names)

    if vary == "anchor":
        print(json.dumps(compare_anchors(spec), indent=2))
        return
    try:
        print(json.dumps(compare_labels(spec, labels, vary, max_samples=max_samples),
                         indent=2))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None


def match_contract(header: Sequence[str]) -> List[str]:
    """Return the column contract a CSV header satisfies, or raise.

    The header must equal `COLUMNS_10` or `COLUMNS_30` exactly, optionally
    followed by exactly one extra trailing RLS discriminator column. Inferring
    the contract from the header's WIDTH instead (the original implementation)
    let a malformed file pass: a 30-column calendar minus `monthly` and
    `quarterly` is 28 wide, so it was read against the 10-column contract, whose
    ten columns were all present, and validated clean.
    """
    cols = list(header)
    for contract in (COLUMNS_30, COLUMNS_10):
        expected = list(contract)
        if cols == expected:
            return expected
        # Exactly one trailing discriminator column (name is caller-chosen).
        if len(cols) == len(expected) + 1 and cols[:len(expected)] == expected:
            return expected

    # No match: describe the failure against whichever contract it is closest to.
    closest = max((COLUMNS_10, COLUMNS_30),
                  key=lambda c: len(set(cols) & set(c)))
    expected = list(closest)
    missing = [c for c in expected if c not in cols]
    unexpected = [c for c in cols if c not in expected]
    detail: List[str] = []
    if missing:
        detail.append(f"missing column(s): {', '.join(missing)}")
    if unexpected:
        detail.append(f"unexpected column(s): {', '.join(unexpected)}")
    if not detail:
        detail.append(f"columns are out of contract order — expected {expected}")
    raise ValueError(
        f"CSV header does not match the {len(expected)}-column calendar contract "
        f"(one trailing discriminator column is allowed): " + "; ".join(detail))


def read_calendar_csv(path: str) -> Tuple[List[Dict[str, object]], List[str]]:
    """Read a calendar CSV back into typed rows plus its contract column list.

    A trailing discriminator column is tolerated and excluded from the contract.
    """
    with open(path, newline="", encoding="utf-8") as fh:
        raw = list(_csv.DictReader(fh))
    if not raw:
        return [], []
    contract = match_contract(list(raw[0].keys()))

    rows: List[Dict[str, object]] = []
    for r in raw:
        typed: Dict[str, object] = {}
        for col in contract:
            val = r[col]
            if col == "date" or col.endswith("_epoch"):
                typed[col] = _date.fromisoformat(val)
            elif col == "is_weekend":
                typed[col] = val.strip().lower() == "true"
            elif col.startswith(("day_number_", "week_number_", "month_number_",
                                 "quarter_number_", "absolute_")):
                typed[col] = int(val)
            else:
                typed[col] = val
        rows.append(typed)
    return rows, contract


@app.command("validate")
def validate_cmd(
    csv_paths: List[str] = typer.Option(..., "--csv",
                                        help="Calendar CSV to check (repeat for an RLS set)"),
    allow_label_drift: bool = typer.Option(
        False, "--allow-label-drift",
        help="Downgrade cross-variant label mismatches from error to warning"),
) -> None:
    """Check calendars against the column contract and the structural invariants.

    With two or more --csv paths, also checks cross-variant label consistency:
    ThoughtSpot indexes label values across every row of the registered object
    while RLS resolves a user to one variant, so AUGUST in one variant and AUG
    in another offers both as search suggestions while only one can return rows.

    Output: JSON to stdout. Exits non-zero if any finding has severity "error".

    Examples:

    \b
      ts calendar validate --csv retail.csv
      ts calendar validate --csv tenant_a.csv --csv tenant_b.csv
    """
    findings = []
    # Keyed on the path AS GIVEN, never the basename: `a/cal.csv` and `b/cal.csv`
    # both stem to "cal", which collapsed them into one variant so the
    # cross-variant check saw len < 2 and silently returned no findings — a false
    # pass on the single check multi---csv mode exists for.
    seen: Dict[str, str] = {}
    for path in csv_paths:
        resolved = str(Path(path).resolve())
        if resolved in seen:
            raise typer.BadParameter(
                f"--csv names the same file twice: '{seen[resolved]}' and '{path}'. "
                "Each variant of an RLS set must be a distinct file.")
        seen[resolved] = path

    variant_rows: Dict[str, List[Dict[str, object]]] = {}
    for path in csv_paths:
        try:
            rows, contract = read_calendar_csv(path)
        except ValueError as exc:
            findings.append({"severity": "error", "code": "column-contract",
                             "message": str(exc), "source": path})
            continue
        variant_rows[path] = rows
        for f in validate_rows(rows, columns=contract):
            findings.append({"severity": f.severity, "code": f.code,
                             "message": f.message, "source": path})

    for f in validate_set_labels(variant_rows, allow_label_drift=allow_label_drift):
        findings.append({"severity": f.severity, "code": f.code,
                         "message": f.message, "source": "<set>"})

    print(json.dumps({"findings": findings}, indent=2))
    if any(f["severity"] == "error" for f in findings):
        raise typer.Exit(1)


# ThoughtSpot calendar_type values. 13x4 has no native equivalent.
_API_CALENDAR_TYPE = {
    "4-4-5": "FOUR_FOUR_FIVE",
    "4-5-4": "FOUR_FIVE_FOUR",
    "5-4-4": "FIVE_FOUR_FOUR",
}


def build_register_payload(*, name: str, connection: str, database: str, schema: str,
                           table: str, native: bool,
                           spec: Optional[CalendarSpec]) -> Dict[str, object]:
    """Build the POST /api/rest/2.0/calendars/create body.

    `native` uses FROM_INPUT_PARAMS, which is only correct for the `fixed52`
    anchor rule: the API emits fixed 364-day years and never inserts a leap week,
    so any other rule would silently ship a drifting calendar. Verified against
    LULULEMON on 2026-09-15 — see the skill's references/anchor-rules.md.

    Pure — no I/O — so it is unit-testable without a live instance.
    """
    payload: Dict[str, object] = {
        "name": name,
        "table_reference": {
            "connection_identifier": connection,
            "database_name": database,
            "schema_name": schema,
            "table_name": table,
        },
        "creation_method": "FROM_INPUT_PARAMS" if native else "FROM_EXISTING_TABLE",
    }
    if not native:
        return payload

    if spec is None:
        raise ValueError("--native requires the generation options")
    if spec.anchor_rule != "fixed52":
        raise ValueError(
            f"--native cannot express anchor rule '{spec.anchor_rule}'. The ThoughtSpot "
            "API emits fixed 364-day years with no leap week, which matches only "
            "'fixed52'. Generate a table and register it with FROM_EXISTING_TABLE instead."
        )
    if spec.pattern not in _API_CALENDAR_TYPE:
        raise ValueError(
            f"--native cannot express pattern '{spec.pattern}' — the API has no "
            f"13x4 calendar type. Generate a table and register it instead."
        )
    # end_date is the last day the calendar actually covers — the day before the
    # next fiscal year's anchor — not a nominal "start of last_year + 1". The
    # nominal-start form overshoots into a partial fiscal period on the live API
    # (verified 2026-09-16 against generate-csv — see references/open-items.md
    # item #5), and the overshoot grows with the range.
    last_day = resolve_anchor(spec, spec.last_year + 1) - timedelta(days=1)
    payload.update({
        "calendar_type": _API_CALENDAR_TYPE[spec.pattern],
        "month_offset": MONTHS_EN[spec.start_month - 1],
        "start_day_of_week": DAYS_EN[spec.start_day_of_week],
        "start_date": f"{spec.start_month:02d}/01/{spec.first_year}",
        "end_date": last_day.strftime("%m/%d/%Y"),
    })
    return payload


@app.command("register")
def register_cmd(
    name: str = typer.Option(..., "--name", help="Calendar name in ThoughtSpot"),
    connection: str = typer.Option(..., "--connection", help="Connection name or GUID"),
    database: str = typer.Option(..., "--database"),
    schema: str = typer.Option(..., "--schema"),
    table: str = typer.Option(..., "--table", help="Warehouse table or view to register"),
    native: bool = typer.Option(False, "--native",
                                help="Use FROM_INPUT_PARAMS (fixed52 anchor rule only)"),
    start_month: Optional[str] = typer.Option(None, "--start-month"),
    start_day: Optional[str] = typer.Option(None, "--start-day"),
    pattern: str = typer.Option("4-5-4", "--pattern"),
    anchor: str = typer.Option("nearest", "--anchor"),
    first_year: Optional[int] = typer.Option(None, "--first-year"),
    last_year: Optional[int] = typer.Option(None, "--last-year"),
    profile: Optional[str] = _profile_option,
) -> None:
    """Register a calendar with ThoughtSpot.

    Default path is FROM_EXISTING_TABLE: register a table this CLI generated.
    --native uses FROM_INPUT_PARAMS and is REFUSED for any anchor rule other
    than fixed52, because the API never inserts a leap week.

    Output: JSON from POST /api/rest/2.0/calendars/create, to stdout.

    Examples:

    \b
      ts calendar register --name RetailCal --connection "Snowflake Prod" \\
        --database CUSTOM_CALENDAR --schema PUBLIC --table retail_cal
    """
    spec = None
    if native:
        missing = [n for n, v in (("--start-month", start_month), ("--start-day", start_day),
                                  ("--first-year", first_year), ("--last-year", last_year))
                   if v is None]
        if missing:
            raise typer.BadParameter(f"--native requires {', '.join(missing)}")
        spec, _ = build_spec_from_options(
            start_month, start_day, pattern, anchor, first_year, last_year,
            "last", "", "", "fiscal", "fiscal", "fiscal", "start", None, None)
    try:
        payload = build_register_payload(
            name=name, connection=connection, database=database, schema=schema,
            table=table, native=native, spec=spec)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None

    client = ThoughtSpotClient(resolve_profile(profile))
    resp = client.post("/api/rest/2.0/calendars/create", json=payload)
    print(json.dumps(resp.json()))


@app.command("search")
def search_cmd(
    connection: Optional[str] = typer.Option(None, "--connection",
                                             help="Connection name or GUID to scope the search"),
    profile: Optional[str] = _profile_option,
) -> None:
    """List registered custom calendars, to verify what landed.

    Output: JSON array from POST /api/rest/2.0/calendars/search, to stdout.

    Examples:

    \b
      ts calendar search --connection "Snowflake Prod"
    """
    payload: Dict[str, object] = {}
    if connection:
        payload["connection_identifier"] = connection
    client = ThoughtSpotClient(resolve_profile(profile))
    resp = client.post("/api/rest/2.0/calendars/search", json=payload)
    print(json.dumps(resp.json()))
