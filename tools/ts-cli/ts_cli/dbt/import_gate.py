"""Lint gate both dbt Model builders run before anything is imported.

`ts dbt build-model` and `ts dbt-export build-model --import` both POST Model TML;
neither linted it until audit 2026-10-29 (findings 9.3, and its sibling on the
schema.yml path). The Snowflake and Databricks builders gate the same way.
"""
from __future__ import annotations

import sys


def lint_gate(model_tml: dict, *, updating: bool) -> None:
    """Exit non-zero, listing every finding, if the Model TML fails the model
    invariants. Nothing has been written when this runs.

    When ``updating`` an existing Model, an I5 finding is reported as advisory and
    does not block: the builders keep a round-tripped `COUNT_DISTINCT` column as it
    is on update (see `formula_pass.count_distinct_pass`), which I5's round-trip
    exception allows.
    """
    from ts_cli.tml_lint import lint_tml

    findings = lint_tml(model_tml)
    advisory = [f for f in findings if updating and f.startswith("I5")]
    blocking = [f for f in findings if f not in advisory]
    for finding in advisory:
        print(f"LINT (advisory, existing Model kept as is): {finding}", file=sys.stderr)
    for finding in blocking:
        print(f"LINT: {finding}", file=sys.stderr)
    if blocking:
        raise SystemExit(
            f"Model TML failed {len(blocking)} lint check(s) (listed above); "
            "nothing was imported.")
