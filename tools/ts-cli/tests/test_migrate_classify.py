"""Unit tests for dependent classification — the number that sizes a tenant's migration.

The object count points the wrong way: 200 Answers over 4 Views is four repoints, while 40
Answers straight onto the Model is forty rewrites. These tests protect the arithmetic that
tells those two apart.
"""
from __future__ import annotations

from ts_cli.migrate.classify import (
    MODEL_BASED, TABLE_BASED, UNKNOWN, VIEW_BASED, build_effort, classify_dependent,
    kind_of, render_effort_markdown, source_refs,
)


# ---------------------------------------------------------------------------
# Subtype mapping
# ---------------------------------------------------------------------------

def test_subtypes_map_to_migration_cost():
    assert kind_of("AGGR_WORKSHEET") == VIEW_BASED
    assert kind_of("WORKSHEET") == MODEL_BASED
    assert kind_of("ONE_TO_ONE_LOGICAL") == TABLE_BASED


def test_an_unrecognised_subtype_is_UNKNOWN_not_assumed_cheap():
    """Guessing VIEW_BASED for something unrecognised would silently drop it from the
    rewrite set, and it would be discovered only when a user opened a broken object."""
    assert kind_of("SOME_FUTURE_SUBTYPE") == UNKNOWN
    assert kind_of(None) == UNKNOWN


def test_subtype_matching_is_case_insensitive():
    assert kind_of("aggr_worksheet") == VIEW_BASED


# ---------------------------------------------------------------------------
# Finding what a document points at
# ---------------------------------------------------------------------------

def test_the_source_fqn_is_extracted_from_a_liveboard():
    doc = {"liveboard": {"visualizations": [
        {"answer": {"tables": [{"id": "M", "name": "M", "fqn": "src-1"}]}}]}}
    assert source_refs(doc) == ["src-1"]


def test_multiple_distinct_sources_are_all_found():
    doc = {"liveboard": {"visualizations": [
        {"answer": {"tables": [{"fqn": "src-1"}]}},
        {"answer": {"tables": [{"fqn": "src-2"}]}}]}}
    assert source_refs(doc) == ["src-1", "src-2"]


def test_a_repeated_source_is_reported_once():
    doc = {"liveboard": {"visualizations": [
        {"answer": {"tables": [{"fqn": "src-1"}]}},
        {"answer": {"tables": [{"fqn": "src-1"}]}}]}}
    assert source_refs(doc) == ["src-1"]


def test_a_tables_entry_with_no_fqn_is_skipped():
    """Only `fqn` is stable. A name-only reference is exactly what the migration is about
    to change, so it cannot be used to identify the source."""
    doc = {"answer": {"tables": [{"id": "M", "name": "M"}]}}
    assert source_refs(doc) == []


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def test_content_on_a_view_is_free():
    d = classify_dependent("a1", "A", "ANSWER", ["v1"], {"v1": VIEW_BASED})
    assert d["sits_on"] == VIEW_BASED
    assert d["needs_rewrite"] is False


def test_content_on_the_model_needs_rewriting():
    d = classify_dependent("a1", "A", "ANSWER", ["m1"], {"m1": MODEL_BASED})
    assert d["needs_rewrite"] is True


def test_a_MIXED_dependent_takes_the_MOST_EXPENSIVE_classification():
    """An Answer reading one View and one Model still needs the Model half rewritten.
    Calling it VIEW_BASED would under-count the work and skip the object entirely."""
    d = classify_dependent("a1", "A", "ANSWER", ["v1", "m1"],
                           {"v1": VIEW_BASED, "m1": MODEL_BASED})
    assert d["sits_on"] == MODEL_BASED
    assert d["needs_rewrite"] is True


def test_an_UNRESOLVED_source_outranks_everything_and_needs_work():
    """An unresolved dependency is not a safe one to skip."""
    d = classify_dependent("a1", "A", "ANSWER", ["v1", "???"], {"v1": VIEW_BASED})
    assert d["sits_on"] == UNKNOWN
    assert d["needs_rewrite"] is True


def test_a_dependent_with_NO_sources_is_unknown_rather_than_free():
    d = classify_dependent("a1", "A", "ANSWER", [], {})
    assert d["sits_on"] == UNKNOWN
    assert d["needs_rewrite"] is True


def test_table_based_content_needs_rewriting():
    d = classify_dependent("a1", "A", "ANSWER", ["t1"], {"t1": TABLE_BASED})
    assert d["needs_rewrite"] is True


# ---------------------------------------------------------------------------
# The effort roll-up
# ---------------------------------------------------------------------------

def _mixed():
    kinds = {"v1": VIEW_BASED, "v2": VIEW_BASED, "m1": MODEL_BASED, "t1": TABLE_BASED}
    return [classify_dependent(f"a{i}", f"A{i}", "ANSWER", [src], kinds)
            for i, src in enumerate(["v1", "v1", "v1", "v2", "m1", "t1"])]


def test_view_shielded_objects_are_EXCLUDED_from_the_rewrite_count():
    """The whole point. If they counted, a View-heavy tenant would look as expensive as
    any other and the cheap wave would never be identified."""
    e = build_effort(_mixed())
    assert e["dependents"] == 6
    assert e["shielded_by_views"] == 4
    assert e["needs_rewrite"] == 2


def test_the_views_to_repoint_are_named_and_deduped():
    """"4 objects are shielded" is not actionable; "repoint these 2 Views" is."""
    assert build_effort(_mixed())["views_to_repoint"] == ["v1", "v2"]


def test_table_based_objects_are_counted_separately_for_warning():
    assert build_effort(_mixed())["table_based_warning"] == 1


def test_a_tenant_with_no_views_has_rewrite_count_equal_to_object_count():
    items = [classify_dependent(f"a{i}", "A", "ANSWER", ["m1"], {"m1": MODEL_BASED})
             for i in range(5)]
    e = build_effort(items)
    assert e["needs_rewrite"] == e["dependents"] == 5
    assert e["views_to_repoint"] == []


def test_an_empty_dependent_set_does_not_crash():
    assert build_effort([])["dependents"] == 0


# ---------------------------------------------------------------------------
# The report section
# ---------------------------------------------------------------------------

def test_the_report_leads_with_rewrite_count_not_object_count():
    md = render_effort_markdown(build_effort(_mixed()))
    assert "6 dependent object(s)" in md
    assert "2 need rewriting" in md


def test_the_report_names_each_view_to_repoint():
    md = render_effort_markdown(build_effort(_mixed()))
    assert "`v1`" in md and "`v2`" in md


def test_the_report_WARNS_about_table_based_content_and_says_why():
    """A Model-level change never reaches them, so anything assuming Model-level coverage
    silently misses these. The reader has to be told the reason, not just the count."""
    md = render_effort_markdown(build_effort(_mixed()))
    assert "directly on a Table" in md
    assert "never reaches them" in md


def test_the_report_says_so_when_there_is_NO_shielding():
    """Absence of a View section could be read as "no Views found, nothing to worry
    about". It means the opposite: every object is chargeable."""
    items = [classify_dependent("a1", "A", "ANSWER", ["m1"], {"m1": MODEL_BASED})]
    md = render_effort_markdown(build_effort(items))
    assert "No View shielding available" in md
    assert "rewrite count is the object count" in md


def test_the_report_flags_unresolved_dependents_as_chargeable():
    items = [classify_dependent("a1", "A", "ANSWER", ["???"], {})]
    md = render_effort_markdown(build_effort(items))
    assert "could not be resolved" in md
    assert "not a safe one to skip" in md
