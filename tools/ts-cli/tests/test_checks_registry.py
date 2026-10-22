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


def test_every_inactive_rule_is_retired_on_purpose_and_listed():
    """A rule that exists but does not run says nothing, so not running must be
    deliberate and visible.

    The catalog's own `status: retired` is the declaration (there is no second,
    hand-kept list to update): every rule that is not active must be retired, carry a
    description saying why, and appear under "Retired rules" in the generated
    check-catalog.md — never be deleted (the history gate fails that). Found by counting
    the legacy checks: 51 functions were defined, 50 registered, and the one gap (H6) is
    deliberate.
    """
    inactive = [r for r in catalog().rules.values() if r.status != "active"]
    assert all(r.status == "retired" for r in inactive), \
        [f"{r.id}: {r.status}" for r in inactive if r.status != "retired"]
    undocumented = [r.id for r in inactive if not (r.description or "").strip()]
    assert undocumented == [], f"retired without saying why: {undocumented}"
    from ts_cli.audit.generate import catalog_markdown
    doc = catalog_markdown(catalog())
    retired_section = doc[doc.index("Retired rules"):] if "Retired rules" in doc else ""
    missing = [r.id for r in inactive if f"| {r.id} |" not in retired_section]
    assert missing == [], f"retired but not listed under Retired rules: {missing}"


def test_selecting_a_category_runs_its_active_rules():
    """`--angles X` runs exactly the catalog's active rules in category X, under each
    profile (derived from the catalog — adding or retiring a rule moves both sides)."""
    from ts_cli.audit.catalog_model import profile_override
    from ts_cli.audit.engine.run import selected_rules
    cat = catalog()
    for profile in cat.profiles:
        for category in CATEGORIES:
            expected = [r.id for r in cat.rules.values() if category in r.categories
                        and r.status == "active"
                        and (profile_override(r, profile).get("status") or "active") == "active"]
            got = [r.id for r in selected_rules(cat, [category], profile)]
            assert sorted(got) == sorted(expected), (profile, category)


def test_registries_are_not_empty():
    """A category with no active rule contributes nothing and says nothing."""
    empty = [cat for cat in CATEGORIES if not active_rule_ids(cat)]
    assert empty == [], f"categories with no active rule: {empty}"


# ── BL-304: rules that used to exist twice now exist once ──────────────────

def test_shared_rule_pairs_stay_in_step():
    """The data/perf split was made by copying; six rules existed twice.

    A threshold tuned in one angle silently left the other on the old value, and
    `check_d2`/`check_p6` shipped the *same* two defects and had to be fixed twice
    (#528). Until Task 12b this read checks_perf.py and checks_data.py for re-declared
    regexes and inlined thresholds. The pairs now live as catalog entries (and, for
    D1, a code rule's shared constants in engine/tml.py), so this holds each pair to
    the same logic — scope, data, aggregation and bands — holds the `legacy_threshold`
    literals that restate a shared number to that number, and checks that the shared
    bracketed-reference pattern is declared once in the audit code.
    """
    import re as _re
    from ts_cli.audit.engine import tml

    cat = catalog().rules
    offenders = []

    def levels(rid):
        return [(b.op, b.value, b.severity) for b in cat[rid].bands.levels]

    def logic(rid):
        r = cat[rid]
        return (r.scope, r.requires, r.uses, r.implementation, r.aggregate)

    # D4 / P4: one predicate (wide model, join_progressive off), one band.
    if (logic("D4"), levels("D4")) != (logic("P4"), levels("P4")):
        offenders.append("D4/P4: the join_progressive rule differs between the angles")
    # S9 / P14: the same walk over RLS rules with one function-call regex.
    if logic("S9") != logic("P14"):
        offenders.append("S9/P14: the RLS function-call rule differs")
    # S8 / P15: P15 is S8 plus the value_casing guard, nothing else.
    s8, p15 = logic("S8"), logic("P15")
    if s8[:4] != p15[:4] or s8[4]["mode"] != p15[4]["mode"] or \
            p15[4]["where"] != {"all": [s8[4]["where"],
                                        {"field": "value_casing", "truthy": False}]}:
        offenders.append("S8/P15: P15 is no longer S8 plus the value_casing guard")
    # D1 grades with the shared constants; P8 and P7 carry them as catalog bands.
    if levels("P8") != [("gt", float(tml.MAX_MODEL_COLUMNS), "MEDIUM")]:
        offenders.append("P8: the 75-column ceiling differs from D1's")
    if levels("P7") != [("gt", float(tml.JOIN_DEPTH_YELLOW), "HIGH"),
                        ("gt", float(tml.JOIN_DEPTH_GREEN), "MEDIUM")]:
        offenders.append("P7: the join-depth bands differ from D1's")
    # The legacy threshold payloads restate those numbers: they must say the same.
    if cat["D4"].legacy_threshold != {"min_tables_for_flag": levels("D4")[0][1]}:
        offenders.append("D4: legacy_threshold disagrees with its band")
    if cat["P8"].legacy_threshold != {"max": tml.MAX_MODEL_COLUMNS}:
        offenders.append("P8: legacy_threshold disagrees with the 75-column ceiling")
    if cat["P7"].legacy_threshold != {"green": tml.JOIN_DEPTH_GREEN,
                                      "yellow": tml.JOIN_DEPTH_YELLOW}:
        offenders.append("P7: legacy_threshold disagrees with the join-depth bands")

    # The bracketed-reference pattern is declared once (engine/tml.py BRACKET_REF): a
    # copy under any name is found by its pattern text, not its name.
    audit = Path(__file__).resolve().parents[1] / "ts_cli" / "audit"
    literal = _re.compile(r"""re\.compile\(\s*r?["']\\\[\(\[\^\\\]\]\+\)\\\]["']""")
    declaring = [str(path.relative_to(audit)) for path in sorted(audit.rglob("*.py"))
                 if literal.search(path.read_text())]
    assert "engine/tml.py" in declaring, "the scan no longer recognises the declaration"
    offenders += [f"{p}: re-declares the BRACKET_REF pattern" for p in declaring
                  if p != "engine/tml.py"]

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
