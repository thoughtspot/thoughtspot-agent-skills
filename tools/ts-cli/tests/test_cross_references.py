"""Unit tests for ts_cli.tml_lint.lint_cross_references — the dangling
cross-reference check for generated Model TML.

Each check gets a clean (resolves) case and a violating case. Pure-function
tests — no ThoughtSpot connection required.
"""
from ts_cli.tml_lint import lint_cross_references


def _clean_model() -> dict:
    """A model referencing exactly the tables/columns the `tables` map provides."""
    return {
        "model": {
            "name": "SALES",
            "model_tables": [
                {
                    "name": "ORDERS",
                    "joins": [
                        {
                            "with": "CUSTOMERS",
                            "on": "[ORDERS::CUSTOMER_ID] = [CUSTOMERS::ID]",
                            "type": "INNER",
                            "cardinality": "MANY_TO_ONE",
                        }
                    ],
                },
                {"name": "CUSTOMERS"},
            ],
            "columns": [
                {"name": "Order Amount", "column_id": "ORDERS::AMOUNT"},
                {"name": "Customer Name", "column_id": "CUSTOMERS::NAME"},
            ],
        }
    }


def _clean_tables() -> dict[str, set[str]]:
    return {
        "ORDERS": {"AMOUNT", "CUSTOMER_ID", "ORDER_ID"},
        "CUSTOMERS": {"ID", "NAME"},
    }


def test_clean_model_has_no_findings():
    assert lint_cross_references(_clean_model(), _clean_tables()) == []


def test_non_dict_model_tml_returns_empty():
    assert lint_cross_references(["not", "a", "dict"], _clean_tables()) == []


def test_table_only_tml_returns_empty():
    # No 'model' key (e.g. a Table TML) — nothing to check here.
    assert lint_cross_references({"table": {"name": "ORDERS"}}, _clean_tables()) == []


def test_dangling_model_table_not_generated():
    data = _clean_model()
    data["model"]["model_tables"].append({"name": "GHOST_TABLE"})
    findings = lint_cross_references(data, _clean_tables())
    assert any(
        f.startswith("XREF:") and "GHOST_TABLE" in f and "was not generated" in f
        for f in findings
    )


def test_column_id_table_prefix_not_a_model_table():
    data = _clean_model()
    data["model"]["columns"].append(
        {"name": "Rogue", "column_id": "NOT_A_TABLE::SOMECOL"}
    )
    findings = lint_cross_references(data, _clean_tables())
    assert any(
        f.startswith("XREF:") and "NOT_A_TABLE" in f and "not a model table" in f
        for f in findings
    )


def test_column_id_column_missing_from_table_is_flagged():
    data = _clean_model()
    data["model"]["columns"].append(
        {"name": "Missing Col", "column_id": "ORDERS::DOES_NOT_EXIST"}
    )
    findings = lint_cross_references(data, _clean_tables())
    assert any(
        f.startswith("XREF:") and "DOES_NOT_EXIST" in f and "ORDERS" in f
        for f in findings
    )


def test_column_id_case_mismatch_resolves_cleanly():
    # ThoughtSpot column names are case-insensitive — a case-differing column_id
    # must still resolve (no finding), for both the table part and the column part.
    data = _clean_model()
    data["model"]["columns"].append(
        {"name": "Lowercase Ref", "column_id": "orders::amount"}
    )
    assert lint_cross_references(data, _clean_tables()) == []


def test_dangling_join_target():
    data = _clean_model()
    data["model"]["model_tables"][0]["joins"].append(
        {
            "with": "NONEXISTENT_DIM",
            "on": "[ORDERS::SOME_FK] = [NONEXISTENT_DIM::ID]",
            "type": "LEFT_OUTER",
            "cardinality": "MANY_TO_ONE",
        }
    )
    findings = lint_cross_references(data, _clean_tables())
    assert any(
        f.startswith("XREF:") and "NONEXISTENT_DIM" in f and "not a model table" in f
        for f in findings
    )
    # The [NONEXISTENT_DIM::ID] bracket ref inside `on:` also fails to resolve, but
    # via the same "not a model table" branch (checked separately below).


def test_dangling_bracket_ref_inside_join_on_clause():
    # The join target itself IS a real model table, but the `on:` clause
    # references a column that doesn't exist on it.
    data = _clean_model()
    data["model"]["model_tables"][0]["joins"].append(
        {
            "with": "CUSTOMERS",
            "on": "[ORDERS::CUSTOMER_ID] = [CUSTOMERS::PHANTOM_COL]",
            "type": "LEFT_OUTER",
            "cardinality": "MANY_TO_ONE",
        }
    )
    findings = lint_cross_references(data, _clean_tables())
    assert any(
        f.startswith("XREF:") and "PHANTOM_COL" in f and "CUSTOMERS" in f
        for f in findings
    )


def test_referencing_join_scenario_a_with_no_on_clause_is_fine():
    # Scenario A joins (with + referencing_join, no `on:`) must not crash and
    # must not produce a spurious bracket-ref finding.
    data = _clean_model()
    data["model"]["model_tables"][0]["joins"] = [
        {"with": "CUSTOMERS", "referencing_join": "ORDERS_to_CUSTOMERS"}
    ]
    assert lint_cross_references(data, _clean_tables()) == []


def test_alias_addressed_table_resolves():
    # Self-join via alias: column_id and `with:` may address the aliased entry.
    data = {
        "model": {
            "name": "SELF_JOIN_MODEL",
            "model_tables": [
                {
                    "name": "EMPLOYEE",
                    "alias": "EMPLOYEE_MGR",
                    "joins": [
                        {
                            "with": "EMPLOYEE_MGR",
                            "on": "[EMPLOYEE::MANAGER_ID] = [EMPLOYEE_MGR::EMP_ID]",
                            "type": "LEFT_OUTER",
                            "cardinality": "MANY_TO_ONE",
                        }
                    ],
                },
            ],
            "columns": [
                {"name": "Manager Name", "column_id": "EMPLOYEE_MGR::NAME"},
            ],
        }
    }
    tables = {"EMPLOYEE": {"MANAGER_ID", "EMP_ID", "NAME"}}
    assert lint_cross_references(data, tables) == []


def test_formula_column_ids_are_not_flagged():
    # A formula_id-backed column has no column_id and must be skipped entirely.
    data = _clean_model()
    data["model"]["columns"].append({"name": "Revenue", "formula_id": "formula_Revenue"})
    data["model"]["formulas"] = [
        {"id": "formula_Revenue", "name": "Revenue", "expr": "sum ( [ORDERS::AMOUNT] )"}
    ]
    assert lint_cross_references(data, _clean_tables()) == []


def test_multiple_violations_accumulate():
    data = _clean_model()
    data["model"]["model_tables"].append({"name": "GHOST"})
    data["model"]["columns"].append({"name": "Bad", "column_id": "ORDERS::NOPE"})
    data["model"]["model_tables"][0]["joins"].append({"with": "ANOTHER_GHOST"})
    findings = lint_cross_references(data, _clean_tables())
    assert len(findings) >= 3
