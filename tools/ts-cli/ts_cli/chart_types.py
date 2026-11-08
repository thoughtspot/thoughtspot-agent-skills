"""ThoughtSpot ``answer.chart.type`` values, and the new-library twin rule.

``CHART_TYPE_ENUM`` is the one code copy of the enum in
``agents/shared/schemas/thoughtspot-chart-types.md``, which records how and where it was
read: the import validator's own error message, last on 2026-11-08 (BL-449), on a dev
build whose release version is unreadable. A value here can still be rejected by an
older cluster. ``tests/test_chart_types.py`` fails when this list and the doc disagree.

The ``ADVANCED_*`` values are the new charts library (Muze). Each one has a Legacy twin:
its own name without the prefix, except ``ADVANCED_DONUT``, whose twin is ``PIE``. Code
that classifies chart types (which need an axis encoding, which need a second measure,
which take the cartesian axis layout) lists Legacy types only and derives the new-library
members with ``with_new_library_twins``. Hand-kept ``ADVANCED_*`` lists drifted apart: the
lint held nine, the Tableau generator a different eight, one of them missing from the
documented enum.

Pure constants and functions, no I/O.
"""
from __future__ import annotations

from typing import Iterable

NEW_LIBRARY_PREFIX = "ADVANCED_"

# The 44 values read on 2026-06-16 from a release build (the SE demo cluster). A converter's
# chart map may emit only these until the dev-build additions below are seen on a release.
RELEASE_BUILD_CHART_TYPES = frozenset({
    "ADVANCED_AREA", "ADVANCED_BAR", "ADVANCED_COLUMN", "ADVANCED_LINE",
    "ADVANCED_LINE_COLUMN", "ADVANCED_LINE_STACKED_COLUMN", "ADVANCED_PIVOT_TABLE",
    "ADVANCED_STACKED_AREA", "ADVANCED_STACKED_BAR", "ADVANCED_STACKED_COLUMN",
    "AREA", "BAR", "BUBBLE", "CANDLESTICK", "COLUMN", "CUSTOM_CHART", "FUNNEL",
    "GEO_AREA", "GEO_BUBBLE", "GEO_EARTH_AREA", "GEO_EARTH_BAR", "GEO_EARTH_BUBBLE",
    "GEO_EARTH_GRAPH", "GEO_EARTH_HEATMAP", "GEO_HEATMAP", "GRID_TABLE", "HEATMAP", "KPI",
    "LINE", "LINE_COLUMN", "LINE_STACKED_COLUMN", "MUZE_STUDIO", "PARETO", "PIE",
    "PIVOT_TABLE", "SANKEY", "SCATTER", "SPIDER_WEB", "STACKED_AREA", "STACKED_BAR",
    "STACKED_COLUMN", "TREEMAP", "WATERFALL", "WHISKER_SCATTER",
})

# Added since, read 2026-11-08 on dev builds that report no release version. The import
# validator there accepts them; no named release is known to.
DEV_BUILD_CHART_TYPES = frozenset({
    "ADVANCED_BUBBLE", "ADVANCED_CANDLESTICK", "ADVANCED_DONUT", "ADVANCED_FUNNEL",
    "ADVANCED_HEATMAP", "ADVANCED_PARETO", "ADVANCED_SCATTER", "ADVANCED_WATERFALL",
})

CHART_TYPE_ENUM = RELEASE_BUILD_CHART_TYPES | DEV_BUILD_CHART_TYPES

NEW_LIBRARY_TYPES = frozenset(t for t in CHART_TYPE_ENUM if t.startswith(NEW_LIBRARY_PREFIX))

# The one new-library type whose Legacy twin is not its own name minus the prefix.
_RENAMED_TWINS = {"ADVANCED_DONUT": "PIE"}


def legacy_twin(chart_type: str) -> str:
    """The Legacy type a new-library type mirrors. A Legacy type is its own twin."""
    if chart_type in _RENAMED_TWINS:
        return _RENAMED_TWINS[chart_type]
    if chart_type.startswith(NEW_LIBRARY_PREFIX):
        return chart_type[len(NEW_LIBRARY_PREFIX):]
    return chart_type


def with_new_library_twins(legacy_types: Iterable[str]) -> frozenset:
    """``legacy_types`` plus every new-library type whose Legacy twin is among them."""
    base = frozenset(legacy_types)
    return base | frozenset(t for t in NEW_LIBRARY_TYPES if legacy_twin(t) in base)
