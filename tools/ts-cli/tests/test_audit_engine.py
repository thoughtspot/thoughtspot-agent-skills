"""Tests for the audit rule engine (ts_cli/audit/engine/).

The engine turns catalog rules (YAML data) into findings. Its output contract is what
the equivalence gate compares against the legacy check functions, so these tests pin
the contract exactly: detail text, metric type, legacy threshold dict (key order and
number types), severity, the object a finding names, and the additive `categories` /
`bands` payload.

Every rule used here is built as catalog YAML and passed through the real validator
first (`_catalog`), so a test cannot exercise a rule the gate would reject.
"""
from __future__ import annotations

import copy

import pytest

import audit_rule_fixtures as fx
from ts_cli.audit.catalog_model import Band, Bands, build_catalog, load_raw
from ts_cli.audit.catalog_validate import validate_catalog
from ts_cli.audit.context import make_context
from ts_cli.audit.engine import bands as bands_mod
from ts_cli.audit.engine import fields, messages, predicates, scopes
from ts_cli.audit.engine.run import run_rules

# ── helpers ─────────────────────────────────────────────────────────────────

_EXAMPLES = {"fires": {"fixture": "f", "profile": "spotter", "severity": "HIGH"},
             "silent": {"fixture": "s", "profile": "spotter"}}


def _rule(rid: str, **body) -> dict:
    rule = {"id": rid, "title": f"Rule {rid}", "categories": ["A"],
            "requires": ["model_tml"], "examples": copy.deepcopy(_EXAMPLES)}
    rule.update(body)
    return rule


def _catalog(*rules: dict):
    """The shipped categories and profiles plus `rules`, validated clean."""
    raw = {k: v for k, v in load_raw().items() if not k.startswith("rules/")}
    raw["rules/test.yaml"] = [copy.deepcopy(r) for r in rules]
    cat = build_catalog(raw)
    assert validate_catalog(cat, raw) == []
    return cat


def _run(ctx, *rules: dict, profile: str = "spotter", categories=("A", "D", "H", "P", "S"),
         layers=None):
    return run_rules(ctx, _catalog(*rules), list(categories), profile, layers=layers)


A6 = _rule(
    "A6",
    scope="model",
    aggregate={
        "mode": "ratio",
        "over": "model.column",
        "where": {"all": [{"field": "properties.column_type", "eq": "MEASURE"},
                          {"not": {"field": "properties.is_hidden", "truthy": True}}]},
        "match": {"field": "properties.ai_context", "nonblank": True},
    },
    bands={"direction": "higher_is_better", "unit": "percent",
           "levels": [{"op": "lt", "value": 40, "severity": "HIGH"},
                      {"op": "lt", "value": 80, "severity": "MEDIUM"}]},
    profiles={"general": {
        "bands": {"direction": "higher_is_better", "unit": "percent",
                  "levels": [{"op": "lt", "value": 80, "severity": "LOW"}]},
        "legacy_threshold": {"green": 80, "assessment": "{profile_label}"},
    }},
    message="{matched}/{total} measures have AI context ({pct:.0f}%) — missing: {unmatched_names}",
    legacy_threshold={"green": 80, "assessment": "{profile_label}", "yellow": 40.0},
)

P8 = _rule(
    "P8", categories=["P"], scope="model",
    aggregate={"mode": "count", "over": "model.column"},
    bands={"direction": "lower_is_better", "unit": "count",
           "levels": [{"op": "gt", "value": 75, "severity": "MEDIUM"}]},
    message="{count} columns — wider GROUP BY, more complex query plans",
    legacy_threshold={"max": 75},
)

# ── modes ───────────────────────────────────────────────────────────────────


def test_each_mode_one_finding_per_item():
    rule = _rule(
        "P9", categories=["P"], scope="model.column",
        aggregate={"mode": "each", "where": {"all": [
            {"field": "properties.column_type", "eq": "ATTRIBUTE"},
            {"field": "@is_indexed", "truthy": True},
            {"field": "name", "regex": "(?i)_id$"}]}},
        severity="MEDIUM",
        message="High-cardinality ID column '{name}' indexed as {obj.properties.column_type}",
    )
    found = _run(fx.model_id_columns(), rule)
    assert [(f.check_id, f.object_type, f.object_name, f.object_guid, f.severity)
            for f in found] == [
        ("P9", "column", "customer_id", fx.MODEL_GUID, "MEDIUM"),
        ("P9", "column", "order_id", fx.MODEL_GUID, "MEDIUM"),
    ]
    assert found[0].detail == "High-cardinality ID column 'customer_id' indexed as ATTRIBUTE"
    assert found[0].metric is None and found[0].threshold is None


