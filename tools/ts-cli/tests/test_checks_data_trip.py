"""D3 / D6 / D8 / D10 / D11 / D12 — proof that each check can return a finding.

2026-09-22 audit finding 6.1: 27 of 51 checks are *imported* by a test and never
*called* by one, which satisfies a coverage grep and exercises nothing. Two checks
(P6/D2) shipped structurally incapable of returning a finding and went unnoticed for
months — see `test_checks_varchar_join_keys.py`.

These six were in the imported-never-called set (`test_checks_data.py` imports all
twelve D-checks and calls only d1/d4/d5/d7/d9). Every fixture below uses the shapes
real TML actually exports, per:

* `agents/shared/schemas/thoughtspot-model-tml.md` — `model_tables[].joins[]` carries
  `with` + `on` + `type` + `cardinality` (Scenario B) or `with` + `referencing_join`
  (Scenario A) and **no `name` key** in any of the 493 joins of the 2026-07-30
  census; join `type` vocabulary is exactly `INNER | LEFT_OUTER | RIGHT_OUTER | OUTER`
  (`OUTER` *is* full outer — `FULL_OUTER` is rejected); `cardinality` vocabulary is
  `MANY_TO_ONE` / `ONE_TO_MANY` / `ONE_TO_ONE`; `column_id` is `TABLE::COL` using the
  `model_tables[]` entry's **alias when it has one**; model `columns[]` carry
  `name` + `column_id` + `properties.column_type` and **no `data_type` and no
  `db_column_name`**.
* `agents/shared/schemas/thoughtspot-table-tml.md` — `db_column_name` and
  `db_column_properties.data_type` live on the TABLE document, not the model.
* `searchMetadata` REST spec (SpotterCode MCP, 2026-09-23) — a search row is
  `{metadata_id, metadata_name, metadata_type, metadata_header}`; the spec types
  `metadata_header` as a free-form object, so its keys are taken from what this repo
  has observed live (`id`, `name`, `type` = the LOGICAL_TABLE subtype,
  `dataSourceName`).

Each check gets a positive test (a shape that must produce a finding) and a negative
test (a clean shape that must produce none). Two `xfail(strict=True)` tests record
defects found while building the fixtures — they are deliberately NOT fixed here, and
the marker must be deleted, not the assertion, when the check is corrected.
"""
import pytest

import audit_rule_fixtures as fx
from ts_cli.audit.checks_data import (
    check_d3, check_d6, check_d8, check_d10, check_d11, check_d12,
)


# The TML-shaped contexts are named builders in audit_rule_fixtures (data.py), so the
# D catalog rules' equivalence test runs over exactly these inputs. Note what those
# shapes deliberately leave out: joins have no `name`, model columns have no
# `data_type` and no `db_column_name`.


# --------------------------------------------------------------------------
# D3 — join type analysis. Trips on `joins[].type`.
# --------------------------------------------------------------------------

def test_d3_flags_full_outer_join_as_high():
    """`OUTER` is ThoughtSpot's name for a full outer join (model-tml schema)."""
    findings = check_d3(fx.data_join_full_outer())
    assert len(findings) == 1
    assert findings[0].check_id == "D3"
    assert findings[0].severity == "HIGH"
    assert "OUTER" in findings[0].detail


@pytest.mark.parametrize("jtype", ["LEFT_OUTER", "RIGHT_OUTER"])
def test_d3_flags_one_sided_outer_joins_as_info(jtype):
    findings = check_d3(fx.build_join_type_ctx(jtype))
    assert len(findings) == 1
    assert findings[0].check_id == "D3"
    assert findings[0].severity == "INFO"
    assert jtype in findings[0].detail


def test_d3_clean_model_returns_nothing():
    """An all-INNER model — the overwhelmingly common real shape — must be silent."""
    assert check_d3(fx.data_join_inner()) == []


# --------------------------------------------------------------------------
# D6 — grain consistency. Needs a table that is BOTH a fact (>3 MEASURE
# columns) and >40% ATTRIBUTE columns.
# --------------------------------------------------------------------------

def test_d6_flags_fact_table_that_is_mostly_attributes():
    """4 MEASURE + 3 ATTRIBUTE = fact (4 > 3) and 42.9% attributes (> 40%)."""
    findings = check_d6(fx.data_fact_table_mostly_attributes())
    assert len(findings) == 1
    assert findings[0].check_id == "D6"
    assert findings[0].object_name == "ORDERS"
    assert findings[0].metric == pytest.approx(42.9)


def test_d6_clean_fact_table_returns_nothing():
    """4 MEASURE + 2 ATTRIBUTE = 33% attributes, under the 40% line."""
    assert check_d6(fx.data_fact_table_mostly_measures()) == []


def test_d6_ignores_dimension_tables():
    """A dimension (<=3 measures) is allowed to be nearly all attributes."""
    assert check_d6(fx.data_dimension_mostly_attributes()) == []


