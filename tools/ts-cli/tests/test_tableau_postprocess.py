"""Unit tests for ts tableau postprocess (T4) — regression tests for TML fix-up."""
import os
import tempfile
from pathlib import Path

import yaml

from ts_cli.commands.tableau_postprocess import (
    apply_name_mapping_to_all_models,
    fix_formula_column_refs,
    normalize_db_identifiers,
    run_postprocess,
    save_name_mapping,
)


# ── sql_query preservation ─────────────────────────────────────────────────

SQL_VIEW_TML = {
    "guid": "abc-123",
    "sql_view": {
        "name": "Custom SQL View",
        "sql_query": (
            'SELECT\n'
            '    SALES_PERSON AS "Sales Person",\n'
            '    COUNTRY AS "Country",\n'
            '    AMOUNT AS "Amount"\n'
            'FROM FRANCOIS.CHOCOLATE_SALES.CHOCOLATE_SALES_2\n'
            "WHERE EXTRACT(MONTH FROM DATE) = 4"
        ),
        "connection": {"name": "KS_Data"},
        "columns": [
            {"name": "Sales Person", "db_column_name": "Sales Person"},
            {"name": "Country", "db_column_name": "Country"},
            {"name": "Amount", "db_column_name": "Amount"},
        ],
    },
}

MINIMAL_TWB = """<?xml version='1.0' encoding='utf-8' ?>
<workbook>
  <datasources>
    <datasource name='federated.test'>
      <connection class='snowflake'>
        <relation type='text'>SELECT 1</relation>
      </connection>
    </datasource>
  </datasources>
</workbook>
"""


