import json
from unittest.mock import MagicMock

from ts_cli.migrate import discover
from ts_cli.migrate.schema import ColumnInfo

MODEL_EDOC = json.dumps({
    "guid": "src-guid",
    "model": {
        "name": "Sales",
        "columns": [
            {"name": "Amount", "column_id": "T::AMT", "properties": {"column_type": "MEASURE"}},
            {"name": "Department", "column_id": "T::DEPT", "properties": {"column_type": "ATTRIBUTE"}},
        ],
    },
})
ANSWER_EDOC = json.dumps({
    "guid": "ans-1",
    "answer": {"name": "A1", "search_query": "[Department] [Amount]", "answer_columns": []},
})


def _client_returning(*edocs):
    """Return a mock client whose .post().json() yields export payloads in order."""
    client = MagicMock()
    client.post.side_effect = [MagicMock(json=lambda e=e: [{"edoc": e}]) for e in edocs]
    return client


def test_model_columns_parses_name_binding_and_type():
    cols = discover.model_columns(_client_returning(MODEL_EDOC), "src-guid")
    assert cols[0] == ColumnInfo("Amount", "T::AMT", "MEASURE")
    assert cols[1].name == "Department"


def test_find_model_by_name_matches_case_insensitively():
    client = MagicMock()
    client.post.return_value = MagicMock(json=lambda: [
        {"metadata_id": "tgt-1", "metadata_name": "Sales", "metadata_type": "LOGICAL_TABLE"},
    ])
    assert discover.find_model_by_name(client, "sales") == "tgt-1"


def test_find_model_by_name_returns_none_when_absent():
    client = MagicMock()
    client.post.return_value = MagicMock(json=lambda: [])
    assert discover.find_model_by_name(client, "Nope") is None


def test_used_column_names_finds_referenced_columns_only():
    client = _client_returning(ANSWER_EDOC)
    used = discover.used_column_names(
        client, dependents=[{"guid": "ans-1"}], source_col_names={"Amount", "Department", "Notes"}
    )
    assert used == {"Amount", "Department"}
