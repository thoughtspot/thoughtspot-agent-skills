"""The catalog against the legacy checks' own answers, after the legacy checks are gone.

Task 12b deleted `ts_cli/audit/checks_*.py`. Before it did, `pin_legacy_findings.py`
(commit 1ddb3185; removed with the legacy checks, since it imported them) ran every
legacy check over every committed audit input (`AI_INPUTS`, `P_INPUTS`,
`S_INPUTS`, `D_INPUTS`, `H_INPUTS` in `audit_rule_fixtures`) under both profiles and
pinned what each check reported in `audit_rule_fixtures/legacy_findings.json.gz`.
These tests hold the catalog to those answers with the same strict comparator the
equivalence gate used (`equivalence.compare_findings`: exact types, `None` vs `""`,
key order, multiset of findings).

They replace the legacy-vs-catalog equivalence tests, and they are the regression net
for the 13 rules the 351-Model snapshot never exercises (D4, D5, D9, H9, P1, P4, P13,
P14, P15, S4, S5, S9, S10): every one of those fires in these inputs.

**Scope: the 51 pinned rules only.** The frozen set is the pin file's own `rules` list
(`audit_pinned.PINNED_RULE_IDS` mirrors it; a test fails if they differ). A rule added
to the catalog after the pin is not compared here; its `fires`/`silent` examples
(test_audit_rule_examples.py) are its net.

**Status counts per profile.** Every pinned rule is compared whatever its status: a
rule that is not active under a profile (retired at base, or switched off by that
profile's `status` override) reports nothing there, so its pin for that profile must
be []. Only the pinned rules ACTIVE under a profile must fire somewhere in their
category's inputs.

**Changing a pinned rule, or an input builder, on purpose** — a threshold, severity or
wording edit, a defect fixed (one of the strict xfails), a `status` change at base or
under a profile, a builder reshaped — fails here until the pin moves with it:

    PYTHONPATH=tools/ts-cli python tools/ts-cli/tests/repin_findings.py --rule P8 [--dry-run]
    PYTHONPATH=tools/ts-cli python tools/ts-cli/tests/repin_findings.py --input <name>

It rewrites only the named entries from the CURRENT catalog (a rule not active under a
profile pins to [] there), deterministically, and prints the before/after of every
entry it changes. Nothing leaves the pin silently: a rule leaves the frozen set only
through `--drop-rule <id>` (refused while the rule is active under any profile: retire
it first), a stale input only through `--drop-input <name>`, each
printing every entry it removes, and the write refuses any entry outside the file's
frozen sets. The gzip shows in a PR only as
"Binary files differ", so that printed diff is the review artefact: paste it into the
PR description. (The pin as plain sorted, indented JSON would be 3.6 MB, too large to
review as a diff, so it stays gzipped at 66 KB.) Re-pinning an entry pinned as
"RAISES" replaces the legacy raise with what the catalog reports; update
LEGACY_RAISES / ENGINE_RAISES below in the same change.
"""
from __future__ import annotations

import copy

import pytest

import audit_pinned as ap
from audit_run_rule import catalog, findings_by_rule
from ts_cli.audit.engine.run import selected_rules
from ts_cli.audit.equivalence import compare_findings

CATEGORIES = ["A", "D", "H", "P", "S"]
PROFILES = ap.PROFILES
OWN_INPUTS = ap.OWN_INPUTS

#: (input, rule) pairs on which the legacy check RAISED (under both profiles). What
#: the catalog reports there has no legacy answer to compare with. A None name or a
#: list-valued `properties` aborts the legacy regex and lookup code.
LEGACY_RAISES = {
    "ai_model_name_none": {"H10"},
    "tml_value_shapes": {"H3", "P2", "P9", "P18"},
    "perf_names_none": {"A5", "A6", "H1", "H10", "S1", "S2", "S3", "S5"},
    "sec_names_none": {"H10"},
    "data_names_none": {"A5", "A6", "H1", "H10", "P9", "S1", "S2", "S3", "S5"},
    "data_single_model_malformed_column": {"H3", "P2", "P9", "P18"},
}

#: (input, rule) pairs on which the CATALOG raises too: A5 (a code rule) reads the
#: column names as the legacy A5 did, and a None name raises in both. Pinned so that a
#: fix shows up here; a pinned rule raising anywhere else fails.
ENGINE_RAISES = {("perf_names_none", "A5"), ("data_names_none", "A5")}


