"""Per-wave alias assembly for an Org migration — spec step 7.

The step is one full-document replace per wave, so its failure mode is fleet-wide silent
alias loss. These tests are mostly about the refusals.
"""
from __future__ import annotations

from ts_cli.alias import WILDCARD_GROUP, merge_aliases, translations_to_columns
from ts_cli.migrate.aliases import (
    missing_org_coverage, orgs_present, translations_from_mapping, wave_problems,
)
from ts_cli.migrate.schema import GAP_BLOCKER, MATCHED, SET_BLOCKER, ColumnMappingRow


def _row(tenant, published, status=MATCHED, model="M"):
    return ColumnMappingRow(model=model, tenant_column=tenant,
                            tenant_column_id=f"T::{published or tenant}",
                            published_column=published, status=status)


def _cols(*triples):
    """Alias columns for (column, org, alias) triples, via the real builder."""
    return translations_to_columns([
        {"column": c, "locale": "en-US", "org": o, "group": WILDCARD_GROUP, "alias": a}
        for c, o, a in triples])


# --- deriving the aliases from the approved mapping --------------------------------

def test_the_alias_is_the_INVERSE_of_the_rename():
    """`apply` rewrote the tenant's content Segment -> STRING_1 to bind it to the published
    Model. The alias puts Segment back as what that Org's users SEE, so the aliased column
    is the PUBLISHED name and the alias value is the TENANT's."""
    out = translations_from_mapping([_row("Segment", "STRING_1")], "ORG1")
    assert out == [{"column": "STRING_1", "locale": "en-US", "org": "ORG1",
                    "group": WILDCARD_GROUP, "alias": "Segment",
                    "description": "ORG1 tenant alias"}]


def test_scope_is_always_org_wide():
    """A tenant migration wants every user in the Org to see the tenant's names, and a group
    scope beside a wildcard would make both resolve to the base name."""
    out = translations_from_mapping([_row("Segment", "STRING_1")], "ORG1")
    assert out[0]["group"] == WILDCARD_GROUP


def test_columns_whose_names_already_AGREE_produce_no_alias():
    """Nothing to restore, and the document is size-bound (5 MB async / 25 MB hard), so an
    entry that changes nothing is not free."""
    assert translations_from_mapping([_row("AMOUNT", "AMOUNT")], "ORG1") == []


def test_an_UNMAPPED_gap_produces_no_alias():
    """No target to alias onto. `apply` refuses these, so reaching here means the mapping
    was edited after approval."""
    assert translations_from_mapping([_row("Segment", "", GAP_BLOCKER)], "ORG1") == []


def test_a_SET_BLOCKER_row_produces_no_alias():
    """The Model cannot be published at all, so there is nothing to alias onto."""
    assert translations_from_mapping([_row("Segment", "STRING_1", SET_BLOCKER)], "ORG1") == []


def test_one_alias_per_published_column_even_across_models():
    """`column_map` is flat across Models because the rewrite is document-wide; the alias
    document is keyed the same way, so a second entry for one published column would be an
    ambiguous duplicate rather than extra coverage."""
    out = translations_from_mapping(
        [_row("Segment", "STRING_1", model="A"), _row("Segment", "STRING_1", model="B")],
        "ORG1")
    assert len(out) == 1


# --- the catastrophic check: was the export COMPLETE? -----------------------------

def test_an_org_missing_from_the_export_is_REFUSED():
    """Alias load is full-document with no delta until 26.10, so the merged document
    REPLACES what the Model carries. An export that came back partial silently strips every
    Org it missed, and those users see STRING_1 where they saw Region — no error anywhere."""
    existing = _cols(("STRING_1", "ORG1", "Segment"))
    problems = missing_org_coverage(existing, ["ORG1", "ORG2", "ORG3"])
    assert len(problems) == 2
    assert any("ORG2" in p for p in problems) and any("ORG3" in p for p in problems)
    assert "base column names" in problems[0]


def test_a_complete_export_passes():
    existing = _cols(("STRING_1", "ORG1", "Segment"), ("DATE_1", "ORG2", "Order Date"))
    assert missing_org_coverage(existing, ["ORG1", "ORG2"]) == []


def test_coverage_is_by_ORG_not_by_COUNT():
    """A count is satisfiable by the wrong Orgs: three entries for one tenant would pass a
    "three or more" assertion while two tenants are being wiped."""
    existing = _cols(("STRING_1", "ORG1", "A"), ("STRING_2", "ORG1", "B"),
                     ("STRING_3", "ORG1", "C"))
    problems = missing_org_coverage(existing, ["ORG1", "ORG2"])
    assert len(problems) == 1 and "ORG2" in problems[0]


def test_no_expected_orgs_means_nothing_to_lose():
    """The first wave has no already-cut-over tenant, so an empty export is correct."""
    assert missing_org_coverage([], []) == []


def test_orgs_present_reads_every_org_in_the_document():
    cols = _cols(("STRING_1", "ORG1", "A"), ("DATE_1", "ORG2", "B"))
    assert orgs_present(cols) == {"ORG1", "ORG2"}


# --- the whole gate ---------------------------------------------------------------

def test_wave_problems_reports_a_missing_org_AND_an_overlap_together():
    """An alias document is assembled once per wave and the window is serialised, so finding
    the second fault only after re-running the first fix wastes everyone's queue slot."""
    existing = _cols(("STRING_1", "ORG1", "Segment"))
    merged = translations_to_columns([
        {"column": "STRING_1", "locale": "en-US", "org": "ORG1",
         "group": WILDCARD_GROUP, "alias": "Segment"},
        {"column": "STRING_1", "locale": "en-US", "org": "ORG1",
         "group": "ANALYSTS", "alias": "Segment"},
    ])
    problems = wave_problems(existing, merged, expected_orgs=["ORG1", "ORG9"])
    assert any("ORG9" in p for p in problems)
    assert any("BASE column name" in p for p in problems)


def test_wave_problems_is_empty_for_a_clean_wave():
    existing = _cols(("STRING_1", "ORG1", "Segment"))
    incoming = translations_to_columns(
        translations_from_mapping([_row("Order Date", "DATE_1")], "ORG2"))
    merged = merge_aliases(existing, incoming)
    assert wave_problems(existing, merged, expected_orgs=["ORG1"]) == []


def test_a_real_merge_KEEPS_the_previous_wave_and_adds_the_new_one():
    """The end-to-end property the whole step exists for: ORG1 keeps its aliases while ORG2
    gains its own."""
    existing = _cols(("STRING_1", "ORG1", "Segment"))
    incoming = translations_to_columns(
        translations_from_mapping([_row("Segment", "STRING_1")], "ORG2"))
    merged = merge_aliases(existing, incoming)
    assert orgs_present(merged) == {"ORG1", "ORG2"}
    assert wave_problems(existing, merged, expected_orgs=["ORG1"]) == []


def test_a_merge_that_LOST_entries_is_refused():
    """Unreachable with an additive merge, asserted anyway: the consequence is silent alias
    loss across every already-migrated tenant at once."""
    existing = _cols(("STRING_1", "ORG1", "A"), ("DATE_1", "ORG2", "B"))
    problems = wave_problems(existing, _cols(("STRING_1", "ORG1", "A")),
                             expected_orgs=["ORG1", "ORG2"])
    assert any("FEWER alias entries" in p for p in problems)
