"""Unit tests for the Phase 2 `ts migrate apply` planning engine.

The assertions encode findings that cost live verification to learn. Where a test looks
pedantic, the docstring says what breaks in production without it.
"""
from __future__ import annotations

from ts_cli.migrate.apply_plan import (
    STEP_BACKUP, STEP_CLEANUP_CONNECTION, STEP_CLEANUP_MODELS, STEP_CLEANUP_TABLES,
    STEP_LIFT_CONTENT, STEP_LIFT_SCAFFOLDING, STEP_RENAME, STEP_REPOINT,
    build_apply_plan, build_cleanup_steps, connection_action, find_rename_collisions,
    new_ledger, pending_steps, record_completed, record_failure, rename_pairs,
    render_plan, validate_apply,
)
from ts_cli.migrate.schema import (ColumnMappingRow, GAP, GAP_BLOCKER, MATCHED,
                                   SET_BLOCKER)


def _row(model, tenant, published, status=MATCHED):
    return ColumnMappingRow(model=model, tenant_column=tenant,
                            tenant_column_id=f"{model}::{tenant}",
                            published_column=published, status=status)


# ---------------------------------------------------------------------------
# Rename extraction
# ---------------------------------------------------------------------------

def test_only_actual_renames_are_emitted():
    """A column whose names already match needs no work. Emitting it would make the
    rename step O(columns) rather than O(renames) and import a no-op diff."""
    rows = [_row("Sales", "Region", "String_1"), _row("Sales", "Amount", "Amount")]
    assert rename_pairs(rows) == [("Sales", "Region", "String_1")]


def test_an_unmapped_gap_row_is_not_a_rename():
    assert rename_pairs([_row("Sales", "Dept", "", status=GAP)]) == []


def test_renames_are_sorted_and_deduped_so_two_runs_are_diffable():
    rows = [_row("S", "B", "String_2"), _row("S", "A", "String_1"),
            _row("S", "A", "String_1")]
    assert rename_pairs(rows) == [("S", "A", "String_1"), ("S", "B", "String_2")]


# ---------------------------------------------------------------------------
# Collision detection -- the generated-map safety net
# ---------------------------------------------------------------------------

def test_two_columns_mapped_onto_one_published_name_is_fatal():
    """Standard fields keep their names and custom fields take unused generic slots, so
    this cannot happen by design. It is checked because the map is GENERATED, and the
    failure is silent: a rename cascades to every dependent automatically, so a wrong
    target quietly repoints real content at the wrong column rather than failing."""
    rows = [_row("Sales", "Region", "String_1"), _row("Sales", "Territory", "String_1")]
    problems = find_rename_collisions(rows)
    assert len(problems) == 1
    assert "not injective" in problems[0]
    assert "Region" in problems[0] and "Territory" in problems[0]


def test_renaming_onto_a_column_that_already_exists_is_fatal():
    """`Region -> Amount` where `Amount` is a real column of that Model and is not itself
    being renamed. Two columns would end up sharing one name."""
    rows = [_row("Sales", "Region", "Amount"), _row("Sales", "Amount", "Amount")]
    problems = find_rename_collisions(rows)
    assert any("already a column of that Model" in p for p in problems)


def test_a_rename_CHAIN_is_allowed_because_the_target_frees_up():
    """`A -> B` and `B -> C` is legal: B is itself renamed away, so nothing collides.
    Rejecting it would refuse a correct mapping."""
    rows = [_row("S", "A", "B"), _row("S", "B", "C")]
    assert find_rename_collisions(rows) == []


def test_the_same_target_name_in_DIFFERENT_models_is_fine():
    """Column names only have to be unique within a Model."""
    rows = [_row("Sales", "Region", "String_1"), _row("Orders", "Zone", "String_1")]
    assert find_rename_collisions(rows) == []


# ---------------------------------------------------------------------------
# validate_apply
# ---------------------------------------------------------------------------

def test_an_unmapped_gap_blocker_is_refused():
    problems = validate_apply([_row("Sales", "Dept", "", status=GAP_BLOCKER)])
    assert any("GAP_BLOCKER" in p for p in problems)


def test_a_set_blocker_is_refused_and_says_there_is_no_override():
    """`apply` refuses a cohort-carrying Model with no force flag, deliberately. Silently
    leaving content behind is the failure mode Phase 0 exists to prevent, so the message
    must not send someone looking for the flag."""
    problems = validate_apply([_row("Sales", "Bins", "", status=SET_BLOCKER)])
    assert any("no override" in p for p in problems)


