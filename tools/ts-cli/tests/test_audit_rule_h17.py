"""H17: a Model with no query in 90 days or more, or none in the usage history.

Graded from `ctx.usage` (audit/usage.py), relative to when the usage was read, so a
replay judges as the live run did. Not judged when the usage was not read: a failed
read must never read as "unused". Synthetic GUIDs only.
"""
from __future__ import annotations

import pytest

import audit_rule_fixtures as fx
from ts_cli.audit.catalog_model import load_catalog
from ts_cli.audit.context import make_context
from ts_cli.audit.engine.run import run_rules


def _h17(ctx, profile="general"):
    return [f for f in run_rules(ctx, load_catalog(), ["H"], profile) if f.check_id == "H17"]


def _ctx(usage, guid="m-1"):
    return make_context(models=[fx.build_human_model(guid=guid)], usage=usage)


@pytest.mark.parametrize("profile", ["general", "spotter"])
@pytest.mark.parametrize("days, fires", [(89, False), (90, True), (91, True)])
def test_90_days_or_more_since_the_last_query_fires(days, fires, profile):
    found = _h17(_ctx(fx.build_usage({"m-1": days})), profile)
    if not fires:
        assert found == []
        return
    [f] = found
    assert (f.severity, f.object_guid, f.object_type, f.metric) == ("LOW", "m-1", "model", days)
    last = {90: "2026-08-27", 91: "2026-08-26"}[days]
    assert f.detail == (f"No query in {days} days; last queried on {last} "
                        "(usage of the Org 'Primary')")


def test_90_and_a_half_days_fires_as_90_whole_days():
    usage = fx.build_usage({"m-1": {"last_used": fx.USAGE_READ_AT - 90 * 86400 - 12 * 3600,
                                    "queries_180d": 1, "users_180d": 1}})
    [f] = _h17(_ctx(usage))
    assert f.metric == 90


def test_89_and_a_half_days_is_still_89_whole_days():
    usage = fx.build_usage({"m-1": {"last_used": fx.USAGE_READ_AT - 89 * 86400 - 12 * 3600,
                                    "queries_180d": 1, "users_180d": 1}})
    assert _h17(_ctx(usage)) == []


def test_a_model_the_history_never_mentions_fires_naming_where_it_starts():
    [f] = _h17(_ctx(fx.build_usage({"other": 3})))
    assert f.severity == "LOW" and f.metric is None
    assert f.detail == ("No query in the usage history ThoughtSpot holds, which starts on "
                        "2023-10-01 (usage of the Org 'Primary')")


def test_a_history_with_no_start_is_not_read_and_judges_no_model():
    """No first query time: the history says nothing about any Model."""
    usage = fx.build_usage({"m-1": 200}, start=None)
    assert _h17(_ctx(usage)) == []
    assert _h17(_ctx(fx.build_usage({}, start=None))) == []


@pytest.mark.parametrize("history_days, fires", [(89, False), (90, True), (400, True)])
def test_never_queried_needs_a_history_of_90_days_or_more(history_days, fires):
    """A Model missing from a short history may simply be newer than the history."""
    usage = fx.build_usage({"other": 3}, start=fx.USAGE_READ_AT - history_days * 86400)
    assert len(_h17(_ctx(usage))) == (1 if fires else 0)


def test_a_row_with_no_query_time_says_nothing():
    usage = fx.build_usage({"m-1": None})
    assert _h17(_ctx(usage)) == []


def test_not_read_usage_judges_no_model():
    """None — not fetched, or a failed read — is never "unused"."""
    assert _h17(_ctx(None)) == []


def test_the_org_whose_usage_was_read_is_named():
    usage = fx.build_usage({}, org={"id": 7, "name": "Tenant B"})
    [f] = _h17(_ctx(usage))
    assert f.detail.endswith("(usage of the Org 'Tenant B')")
    unnamed = fx.build_usage({}, org={"id": None, "name": None})
    [f] = _h17(_ctx(unnamed))
    assert f.detail.endswith("(usage of the audit's Org (its name could not be read))")


def test_idle_days_is_a_catalog_parameter():
    rule = load_catalog().rules["H17"]
    assert rule.parameters == {"idle_days": 90}
    assert rule.requires == ["model_tml", "usage"] and rule.severity == "LOW"
    assert rule.evidence == "fact" and "cleanup" in rule.views
