"""PR #506 review, second pass — semi-additive/fill/timespine metrics (A), shared
formula_common helper adoption in the dbt Model builders (B, BL-217), superseded
ts_formula references (C), and bracket-safe formula ids (D).

Fixtures reuse test_dbt_metricflow's manifest builders so the shapes stay the ones
observed live (dbt Cloud 2026.9.1 / dbt Fusion, manifest v12).
"""
import importlib.util
import re
from pathlib import Path

import yaml

from ts_cli.dbt_metricflow import translate_metrics
from tests.test_dbt_metricflow import PATH, _derived, _manifest, _ratio, _simple

REPO_ROOT = Path(__file__).resolve().parents[3]
_ID_REF_RE = re.compile(r"\[(formula_[^\[\]]+)\]")


def _unmapped(report):
    return {u["metric"]: u["reason"] for u in report["unmapped"]}


# ---------------------------------------------------------------------------
# A — non_additive_dimension / fill_nulls_with / join_to_timespine
# ---------------------------------------------------------------------------

class TestSemiAdditiveAndFillSemantics:
    NAD = {"name": "as_of", "window_choice": "max", "window_groupings": []}

    def _legacy(self, measure_extra=None, measure_input_extra=None):
        """Legacy shape: type_params.measure -> semantic model measures[]."""
        measure = {"name": "balance", "agg": "sum", "expr": "BALANCE"}
        measure.update(measure_extra or {})
        mt = {"name": "bal", "type": "simple", "label": None, "filter": None,
              "config": {"enabled": True, "meta": {}},
              "depends_on": {"nodes": ["semantic_model.p.transactions"]},
              "type_params": {"measure": {"name": "balance", "filter": None, "alias": None,
                                          "join_to_timespine": False, "fill_nulls_with": None,
                                          **(measure_input_extra or {})}}}
        man = _manifest([mt])
        man["semantic_models"]["semantic_model.p.transactions"]["measures"] = [measure]
        return man

    def test_v2_non_additive_dimension_is_unmapped(self):
        mt = _simple("bal", "transactions", "sum", "BALANCE")
        mt["type_params"]["metric_aggregation_params"]["non_additive_dimension"] = self.NAD
        r = translate_metrics(_manifest([mt]), PATH)
        assert r["formulas"] == []
        reason = _unmapped(r)["bal"]
        assert "semi-additive" in reason and "as_of" in reason and "max" in reason

    def test_legacy_measure_non_additive_dimension_is_unmapped(self):
        r = translate_metrics(self._legacy({"non_additive_dimension": self.NAD}), PATH)
        assert r["formulas"] == []
        assert "semi-additive" in _unmapped(r)["bal"]
        # control: the same measure without it (join_to_timespine False,
        # fill_nulls_with None) still translates
        r = translate_metrics(self._legacy(), PATH)
        assert [f["expr"] for f in r["formulas"]] == ["sum ( [TRANSACTIONS::BALANCE] )"]

    def test_fill_nulls_with_zero_is_unmapped_in_both_shapes(self):
        mt = _simple("bal", "transactions", "sum", "BALANCE")
        mt["type_params"]["fill_nulls_with"] = 0          # 0 is falsy — must still fire
        r = translate_metrics(_manifest([mt]), PATH)
        assert "fill_nulls_with 0" in _unmapped(r)["bal"]
        mt = _simple("bal", "transactions", "sum", "BALANCE")
        mt["type_params"]["metric_aggregation_params"]["fill_nulls_with"] = 0
        assert "fill_nulls_with" in _unmapped(translate_metrics(_manifest([mt]), PATH))["bal"]
        r = translate_metrics(self._legacy(measure_input_extra={"fill_nulls_with": 0}), PATH)
        assert "fill_nulls_with" in _unmapped(r)["bal"]

    def test_join_to_timespine_is_unmapped_in_both_shapes(self):
        mt = _simple("bal", "transactions", "sum", "BALANCE")
        mt["type_params"]["join_to_timespine"] = True
        assert "join_to_timespine" in _unmapped(translate_metrics(_manifest([mt]), PATH))["bal"]
        r = translate_metrics(self._legacy(measure_input_extra={"join_to_timespine": True}), PATH)
        assert "join_to_timespine" in _unmapped(r)["bal"]

    def test_input_measures_carrying_fill_nulls_are_unmapped(self):
        mt = _simple("bal", "transactions", "sum", "BALANCE")
        mt["type_params"]["input_measures"] = [
            {"name": "bal", "filter": None, "alias": None,
             "join_to_timespine": False, "fill_nulls_with": 0}]
        assert "fill_nulls_with" in _unmapped(translate_metrics(_manifest([mt]), PATH))["bal"]

    def test_ratio_and_derived_over_semi_additive_input_are_reported(self):
        bal = _simple("bal", "transactions", "sum", "BALANCE")
        bal["type_params"]["metric_aggregation_params"]["non_additive_dimension"] = self.NAD
        man = _manifest([bal, _simple("n", "transactions", "count", "ACCOUNT_ID"),
                         _ratio("avg_bal", "transactions", "bal", "n"),
                         _derived("bal_x2", "transactions", "b * 2", [("bal", "b", None)])])
        r = translate_metrics(man, PATH)
        assert [f["name"] for f in r["formulas"]] == ["n"]
        reasons = _unmapped(r)
        assert set(reasons) == {"bal", "avg_bal", "bal_x2"}
        assert "'bal' not translated" in reasons["avg_bal"]
        assert "'bal' not translated" in reasons["bal_x2"]


