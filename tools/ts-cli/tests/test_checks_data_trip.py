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

from ts_cli.audit.checks_data import (
    check_d3, check_d6, check_d8, check_d10, check_d11, check_d12,
)
from ts_cli.audit.context import make_context


# --------------------------------------------------------------------------
# TML-shaped builders. Note what is deliberately absent: joins have no `name`,
# model columns have no `data_type` and no `db_column_name`.
# --------------------------------------------------------------------------

def _col(display, table, col, column_type):
    """A model `columns[]` entry: name + column_id + properties.column_type."""
    return {
        "name": display,
        "column_id": f"{table}::{col}",
        "properties": {"column_type": column_type},
    }


def _fact_columns(table, measures=4, attributes=3):
    """`measures` MEASURE + `attributes` ATTRIBUTE columns on one table.

    `_table_role` calls anything with more than 3 MEASURE columns a fact table.
    """
    cols = [_col(f"{table} M{i}", table, f"M{i}", "MEASURE") for i in range(measures)]
    cols += [_col(f"{table} A{i}", table, f"A{i}", "ATTRIBUTE") for i in range(attributes)]
    return cols


def _inline_join(with_table, on, jtype="INNER", cardinality="MANY_TO_ONE"):
    """Scenario B join — exactly the four keys real inline joins carry."""
    return {"with": with_table, "on": on, "type": jtype, "cardinality": cardinality}


def _model(name="Sales", guid="m-1", model_tables=None, columns=None):
    return {"guid": guid, "model": {
        "name": name,
        "model_tables": model_tables or [],
        "columns": columns or [],
        "formulas": [],
        "properties": {"join_progressive": True},
    }}


def _table_entry(name, fqn, joins=None, alias=None):
    entry = {"name": name, "fqn": fqn}
    if alias:
        entry["alias"] = alias
    if joins:
        entry["joins"] = joins
    return entry


def _search_row(guid, name, subtype="ONE_TO_ONE_LOGICAL", connection="Snowflake Prod",
                db="AGENT_SKILLS", schema="PUBLIC"):
    """A `/metadata/search` row with `include_headers` (what build_context stores)."""
    return {
        "metadata_id": guid,
        "metadata_name": name,
        "metadata_type": "LOGICAL_TABLE",
        "metadata_header": {
            "id": guid,
            "name": name,
            "type": subtype,
            "dataSourceName": connection,
            "databaseStripe": db,
            "schemaStripe": schema,
        },
    }


# --------------------------------------------------------------------------
# D3 — join type analysis. Trips on `joins[].type`.
# --------------------------------------------------------------------------

def _model_with_join_type(jtype):
    return _model(model_tables=[
        _table_entry("ORDERS", "tbl-orders", joins=[_inline_join(
            "CUSTOMER", "[ORDERS::CUST_ID] = [CUSTOMER::ID]", jtype=jtype)]),
        _table_entry("CUSTOMER", "tbl-customer"),
    ])


def test_d3_flags_full_outer_join_as_high():
    """`OUTER` is ThoughtSpot's name for a full outer join (model-tml schema)."""
    findings = check_d3(make_context(models=[_model_with_join_type("OUTER")]))
    assert len(findings) == 1
    assert findings[0].check_id == "D3"
    assert findings[0].severity == "HIGH"
    assert "OUTER" in findings[0].detail


@pytest.mark.parametrize("jtype", ["LEFT_OUTER", "RIGHT_OUTER"])
def test_d3_flags_one_sided_outer_joins_as_info(jtype):
    findings = check_d3(make_context(models=[_model_with_join_type(jtype)]))
    assert len(findings) == 1
    assert findings[0].check_id == "D3"
    assert findings[0].severity == "INFO"
    assert jtype in findings[0].detail


def test_d3_clean_model_returns_nothing():
    """An all-INNER model — the overwhelmingly common real shape — must be silent."""
    assert check_d3(make_context(models=[_model_with_join_type("INNER")])) == []


# --------------------------------------------------------------------------
# D6 — grain consistency. Needs a table that is BOTH a fact (>3 MEASURE
# columns) and >40% ATTRIBUTE columns.
# --------------------------------------------------------------------------

def _grain_ctx(measures, attributes):
    cols = _fact_columns("ORDERS", measures=measures, attributes=attributes)
    return make_context(models=[_model(
        model_tables=[_table_entry("ORDERS", "tbl-orders")], columns=cols)])


