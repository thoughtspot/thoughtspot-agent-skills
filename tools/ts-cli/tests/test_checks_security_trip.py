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

from ts_cli.audit.checks_perf import check_p14, check_p15
from ts_cli.audit.checks_security import check_s2, check_s3, check_s8, check_s9
from ts_cli.audit.context import make_context
from ts_cli.audit.findings import CHECK_META

TABLE_FQN = "AGENT_SKILLS.PUBLIC.CUSTOMERS"

# A table column carries its warehouse type; a model column does not.
TABLE_COLS = [
    {"name": "COUNTRY", "db_column_name": "COUNTRY",
     "properties": {"column_type": "ATTRIBUTE"},
     "db_column_properties": {"data_type": "VARCHAR"}},
    {"name": "REGION_ID", "db_column_name": "REGION_ID",
     "properties": {"column_type": "ATTRIBUTE"},
     "db_column_properties": {"data_type": "INT64"}},
]


def _rls(expr, path_column="COUNTRY"):
    """`rls_rules` in the nested mapping form the table schema documents."""
    return {
        "tables": [{"name": "CUSTOMERS"}],
        "table_paths": [{"id": "T_1", "table": "CUSTOMERS", "column": [path_column]}],
        "rules": [{"name": "tenant filter", "expr": expr}],
    }


def _table(rls_rules=None, columns=None, name="CUSTOMERS", guid="t-1"):
    t = {
        "name": name, "db": "AGENT_SKILLS", "schema": "PUBLIC",
        "db_table": "CUSTOMERS", "connection": {"name": "se-snowflake"},
        "columns": TABLE_COLS if columns is None else columns,
    }
    if rls_rules:
        t["rls_rules"] = rls_rules
    return {"guid": guid, "table": t}


def _mcol(name, column_id=None, index_type=None):
    props = {"column_type": "ATTRIBUTE"}
    if index_type:
        props["index_type"] = index_type
    return {"name": name, "column_id": column_id or f"CUSTOMERS::{name}",
            "properties": props}


def _model(columns, formulas=None, alias=None):
    mt = {"name": "CUSTOMERS", "fqn": TABLE_FQN}
    if alias:
        mt["alias"] = alias
    return {"guid": "m-1", "model": {
        "name": "Customer 360", "model_tables": [mt],
        "columns": columns, "formulas": formulas or [],
    }}


# --------------------------------------------------------------------------
# S2 — PII indexed without RLS
# --------------------------------------------------------------------------

def test_s2_trips_on_an_indexed_pii_column_with_no_table_rls():
    """First assertion ever made that S2 can return a Finding."""
    ctx = make_context(
        models=[_model([_mcol("customer_email", index_type="PREFIX_AND_SUBSTRING")])],
        tables={TABLE_FQN: _table()},
    )
    findings = check_s2(ctx)
    assert len(findings) == 1
    assert findings[0].check_id == "S2"
    assert findings[0].severity == "HIGH"
    assert "WITHOUT table RLS" in findings[0].detail


def test_s2_downgrades_to_info_when_the_owning_table_has_rls():
    ctx = make_context(
        models=[_model([_mcol("customer_email", index_type="PREFIX_AND_SUBSTRING")])],
        tables={TABLE_FQN: _table(_rls("ts_groups = [T_1::COUNTRY]"))},
    )
    findings = check_s2(ctx)
    assert len(findings) == 1
    assert findings[0].severity == "INFO"
    assert "table has RLS" in findings[0].detail


def test_s2_clean_model_returns_nothing():
    """Indexed, but nothing that reads as PII."""
    cols = [_mcol("Revenue", index_type="DEFAULT"),
            _mcol("Order Count", index_type="DEFAULT")]
    ctx = make_context(models=[_model(cols)], tables={TABLE_FQN: _table()})
    assert check_s2(ctx) == []


@pytest.mark.xfail(strict=True, reason=(
    "AUDIT FINDING — checks_security.py:67-68 `if not idx: continue` skips the "
    "column that IS fully indexed. thoughtspot-model-tml.md:241: index_type is "
    "'omit for full indexing (default)'. So the default-indexed PII column — the "
    "risk S2 exists to report, and the commonest shape in exported TML — is the "
    "one case S2 never fires on."))
def test_s2_should_flag_a_default_indexed_pii_column():
    ctx = make_context(models=[_model([_mcol("customer_email")])],
                       tables={TABLE_FQN: _table()})
    assert len(check_s2(ctx)) == 1


