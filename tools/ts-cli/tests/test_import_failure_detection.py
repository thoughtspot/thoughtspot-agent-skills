"""BL-138: `metadata/tml/import` returns HTTP 200 even when items failed.

The per-item outcome lives in the body, not the status code, so a caller checking only
`resp.ok` reports success on an import that did nothing. Live-observed: a CSR import
failing with error 14502 exited 0. `ts security column-rules import` was fixed at the
time; `ts alias import` and `ts tml import` had the identical gap and are fixed here.

These assert the CONTRACT the three callers share, so a future fourth caller has
something to copy.
"""
from __future__ import annotations

from ts_cli.tml_common import format_import_failures, tml_import_failures


def _item(index, status, message=None, code=None):
    status_block = {"status_code": status}
    if message:
        status_block["error_message"] = message
    if code:
        status_block["error_code"] = code
    return {"request_index": index, "response": {"status": status_block}}


def test_an_all_ok_response_reports_no_failures():
    assert tml_import_failures([_item(0, "OK"), _item(1, "OK")]) == []


def test_an_error_item_inside_a_200_is_detected():
    """The whole point: HTTP said fine, the body did not."""
    failures = tml_import_failures([_item(0, "OK"), _item(1, "ERROR", "boom", 14502)])
    assert len(failures) == 1
    assert failures[0]["request_index"] == 1


def test_a_missing_status_block_is_NOT_treated_as_a_failure():
    """No positive evidence of failure. Defaulting to "failed" would flag responses that
    never carried status information at all."""
    assert tml_import_failures([{"request_index": 0, "response": {}}]) == []


def test_junk_and_empty_responses_do_not_raise():
    """A read-back must not fail louder than the write it is checking."""
    for junk in (None, [], {}, "nonsense", [{"nope": 1}]):
        assert tml_import_failures(junk) == []


def test_the_message_names_the_contradiction_not_just_the_failure():
    """The surprising part is not that an item failed, but that it failed inside a 200.
    A reader who does not know that will go looking at the HTTP layer."""
    lines = format_import_failures(
        tml_import_failures([_item(0, "ERROR", "Referenced table not found", 14502)]),
        "Could not import TML")
    assert "HTTP call succeeded" in lines[0]
    assert "Referenced table not found" in lines[1]


def test_an_error_with_no_message_still_reports_something_useful():
    lines = format_import_failures(tml_import_failures([_item(0, "ERROR", code=14502)]),
                                   "ctx")
    assert "14502" in lines[1]


def test_every_failed_item_is_named_not_just_the_first():
    """A batch import fails per item; reporting one would hide the rest."""
    failures = tml_import_failures([_item(0, "ERROR", "a"), _item(1, "OK"),
                                    _item(2, "ERROR", "b")])
    lines = format_import_failures(failures, "ctx")
    assert len(lines) == 3                      # header + 2 failures
    assert "[0]" in lines[1] and "[2]" in lines[2]


def test_all_three_import_callers_are_wired_to_the_helper():
    """The gap was fixed for CSR only at the time, deliberately, to keep that PR small.
    This asserts the follow-up actually landed for the other two, so the next reader does
    not have to grep three modules to find out."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "ts_cli" / "commands"
    for module in ("alias.py", "tml.py", "security_planning.py"):
        text = (root / module).read_text(encoding="utf-8")
        assert "tml_import_failures" in text, f"{module} still trusts resp.ok alone"
