# tools/ts-cli/tests/test_report_review2_lookup.py
"""Formula-column cascade lookup — PR #506 review, 2026-10-08.

`find_column_guid_by_name` searched one 50-record page of a cluster-wide name
match and filtered by owner in memory, so a common name could push the real
column past the page. Its caller then skipped a None result silently, so that
formula's Answers/Liveboards dropped out of the impact report with no trace —
the same "empty lookup reads as nothing depends on this" class as blocker 6.

Covers:
  - the lookup paginates until the owner matches or results run out
  - an empty lookup (and an erroring one) warns, names the formula and Model,
    and leaves the "Formula column dependents" coverage row checked=False
No network: every client is a MagicMock.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from ts_cli.report import (
    _ProbeState, _extended_probe_map, _run_per_model_probes, build_extended_coverage,
)
from ts_cli.report import impact_probes


def _resp(body):
    r = MagicMock()
    r.json.return_value = body
    return r


def _other_owner_rows(n, start=0):
    return [{"metadata_id": f"other-{i}", "metadata_header": {"owner": f"m-other-{i}"}}
            for i in range(start, start + n)]


class TestLookupPaginates:
    def test_match_on_second_page_is_found(self):
        client = MagicMock()
        client.post.side_effect = [
            _resp(_other_owner_rows(50)),
            _resp(_other_owner_rows(7, start=50)
                  + [{"metadata_id": "col-target", "metadata_header": {"owner": "m-1"}}]),
        ]
        assert impact_probes.find_column_guid_by_name(client, "Revenue", "m-1") == "col-target"
        offsets = [c.kwargs["json"]["record_offset"] for c in client.post.call_args_list]
        assert offsets == [0, 50]

    def test_exhausts_every_page_before_returning_none(self):
        client = MagicMock()
        client.post.side_effect = [
            _resp(_other_owner_rows(50)),
            _resp(_other_owner_rows(50, start=50)),
            _resp(_other_owner_rows(3, start=100)),
        ]
        assert impact_probes.find_column_guid_by_name(client, "Revenue", "m-1") is None
        assert client.post.call_count == 3


def _model(name="Sales Model"):
    return {"model": {"name": name,
                      "formulas": [{"id": "f1", "name": "Net Rev", "expr": "sum ( [AMOUNT] ) * 0.9"}]}}


def _run(lookup_kwargs, walk_rows=None):
    state = _ProbeState()
    state.model_docs = [("m-1", _model())]
    with patch.object(impact_probes, "fetch_formula_variables", return_value=[]), \
         patch.object(impact_probes, "fetch_business_terms_and_ai_memory", return_value=[]), \
         patch.object(impact_probes, "find_column_guid_by_name", **lookup_kwargs), \
         patch.object(impact_probes, "walk_one_hop", return_value=walk_rows or []) as walk:
        _run_per_model_probes(state, MagicMock(), {"AMOUNT"}, "AMOUNT")
    return state, walk


def _cascade_row(state):
    coverage, _ = build_extended_coverage(deep_active=True, probes=_extended_probe_map(state))
    return next(c for c in coverage if c.type == "Formula column dependents")


class TestEmptyLookupIsNeverSilent:
    def test_empty_lookup_warns_naming_formula_and_model(self):
        state, walk = _run({"return_value": None})
        walk.assert_not_called()
        assert len(state.walk_warnings) == 1
        w = state.walk_warnings[0]
        assert "'Net Rev'" in w and "'Sales Model'" in w and "m-1" in w
        assert "could NOT be walked" in w and "no column of that name" in w

    def test_empty_lookup_marks_cascade_row_unchecked(self):
        state, _ = _run({"return_value": None})
        row = _cascade_row(state)
        assert row.checked is False
        assert row.reason == "probe failed — see warnings"

    def test_erroring_lookup_also_marks_row_unchecked(self):
        state, _ = _run({"side_effect": RuntimeError("HTTP 500")})
        assert "HTTP 500" in state.walk_warnings[0]
        assert _cascade_row(state).checked is False

    def test_found_lookup_walks_and_counts(self):
        rows = [{"guid": "a-1", "type": "ANSWER", "name": "Rev by region"}]
        state, walk = _run({"return_value": "col-9"}, walk_rows=rows)
        walk.assert_called_once()
        assert state.walk_warnings == []
        assert state.extra_dependent_rows == rows
        row = _cascade_row(state)
        assert row.checked is True and row.found == 1

    def test_primary_export_failure_leaves_row_unchecked(self):
        state = _ProbeState()
        state.primary_probe_ok = False
        _run_per_model_probes(state, MagicMock(), {"AMOUNT"}, "AMOUNT")
        assert _cascade_row(state).checked is False


class TestIncompleteDependentsBlockSafe:
    """A dependents list with known holes must not yield SAFE / SAFE_TO_DROP — the
    same rule as an unchecked security row (PR #506 review, 2026-10-07)."""

    def test_empty_lookup_makes_the_verdict_unverified(self):
        from ts_cli.report import _unverified_dependents
        from ts_cli.report.classifier import AggregateInputs, aggregate_classification
        state, _ = _run({"return_value": None})
        reasons = _unverified_dependents(state)
        assert reasons and "formula-column dependents were not walked" in reasons[0]
        agg = aggregate_classification(AggregateInputs(unverified_dependents=reasons))
        assert agg.aggregate.tag == "UNVERIFIED"
        assert agg.recommendation == "BLOCKED_VERIFY_DEPENDENTS_FIRST"

    def test_clean_walk_adds_nothing(self):
        from ts_cli.report import _unverified_dependents
        state, _ = _run({"return_value": "col-guid"}, walk_rows=[])
        assert _unverified_dependents(state) == []

    def test_security_outranks_incomplete_dependents(self):
        from ts_cli.report.classifier import AggregateInputs, aggregate_classification
        stop = aggregate_classification(AggregateInputs(
            csr_hits=[{"col": "AMOUNT"}], unverified_dependents=["x"]))
        assert stop.aggregate.tag == "STOP"
        sec = aggregate_classification(AggregateInputs(
            unverified_security=["CSR: not checked"], unverified_dependents=["x"]))
        assert sec.recommendation == "BLOCKED_VERIFY_SECURITY_FIRST"