# --------------------------------------------------------------------------
# D8 — duplicate physical-table objects. Trips on ctx.metadata, not on TML.
# --------------------------------------------------------------------------

def test_d8_flags_two_table_objects_on_one_physical_table():
    findings = check_d8(fx.data_metadata_duplicate_table())
    assert len(findings) == 1
    assert findings[0].check_id == "D8"
    assert findings[0].severity == "HIGH"
    assert findings[0].metric == 2
    assert findings[0].object_name == "Snowflake Prod.AGENT_SKILLS.PUBLIC.ORDERS"
    assert findings[0].object_guid == "tbl-1"


def test_d8_same_name_in_a_different_schema_is_not_a_duplicate():
    assert check_d8(fx.data_metadata_same_name_other_schema()) == []


def test_d8_ignores_models():
    """Two Models over the same tables are D7's business, not D8's."""
    assert check_d8(fx.data_metadata_duplicate_models()) == []


# --------------------------------------------------------------------------
# D10 — zero-column tables, split bridge (INFO) vs leaf (MEDIUM).
# --------------------------------------------------------------------------

def test_d10_flags_zero_column_bridge_and_leaf_tables():
    findings = check_d10(fx.data_model_zero_column_bridge_and_leaf())
    by_name = {f.object_name: f for f in findings}
    assert set(by_name) == {"BRIDGE", "ORPHAN"}
    assert all(f.check_id == "D10" for f in findings)
    assert by_name["BRIDGE"].severity == "INFO"
    assert "bridge" in by_name["BRIDGE"].detail
    assert by_name["ORPHAN"].severity == "MEDIUM"
    assert "leaf" in by_name["ORPHAN"].detail


def test_d10_model_where_every_table_contributes_columns_returns_nothing():
    assert check_d10(fx.data_model_every_table_has_columns()) == []


@pytest.mark.xfail(strict=True, reason=(
    "D10 (checks_data.py:301) keys on model_tables[].name, but a table with an "
    "alias prefixes its column_id with the ALIAS (model-tml schema, `alias` row). "
    "AuditContext.column_types (context.py:44) already does `alias or name`; the "
    "check does not, so a fully-populated aliased table is reported zero-column. "
    "D6 (checks_data.py:184) and D11 (via _table_role) are blind the same way — "
    "there they cause a silent miss rather than a false positive."))
def test_d10_aliased_table_is_not_zero_column():
    assert check_d10(fx.data_model_aliased_table_with_columns()) == []


# --------------------------------------------------------------------------
# D11 — fan-out risk. Trips on cardinality ONE_TO_MANY / MANY_TO_MANY.
# --------------------------------------------------------------------------

def test_d11_flags_fact_to_fact_one_to_many_join():
    findings = check_d11(fx.data_fanout_fact_to_fact())
    assert len(findings) == 1
    assert findings[0].check_id == "D11"
    assert findings[0].severity == "MEDIUM"
    assert "Fan-out risk" in findings[0].detail
    assert "ORDERS" in findings[0].detail and "SHIPMENTS" in findings[0].detail


def test_d11_reports_fact_to_dimension_one_to_many_as_info():
    findings = check_d11(fx.data_fanout_fact_to_dimension())
    assert len(findings) == 1
    assert findings[0].severity == "INFO"


def test_d11_many_to_one_join_returns_nothing():
    """MANY_TO_ONE is 223 of 233 real inline joins and cannot fan out."""
    assert check_d11(fx.data_fanout_many_to_one()) == []


@pytest.mark.xfail(strict=True, reason=(
    "D11's else branch (checks_data.py:340) hardcodes 'ONE_TO_MANY join' into the "
    "detail, so a MANY_TO_MANY join — the worse of the two, and the one the check "
    "explicitly admits at checks_data.py:322 — is reported to the user as "
    "ONE_TO_MANY. The MEDIUM branch interpolates `cardinality` correctly; only the "
    "INFO branch lies."))
def test_d11_many_to_many_detail_names_the_actual_cardinality():
    findings = check_d11(fx.data_fanout_many_to_many_dimension())
    assert len(findings) == 1
    assert "MANY_TO_MANY" in findings[0].detail


# --------------------------------------------------------------------------
# D12 — conformed dimension divergence across models.
# --------------------------------------------------------------------------

def test_d12_flags_column_classified_differently_across_models():
    findings = check_d12(fx.data_models_divergent_column_type())
    assert len(findings) == 1
    assert findings[0].check_id == "D12"
    assert findings[0].severity == "MEDIUM"
    assert findings[0].object_name == "Discount"
    assert "Sales=MEASURE" in findings[0].detail
    assert "Returns=ATTRIBUTE" in findings[0].detail


def test_d12_consistent_classification_returns_nothing():
    assert check_d12(fx.data_models_consistent_column_type()) == []


def test_d12_single_model_returns_nothing():
    assert check_d12(fx.data_model_single_discount()) == []