def test_each_mode_measure_drives_bands_and_metric():
    rule = _rule(
        "D1", categories=["D"], scope="model",
        aggregate={"mode": "each", "measure": "@join_depth"},
        bands={"direction": "lower_is_better", "unit": "depth",
               "levels": [{"op": "gt", "value": 5, "severity": "HIGH"},
                          {"op": "gt", "value": 0, "severity": "MEDIUM"}]},
        message="Join depth {value}",
    )
    found = _run(fx.model_role_playing_dimension(), rule)
    assert [(f.severity, f.metric, f.detail) for f in found] == [("MEDIUM", 1, "Join depth 1")]
    assert type(found[0].metric) is int


def test_each_mode_severity_mapping():
    rule = _rule(
        "S2", categories=["S"], scope="model.column",
        aggregate={"mode": "each", "where": {"field": "name", "regex": "_id$"}},
        severity={"field": "@is_indexed", "map": {True: "HIGH"}, "default": "INFO"},
        message="{name}",
    )
    found = _run(fx.model_id_columns(), rule)
    assert [(f.object_name, f.severity) for f in found] == [
        ("customer_id", "HIGH"), ("order_id", "HIGH"), ("row_id", "INFO")]


def test_ratio_mode_counts_and_bands():
    assert _run(fx.model_measures_with_ai_context(), A6) == []
    [f] = _run(fx.model_measures_no_ai_context(), A6)
    assert (f.check_id, f.severity, f.object_type, f.object_name, f.object_guid) == (
        "A6", "HIGH", "model", "Sales", fx.MODEL_GUID)
    assert f.detail == ("3/10 measures have AI context (30%) — missing: "
                        "M3, M4, M5, M6, M7 (+2 more)")
    assert f.metric == 30.0 and type(f.metric) is float


def test_ratio_with_empty_population_is_silent():
    for profile in ("spotter", "general"):
        assert _run(fx.model_without_measures(), A6, profile=profile) == []


def test_ratio_unit_ratio_classifies_the_fraction():
    rule = copy.deepcopy(A6)
    rule["bands"] = {"direction": "higher_is_better", "unit": "ratio",
                     "levels": [{"op": "lt", "value": 0.4, "severity": "HIGH"}]}
    rule.pop("profiles")
    [f] = _run(fx.model_measures_no_ai_context(), rule)
    assert f.severity == "HIGH" and f.metric == 30.0


def test_count_mode_lower_is_better():
    [f] = _run(fx.model_76_columns(), P8, profile="general")
    assert (f.severity, f.metric, f.object_name) == ("MEDIUM", 76, "Wide")
    assert type(f.metric) is int
    assert f.detail == "76 columns — wider GROUP BY, more complex query plans"
    assert f.threshold == {"max": 75}
    assert _run(fx.model_75_columns(), P8) == []


def test_count_mode_where_filters_children_and_total_counts_all():
    rule = _rule(
        "P3", categories=["P"], scope="model",
        aggregate={"mode": "count", "over": "model.column",
                   "where": {"field": "properties.column_type", "eq": "MEASURE"}},
        bands={"direction": "lower_is_better", "unit": "count",
               "levels": [{"op": "gt", "value": 0, "severity": "MEDIUM"}]},
        message="{count}/{total} columns are measures",
    )
    [f] = _run(fx.model_measures_no_ai_context(), rule)
    assert f.detail == "11/12 columns are measures" and f.metric == 11