def _pinned() -> dict:
    return ap.pinned()


def _committed_inputs() -> dict:
    return ap.committed_inputs()


def _legacy(name: str, profile: str, rule_id: str):
    """The pinned legacy findings ([] when the check found nothing), or "RAISES"."""
    return ap.entry(_pinned(), name, profile, rule_id)


def _legacy_category(name: str, profile: str, category: str) -> list:
    out = []
    for rule_id in ap.pinned_rules(category):
        found = _legacy(name, profile, rule_id)
        assert found != ap.RAISES, f"{name}: the legacy {rule_id} raised; nothing to probe"
        out += found
    return out


def test_the_pinned_inputs_are_the_committed_inputs():
    """An input added or renamed since the pin has no legacy answer: say so, loudly
    (repin_findings.py --input <name> pins a new one)."""
    assert sorted(_committed_inputs()) == _pinned()["inputs"]
    assert _pinned()["profiles"] == PROFILES


def test_the_pinned_rule_set_is_frozen_by_the_pin_file():
    """The frozen rule set is data: the pin file's `rules` list. The code's mirror must
    equal it (so neither side shrinks alone), the file holds no entry outside its own
    sets, and every pinned id is in the catalog, active or retired (a rule id is never
    deleted; a retired one pins to [] on purpose)."""
    doc = _pinned()
    assert tuple(doc["rules"]) == ap.PINNED_RULE_IDS
    assert len(set(doc["rules"])) == len(doc["rules"])
    assert ap.strays(doc) == []
    missing = [r for r in doc["rules"] if r not in catalog().rules]
    assert missing == [], f"pinned rule ids not in the catalog: {missing}"


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("category", CATEGORIES)
def test_catalog_reproduces_the_pinned_legacy_findings(category, profile):
    """Every committed input, every pinned rule of the category: the catalog's findings
    are the pinned ones, exactly. The engine runs the whole category (as `ts audit run`
    does) on every input — including those a legacy check raised on — and a pinned rule
    raises only where ENGINE_RAISES says (where the legacy check raised as well)."""
    rules = ap.pinned_rules(category)
    differing, raised = {}, set()
    for name, build in _committed_inputs().items():
        got, failed = ap.catalog_by_rule(build, category, profile)
        raised |= {(name, rule_id) for rule_id in failed if rule_id in rules}
        for rule_id in rules:
            legacy = _legacy(name, profile, rule_id)
            if legacy == ap.RAISES or rule_id in failed:
                continue
            res = compare_findings(legacy, got.get(rule_id, []))
            if not res["identical"]:
                differing[(name, rule_id)] = res
    assert differing == {}, {k: differing[k] for k in list(differing)[:5]}
    assert raised == {(n, r) for n, r in ENGINE_RAISES if r in rules}
    assert all(_legacy(n, profile, r) == ap.RAISES for n, r in raised)


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("category", CATEGORIES)
def test_every_rule_fires_in_its_own_categorys_inputs(category, profile):
    """Not vacuous: each pinned rule ACTIVE under this profile (effective status) has
    pinned findings in its category's own inputs, so the comparison above exercises
    every one, not just the silent case. A rule not active under the profile is pinned
    to [] there instead, which the comparison holds it to."""
    fired = dict.fromkeys(ap.active_pinned_rules(category, profile), 0)
    for name in OWN_INPUTS[category]:
        for rule_id in fired:
            legacy = _legacy(name, profile, rule_id)
            fired[rule_id] += 0 if legacy == ap.RAISES else len(legacy)
    assert all(fired.values()), fired


@pytest.mark.parametrize("profile", PROFILES)
def test_the_rules_the_snapshot_never_exercises_are_pinned_firing(profile):
    """The 13 rules the 351-Model snapshot gave no finding for rest on these inputs
    (each one still active under the profile)."""
    unexercised = ["D4", "D5", "D9", "H9", "P1", "P4", "P13", "P14", "P15", "S4", "S5",
                   "S9", "S10"]
    # Effective status only, never pin membership: a rule dropped from the pin while
    # still active must fail here, not be exempted (12b re-review N5).
    active = {r.id for r in selected_rules(catalog(), CATEGORIES, profile)}
    counts = {r: 0 for r in unexercised if r in active}
    for profiles in _pinned()["findings"].values():
        for rule_id in counts:
            found = profiles.get(profile, {}).get(rule_id, [])
            counts[rule_id] += 0 if found == ap.RAISES else len(found)
    assert all(counts.values()), counts


