"""Unit tests for the Phase 0 `ts migrate scan-sets` engine.

The assertions encode why the scan exists at all: a cohort column is invisible in TML but
blocks publishing its Model and everything on it, so a detection that misses one reports a
clean Model that is in fact blocked — and a lift-and-shift then drops the Set silently.
"""
from __future__ import annotations

from ts_cli.migrate.sets_scan import (
    blocked_model_guids,
    build_blocked_entry,
    build_scan_report,
    extract_cohort_columns,
    is_cohort_row,
    normalise_dependents,
    render_scan_markdown,
)


def _col(guid, name, owner, subtype="COHORT_SIMPLE"):
    return {"metadata_id": guid, "metadata_name": name,
            "metadata_header": {"id": guid, "name": name, "type": subtype, "owner": owner}}


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def test_a_cohort_subtype_is_detected():
    assert is_cohort_row(_col("c1", "RSET_QTY_BINS", "m1"))


def test_an_ordinary_column_is_not():
    assert not is_cohort_row(_col("c1", "AMOUNT", "m1", subtype="FORMULA"))


def test_detection_matches_the_cohort_PREFIX_not_one_exact_subtype():
    """`COHORT_SIMPLE` is what was observed live, but matching it exactly would silently
    miss a future COHORT_ variant — and the failure mode of missing one is reporting a
    blocked Model as clean, which is the whole thing this command prevents."""
    assert is_cohort_row(_col("c1", "X", "m1", subtype="COHORT_COMPLEX"))
    assert is_cohort_row(_col("c1", "X", "m1", subtype="cohort_simple"))   # case-insensitive


def test_columns_are_attributed_to_their_owning_model():
    rows = [_col("c1", "BINS", "m1"), _col("c2", "TIERS", "m2"),
            _col("c3", "AMOUNT", "m1", subtype="FORMULA")]
    found = extract_cohort_columns(rows, ["m1", "m2"])
    assert [c["name"] for c in found["m1"]] == ["BINS"]      # FORMULA excluded
    assert [c["name"] for c in found["m2"]] == ["TIERS"]


def test_columns_owned_by_out_of_scope_models_are_ignored():
    """One cluster-wide LOGICAL_COLUMN search is sliced per Model, so rows for Models
    nobody asked about must not leak into the report."""
    rows = [_col("c1", "BINS", "m1"), _col("c2", "OTHER", "m_elsewhere")]
    assert set(extract_cohort_columns(rows, ["m1"])) == {"m1"}


def test_a_model_with_no_cohort_column_is_simply_absent():
    assert extract_cohort_columns([_col("c1", "BINS", "m1")], ["m1", "m2"]).keys() == {"m1"}


def test_duplicate_rows_for_one_column_collapse():
    rows = [_col("c1", "BINS", "m1"), _col("c1", "BINS", "m1")]
    assert len(extract_cohort_columns(rows, ["m1"])["m1"]) == 1


# ---------------------------------------------------------------------------
# Dependents — the actionable half
# ---------------------------------------------------------------------------

def test_only_answers_and_liveboards_are_reported_as_affected():
    deps = normalise_dependents([
        {"type": "ANSWER", "name": "Q4 cohort view", "id": "a1"},
        {"type": "LIVEBOARD", "name": "Exec", "id": "l1"},
        {"type": "LOGICAL_TABLE", "name": "Some Model", "id": "t1"},
    ])
    assert [d["type"] for d in deps] == ["ANSWER", "LIVEBOARD"]


def test_dependents_dedupe_and_sort_so_the_report_is_diffable():
    deps = normalise_dependents([
        {"type": "ANSWER", "name": "B", "id": "a2"},
        {"type": "ANSWER", "name": "A", "id": "a1"},
        {"type": "ANSWER", "name": "A", "id": "a1"},
    ])
    assert [d["name"] for d in deps] == ["A", "B"]


def test_dependent_rows_are_read_from_either_key_shape():
    """`_collect_dependents` and `metadata/search` disagree on id/name keys."""
    assert normalise_dependents([{"metadata_type": "ANSWER", "metadata_name": "X",
                                  "metadata_id": "a1"}])[0]["guid"] == "a1"


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def _blocked():
    return build_blocked_entry("Tenant1", "Sales", "m1",
                               [{"name": "RSET_QTY_BINS", "guid": "c1"}],
                               [{"type": "ANSWER", "name": "Q4", "guid": "a1"}])


def test_the_report_carries_the_DENOMINATOR_not_just_the_count():
    """"Three blocked Orgs" is not a decision; "three of twelve" is — and sizing the
    problem before committing to build Phase 2 is the entire purpose of Phase 0."""
    report = build_scan_report(["T1", "T2", "T3"], scanned_models=9, blocked=[_blocked()])
    assert report["scanned"] == {"orgs": 3, "models": 9}
    assert report["summary"] == {"orgs_blocked": 1, "models_blocked": 1,
                                 "objects_affected": 1}


def test_a_clean_fleet_reports_zero_rather_than_omitting_the_summary():
    report = build_scan_report(["T1"], scanned_models=4, blocked=[])
    assert report["summary"]["models_blocked"] == 0
    assert report["blocked"] == []


def test_blocked_entries_sort_so_two_runs_are_diffable():
    a = build_blocked_entry("B_org", "M", "g1", [], [])
    b = build_blocked_entry("A_org", "M", "g2", [], [])
    report = build_scan_report(["A_org", "B_org"], 2, [a, b])
    assert [e["org"] for e in report["blocked"]] == ["A_org", "B_org"]


def test_blocked_model_guids_lets_audit_mark_SET_BLOCKER_without_rescanning():
    report = build_scan_report(["T1"], 1, [_blocked()])
    assert blocked_model_guids(report) == {"m1"}


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def test_markdown_names_the_dependent_objects():
    """"Blocked" alone is a dead end; "blocked by these four Answers" is something a
    tenant can act on."""
    md = render_scan_markdown(build_scan_report(["T1"], 3, [_blocked()]))
    assert "Q4" in md and "RSET_QTY_BINS" in md and "Tenant1 / Sales" in md


def test_markdown_says_a_model_with_no_dependents_is_STILL_blocked():
    """The column blocks publication whether or not anything uses it. A reader who sees an
    empty dependent list must not conclude the Model is fine."""
    entry = build_blocked_entry("T1", "Sales", "m1", [{"name": "BINS", "guid": "c1"}], [])
    md = render_scan_markdown(build_scan_report(["T1"], 1, [entry]))
    assert "still blocked" in md.lower()
    assert "deleting the set unblocks" in md.lower()


def test_markdown_on_a_clean_scan_tells_the_reader_to_re_run_later():
    """A Set added tomorrow blocks the Model from that moment on, so a clean result is a
    point-in-time fact rather than a permanent clearance."""
    md = render_scan_markdown(build_scan_report(["T1"], 5, []))
    assert "No blockers found" in md
    assert "Re-run" in md


def test_markdown_states_there_is_no_override():
    """`apply` refuses with no force flag, deliberately. If the report implied otherwise
    someone would go looking for the flag."""
    md = render_scan_markdown(build_scan_report(["T1"], 1, [_blocked()]))
    assert "no override" in md.lower()
