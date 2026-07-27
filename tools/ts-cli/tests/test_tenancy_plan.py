"""Unit tests for the `ts tenancy` spec + planning engine.

The assertions encode the rules that make a topology coherent — above all the per-Org
group rule, which is the thing a hand-built environment most often gets wrong and the
reason this command exists (BL-137).
"""
from __future__ import annotations

import pytest

from ts_cli.tenancy_plan import (
    build_apply_plan,
    build_teardown_plan,
    diff_topology,
    format_plan,
    is_complete,
    spec_from_cluster,
)
from ts_cli.tenancy_spec import (
    PRIMARY_ORG,
    SpecError,
    parse_spec,
    substitute_tenant,
    unresolved_placeholders,
    validate_spec,
)


def _spec(**overrides):
    doc = {
        "marker": "m",
        "orgs": [{"name": "ORG1"}],
        "groups": {"Primary": [{"name": "Analyst"}], "ORG1": [{"name": "Retail"}]},
        "users": [{"name": "guest1", "email": "g1@x.io", "orgs": ["Primary", "ORG1"],
                   "groups": {"Primary": ["Analyst"], "ORG1": ["Retail"]}}],
    }
    doc.update(overrides)
    return parse_spec(doc)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def test_orgs_and_groups_accept_bare_string_shorthand():
    """The spec is hand-edited, so the terse form has to work."""
    spec = parse_spec({"orgs": ["ORG1"], "groups": {"ORG1": ["Retail"]}})
    assert spec["orgs"] == [{"name": "ORG1", "description": ""}]
    assert spec["groups"]["ORG1"][0]["name"] == "Retail"
    # display_name defaults to the name rather than being left empty — the API requires it.
    assert spec["groups"]["ORG1"][0]["display_name"] == "Retail"


def test_account_type_defaults_to_local_and_rejects_nonsense():
    assert _spec()["users"][0]["account_type"] == "LOCAL_USER"
    spec = parse_spec({"users": [{"name": "u", "email": "e@x.io",
                                  "account_type": "saml_user"}]})
    assert spec["users"][0]["account_type"] == "SAML_USER"
    with pytest.raises(SpecError, match="account_type"):
        parse_spec({"users": [{"name": "u", "email": "e@x.io", "account_type": "WAT"}]})


def test_a_missing_name_is_refused_rather_than_defaulted():
    with pytest.raises(SpecError):
        parse_spec({"orgs": [{"description": "no name"}]})


# ---------------------------------------------------------------------------
# Validation — the per-Org coherence rules
# ---------------------------------------------------------------------------

def test_a_coherent_spec_validates_clean():
    assert validate_spec(_spec()) == []


def test_a_group_from_ANOTHER_org_is_refused():
    """THE rule. `Analyst` in Primary says nothing about `Analyst` in ORG1 — they are
    different principals, and a manifest naming the wrong one fails at apply time with
    `Invalid group identifiers`. Catching it in the spec is the whole point."""
    spec = parse_spec({
        "orgs": [{"name": "ORG1"}],
        "groups": {"Primary": [{"name": "Analyst"}]},
        "users": [{"name": "u", "email": "e@x.io", "orgs": ["ORG1"],
                   "groups": {"ORG1": ["Analyst"]}}]})
    problems = validate_spec(spec)
    assert any("per-Org" in p and "Analyst" in p for p in problems)


def test_joining_a_group_in_an_org_you_do_not_belong_to_is_refused():
    spec = parse_spec({
        "orgs": [{"name": "ORG1"}],
        "groups": {"ORG1": [{"name": "Retail"}]},
        "users": [{"name": "u", "email": "e@x.io", "orgs": ["Primary"],
                   "groups": {"ORG1": ["Retail"]}}]})
    assert any("not a member" in p for p in validate_spec(spec))


def test_primary_must_not_be_declared_as_an_org_to_create():
    spec = parse_spec({"orgs": [{"name": PRIMARY_ORG}]})
    assert any(PRIMARY_ORG in p and "always exists" in p for p in validate_spec(spec))


def test_every_problem_is_reported_not_just_the_first():
    """A topology mistake is usually systematic; fixing them one run at a time is
    miserable."""
    spec = parse_spec({
        "orgs": [{"name": "ORG1"}, {"name": "ORG1"}],
        "users": [{"name": "u", "email": "", "orgs": ["NOPE"]}]})
    problems = validate_spec(spec)
    assert len(problems) >= 3   # duplicate org, missing email, unknown org


# ---------------------------------------------------------------------------
# Tenant templating
# ---------------------------------------------------------------------------

def test_tenant_substitution_covers_keys_values_and_case_variants():
    doc = {"orgs": [{"name": "{TENANT}"}],
           "groups": {"{TENANT}": [{"name": "{TENANT_UPPER}_A"}]},
           "users": [{"name": "u@{TENANT_LOWER}.io"}]}
    out = substitute_tenant(doc, "Acme")
    assert out["orgs"][0]["name"] == "Acme"
    assert "Acme" in out["groups"]              # mapping KEYS are substituted too
    assert out["groups"]["Acme"][0]["name"] == "ACME_A"
    assert out["users"][0]["name"] == "u@acme.io"