def test_the_legacy_raises_are_the_known_ones():
    pinned = {}
    for name, profiles in _pinned()["findings"].items():
        for profile, rules in profiles.items():
            raised = {r for r, v in rules.items() if v == ap.RAISES}
            if raised:
                pinned.setdefault(name, {})[profile] = raised
    assert pinned == {name: {p: rules for p in PROFILES} for name, rules in LEGACY_RAISES.items()}


# ── edge cases the equivalence gate probed, now probed against the pinned answers ──
# Each probe must hold on the legacy findings (the input exercises the case) and the
# catalog's findings must equal them.

A_PROBES = [
    # a nameless measure: legacy A6 lists it as "?"
    ("tml_unnamed_measure", lambda f: f["check_id"] == "A6" and f["detail"].endswith(": ?")),
    # `name: None` / `guid: None` reach the finding as None, not ""
    ("ai_model_name_none", lambda f: f["object_name"] is None),
    ("ai_document_guid_none", lambda f: f["object_guid"] is None),
]


P_PROBES = [
    # `name: None` / `guid: None` reach the finding as None, not ""
    ("perf_names_none", lambda f: f["object_name"] is None and f["object_guid"] is None),
    ("perf_names_none", lambda f: f["check_id"] == "P1" and f["object_guid"] is None),
    # absent keys reach it as ""
    ("perf_names_absent", lambda f: f["object_name"] == "" and f["object_guid"] == ""),
    # legacy P17 keys its graph by name: one finding per name, later definition wins
    ("perf_duplicate_formula_names",
     lambda f: f["check_id"] == "P17" and f["object_name"] == "Z" and f["metric"] == 4),
    ("perf_unnamed_formulas_with_references",
     lambda f: f["check_id"] == "P17" and f["object_name"] == ""),
]


S_PROBES = [
    # `name: None` / `guid: None` reach the finding as None, not ""
    ("sec_names_none", lambda f: f["check_id"] == "S4" and f["object_name"] is None
     and f["object_guid"] is None),
    ("sec_names_none", lambda f: f["check_id"] == "S9" and f["object_name"] is None
     and f["object_guid"] is None),
    ("sec_names_none", lambda f: f["check_id"] == "S8" and f["object_guid"] is None),
    # absent keys reach it as ""
    ("sec_names_absent", lambda f: f["check_id"] == "S10" and f["object_name"] == ""
     and f["object_guid"] == ""),
    ("sec_names_absent", lambda f: f["check_id"] == "S9" and f["object_name"] == ""),
    # S2: the owning table's RLS through "" keys, overriding aliases and absent tables
    ("sec_owning_table_edges", lambda f: f["check_id"] == "S2"
     and f["object_name"] == "email_no_id" and f["severity"] == "INFO"),
    ("sec_owning_table_edges", lambda f: f["check_id"] == "S2"
     and f["object_name"] == "email_x" and f["severity"] == "HIGH"),
    ("sec_owning_table_edges", lambda f: f["check_id"] == "S2"
     and f["object_name"] == "email_y" and f["severity"] == "INFO"),
    # S3: the masking blob is case-insensitive on both sides
    ("sec_masking_edges", lambda f: f["check_id"] == "S3" and f["object_name"] == "home_phone"),
    # S5: `token` is HIGH, the other words CRITICAL, matched in any case
    ("credential_names", lambda f: f["check_id"] == "S5" and f["object_name"] == "TOKEN"
     and f["severity"] == "HIGH"),
    # S9: the detail quotes the first 80 characters
    ("sec_long_rls_expression", lambda f: f["check_id"] == "S9"
     and len(f["detail"]) == len("Function in RLS expression prevents filter pushdown: ") + 80),
]


