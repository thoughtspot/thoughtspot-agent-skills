"""Smoke test for the ts-security-columns skill.

The skill is a DECISION layer over two mechanisms, so what has to hold is not that
either pipeline runs -- `ts share` and `ts security column-rules` have their own
tests -- but that the two engines stay distinguishable in the ways the decision
depends on. Every assertion below encodes something that was live-verified on
`nebula-damian-alias` and that, if it regressed, would make the skill recommend a
mechanism that silently fails to protect data.

No live ThoughtSpot or Snowflake connection required.

Evidence: docs/superpowers/verification/2026-07-27-ts-security-columns-live-verification.md
"""
import sys
from pathlib import Path

# Test the ts_cli in THIS checkout, not whatever happens to be installed. An
# editable install usually points at the primary clone, so on a worktree branch
# the hook would otherwise import the wrong copy.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ts-cli"))

from ts_cli.csr_plan import (  # noqa: E402
    build_csr_steps,
    build_update_payload,
    explain_csr_error,
    parse_rule_flags,
)
from ts_cli.share_plan import (  # noqa: E402
    build_share_steps,
    find_exclusivity_conflicts,
    parse_grant_rows,
)


def _grant(org, obj, group, mode="READ_ONLY", column="", obj_type="LOGICAL_TABLE"):
    """One raw manifest row, exactly the TS_SHARE_GRANTS columns."""
    return {"org_name": org, "object_identifier": obj, "object_type": obj_type,
            "column_name": column, "group_name": group, "share_mode": mode}


def _resolved(rows):
    """Manifest rows through the real pipeline order: parse, THEN resolve.

    `parse_grant_rows` normalises to the manifest columns only -- GUIDs are attached
    afterwards by `ts share resolve`, and `build_share_steps` refuses a row without
    them, because building a payload around an empty identifier would share nothing
    while reporting success. This stands in for that resolution step.
    """
    out = []
    for row in parse_grant_rows(rows):
        row = dict(row)
        row["object_guid"] = f"guid-{row['object_identifier']}"
        if row["column_name"]:
            row["column_guid"] = f"guid-{row['object_identifier']}-{row['column_name']}"
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# The declaration models are INVERSE, and must not be interchangeable
# ---------------------------------------------------------------------------

def test_the_two_manifests_declare_opposite_things():
    """CSR names the RESTRICTED columns; CLS names the VISIBLE ones.

    This is the inversion an operator most easily gets backwards, and getting it
    backwards exposes exactly the columns they meant to hide. The engines must not
    accept each other's row shape.
    """
    # CSR: "UNIT_PRICE_AMT is restricted; only Analyst may see it."
    csr = parse_rule_flags(["UNIT_PRICE_AMT=Analyst"])
    assert csr == {"UNIT_PRICE_AMT": ["Analyst"]}

    # CLS: "Consumer may see these three columns" -- enumerating the VISIBLE set.
    cls_rows = parse_grant_rows([
        _grant("Primary", "T2_PUBLISH", "Consumer", column="PROD_NM"),
        _grant("Primary", "T2_PUBLISH", "Consumer", column="PROD_CAT_L1"),
        _grant("Primary", "T2_PUBLISH", "Consumer", column="AMOUNT"),
    ])
    assert len(cls_rows) == 3
    assert {r["column_name"] for r in cls_rows} == {"PROD_NM", "PROD_CAT_L1", "AMOUNT"}

    # A CSR manifest row carries no share_mode, so it cannot be fed to the CLS parser.
    try:
        parse_grant_rows([{"org_name": "Primary", "table_name": "T2_PUBLISH",
                           "column_name": "UNIT_PRICE_AMT", "group_name": "Analyst"}])
    except (ValueError, KeyError):
        pass
    else:
        raise AssertionError("a CSR-shaped row must not parse as a CLS grant")


# ---------------------------------------------------------------------------
# CLS is one step, CSR is two -- the asymmetry the plan shape rests on
# ---------------------------------------------------------------------------

def test_cls_column_grant_is_self_contained():
    """Live-verified 2026-07-27: with NO object grant, a group holding only column
    grants opened both Table and Model and saw exactly those columns. So a CLS plan
    carrying only column grants is complete, not half-built."""
    steps = build_share_steps(_resolved([
        _grant("Primary", "T2_PUBLISH", "Consumer", column="PROD_NM"),
        _grant("Primary", "T2_PUBLISH", "Consumer", column="AMOUNT"),
    ]))
    assert len(steps) == 1, "one call per (Org, type, audience)"
    assert steps[0]["metadata_type"] == "LOGICAL_COLUMN"
    assert steps[0]["org_name"] == "Primary"


def test_csr_payload_never_conveys_access():
    """CSR filters WITHIN access someone else granted. Its payload must contain no
    principal grant of any kind -- if it did, the skill's ordering rule (object
    access first) would be pointless."""
    payload = build_update_payload("T2_PUBLISH", {"UNIT_PRICE_AMT": ["Analyst"]})
    flat = repr(payload)
    assert "share_mode" not in flat and "permissions" not in flat
    assert payload["column_security_rules"][0]["column_identifier"] == "UNIT_PRICE_AMT"


