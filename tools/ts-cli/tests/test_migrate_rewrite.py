"""Unit tests for the content-rewrite transform.

Shapes come from real exports on `se-thoughtspot` and `nebula-damian-alias` (2026-07-28),
not from the schema docs. Where a test looks pedantic, the docstring says what breaks in
production without it -- and for this module the answer is usually "an object that imports
cleanly and renders wrong", which is why the coverage gate at the bottom exists.
"""
from __future__ import annotations

import json

from ts_cli.migrate.rewrite import (
    LABEL_PATHS, repoint_source, residual_references, rewrite_client_state,
    rewrite_content, rewrite_view, substitute_bracketed, substitute_decorated,
)

MAP = {"Segment": "STRING_1", "Order Date": "DATE_1"}


# ---------------------------------------------------------------------------
# Bracketed tokens
# ---------------------------------------------------------------------------

def test_bracketed_column_tokens_are_rewritten():
    assert substitute_bracketed("[Segment] [AMOUNT]", MAP) == "[STRING_1] [AMOUNT]"


def test_search_query_SYNTAX_survives_verbatim():
    """Real search queries mix column tokens with syntax that must not be touched:
    `[date].'last 12 months' top 5`. Mangling it produces a query that imports and then
    returns the wrong rows."""
    q = "[Segment] [Order Date].'last 12 months' top 5 by [AMOUNT]"
    assert substitute_bracketed(q, MAP) == \
        "[STRING_1] [DATE_1].'last 12 months' top 5 by [AMOUNT]"


def test_unmapped_tokens_are_left_alone():
    """A formula reference like `[formula_Unit Cost]` is not a Model column."""
    assert substitute_bracketed("[formula_Unit Cost] [Segment]", MAP) == \
        "[formula_Unit Cost] [STRING_1]"


def test_an_empty_query_does_not_crash():
    assert substitute_bracketed("", MAP) == ""


# ---------------------------------------------------------------------------
# Decorated names (search_output_column)
# ---------------------------------------------------------------------------

def test_an_aggregation_prefix_is_preserved_around_the_rewrite():
    """Observed live: `search_output_column` carries decoration -- `Total LINEAMOUNT`,
    `Month(YM)`. Replacing the whole value would destroy the aggregation."""
    assert substitute_decorated("Total Segment", MAP) == "Total STRING_1"


def test_a_bucket_wrapper_is_preserved():
    assert substitute_decorated("Month(Order Date)", MAP) == "Month(DATE_1)"


def test_an_exact_match_wins_over_partial_substitution():
    assert substitute_decorated("Segment", MAP) == "STRING_1"


def test_the_LONGEST_matching_column_wins():
    """With both `Order` and `Order Date` mapped, `Order Date` must match first or the
    value is corrupted into `DATE_X Date`."""
    m = {"Order": "STRING_9", "Order Date": "DATE_1"}
    assert substitute_decorated("Total Order Date", m) == "Total DATE_1"


def test_a_column_name_embedded_in_a_LONGER_WORD_is_not_touched():
    """`Segment` must not match inside `Segmentation`."""
    assert substitute_decorated("Total Segmentation", MAP) == "Total Segmentation"


# ---------------------------------------------------------------------------
# client_state_v2 — the blob a naive rewrite corrupts
# ---------------------------------------------------------------------------

def _cs():
    return json.dumps({
        "version": "V4DOT2",
        "columnProperties": [{"columnId": "Segment", "columnProperty": {"dataLabels": True}}],
        "systemSeriesColors": [{"serieName": "Segment", "color": "#06BF7F"}],
        "axisProperties": [{"id": "3352d226-717b-46fb-8a3b-4e7c9dc355d6",
                            "properties": {"axisType": "Y"}}]})


def test_the_two_name_bearing_fields_are_rewritten():
    out = json.loads(rewrite_client_state(_cs(), MAP))
    assert out["columnProperties"][0]["columnId"] == "STRING_1"
    assert out["systemSeriesColors"][0]["serieName"] == "STRING_1"


def test_the_axis_GUID_is_left_alone():
    """`axisProperties[].id` is a stable GUID, not a column name. Rewriting it would
    detach the axis configuration."""
    out = json.loads(rewrite_client_state(_cs(), MAP))
    assert out["axisProperties"][0]["id"] == "3352d226-717b-46fb-8a3b-4e7c9dc355d6"


def test_unrelated_state_survives_untouched():
    out = json.loads(rewrite_client_state(_cs(), MAP))
    assert out["version"] == "V4DOT2"
    assert out["columnProperties"][0]["columnProperty"] == {"dataLabels": True}


def test_an_unparseable_blob_is_returned_UNCHANGED_rather_than_raising():
    """Display state is not worth failing a migration over, and a corrupted blob is worse
    than a stale one."""
    assert rewrite_client_state("not json at all", MAP) == "not json at all"


# ---------------------------------------------------------------------------
# Data source repoint
# ---------------------------------------------------------------------------