D_PROBES = [
    # `name: None` / `guid: None` reach the finding as None, not ""
    ("data_names_none", lambda f: f["check_id"] == "D1" and f["object_name"] is None
     and f["object_guid"] is None),
    ("data_names_none", lambda f: f["check_id"] == "D10" and f["object_name"] is None
     and f["detail"] == "Zero-column bridge table 'None'"),
    ("data_names_none", lambda f: f["check_id"] == "D7" and f["object_name"] == "None / Twin"
     and f["object_guid"] is None),
    ("data_names_none", lambda f: f["check_id"] == "D8" and f["object_name"] == "...None"
     and f["object_guid"] is None),
    ("data_names_none", lambda f: f["check_id"] == "D12" and f["object_name"] is None
     and f["object_guid"] == ""),
    # absent keys reach it as ""
    ("data_names_absent", lambda f: f["check_id"] == "D9" and f["object_name"] == ""
     and f["object_guid"] == ""),
    ("data_names_absent", lambda f: f["check_id"] == "D8" and f["object_name"] == "..."),
    # D1: one finding per measure, each with its own legacy threshold
    ("data_names_absent", lambda f: f["check_id"] == "D1"
     and f["threshold"] == {"green": 10, "yellow": 15} and f["metric"] == 16),
    # D7: the MEDIUM finding carries a threshold, the HIGH one none
    ("models_overlapping_tables", lambda f: f["check_id"] == "D7" and f["severity"] == "MEDIUM"
     and f["threshold"] == {"high_overlap": 0.5}),
    ("data_models_identical_tables", lambda f: f["check_id"] == "D7" and f["threshold"] is None),
    # D7: an explicit `fqn: None` is an element; an absent fqn falls back to the name
    ("data_models_overlap_edges", lambda f: f["check_id"] == "D7"
     and f["object_name"] == "NoneFqn / NoneToo"),
    ("data_models_overlap_edges", lambda f: f["check_id"] == "D7"
     and f["object_name"] == "ByName / ByFqn"),
    # D8: an absent stripe groups with an explicit "", never with None
    ("data_metadata_edges", lambda f: f["check_id"] == "D8" and f["object_name"] == "...LINES"),
    # D10 / D11 look a table up by name, not alias (BL-305, kept)
    ("data_model_aliased_fact", lambda f: f["check_id"] == "D10" and f["object_name"] == "ORDERS"),
    ("data_model_aliased_fact", lambda f: f["check_id"] == "D11" and f["severity"] == "INFO"
     and f["detail"] == "ONE_TO_MANY join 'SHIPMENTS' -> 'O'"),
    # D11 words a MANY_TO_MANY INFO finding "ONE_TO_MANY" (kept)
    ("data_fanout_many_to_many_dimension", lambda f: f["check_id"] == "D11"
     and f["detail"].startswith("ONE_TO_MANY join")),
    # D12: a later column overwrites an earlier one's type within a Model
    ("data_models_column_type_edges", lambda f: f["check_id"] == "D12"
     and f["detail"].endswith("A=MEASURE, B=ATTRIBUTE")),
    # D7 / D8 compare as Python does: 1 and True are one table, 0 and False one schema
    ("overlap_scalars_1_True", lambda f: f["check_id"] == "D7" and f["severity"] == "HIGH"),
    ("duplicate_schemaStripe_0_False", lambda f: f["check_id"] == "D8" and f["metric"] == 2),
]