def test_unresolved_placeholders_are_detectable():
    """Applying an un-templated spec would create an Org literally named '{TENANT}' —
    which succeeds, and is tedious to unpick."""
    doc = {"orgs": [{"name": "{TENANT}"}]}
    assert unresolved_placeholders(doc) == ["{TENANT}"]
    assert unresolved_placeholders(substitute_tenant(doc, "Acme")) == []


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def test_apply_plan_orders_orgs_then_groups_then_users_then_members():
    """A dependency chain, not a preference: an Org must exist before a group inside it,
    and both before a user can join that group."""
    kinds = [s["kind"] for s in build_apply_plan(_spec())]
    assert kinds == sorted(kinds, key=lambda k: ["create_org", "create_group",
                                                 "create_user", "add_group_member"].index(k))
    assert kinds[0] == "create_org"
    assert kinds[-1] == "add_group_member"


def test_apply_is_idempotent_against_existing_state():
    """A half-finished run is the normal case, so re-running must be a no-op."""
    spec = _spec()
    current = {"orgs": ["ORG1"], "groups": {"Primary": ["Analyst"], "ORG1": ["Retail"]},
               "users": ["guest1"],
               "members": {"Primary": {"Analyst": ["guest1"]},
                           "ORG1": {"Retail": ["guest1"]}}}
    assert build_apply_plan(spec, current) == []


def test_apply_fills_only_the_gap():
    spec = _spec()
    current = {"orgs": ["ORG1"], "groups": {"Primary": ["Analyst"], "ORG1": []},
               "users": ["guest1"], "members": {"Primary": {"Analyst": ["guest1"]}}}
    kinds = [s["kind"] for s in build_apply_plan(spec, current)]
    assert kinds == ["create_group", "add_group_member"]


def test_only_local_users_are_marked_as_accepting_a_password():
    """A federated account authenticates against the IdP; handing it a password would look
    like a working credential and not be one."""
    spec = parse_spec({"users": [
        {"name": "local", "email": "a@x.io"},
        {"name": "fed", "email": "b@x.io", "account_type": "SAML_USER"}]})
    plan = {s["user"]: s["accepts_password"] for s in build_apply_plan(spec)
            if s["kind"] == "create_user"}
    assert plan == {"local": True, "fed": False}


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------

def test_diff_reports_what_is_missing():
    diff = diff_topology(_spec(), {"orgs": [], "groups": {}, "users": [], "members": {}})
    assert diff["missing_orgs"] == ["ORG1"]
    assert "ORG1/Retail" in diff["missing_groups"]
    assert diff["missing_users"] == ["guest1"]
    assert not is_complete(diff)


def test_diff_ignores_extra_objects_the_spec_never_mentioned():
    """A shared cluster always carries objects no spec knows about. Flagging them would
    make verify permanently red, and therefore ignored."""
    current = {"orgs": ["ORG1", "ORG_UNRELATED"],
               "groups": {"Primary": ["Analyst", "Whatever"], "ORG1": ["Retail"]},
               "users": ["guest1", "someone_else"],
               "members": {"Primary": {"Analyst": ["guest1"]},
                           "ORG1": {"Retail": ["guest1"]}}}
    assert is_complete(diff_topology(_spec(), current))


# ---------------------------------------------------------------------------
# Teardown — three independent gates
# ---------------------------------------------------------------------------

def _teardown_state():
    return {"orgs": ["ORG1"], "groups": {"ORG1": ["Retail"]}, "users": ["guest1"],
            "members": {},
            "marked": {"orgs": ["ORG1"], "groups": {"ORG1": ["Retail"]},
                       "users": ["guest1"]}}


def test_teardown_refuses_everything_when_no_org_was_named():
    """The spec alone is never sufficient authority to delete."""
    spec = parse_spec({"marker": "m", "orgs": [{"name": "ORG1"}],
                       "groups": {"ORG1": [{"name": "Retail"}]},
                       "users": [{"name": "guest1", "email": "g@x.io", "orgs": ["ORG1"]}]})
    steps, refusals = build_teardown_plan(spec, _teardown_state(), allowed_orgs=None)
    assert steps == []
    assert len(refusals) >= 3


def test_teardown_refuses_objects_without_the_marker():
    spec = parse_spec({"marker": "m", "orgs": [{"name": "ORG1"}],
                       "groups": {"ORG1": [{"name": "Retail"}]}, "users": []})
    state = _teardown_state()
    state["marked"] = {"orgs": [], "groups": {}, "users": []}
    steps, refusals = build_teardown_plan(spec, state, allowed_orgs={"ORG1"})
    assert steps == []
    assert any("not marked" in r for r in refusals)


