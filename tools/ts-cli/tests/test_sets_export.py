"""`ts_cli.sets.export` — one Set's TML to a file, never from an unconfirmed body (spec §7)."""
import json
from unittest.mock import MagicMock

import pytest

from ts_cli.sets import export as ex

SET = {"guid": "69f6aed0-503f-4ded-87b2-bac3ffe391af", "name": "Top Brands"}

# Shape of the live export (se-thoughtspot, 2026-11-11), trimmed.
EDOC = ('guid: 69f6aed0-503f-4ded-87b2-bac3ffe391af\ncohort:\n  name: Top Brands\n'
        '  worksheet:\n    name: Retail Sales - RP\n    fqn: e2806e7c-87d3-44b7-b230-69efb6183045\n'
        '  config:\n    cohort_type: ADVANCED\n    cohort_grouping_type: COLUMN_BASED\n')


def _item(edoc=EDOC, status="OK", **info):
    return {"info": dict({"name": "Top Brands", "id": SET["guid"], "type": "cohort",
                          "status": {"status_code": status}}, **info), "edoc": edoc}


def _client(body, status_code=200):
    resp = MagicMock(status_code=status_code, text=json.dumps(body))
    resp.json.return_value = body
    c = MagicMock()
    c.post.return_value = resp
    return c


def test_writes_tml_and_requests_yaml_with_fqn(tmp_path):
    c = _client([_item()])
    path = tmp_path / "o" / "x.cohort.tml"
    assert ex.export_set_tml(c, SET, path) is None
    assert path.read_text() == EDOC
    sent = c.post.call_args.kwargs["json"]
    assert sent == {"metadata": [{"identifier": SET["guid"]}], "export_fqn": True,
                    "formattype": "YAML"}
    assert c.post.call_args.kwargs["raise_for_status"] is False


@pytest.mark.parametrize("body,code,expect", [
    ([], 200, "unexpected export response"),
    ({"error": "x"}, 200, "unexpected export response"),
    ([_item(status="ERROR", )], 200, "export status 'ERROR'"),
    ([_item(edoc="")], 200, "no TML"),
    ([_item(edoc="guid: abc\nliveboard:\n  name: L\n")], 200, "not Set (cohort) TML"),
    ([_item(edoc="guid: other-guid\ncohort:\n  name: X\n")], 200, "different object"),
    ([_item(edoc="cohort: [unclosed\n")], 200, "does not parse"),
    ({"error": "forbidden"}, 403, "HTTP 403"),
], ids=["empty", "not-a-list", "status-error", "no-edoc", "wrong-type", "wrong-guid",
        "bad-yaml", "http-error"])
def test_unconfirmed_body_fails_and_writes_nothing(tmp_path, body, code, expect):
    path = tmp_path / "x.cohort.tml"
    reason = ex.export_set_tml(_client(body, code), SET, path)
    assert reason and expect in reason
    assert not path.exists()


def test_json_edoc_is_written_as_equivalent_yaml(tmp_path):
    """Live: the server answered JSON with formattype YAML (se-thoughtspot, 2026-11-11)."""
    import yaml
    doc = yaml.safe_load(EDOC)
    path = tmp_path / "x.cohort.tml"
    assert ex.export_set_tml(_client([_item(edoc=json.dumps(doc))]), SET, path) is None
    text = path.read_text()
    assert not text.lstrip().startswith("{")
    assert yaml.safe_load(text) == doc
    assert list(yaml.safe_load(text)) == ["guid", "cohort"]   # key order kept


def test_call_exception_is_reported(tmp_path):
    c = MagicMock()
    c.post.side_effect = RuntimeError("network down")
    path = tmp_path / "x.cohort.tml"
    assert "network down" in ex.export_set_tml(c, SET, path)
    assert not path.exists()


def test_tml_path_is_one_safe_segment_per_level(tmp_path):
    p = ex.tml_path(tmp_path, "(default)", {"guid": "g1", "name": "../../etc/Top/5"})
    assert p.parent.parent == tmp_path
    assert p.parent.name == "default"
    assert p.name == "etc_Top_5__g1.cohort.tml"
    assert ex.tml_path(tmp_path, "", {"guid": "g1", "name": ""}).name == "unnamed__g1.cohort.tml"
