"""Smoke test for the ts-setup-tenancy skill.

The skill orchestrates existing commands rather than adding API surface, so what has to
hold is that the artefacts it hands to those commands are sound: the shipped topology
specs parse and validate, the scenarios are internally consistent, and the discriminating
users the environment exists to provide actually discriminate.

That last one is the substantive check. A test environment whose two users cannot be told
apart proves nothing, and a scenario doc claiming otherwise would send someone down the
same blind alley a verification round in this programme already went down.

No live ThoughtSpot connection required.
"""
import re
import sys
from pathlib import Path

import yaml

# Test the ts_cli in THIS checkout, not whatever happens to be installed.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ts-cli"))

from ts_cli.tenancy_spec import parse_spec, validate_spec  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SKILL = REPO / "agents" / "cli" / "ts-setup-tenancy"
REFERENCE = REPO / "tools" / "fixtures" / "tenancy-reference.yaml"

SCENARIOS = ("topology", "per-org", "published", "mixed")


def test_the_reference_topology_validates():
    """The skill's default topology must be applicable, or Step 7 fails for everyone."""
    spec = parse_spec(yaml.safe_load(REFERENCE.read_text(encoding="utf-8")))
    assert validate_spec(spec) == []
    assert spec["orgs"], "a multi-tenancy environment needs at least one tenant Org"


def test_the_reference_topology_has_a_discriminating_pair_in_primary():
    """The whole point of the environment: two users who differ, so a security test can
    show one seeing a column and the other not. If they cannot be told apart, every
    observation made against them is worthless."""
    spec = parse_spec(yaml.safe_load(REFERENCE.read_text(encoding="utf-8")))
    primary = {u["name"]: set(u["groups"].get("Primary", [])) for u in spec["users"]
               if "Primary" in u["orgs"]}
    pairs = [(a, b) for a in primary for b in primary
             if a < b and primary[a] != primary[b] and (primary[a] - primary[b])]
    assert pairs, "no two Primary users have differing group membership"


def test_tenant_orgs_do_not_discriminate_and_the_docs_say_so():
    """In the tenant Orgs both guests share one group, so a tenant-side check is
    'is it visible at all', never 'who sees it'. A reader who assumes otherwise will
    misread a negative result as a finding — which has already happened once."""
    spec = parse_spec(yaml.safe_load(REFERENCE.read_text(encoding="utf-8")))
    tenant_orgs = [o["name"] for o in spec["orgs"]]

    for org in tenant_orgs:
        memberships = {u["name"]: tuple(sorted(u["groups"].get(org, [])))
                       for u in spec["users"] if org in u["orgs"]}
        distinct = {m for m in memberships.values() if m}
        if len(memberships) > 1 and len(distinct) <= 1:
            break
    else:
        return   # a topology where tenants DO discriminate needs no warning

    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "do NOT discriminate" in text or "does NOT discriminate" in text, \
        "the tenant Orgs cannot tell the test users apart, and SKILL.md must say so"


def test_every_scenario_is_documented_in_both_places():
    """A scenario named in the skill but absent from the reference (or vice versa) means
    someone picks an option with no explanation of what it builds."""
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    ref = (SKILL / "references" / "scenarios.md").read_text(encoding="utf-8")
    for scenario in SCENARIOS:
        assert scenario in skill, f"{scenario} missing from SKILL.md"
        assert scenario in ref, f"{scenario} missing from references/scenarios.md"


def test_the_scenarios_reference_maps_each_one_to_a_migration_phase():
    """The scenarios exist because the programme has a before state and an after state.
    If the reference stops explaining which is which, the option list becomes arbitrary."""
    ref = (SKILL / "references" / "scenarios.md").read_text(encoding="utf-8")
    assert re.search(r"per-org.*PRE-migration|PRE-migration.*per-org", ref, re.S | re.I)
    assert re.search(r"published.*POST-migration|POST-migration.*published", ref,
                     re.S | re.I)
    assert "mixed" in ref and "transition" in ref.lower()


def test_the_skill_separates_test_setup_from_production():
    """These environments are disposable and opinionated; onboarding a real client is
    neither. Conflating them is how someone tears down a live tenant."""
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "Production is different" in text
    assert "BL-143" in text, "must point at where production onboarding actually lives"


def test_the_skill_never_asks_for_a_password_in_conversation():
    """`.claude/rules/security.md`: a credential must never appear in a message. The skill
    directs the operator to export it in their own terminal and passes the variable NAME."""
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "--password-env" in text
    assert "never taken in conversation" in text or "never a flag" in text
    # No prompt that would invite a secret into the transcript.
    assert not re.search(r"(enter|paste|provide|type).{0,20}(password|secret|token)",
                         text, re.I)


def test_teardown_is_documented_with_all_three_gates():
    """Refusals are the rail working. A reader who does not know the three gates will read
    a refusal as a bug and reach for a bigger hammer."""
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "--dry-run" in text and "--yes" in text and "--org" in text
    assert "marker" in text.lower()
    assert "Primary is never deleted" in text


def test_the_skill_hands_off_rather_than_reimplementing():
    """It orchestrates shipped skills. If it started duplicating them, the two would
    drift and the environment would stop matching what the skills actually do."""
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    for target in ("/ts-publish-orgs", "/ts-object-model-alias", "/ts-security-columns",
                   "/ts-load-source-data"):
        assert target in text, f"{target} should be handed off to, not reimplemented"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  PASS  {name}")
    print("\nAll ts-setup-tenancy smoke tests passed.")
