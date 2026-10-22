"""`uses:` and the data-read declarations (audit rule catalog, task 11 fix round 1).

`uses:` names conditional data a rule reads but must not be skipped for lacking — it is
fetched, never gates. Derived fields, code rules and scopes declare in their registries
which conditional data they read; the catalog gate fails a rule whose `requires ∪ uses`
does not cover what its scope, fields and code read. A recording context then checks
the registries themselves against what each rule actually touches.
"""
import copy

import pytest

import audit_rule_fixtures as fx
from ts_cli.audit.catalog_expr import CONDITIONAL_DATA
from ts_cli.audit.catalog_model import build_catalog, load_catalog, load_raw
from ts_cli.audit.catalog_uses import data_reads
from ts_cli.audit.catalog_validate import validate_catalog
from ts_cli.audit.engine import code_rules, fields, scopes
from ts_cli.audit.engine.run import run_rule


def _shipped_with(edit):
    raw = copy.deepcopy(load_raw())
    by_id = {r["id"]: r for f, rules in raw.items() if f.startswith("rules/") for r in rules}
    edit(by_id)
    return validate_catalog(build_catalog(raw), raw)


def test_shipped_catalog_is_valid_and_a5_declares_its_use():
    assert _shipped_with(lambda rules: None) == []
    assert load_catalog().rules["A5"].uses == ["ai_instructions"]


# ── the gate: requires ∪ uses must cover what a rule reads ──────────────────

def test_gate_fires_for_a5_without_uses():
    problems = _shipped_with(lambda rules: rules["A5"].pop("uses"))
    [p] = problems
    assert "A5" in p and "ai_instructions" in p and "code:spotter_readiness" in p


def test_gate_fires_for_a_derived_field_read_undeclared():
    """A3 reads @is_coached; dropping its `requires: ai_instructions` leaves it uncovered."""
    problems = _shipped_with(lambda rules: rules["A3"].update(requires=["model_tml"]))
    [p] = problems
    assert "A3" in p and "ai_instructions" in p and "@is_coached" in p


def test_gate_fires_for_a_scope_read_undeclared():
    problems = _shipped_with(lambda rules: rules["H7"].update(requires=[]))
    assert any("H7" in p and "answers" in p and "scope answer" in p for p in problems)


def test_gate_fires_for_h4_without_dependents():
    problems = _shipped_with(lambda rules: rules["H4"].update(requires=["model_tml"]))
    assert any("H4" in p and "dependents" in p and "@dependent_count" in p for p in problems)


def test_uses_covers_a_read_as_well_as_requires():
    def h4_uses_dependents(rules):
        rules["H4"].update(requires=["model_tml"], uses=["dependents"])
    assert _shipped_with(h4_uses_dependents) == []


def test_data_reads_names_each_source():
    reads = data_reads(load_catalog().rules["A5"])
    assert reads == {"ai_instructions": ["code:spotter_readiness"]}
    assert data_reads(load_catalog().rules["H5"]) == {
        "dependents": ["scope set", "@set_consumers"], "sets": ["scope set", "@set_consumers"]}


# ── the `uses` key itself ───────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["model_tml", "table_tml", "metadata"])
def test_uses_rejects_unconditional_data_and_says_why(value):
    problems = _shipped_with(lambda rules: rules["A5"].update(uses=["ai_instructions", value]))
    [p] = problems
    assert f"'{value}'" in p and "fetched for every audit" in p


def test_uses_rejects_an_unknown_value():
    [p] = _shipped_with(lambda rules: rules["A5"].update(uses=["ai_instructions", "answer"]))
    assert "unknown uses value 'answer'" in p


def test_uses_rejects_what_requires_already_declares():
    [p] = _shipped_with(lambda rules: rules["A3"].update(uses=["ai_instructions"]))
    assert "A3" in p and "already in requires" in p


def test_a_profile_cannot_override_uses():
    problems = _shipped_with(
        lambda rules: rules["A5"].setdefault("profiles", {}).update(spotter={"uses": []}))
    assert any("profiles.spotter.uses is not overridable" in p for p in problems)


def test_uses_never_gates_an_item():
    """A5 still judges a Model with no ai/instructions entry (scored uncoached)."""
    from ts_cli.audit.context import make_context
    ctx = make_context(models=[{"guid": "m1", "model": {"name": "S", "columns": []}}])
    assert ctx.ai_instructions == {}
    rule = load_catalog().rules["A5"]
    assert [i["guid"] for i in scopes.available(ctx, rule)] == ["m1"]
    assert [f.object_guid for f in run_rule(ctx, load_catalog(), "A5", "general")] == ["m1"]


# ── the registries ──────────────────────────────────────────────────────────

def test_every_registered_field_and_code_rule_declares_its_uses():
    assert set(fields.FIELD_USES) == set(fields.FIELDS)
    assert set(code_rules.CODE_USES) == set(code_rules.REGISTRY)
    for declared in list(fields.FIELD_USES.values()) + list(code_rules.CODE_USES.values()):
        assert set(declared) <= set(CONDITIONAL_DATA)
    assert set(scopes.SCOPE_USES) <= set(scopes.ITERATORS)


def test_register_requires_a_uses_declaration():
    with pytest.raises(ValueError, match="uses is required"):
        fields.register("t11_no_uses")
    with pytest.raises(ValueError, match="uses is required"):
        code_rules.code_rule("t11_no_uses", severity="bands")


def test_register_rejects_unconditional_or_unknown_uses():
    with pytest.raises(ValueError, match="uses"):
        fields.register("t11_bad", uses={"table_tml"})
    with pytest.raises(ValueError, match="uses"):
        code_rules.code_rule("t11_bad", severity="bands", uses={"answer"})
    assert "t11_bad" not in fields.FIELDS and "t11_bad" not in code_rules.REGISTRY


class _Recording:
    """An AuditContext stand-in that records which attributes are read."""

    def __init__(self, inner):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "read", set())

    def __getattr__(self, name):
        self.read.add(name)
        return getattr(self._inner, name)


def _examples():
    cat = load_catalog()
    for rule in cat.rules.values():
        if rule.status != "active":
            continue
        for kind, ex in rule.examples.items():
            yield pytest.param(rule.id, ex, id=f"{rule.id}-{kind}")


@pytest.mark.parametrize("rule_id,example", list(_examples()))
def test_a_rule_touches_no_conditional_data_it_does_not_declare(rule_id, example):
    """The registries' declarations, checked against what each rule's examples read:
    a field or code rule that reads conditional data its registration omits fails here
    even though the gate (which trusts the registration) passes."""
    cat = load_catalog()
    rule = cat.rules[rule_id]
    ctx = _Recording(getattr(fx, example["fixture"])())
    run_rule(ctx, cat, rule_id, example.get("profile") or "general")
    touched = ctx.read & set(CONDITIONAL_DATA)
    assert touched <= set(rule.requires) | set(rule.uses), (rule_id, touched)
    assert touched <= set(data_reads(rule)), (rule_id, touched, data_reads(rule))
