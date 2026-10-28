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