@pytest.mark.xfail(strict=True, reason=(
    "AUDIT FINDING — the same line, inverted the other way. DONT_INDEX means "
    "text-search indexing is SUPPRESSED, yet it is truthy, so S2 emits HIGH "
    "'PII column is indexed WITHOUT table RLS' about a column that is not "
    "indexed at all."))
def test_s2_should_not_flag_a_dont_index_pii_column():
    ctx = make_context(models=[_model([_mcol("customer_email", index_type="DONT_INDEX")])],
                       tables={TABLE_FQN: _table()})
    assert check_s2(ctx) == []


def test_s2_misses_table_rls_when_the_model_aliases_the_table():
    """DOCUMENTS A SEVERITY DEFECT — asserts today's behaviour, not a requirement.

    S2 keys `table_has_rls` by the Table TML's display name
    (checks_security.py:64) but looks it up by the `column_id` prefix
    (checks_security.py:70), which is the `model_tables` **alias** — see
    `AuditContext.column_types` (context.py:44), `mt.get("alias") or
    mt.get("name")`. A role-playing dimension therefore reports HIGH "WITHOUT
    table RLS" about a table that has RLS.
    """
    ctx = make_context(
        models=[_model([_mcol("customer_email", column_id="SHIP_TO::customer_email",
                              index_type="PREFIX_AND_SUBSTRING")], alias="SHIP_TO")],
        tables={TABLE_FQN: _table(_rls("ts_groups = [T_1::COUNTRY]"))},
    )
    findings = check_s2(ctx)
    assert len(findings) == 1
    assert findings[0].severity == "HIGH", "the table does have RLS — this is wrong"


# --------------------------------------------------------------------------
# S3 — PII without CLS or masking formula
# --------------------------------------------------------------------------

def test_s3_trips_on_pii_with_no_masking_formula():
    ctx = make_context(models=[_model([_mcol("customer_email"), _mcol("Revenue")])],
                       tables={TABLE_FQN: _table()})
    findings = check_s3(ctx)
    assert len(findings) == 1
    assert findings[0].check_id == "S3"
    assert findings[0].severity == "HIGH"
    assert findings[0].object_name == "customer_email"
    # The claim S3 makes. Nothing in check_s3 reads sharing/CLS state — it only
    # greps the model's own formulas — so the "no CLS" half is unverified.
    assert "no CLS or masking formula" in findings[0].detail


def test_s3_clean_model_returns_nothing():
    ctx = make_context(models=[_model([_mcol("Revenue"), _mcol("Order Count")])],
                       tables={TABLE_FQN: _table()})
    assert check_s3(ctx) == []


def test_s3_masking_formula_suppresses_the_finding():
    formulas = [{"id": "f1", "name": "Masked Email",
                 "expr": "if (is_group_member('PII_VIEWERS')) then [customer_email] "
                         "else 'REDACTED'"}]
    ctx = make_context(models=[_model([_mcol("customer_email")], formulas=formulas)],
                       tables={TABLE_FQN: _table()})
    assert check_s3(ctx) == []


def test_s3_is_silenced_by_any_formula_that_merely_names_the_column():
    """DOCUMENTS A PRECISION DEFECT — asserts today's behaviour, not a requirement.

    checks_security.py:88-92 joins *all* formula exprs into one string, sets
    `has_masking` if "is_group_member" appears anywhere in it, then skips any PII
    column whose name is a substring of that same blob. Here the masking guards
    Salary and the email is projected raw — S3 still says nothing.
    """
    formulas = [
        {"id": "f1", "name": "Masked Salary",
         "expr": "if (is_group_member('HR')) then [Salary] else 0"},
        {"id": "f2", "name": "Contact", "expr": "[customer_email]"},
    ]
    ctx = make_context(models=[_model([_mcol("customer_email")], formulas=formulas)],
                       tables={TABLE_FQN: _table()})
    assert check_s3(ctx) == [], "the email is not masked, yet S3 is silent"


# --------------------------------------------------------------------------
# S8 — VARCHAR RLS column
# --------------------------------------------------------------------------

