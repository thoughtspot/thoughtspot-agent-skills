"""The chart-type enum and the new-library twin rule (BL-449).

Three things are pinned here:

1. ``CHART_TYPE_ENUM`` equals the enum block in the shared schema doc, so the doc (which
   records how and where the enum was read live) and the code cannot drift apart.
2. Every chart type a converter can emit, or that the lint and the Tableau generator
   classify, is in that enum: one value outside it fails the WHOLE import, PARTIAL policy
   included. ``ADVANCED_BUBBLE`` sat in ``tableau/liveboard.py`` for months while the
   schema's enum did not list it; this is the check that would have said so.
3. The Tableau generator's measure floor and cartesian layout classify a new-library
   (``ADVANCED_*``) type like its Legacy twin. Before this, each held a hand-kept list of
   ``ADVANCED_*`` names, and the lists disagreed. The lint's axis set is NOT twin-derived:
   it is pinned to the phase-1 members until a render check shows a bare added type blank.
"""
import re
from pathlib import Path

import pytest

from ts_cli import chart_types as ct
from ts_cli import tml_lint
from ts_cli.tableau import liveboard as lb

SCHEMA = (Path(__file__).resolve().parents[3]
          / "agents" / "shared" / "schemas" / "thoughtspot-chart-types.md")


def _doc_enum() -> set[str]:
    text = SCHEMA.read_text(encoding="utf-8")
    m = re.search(r"## The authoritative `answer\.chart\.type` enum \((\d+) values\)\s*```(.*?)```",
                  text, re.S)
    assert m, "enum block not found in thoughtspot-chart-types.md"
    values = {v.strip() for v in m.group(2).replace("\n", " ").split(",") if v.strip()}
    assert len(values) == int(m.group(1)), "the heading's count disagrees with the block"
    return values


# ── 1. doc ↔ code ────────────────────────────────────────────────────────────

def test_code_enum_matches_the_schema_doc():
    assert set(ct.CHART_TYPE_ENUM) == _doc_enum()


def test_enum_holds_the_new_library_types_read_live_2026_11_08():
    added = {"ADVANCED_BUBBLE", "ADVANCED_CANDLESTICK", "ADVANCED_DONUT", "ADVANCED_FUNNEL",
             "ADVANCED_HEATMAP", "ADVANCED_PARETO", "ADVANCED_SCATTER", "ADVANCED_WATERFALL"}
    assert added <= ct.CHART_TYPE_ENUM
    assert len(ct.NEW_LIBRARY_TYPES) == 18
    assert "GAUGE" not in ct.CHART_TYPE_ENUM and "TABLE" not in ct.CHART_TYPE_ENUM


# ── 2. nothing outside the enum ──────────────────────────────────────────────

def _converter_chart_maps():
    from ts_cli.powerbi import answers as pbi
    from ts_cli.qlik import answers as qlik
    from ts_cli.sisense import answers as sis
    return {
        "tableau._MARK_TO_CHART": set(lb._MARK_TO_CHART.values()),
        "powerbi._CHART_MAP": set(pbi._CHART_MAP.values()),
        "qlik._CHART_MAP": set(qlik._CHART_MAP.values()),
        "sisense._CHART_MAP": set(sis._CHART_MAP.values()) - {None},   # None = skip the widget
    }


@pytest.mark.parametrize("name", sorted(_converter_chart_maps()))
def test_every_converter_chart_map_emits_enum_values_only(name):
    assert _converter_chart_maps()[name] - ct.CHART_TYPE_ENUM == set()


def test_classification_sets_hold_enum_values_only():
    assert set(tml_lint.CHART_NEEDS_AXIS) - ct.CHART_TYPE_ENUM == set()
    assert set(lb.CHART_NEEDS) - ct.CHART_TYPE_ENUM == set()
    assert set(lb._CARTESIAN) - ct.CHART_TYPE_ENUM == set()


# ── 3. the twin rule ─────────────────────────────────────────────────────────

def test_legacy_twin():
    assert ct.legacy_twin("ADVANCED_COLUMN") == "COLUMN"
    assert ct.legacy_twin("ADVANCED_DONUT") == "PIE"       # the one renamed twin
    assert ct.legacy_twin("SCATTER") == "SCATTER"          # a Legacy type is its own twin
    for t in ct.NEW_LIBRARY_TYPES:
        assert ct.legacy_twin(t) in ct.CHART_TYPE_ENUM, t


def test_with_new_library_twins_adds_only_twins_of_members():
    got = ct.with_new_library_twins({"PIE", "SCATTER"})
    assert got == {"PIE", "SCATTER", "ADVANCED_DONUT", "ADVANCED_SCATTER"}


def test_axis_set_holds_only_the_phase_1_new_library_types():
    # verify-render shares this set. The types added since 2026-11-08 stay out until a
    # render check shows a bare tile of one drawing blank (BL-449).
    assert {t for t in tml_lint.CHART_NEEDS_AXIS if t in ct.NEW_LIBRARY_TYPES} == {
        "ADVANCED_LINE", "ADVANCED_COLUMN", "ADVANCED_BAR", "ADVANCED_AREA",
        "ADVANCED_STACKED_COLUMN", "ADVANCED_STACKED_BAR", "ADVANCED_STACKED_AREA",
        "ADVANCED_LINE_COLUMN", "ADVANCED_LINE_STACKED_COLUMN"}


@pytest.mark.parametrize("adv", sorted(t for t in ct.NEW_LIBRARY_TYPES
                                        if ct.legacy_twin(t) in lb._LEGACY_CHART_NEEDS))
def test_measure_floor_matches_the_twin_for_the_explicit_floors(adv):
    assert lb._chart_needs(adv) == lb._chart_needs(ct.legacy_twin(adv)) == 2


def test_advanced_pivot_table_floor_is_not_coupled_to_pivot_table():
    # PIVOT_TABLE needs no measure; ADVANCED_PIVOT_TABLE resolves differently (chart-types
    # schema) and keeps main's floor of 1 until a live check says otherwise.
    assert lb._chart_needs("PIVOT_TABLE") == 0
    assert lb._chart_needs("ADVANCED_PIVOT_TABLE") == 1


@pytest.mark.parametrize("adv", sorted(ct.NEW_LIBRARY_TYPES))
def test_cartesian_layout_matches_each_new_library_types_twin(adv):
    assert (adv in lb._CARTESIAN) == (ct.legacy_twin(adv) in lb._CARTESIAN)
