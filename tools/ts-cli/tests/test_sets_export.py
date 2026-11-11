"""`ts_cli.sets.export` — one Set's TML to a file, never from an unconfirmed body (spec §7)."""
import json
from unittest.mock import MagicMock

import pytest

from ts_cli.sets import export as ex

SET = {"guid": "69f6aed0-503f-4ded-87b2-bac3ffe391af", "name": "Top Brands"}

# Shape of the live export (se-thoughtspot, 2026-11-11, edoc_format YAML), trimmed.
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


def test_writes_tml_as_received_and_requests_yaml_with_fqn(tmp_path):
    c = _client([_item()])
    path = tmp_path / "o" / "x.cohort.tml"
    assert ex.export_set_tml(c, SET, path) is None
    assert path.read_text() == EDOC
    sent = c.post.call_args.kwargs["json"]
    # edoc_format is the key v2 reads; formattype is ignored (live 2026-11-11, open item #9)
    assert sent == {"metadata": [{"identifier": SET["guid"]}], "export_fqn": True,
                    "edoc_format": "YAML"}
    assert c.post.call_args.kwargs["raise_for_status"] is False


def test_json_edoc_is_written_byte_for_byte(tmp_path):
    """Never re-serialised: a YAML round trip folds NEL, rejects C1 controls and unquotes
    number-like strings such as "1e5" (pr-reviewer, 2026-11-11)."""
    doc = {"guid": SET["guid"], "cohort": {"name": "Top\x85Brands\x92",
                                           "groups": [{"name": "1e5"}]}}
    edoc = json.dumps(doc)
    path = tmp_path / "x.cohort.tml"
    assert ex.export_set_tml(_client([_item(edoc=edoc)]), SET, path) is None
    assert path.read_text(encoding="utf-8") == edoc + "\n"
    assert json.loads(path.read_text(encoding="utf-8")) == doc


@pytest.mark.parametrize("body,code,expect", [
    ([], 200, "unexpected export response"),
    ({"error": "x"}, 200, "unexpected export response"),
    ([_item(status="ERROR")], 200, "status ERROR"),
    ([_item(edoc="")], 200, "Top Brands:"),   # export_item_doc wording
    ([_item(edoc="guid: abc\nliveboard:\n  name: L\n")], 200, "not Set (cohort) TML"),
    ([_item(edoc="guid: other-guid\ncohort:\n  name: X\n")], 200, "different object"),
    ([_item(edoc="cohort:\n  name: X\n", id="other-guid")], 200, "different object (other-guid)"),
    ([_item(edoc="cohort: [unclosed\n")], 200, "does not parse"),
    ({"error": "forbidden"}, 403, "HTTP 403"),
], ids=["empty", "not-a-list", "status-error", "no-edoc", "wrong-type", "wrong-guid",
        "no-root-guid-wrong-info-id", "bad-yaml", "http-error"])
def test_unconfirmed_body_fails_and_writes_nothing(tmp_path, body, code, expect):
    path = tmp_path / "x.cohort.tml"
    reason = ex.export_set_tml(_client(body, code), SET, path)
    assert reason and expect in reason
    assert not path.exists()


@pytest.mark.parametrize("exc", [RuntimeError("network down"), SystemExit(1)],
                         ids=["exception", "client-exits-after-retries"])
def test_call_failure_is_reported_not_raised(tmp_path, exc):
    """The real client raises SystemExit(1) after its retries (client.py); it must become
    a failed export, not end the whole inventory (pr-reviewer, 2026-11-11)."""
    c = MagicMock()
    c.post.side_effect = exc
    path = tmp_path / "x.cohort.tml"
    assert "export call failed" in ex.export_set_tml(c, SET, path)
    assert not path.exists()


def test_write_failure_is_reported(tmp_path):
    blocker = tmp_path / "o"
    blocker.write_text("a file where a directory should be")
    reason = ex.export_set_tml(_client([_item()]), SET, blocker / "x.cohort.tml")
    assert reason and reason.startswith("could not write")


def test_tml_path_is_one_safe_segment_per_level(tmp_path):
    p = ex.tml_path(tmp_path, "(default)", {"guid": "g1", "name": "../../etc/Top/5"})
    assert p.parent.parent == tmp_path
    assert p.parent.name == "default"
    assert p.name == "etc_Top_5__g1.cohort.tml"
    assert ex.tml_path(tmp_path, "", {"guid": "g1", "name": ""}).name == "unnamed__g1.cohort.tml"


def test_non_latin_names_are_kept(tmp_path):
    p = ex.tml_path(tmp_path, "東京", {"guid": "g1", "name": "上位ブランド/2"})
    assert p.parent.name == "東京" and p.name == "上位ブランド_2__g1.cohort.tml"


@pytest.mark.parametrize("name", ["я" * 105, "上" * 72, "上" * 400, "a" * 400, "é" * 75 + "上",
                                  "a" * 149 + "上"],
                         ids=["cyrillic-105", "cjk-72", "cjk-400", "ascii-400", "boundary",
                              "mid-character"])
def test_names_are_the_longest_prefix_within_both_caps(tmp_path, name):
    """255-byte name limit (ext4/XFS/Btrfs) counts UTF-8 bytes; Windows caps the path at 260
    characters. Each segment is the LONGEST prefix within 120 chars and 150 bytes."""
    p = ex.tml_path(tmp_path, name, {"guid": SET["guid"], "name": name})
    seg = ex.safe_name(name)
    assert name.startswith(seg)
    assert len(seg) <= 120 and len(seg.encode("utf-8")) <= 150
    longer = name[:len(seg) + 1]
    assert len(longer) > 120 or len(longer.encode("utf-8")) > 150 or longer == seg
    for part in (p.parent.name, p.name):
        assert len(part.encode("utf-8")) <= 255


def test_non_guid_id_still_fits(tmp_path):
    p = ex.tml_path(tmp_path, "o", {"guid": "x" * 400, "name": "上" * 400})
    assert len(p.name.encode("utf-8")) <= 255


def test_combining_marks_are_kept():
    assert ex.safe_name("नमस्ते") == "नमस्ते"
    assert ex.safe_name("e\u0301clair") == "e\u0301clair"


def test_yaml_with_c1_character_is_checked_and_written_as_received(tmp_path):
    """A raw U+0095 breaks the YAML parser (thoughtspot-tml.md); strip it for the check
    only — the file keeps it (pr-reviewer re-review, 2026-11-11)."""
    edoc = EDOC.replace("name: Top Brands", "name: Top\x95Brands")
    path = tmp_path / "x.cohort.tml"
    assert ex.export_set_tml(_client([_item(edoc=edoc)]), SET, path) is None
    assert path.read_text(encoding="utf-8") == edoc


def test_yaml_with_nel_is_checked_and_written_as_received(tmp_path):
    """NEL (U+0085) survives strip_nonprintable and YAML reads it as a line break."""
    edoc = EDOC.replace("name: Top Brands", "name: Top\x85Brands")
    path = tmp_path / "x.cohort.tml"
    assert ex.export_set_tml(_client([_item(edoc=edoc)]), SET, path) is None
    assert path.read_text(encoding="utf-8") == edoc
