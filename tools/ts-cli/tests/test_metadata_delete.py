"""`ts metadata delete` partial-success handling (BL-133).

A batch delete is atomic — one missing GUID fails the whole call and deletes
nothing. The command now falls back to per-GUID deletes and reports a
`{guid: deleted|not_found|error}` outcome map, with `--ignore-missing` to treat
already-gone objects as success.
"""
import json

from unittest.mock import patch

from typer.testing import CliRunner

from ts_cli.cli import app
from ts_cli.commands.metadata import (
    classify_delete_response,
    resolve_delete_outcomes,
)

runner = CliRunner()


class _FakeResp:
    def __init__(self, *, ok=True, status_code=204, text=""):
        self.ok = ok
        self.status_code = status_code
        self.text = text


class _FakeDeleteClient:
    """Models the atomic batch delete: any missing/error GUID fails the whole
    call (deletes nothing); a per-GUID call isolates the outcome."""

    def __init__(self, *, missing=(), error=()):
        self.missing = set(missing)
        self.error = set(error)
        self.calls = []

    def post(self, path, json=None, raise_for_status=True, **kw):
        assert path.endswith("/metadata/delete")
        ids = [m["identifier"] for m in json["metadata"]]
        self.calls.append(ids)
        if any(g in self.error for g in ids):
            return _FakeResp(ok=False, status_code=403, text="forbidden")
        bad = [g for g in ids if g in self.missing]
        if bad:
            return _FakeResp(
                ok=False, status_code=400,
                text=('{"error":{"code":13003,"message":"Metadata object not '
                      'found corresponding to the metadata_identifier: '
                      f'{bad[0]}"}}}}'))
        return _FakeResp(ok=True, status_code=204, text="")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

class TestClassifyDeleteResponse:
    def test_ok_is_deleted(self):
        assert classify_delete_response(True, 204, "") == "deleted"

    def test_400_code_13003_is_not_found(self):
        out = classify_delete_response(
            False, 400,
            '{"error":{"code":13003,"message":"Metadata object not found ..."}}')
        assert out == "not_found"

    def test_400_top_level_code_13003_is_not_found(self):
        assert classify_delete_response(
            False, 400, '{"code": 13003, "message": "gone"}') == "not_found"

    def test_400_documented_phrase_non_json_is_not_found(self):
        # non-JSON body carrying the documented message still classifies
        assert classify_delete_response(
            False, 400,
            "13003 Metadata object not found corresponding to the "
            "metadata_identifier: abc") == "not_found"

    def test_400_metadata_object_not_found_phrase_is_not_found(self):
        assert classify_delete_response(
            False, 400, "Metadata Object Not Found for xyz") == "not_found"

    def test_400_unrelated_not_found_is_error(self):
        # REGRESSION GUARD (code-review finding): a *different* 400 whose message
        # merely contains "not found" (e.g. a wrong --type) must NOT be swallowed
        # as not_found — else --ignore-missing would hide a real failure.
        assert classify_delete_response(
            False, 400,
            '{"error":{"code":13005,"message":"connection not found"}}'
        ).startswith("error")

    def test_403_is_error(self):
        assert classify_delete_response(False, 403, "forbidden").startswith("error")

    def test_500_is_error(self):
        assert classify_delete_response(False, 500, "boom").startswith("error")

    def test_400_without_marker_is_error(self):
        # a 400 that isn't a missing-object error must not be swallowed as not_found
        assert classify_delete_response(False, 400, "bad type").startswith("error")


class TestResolveDeleteOutcomes:
    def test_mixed_outcomes_ordered(self):
        def delete_one(guid):
            return {
                "a": (True, 204, ""),
                "b": (False, 400, "13003 not found"),
                "c": (False, 403, "forbidden"),
            }[guid]

        outcomes = resolve_delete_outcomes(["a", "b", "c"], delete_one)
        assert list(outcomes.keys()) == ["a", "b", "c"]  # requested order
        assert outcomes["a"] == "deleted"
        assert outcomes["b"] == "not_found"
        assert outcomes["c"].startswith("error")

    def test_dedupes_requested_guids(self):
        seen = []

        def delete_one(guid):
            seen.append(guid)
            return (True, 204, "")

        outcomes = resolve_delete_outcomes(["a", "a", "b"], delete_one)
        assert seen == ["a", "b"]
        assert outcomes == {"a": "deleted", "b": "deleted"}


# ---------------------------------------------------------------------------
# CLI behaviour
# ---------------------------------------------------------------------------

def _invoke(client, args):
    with patch("ts_cli.commands.metadata.ThoughtSpotClient", return_value=client), \
         patch("ts_cli.commands.metadata.resolve_profile", return_value="test"):
        return runner.invoke(app, ["metadata", "delete", *args, "--profile", "test"])


class TestDeleteCommand:
    def test_all_present_uses_single_batch_call(self):
        client = _FakeDeleteClient()
        result = _invoke(client, ["g1", "g2", "g3"])
        assert result.exit_code == 0, result.output
        out = json.loads(result.stdout)
        assert out["deleted"] == ["g1", "g2", "g3"]
        assert out["not_found"] == [] and out["errors"] == {}
        # fast path: exactly one (batch) call, no per-GUID fallback
        assert client.calls == [["g1", "g2", "g3"]]

    def test_one_missing_falls_back_and_deletes_the_rest(self):
        client = _FakeDeleteClient(missing={"g2"})
        result = _invoke(client, ["g1", "g2", "g3"])
        # without --ignore-missing, a not_found is a non-zero exit
        assert result.exit_code == 1, result.output
        out = json.loads(result.stdout)
        assert out["deleted"] == ["g1", "g3"]
        assert out["not_found"] == ["g2"]
        assert out["errors"] == {}
        assert out["outcomes"] == {"g1": "deleted", "g2": "not_found", "g3": "deleted"}
        # batch attempted once, then per-GUID fallback for all three
        assert client.calls[0] == ["g1", "g2", "g3"]
        assert ["g1"] in client.calls and ["g2"] in client.calls

    def test_ignore_missing_exits_zero_when_only_missing(self):
        client = _FakeDeleteClient(missing={"g2"})
        result = _invoke(client, ["g1", "g2", "--ignore-missing"])
        assert result.exit_code == 0, result.output
        out = json.loads(result.stdout)
        assert out["deleted"] == ["g1"] and out["not_found"] == ["g2"]

    def test_real_error_always_exits_nonzero_even_with_ignore_missing(self):
        client = _FakeDeleteClient(error={"g2"})
        result = _invoke(client, ["g1", "g2", "--ignore-missing"])
        assert result.exit_code == 1, result.output
        out = json.loads(result.stdout)
        assert out["deleted"] == ["g1"]
        assert "g2" in out["errors"]