# ---------------------------------------------------------------------------
# The exclusivity rule CLS needs and CSR does not
# ---------------------------------------------------------------------------

def test_table_grant_and_column_grant_collide_for_cls():
    """A table grant conveys EVERY column, so it silently defeats a column grant for
    the same (Org, table, group). Live-verified: one object grant auto-created all 25
    column rows."""
    conflicts = find_exclusivity_conflicts(_resolved([
        _grant("Primary", "T2_PUBLISH", "Consumer"),
        _grant("Primary", "T2_PUBLISH", "Consumer", column="PROD_NM"),
    ]))
    assert conflicts, "a table grant beside a column grant must be refused"


def test_same_table_different_groups_is_not_a_conflict():
    """The per-Org, per-group shape of the real pattern: one group sees everything,
    another sees three columns. Refusing this would make the skill unusable."""
    assert not find_exclusivity_conflicts(_resolved([
        _grant("Primary", "T2_PUBLISH", "Analyst"),
        _grant("Primary", "T2_PUBLISH", "Consumer", column="PROD_NM"),
    ]))


def test_csr_has_no_exclusivity_rule_because_it_is_a_different_axis():
    """CSR composes with a table share rather than being defeated by one, so two
    rules on one table are a normal plan, not a conflict."""
    steps = build_csr_steps([
        {"org_name": "Primary", "table_name": "T2_PUBLISH",
         "column_name": "UNIT_PRICE_AMT", "group_name": "Analyst"},
        {"org_name": "Primary", "table_name": "T2_PUBLISH",
         "column_name": "PROD_DESC_TXT", "group_name": "Analyst"},
    ])
    assert len(steps) == 1, "one step per (Org, table); update takes one table per call"


# ---------------------------------------------------------------------------
# Per-Org keying -- groups do not cross the Org boundary
# ---------------------------------------------------------------------------

def test_both_engines_keep_orgs_separate():
    """Groups are per-Org: Primary had Analyst/Consumer, ORG1 had only
    Administrator/All/Demo Retail Group. Protecting N Orgs is N configurations, so
    neither engine may collapse two Orgs into one call."""
    share_steps = build_share_steps(_resolved([
        _grant("Primary", "T2_PUBLISH", "Analyst"),
        _grant("ORG1", "T2_PUBLISH", "Demo Retail Group"),
    ]))
    assert {s["org_name"] for s in share_steps} == {"Primary", "ORG1"}

    csr_steps = build_csr_steps([
        {"org_name": "Primary", "table_name": "T2_PUBLISH",
         "column_name": "UNIT_PRICE_AMT", "group_name": "Analyst"},
        {"org_name": "ORG1", "table_name": "T2_PUBLISH",
         "column_name": "UNIT_PRICE_AMT", "group_name": "Demo Retail Group"},
    ])
    assert {s["org_name"] for s in csr_steps} == {"Primary", "ORG1"}


# ---------------------------------------------------------------------------
# The failure modes the skill exists to explain
# ---------------------------------------------------------------------------

def test_tenant_csr_refusal_is_explained_as_publication_not_privilege():
    """Code 10038, live-verified as a tenant Org being refused CSR on an object
    published into it. The operator must be sent to check publication, NOT to hunt
    privileges they already hold."""
    message = explain_csr_error(
        '{"error":{"message":{"debug":{"code":10038,"debug":"[\\"Error Code: FORBIDDEN'
        ' Error Message: User does not have access to read/modify CSR for these '
        'tables: [g1]\\"]"}}}}', 500)
    assert message is not None
    assert "published" in message.lower()
    assert "CLS" in message, "must name the mechanism that does work per-Org"


def test_feature_flag_and_access_failures_stay_distinguishable():
    """Code 10023 is overloaded. Conflating the two sends the operator to the wrong
    place: one needs ThoughtSpot to enable a flag, the other is about publication or
    per-Org privilege."""
    feature = explain_csr_error(
        '{"error":{"code":10023,"message":"Column Security rule feature is disabled"}}', 403)
    access = explain_csr_error(
        '{"error":{"code":10023,"debug":"User does not have access to read"}}', 500)
    assert "feature-flagged" in feature and "feature-flagged" not in access
    assert "published" in access.lower(), "the publication check must come first"


def test_clear_csr_always_ships_the_required_array():
    """`column_security_rules` is a required field, so `clear_csr: true` alone is
    rejected by schema validation. The skill's revoke path depends on this."""
    payload = build_update_payload("T2_PUBLISH", {}, clear=True)
    assert payload["clear_csr"] is True
    assert payload["column_security_rules"] == []


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  PASS  {name}")
    print("\nAll ts-security-columns smoke tests passed.")