H_PROBES = [
    # H1: one finding per Model, the first five names, the legacy threshold dict
    ("human_h1_all_anti_patterns", lambda f: f["check_id"] == "H1"
     and f["detail"] == "7/7 columns have anti-pattern names (100%): col1, col2, val, "
     "tmp_a, 9b" and f["threshold"] == {"max_pct": 10} and f["metric"] == 100.0),
    # H2: one finding per Model, three issues listed, "; "-joined
    ("human_h2_many_issues", lambda f: f["check_id"] == "H2" and f["metric"] == 4
     and f["detail"] == "4 description quality issues: 'C0' too short (5 chars); "
     "'C1' too short (4 chars); '' uses boilerplate pattern"),
    # H3 looks a table up by NAME: a hidden column of an aliased table is reported
    ("human_h3_join_edges", lambda f: f["check_id"] == "H3" and f["object_name"] == "K1"),
    # H4: a Model whose only dependents are Sets is an orphan
    ("human_h4_dependent_shapes", lambda f: f["check_id"] == "H4"
     and f["object_guid"] == "m-sets"),
    # H5: a Set consumed by a Set is not an orphan; that consumer, looked up, is
    ("human_h5_set_shapes", lambda f: f["check_id"] == "H5" and f["object_guid"] == "s2"),
    # H5: a failed consumer lookup is silent; a clean empty one reports
    ("built_set_without_consumers", lambda f: f["check_id"] == "H5"
     and f["object_type"] == "set" and f["object_guid"] == "s1"),
    # H7: one finding per table reference, the same reference twice included
    ("human_h7_reference_shapes", lambda f: f["check_id"] == "H7"
     and f["object_name"] == "Twice"),
    # H8: object named by a count, no guid, metric the size, three answers listed
    ("human_h8_group_shapes", lambda f: f["check_id"] == "H8"
     and f["object_name"] == "shared in 4 answers" and f["object_guid"] == ""
     and f["metric"] == 4 and f["detail"].endswith(": Q1, Q2, Q3")),
    ("human_h8_group_shapes", lambda f: f["check_id"] == "H8" and f["detail"]
     == "Formula duplicated in 2 answers but not in model: Q0, Q0"),
    # H9: a blank Answer expression matches a blank Model one; the later Model wins
    ("human_h9_match_shapes", lambda f: f["check_id"] == "H9"
     and f["detail"] == "Answer formula 'NoExpr' duplicates model formula 'Empty'"),
    ("human_h9_match_shapes", lambda f: f["check_id"] == "H9"
     and f["detail"] == "Answer formula '' duplicates model formula 'Second'"),
    # H10: Model and column findings; a description cut at 60 characters
    ("human_h10_name_shapes", lambda f: f["check_id"] == "H10" and f["object_type"] == "model"
     and f["detail"] == "Model name matches stale pattern: 'Sales (Backup)'"),
    ("human_h10_name_shapes", lambda f: f["check_id"] == "H10" and f["object_name"] == "Plain"
     and f["detail"] == "Column description matches stale pattern: 'Deprecated: this "
     "column will be removed once the new ledger '"),
    # raw None names and guids reach the finding as None
    ("human_names_none", lambda f: f["check_id"] == "H4" and f["object_guid"] is None),
    ("human_names_none", lambda f: f["check_id"] == "H5" and f["object_name"] is None
     and f["object_guid"] is None),
    ("human_names_none", lambda f: f["check_id"] == "H7" and f["object_name"] is None),
    ("human_names_none", lambda f: f["check_id"] == "H9" and f["object_name"] is None
     and f["detail"] == "Answer formula 'None' duplicates model formula 'None'"),
]


PROBES = [("A", *p) for p in A_PROBES] + [("P", *p) for p in P_PROBES] + \
    [("S", *p) for p in S_PROBES] + [("D", *p) for p in D_PROBES] + \
    [("H", *p) for p in H_PROBES]


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("category,fixture,probe", PROBES,
                         ids=[f"{c}-{f}-{i}" for i, (c, f, _) in enumerate(PROBES)])
def test_catalog_keeps_legacy_names_guids_and_edges(category, fixture, probe, profile):
    old = _legacy_category(fixture, profile, category)
    assert any(probe(f) for f in old), "the input must exercise the case"
    build = _committed_inputs()[fixture]
    got = findings_by_rule(build(), category, profile)
    new = [f.to_dict() for rule_id in ap.pinned_rules(category) for f in got.get(rule_id, [])]
    assert compare_findings(old, new)["identical"] is True


# ── repin_findings.py: the supported way to move the pin ────────────────────
# Every test here works on a temporary copy of the pin, with the cached document
# cleared before and after, so none depends on test order or on the live catalog.

@pytest.fixture
def pin_copy(tmp_path, monkeypatch):
    import shutil
    copy = tmp_path / "pin.json.gz"
    shutil.copy(ap.PINNED, copy)
    ap.pinned.cache_clear()
    monkeypatch.setattr(ap, "PINNED", copy)
    yield copy
    ap.pinned.cache_clear()


def _pinned_entries(doc, exclude=()):
    return {(n, p, r): v for n, ps in doc["findings"].items() for p, rs in ps.items()
            for r, v in rs.items() if r not in exclude}


def _a_pinned_finding(doc):
    """`(input, profile, rule id)` of the first pinned entry holding at least one
    finding — chosen from the pin itself, so these helper tests never depend on what
    any one shipped rule reports (rule-authoring.md uses P8 and D3 as its examples)."""
    return next(k for k, v in sorted(_pinned_entries(doc).items())
                if v != ap.RAISES and v)


def test_repin_refuses_unknown_names(pin_copy, capsys):
    import repin_findings
    original = pin_copy.read_bytes()
    committed = next(iter(ap.committed_inputs()))
    assert repin_findings.main(["--rule", "Z99"]) == 1
    assert repin_findings.main(["--input", "no_such_input"]) == 1
    assert repin_findings.main(["--drop-rule", "Z99"]) == 1
    assert repin_findings.main(["--drop-input", committed]) == 1  # still committed
    assert repin_findings.main([]) == 1
    err = capsys.readouterr().err
    assert "frozen rule set" in err and "unknown input" in err and "still a committed" in err
    assert pin_copy.read_bytes() == original


