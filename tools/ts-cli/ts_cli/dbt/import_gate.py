"""Lint gate both dbt Model builders run before the Model is imported.

`ts dbt build-model` and `ts dbt-export build-model --import` both import Model
TML; neither linted it until audit 2026-10-29 (finding 9.3). The Snowflake and
Databricks builders gate the same way.
"""
from __future__ import annotations

import sys


def lint_gate(model_tml: dict) -> None:
    """Exit non-zero, listing every finding, if the Model TML fails the model
    invariants. Runs before any ThoughtSpot import.

    I5 (`aggregation: COUNT_DISTINCT` on a physical measure) is reported but does
    not block. A dbt `ts_aggregation: count_distinct` tag is often ThoughtSpot's own
    column round-tripped by ts-convert-to-dbt, and on a numeric column it works;
    converting it safely means reading the existing Model first (audit 2026-10-29
    findings 9.1/9.2, routed to the backlog).
    Until then the column imports exactly as it did before this gate existed.
    """
    from ts_cli.tml_lint import lint_tml

    findings = lint_tml(model_tml)
    advisory = [f for f in findings if f.startswith("I5")]
    blocking = [f for f in findings if f not in advisory]
    for finding in advisory:
        print(f"LINT (advisory — on a text or date column this imports as an attribute; "
              f"audit 2026-10-29 9.2): {finding}", file=sys.stderr)
    for finding in blocking:
        print(f"LINT: {finding}", file=sys.stderr)
    if blocking:
        raise SystemExit(
            f"Model TML failed {len(blocking)} lint check(s) (listed above); "
            "nothing was imported.")
