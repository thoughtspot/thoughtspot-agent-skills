"""S2 / S3 / S8 / S9 — the four security checks that no test ever called.

2026-09-22 audit finding 6.1: 27 of 51 checks are *imported* by a test and never
invoked. `tests/test_checks_security.py:1-4` imports `check_s2`, `check_s3`,
`check_s8` and `check_s9` and calls none of them, so nothing had ever shown that
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
from ts_cli.audit.checks_perf import check_p14, check_p15
from ts_cli.audit.checks_security import check_s2, check_s3, check_s8, check_s9
from ts_cli.audit.findings import CHECK_META

# Every context below is a named builder in audit_rule_fixtures (rls.py and
# security.py), so the S catalog rules' equivalence test — and the P one, for the
# P14/P15 clones — runs over exactly these inputs.


# --------------------------------------------------------------------------
# S2 — PII indexed without RLS
# --------------------------------------------------------------------------

def test_s2_trips_on_an_indexed_pii_column_with_no_table_rls():
    """First assertion ever made that S2 can return a Finding."""
    findings = check_s2(fx.sec_pii_indexed_without_rls())
    assert len(findings) == 1
    assert findings[0].check_id == "S2"
    assert findings[0].severity == "HIGH"
    assert "WITHOUT table RLS" in findings[0].detail


def test_s2_downgrades_to_info_when_the_owning_table_has_rls():
    findings = check_s2(fx.sec_pii_indexed_with_rls())
    assert len(findings) == 1
    assert findings[0].severity == "INFO"
    assert "table has RLS" in findings[0].detail


def test_s2_clean_model_returns_nothing():
    """Indexed, but nothing that reads as PII."""
    assert check_s2(fx.sec_indexed_without_pii()) == []


def test_s2_should_flag_a_default_indexed_pii_column():
    """A PII column with no `index_type` is indexed by DEFAULT — the risk S2
    exists to report, and the shape it used to skip (BL-299, fixed)."""
    assert len(check_s2(fx.sec_pii_default_indexed())) == 1


def test_s2_should_not_flag_a_dont_index_pii_column():
    """`DONT_INDEX` is the mitigation. S2 used to report it as the risk, and it
    is the only value this repo writes (BL-299, fixed)."""
    assert check_s2(fx.sec_pii_not_indexed()) == []


# NOTE: the S2 alias-blindness characterization test was removed when BL-305
# was fixed — S2 now resolves RLS through model_tables, so an aliased table's
# RLS is found. Covered by tools/ts-cli/tests/test_alias_and_join_names.py.

# --------------------------------------------------------------------------
# S3 — PII without CLS or masking formula
# --------------------------------------------------------------------------

def test_s3_trips_on_pii_with_no_masking_formula():
    findings = check_s3(fx.sec_pii_unmasked())
    assert len(findings) == 1
    assert findings[0].check_id == "S3"
    assert findings[0].severity == "HIGH"
    assert findings[0].object_name == "customer_email"
    # The claim S3 makes. Nothing in check_s3 reads sharing/CLS state — it only
    # greps the model's own formulas — so the "no CLS" half is unverified.
    assert "no CLS or masking formula" in findings[0].detail


def test_s3_clean_model_returns_nothing():
    assert check_s3(fx.sec_non_pii_columns()) == []


def test_s3_masking_formula_suppresses_the_finding():
    assert check_s3(fx.sec_pii_masked()) == []


def test_s3_is_silenced_by_any_formula_that_merely_names_the_column():
    """DOCUMENTS A PRECISION DEFECT — asserts today's behaviour, not a requirement.

    checks_security.py:88-92 joins *all* formula exprs into one string, sets
    `has_masking` if "is_group_member" appears anywhere in it, then skips any PII
    column whose name is a substring of that same blob. Here the masking guards
    Salary and the email is projected raw — S3 still says nothing.
    """
    assert check_s3(fx.sec_mask_elsewhere_raw_projection()) == [], \
        "the email is not masked, yet S3 is silent"


# --------------------------------------------------------------------------
# S8 — VARCHAR RLS column
# --------------------------------------------------------------------------

def test_s8_trips_on_a_varchar_rls_column():
    """Expr shape is the live example from thoughtspot-table-tml.md:129."""
    findings = check_s8(fx.sec_rls_uncased_varchar())
    assert len(findings) == 1
    assert findings[0].check_id == "S8"
    assert findings[0].severity == "MEDIUM"
    assert findings[0].object_name == "COUNTRY"
    assert findings[0].object_guid == "t-1"


def test_s8_reads_the_type_from_the_table_and_needs_no_model_at_all():
    """The reason S8 does NOT share the P6/D2 defect (audit 14.1).

    Those two read `db_column_properties.data_type` off the MODEL, where it
    never exists. S8 iterates `ctx.tables` and reads it off the Table TML, where
    the schema makes it required — so it still fires with no models in context,
    and a lying type on a model column cannot influence it.
    """
    # a model column with no db_column_properties anywhere, beside the Table
    assert len(check_s8(fx.sec_rls_varchar_beside_a_model())) == 1
    assert len(check_s8(fx.sec_rls_uncased_varchar())) == 1  # no models at all


def test_s8_integer_rls_column_returns_nothing():
    assert check_s8(fx.sec_rls_integer_column()) == []


def test_s8_table_without_rls_returns_nothing():
    assert check_s8(fx.sec_table_without_rls()) == []


def test_s8_unresolvable_ref_is_silently_treated_as_not_a_string():
    """DOCUMENTS A GAP — asserts today's behaviour, not a requirement.

    `col_types.get(col_name, "")` (checks_security.py:153) gives "" for a ref
    that resolves to another table via `rls_rules.tables[]`/`table_paths[]`, and
    "" is not in the VARCHAR set, so it passes silently. Unknown is not the same
    as "not a string" — the same hazard test_checks_varchar_join_keys.py:111
    guards for P6/D2.
    """
    assert check_s8(fx.sec_rls_unresolved_ref()) == []


def test_s8_is_p15_minus_the_value_casing_guard():
    """DOCUMENTS A NEAR-CLONE. checks_security.py:140-161 vs checks_perf.py:295-320.

    Identical but for P15's `and not vc`, so on a cased VARCHAR column S8 fires
    and P15 does not, and on an uncased one the estate gets two findings for one
    column.
    """
    ctx = fx.sec_rls_cased_varchar()
    assert len(check_s8(ctx)) == 1
    assert check_p15(ctx) == []

    uncased = fx.sec_rls_uncased_varchar()
    assert len(check_s8(uncased)) == 1 and len(check_p15(uncased)) == 1


# --------------------------------------------------------------------------
# S9 — function in an RLS expression
# --------------------------------------------------------------------------

@pytest.mark.parametrize("expr", fx.S9_TRIP_EXPRS)
def test_s9_trips_on_a_function_in_the_rls_expression(expr):
    findings = check_s9(fx.build_sec_rls_expr(expr))
    assert len(findings) == 1
    assert findings[0].check_id == "S9"
    assert findings[0].severity == "HIGH"
    assert findings[0].object_type == "table"
    assert findings[0].object_name == "CUSTOMERS"
    assert expr[:80] in findings[0].detail


def test_s9_plain_comparison_returns_nothing():
    assert check_s9(fx.sec_rls_uncased_varchar()) == []


def test_s9_table_without_rls_returns_nothing():
    assert check_s9(fx.sec_table_without_rls()) == []


def test_s9_is_a_verbatim_clone_of_p14():
    """DOCUMENTS A CLONE. checks_security.py:164-178 vs checks_perf.py:278-292.

    Same loop, same regex, same trigger — only check_id, severity and wording
    differ. Every such RLS expression is counted twice in the report, once HIGH
    (security) and once MEDIUM (performance).
    """
    ctx = fx.sec_rls_upper_function()
    s9, p14 = check_s9(ctx), check_p14(ctx)
    assert len(s9) == len(p14) == 1
    assert (s9[0].object_name, s9[0].object_guid) == (p14[0].object_name, p14[0].object_guid)


# --------------------------------------------------------------------------
# Report titles
# --------------------------------------------------------------------------

@pytest.mark.parametrize("cid,word", [("S8", "rls"), ("S9", "rls")])
def test_check_meta_describes_what_the_check_actually_does(cid, word):
    """`desc` is rendered as the finding TITLE (audit/__init__.py:44).

    It used to read "Overly permissive sharing (FULL access to all users)" for S8
    and "Sharing to external groups" for S9, while both checks read table RLS —
    so a delivered report carried a sharing headline over an RLS detail, and
    implied a sharing audit had run. Corrected here; the two sharing checks the
    catalog promised remain unimplemented and are BL-298.
    """
    assert word in CHECK_META[cid]["desc"].lower()