def test_group_duplicates_and_divergence():
    dupes = _rule(
        "D8", categories=["D"], requires=["metadata"], scope="metadata",
        aggregate={"mode": "group", "kind": "duplicates",
                   "key": ["dataSourceName", "name"]},
        bands={"direction": "lower_is_better", "unit": "count",
               "levels": [{"op": "gt", "value": 1, "severity": "HIGH"}]},
        message="{size} ThoughtSpot objects point to the same physical table",
    )
    [f] = _run(fx.metadata_duplicate_tables(), dupes)
    assert (f.object_type, f.object_name, f.object_guid, f.severity, f.metric) == (
        "table", "SF.ORDERS", "t1", "HIGH", 3)
    assert f.detail == "3 ThoughtSpot objects point to the same physical table"

    divergent = _rule(
        "D12", categories=["D"], scope="model.column",
        aggregate={"mode": "group", "kind": "divergence", "key": "name",
                   "value": "properties.column_type", "guid": "none",
                   "member": "parent.name"},
        severity="MEDIUM",
        message="Column '{key}' differs across {members}: {values}",
    )
    [g] = _run(fx.models_divergent_column_types(), divergent)
    assert (g.object_type, g.object_name, g.object_guid, g.metric) == (
        "column", "REGION", "", None)
    assert g.detail == "Column 'REGION' differs across North, South: ATTRIBUTE, MEASURE"


def test_group_name_template():
    rule = _rule(
        "H8", categories=["H"], requires=["metadata"], scope="metadata",
        aggregate={"mode": "group", "kind": "duplicates", "key": "name",
                   "name": "shared by {size}", "guid": "none"},
        severity="HIGH", message="{members:head2}",
    )
    found = _run(fx.metadata_duplicate_tables(), rule)
    assert [(f.object_name, f.object_guid, f.detail, f.metric) for f in found] == [
        ("shared by 4", "", "ORDERS, ORDERS", None)]


def test_pairwise_jaccard():
    rule = _rule(
        "D7", categories=["D"], scope="model",
        aggregate={"mode": "pairwise", "set": "model_tables.fqn"},
        bands={"direction": "lower_is_better", "unit": "ratio",
               "levels": [{"op": "gte", "value": 1.0, "severity": "HIGH"},
                          {"op": "gt", "value": 0.5, "severity": "MEDIUM"}]},
        message="{shared}/{union} tables shared (Jaccard {similarity:.2f})",
    )
    [f] = _run(fx.models_overlapping_tables(), rule)
    assert (f.object_type, f.object_name, f.object_guid, f.severity, f.metric) == (
        "model", "A / B", "g-a", "MEDIUM", 0.75)
    assert f.detail == "3/4 tables shared (Jaccard 0.75)"


def test_composite_weights():
    rule = _rule(
        "A5", scope="model",
        aggregate={"mode": "composite",
                   "components": {"coverage": "properties.coverage",
                                  "coached": "properties.coached"},
                   "weights": {"coverage": 0.6, "coached": 0.4}},
        bands={"direction": "higher_is_better", "unit": "score",
               "levels": [{"op": "lt", "value": 50, "severity": "HIGH"},
                          {"op": "lt", "value": 80, "severity": "MEDIUM"}]},
        message="score {score:.0f}/100 (coverage {coverage:.0f}, coached {coached:.0f})",
    )
    found = _run(fx.models_for_readiness_score(), rule)
    assert [(f.object_name, f.severity, f.metric, f.detail) for f in found] == [
        ("Partial", "MEDIUM", 70.0, "score 70/100 (coverage 50, coached 100)"),
        ("Bare", "HIGH", 12.0, "score 12/100 (coverage 20, coached 0)"),
    ]


# ── profiles and layers ─────────────────────────────────────────────────────

def test_profile_layer_replaces_bands_whole():
    [f] = _run(fx.model_measures_no_ai_context(), A6, profile="general")
    assert f.severity == "LOW"
    assert f.bands["levels"] == [{"op": "lt", "value": 80.0, "severity": "LOW"}]
    assert f.bands["profile"] == "general"
    assert f.bands["provenance"] == {"bands": "profile:general", "severity": "profile:general"}


def test_profile_comes_from_argument_not_context():
    ctx = fx.model_measures_no_ai_context()
    ctx.assessment = "spotter"
    [f] = _run(ctx, A6, profile="general")
    assert f.severity == "LOW"


def test_legacy_threshold_rendered_with_key_order_and_number_types():
    [spot] = _run(fx.model_measures_no_ai_context(), A6, profile="spotter")
    assert list(spot.threshold.items()) == [
        ("green", 80), ("assessment", "Spotter-ready"), ("yellow", 40.0)]
    assert type(spot.threshold["green"]) is int and type(spot.threshold["yellow"]) is float
    [gen] = _run(fx.model_measures_no_ai_context(), A6, profile="general")
    assert list(gen.threshold.items()) == [("green", 80), ("assessment", "General")]