def _answer():
    return {"answer": {
        "name": "Revenue by Segment",
        "tables": [{"id": "ACME_MODEL", "name": "ACME_MODEL", "fqn": "src-guid"}],
        "search_query": "[Segment] [AMOUNT]",
        "answer_columns": [{"name": "Segment"}, {"name": "AMOUNT"}],
        "table": {"table_columns": [{"column_id": "Segment"}],
                  "ordered_column_ids": ["Segment", "AMOUNT"]},
        "chart": {"chart_columns": [{"column_id": "Segment"}],
                  "axis_configs": [{"x": ["Segment"], "y": ["AMOUNT"]}],
                  "client_state_v2": _cs()},
        "formulas": [{"name": "f", "expr": "to_string ( [Order Date] , \"%d-%m-%y\" )"}]}}


def test_the_fqn_is_repointed():
    out = repoint_source(_answer(), "tgt-guid", "PUBLISHED_MODEL")
    assert out["answer"]["tables"][0]["fqn"] == "tgt-guid"


def test_the_NAME_is_repointed_too_not_just_the_fqn():
    """Resolution falls back to the name when the fqn is dead. A stale name means a
    silent bind to the wrong object if the target holds a same-named one."""
    out = repoint_source(_answer(), "tgt-guid", "PUBLISHED_MODEL")
    assert out["answer"]["tables"][0]["name"] == "PUBLISHED_MODEL"
    assert out["answer"]["tables"][0]["id"] == "PUBLISHED_MODEL"


# ---------------------------------------------------------------------------
# Full content rewrite
# ---------------------------------------------------------------------------

def test_every_measured_reference_path_is_rewritten():
    """The 12 whole-string paths plus the two token paths, from the live scan."""
    a = rewrite_content(_answer(), MAP, "tgt-guid", "PUBLISHED_MODEL")["answer"]
    assert a["search_query"] == "[STRING_1] [AMOUNT]"
    assert [c["name"] for c in a["answer_columns"]] == ["STRING_1", "AMOUNT"]
    assert a["table"]["table_columns"][0]["column_id"] == "STRING_1"
    assert a["table"]["ordered_column_ids"] == ["STRING_1", "AMOUNT"]
    assert a["chart"]["chart_columns"][0]["column_id"] == "STRING_1"
    assert a["chart"]["axis_configs"][0]["x"] == ["STRING_1"]
    assert "[DATE_1]" in a["formulas"][0]["expr"]
    assert json.loads(a["chart"]["client_state_v2"])["columnProperties"][0]["columnId"] \
        == "STRING_1"


def test_the_visualization_TITLE_is_never_rewritten():
    """`answer.name` is a human label. Three real titles matched a column name exactly,
    and 134 more matched as substrings ("Sales by Region"). Rewriting renames the user's
    chart."""
    doc = _answer()
    doc["answer"]["name"] = "Segment"
    out = rewrite_content(doc, MAP, "tgt-guid")
    assert out["answer"]["name"] == "Segment"


def test_a_filters_display_name_is_never_rewritten():
    doc = {"liveboard": {"filters": [{"display_name": "Segment", "column": ["Segment"]}]}}
    out = rewrite_content(doc, MAP, "tgt")
    assert out["liveboard"]["filters"][0]["display_name"] == "Segment"
    assert out["liveboard"]["filters"][0]["column"] == ["STRING_1"]   # the ref IS rewritten


def test_the_input_document_is_not_mutated():
    """`apply` keeps the original for the backup and for a diff. Mutating in place would
    quietly corrupt both."""
    doc = _answer()
    rewrite_content(doc, MAP, "tgt-guid")
    assert doc["answer"]["search_query"] == "[Segment] [AMOUNT]"


def test_an_unmapped_column_is_left_alone():
    """Most columns match 1:1 and are absent from the map. Touching them would be a
    rename nobody asked for."""
    out = rewrite_content(_answer(), MAP, "tgt")["answer"]
    assert "AMOUNT" in out["search_query"]


# ---------------------------------------------------------------------------
# Views — the shield
# ---------------------------------------------------------------------------

def _view():
    return {"view": {
        "name": "MIGTEST_VIEW",
        "tables": [{"id": "ACME_MODEL", "name": "ACME_MODEL", "fqn": "src-guid"}],
        "search_query": "[Segment] [AMOUNT]",
        "view_columns": [
            {"name": "MySegment", "search_output_column": "Segment"},
            {"name": "MyAmount", "search_output_column": "Total AMOUNT"}]}}


def test_a_view_repoint_rewrites_what_it_READS():
    out = rewrite_view(_view(), MAP, "tgt-guid", "PUBLISHED_MODEL")["view"]
    assert out["tables"][0]["fqn"] == "tgt-guid"
    assert out["search_query"] == "[STRING_1] [AMOUNT]"
    assert out["view_columns"][0]["search_output_column"] == "STRING_1"


def test_a_view_repoint_PRESERVES_what_it_EXPOSES():
    """The shield, proven live 2026-07-28: the alias survives a repoint to a different
    Model through a different column, and the untouched Answer keeps returning data.
    If `name` were rewritten, every dependent would break at once."""
    out = rewrite_view(_view(), MAP, "tgt-guid")["view"]
    assert [c["name"] for c in out["view_columns"]] == ["MySegment", "MyAmount"]


