"""CSV, Snowflake DDL and union-SQL emitters.

The union shape mirrors CUSTOM_CALENDAR.PUBLIC.rlscalendar: N calendars
UNION ALLed with a literal discriminator appended as the final column.

Pure — no I/O beyond the caller-supplied file handle.
"""
from __future__ import annotations

import csv
from datetime import date
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from ts_cli.custom_calendar.spec import CalendarSet

# Column -> Snowflake type. Everything not listed is VARCHAR.
_DATE_COLUMNS = {
    "date", "start_of_week_epoch", "end_of_week_epoch",
    "start_of_month_epoch", "end_of_month_epoch",
    "start_of_quarter_epoch", "end_of_quarter_epoch",
    "start_of_year_epoch", "end_of_year_epoch",
}
_NUMBER_PREFIXES = ("day_number_", "week_number_", "month_number_",
                    "quarter_number_", "absolute_")


def _sql_type(column: str) -> str:
    if column in _DATE_COLUMNS:
        return "DATE"
    if column == "is_weekend":
        return "BOOLEAN"
    if column.startswith(_NUMBER_PREFIXES):
        return "NUMBER"
    return "VARCHAR"


def _cell(value: object) -> object:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def write_csv(rows: Iterable[Dict[str, object]], columns: Sequence[str], fh,
              *, discriminator: Optional[Tuple[str, str]] = None) -> None:
    """Write rows as CSV. Dates ISO-8601, booleans lowercase true/false."""
    header: List[str] = list(columns)
    if discriminator:
        header.append(discriminator[0])
    writer = csv.writer(fh, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        out = [_cell(row[c]) for c in columns]
        if discriminator:
            out.append(discriminator[1])
        writer.writerow(out)


def snowflake_ddl(table: str, columns: Sequence[str], *, database: str, schema: str,
                  discriminator: Optional[str] = None) -> str:
    """CREATE OR REPLACE TABLE for the calendar contract.

    Contract column names are lower-case and MUST stay quoted — Snowflake would
    otherwise fold them to upper case and the API would reject the table.
    The discriminator is caller-named and left unquoted, matching the corpus.
    """
    lines = [f'    "{c}" {_sql_type(c)}' for c in columns]
    if discriminator:
        lines.append(f"    {discriminator} VARCHAR")
    body = ",\n".join(lines)
    return (f'CREATE OR REPLACE TABLE "{database}"."{schema}"."{table}" (\n'
            f"{body}\n);")


def union_sql(cset: CalendarSet, *, database: str, schema: str, target: str,
              source_tables: Sequence[str]) -> str:
    """UNION ALL the variant tables with their literal discriminators."""
    if len(source_tables) != len(cset.variants):
        raise ValueError(
            f"source_tables has {len(source_tables)} entries but the set has "
            f"{len(cset.variants)} variants"
        )
    kind = "VIEW" if cset.materialisation == "view" else "TABLE"
    branches = [
        f'  SELECT *, \'{value}\' AS {cset.discriminator_column} '
        f'FROM "{database}"."{schema}"."{table}"'
        for (value, _spec), table in zip(cset.variants, source_tables)
    ]
    joined = "\n  UNION ALL\n".join(branches)
    return (f'CREATE OR REPLACE {kind} "{database}"."{schema}"."{target}" AS (\n'
            f"{joined}\n);")
