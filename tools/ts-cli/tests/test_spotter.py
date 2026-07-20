"""Unit tests for `ts spotter answer` response normalisation (no live connection)."""
from ts_cli.commands.spotter import normalise_answer_response


def test_success_with_tokens():
    raw = {
        "message_type": "TSAnswer",
        "visualization_type": "Table",
        "session_identifier": "sess-1",
        "generation_number": 1,
        "tokens": "[sales] [region]",
        "display_tokens": "Sales by Region",
    }
    out = normalise_answer_response(raw, 200)
    assert out["status"] == "SUCCESS"
    assert out["tokens"] == "[sales] [region]"
    assert out["display_tokens"] == "Sales by Region"
    assert out["visualization_type"] == "Table"
    assert out["errors"] == []


def test_success_when_only_session_returned():
    # A 200 with a session but no tokens still counts as a usable answer, not an error.
    out = normalise_answer_response({"message_type": "TSAnswer", "session_identifier": "s"}, 200)
    assert out["status"] == "SUCCESS"
    assert out["errors"] == []


def test_forbidden_maps_from_http_403():
    # 403 with a generic error object and no code -> FORBIDDEN (missing CAN_USE_SPOTTER).
    out = normalise_answer_response({"error": {"message": "no privilege"}}, 403)
    assert out["status"] == "FORBIDDEN"
    assert out["errors"][0]["code"] == "FORBIDDEN"
    assert out["errors"][0]["message"] == "no privilege"
    assert out["tokens"] is None


def test_unauthorized_maps_from_http_401():
    out = normalise_answer_response({"error": {}}, 401)
    assert out["status"] == "UNAUTHORIZED"


def test_error_object_code_is_preserved():
    out = normalise_answer_response({"error": {"code": "MODEL_NOT_FOUND", "message": "no such model"}}, 400)
    assert out["status"] == "MODEL_NOT_FOUND"
    assert out["errors"][0]["message"] == "no such model"


def test_error_message_as_nested_object_is_serialised():
    out = normalise_answer_response({"error": {"message": {"debug": "boom"}}}, 400)
    assert out["status"] == "HTTP_400"  # no code on the envelope, non-401/403 status
    assert "boom" in out["errors"][0]["message"]


def test_201_error_response_without_tokens_is_spotter_error():
    # 201 "Common error response" shares the success schema but carries no answer.
    out = normalise_answer_response({"message_type": "TSAnswer"}, 201)
    assert out["status"] == "SPOTTER_ERROR"
    assert out["errors"][0]["code"] == "SPOTTER_ERROR"


def test_empty_200_body_is_spotter_error():
    out = normalise_answer_response({}, 200)
    assert out["status"] == "SPOTTER_ERROR"
    assert out["tokens"] is None


def test_non_dict_payload_is_parse_error():
    out = normalise_answer_response("not a dict", 200)
    assert out["status"] == "PARSE_ERROR"
    assert out["errors"][0]["code"] == "PARSE_ERROR"


def test_unexpected_http_status_without_error_object():
    out = normalise_answer_response({"message": "gateway timeout"}, 504)
    assert out["status"] == "HTTP_504"
    assert out["errors"][0]["message"] == "gateway timeout"