def test_the_pin_round_trips_byte_for_byte(pin_copy):
    """Determinism without the catalog: writing what was read gives the same bytes."""
    original = pin_copy.read_bytes()
    ap.write(ap.load())
    assert pin_copy.read_bytes() == original


def test_write_refuses_entries_outside_the_frozen_sets(pin_copy):
    original = pin_copy.read_bytes()
    name, profile, rule_id = next(iter(_pinned_entries(ap.load())))   # any pinned entry
    for stray in ("rule", "input", "profile"):
        doc = ap.load()
        if stray == "rule":
            doc["rules"].remove(rule_id)
        elif stray == "input":
            doc["inputs"].remove(name)
        else:
            doc["findings"][name]["strict"] = {rule_id: []}
        with pytest.raises(ValueError, match="outside its frozen sets"):
            ap.write(doc)
    assert pin_copy.read_bytes() == original


def test_repin_rewrites_only_the_named_entries(pin_copy, monkeypatch, capsys):
    """Re-pinning a rule from a catalog that reports nothing removes exactly its entries
    and prints them; re-pinning from the original answers restores the bytes."""
    import repin_findings
    original, before = pin_copy.read_bytes(), ap.load()
    name, profile, rule_id = _a_pinned_finding(before)
    names = {build: n for n, build in ap.committed_inputs().items()}
    monkeypatch.setattr(ap, "current", lambda build, rid, prof: [])
    assert repin_findings.main(["--rule", rule_id, "--dry-run"]) == 0
    assert pin_copy.read_bytes() == original                    # a dry run writes nothing
    assert repin_findings.main(["--rule", rule_id]) == 0
    out = capsys.readouterr().out
    assert f"{rule_id} / {name} / {profile}:" in out and f"    - ('{rule_id}'," in out
    after = ap.load()
    assert _pinned_entries(after, exclude=()) == _pinned_entries(before, exclude=(rule_id,))
    assert after["rules"] == before["rules"]                   # it stays pinned, as []

    monkeypatch.setattr(ap, "current", lambda build, rid, prof:
                        ap.entry(before, names[build], prof, rid))
    assert repin_findings.main(["--rule", rule_id]) == 0
    assert pin_copy.read_bytes() == original


def test_drop_rule_refuses_a_rule_still_active_under_a_profile(pin_copy, capsys, monkeypatch):
    """Every legitimate change to an active rule is a re-pin; dropping one would take
    it out of the regression net. Retire it in the catalog first (12b re-review N5)."""
    import repin_findings
    rule_id = _a_pinned_finding(ap.load())[2]
    active = copy.deepcopy(catalog().rules[rule_id])
    active.status, active.profiles = "active", {}
    monkeypatch.setitem(catalog().rules, rule_id, active)  # whatever the catalog says today
    original = pin_copy.read_bytes()
    assert repin_findings.main(["--drop-rule", rule_id]) == 1
    assert f"{rule_id} is still active under spotter, general: retire it first" in \
        capsys.readouterr().err
    assert pin_copy.read_bytes() == original


def test_drop_rule_is_the_only_way_out_and_prints_every_entry(pin_copy, capsys, monkeypatch):
    import repin_findings
    before = ap.load()
    rule_id = _a_pinned_finding(before)[2]
    retired = copy.deepcopy(catalog().rules[rule_id])
    retired.status = "retired"
    monkeypatch.setitem(catalog().rules, rule_id, retired)   # retired in the catalog first
    dropped = {k: v for k, v in _pinned_entries(before).items() if k[2] == rule_id}
    assert repin_findings.main(["--drop-rule", rule_id]) == 0
    out = capsys.readouterr().out
    after = ap.load()
    assert rule_id not in after["rules"]
    assert _pinned_entries(after) == {k: v for k, v in _pinned_entries(before).items()
                                      if k[2] != rule_id}
    for (name, profile, _), value in dropped.items():
        shown = value if value == ap.RAISES else f"{len(value)} finding(s)"
        assert f"{rule_id} / {name} / {profile}: REMOVED ({shown})" in out
    assert f"rule {rule_id}: REMOVED from the pinned rule set" in out
