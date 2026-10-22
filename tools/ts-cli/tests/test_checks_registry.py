"""Registry-level guards over every ts-audit rule — audit 6.1 / BL-297.

These do not prove a rule can *fire* (that is each family's trip-test file).
They pin the things that hold for all of them regardless of what each one looks
for, and they are keyed on the rule catalog itself (the legacy `ALL_CHECKS`
registries until Task 12b), so a rule added to the catalog is covered here from its
first commit without editing a list.
"""
from pathlib import Path

import pytest
import yaml

from audit_run_rule import active_rule_ids, catalog, run_rule
from ts_cli.audit.context import make_context

CATEGORIES = list(catalog().categories)

#: Every active rule once, category by category (a rule in two categories runs once).
ALL = list(dict.fromkeys(rid for cat in CATEGORIES for rid in active_rule_ids(cat)))

RULES_DIR = Path(__file__).resolve().parents[1] / "ts_cli" / "audit" / "catalog" / "rules"


def _populated():
    """A context with every field non-empty, in realistic TML shapes.

    Not designed to trip anything in particular — designed to walk the loops.
    A rule that raises on well-formed input is broken whatever it looks for.
    Built by audit_rule_fixtures (security.py), so its legacy answers are pinned for
    test_audit_pinned_findings.py too.
    """
    import audit_rule_fixtures as fx
    return fx.registry_populated_context()


@pytest.mark.parametrize("rule_id", ALL)
def test_check_survives_an_empty_context(rule_id):
    """Every rule must tolerate a context with nothing in it.

    `build_context` returns empty collections when an export fails or the user
    scopes the audit narrowly, so this is a real input, not a synthetic one.
    """
    assert isinstance(run_rule(make_context(), rule_id), list)


@pytest.mark.parametrize("rule_id", ALL)
def test_check_survives_a_populated_context(rule_id):
    """And must not raise on well-formed TML — whatever it does or does not find."""
    assert isinstance(run_rule(_populated(), rule_id), list)


def test_every_check_id_is_unique():
    """Two rules sharing an id make a finding unattributable.

    The id is what the catalog, the report and a backlog citation all key on. Read
    from the rule files themselves: the loader keeps the first of a repeated id, so
    the loaded catalog cannot show a duplicate.
    """
    seen: dict = {}
    dupes = []
    for path in sorted(RULES_DIR.glob("*.yaml")):
        for entry in yaml.safe_load(path.read_text()) or []:
            rid = entry.get("id")
            if rid in seen:
                dupes.append(f"{rid}: {seen[rid]} and {path.name}")
            seen[rid] = path.name
    assert dupes == [], f"duplicate rule ids: {dupes}"
    assert len(seen) == len(catalog().rules)


#: Rules defined but deliberately NOT active, with the reason.
#: Adding to this needs a catalog entry saying the rule is deferred.
DEFERRED = {
    "H6": "H6 duplicate sets — deferred in check-catalog.md "
          "(requires deep set comparison); retired, keeping the id allocated",
}


def test_every_defined_check_is_registered():
    """A rule that exists but is not active never runs, and says nothing.

    Found by counting the legacy checks: 51 functions were defined, 50 registered.
    The one gap is deliberate and declared; any other is a rule silently switched off.
    """
    inactive = sorted(r.id for r in catalog().rules.values() if r.status != "active")
    unregistered = [rid for rid in inactive if rid not in DEFERRED]
    assert unregistered == [], (
        f"defined but never run: {unregistered}. Make them active, delete them, or "
        f"add them to DEFERRED with a check-catalog entry saying why.")
    assert sorted(DEFERRED) == inactive, "a DEFERRED rule is active again: drop it here"


def test_registries_are_not_empty():
    """A category with no active rule contributes nothing and says nothing."""
    empty = [cat for cat in CATEGORIES if not active_rule_ids(cat)]
    assert empty == [], f"categories with no active rule: {empty}"


# ── BL-304: rules that used to exist twice now exist once ──────────────────

def test_shared_rules_are_imported_not_re_implemented():
    """The data/perf split was made by copying; six rules existed twice.

    A threshold tuned in one angle silently left the other on the old value, and
    `check_d2`/`check_p6` shipped the *same* two defects and had to be fixed twice
    (#528). Until Task 12b this read checks_perf.py and checks_data.py for re-declared
    regexes and inlined thresholds. The pairs now live in two places of a different
    kind — a code rule's shared constant and a catalog literal, or two catalog
    entries — so this asserts what the rule was for: the two halves of each pair
    still agree, and no engine module carries its own copy of a shared pattern.
    """
    import re as _re
    from ts_cli.audit.engine import tml

    cat = catalog().rules
    offenders = []

    def levels(rid):
        return [(b.op, b.value, b.severity) for b in cat[rid].bands.levels]

    # D4 / P4: one predicate (wide model, join_progressive off), one band.
    if (cat["D4"].aggregate, levels("D4")) != (cat["P4"].aggregate, levels("P4")):
        offenders.append("D4/P4: the join_progressive rule differs between the angles")
    # S9 / P14: one function-call regex over the same RLS rules.
    if cat["S9"].aggregate["where"] != cat["P14"].aggregate["where"]:
        offenders.append("S9/P14: the RLS function-call regex differs")
    # S8 / P15: P15 is S8 plus the value_casing guard, nothing else.
    if cat["P15"].aggregate["where"] != {"all": [cat["S8"].aggregate["where"],
                                                {"field": "value_casing", "truthy": False}]}:
        offenders.append("S8/P15: P15 is no longer S8 plus the value_casing guard")
    # D1 grades with the shared constants; P8 and P7 carry them as catalog bands.
    if levels("P8") != [("gt", float(tml.MAX_MODEL_COLUMNS), "MEDIUM")]:
        offenders.append("P8: the 75-column ceiling differs from D1's")
    if levels("P7") != [("gt", float(tml.JOIN_DEPTH_YELLOW), "HIGH"),
                        ("gt", float(tml.JOIN_DEPTH_GREEN), "MEDIUM")]:
        offenders.append("P7: the join-depth bands differ from D1's")

    # The shared regexes are declared once, in the helpers module.
    engine = Path(__file__).resolve().parents[1] / "ts_cli" / "audit" / "engine"
    for path in sorted(engine.glob("*.py")):
        if path.name == "tml.py":   # the one declaration
            continue
        text = path.read_text()
        for name in ("FUNC_IN_EXPR", "BRACKET_REF"):
            if _re.search(rf"\b_?{name}\s*=\s*re\.compile", text):
                offenders.append(f"engine/{path.name}: re-declares {name}")

    assert offenders == [], f"a shared rule has been copied apart: {offenders}"


def test_both_angles_still_report_a_shared_rule():
    """Collapsing the code must not collapse the reporting.

    A wide un-progressive model is legitimately both a modelling and a
    performance finding; the angles are different lenses. Only the rule is shared.
    """
    import audit_rule_fixtures as fx

    ctx = fx.registry_wide_not_progressive()
    d4, p4 = run_rule(ctx, "D4"), run_rule(ctx, "P4")
    assert len(d4) == 1 and d4[0].check_id == "D4"
    assert len(p4) == 1 and p4[0].check_id == "P4"
    assert d4[0].metric == p4[0].metric == 6