def test_third_layer_override_and_provenance():
    layer = {"A6": {"bands": {"direction": "higher_is_better", "unit": "percent",
                              "levels": [{"op": "lt", "value": 50, "severity": "CRITICAL"}]}}}
    for profile in ("spotter", "general"):
        [f] = _run(fx.model_measures_no_ai_context(), A6, profile=profile, layers=[layer])
        assert f.severity == "CRITICAL"
        assert f.bands["provenance"] == {"bands": "layer:2", "severity": "layer:2"}
    # A layer that does not touch bands leaves their provenance with the profile.
    [g] = _run(fx.model_measures_no_ai_context(), A6, profile="general",
               layers=[{"A6": {"remediation": "x"}}])
    assert g.bands["provenance"] == {"bands": "profile:general", "severity": "profile:general"}


def test_non_overridable_key_in_layer_ignored_and_reported():
    layer = {"A6": {"scope": "model.column", "aggregate": {"mode": "count"},
                    "message": "custom {matched}"}}
    [f] = _run(fx.model_measures_no_ai_context(), A6, layers=[layer])
    assert (f.object_type, f.detail) == ("model", "custom 3")
    assert f.bands["provenance"]["ignored"] == [
        {"layer": "layer:2", "key": "scope"}, {"layer": "layer:2", "key": "aggregate"}]


def test_effective_merges_only_overridable_keys():
    rule = _catalog(A6).rules["A6"]
    layers = [{"source": "profile:general", "overrides": rule.profiles["general"]}]
    merged, prov = bands_mod.effective(rule, layers)
    assert merged.bands.levels == [Band("lt", 80.0, "LOW")]
    assert merged.legacy_threshold == rule.legacy_threshold  # profile-only, not merged
    assert "ignored" not in prov  # legacy_threshold is allowed in a profile layer
    assert rule.bands.levels[0].severity == "HIGH"  # the catalog rule is not mutated


def test_retired_rule_never_runs():
    retired = dict(A6, status="retired")
    assert _run(fx.model_measures_no_ai_context(), retired) == []
    revived = [{"A6": {"status": "active"}}]
    assert _run(fx.model_measures_no_ai_context(), retired, layers=revived) == []
    disabled = [{"A6": {"status": "retired"}}]
    assert _run(fx.model_measures_no_ai_context(), A6, layers=disabled) == []


# ── selection, data availability, finding contract ─────────────────────────

def test_rule_skips_object_when_required_data_absent():
    rule = _rule(
        "A3", requires=["model_tml", "ai_instructions"], scope="model",
        aggregate={"mode": "each", "where": {
            "not": {"field": "model_instructions.data_model_instructions", "nonblank": True}}},
        severity="HIGH", message="No AI/Spotter coaching instructions configured",
    )
    found = _run(fx.models_with_and_without_ai_instructions(), rule)
    assert [f.object_name for f in found] == ["Looked Up"]


def test_scopes_available_applies_requires_for_any_rule():
    """The public helper code rules iterate with: the rule's scope, minus the objects
    whose required data the context lacks — the same filter the modes apply."""
    cat = _catalog(_rule("A3", requires=["model_tml", "ai_instructions"], scope="model",
                         aggregate={"mode": "each"}, severity="HIGH", message="x"),
                   _rule("A4", requires=["model_tml"], scope="model",
                         aggregate={"mode": "each"}, severity="HIGH", message="x"))
    ctx = fx.models_with_and_without_ai_instructions()
    assert [i["name"] for i in scopes.available(ctx, cat.rules["A3"])] == ["Looked Up"]
    assert [i["name"] for i in scopes.available(ctx, cat.rules["A4"])] == [
        "Looked Up", "Not Fetched"]


def test_model_table_scope_keyed_by_alias():
    ctx = fx.model_role_playing_dimension()
    assert [i["name"] for i in scopes.iterate(ctx, "model.table")] == [
        "FACT", "ORDER_DATE", "SHIP_DATE"]
    rule = _rule("D5", categories=["D"], scope="model.table",
                 aggregate={"mode": "each", "where": {"field": "name", "eq": "DIM_DATE"}},
                 severity="LOW", message="{name} plays a role")
    found = _run(ctx, rule)
    assert [(f.object_type, f.object_name, f.object_guid) for f in found] == [
        ("table", "ORDER_DATE", fx.MODEL_GUID), ("table", "SHIP_DATE", fx.MODEL_GUID)]


