"""Show what an option choice actually changes, before a calendar is generated.

Reports only DISAGREEMENTS. A null result ("0 of 364 rows differ") is the
informative case: it tells the user the choice is irrelevant for their calendar.

Pure — no I/O.
"""
from __future__ import annotations

import dataclasses
from datetime import timedelta
from typing import Dict, List, Sequence, Tuple

from ts_cli.custom_calendar.anchors import resolve_anchor
from ts_cli.custom_calendar.grid import build_years
from ts_cli.custom_calendar.labels import render
from ts_cli.custom_calendar.spec import CalendarSpec, LabelSpec

# Option name -> the values worth comparing. Keys are the CLI --vary spellings.
LABEL_DIMENSIONS: Dict[str, Tuple[str, ...]] = {
    "year-basis": ("fiscal", "gregorian"),
    "monthly-basis": ("fiscal", "gregorian"),
    "quarterly-basis": ("fiscal", "gregorian"),
    "fiscal-year-number": ("start", "end"),
}

# The label columns a dimension can move.
_WATCHED = ("year", "monthly", "quarterly")

ANCHOR_RULES: Tuple[str, ...] = ("nearest", "first", "fixed52")


def _field_for(dimension: str) -> str:
    return dimension.replace("-", "_")


def compare_labels(spec: CalendarSpec, labels: LabelSpec, dimension: str,
                   *, max_samples: int = 10) -> Dict[str, object]:
    """Render every row under each value of `dimension` and report disagreements."""
    if dimension not in LABEL_DIMENSIONS:
        raise ValueError(
            f"Unknown dimension '{dimension}'. Expected one of: "
            f"{', '.join(LABEL_DIMENSIONS)}"
        )
    values = list(LABEL_DIMENSIONS[dimension])
    field = _field_for(dimension)
    variants = {v: dataclasses.replace(labels, **{field: v}) for v in values}

    total = 0
    differing = 0
    samples: List[Dict[str, object]] = []

    for fy in build_years(spec):
        for period in fy.periods:
            d = period.start
            while d < period.end_exclusive:
                total += 1
                rendered = {v: render(variants[v], fy, period, d) for v in values}
                first = rendered[values[0]]
                if any(rendered[v][c] != first[c] for v in values[1:] for c in _WATCHED):
                    differing += 1
                    if len(samples) < max_samples:
                        samples.append({
                            "date": d.isoformat(),
                            **{v: {c: rendered[v][c] for c in _WATCHED} for v in values},
                        })
                d += timedelta(days=1)

    return {
        "vary": dimension,
        "values": values,
        "total_rows": total,
        "differing_rows": differing,
        "samples": samples,
    }


def compare_anchors(spec: CalendarSpec,
                    rules: Sequence[str] = ANCHOR_RULES) -> Dict[str, object]:
    """Year start dates under each anchor rule, plus where they first disagree."""
    rules = list(rules)
    years: List[Dict[str, object]] = []
    first_divergence = None
    nearest_vs_fixed = None

    for year in range(spec.first_year, spec.last_year + 1):
        row: Dict[str, object] = {"year": year}
        starts = {}
        for rule in rules:
            start = resolve_anchor(dataclasses.replace(spec, anchor_rule=rule), year)
            starts[rule] = start
            row[rule] = start.isoformat()
        years.append(row)

        if first_divergence is None and len(set(starts.values())) > 1:
            first_divergence = year
        if (nearest_vs_fixed is None
                and "nearest" in starts and "fixed52" in starts
                and starts["nearest"] != starts["fixed52"]):
            nearest_vs_fixed = year

    return {
        "vary": "anchor",
        "values": rules,
        "years": years,
        "first_divergence": first_divergence,
        "nearest_vs_fixed52_first_divergence": nearest_vs_fixed,
    }
