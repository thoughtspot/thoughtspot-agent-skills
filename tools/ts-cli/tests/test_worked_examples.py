"""
test_worked_examples.py — regression tests verifying the worked examples satisfy
structural validators and internal consistency rules.

These tests do NOT re-run the conversion skills (Claude is in the execution path).
They verify that the documented expected outputs satisfy every invariant enforced
by check_sv_yaml.py and check_tml.py.  If someone edits a worked example in a way
that breaks a structural rule, this test catches it before the change is committed.

All tests are pure static analysis — no live ThoughtSpot or Snowflake connection required.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

# Make tools/validate and tests/ importable without installing them as packages
_TESTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TESTS_DIR.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "tools" / "validate"))
sys.path.insert(0, str(_TESTS_DIR))

from check_sv_yaml import validate_sv_yaml  # noqa: E402
from check_tml import validate_table_tml, validate_model_tml  # noqa: E402
from fixtures import load_ts_to_snowflake_example_1, load_ts_from_snowflake_example  # noqa: E402


# ---------------------------------------------------------------------------
# ts-to-snowflake Example 1 — Retail Sales Worksheet → Semantic View
# ---------------------------------------------------------------------------

class TestTsToSnowflakeExample1:
    """Retail Sales: ThoughtSpot Worksheet TML → Snowflake Semantic View YAML."""

    @pytest.fixture(scope="class")
    def example(self):
        return load_ts_to_snowflake_example_1()

    def test_input_tml_parses(self, example):
        assert example["input_tml"] is not None, \
            "Could not parse the input worksheet TML block from ts-to-snowflake.md"

    def test_output_sv_parses(self, example):
        assert example["output_sv"] is not None, \
            "Could not find the output Semantic View YAML block in ts-to-snowflake.md"

    def test_output_passes_structural_validator(self, example):
        """The worked-example output must satisfy all rules in check_sv_yaml."""
        sv = example["output_sv"]
        if sv is None:
            pytest.skip("No output SV found")
        errors = validate_sv_yaml(sv)
        assert errors == [], (
            "Worked example output has structural errors:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

    def test_sv_has_expected_tables(self, example):
        sv = example["output_sv"]
        if sv is None:
            pytest.skip()
        table_names = {t["name"] for t in sv.get("tables", [])}
        assert "fact_sales" in table_names, "Expected 'fact_sales' table in output SV"
        assert "dim_product" in table_names, "Expected 'dim_product' table in output SV"

    def test_sv_view_name(self, example):
        sv = example["output_sv"]
        if sv is None:
            pytest.skip()
        assert sv.get("name") == "retail_sales"

    def test_sv_has_one_relationship(self, example):
        sv = example["output_sv"]
        if sv is None:
            pytest.skip()
        rels = sv.get("relationships", [])
        assert len(rels) == 1, f"Expected 1 relationship, got {len(rels)}"
        assert rels[0]["left_table"] == "fact_sales"
        assert rels[0]["right_table"] == "dim_product"

    def test_right_table_has_primary_key(self, example):
        sv = example["output_sv"]
        if sv is None:
            pytest.skip()
        right_tables = {r["right_table"] for r in sv.get("relationships", [])}
        for table in sv.get("tables", []):
            if table.get("name") in right_tables:
                assert "primary_key" in table, \
                    f"Table '{table['name']}' is a right_table but has no 'primary_key'"

    def test_no_measures_keyword(self, example):
        """'measures' is a common mistake — correct keyword is 'metrics'."""
        sv = example["output_sv"]
        if sv is None:
            pytest.skip()
        sv_str = yaml.dump(sv)
        assert "measures:" not in sv_str, \
            "Output contains 'measures:' — the correct keyword is 'metrics:'"

    def test_no_data_type_on_metrics(self, example):
        sv = example["output_sv"]
        if sv is None:
            pytest.skip()
        for table in sv.get("tables", []):
            for metric in table.get("metrics", []):
                assert "data_type" not in metric, (
                    f"Metric '{metric.get('name')}' in table '{table.get('name')}' "
                    "has data_type — this causes Cortex Analyst error 392700"
                )

    def test_field_names_globally_unique(self, example):
        sv = example["output_sv"]
        if sv is None:
            pytest.skip()
        all_names: list[str] = []
        for table in sv.get("tables", []):
            for section in ("dimensions", "time_dimensions", "metrics"):
                for field in table.get(section, []):
                    if "name" in field:
                        all_names.append(field["name"])
        duplicates = [n for n in all_names if all_names.count(n) > 1]
        assert not duplicates, (
            f"Duplicate field names found in output SV: {sorted(set(duplicates))}"
        )

    def test_revenue_metric_has_sales_synonym(self, example):
        """Revenue column in the input worksheet has synonyms: [Sales]; this must carry over."""
        sv = example["output_sv"]
        if sv is None:
            pytest.skip()
        all_metrics = [
            m for t in sv.get("tables", []) for m in t.get("metrics", [])
        ]
        revenue = next((m for m in all_metrics if m.get("name") == "revenue"), None)
        assert revenue is not None, "Expected a 'revenue' metric in the output SV"
        synonyms = revenue.get("synonyms", [])
        assert "Sales" in synonyms, \
            f"Revenue metric synonyms {synonyms!r} missing 'Sales' from input worksheet"

    def test_ai_context_prefix_in_description(self, example):
        """ai_context from ThoughtSpot columns must appear with '[TS AI Context]' prefix."""
        sv = example["output_sv"]
        if sv is None:
            pytest.skip()
        all_metrics = [
            m for t in sv.get("tables", []) for m in t.get("metrics", [])
        ]
        revenue = next((m for m in all_metrics if m.get("name") == "revenue"), None)
        if revenue is None:
            pytest.skip("No 'revenue' metric found")
        desc = revenue.get("description", "")
        assert "[TS AI Context]" in desc, (
            f"Revenue metric description {desc!r} missing '[TS AI Context]' prefix. "
            "ThoughtSpot ai_context values must be wrapped with this prefix."
        )


# ---------------------------------------------------------------------------
# ts-from-snowflake — BIRD Superhero Semantic View → ThoughtSpot Model TML
# ---------------------------------------------------------------------------

class TestTsFromSnowflakeExample:
    """BIRD Superhero: Snowflake Semantic View DDL → ThoughtSpot Model TML."""

    @pytest.fixture(scope="class")
    def example(self):
        return load_ts_from_snowflake_example()

    def test_input_ddl_present(self, example):
        assert example["input_ddl"], \
            "Could not find a SQL DDL block in ts-from-snowflake.md"

    def test_input_ddl_is_semantic_view(self, example):
        ddl = example["input_ddl"]
        assert "SEMANTIC VIEW" in ddl.upper(), \
            "Input DDL does not contain 'SEMANTIC VIEW'"

    def test_output_model_parses(self, example):
        assert example["output_model_tml"] is not None, \
            "Could not find a model TML block in ts-from-snowflake.md"

    def test_output_passes_structural_validator(self, example):
        model = example["output_model_tml"]
        if model is None:
            pytest.skip("No model TML found")
        errors = validate_model_tml(model)
        assert errors == [], (
            "Worked example model TML has structural errors:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

    def test_model_has_name(self, example):
        model = example["output_model_tml"]
        if model is None:
            pytest.skip()
        assert model.get("model", {}).get("name"), "model.name is missing"

    def test_every_formula_has_column_entry(self, example):
        """Every formula defined in formulas[] must be surfaced in at least one column."""
        model_data = example["output_model_tml"]
        if model_data is None:
            pytest.skip()
        m = model_data.get("model", {})
        formula_ids = {f["id"] for f in m.get("formulas", []) if "id" in f}
        referenced = {c["formula_id"] for c in m.get("columns", []) if "formula_id" in c}
        unreferenced = formula_ids - referenced
        assert not unreferenced, (
            f"Formulas defined but not surfaced in columns[]: {sorted(unreferenced)}. "
            "Add a columns[] entry with formula_id: for each formula."
        )

    def test_no_aggregation_in_formulas(self, example):
        """aggregation: belongs in columns[], never in formulas[]."""
        model_data = example["output_model_tml"]
        if model_data is None:
            pytest.skip()
        m = model_data.get("model", {})
        for f in m.get("formulas", []):
            assert "aggregation" not in f, (
                f"Formula '{f.get('name', f.get('id'))}' has 'aggregation:' — "
                "this causes ThoughtSpot import errors"
            )

    def test_no_guid_nested_in_model(self, example):
        """guid must be at document root, not inside model:."""
        model_data = example["output_model_tml"]
        if model_data is None:
            pytest.skip()
        assert "guid" not in model_data.get("model", {}), (
            "'guid' is nested inside 'model:' — it must be at the document root"
        )

    def test_columns_have_column_type(self, example):
        """Every column must have properties.column_type."""
        model_data = example["output_model_tml"]
        if model_data is None:
            pytest.skip()
        m = model_data.get("model", {})
        for col in m.get("columns", []):
            props = col.get("properties", {})
            assert props.get("column_type") in ("ATTRIBUTE", "MEASURE"), (
                f"Column '{col.get('name')}' has invalid or missing "
                f"properties.column_type: {props.get('column_type')!r}"
            )