def test_finding_carries_categories_and_bands():
    rule = dict(P8, categories=["D", "P"])
    [f] = _run(fx.model_76_columns(), rule, profile="general", categories=["P"])
    assert f.angle == "data_modeling"
    assert f.categories == ["D", "P"]
    assert f.bands == {"direction": "lower_is_better", "unit": "count",
                       "levels": [{"op": "gt", "value": 75.0, "severity": "MEDIUM"}],
                       "profile": "general",
                       "provenance": {"bands": "catalog", "severity": "catalog"}}
    d = f.to_dict()
    assert d["categories"] == ["D", "P"] and d["bands"] == f.bands


def test_fixed_severity_finding_bands_payload_has_no_levels():
    rule = _rule("S10", categories=["S"], scope="model", aggregate={"mode": "each"},
                 severity="MEDIUM", message="m")
    [f] = _run(fx.model_75_columns(), rule, profile="general")
    assert f.bands == {"direction": None, "unit": None, "levels": [], "profile": "general",
                       "provenance": {"bands": "catalog", "severity": "catalog"}}


def test_categories_select_rules_by_intersection():
    rule = dict(P8, categories=["D", "P"])
    ctx = fx.model_76_columns()
    assert len(_run(ctx, rule, categories=["P"])) == 1
    assert len(_run(ctx, rule, categories=["D"])) == 1
    assert _run(ctx, rule, categories=["A", "S"]) == []


def test_unknown_profile_or_category_rejected():
    with pytest.raises(ValueError, match="profile"):
        _run(fx.model_76_columns(), P8, profile="strict")
    with pytest.raises(ValueError, match="categor"):
        _run(fx.model_76_columns(), P8, categories=["X"])


# ── scopes ──────────────────────────────────────────────────────────────────

def test_scopes_cover_every_scope_in_the_vocabulary():
    from ts_cli.audit.catalog_validate import SCOPES
    assert set(scopes.ITERATORS) == set(SCOPES)


def test_child_scope_items_report_their_root_guid():
    ctx = make_context(
        models=[{"guid": "gm", "model": {"name": "M", "formulas": [{"name": "F", "expr": "1"}],
                                         "filters": [{"column": ["C"]}]}}],
        tables={"gt": {"guid": "gt", "table": {"name": "T", "rls_rules": {"rules": [
            {"name": "r1", "expr": "[T::REGION] = ts_username"}]},
            "columns": [{"name": "REGION",
                         "db_column_properties": {"data_type": "VARCHAR"}}]}}},
        answers=[{"guid": "ga", "answer": {"name": "Ans", "tables": [{"fqn": "gt"}],
                                           "formulas": [{"name": "AF", "expr": "2"}]}}],
        dependents={"gm": [{"guid": "gs", "name": "Set1", "type": "SET"}], "gs": []},
    )
    seen = {s: [(i["object_type"], i["name"], i["guid"]) for i in scopes.iterate(ctx, s)]
            for s in ("model.formula", "model.filter", "table.rls_rule", "rls_column_ref",
                      "answer.table_ref", "answer.formula", "set")}
    assert seen == {
        "model.formula": [("formula", "F", "gm")],
        "model.filter": [("filter", "C", "gm")],
        "table.rls_rule": [("table", "T", "gt")],
        "rls_column_ref": [("column", "REGION", "gt")],
        "answer.table_ref": [("answer", "Ans", "ga")],
        "answer.formula": [("formula", "AF", "ga")],
        "set": [("set", "Set1", "gs")],
    }
    [ref] = scopes.iterate(ctx, "rls_column_ref")
    assert ref["obj"]["data_type"] == "VARCHAR"


def test_iterate_children_of_one_parent():
    ctx = fx.models_divergent_column_types()
    [north, _south] = scopes.iterate(ctx, "model")
    assert [i["name"] for i in scopes.iterate(ctx, "model.column", parent=north)] == [
        "REGION", "AMOUNT"]
    assert len(list(scopes.iterate(ctx, "model.column"))) == 4


# ── fields ──────────────────────────────────────────────────────────────────

def _item(obj: dict, parent=None) -> dict:
    return {"obj": obj, "parent": parent, "guid": "g", "name": obj.get("name", ""),
            "object_type": "column", "scope": "model.column", "doc": {}}


