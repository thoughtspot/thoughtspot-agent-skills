"""S2 / S3 / S8 / S9 — the four security checks that no test ever called.

2026-09-22 audit finding 6.1: 27 of 51 checks are *imported* by a test and never
invoked. `tests/test_checks_security.py` imported `check_s2`, `check_s3`,
`check_s8` and `check_s9` and called none of them, so nothing had ever shown that
any of the four can return a `Finding`. For a security check that is the worst
class of defect — a check that cannot fire reports "no problem" about PII and
RLS. `check_p6`/`check_d2` shipped in exactly that state for months
(see test_checks_varchar_join_keys.py).

All four CAN be tripped; every fixture below is a first-call assertion that they
do. Three defects found on the way are recorded as `xfail(strict=True)` rather
than fixed, so the marker fails loudly the day someone corrects them.

TML shapes follow the repo's own schemas, consulted for this file:
  * `agents/shared/schemas/thoughtspot-table-tml.md` — `rls_rules` is a MAPPING
    (`tables` / `table_paths` / `rules`), not a list; bracket refs live in
    `rules[].expr` and use the `table_paths[].id` alias, e.g. the live example
    `ts_groups = [BANK_EMPLOYEES_1::COUNTRY]`. `db_column_properties.data_type`
    is required on every table column.
  * `agents/shared/schemas/thoughtspot-model-tml.md:241` —
    `properties.index_type` is "omit for full indexing (default)"; the value set
    is DONT_INDEX / PREFIX_ONLY / DEFAULT / PREFIX_AND_SUBSTRING /
    PREFIX_AND_WORD_SUBSTRING. Model columns carry no data type.
"""
import pytest

import audit_rule_fixtures as fx
from audit_run_rule import run_rule
from ts_cli.audit.findings import CHECK_META

# Every context below is a named builder in audit_rule_fixtures (rls.py and
# security.py), whose legacy S answers — and P answers, for the P14/P15 clones —
# test_audit_pinned_findings.py pins. The `checks_security.py:N` / `checks_perf.py:N`
# references below are to the legacy modules (deleted when the rule catalog replaced them), which the catalog
# rules reproduce.


# --------------------------------------------------------------------------
# S2 — PII indexed without RLS
# --------------------------------------------------------------------------

def test_s2_trips_on_an_indexed_pii_column_with_no_table_rls():
    """First assertion ever made that S2 can return a Finding."""
    findings = run_rule(fx.sec_pii_indexed_without_rls(), "S2")
    assert len(findings) == 1
    assert findings[0].check_id == "S2"
    assert findings[0].severity == "HIGH"
    assert "WITHOUT table RLS" in findings[0].detail


def test_s2_downgrades_to_info_when_the_owning_table_has_rls():
    findings = run_rule(fx.sec_pii_indexed_with_rls(), "S2")
    assert len(findings) == 1
    assert findings[0].severity == "INFO"
    assert "table has RLS" in findings[0].detail


def test_s2_clean_model_returns_nothing():
    """Indexed, but nothing that reads as PII."""
    assert run_rule(fx.sec_indexed_without_pii(), "S2") == []


def test_s2_should_flag_a_default_indexed_pii_column():
    """A PII column with no `index_type` is indexed by DEFAULT — the risk S2
    exists to report, and the shape it used to skip (BL-299, fixed)."""
    assert len(run_rule(fx.sec_pii_default_indexed(), "S2")) == 1


def test_s2_should_not_flag_a_dont_index_pii_column():
    """`DONT_INDEX` is the mitigation. S2 used to report it as the risk, and it
    is the only value this repo writes (BL-299, fixed)."""
    assert run_rule(fx.sec_pii_not_indexed(), "S2") == []


# NOTE: the S2 alias-blindness characterization test was removed when BL-305
# was fixed — S2 now resolves RLS through model_tables, so an aliased table's
# RLS is found. Covered by tools/ts-cli/tests/test_alias_and_join_names.py.

# --------------------------------------------------------------------------
# S3 — retired 2026-10: it claimed "no CLS" but never read column security
# --------------------------------------------------------------------------

def test_s3_is_retired_and_silent_on_unmasked_pii():
    assert run_rule(fx.sec_pii_unmasked(), "S3") == []


# --------------------------------------------------------------------------
# S8 — retired 2026-10: a text column in an RLS rule is not a security problem.
# P15, the same walk with a value_casing guard, still runs.
# --------------------------------------------------------------------------

def test_s8_is_retired_and_p15_still_reports_an_uncased_varchar_rls_column():
    uncased = fx.sec_rls_uncased_varchar()
    assert run_rule(uncased, "S8") == []
    assert len(run_rule(uncased, "P15")) == 1
    assert run_rule(fx.sec_rls_cased_varchar(), "P15") == []


# --------------------------------------------------------------------------
# S9 — merged into P14 (2026-10): a function in an RLS rule is a performance
# issue, so it is reported once, as P14, not twice (HIGH security + MEDIUM perf)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("expr", fx.S9_TRIP_EXPRS)
def test_p14_reports_a_function_in_the_rls_expression_once(expr):
    ctx = fx.build_sec_rls_expr(expr)
    assert run_rule(ctx, "S9") == []
    [finding] = run_rule(ctx, "P14")
    assert finding.severity == "MEDIUM"
    assert finding.object_type == "table"
    assert finding.object_name == "CUSTOMERS"
    assert expr[:80] in finding.detail


def test_p14_plain_comparison_and_no_rls_return_nothing():
    assert run_rule(fx.sec_rls_uncased_varchar(), "P14") == []
    assert run_rule(fx.sec_table_without_rls(), "P14") == []


# --------------------------------------------------------------------------
# Report titles
# --------------------------------------------------------------------------

# S8 and S9 retired (2026-10); P15 and P14 are their RLS walks that still run.
@pytest.mark.parametrize("cid,word", [("P15", "rls"), ("P14", "rls")])
def test_check_meta_describes_what_the_check_actually_does(cid, word):
    """`desc` is rendered as the finding TITLE (audit/__init__.py:44).

    It used to read "Overly permissive sharing (FULL access to all users)" for S8
    and "Sharing to external groups" for S9, while both checks read table RLS —
    so a delivered report carried a sharing headline over an RLS detail, and
    implied a sharing audit had run. Corrected here; the two sharing checks the
    catalog promised remain unimplemented and are BL-298.
    """
    assert word in CHECK_META[cid]["desc"].lower()