# ---------------------------------------------------------------------------
# B — shared fix_double_aggregation / resolve_name_collisions (BL-217)
# ---------------------------------------------------------------------------

def _metric_set_manifest(extra_formula_cols=None):
    man = _manifest([
        _simple("total_tips", "transactions", "sum", "TIP_AMOUNT", label="Total Tips"),
        _simple("customers", "transactions", "count_distinct", "CUSTOMER_ID", label="Customers"),
        _simple("median_price", "transactions", "median", "SERVICE_PRICE", label="Median Price"),
        _simple("tipped", "transactions", "sum_boolean", "IS_TIPPED", label="Tipped Count"),
        _simple("revenue", "transactions", "sum", "SERVICE_PRICE", label="Revenue"),
        _ratio("tip_rate", "transactions", "total_tips", "revenue", label="Tip Rate"),
        _derived("net", "transactions", "rev - tips",
                 [("revenue", "rev", None), ("total_tips", "tips", None)], label="Net"),
    ])
    man["nodes"]["model.p.transactions"]["columns"] = extra_formula_cols or {}
    return man


class TestSharedHelpersInManifestBuilder:
    def test_double_aggregation_pass_on_a_representative_metric_set(self):
        """Only the ts_formula wrapping an aggregated metric changes. None of the
        six metric shapes wraps a [formula_…] ref in an aggregate, so their
        exprs are unchanged — and their column aggregation stays SUM, which
        thoughtspot-model-tml.md documents as a no-op on an aggregate expr. A sum
        over a SCALAR formula is a real aggregation and is left alone."""
        from ts_cli.dbt.manifest import build_model_tml_from_manifest
        man = _metric_set_manifest({
            "Tips Again": {"config": {"meta": {
                "ts_formula": "sum ( [formula_Total Tips] )", "ts_column_type": "measure",
                "ts_aggregation": "sum"}}},
            "Margin": {"config": {"meta": {"ts_formula": "[TRANSACTIONS::A] - [TRANSACTIONS::B]",
                                           "ts_column_type": "measure"}}},
            "Total Margin": {"config": {"meta": {"ts_formula": "sum ( [formula_Margin] )",
                                                 "ts_column_type": "measure"}}}})
        tml = build_model_tml_from_manifest(man, {}, PATH, "M")
        exprs = {f["name"]: f["expr"] for f in tml["model"]["formulas"]}
        assert exprs == {
            "Tips Again": "[formula_Total Tips]",                  # was sum ( [formula_Total Tips] )
            "Margin": "[TRANSACTIONS::A] - [TRANSACTIONS::B]",
            "Total Margin": "sum ( [formula_Margin] )",
            "Total Tips": "sum ( [TRANSACTIONS::TIP_AMOUNT] )",
            "Customers": "unique count ( [TRANSACTIONS::CUSTOMER_ID] )",
            "Median Price": "median ( [TRANSACTIONS::SERVICE_PRICE] )",
            "Tipped Count": "sum ( if ( [TRANSACTIONS::IS_TIPPED] ) then 1 else 0 )",
            "Revenue": "sum ( [TRANSACTIONS::SERVICE_PRICE] )",
            "Tip Rate": "[formula_Total Tips] / [formula_Revenue]",
            "Net": "[formula_Revenue] - [formula_Total Tips]",
        }
        assert tml["_double_aggregation_collapsed"] == [
            {"formula": "Tips Again", "from": "sum ( [formula_Total Tips] )",
             "to": "[formula_Total Tips]"}]
        metric_aggs = {c["properties"].get("aggregation") for c in tml["model"]["columns"]
                       if c.get("formula_id") and c["name"] in {
                           "Total Tips", "Customers", "Median Price", "Tipped Count",
                           "Revenue", "Tip Rate", "Net"}}
        assert metric_aggs == {"SUM"}