def test_s8_trips_on_a_varchar_rls_column():
    """Expr shape is the live example from thoughtspot-table-tml.md:129."""
    ctx = make_context(tables={TABLE_FQN: _table(_rls("ts_groups = [T_1::COUNTRY]"))})
    findings = check_s8(ctx)
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
    ctx = make_context(
        models=[_model([_mcol("Country")])],   # no db_column_properties anywhere
        tables={TABLE_FQN: _table(_rls("ts_groups = [T_1::COUNTRY]"))},
    )
    assert len(check_s8(ctx)) == 1
    no_models = make_context(tables={TABLE_FQN: _table(_rls("ts_groups = [T_1::COUNTRY]"))})
    assert len(check_s8(no_models)) == 1


def test_s8_integer_rls_column_returns_nothing():
    ctx = make_context(tables={TABLE_FQN: _table(
        _rls("ts_groups_int = [T_1::REGION_ID]", path_column="REGION_ID"))})
    assert check_s8(ctx) == []


def test_s8_table_without_rls_returns_nothing():
    assert check_s8(make_context(tables={TABLE_FQN: _table()})) == []


def test_s8_unresolvable_ref_is_silently_treated_as_not_a_string():
    """DOCUMENTS A GAP — asserts today's behaviour, not a requirement.

    `col_types.get(col_name, "")` (checks_security.py:153) gives "" for a ref
    that resolves to another table via `rls_rules.tables[]`/`table_paths[]`, and
    "" is not in the VARCHAR set, so it passes silently. Unknown is not the same
    as "not a string" — the same hazard test_checks_varchar_join_keys.py:111
    guards for P6/D2.
    """
    ctx = make_context(tables={TABLE_FQN: _table(_rls("ts_groups = [T_2::TENANT_NAME]"))})
    assert check_s8(ctx) == []


def test_s8_is_p15_minus_the_value_casing_guard():
    """DOCUMENTS A NEAR-CLONE. checks_security.py:140-161 vs checks_perf.py:295-320.

    Identical but for P15's `and not vc`, so on a cased VARCHAR column S8 fires
    and P15 does not, and on an uncased one the estate gets two findings for one
    column.
    """
    cased = [{"name": "COUNTRY", "db_column_name": "COUNTRY",
              "properties": {"column_type": "ATTRIBUTE", "value_casing": "UPPER"},
              "db_column_properties": {"data_type": "VARCHAR"}}]
    ctx = make_context(tables={TABLE_FQN: _table(_rls("ts_groups = [T_1::COUNTRY]"),
                                                 columns=cased)})
    assert len(check_s8(ctx)) == 1
    assert check_p15(ctx) == []

    uncased = make_context(tables={TABLE_FQN: _table(_rls("ts_groups = [T_1::COUNTRY]"))})
    assert len(check_s8(uncased)) == 1 and len(check_p15(uncased)) == 1


# --------------------------------------------------------------------------
# S9 — function in an RLS expression
# --------------------------------------------------------------------------

@pytest.mark.parametrize("expr", [
    "UPPER([T_1::COUNTRY]) = ts_groups",
    "trim([T_1::COUNTRY]) = ts_groups",
    "if ([T_1::COUNTRY] = 'AU') then true else false",
    "contains([T_1::COUNTRY], ts_groups)",
])
def test_s9_trips_on_a_function_in_the_rls_expression(expr):
    findings = check_s9(make_context(tables={TABLE_FQN: _table(_rls(expr))}))
    assert len(findings) == 1
    assert findings[0].check_id == "S9"
    assert findings[0].severity == "HIGH"
    assert findings[0].object_type == "table"
    assert findings[0].object_name == "CUSTOMERS"
    assert expr[:80] in findings[0].detail


def test_s9_plain_comparison_returns_nothing():
    ctx = make_context(tables={TABLE_FQN: _table(_rls("ts_groups = [T_1::COUNTRY]"))})
    assert check_s9(ctx) == []


def test_s9_table_without_rls_returns_nothing():
    assert check_s9(make_context(tables={TABLE_FQN: _table()})) == []


def test_s9_is_a_verbatim_clone_of_p14():
    """DOCUMENTS A CLONE. checks_security.py:164-178 vs checks_perf.py:278-292.

    Same loop, same regex, same trigger — only check_id, severity and wording
    differ. Every such RLS expression is counted twice in the report, once HIGH
    (security) and once MEDIUM (performance).
    """
    ctx = make_context(tables={TABLE_FQN: _table(_rls("UPPER([T_1::COUNTRY]) = ts_groups"))})
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
