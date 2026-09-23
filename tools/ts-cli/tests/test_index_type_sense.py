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

from ts_cli.audit.checks_perf import check_p9, check_p11
from ts_cli.audit.checks_security import check_s2
from ts_cli.audit.context import make_context

#: Every value the schema documents, and whether it means "this column is indexed".
INDEXED = ["DEFAULT", "PREFIX_ONLY", "PREFIX_AND_SUBSTRING", "PREFIX_AND_WORD_SUBSTRING"]
NOT_INDEXED = ["DONT_INDEX"]


def _col(name, ctype, index_type, column_id=None):
    props = {"column_type": ctype}
    if index_type is not None:
        props["index_type"] = index_type
    return {"name": name, "column_id": column_id or f"T::{name}", "properties": props}


def _model(cols, **model):
    base = {"name": "M", "columns": cols}
    base.update(model)
    return {"guid": "m-1", "model": base}


# ── S2: PII indexed without table RLS ──────────────────────────────────────

def test_s2_flags_pii_indexed_by_default():
    """The commonest shape in exported TML, and the one S2 exists for."""
    ctx = make_context(models=[_model([_col("customer_email", "ATTRIBUTE", None)])])
    assert len(check_s2(ctx)) == 1


@pytest.mark.parametrize("idx", INDEXED)
def test_s2_flags_pii_with_an_explicit_index_strategy(idx):
    ctx = make_context(models=[_model([_col("customer_email", "ATTRIBUTE", idx)])])
    assert len(check_s2(ctx)) == 1


@pytest.mark.parametrize("idx", NOT_INDEXED)
def test_s2_does_not_flag_pii_with_indexing_suppressed(idx):
    """DONT_INDEX is the mitigation, not the risk — and the only value we emit."""
    ctx = make_context(models=[_model([_col("customer_email", "ATTRIBUTE", idx)])])
    assert check_s2(ctx) == []


# ── P9: indexed ATTRIBUTE id columns ───────────────────────────────────────

def test_p9_flags_a_default_indexed_id_column():
    ctx = make_context(models=[_model([_col("CUSTOMER_ID", "ATTRIBUTE", None)])])
    assert len(check_p9(ctx)) == 1


def test_p9_does_not_flag_an_id_column_with_indexing_suppressed():
    ctx = make_context(models=[_model([_col("CUSTOMER_ID", "ATTRIBUTE", "DONT_INDEX")])])
    assert check_p9(ctx) == []


def test_p9_ignores_a_measure():
    ctx = make_context(models=[_model([_col("CUSTOMER_ID", "MEASURE", None)])])
    assert check_p9(ctx) == []


# ── P11: indexed-column count on a Spotter model ───────────────────────────

def _spotter_model(cols):
    return _model(cols, properties={"spotter_config": {"is_spotter_enabled": True}})


def test_p11_counts_default_indexed_columns():
    cols = [_col(f"C{i}", "ATTRIBUTE", None) for i in range(31)]
    findings = check_p11(make_context(models=[_spotter_model(cols)]))
    assert len(findings) == 1 and findings[0].metric == 31


def test_p11_does_not_count_dont_index_columns():
    """31 suppressed columns are 0 indexed columns, not 31."""
    cols = [_col(f"C{i}", "ATTRIBUTE", "DONT_INDEX") for i in range(31)]
    assert check_p11(make_context(models=[_spotter_model(cols)])) == []


def test_p11_counts_a_mixed_model_correctly():
    cols = ([_col(f"A{i}", "ATTRIBUTE", None) for i in range(31)]
            + [_col(f"B{i}", "ATTRIBUTE", "DONT_INDEX") for i in range(10)])
    findings = check_p11(make_context(models=[_spotter_model(cols)]))
    assert len(findings) == 1 and findings[0].metric == 31