def test_teardown_deletes_in_reverse_dependency_order_when_all_gates_pass():
    spec = parse_spec({"marker": "m", "orgs": [{"name": "ORG1"}],
                       "groups": {"ORG1": [{"name": "Retail"}]},
                       "users": [{"name": "guest1", "email": "g@x.io", "orgs": ["ORG1"]}]})
    steps, _ = build_teardown_plan(spec, _teardown_state(), allowed_orgs={"ORG1"})
    assert [s["kind"] for s in steps] == ["delete_user", "delete_group", "delete_org"]


def test_teardown_refuses_a_user_who_also_belongs_to_an_unnamed_org():
    """Deleting them would strip them from that other Org as a side effect."""
    spec = parse_spec({"marker": "m", "orgs": [{"name": "ORG1"}, {"name": "ORG2"}],
                       "groups": {},
                       "users": [{"name": "guest1", "email": "g@x.io",
                                  "orgs": ["ORG1", "ORG2"]}]})
    state = {"orgs": ["ORG1", "ORG2"], "groups": {}, "users": ["guest1"], "members": {},
             "marked": {"orgs": ["ORG1", "ORG2"], "groups": {}, "users": ["guest1"]}}
    steps, refusals = build_teardown_plan(spec, state, allowed_orgs={"ORG1"})
    assert not any(s["kind"] == "delete_user" for s in steps)
    assert any("also belongs to ORG2" in r for r in refusals)


def test_teardown_never_deletes_primary():
    spec = parse_spec({"marker": "m", "orgs": [{"name": PRIMARY_ORG}]})
    state = {"orgs": [PRIMARY_ORG], "groups": {}, "users": [], "members": {},
             "marked": {"orgs": [PRIMARY_ORG], "groups": {}, "users": []}}
    steps, refusals = build_teardown_plan(spec, state, allowed_orgs={PRIMARY_ORG})
    assert steps == []
    assert any("never deleted" in r for r in refusals)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def test_export_excludes_primary_from_orgs_but_keeps_its_groups():
    """Primary is never created, but the reference topology puts real groups in it."""
    doc = spec_from_cluster(
        orgs=[{"name": PRIMARY_ORG}, {"name": "ORG1"}],
        groups_by_org={PRIMARY_ORG: [{"name": "Analyst"}], "ORG1": [{"name": "Retail"}]},
        users=[{"name": "guest1", "email": "g@x.io", "orgs": ["Primary", "ORG1"],
                "groups": {"Primary": ["Analyst"]}}])
    assert [o["name"] for o in doc["orgs"]] == ["ORG1"]
    assert PRIMARY_ORG in doc["groups"]
    # And the captured document must survive a round trip through the parser.
    assert validate_spec(parse_spec(doc)) == []


def test_format_plan_marks_deletions_loudly():
    steps = [{"kind": "create_org", "org": "ORG1"},
             {"kind": "delete_org", "org": "ORG1"}]
    lines = format_plan(steps)
    assert lines[0].startswith("create org")
    assert "DELETE" in lines[1]


# ---------------------------------------------------------------------------
# Regression: per-Org attribution when a search returns cross-Org rows
# ---------------------------------------------------------------------------

def test_groups_are_attributed_to_their_own_org():
    """Live-observed bug: a Primary-scoped `groups/search` returns groups from EVERY Org,
    so Primary's list arrived carrying each tenant's `Demo Retail Group` — and a user was
    consequently recorded as belonging to a Primary group of that name, which does not
    exist. That is exactly the per-Org attribution error this command exists to prevent,
    so the row's own `orgs` field is the authority, not which client fetched it.
    """
    from ts_cli.commands.tenancy import _groups_in_org

    rows = [{"name": "Analyst", "orgs": [{"name": "Primary"}]},
            {"name": "Demo Retail Group", "orgs": [{"name": "ORG1"}]},
            {"name": "Demo Retail Group", "orgs": [{"name": "ORG2"}]}]
    assert [g["name"] for g in _groups_in_org(rows, "Primary")] == ["Analyst"]
    assert [g["name"] for g in _groups_in_org(rows, "ORG1")] == ["Demo Retail Group"]


def test_rows_without_an_orgs_field_are_kept():
    """A build that omits `orgs` should degrade to the old behaviour, not silently drop
    every group and report an empty Org."""
    from ts_cli.commands.tenancy import _groups_in_org

    assert len(_groups_in_org([{"name": "Analyst"}], "Primary")) == 1


def test_the_shipped_reference_fixture_is_valid():
    """The captured topology must round-trip through the parser, or the thing we tell
    people to run cannot be run."""
    from pathlib import Path
    import yaml

    path = (Path(__file__).resolve().parents[2] / "fixtures" / "tenancy-reference.yaml")
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    spec = parse_spec(doc)
    assert validate_spec(spec) == []
    # The discriminating pair the column-security verification depends on.
    users = {u["name"]: u for u in spec["users"]}
    # The discriminating pair the column-security verification depends on: Analyst and
    # Consumer exist only in Primary, so guest1/guest4 differ there and NOT in the tenants.
    assert "Analyst" in users["guest1"]["groups"]["Primary"]
    assert "Consumer" in users["guest4"]["groups"]["Primary"]
    assert "Analyst" not in spec["groups"].get("ORG1", [])