def test_postprocess_does_not_modify_sql_query():
    """Regression: sql_query must survive postprocessing unchanged."""
    original_sql = SQL_VIEW_TML["sql_view"]["sql_query"]

    with tempfile.TemporaryDirectory() as tmpdir:
        sv_path = Path(tmpdir) / "Custom SQL View.sql_view.tml"
        sv_path.write_text(
            yaml.dump(SQL_VIEW_TML, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )

        twb_path = Path(tmpdir) / "test.twb"
        twb_path.write_text(MINIMAL_TWB, encoding="utf-8")

        run_postprocess(tmpdir, str(twb_path))

        result = yaml.safe_load(sv_path.read_text(encoding="utf-8"))
        assert result["sql_view"]["sql_query"] == original_sql, (
            "sql_query was modified by postprocessor — "
            "sanitize_sql_quoted_identifiers should not run on SQL View TMLs"
        )


def test_postprocess_preserves_double_quoted_aliases_in_sql():
    """Double-quoted column aliases in sql_query must not be rewritten."""
    tml = {
        "sql_view": {
            "name": "Quoted Alias View",
            "sql_query": 'SELECT COL_A AS "My Column", COL_B AS "Other" FROM T',
            "connection": {"name": "Conn"},
            "columns": [
                {"name": "My Column", "db_column_name": "My Column"},
                {"name": "Other", "db_column_name": "Other"},
            ],
        },
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        sv_path = Path(tmpdir) / "Quoted Alias View.sql_view.tml"
        sv_path.write_text(
            yaml.dump(tml, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )

        twb_path = Path(tmpdir) / "test.twb"
        twb_path.write_text(MINIMAL_TWB, encoding="utf-8")

        run_postprocess(tmpdir, str(twb_path))

        result = yaml.safe_load(sv_path.read_text(encoding="utf-8"))
        assert result["sql_view"]["sql_query"] == tml["sql_view"]["sql_query"]


# ── db identifier normalization ────────────────────────────────────────────

def test_normalize_db_identifiers_converts_to_upper_snake():
    """db_table and db_column_name values are converted to UPPER_SNAKE_CASE."""
    tml = {
        "table": {
            "name": "Chocolate Sales 2",
            "db": "FRANCOIS",
            "schema": "CHOCOLATE_SALES",
            "db_table": "Chocolate Sales 2",
            "connection": {"name": "KS_Data"},
            "columns": [
                {"name": "Sales Person", "db_column_name": "Sales Person"},
                {"name": "Boxes Shipped", "db_column_name": "Boxes Shipped"},
                {"name": "Amount", "db_column_name": "Amount"},
            ],
        },
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        tbl_path = Path(tmpdir) / "Chocolate Sales 2.table.tml"
        tbl_path.write_text(
            yaml.dump(tml, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )

        changed = normalize_db_identifiers(tbl_path)
        assert changed is True

        result = yaml.safe_load(tbl_path.read_text(encoding="utf-8"))
        assert result["table"]["db_table"] == "CHOCOLATE_SALES_2"
        assert result["table"]["columns"][0]["db_column_name"] == "SALES_PERSON"
        assert result["table"]["columns"][1]["db_column_name"] == "BOXES_SHIPPED"


def test_normalize_db_identifiers_noop_when_already_uppercase():
    """No change when db identifiers are already UPPER_SNAKE_CASE."""
    tml = {
        "table": {
            "name": "Sales",
            "db_table": "SALES",
            "connection": {"name": "Conn"},
            "columns": [
                {"name": "Amount", "db_column_name": "AMOUNT"},
            ],
        },
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        tbl_path = Path(tmpdir) / "Sales.table.tml"
        tbl_path.write_text(
            yaml.dump(tml, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )

        changed = normalize_db_identifiers(tbl_path)
        assert changed is False


def test_normalize_db_identifiers_skips_sql_view():
    """sql_view TMLs have no db_table — function should return False."""
    tml = {
        "sql_view": {
            "name": "My View",
            "sql_query": "SELECT 1",
            "connection": {"name": "Conn"},
        },
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        sv_path = Path(tmpdir) / "My View.sql_view.tml"
        sv_path.write_text(
            yaml.dump(tml, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )

        changed = normalize_db_identifiers(sv_path)
        assert changed is False


# ── fix_formula_column_refs ───────────────────────────────────────────────

def _make_model_tml(formulas, columns):
    """Helper: build a minimal model TML dict with given formulas and columns."""
    return {
        "model": {
            "name": "Test Model",
            "columns": columns,
            "formulas": formulas,
            "model_tables": [],
        },
    }


def _write_and_fix(tmpdir, tml):
    """Write model TML to disk, run fix_formula_column_refs, return formulas."""
    p = Path(tmpdir) / "Test Model.model.tml"
    p.write_text(
        yaml.dump(tml, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )
    fix_formula_column_refs(p)
    result = yaml.safe_load(p.read_text(encoding="utf-8"))
    return {f["id"]: f["expr"] for f in result["model"]["formulas"]}


# Shared column definitions: Sales Person + Amount are ambiguous (in 2 tables),
# Commission Rate is unique to DIM.
MULTI_TABLE_COLUMNS = [
    {"column_id": "Fact::Sales Person", "name": "Sales Person"},
    {"column_id": "Fact::Amount", "name": "Amount"},
    {"column_id": "Fact::Boxes Shipped", "name": "Boxes Shipped"},
    {"column_id": "SQL View::Sales Person", "name": "Sales Person (SV)"},
    {"column_id": "SQL View::Amount", "name": "Amount (SV)"},
    {"column_id": "SQL View::Boxes Shipped", "name": "Boxes Shipped (SV)"},
    {"column_id": "DIM::Sales Person", "name": "Sales Person (DIM)"},
    {"column_id": "DIM::Commission Rate", "name": "Commission Rate"},
]


def test_formula_col_ref_always_preserved():
    """fix_formula_column_refs is a no-op — TABLE::COL qualifications are never stripped."""
    tml = _make_model_tml(
        formulas=[
            {"id": "f1", "name": "F1", "expr": "sum ( [Fact::Boxes Shipped] )"},
            {"id": "f2", "name": "F2", "expr": "[Fact::Commission Rate]"},
        ],
        columns=MULTI_TABLE_COLUMNS,
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _write_and_fix(tmpdir, tml)
    assert result["f1"] == "sum ( [Fact::Boxes Shipped] )"
    assert result["f2"] == "[Fact::Commission Rate]"


def test_formula_col_ref_skips_non_model():
    """fix_formula_column_refs returns False for non-model TMLs."""
    tml = {"table": {"name": "T", "columns": []}}
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "T.table.tml"
        p.write_text(
            yaml.dump(tml, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )
        changed = fix_formula_column_refs(p)
    assert changed is False


# ── apply_name_mapping (physical vs formula collision) ───────────────────

def test_name_mapping_does_not_rewrite_physical_column_ref():
    """Regression: [district] (physical col) must not become [formula_District].

    When a physical column and a calc field differ only by case (e.g.
    'district' vs 'District'), the case-insensitive name-mapping pass must
    skip the physical column reference instead of rewriting it to a formula
    reference.
    """
    tml = {
        "model": {
            "name": "Test Model",
            "columns": [
                {"column_id": "T::district", "name": "district"},
                {"formula_id": "formula_District", "name": "District"},
            ],
            "formulas": [
                {"id": "formula_District", "name": "District",
                 "expr": "'District'"},
                {"id": "formula_Sales_adj", "name": "Sales_adj",
                 "expr": "if ([district] in { 'APAC' }) then 0 else [sales]"},
            ],
            "model_tables": [],
        },
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        mdl_path = Path(tmpdir) / "Test Model.model.tml"
        mdl_path.write_text(
            yaml.dump(tml, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )

        save_name_mapping(tmpdir, {
            "formulas": {"District": "District"},
            "columns": {},
            "parameters": {},
        })

        apply_name_mapping_to_all_models(tmpdir)

        result = yaml.safe_load(mdl_path.read_text(encoding="utf-8"))
        formulas = {f["id"]: f["expr"] for f in result["model"]["formulas"]}

        assert "[district]" in formulas["formula_Sales_adj"], (
            f"Physical column ref [district] was wrongly rewritten: "
            f"{formulas['formula_Sales_adj']}"
        )
        assert "[formula_District]" not in formulas["formula_Sales_adj"]


def test_name_mapping_sanitizes_formula_id_spaces():
    """Regression: formula IDs must use underscores, never spaces.

    When a TWB calc field has spaces in its name (e.g. 'Gross Sales'), the
    name-mapping pass must produce formula_Gross_Sales (sanitized), not
    formula_Gross Sales (with a space).
    """
    tml = {
        "model": {
            "name": "Test Model",
            "columns": [
                {"formula_id": "formula_Gross_Sales", "name": "Gross Sales"},
                {"formula_id": "formula_Net_Sales", "name": "Net Sales"},
            ],
            "formulas": [
                {"id": "formula_Gross_Sales", "name": "Gross Sales",
                 "expr": "sum ( [T::amount] )"},
                {"id": "formula_Net_Sales", "name": "Net Sales",
                 "expr": "[formula_Gross_Sales] - [formula_Returns]"},
            ],
            "model_tables": [],
        },
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        mdl_path = Path(tmpdir) / "Test Model.model.tml"
        mdl_path.write_text(
            yaml.dump(tml, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )

        save_name_mapping(tmpdir, {
            "formulas": {"Gross Sales": "Gross Sales", "Net Sales": "Net Sales"},
            "columns": {},
            "parameters": {},
        })

        apply_name_mapping_to_all_models(tmpdir)

        result = yaml.safe_load(mdl_path.read_text(encoding="utf-8"))
        formulas = {f["id"]: f["expr"] for f in result["model"]["formulas"]}

        assert "formula_Gross_Sales" in formulas, (
            f"formula_Gross_Sales ID missing — got IDs: {list(formulas.keys())}"
        )
        assert "formula_Gross Sales" not in formulas, (
            "formula ID contains spaces — sanitization failed"
        )
        assert "[formula_Gross_Sales]" in formulas["formula_Net_Sales"] or \
               "[formula_Returns]" in formulas["formula_Net_Sales"], (
            f"Cross-ref broken: {formulas['formula_Net_Sales']}"
        )


def test_name_mapping_does_not_rewrite_parameter_ref():
    """Regression: [Metric] (parameter) must not become [formula_Metric].

    When a calc field and a parameter share the same name (e.g. 'Metric'),
    the name-mapping pass must preserve bare [Metric] references that point
    to the parameter, not rewrite them as formula cross-refs.
    """
    tml = {
        "model": {
            "name": "Test Model",
            "columns": [
                {"column_id": "T::Revenue", "name": "Revenue"},
                {"formula_id": "formula_Metric", "name": "Metric"},
                {"formula_id": "formula_Metric_Value", "name": "Metric Value"},
            ],
            "formulas": [
                {"id": "formula_Metric", "name": "Metric",
                 "expr": "[Metric]"},
                {"id": "formula_Metric_Value", "name": "Metric Value",
                 "expr": "if ( [Metric] = 'Revenue' ) then sum ( [T::Revenue] ) else 0"},
            ],
            "model_tables": [],
            "parameters": [
                {"name": "Metric", "data_type": "CHAR",
                 "default_value": "Revenue",
                 "list_config": {"list_choice": [{"value": "Revenue"}, {"value": "Qty"}]}},
            ],
        },
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        mdl_path = Path(tmpdir) / "Test Model.model.tml"
        mdl_path.write_text(
            yaml.dump(tml, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )

        save_name_mapping(tmpdir, {
            "formulas": {"Metric": "Metric", "Metric Value": "Metric Value"},
            "columns": {},
            "parameters": {"Metric": "Metric"},
        })

        apply_name_mapping_to_all_models(tmpdir)

        result = yaml.safe_load(mdl_path.read_text(encoding="utf-8"))
        formulas = {f["id"]: f["expr"] for f in result["model"]["formulas"]}

        assert "[Metric]" in formulas["formula_Metric_Value"], (
            f"Parameter ref [Metric] was wrongly rewritten: "
            f"{formulas['formula_Metric_Value']}"
        )
        assert "[formula_Metric]" not in formulas["formula_Metric_Value"], (
            f"Parameter ref became formula ref: {formulas['formula_Metric_Value']}"
        )
