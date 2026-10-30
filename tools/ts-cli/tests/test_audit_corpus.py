import pytest

from ts_cli.audit.test_fixtures import generate_test_data


def test_generate_test_data_default():
    data = generate_test_data()
    assert "findings" in data
    assert "summary" in data
    assert "corpus" in data
    corpus = data["corpus"]
    assert corpus["cluster_url"] == "https://demo.thoughtspot.cloud"
    assert len(corpus["models"]) == 5
    assert isinstance(corpus["table_reuse"], list)
    assert isinstance(corpus["model_overlaps"], list)
    assert isinstance(corpus["dependents"], dict)


def test_generate_test_data_name_collisions():
    data = generate_test_data(model_count=4, name_collisions=2)
    corpus = data["corpus"]
    names = [m["name"] for m in corpus["models"]]
    assert len(names) != len(set(names)), "Expected duplicate names"


def test_generate_test_data_no_corpus():
    data = generate_test_data(include_corpus=False)
    assert "corpus" not in data


def test_generate_test_data_empty_angles():
    data = generate_test_data(empty_angles=["S"])
    for f in data["findings"]:
        assert f["angle"] != "security"


from ts_cli.audit import build_corpus
from ts_cli.audit.context import make_context


def test_build_corpus_basic():
    models = [
        {
            "guid": "m-1",
            "model": {
                "name": "Test Model",
                "model_tables": [
                    {"name": "T1", "fqn": "DB.SCH.T1", "joins": [{"with": "T2"}]},
                    {"name": "T2", "fqn": "DB.SCH.T2"},
                ],
                "columns": [{"name": "c1"}, {"name": "c2"}],
                "formulas": [{"name": "f1"}],
            },
        }
    ]
    ctx = make_context(
        models=models,
        tables={"DB.SCH.T1": {"guid": "t-1"}, "DB.SCH.T2": {"guid": "t-2"}},
        dependents={"m-1": [{"guid": "a-1", "name": "My Answer", "type": "ANSWER"}]},
        model_guids=["m-1"],
    )
    corpus = build_corpus(ctx, cluster_url="https://test.thoughtspot.cloud",
                          profile_name="test", angles=["A", "D"])
    assert corpus["cluster_url"] == "https://test.thoughtspot.cloud"
    assert corpus["profile_name"] == "test"
    assert len(corpus["models"]) == 1
    m = corpus["models"][0]
    assert m["guid"] == "m-1"
    assert m["name"] == "Test Model"
    assert m["table_count"] == 2
    assert m["join_count"] == 1
    assert m["column_count"] == 2
    assert m["formula_count"] == 1
    assert corpus["angles_run"] == ["A", "D"]
    assert "m-1" in corpus["dependents"]


def test_build_corpus_counts_joins_where_model_tml_keeps_them():
    """Model TML has no Model-level `joins`: each join sits under its `model_tables[]`
    entry. Reading the absent key reported 0 joins and depth 0 for every Model."""
    models = [{
        "guid": "m-2",
        "model": {
            "name": "Chain",
            "model_tables": [
                {"name": "FACT", "fqn": "DB.SCH.FACT",
                 "joins": [{"with": "DIM_A", "on": "[FACT::A_ID] = [DIM_A::ID]"},
                           {"with": "DIM_C", "on": "[FACT::C_ID] = [DIM_C::ID]"}]},
                {"name": "DIM_A", "fqn": "DB.SCH.DIM_A",
                 "joins": [{"with": "DIM_B", "on": "[DIM_A::B_ID] = [DIM_B::ID]"}]},
                {"name": "DIM_B", "fqn": "DB.SCH.DIM_B"},
                {"name": "DIM_C", "fqn": "DB.SCH.DIM_C"},
            ],
        },
    }]
    ctx = make_context(models=models, tables={}, dependents={}, model_guids=["m-2"])
    m = build_corpus(ctx, angles=["D"])["models"][0]
    assert m["join_count"] == 3
    assert m["join_depth"] == 2


