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
                    {"name": "T1", "fqn": "DB.SCH.T1"},
                    {"name": "T2", "fqn": "DB.SCH.T2"},
                ],
                "joins": [{"name": "j1"}],
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