def test_the_shield_holds_even_when_the_alias_EQUALS_a_mapped_column():
    """The dangerous case: a View exposing `Segment` under its own name `Segment`. The
    alias must still be preserved, or its dependents break."""
    doc = _view()
    doc["view"]["view_columns"][0]["name"] = "Segment"
    out = rewrite_view(doc, MAP, "tgt")["view"]
    assert out["view_columns"][0]["name"] == "Segment"
    assert out["view_columns"][0]["search_output_column"] == "STRING_1"


# ---------------------------------------------------------------------------
# The coverage gate
# ---------------------------------------------------------------------------

def test_a_fully_rewritten_document_has_no_residual_references():
    out = rewrite_content(_answer(), MAP, "tgt-guid", "PUBLISHED_MODEL")
    assert residual_references(out, MAP) == []


def test_a_MISSED_field_is_caught():
    """The gate's whole purpose. A partial rewrite imports cleanly and renders wrong, so
    this must fail loudly rather than look like success."""
    out = rewrite_content(_answer(), MAP, "tgt-guid")
    out["answer"]["some_new_platform_field"] = "Segment"
    residual = residual_references(out, MAP)
    assert residual and residual[0][1] == "Segment"


def test_a_missed_BRACKETED_token_is_caught():
    out = rewrite_content(_answer(), MAP, "tgt-guid")
    out["answer"]["another_query"] = "[Segment]"
    assert residual_references(out, MAP)


def test_label_paths_do_not_register_as_residual():
    """They are supposed to still hold the old name. Reporting them would make the gate
    permanently red and train people to ignore it."""
    doc = _answer()
    doc["answer"]["name"] = "Segment"
    assert residual_references(rewrite_content(doc, MAP, "tgt"), MAP) == []


def test_a_preserved_VIEW_alias_does_not_register_as_residual():
    """Same reason: preserving it is the point."""
    doc = _view()
    doc["view"]["view_columns"][0]["name"] = "Segment"
    assert residual_references(rewrite_view(doc, MAP, "tgt"), MAP) == []


def test_every_label_path_is_documented_as_needing_review_on_platform_change():
    """LABEL_PATHS is the one thing the coverage gate CANNOT verify: a new label field
    would be wrongly rewritten and the gate would report success. Keep it small and
    deliberate."""
    assert len(LABEL_PATHS) <= 8
    assert all(p.endswith(("name", "display_name")) for p in LABEL_PATHS)


# ---------------------------------------------------------------------------
# Qualified `Source::Column` references
# ---------------------------------------------------------------------------

from ts_cli.migrate.rewrite import substitute_qualified  # noqa: E402


def test_a_qualified_reference_has_its_COLUMN_half_rewritten():
    """Found live 2026-07-28: 82 occurrences across 45 real Liveboards, in filters,
    ordered_chips, view_filters and parameter_overrides. A whole-string match misses all
    of them, and so did the coverage gate -- a silent hole in both."""
    assert substitute_qualified("Retail - Apparel::Segment", MAP) == \
        "Retail - Apparel::STRING_1"


def test_the_SOURCE_half_is_left_alone():
    """The migration pairs tenant Model to published Model BY NAME, so the qualifier does
    not change. Rewriting it would point the reference at nothing."""
    out = substitute_qualified("Sales::Segment", MAP)
    assert out.startswith("Sales::")


def test_an_unqualified_value_passes_through_untouched():
    assert substitute_qualified("Segment", MAP) == "Segment"


def test_a_qualified_reference_to_an_UNMAPPED_column_is_untouched():
    assert substitute_qualified("Sales::Amount", MAP) == "Sales::Amount"


def test_a_column_name_CONTAINING_a_colon_still_resolves():
    """`::` splits on the FIRST colon pair, so a column named `A:B` survives."""
    m = {"A:B": "STRING_9"}
    assert substitute_qualified("Sales::A:B", m) == "Sales::STRING_9"


def test_BOTH_forms_in_the_same_field_are_handled():
    """Real Liveboards mix them: 25 qualified and 39 bare in `filters[].column[]`."""
    doc = {"liveboard": {"filters": [{"column": ["Sales::Segment", "Segment"]}]}}
    out = rewrite_content(doc, MAP, "tgt")
    assert out["liveboard"]["filters"][0]["column"] == ["Sales::STRING_1", "STRING_1"]


def test_a_qualified_reference_in_parameter_overrides_is_rewritten():
    """A path the original scan never surfaced, precisely BECAUSE it holds qualified
    references -- the scan was looking for whole-string matches."""
    doc = {"liveboard": {"parameter_overrides": [{"value": {"name": "Sales::Segment"}}]}}
    out = rewrite_content(doc, MAP, "tgt")
    assert out["liveboard"]["parameter_overrides"][0]["value"]["name"] == "Sales::STRING_1"


def test_the_gate_CATCHES_a_missed_qualified_reference():
    """Without this the gate reports success on a document that still points at the
    tenant's column -- the exact failure mode the gate exists to prevent."""
    doc = {"liveboard": {"some_new_field": "Sales::Segment"}}
    assert residual_references(doc, MAP)