def test_a_set_blocker_found_by_scan_sets_is_refused_even_when_the_csv_is_clean():
    """`scan-sets` and `audit` are separate commands run at different times. A Set added
    between them appears in neither's CSV, so the GUID set is the authority."""
    problems = validate_apply([_row("Sales", "Amount", "Amount")],
                              blocked_model_guids={"m1"},
                              model_guids_by_name={"Sales": "m1"})
    assert any("scan-sets" in p for p in problems)


def test_every_problem_is_returned_not_just_the_first():
    """Mapping mistakes are systematic. Fixing them one round-trip at a time is how a
    migration window gets lost."""
    rows = [_row("S", "A", "", status=GAP_BLOCKER),
            _row("S", "B", "X"), _row("S", "C", "X")]
    assert len(validate_apply(rows)) >= 2


def test_one_model_with_many_set_blocker_rows_reports_once():
    rows = [_row("S", "A", "", status=SET_BLOCKER), _row("S", "B", "", status=SET_BLOCKER)]
    assert len(validate_apply(rows)) == 1


def test_a_clean_mapping_returns_no_problems():
    rows = [_row("S", "Region", "String_1"), _row("S", "Amount", "Amount")]
    assert validate_apply(rows) == []


# ---------------------------------------------------------------------------
# Connection handling (live-verified 2026-07-27)
# ---------------------------------------------------------------------------

def test_a_target_org_with_no_connection_is_fatal():
    """Publishing a Table into an Org does NOT give that Org a usable connection --
    verified directly. Without one no Table import can succeed."""
    action = connection_action("APJ_ACME", [])
    assert action["action"] == "fail"
    assert "Publishing does not grant one" in action["reason"]


def test_a_same_named_connection_lets_the_lifted_tml_resolve_unchanged():
    """Connection names are per-Org, not cluster-unique (verified by rename). Naming the
    target's connection as the source's removes the connection-block rewrite entirely."""
    action = connection_action("APJ_ACME", ["APJ_ACME"])
    assert action == {"action": "resolve_unchanged", "connection": "APJ_ACME"}


def test_a_differently_named_connection_falls_back_to_rewriting_rather_than_failing():
    """The same-name trick is an optimisation with a correct fallback. Nothing is queried
    through the scaffolding and it is deleted at cleanup, so any valid connection will
    do -- treating a mismatch as fatal would refuse a migration that works."""
    action = connection_action("APJ_ACME", ["APJ_OTHER"])
    assert action["action"] == "rewrite"
    assert action["connection"] == "APJ_OTHER"


# ---------------------------------------------------------------------------
# Plan shape and ordering
# ---------------------------------------------------------------------------

def _plan(**over):
    scaffolding = over.get("scaffolding", {"tables": ["t1"], "models": ["m1"]})
    content = over.get("content", {"views": ["v1"], "answers": ["a1"],
                                   "liveboards": ["l1"]})
    rows = over.get("rows", [_row("Sales", "Region", "String_1")])
    conn = over.get("connection", {"action": "resolve_unchanged",
                                   "connection": "APJ_ACME", "provisioned": True})
    return build_apply_plan({"source": "ACME", "target": "ACME NEW"},
                            scaffolding, content, rows, conn)


def test_backup_is_first_so_nothing_is_written_before_a_copy_exists():
    assert _plan()[0]["step"] == STEP_BACKUP


def test_the_backup_covers_scaffolding_AND_content():
    assert set(_plan()[0]["objects"]) == {"t1", "m1", "v1", "a1", "l1"}


def test_scaffolding_is_lifted_before_content_that_references_it():
    steps = [s["step"] for s in _plan()]
    assert steps.index(STEP_LIFT_SCAFFOLDING) < steps.index(STEP_LIFT_CONTENT)


def test_content_batches_run_views_then_answers_then_liveboards():
    """Intra-batch references remap on import, but only for objects already in the batch:
    a Liveboard references Answers, an Answer references Views."""
    batches = [k for k, _ in _plan()[2]["batches"]]
    assert batches == ["views", "answers", "liveboards"]


def test_rename_precedes_repoint_because_repoint_matches_columns_BY_NAME():
    """The repoint is a 1:1-by-name match onto the published Model. Before the rename the
    names do not match, so the repoint has nothing to bind to."""
    steps = [s["step"] for s in _plan()]
    assert steps.index(STEP_RENAME) < steps.index(STEP_REPOINT)