def test_ai_analysis_tolerates_null_and_typed_names():
    """A null column name or a YAML-typed one (`name: 2024`) crashed the join."""
    from ts_cli.audit import _build_ai_analysis
    model = {"name": 2024, "model_tables": [{"name": None}, {"name": "SALES"}],
             "columns": [{"name": None, "properties": {"column_type": "MEASURE"}},
                         {"name": 7}, "not-a-column"]}
    out = _build_ai_analysis([], model)
    assert "1 metric." in out["domain"]


@pytest.mark.parametrize("where,value", [
    ("model", None), ("model", 2024), ("table", None), ("table", 2024),
    ("alias", 7), ("column", None), ("column", 7), ("description", 7)])
def test_a_null_or_typed_name_does_not_end_the_run(where, value):
    """End to end — run_audit, then render_report — not one helper: a fix to one
    function moved the crash one function down (PR 2.4 review)."""
    from ts_cli.audit import run_audit
    from ts_cli.audit.report import render_report
    tables = [{"name": "FACT", "fqn": "g-fact",
               "joins": [{"name": "fact_dim", "with": "DIM", "on": "[FACT::D_ID] = [DIM::ID]",
                          "type": "INNER", "cardinality": "MANY_TO_ONE"}]},
              {"name": "DIM", "fqn": "g-sqlview"}]
    columns = [{"name": "Amount", "column_id": "FACT::AMT",
                "properties": {"column_type": "MEASURE"}, "description": "Net amount"}]
    model = {"name": "Sales", "model_tables": tables, "columns": columns}
    if where == "model":
        model["name"] = value
    elif where == "table":
        tables[1]["name"] = value
    elif where == "alias":
        tables[1]["alias"] = value
    elif where == "column":
        columns[0]["name"] = value
    else:
        columns[0]["description"] = value
    # FACT's Table TML present, DIM's absent (a SQL View model table, which the context
    # does not store, or a failed export): the ERD then looks DIM up by name among the
    # Table TMLs it has (PR 2.4 re-review: the crash's next stop, erd.py, ran only then).
    fact_tml = {"guid": "g-fact", "table": {"name": "FACT", "columns": [
        {"name": "AMT", "db_column_properties": {"data_type": "DOUBLE"}}]}}
    ctx = make_context(models=[{"guid": "m-1", "model": model}],
                       tables={"g-fact": fact_tml}, dependents={}, model_guids=["m-1"])
    out = run_audit(None, ["m-1"], ctx=ctx)
    assert "<html" in render_report(out).lower()


def test_readiness_reads_a_typed_description_as_a1_does():
    """A YAML-typed `description: 2024` is present to A1 and A4, so to the readiness
    score too (it read as blank, losing 45 points for data the report calls present)."""
    from ts_cli.audit.engine.code_rules import _nonblank
    from ts_cli.audit.engine.predicates import _blank
    for value in (2024, 3.5, "x", "  ", "", None, [], ["a"]):
        assert _nonblank(value) is (not _blank(value)), value


def _populated_with_two_models():
    """The populated fixture plus a second Model on the same Table, so D12 compares a
    column across two Models."""
    import copy as _copy
    import audit_rule_fixtures as fx
    ctx = fx.registry_populated_context()
    second = _copy.deepcopy(ctx.models[0])
    second["guid"], second["model"]["name"] = "m-2", "Returns"
    ctx.models.append(second)
    ctx.model_guids.append("m-2")
    ctx.dependents = {}  # the fixture's dependent rows carry no guid, which the report needs
    return ctx


def _corrupt(where, bad):
    ctx = _populated_with_two_models()
    table = next(iter(ctx.tables.values()))["table"]
    if where == "model_column":           # table_role, the corpus, D12, the ERD parser
        ctx.models[0]["model"]["columns"][1]["properties"] = bad
    elif where == "table_column_db":      # column types, RLS column refs
        table["columns"][0]["db_column_properties"] = bad
    elif where == "table_column_props":   # RLS column refs (value casing)
        table["columns"][0]["properties"] = bad
    elif where == "model":                # the parent.properties reads
        ctx.models[0]["model"]["properties"] = bad
    return ctx


