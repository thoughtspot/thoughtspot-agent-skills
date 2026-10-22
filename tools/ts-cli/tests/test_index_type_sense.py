"""`index_type` means the opposite of what three checks read (BL-299).

The model schema: *"`DONT_INDEX` suppresses text-search indexing … Omit for full
indexing (default)."* The full set is `DONT_INDEX`, `DEFAULT`, `PREFIX_ONLY`,
`PREFIX_AND_SUBSTRING`, `PREFIX_AND_WORD_SUBSTRING`.

So a column is indexed unless it says `DONT_INDEX`, and an **absent** key means
indexed. S2, P9 and P11 all tested *presence* of the key — inverting both halves:
the real risk (indexed by default) was invisible, and a column explicitly tuned
to `DONT_INDEX` false-positived.

Not academic: `DONT_INDEX` is the only value this repo writes
(`sv_build_model.py`, `databricks/mv_build_model.py`), so every converter-produced
model made S2 a pure false-positive generator.
"""
import pytest

import audit_rule_fixtures as fx
from audit_run_rule import run_rule

#: Every value the schema documents, and whether it means "this column is indexed".
INDEXED = ["DEFAULT", "PREFIX_ONLY", "PREFIX_AND_SUBSTRING", "PREFIX_AND_WORD_SUBSTRING"]
NOT_INDEXED = ["DONT_INDEX"]

# Builders live in audit_rule_fixtures; the P9/P11 contexts are named builders there
# and the S2 ones are its `build_index_pii_ctx` family (S_INPUTS' `index_pii_*`), whose
# legacy answers test_audit_pinned_findings.py pins.


# ── S2: PII indexed without table RLS ──────────────────────────────────────

def test_s2_flags_pii_indexed_by_default():
    """The commonest shape in exported TML, and the one S2 exists for."""
    assert len(run_rule(fx.build_index_pii_ctx(None), "S2")) == 1


@pytest.mark.parametrize("idx", INDEXED)
def test_s2_flags_pii_with_an_explicit_index_strategy(idx):
    assert len(run_rule(fx.build_index_pii_ctx(idx), "S2")) == 1


@pytest.mark.parametrize("idx", NOT_INDEXED)
def test_s2_does_not_flag_pii_with_indexing_suppressed(idx):
    """DONT_INDEX is the mitigation, not the risk — and the only value we emit."""
    assert run_rule(fx.build_index_pii_ctx(idx), "S2") == []


# ── P9: indexed ATTRIBUTE id columns ───────────────────────────────────────

def test_p9_flags_a_default_indexed_id_column():
    assert len(run_rule(fx.index_id_default_indexed(), "P9")) == 1


def test_p9_does_not_flag_an_id_column_with_indexing_suppressed():
    assert run_rule(fx.index_id_not_indexed(), "P9") == []


def test_p9_ignores_a_measure():
    assert run_rule(fx.index_id_measure(), "P9") == []


# ── P11: indexed-column count on a Spotter model ───────────────────────────

def test_p11_counts_default_indexed_columns():
    findings = run_rule(fx.index_spotter_31_default(), "P11")
    assert len(findings) == 1 and findings[0].metric == 31


def test_p11_does_not_count_dont_index_columns():
    """31 suppressed columns are 0 indexed columns, not 31."""
    assert run_rule(fx.index_spotter_31_not_indexed(), "P11") == []


def test_p11_counts_a_mixed_model_correctly():
    findings = run_rule(fx.index_spotter_mixed(), "P11")
    assert len(findings) == 1 and findings[0].metric == 31
