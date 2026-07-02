"""Unit tests for ts_cli.tableau.build_model — pure helpers behind ts tableau build-model.

These are characterization tests: they pin the behavior of logic extracted
verbatim from build_model_cmd (commands/tableau.py) during the BL-069
follow-up decomposition. If one fails, the extraction changed behavior —
fix the extraction, not the test.
"""
from ts_cli.tableau.build_model import (
    fix_sqlproxy_scoping,
    strip_csq_suffixes,
)


def _model_tml(tables=("SALES",), columns=(), formulas=(), parameters=()):
    return {
        "model": {
            "model_tables": [{"name": t} for t in tables],
            "columns": list(columns),
            "formulas": list(formulas),
            "parameters": list(parameters),
        }
    }


# --- fix_sqlproxy_scoping ---

def test_sqlproxy_scoping_passthrough_when_no_sqlproxy():
    scoped = {"Amount": "SALES"}
    fixed, msg = fix_sqlproxy_scoping(scoped, _model_tml())
    assert fixed == {"Amount": "SALES"}
    assert msg == ""


def test_sqlproxy_scoping_single_table_forces_all_columns():
    scoped = {"Revenue (Custom SQL Query)": "sqlproxy", "Qty": "sqlproxy"}
    tml = _model_tml(
        tables=("SALES",),
        columns=[{"name": "Amount", "column_id": "SALES::AMOUNT"}],
    )
    fixed, msg = fix_sqlproxy_scoping(scoped, tml)
    # every original key forced to the single table
    assert fixed["Revenue (Custom SQL Query)"] == "SALES"
    assert fixed["Qty"] == "SALES"
    # CSQ-suffixed key also gets a base-name alias
    assert fixed["Revenue"] == "SALES"
    # existing model column backfilled
    assert fixed["AMOUNT"] == "SALES"
    assert "Single-table model" in msg


def test_sqlproxy_scoping_multi_table_remaps_via_column_id():
    scoped = {"Amount": "sqlproxy", "Region": "DIM_GEO"}
    tml = _model_tml(
        tables=("SALES", "DIM_GEO"),
        columns=[
            {"name": "Amount", "column_id": "SALES::AMOUNT"},
            {"name": "Region", "column_id": "DIM_GEO::REGION"},
        ],
    )
    fixed, msg = fix_sqlproxy_scoping(scoped, tml)
    assert fixed["Amount"] == "SALES"        # sqlproxy → actual table
    assert fixed["Region"] == "DIM_GEO"      # non-sqlproxy untouched
    assert "Remapped" in msg


def test_sqlproxy_scoping_multi_table_unknown_column_keeps_sqlproxy():
    scoped = {"Mystery": "sqlproxy"}
    tml = _model_tml(
        tables=("SALES", "DIM_GEO"),
        columns=[{"name": "Amount", "column_id": "SALES::AMOUNT"}],
    )
    fixed, _ = fix_sqlproxy_scoping(scoped, tml)
    assert fixed["Mystery"] == "sqlproxy"    # no match — left as-is
    assert fixed["AMOUNT"] == "SALES"        # model columns backfilled


# --- strip_csq_suffixes ---

def test_strip_csq_suffixes_rewrites_in_place_and_counts():
    formulas = [
        {"name": "A", "expr": "[Revenue (Custom SQL Query2)] + [X]"},
        {"name": "B", "expr": "[X] * 2"},
    ]
    changed = strip_csq_suffixes(formulas)
    assert formulas[0]["expr"] == "[Revenue] + [X]"
    assert formulas[1]["expr"] == "[X] * 2"
    assert changed == 1