def test_field_paths():
    item = _item({"name": "C", "properties": {"synonyms": ["a", "b"]},
                  "list": [{"k": 1}, {"k": 2}]},
                 parent=_item({"name": "Model"}))
    ctx = make_context()
    assert fields.get(item, "properties.synonyms", ctx) == ["a", "b"]
    assert fields.get(item, "properties.synonyms.1", ctx) == "b"
    assert fields.get(item, "list.k", ctx) == [1, 2]
    assert fields.get(item, "properties.missing.deeper", ctx) is None
    assert fields.get(item, "parent.name", ctx) == "Model"
    assert fields.get(_item({}), "parent.name", ctx) is None


def test_derived_fields_registry():
    ctx = make_context()
    assert fields.get(_item({"properties": {}}), "@is_indexed", ctx) is True
    assert fields.get(_item({"properties": {"index_type": "DONT_INDEX"}}), "@is_indexed",
                      ctx) is False
    assert fields.get(_item({"properties": {"synonyms": ["x"]}}), "@has_synonyms", ctx) is True
    assert fields.get(_item({"synonyms": ["x"]}), "@has_synonyms", ctx) is True
    assert fields.get(_item({}), "@has_synonyms", ctx) is False
    chain = {"model_tables": [{"name": "A", "joins": [{"with": "B"}]},
                              {"name": "B", "joins": [{"with": "C"}]}]}
    assert fields.get(_item(chain), "@join_depth", ctx) == 2
    with pytest.raises(KeyError, match="@nope"):
        fields.get(_item({}), "@nope", ctx)


def test_register_adds_a_derived_field():
    @fields.register("_test_upper_name")
    def _upper(item, ctx):
        return item["name"].upper()
    try:
        assert fields.get(_item({"name": "abc"}), "@_test_upper_name", make_context()) == "ABC"
    finally:
        del fields.FIELDS["_test_upper_name"]


# ── predicates ──────────────────────────────────────────────────────────────

_OBJ = {"name": "order_id", "n": 5, "flag": True, "none": None, "blank": "  ",
        "tags": ["pii", "key"], "text": "hello world", "empty": []}


@pytest.mark.parametrize("expr,expected", [
    ({"field": "name", "eq": "order_id"}, True),
    ({"field": "none", "eq": None}, True),
    ({"field": "missing", "eq": None}, True),
    ({"field": "n", "eq": 5.0}, True),
    ({"field": "flag", "eq": 1}, False),          # a bool never equals a number
    ({"field": "n", "eq": True}, False),
    ({"field": "name", "in": ["a", "order_id"]}, True),
    ({"field": "flag", "in": [1]}, False),
    ({"field": "name", "regex": "_id$"}, True),
    ({"field": "name", "regex": "^ID"}, False),
    ({"field": "name", "regex": "(?i)^ORDER"}, True),
    ({"field": "n", "regex": "5"}, False),         # regex reads strings only
    ({"field": "name", "regex": "_id$", "not_regex": "^order"}, False),
    ({"field": "name", "not_regex": "^cust"}, True),
    ({"field": "none", "exists": True}, False),
    ({"field": "missing", "exists": False}, True),
    ({"field": "blank", "nonblank": True}, False),
    ({"field": "empty", "nonblank": False}, True),
    ({"field": "n", "nonblank": True}, True),
    ({"field": "flag", "truthy": True}, True),
    ({"field": "none", "truthy": False}, True),
    ({"field": "n", "gt": 4}, True),
    ({"field": "n", "gte": 5, "lt": 6}, True),
    ({"field": "n", "lte": 4}, False),
    ({"field": "flag", "gt": 0}, False),           # a bool is not a number
    ({"field": "name", "gt": 0}, False),
    ({"field": "text", "len_gt": 10}, True),
    ({"field": "tags", "len_lt": 2}, False),
    ({"field": "missing", "len_lt": 1}, True),     # absent has length 0
    ({"field": "text", "contains": "lo wo"}, True),
    ({"field": "tags", "contains": "pii"}, True),
    ({"field": "tags", "contains": "p"}, False),   # list membership, not substring
    ({"field": "n", "contains": "5"}, False),
    ({"all": [{"field": "n", "gt": 1}, {"field": "flag", "truthy": True}]}, True),
    ({"any": [{"field": "n", "gt": 9}, {"field": "flag", "truthy": False}]}, False),
    ({"not": {"field": "n", "gt": 9}}, True),
])
def test_predicate_operators(expr, expected):
    assert predicates.evaluate(expr, _item(_OBJ), make_context()) is expected


