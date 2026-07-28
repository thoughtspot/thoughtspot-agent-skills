"""Smoke test for the ts-migrate-orgs skill.

The skill drives a destructive, multi-step cutover in someone's production Org, so what
has to hold is that the guidance and the engine agree about the things that make it
recoverable: the step order, which failures are checks rather than errors, and where the
rollback actually lives.

A drift between SKILL.md and the engine is the specific hazard. If the skill told an
operator that cleanup runs connection-first, or that a refused Model delete is a bug to
force past, they would follow the skill -- and orphan a tenant's content.

No live ThoughtSpot connection required.
"""
import sys
from pathlib import Path

# Test the ts_cli in THIS checkout, not whatever happens to be installed.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ts-cli"))

from ts_cli.migrate.apply_plan import (  # noqa: E402
    STEP_ORDER, STEP_REWRITE_CONTENT, STEP_REWRITE_VIEWS,
    find_rename_collisions, import_mode, unfiltered_target_problem, validate_apply,
)
from ts_cli.migrate.schema import ColumnMappingRow, SET_BLOCKER  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SKILL = REPO / "agents" / "cli" / "ts-migrate-orgs"
NOTES = SKILL / "references" / "migration-notes.md"


def _skill_text():
    return (SKILL / "SKILL.md").read_text(encoding="utf-8")


def _row(model, tenant, published, status="MATCHED"):
    return ColumnMappingRow(model=model, tenant_column=tenant,
                            tenant_column_id=f"{model}::{tenant}",
                            published_column=published, status=status)


# ---------------------------------------------------------------------------
# The skill and the engine must agree on the step order
# ---------------------------------------------------------------------------

def test_the_skill_documents_the_engines_actual_step_order():
    """An operator reads the table in SKILL.md to know what will happen. If the engine
    grew a step the skill does not mention, the first they learn of it is in production."""
    text = _skill_text()
    for step in STEP_ORDER:
        if step.startswith("cleanup_"):
            continue  # documented collectively as `cleanup_*`
        assert step in text, f"engine step '{step}' is undocumented in SKILL.md"


def test_views_are_rewritten_BEFORE_content_in_both_engine_and_skill():
    """In a new-Org run the View must exist before anything references it -- and the
    skill's table is what an operator follows."""
    order = list(STEP_ORDER)
    assert order.index(STEP_REWRITE_VIEWS) < order.index(STEP_REWRITE_CONTENT)
    text = _skill_text()
    assert text.index("| `rewrite_views` |") < text.index("| `rewrite_content` |")


def test_the_skill_states_the_migration_is_THREE_steps():
    """It was eight. A skill still describing the scaffolding dance would have an
    operator looking for steps the engine no longer runs."""
    assert len(STEP_ORDER) == 3
    text = _skill_text()
    # The DELETED step names, not the word "scaffolding" -- the changelog legitimately
    # says "no scaffolding", and a test that cannot tell those apart is noise.
    for gone in ("lift_scaffolding", "cleanup_models", "cleanup_connection",
                 "| `rename` |", "| `repoint` |"):
        assert gone not in text, f"SKILL.md still documents the removed step {gone!r}"


def test_the_skill_documents_all_THREE_topologies():
    """Same Org / new Org / new cluster differ only in write mode, but their ROLLBACKS
    differ a lot, and the weakest one has to be called out."""
    text = _skill_text()
    assert "Same Org, same cluster" in text
    assert "New Org, different cluster" in text
    assert "weakest" in text


# ---------------------------------------------------------------------------
# The two outcomes that look like errors
# ---------------------------------------------------------------------------

def test_the_skill_says_a_COVERAGE_refusal_must_not_be_worked_around():
    """The most damaging misreading available now. Importing past it produces an object
    that loads and renders wrong -- exactly what the gate exists to prevent."""
    text = _skill_text()
    assert "rewrite incomplete" in text
    assert "Do not work around it" in text
    assert "renders wrong" in text


def test_the_skill_explains_the_TENANT_ISOLATION_refusal_at_the_repoint():
    """The most important refusal in the routine, and the one most likely to be forced
    past: repointing onto a published Model with no RLS lets every tenant see every other
    tenant's rows. The skill has to say the consequence, not just the rule -- and has to
    name the override so a legitimate single-tenant target is not stuck."""
    text = _skill_text()
    assert "row-level security" in text
    assert "every other tenant" in text
    assert "--allow-unfiltered-target" in text


def test_the_skill_says_an_UNREADABLE_isolation_check_also_refuses():
    """Not knowing whether a shared Model filters is not the same as knowing it does.
    Treating unknown as safe is how a silent check becomes a silent hole."""
    text = _skill_text()
    assert "unreadable" in text.lower()