def test_cleanup_runs_models_then_tables_then_connection():
    """Deleting a connection does NOT cascade to its Tables, so the connection cannot go
    first. Live-checked against the `deleteConnection` spec 2026-07-27."""
    steps = [s["step"] for s in _plan()]
    assert (steps.index(STEP_CLEANUP_MODELS) < steps.index(STEP_CLEANUP_TABLES)
            < steps.index(STEP_CLEANUP_CONNECTION))


def test_repoint_precedes_cleanup_so_the_dependent_check_can_fire():
    """A scaffolding Model with dependents refuses to delete. That refusal IS the
    missed-repoint check, and it only works if the repoint has already run."""
    steps = [s["step"] for s in _plan()]
    assert steps.index(STEP_REPOINT) < steps.index(STEP_CLEANUP_MODELS)


def test_a_connection_the_target_org_ALREADY_had_is_never_deleted():
    """Only a connection this migration provisioned is disposable. Deleting a pre-existing
    one would remove something that is not ours."""
    steps = build_cleanup_steps({"tables": ["t1"], "models": ["m1"]},
                                {"connection": "APJ", "provisioned": False})
    assert [s["step"] for s in steps] == [STEP_CLEANUP_MODELS, STEP_CLEANUP_TABLES]


def test_every_step_carries_the_pair_so_a_log_line_is_self_describing():
    assert all(s["pair"]["source"] == "ACME" for s in _plan())


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

def test_completed_steps_are_skipped_on_resume():
    plan = _plan()
    ledger = record_completed(new_ledger({"source": "A", "target": "B"}), STEP_BACKUP)
    assert STEP_BACKUP not in [s["step"] for s in pending_steps(plan, ledger)]


def test_resume_keys_on_step_NAME_not_index():
    """A plan regenerated after a mapping edit can have a different length. An index
    would silently shift and re-run or skip the wrong work."""
    ledger = record_completed(new_ledger({}), STEP_BACKUP)
    short = [{"step": STEP_RENAME}, {"step": STEP_BACKUP}]
    assert [s["step"] for s in pending_steps(short, ledger)] == [STEP_RENAME]


def test_created_guids_are_kept_so_a_rerun_updates_in_place():
    """Re-importing without the target GUID creates a duplicate rather than updating."""
    ledger = record_completed(new_ledger({}), STEP_LIFT_SCAFFOLDING,
                              created={"t1": "new-guid"})
    assert ledger["created"][STEP_LIFT_SCAFFOLDING]["t1"] == "new-guid"


def test_recording_a_completion_clears_a_previous_failure():
    ledger = record_failure(new_ledger({}), STEP_RENAME, "boom")
    assert record_completed(ledger, STEP_RENAME)["failed"] is None


def test_a_failure_records_which_step_and_why():
    ledger = record_failure(new_ledger({}), STEP_REPOINT, "dangling join")
    assert ledger["failed"] == {"step": STEP_REPOINT, "detail": "dangling join"}


def test_an_empty_ledger_leaves_the_whole_plan_pending():
    plan = _plan()
    assert len(pending_steps(plan, new_ledger({}))) == len(plan)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def test_dry_run_names_each_rename_so_it_can_be_read_before_it_runs():
    md = render_plan(_plan())
    assert "`Region` → `String_1`" in md


def test_dry_run_states_that_a_refused_model_delete_is_the_CHECK():
    """An operator who reads "refuses to delete" as an error will go looking for a force
    flag -- and forcing past it is how un-repointed content gets orphaned."""
    md = render_plan(_plan())
    assert "missed-repoint check" in md


def test_dry_run_says_cutover_is_not_included():
    """Users move only after the Org is verified in its final state. A reader who assumes
    apply cuts over would not schedule the verification."""
    assert "Cutover is NOT part of this plan" in render_plan(_plan())


def test_dry_run_explains_a_connection_rewrite_rather_than_just_naming_it():
    plan = _plan(connection=connection_action("APJ_ACME", ["APJ_OTHER"]))
    assert "connection block is rewritten" in render_plan(plan)


def test_dry_run_says_so_when_there_are_no_renames():
    """An empty rename list is a legitimate outcome (every column already matches), not a
    sign the mapping failed to load."""
    plan = _plan(rows=[_row("S", "Amount", "Amount")])
    assert "no renames" in render_plan(plan)