def test_predicate_count_over_children():
    ctx = fx.model_measures_no_ai_context()
    [model] = scopes.iterate(ctx, "model")
    has_measures = {"count": "model.column",
                    "where": {"field": "properties.column_type", "eq": "MEASURE"}, "gt": 10}
    assert predicates.evaluate(has_measures, model, ctx) is True
    assert predicates.evaluate(dict(has_measures, gt=11), model, ctx) is False


def test_predicate_unknown_operator_raises():
    with pytest.raises(ValueError, match="frobnicate"):
        predicates.evaluate({"field": "n", "frobnicate": 1}, _item(_OBJ), make_context())


# ── bands and messages ──────────────────────────────────────────────────────

def test_classify_first_matching_level_wins():
    b = Bands("higher_is_better", "percent",
              [Band("lt", 40.0, "HIGH"), Band("lt", 80.0, "MEDIUM")])
    assert [bands_mod.classify(v, b) for v in (10, 39.99, 40, 79.9, 80, 100)] == [
        "HIGH", "HIGH", "MEDIUM", "MEDIUM", None, None]
    lower = Bands("lower_is_better", "count", [Band("gte", 6.0, "HIGH"),
                                               Band("gt", 3.0, "MEDIUM"),
                                               Band("eq", 3.0, "INFO")])
    assert [bands_mod.classify(v, lower) for v in (7, 6, 4, 3, 2)] == [
        "HIGH", "HIGH", "MEDIUM", "INFO", None]


@pytest.mark.parametrize("spec,expected", [
    ("", "a, b, c, d, e (+2 more)"),
    ("head3", "a, b, c"),
    ("head3+", "a, b, c (+4 more)"),
    ("all", "a, b, c, d, e, f, g"),
])
def test_name_list_formatting(spec, expected):
    names = messages.NameList(list("abcdefg"))
    assert format(names, spec) == expected


def test_short_name_list_has_no_suffix():
    assert format(messages.NameList(["a", "b"]), "") == "a, b"


# ── fix round 1 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("expr", [
    {"all": [{"field": "n", "gt": 1}], "not": {"field": "flag", "truthy": True}},
    {"field": "n", "eq": 999, "not": {"field": "flag", "truthy": True}},
    {"count": "model.column"},
    {"count": "model.column", "where": {"field": "name", "exists": True}},
    {"count": "model.column", "field": "n", "gt": 0},
    {"field": "n"},
    {"gt": 1},
    {"field": "n", "gt": 1, "where": {"field": "n", "gt": 0}},
])
def test_mixed_or_incomplete_expression_raises(expr):
    with pytest.raises(ValueError):
        predicates.evaluate(expr, _item(_OBJ), make_context())


def test_derived_field_inside_a_path_raises():
    item = _item({"properties": {}})
    for path in ("properties.@is_indexed", "properties.@no_such_field"):
        with pytest.raises(KeyError, match="whole path"):
            fields.get(item, path, make_context())
    assert fields.get(item, "@is_indexed", make_context()) is True


def test_iterate_with_an_unrelated_parent_raises():
    ctx = make_context(
        models=[{"guid": "gm", "model": {"name": "M", "columns": [{"name": "C"}]}}],
        answers=[{"guid": "ga", "answer": {"name": "A", "formulas": [{"name": "F"}]}}])
    [column] = scopes.iterate(ctx, "model.column")
    [model] = scopes.iterate(ctx, "model")
    with pytest.raises(ValueError, match="do not belong"):
        list(scopes.iterate(ctx, "answer.formula", parent=column))
    with pytest.raises(ValueError, match="do not belong"):
        list(scopes.iterate(ctx, "model", parent=model))
    # A sibling scope resolves through the shared ancestor.
    assert list(scopes.iterate(ctx, "model.formula", parent=column)) == []


