"""Probe runner: a RAW ThoughtSpot formula against a warehouse SQL oracle, over one fixture.

Each case carries ``source_formula`` (the oracle's SQL) and ``ts_formula`` (the ThoughtSpot
formula as written, with ``[T::COL]`` for a fixture column). The translator is bypassed —
``run.py``'s ``Deps.translate`` seam returns ``ts_formula`` — so a run measures how ThoughtSpot
reads a formula, not what a translator emits. Everything else (load, VALIDATE_ONLY bisect,
AgentQL, compare, teardown with confirmation) is ``run.py``'s.

    PYTHONPATH= uv run --no-project --python 3.12 --with pyyaml --with typer --with requests \
        --with keyring --with snowflake-connector-python \
      python -I tools/formula-fidelity/run_raw.py --cases tools/formula-fidelity/cases/probes/<file>.jsonl \
        --profile se-thoughtspot --sf-profile "ThoughtSpot Partner (AP)" --connection APJ_TAB \
        --out <path>.json

Used for probe record §7 "Quotes and grouping" (2026-10-07, BL-364 / BL-365).
"""
from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import run as RUN  # noqa: E402


def raw_translate(case: dict, fixture: dict, ts_table: str) -> dict:
    formula = case["ts_formula"].replace("[T::", f"[{ts_table}::")
    role = "MEASURE" if case["role"] == "aggregate" else "ATTRIBUTE"
    return {"status": "TRANSLATED", "formula": formula, "role": role, "agentql_wrapper": None,
            "traps": [], "notes": [], "unresolved": []}


def main(argv=None) -> int:
    args = RUN._args(argv)
    cases = RUN.caselib.load_cases(args.cases)
    fixtures = RUN.caselib.fixtures_for(cases, args.cases.parent)
    if not (args.profile and args.sf_profile):
        print("error: --profile and --sf-profile are required", file=sys.stderr)
        return 2
    return RUN.live_run(args, cases, fixtures, f"Raw probe: {args.cases.name}",
                        RUN.Deps(translate=raw_translate))


if __name__ == "__main__":
    sys.exit(main())
