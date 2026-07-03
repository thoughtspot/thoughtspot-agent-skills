# tools/ts-cli/tests/test_report_probe_failures.py
"""Unit tests for ts_cli.report — probe-failure honesty (2026-07 audit finding 4.1).

Before this fix, a TML probe exception (the RLS/joins/AI-surface/column-alias export,
or the separate Monitor-alerts export) was swallowed and the affected coverage rows
still reported `checked=True, found=0` — indistinguishable from "verified: no
RLS/alert usage". Since ts-dependency-manager reads `found=0, checked=True` rows to
green-light destructive removals, a failed probe silently authorised a removal it
never actually verified.

Covers:
  - build_coverage(): the pure function, given explicit per-probe success flags
  - build_report(): the full pipeline with a mocked ThoughtSpotClient whose deep-probe
    calls raise, proving the wiring end to end (no live connection).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from ts_cli.report import build_coverage, build_report


def _resp(body):
    r = MagicMock()
    r.json.return_value = body
    return r


# ---------------------------------------------------------------------------
# build_coverage — pure function
# ---------------------------------------------------------------------------

class TestBuildCoverageAllProbesOk:
    def test_deep_active_and_probes_ok_reports_checked_true(self):
        coverage, warnings = build_coverage(
            [], rls_hits=[], alert_hits=[], alias_hits=[], join_hits=[], ai_hits=[],
            deep_active=True, primary_probe_ok=True, monitor_probe_ok=True,
        )
        by_type = {c.type: c for c in coverage}
        for t in ("RLS rules", "Joins", "Spotter AI surface area",
                  "Column alias TML", "Monitor alerts"):
            assert by_type[t].checked is True, f"{t} should be checked=True when probes succeed"
        assert warnings == []


class TestPrimaryProbeFailure:
    def test_flips_checked_false_on_all_four_affected_rows(self):
        coverage, warnings = build_coverage(
            [], rls_hits=[], alert_hits=[], alias_hits=[], join_hits=[], ai_hits=[],
            deep_active=True, primary_probe_ok=False, monitor_probe_ok=True,
            primary_probe_error="Connection reset",
        )
        by_type = {c.type: c for c in coverage}
        for t in ("RLS rules", "Joins", "Spotter AI surface area", "Column alias TML"):
            entry = by_type[t]
            assert entry.checked is False, f"{t} must be checked=False on probe failure"
            assert entry.found == 0
            assert entry.reason == "TML probe failed — see warnings"

    def test_does_not_affect_monitor_alerts_row(self):
        """Monitor alerts is fed by a SEPARATE probe (the Liveboard TML export) —
        a primary-probe failure must not falsely flag it too."""
        coverage, _ = build_coverage(
            [], rls_hits=[], alert_hits=[], alias_hits=[], join_hits=[], ai_hits=[],
            deep_active=True, primary_probe_ok=False, monitor_probe_ok=True,
        )
        by_type = {c.type: c for c in coverage}
        assert by_type["Monitor alerts"].checked is True

    def test_appends_human_readable_warning_with_error_detail(self):
        _, warnings = build_coverage(
            [], rls_hits=[], alert_hits=[], alias_hits=[], join_hits=[], ai_hits=[],
            deep_active=True, primary_probe_ok=False, monitor_probe_ok=True,
            primary_probe_error="Connection reset",
        )
        assert len(warnings) == 1
        assert "Connection reset" in warnings[0]
        assert "UNVERIFIED" in warnings[0]
        assert "found=0" in warnings[0]

    def test_no_hits_still_found_zero_but_unchecked(self):
        """found stays an accurate hit count (0, since the probe never ran) — the
        signal that a caller must not read found=0 as confirmed absence is the
        checked=False flag + reason + warning, not a fabricated found value."""
        coverage, _ = build_coverage(
            [], rls_hits=[], alert_hits=[], alias_hits=[], join_hits=[], ai_hits=[],
            deep_active=True, primary_probe_ok=False, monitor_probe_ok=True,
        )
        by_type = {c.type: c for c in coverage}
        assert by_type["RLS rules"].found == 0


class TestMonitorProbeFailure:
    def test_flips_checked_false_only_on_monitor_alerts_row(self):
        coverage, warnings = build_coverage(
            [], rls_hits=[], alert_hits=[], alias_hits=[], join_hits=[], ai_hits=[],
            deep_active=True, primary_probe_ok=True, monitor_probe_ok=False,
            monitor_probe_error="500 Internal Server Error",
        )
        by_type = {c.type: c for c in coverage}
        assert by_type["Monitor alerts"].checked is False
        assert by_type["Monitor alerts"].found == 0
        assert by_type["Monitor alerts"].reason == "TML probe failed — see warnings"
        # RLS/Joins/AI-surface/alias are fed by the OTHER probe — unaffected.
        for t in ("RLS rules", "Joins", "Spotter AI surface area", "Column alias TML"):
            assert by_type[t].checked is True

    def test_appends_warning_naming_monitor_alerts(self):
        _, warnings = build_coverage(
            [], rls_hits=[], alert_hits=[], alias_hits=[], join_hits=[], ai_hits=[],
            deep_active=True, primary_probe_ok=True, monitor_probe_ok=False,
            monitor_probe_error="500 Internal Server Error",
        )
        assert len(warnings) == 1
        assert "500 Internal Server Error" in warnings[0]
        assert "Monitor alerts" in warnings[0]


class TestBothProbesFail:
    def test_produces_two_distinct_warnings(self):
        _, warnings = build_coverage(
            [], rls_hits=[], alert_hits=[], alias_hits=[], join_hits=[], ai_hits=[],
            deep_active=True, primary_probe_ok=False, monitor_probe_ok=False,
        )
        assert len(warnings) == 2


class TestNotDeepActiveIsNotAProbeFailure:
    def test_non_column_source_is_unchecked_without_a_warning(self):
        """Table/model sources never activate deep probes at all (documented v1
        limitation) — that's a different reason than a probe raising, and must not
        produce a spurious "probe failed" warning."""
        coverage, warnings = build_coverage(
            [], rls_hits=[], alert_hits=[], alias_hits=[], join_hits=[], ai_hits=[],
            deep_active=False, primary_probe_ok=True, monitor_probe_ok=True,
        )
        by_type = {c.type: c for c in coverage}
        assert by_type["RLS rules"].checked is False
        assert by_type["RLS rules"].reason == "deep probes only populate for column sources in v1"
        assert warnings == []


# ---------------------------------------------------------------------------
# build_report — full pipeline, mocked ThoughtSpotClient
# ---------------------------------------------------------------------------

class TestBuildReportPropagatesProbeFailures:
    @patch("ts_cli.report.ThoughtSpotClient")
    def test_primary_probe_exception_sets_checked_false_and_warning(self, MockClient):
        client = MagicMock()
        MockClient.return_value = client
        uuid = "baa451a6-02a0-42d1-8347-8cd4af13b505"

        # Call 1: resolve_source (GUID -> metadata/search, a LOGICAL_COLUMN hit)
        # Call 2: walk_dependents_recursive (no dependents)
        # Call 3: the primary TML probe export -> raises
        client.post.side_effect = [
            _resp([{
                "metadata_id": "g-1", "metadata_name": "Col",
                "metadata_type": "LOGICAL_COLUMN",
                "metadata_header": {"id": "g-1", "name": "Col"},
            }]),
            _resp([{"metadata_id": "g-1", "dependent_objects": {"dependents": {}}}]),
            RuntimeError("boom"),
        ]

        out = build_report(uuid, profile="test", with_deep=True)

        by_type = {c["type"]: c for c in out["coverage"]}
        for t in ("RLS rules", "Joins", "Spotter AI surface area", "Column alias TML"):
            assert by_type[t]["checked"] is False, f"{t} must be checked=False"
            assert by_type[t]["found"] == 0
        assert len(out["warnings"]) == 1
        assert "boom" in out["warnings"][0]

    @patch("ts_cli.report.ThoughtSpotClient")
    def test_monitor_probe_exception_sets_checked_false_and_warning(self, MockClient):
        client = MagicMock()
        MockClient.return_value = client
        uuid = "baa451a6-02a0-42d1-8347-8cd4af13b505"

        # Call 1: resolve_source (LOGICAL_COLUMN hit)
        # Call 2: walk_dependents_recursive -> one Liveboard dependent (depth 1,
        #   max_depth=1 so the walk stops before re-querying it)
        # Call 3: the primary TML probe export -> succeeds
        # Call 4: the Monitor-alerts Liveboard export -> raises
        client.post.side_effect = [
            _resp([{
                "metadata_id": "g-1", "metadata_name": "Col",
                "metadata_type": "LOGICAL_COLUMN",
                "metadata_header": {"id": "g-1", "name": "Col"},
            }]),
            _resp([{
                "metadata_id": "g-1",
                "dependent_objects": {
                    "dependents": {
                        "g-1": {"PINBOARD_ANSWER_BOOK": [{"id": "lb-1", "name": "LB"}]},
                    },
                },
            }]),
            _resp([{"info": {"type": "model"}, "edoc": "column_alias:\n  columns: []\n"}]),
            RuntimeError("monitor export exploded"),
        ]

        out = build_report(uuid, profile="test", with_deep=True, max_depth=1)

        by_type = {c["type"]: c for c in out["coverage"]}
        assert by_type["Monitor alerts"]["checked"] is False
        assert by_type["Monitor alerts"]["found"] == 0
        assert by_type["RLS rules"]["checked"] is True  # unaffected — different probe
        assert any("monitor export exploded" in w for w in out["warnings"])
