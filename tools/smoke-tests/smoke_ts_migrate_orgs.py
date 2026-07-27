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
    STEP_CLEANUP_CONNECTION, STEP_CLEANUP_MODELS, STEP_CLEANUP_TABLES,
    STEP_LIFT_CONTENT, STEP_LIFT_SCAFFOLDING, STEP_RENAME, STEP_REPOINT, STEP_ORDER,
    connection_action, find_rename_collisions, validate_apply,
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


def test_cleanup_order_is_stated_models_then_tables_then_connection():
    """Connection deletion does NOT cascade to its Tables, so a skill that implied any
    other order would have the operator delete the connection while Tables still hang
    off it."""
    order = list(STEP_ORDER)
    assert (order.index(STEP_CLEANUP_MODELS) < order.index(STEP_CLEANUP_TABLES)
            < order.index(STEP_CLEANUP_CONNECTION))
    text = _skill_text()
    assert "Models, then Tables, then the connection" in text


def test_rename_precedes_repoint_in_both_the_engine_and_the_skill():
    """The repoint is a 1:1-by-name match; before the rename there is nothing to bind."""
    order = list(STEP_ORDER)
    assert order.index(STEP_RENAME) < order.index(STEP_REPOINT)
    text = _skill_text()
    assert text.index("| `rename` |") < text.index("| `repoint` |")


def test_scaffolding_is_lifted_before_content():
    order = list(STEP_ORDER)
    assert order.index(STEP_LIFT_SCAFFOLDING) < order.index(STEP_LIFT_CONTENT)


# ---------------------------------------------------------------------------
# The two outcomes that look like errors
# ---------------------------------------------------------------------------

def test_the_skill_says_a_refused_model_delete_is_the_CHECK():
    """The single most damaging misreading available. An operator who treats the refusal
    as a bug reaches for a bigger hammer and orphans the content it was protecting."""
    text = _skill_text()
    assert "missed-repoint check" in text
    assert "orphans that content" in text
    assert "Deleting past this" in text


def test_the_skill_says_a_failed_rls_assertion_means_the_table_is_UNFILTERED_NOW():
    """BL-144 is silent in the direction that removes security. "Import failed" would be
    read as "nothing happened", which is the opposite of the truth."""
    text = _skill_text()
    assert "BL-144" in text
    assert "unfiltered" in text.lower()
    assert "backup" in text.lower()


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


def test_a_target_org_with_no_connection_is_fatal_as_the_skill_states():
    assert connection_action("APJ_ACME", [])["action"] == "fail"
    assert "No connection at all is fatal" in _skill_text()


def test_a_same_named_connection_avoids_rewriting_as_the_skill_claims():
    assert connection_action("APJ_ACME", ["APJ_ACME"])["action"] == "resolve_unchanged"
    assert "resolves **unchanged**" in _skill_text()


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