class TestSharedHelpersInSchemaYmlBuilder:
    def test_ts_formula_wrapping_an_aggregated_sibling_is_collapsed(self):
        from ts_cli.dbt.model_from_schema_yml import build_model_tml_from_schema_yml
        text = yaml.safe_dump({"version": 2, "models": [{"name": "orders", "columns": [
            {"name": "AMOUNT", "config": {"meta": {"ts_column_type": "measure"}}},
            {"name": "Revenue", "config": {"meta": {
                "ts_column_type": "measure", "ts_formula": "sum ( [ORDERS::AMOUNT] )"}}},
            {"name": "Revenue Again", "config": {"meta": {
                "ts_column_type": "measure", "ts_formula": "sum ( [formula_Revenue] )"}}},
        ]}]}, sort_keys=False)
        tml = build_model_tml_from_schema_yml(text, "M")
        exprs = {f["name"]: f["expr"] for f in tml["model"]["formulas"]}
        assert exprs == {"Revenue": "sum ( [ORDERS::AMOUNT] )",
                         "Revenue Again": "[formula_Revenue]"}


class TestConverterParityWithoutDbtExemptions:
    def _load(self):
        path = REPO_ROOT / "tools" / "validate" / "check_converter_parity.py"
        spec = importlib.util.spec_from_file_location("ccp_review2", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_dbt_passes_on_merit_with_no_exemption(self):
        mod = self._load()
        assert not [k for k in mod.EXPECTED_DIVERGENCES if k[0] == "dbt"]
        files, resolved = mod.resolve_code_files(REPO_ROOT, "dbt")
        assert resolved
        failures, notes = mod.check_platform("dbt", files, frozenset())
        assert failures == []
        assert "resolve_name_collisions: adopted" in notes
        assert "fix_double_aggregation: adopted" in notes


# ---------------------------------------------------------------------------
# C — a superseded ts_formula's id is repointed, in any case
# ---------------------------------------------------------------------------

class TestSupersededReferencesRepointed:
    def _tml(self, ref):
        from ts_cli.dbt.manifest import build_model_tml_from_manifest
        man = _manifest([_simple("total_tips", "transactions", "sum", "TIP_AMOUNT",
                                 label="Total Tips")])
        man["nodes"]["model.p.transactions"]["columns"] = {
            "TOTAL TIPS": {"config": {"meta": {
                "ts_formula": "sum ( [TRANSACTIONS::TIP_AMOUNT] )", "ts_column_type": "measure"}}},
            "Tip Share": {"config": {"meta": {
                "ts_formula": f"{ref} / 2", "ts_column_type": "measure"}}},
        }
        return build_model_tml_from_manifest(man, {}, PATH, "M")

    def test_reference_in_superseded_case_is_repointed(self):
        from ts_cli.tml_lint import lint_tml
        tml = self._tml("[formula_TOTAL TIPS]")
        share = next(f for f in tml["model"]["formulas"] if f["name"] == "Tip Share")
        assert share["expr"] == "[formula_Total Tips] / 2"
        assert tml["_metrics_report"]["repointed_refs"][0]["formula"] == "Tip Share"
        assert not [f for f in lint_tml({"model": tml["model"]}) if "I13" in str(f)]

    def test_reference_in_a_third_case_is_repointed(self):
        tml = self._tml("[formula_total tips]")
        share = next(f for f in tml["model"]["formulas"] if f["name"] == "Tip Share")
        assert share["expr"] == "[formula_Total Tips] / 2"


# ---------------------------------------------------------------------------
# D — formula ids never contain a bracket
# ---------------------------------------------------------------------------

class TestBracketSafeFormulaIds:
    def test_brackets_escaped_and_other_names_unchanged(self):
        from ts_cli.dbt.tags import _formula_id
        assert _formula_id("Rev [USD]") == "formula_Rev %5BUSD%5D"
        for name in ("Gross Margin", "Rev/Cust", "Rev-Cust", "売上", "Margin %"):
            assert _formula_id(name) == "formula_" + name

    def test_metric_reference_to_a_bracketed_label_resolves(self):
        man = _manifest([
            _simple("rev", "transactions", "sum", "SERVICE_PRICE", label="Rev [USD]"),
            _simple("n", "transactions", "count", "ACCOUNT_ID", label="Accounts"),
            _ratio("per", "transactions", "rev", "n", label="Rev per Account")])
        r = translate_metrics(man, PATH)
        ids = {f["id"] for f in r["formulas"]}
        ratio = next(f for f in r["formulas"] if f["name"] == "Rev per Account")
        refs = _ID_REF_RE.findall(ratio["expr"])
        assert refs == ["formula_Rev %5BUSD%5D", "formula_Accounts"]
        assert set(refs) <= ids

    def test_escape_collision_is_still_caught(self):
        from ts_cli.dbt.model_from_schema_yml import build_model_tml_from_schema_yml
        from ts_cli.dbt.tags import find_formula_id_collisions
        text = yaml.safe_dump({"version": 2, "models": [{"name": "orders", "columns": [
            {"name": n, "config": {"meta": {"ts_column_type": "measure",
                                            "ts_formula": "sum ( [ORDERS::AMOUNT] )"}}}
            for n in ("Rev ]X", "Rev %5DX")]}]}, sort_keys=False)
        tml = build_model_tml_from_schema_yml(text, "M")
        assert find_formula_id_collisions(tml) == [
            ("formula_Rev %5DX", ["Rev ]X", "Rev %5DX"])]


class TestDoubleAggregationIsNeverSilent:
    """The collapse rewrites a formula, so it must always be reported — including
    with --no-metrics (no metrics report exists) and on the schema.yml path, which
    used to discard the list."""

    _META = {
        "Total Tips": {"ts_formula": "sum ( [TRANSACTIONS::TIP_AMOUNT] )", "ts_column_type": "measure"},
        "Tips Again": {"ts_formula": "sum ( [formula_Total Tips] )", "ts_column_type": "measure"},
    }

    def test_reported_without_metrics(self):
        from ts_cli.dbt_build_export import build_model_tml_from_manifest
        node = {"resource_type": "model", "name": "transactions", "alias": "transactions",
                "original_file_path": "models/m/transactions.sql", "config": {"meta": {}},
                "columns": {k: {"config": {"meta": v}} for k, v in self._META.items()}}
        tml = build_model_tml_from_manifest({"nodes": {"model.p.transactions": node}}, {},
                                            "models/m", "M", metrics=False)
        [d] = tml["_double_aggregation_collapsed"]
        assert d["formula"] == "Tips Again" and d["to"] == "[formula_Total Tips]"

    def test_reported_on_the_schema_yml_path(self):
        import yaml
        from ts_cli.dbt.model_from_schema_yml import build_model_tml_from_schema_yml
        doc = {"version": 2, "models": [{"name": "transactions", "columns": [
            {"name": k, "config": {"meta": v}} for k, v in self._META.items()]}]}
        tml = build_model_tml_from_schema_yml(yaml.safe_dump(doc), "M")
        assert [d["formula"] for d in tml["_double_aggregation_collapsed"]] == ["Tips Again"]