def test_the_engine_actually_makes_the_refusal_the_skill_promises():
    """Skill/engine drift is the hazard: an operator follows the skill."""
    from ts_cli.migrate.apply_plan import unfiltered_target_problem
    assert unfiltered_target_problem({"SALES": 0}, "Sales")          # unfiltered -> refuse
    assert unfiltered_target_problem({}, "Sales")                    # unreadable -> refuse
    assert unfiltered_target_problem({"SALES": 1}, "Sales") is None  # filtered  -> pass


# ---------------------------------------------------------------------------
# Where the rollback lives
# ---------------------------------------------------------------------------

def test_the_skill_is_explicit_that_the_SOURCE_ORG_is_the_rollback():
    """Not the backup, not the scaffolding, not a staging Org. If an operator believes
    the backup is the safety net they will treat the source Org as expendable."""
    text = _skill_text()
    assert "source Org is never touched" in text
    assert "It is the rollback" in text


def test_the_skill_says_cutover_is_not_part_of_apply():
    """Verification happens between apply and cutover. A reader who assumes apply cuts
    over would not schedule it -- and would verify as an admin, or not at all."""
    text = _skill_text()
    assert "Cutover is deliberately" in text
    assert "real non-admin user" in text


# ---------------------------------------------------------------------------
# Refusals the skill promises, the engine must actually make
# ---------------------------------------------------------------------------

def test_a_set_blocked_model_is_refused_with_no_override():
    """The skill tells the operator not to look for a force flag. That has to be true."""
    problems = validate_apply([_row("Sales", "Bins", "", status=SET_BLOCKER)])
    assert problems and "no override" in problems[0]
    assert "no override" in _skill_text()


def test_a_non_injective_rename_map_is_refused():
    """Promised in the skill as the reason step 3 needs a human read."""
    rows = [_row("S", "Region", "String_1"), _row("S", "Territory", "String_1")]
    assert find_rename_collisions(rows)


def test_the_skill_says_NO_connection_provisioning_is_needed():
    """It was a hard precondition of the old architecture. Leaving it in the skill would
    send an operator to provision something nothing needs."""
    text = _skill_text()
    assert "No connection provisioning is needed" in text


def test_the_import_mode_is_DERIVED_not_configured():
    """Three topologies, one code path. A flag would let an operator pick the wrong one."""
    assert import_mode("A", "A", "p", "p")["keep_guid"] is True
    assert import_mode("A", "B", "p", "p")["create_new"] is True


# ---------------------------------------------------------------------------
# Aliases — the step whose blast radius is other tenants
# ---------------------------------------------------------------------------

def test_the_skill_says_aliases_are_per_WAVE_and_says_why():
    """Per-tenant is O(N-squared) and the reason is not obvious from the command, so an
    operator optimising for simplicity would batch it wrong."""
    text = _skill_text()
    assert "once per wave, never once per tenant" in text.lower()
    assert "O(N²)" in text
    assert "serialised" in text


def test_the_skill_warns_that_a_partial_export_drops_other_tenants_aliases():
    """The one catastrophic step: no error is raised anywhere, and the damage lands on
    tenants who already migrated successfully."""
    text = _skill_text()
    assert "silently drops" in text
    assert "String_1" in text and "Region" in text


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

def test_the_notes_record_why_a_staging_org_was_rejected():
    """It is the obvious "improvement" someone will propose. The reasoning has to survive
    in the repo or it gets re-litigated."""
    text = NOTES.read_text(encoding="utf-8")
    assert "staging Org" in text
    assert "already disposable" in text


def test_the_notes_distinguish_RLS_from_CSR_and_say_why():
    """Both are "security defined in Primary" and they behave OPPOSITELY on publication.
    Without the structural reason recorded, the next person guesses."""
    text = NOTES.read_text(encoding="utf-8")
    assert "RLS carries; CSR does not" in text
    assert "separate, Org-scoped security object" in text


def test_the_notes_record_that_the_old_BL144_guard_was_DEAD_CODE():
    """The guard looked for `doc["table"]["rls_rules"]` but only ever ran on a Model
    document, which has no `table` key -- so it could never fire. Recording that matters
    more than quietly deleting it: dead safety code reads as protection, and the next
    person would otherwise re-add it."""
    text = NOTES.read_text(encoding="utf-8")
    assert "dead code" in text.lower()
    assert "could never fire" in text


def test_the_notes_mark_ts_vars_as_a_test_env_gap_not_a_platform_limit():
    """Recording BL-145 as a platform limitation would be wrong and would misdirect the
    next reader -- ts_vars is confirmed working in production."""
    text = NOTES.read_text(encoding="utf-8")
    assert "test-environment gap, not a platform limitation" in text


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  PASS  {name}")
    print("\nAll ts-migrate-orgs smoke tests passed.")