def test_d6_flags_fact_table_that_is_mostly_attributes():
    """4 MEASURE + 3 ATTRIBUTE = fact (4 > 3) and 42.9% attributes (> 40%)."""
    findings = check_d6(_grain_ctx(measures=4, attributes=3))
    assert len(findings) == 1
    assert findings[0].check_id == "D6"
    assert findings[0].object_name == "ORDERS"
    assert findings[0].metric == pytest.approx(42.9)


def test_d6_clean_fact_table_returns_nothing():
    """4 MEASURE + 2 ATTRIBUTE = 33% attributes, under the 40% line."""
    assert check_d6(_grain_ctx(measures=4, attributes=2)) == []


def test_d6_ignores_dimension_tables():
    """A dimension (<=3 measures) is allowed to be nearly all attributes."""
    assert check_d6(_grain_ctx(measures=1, attributes=8)) == []


# --------------------------------------------------------------------------
# D8 — duplicate physical-table objects. Trips on ctx.metadata, not on TML.
# --------------------------------------------------------------------------

def test_d8_flags_two_table_objects_on_one_physical_table():
    ctx = make_context(metadata=[
        _search_row("tbl-1", "ORDERS"),
        _search_row("tbl-2", "ORDERS"),
    ])
    findings = check_d8(ctx)
    assert len(findings) == 1
    assert findings[0].check_id == "D8"
    assert findings[0].severity == "HIGH"
    assert findings[0].metric == 2
    assert findings[0].object_name == "Snowflake Prod.AGENT_SKILLS.PUBLIC.ORDERS"
    assert findings[0].object_guid == "tbl-1"


def test_d8_same_name_in_a_different_schema_is_not_a_duplicate():
    ctx = make_context(metadata=[
        _search_row("tbl-1", "ORDERS", schema="PUBLIC"),
        _search_row("tbl-2", "ORDERS", schema="STAGING"),
    ])
    assert check_d8(ctx) == []


def test_d8_ignores_models():
    """Two Models over the same tables are D7's business, not D8's."""
    ctx = make_context(metadata=[
        _search_row("m-1", "Sales", subtype="WORKSHEET"),
        _search_row("m-2", "Sales", subtype="WORKSHEET"),
    ])
    assert check_d8(ctx) == []


# --------------------------------------------------------------------------
# D10 — zero-column tables, split bridge (INFO) vs leaf (MEDIUM).
# --------------------------------------------------------------------------

def _zero_column_ctx():
    """ORDERS has columns and joins to BRIDGE; ORPHAN has neither."""
    return make_context(models=[_model(
        model_tables=[
            _table_entry("ORDERS", "tbl-orders", joins=[_inline_join(
                "BRIDGE", "[ORDERS::CUST_ID] = [BRIDGE::CUST_ID]")]),
            _table_entry("BRIDGE", "tbl-bridge"),
            _table_entry("ORPHAN", "tbl-orphan"),
        ],
        columns=_fact_columns("ORDERS", measures=2, attributes=2))]
    )


def test_d10_flags_zero_column_bridge_and_leaf_tables():
    findings = check_d10(_zero_column_ctx())
    by_name = {f.object_name: f for f in findings}
    assert set(by_name) == {"BRIDGE", "ORPHAN"}
    assert all(f.check_id == "D10" for f in findings)
    assert by_name["BRIDGE"].severity == "INFO"
    assert "bridge" in by_name["BRIDGE"].detail
    assert by_name["ORPHAN"].severity == "MEDIUM"
    assert "leaf" in by_name["ORPHAN"].detail


def test_d10_model_where_every_table_contributes_columns_returns_nothing():
    ctx = make_context(models=[_model(
        model_tables=[
            _table_entry("ORDERS", "tbl-orders", joins=[_inline_join(
                "CUSTOMER", "[ORDERS::CUST_ID] = [CUSTOMER::ID]")]),
            _table_entry("CUSTOMER", "tbl-customer"),
        ],
        columns=(_fact_columns("ORDERS", measures=2, attributes=2)
                 + _fact_columns("CUSTOMER", measures=0, attributes=3)))])
    assert check_d10(ctx) == []


@pytest.mark.xfail(strict=True, reason=(
    "D10 (checks_data.py:301) keys on model_tables[].name, but a table with an "
    "alias prefixes its column_id with the ALIAS (model-tml schema, `alias` row). "
    "AuditContext.column_types (context.py:44) already does `alias or name`; the "
    "check does not, so a fully-populated aliased table is reported zero-column. "
    "D6 (checks_data.py:184) and D11 (via _table_role) are blind the same way — "
    "there they cause a silent miss rather than a false positive."))