@pytest.mark.parametrize("bad", [["MEASURE"], [{"column_type": "MEASURE"}]])
@pytest.mark.parametrize("where", ["model_column", "table_column_db",
                                   "table_column_props", "model"])
def test_a_malformed_mapping_does_not_end_the_run(where, bad):
    """BL-406 item 10, end to end over a Model whose tables are in `model_tables`, a
    Table TML under an RLS rule, and two Models sharing a column: every read of a
    malformed mapping reads it as absent (review: the committed malformed inputs reached
    none of these sites)."""
    from ts_cli.audit import run_audit
    from ts_cli.audit.report import render_report
    ctx = _corrupt(where, bad)
    out = run_audit(None, ["m-1", "m-2"], ctx=ctx)
    assert "<html" in render_report(out).lower()
    assert ctx.warnings, "a malformed mapping is named in a warning"


def _wide(ctx):
    tables = ctx.models[0]["model"]["model_tables"]
    tables += [{"name": f"T{i}", "fqn": f"t-x{i}"} for i in range(6)]
    return ctx


@pytest.mark.parametrize("props,fires", [
    ({}, True),                                  # unset: joins every table (live 2026-08-10)
    ({"is_bypass_rls": False}, True),
    ({"join_progressive": False}, True),
    ({"join_progressive": True}, False),
    (["oops"], False),                           # malformed: cannot be read, not judged
    ([{"join_progressive": False}], False),
])
def test_p4_reads_unset_as_off_and_does_not_judge_malformed(props, fires):
    """An unset `join_progressive` joins every table into every query (live-verified
    2026-08-10, ts-object-model-agentql-query patterns.md), so P4 reports it; a malformed
    `properties` cannot be read, so P4 judges nothing (review: reading it as absent made a
    false HIGH, and making unset read as on contradicted the live probe)."""
    from ts_cli.audit import run_audit
    ctx = _wide(_corrupt("model", props))
    out = run_audit(None, ["m-1", "m-2"], ctx=ctx, angles=["P"])
    p4 = [f for f in out["findings"] if f["check_id"] == "P4" and f["object_guid"] == "m-1"]
    assert bool(p4) is fires


def test_a_malformed_model_properties_silences_its_parent_property_rules():
    """S4, S10 and P11 read `parent.properties.*`; on a malformed Model `properties`
    holding a mapping that would fire them all, they read it as absent."""
    from ts_cli.audit import run_audit
    ctx = _corrupt("model", [{"is_bypass_rls": True,
                              "spotter_config": {"is_spotter_enabled": True}}])
    out = run_audit(None, ["m-1", "m-2"], ctx=ctx)
    fired = {f["check_id"] for f in out["findings"] if f["object_guid"] == "m-1"}
    assert not fired & {"S4", "S10", "P11"}


def test_s2_does_not_judge_a_column_whose_properties_cannot_be_read():
    """A PII column whose `properties` is a list (here wrapping DONT_INDEX) has an
    unreadable index setting: S2 must not report it indexed (review finding)."""
    from ts_cli.audit import run_audit
    ctx = _populated_with_two_models()
    ctx.models[0]["model"]["columns"].append(
        {"name": "Email Address", "column_id": "ORDERS::EMAIL",
         "properties": [{"column_type": "ATTRIBUTE", "index_type": "DONT_INDEX"}]})
    out = run_audit(None, ["m-1", "m-2"], ctx=ctx, angles=["S"])
    assert not [f for f in out["findings"]
                if f["check_id"] == "S2" and f["object_name"] == "Email Address"]
    ctx.models[0]["model"]["columns"][-1]["properties"] = {"column_type": "ATTRIBUTE"}
    out = run_audit(None, ["m-1", "m-2"], ctx=ctx, angles=["S"])
    assert [f for f in out["findings"]
            if f["check_id"] == "S2" and f["object_name"] == "Email Address"]