def test_each_message_reads_the_object_and_derived_fields():
    rule = _rule("D5", categories=["D"], scope="model.table",
                 aggregate={"mode": "each", "where": {"field": "name", "eq": "DIM_DATE"}},
                 severity="LOW", message="{name} is {obj.name} via {obj.fqn}")
    found = _run(fx.model_role_playing_dimension(), rule)
    assert [f.detail for f in found] == ["ORDER_DATE is DIM_DATE via t-date",
                                         "SHIP_DATE is DIM_DATE via t-date"]
    indexed = _rule("P9", categories=["P"], scope="model.column",
                    aggregate={"mode": "each", "where": {"field": "name", "eq": "row_id"}},
                    severity="LOW", message="{name} indexed={@is_indexed}")
    assert [f.detail for f in _run(fx.model_id_columns(), indexed)] == ["row_id indexed=False"]


def test_unknown_placeholder_raises_instead_of_rendering_none():
    item = _item({"name": "C"})
    with pytest.raises(KeyError, match="nme"):
        messages.render("{nme}", {"name": "C"}, item, make_context())
    with pytest.raises(KeyError, match="properties"):
        messages.render("{properties.x}", {"name": "C"}, item, make_context())


# ── parity: the engine supplies exactly the vocabulary the validator accepts ──

def test_engine_modes_match_validator_modes():
    from ts_cli.audit.catalog_validate import MODES
    from ts_cli.audit.engine.modes import MODES as ENGINE_MODES
    assert set(ENGINE_MODES) == set(MODES)


def test_engine_leaf_operators_match_validator():
    from ts_cli.audit.catalog_validate import LEAF_OPERATORS
    assert set(predicates.LEAF) == set(LEAF_OPERATORS)


def test_engine_availability_covers_every_requirement():
    from ts_cli.audit.catalog_validate import REQUIRES
    assert set(scopes.AVAILABILITY) == set(REQUIRES)


_PARITY_RULES = {
    "each": (_rule("X1", scope="model.column", aggregate={"mode": "each"},
                   severity="LOW", message="m"), fx.model_id_columns),
    "ratio": (A6, fx.model_measures_no_ai_context),
    "count": (P8, fx.model_76_columns),
    "group": (_rule("X2", requires=["metadata"], scope="metadata",
                    aggregate={"mode": "group", "kind": "divergence", "key": "name",
                               "value": "dataSourceName"},
                    severity="LOW", message="m"), fx.metadata_duplicate_tables),
    "pairwise": (_rule("X3", scope="model", aggregate={"mode": "pairwise",
                                                       "set": "model_tables.fqn"},
                       bands={"direction": "lower_is_better", "unit": "ratio",
                              "levels": [{"op": "gt", "value": 0, "severity": "LOW"}]},
                       message="m"), fx.models_overlapping_tables),
    "composite": (_rule("X4", scope="model",
                        aggregate={"mode": "composite",
                                   "components": {"coverage": "properties.coverage"},
                                   "weights": {"coverage": 1}},
                        bands={"direction": "higher_is_better", "unit": "score",
                               "levels": [{"op": "lt", "value": 100, "severity": "LOW"}]},
                        message="m"), fx.models_for_readiness_score),
}


@pytest.mark.parametrize("mode", sorted(_PARITY_RULES))
def test_mode_supplies_exactly_its_declared_placeholders(mode, monkeypatch):
    from ts_cli.audit.catalog_validate import MODE_PLACEHOLDERS
    from ts_cli.audit.engine import modes
    supplied: set = set()
    real = modes.render

    def spy(template, values, *args):
        supplied.update(values)
        return real(template, values, *args)

    monkeypatch.setattr(modes, "render", spy)
    rule, fixture = _PARITY_RULES[mode]
    assert _run(fixture(), rule), "parity rule must fire"
    components = set(rule["aggregate"].get("components", {}))
    item_reads = {"obj"} if mode == "each" else set()
    assert (supplied - components) | item_reads == MODE_PLACEHOLDERS[mode]


def test_null_override_layer_is_ignored_and_reported():
    # Runtime half of the catalog rule "a null override removes nothing".
    [f] = _run(fx.model_measures_no_ai_context(), A6, layers=[{"A6": {"bands": None}}])
    assert f.severity == "HIGH"
    assert f.bands["provenance"]["bands"] == "catalog"
    assert f.bands["provenance"]["ignored"] == [{"layer": "layer:2", "key": "bands"}]


def test_derived_placeholder_with_a_path_raises_at_render():
    item = _item({"properties": {}})
    with pytest.raises(KeyError):
        messages.render("{@is_indexed.x}", {"name": "C"}, item, make_context())