def test_d10_aliased_table_is_not_zero_column():
    ctx = make_context(models=[_model(
        model_tables=[
            _table_entry("LOT_DRUGS", "tbl-lot", alias="LOT_DRUGS_1"),
        ],
        columns=[_col("Molecule", "LOT_DRUGS_1", "MOLECULE", "ATTRIBUTE")])])
    assert check_d10(ctx) == []


# --------------------------------------------------------------------------
# D11 — fan-out risk. Trips on cardinality ONE_TO_MANY / MANY_TO_MANY.
# --------------------------------------------------------------------------

def _fanout_ctx(target, target_columns, cardinality="ONE_TO_MANY"):
    return make_context(models=[_model(
        model_tables=[
            _table_entry("ORDERS", "tbl-orders", joins=[_inline_join(
                target, f"[ORDERS::ID] = [{target}::ORDER_ID]",
                jtype="INNER", cardinality=cardinality)]),
            _table_entry(target, "tbl-target"),
        ],
        columns=_fact_columns("ORDERS") + target_columns)])


def test_d11_flags_fact_to_fact_one_to_many_join():
    ctx = _fanout_ctx("SHIPMENTS", _fact_columns("SHIPMENTS"))
    findings = check_d11(ctx)
    assert len(findings) == 1
    assert findings[0].check_id == "D11"
    assert findings[0].severity == "MEDIUM"
    assert "Fan-out risk" in findings[0].detail
    assert "ORDERS" in findings[0].detail and "SHIPMENTS" in findings[0].detail


def test_d11_reports_fact_to_dimension_one_to_many_as_info():
    dim = [_col(f"Cust A{i}", "CUSTOMER", f"A{i}", "ATTRIBUTE") for i in range(4)]
    findings = check_d11(_fanout_ctx("CUSTOMER", dim))
    assert len(findings) == 1
    assert findings[0].severity == "INFO"


def test_d11_many_to_one_join_returns_nothing():
    """MANY_TO_ONE is 223 of 233 real inline joins and cannot fan out."""
    ctx = _fanout_ctx("CUSTOMER", _fact_columns("CUSTOMER"),
                      cardinality="MANY_TO_ONE")
    assert check_d11(ctx) == []


@pytest.mark.xfail(strict=True, reason=(
    "D11's else branch (checks_data.py:340) hardcodes 'ONE_TO_MANY join' into the "
    "detail, so a MANY_TO_MANY join — the worse of the two, and the one the check "
    "explicitly admits at checks_data.py:322 — is reported to the user as "
    "ONE_TO_MANY. The MEDIUM branch interpolates `cardinality` correctly; only the "
    "INFO branch lies."))
def test_d11_many_to_many_detail_names_the_actual_cardinality():
    dim = [_col(f"Cust A{i}", "CUSTOMER", f"A{i}", "ATTRIBUTE") for i in range(4)]
    findings = check_d11(_fanout_ctx("CUSTOMER", dim, cardinality="MANY_TO_MANY"))
    assert len(findings) == 1
    assert "MANY_TO_MANY" in findings[0].detail


# --------------------------------------------------------------------------
# D12 — conformed dimension divergence across models.
# --------------------------------------------------------------------------

def _two_models(type_a, type_b):
    return make_context(models=[
        _model(name="Sales", guid="m-1",
               model_tables=[_table_entry("ORDERS", "tbl-orders")],
               columns=[_col("Discount", "ORDERS", "DISCOUNT", type_a)]),
        _model(name="Returns", guid="m-2",
               model_tables=[_table_entry("RETURNS", "tbl-returns")],
               columns=[_col("Discount", "RETURNS", "DISCOUNT", type_b)]),
    ])


def test_d12_flags_column_classified_differently_across_models():
    findings = check_d12(_two_models("MEASURE", "ATTRIBUTE"))
    assert len(findings) == 1
    assert findings[0].check_id == "D12"
    assert findings[0].severity == "MEDIUM"
    assert findings[0].object_name == "Discount"
    assert "Sales=MEASURE" in findings[0].detail
    assert "Returns=ATTRIBUTE" in findings[0].detail


def test_d12_consistent_classification_returns_nothing():
    assert check_d12(_two_models("MEASURE", "MEASURE")) == []


def test_d12_single_model_returns_nothing():
    ctx = make_context(models=[_model(
        model_tables=[_table_entry("ORDERS", "tbl-orders")],
        columns=[_col("Discount", "ORDERS", "DISCOUNT", "MEASURE")])])
    assert check_d12(ctx) == []
