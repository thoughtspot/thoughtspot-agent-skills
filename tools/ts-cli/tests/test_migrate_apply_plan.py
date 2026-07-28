"""Unit tests for the Phase 2 `ts migrate apply` planning engine.

The assertions encode findings that cost live verification to learn. Where a test looks
pedantic, the docstring says what breaks in production without it.
"""
from __future__ import annotations

from ts_cli.migrate.apply_plan import (
    STEP_BACKUP, STEP_ORDER, STEP_REWRITE_CONTENT, STEP_REWRITE_VIEWS,
    build_apply_plan, column_map, find_rename_collisions, import_mode, new_ledger,
    pending_steps, record_completed, record_failure, rename_pairs, render_plan,
    unfiltered_target_problem, validate_apply,
)
from ts_cli.migrate.schema import (ColumnMappingRow, GAP, GAP_BLOCKER, MATCHED,
                                   SET_BLOCKER)


def _row(model, tenant, published, status=MATCHED):
    return ColumnMappingRow(model=model, tenant_column=tenant,
                            tenant_column_id=f"{model}::{tenant}",
                            published_column=published, status=status)


# ---------------------------------------------------------------------------
# The column map
# ---------------------------------------------------------------------------

def test_only_actual_renames_enter_the_map():
    """A column whose names already match needs no substitution. Including it would make
    the rewrite touch every column instead of only the changed ones."""
    rows = [_row("Sales", "Region", "String_1"), _row("Sales", "Amount", "Amount")]
    assert column_map(rows) == {"Region": "String_1"}


def test_an_unmapped_gap_row_is_not_a_rename():
    assert rename_pairs([_row("Sales", "Dept", "", status=GAP)]) == []


def test_renames_are_sorted_and_deduped_so_two_runs_are_diffable():
    rows = [_row("S", "B", "String_2"), _row("S", "A", "String_1"),
            _row("S", "A", "String_1")]
    assert rename_pairs(rows) == [("S", "A", "String_1"), ("S", "B", "String_2")]


# ---------------------------------------------------------------------------
# Collision detection — the generated-map safety net
# ---------------------------------------------------------------------------

def test_two_columns_mapped_onto_one_published_name_is_fatal():
    """The map is GENERATED and its failure is silent: the rewrite substitutes names
    across the whole document, so a wrong target quietly repoints real content at the
    wrong column rather than erroring."""
    rows = [_row("Sales", "Region", "String_1"), _row("Sales", "Territory", "String_1")]
    problems = find_rename_collisions(rows)
    assert problems and "not injective" in problems[0]


def test_renaming_onto_a_column_that_already_exists_is_fatal():
    rows = [_row("Sales", "Region", "Amount"), _row("Sales", "Amount", "Amount")]
    assert any("already a column of that Model" in p for p in find_rename_collisions(rows))


def test_a_rename_CHAIN_is_allowed_because_the_target_frees_up():
    """`A -> B` and `B -> C` is legal: B is renamed away, so nothing collides."""
    assert find_rename_collisions([_row("S", "A", "B"), _row("S", "B", "C")]) == []


def test_ONE_column_mapped_DIFFERENTLY_in_two_models_is_fatal():
    """The rewrite is document-wide, not per-Model, so it could not honour both -- it
    would silently pick one. This is the collision the flat column map introduces, and
    the reason it has to be checked."""
    rows = [_row("Sales", "Region", "String_1"), _row("Orders", "Region", "String_9")]
    assert any("cannot honour both" in p for p in find_rename_collisions(rows))


def test_the_same_TARGET_in_two_models_is_fine():
    """Two different tenant columns landing on `String_1` in different Models is normal:
    generic slots are per-Model."""
    rows = [_row("Sales", "Region", "String_1"), _row("Orders", "Zone", "String_1")]
    assert find_rename_collisions(rows) == []


# ---------------------------------------------------------------------------
# validate_apply
# ---------------------------------------------------------------------------

def test_an_unmapped_gap_blocker_is_refused():
    assert any("GAP_BLOCKER" in p
               for p in validate_apply([_row("S", "Dept", "", status=GAP_BLOCKER)]))


def test_a_set_blocker_is_refused_and_says_there_is_no_override():
    """The message must not send someone looking for a force flag: silently leaving
    content behind is the failure mode Phase 0 exists to prevent."""
    assert any("no override"
               in p for p in validate_apply([_row("S", "B", "", status=SET_BLOCKER)]))


def test_a_set_blocker_found_by_scan_sets_is_refused_even_when_the_csv_is_clean():
    """`scan-sets` and `audit` run at different times; a Set added between them is in
    neither CSV, so the GUID set is the authority."""
    problems = validate_apply([_row("Sales", "Amount", "Amount")],
                              blocked_model_guids={"m1"},
                              model_guids_by_name={"Sales": "m1"})
    assert any("scan-sets" in p for p in problems)


def test_every_problem_is_returned_not_just_the_first():
    rows = [_row("S", "A", "", status=GAP_BLOCKER), _row("S", "B", "X"),
            _row("S", "C", "X")]
    assert len(validate_apply(rows)) >= 2


def test_one_model_with_many_set_blocker_rows_reports_once():
    rows = [_row("S", "A", "", status=SET_BLOCKER), _row("S", "B", "", status=SET_BLOCKER)]
    assert len(validate_apply(rows)) == 1


def test_a_clean_mapping_returns_no_problems():
    assert validate_apply([_row("S", "Region", "String_1"),
                           _row("S", "Amount", "Amount")]) == []


# ---------------------------------------------------------------------------
# Topology — the ONLY thing that varies between the three cases
# ---------------------------------------------------------------------------

def test_same_org_updates_in_place():
    """The objects already exist. Creating fresh ones would duplicate the tenant's
    content rather than migrate it."""
    m = import_mode("ACME", "ACME", "prod", "prod")
    assert m["same_org"] and m["keep_guid"] and not m["create_new"]


def test_a_new_org_on_the_same_cluster_creates_fresh():
    m = import_mode("ACME", "ACME NEW", "prod", "prod")
    assert m["create_new"] and not m["keep_guid"]


def test_a_DIFFERENT_CLUSTER_needs_no_special_handling():
    """Cluster is a property of the profile, and the two clients are already
    independent. Treating it as a third mode would be machinery for nothing."""
    same_cluster = import_mode("ACME", "ACME NEW", "prod", "prod")
    cross_cluster = import_mode("ACME", "ACME NEW", "prod", "dr")
    assert same_cluster["create_new"] == cross_cluster["create_new"]


def test_same_org_mode_WARNS_that_the_backup_is_the_only_rollback():
    """It is the weakest of the three topologies, and the operator has to know before
    starting rather than after."""
    assert "only rollback" in import_mode("ACME", "ACME", "p", "p")["note"]


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------

def test_binding_to_an_unfiltered_published_model_is_refused():
    """The tenant's content ends up reading the SHARED published Model. If it filters no
    rows, every tenant sees every other tenant's -- silent, and the worst outcome the
    programme can produce."""
    problem = unfiltered_target_problem({"SALES": 0}, "Sales")
    assert problem and "every other tenant's rows" in problem


def test_a_filtered_target_passes():
    assert unfiltered_target_problem({"SALES": 2}, "Sales") is None


def test_ONE_unfiltered_table_among_several_still_refuses():
    """A Model is only as segmented as its least-filtered table."""
    assert unfiltered_target_problem({"SALES": 2, "CUSTOMER": 0}, "Sales")


def test_an_UNREADABLE_check_refuses_rather_than_passing():
    """Treating unknown as safe is how a silent check becomes a silent hole."""
    assert "unreadable check is not a passed one" in unfiltered_target_problem({}, "S")


def test_the_override_does_NOT_cover_the_unreadable_case():
    """`--allow-unfiltered-target` says "I know this target has no RLS". It cannot mean
    "whatever is there is fine", because in the unreadable case nobody knows."""
    assert unfiltered_target_problem({"S": 0}, "S", allow=True) is None
    assert unfiltered_target_problem({}, "S", allow=True) is not None


# ---------------------------------------------------------------------------
# Plan shape
# ---------------------------------------------------------------------------

def _plan(views=None, content=None, same_org=False):
    return build_apply_plan(
        {"source": "ACME", "target": "ACME NEW"},
        views if views is not None else [{"guid": "v1", "name": "V"}],
        content if content is not None else [{"guid": "a1", "name": "A"}],
        {"Segment": "STRING_1"},
        {"guid": "tgt", "name": "PUBLISHED"},
        import_mode("ACME", "ACME" if same_org else "ACME NEW", "p", "p"))


def test_the_plan_is_FOUR_steps():
    """It was eight. Three of the four are the migration; the fourth exists only because
    shielded content still has to MOVE in a new-Org run, which omitting it made silent
    data loss."""
    assert [s["step"] for s in _plan()] == list(STEP_ORDER)
    assert len(STEP_ORDER) == 4


def test_backup_is_first_so_nothing_is_written_before_a_copy_exists():
    assert _plan()[0]["step"] == STEP_BACKUP


def test_the_backup_covers_views_AND_content():
    assert set(_plan()[0]["objects"]) == {"v1", "a1"}


def test_views_are_rewritten_BEFORE_content():
    """In a new-Org run the View must exist before anything references it."""
    steps = [s["step"] for s in _plan()]
    assert steps.index(STEP_REWRITE_VIEWS) < steps.index(STEP_REWRITE_CONTENT)


def test_every_step_carries_the_pair_so_a_log_line_is_self_describing():
    assert all(s["pair"]["source"] == "ACME" for s in _plan())


def test_a_migration_with_no_views_still_plans_cleanly():
    plan = _plan(views=[])
    assert plan[1]["objects"] == []
    assert plan[2]["objects"]


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

def test_completed_steps_are_skipped_on_resume():
    ledger = record_completed(new_ledger({}), STEP_BACKUP)
    assert STEP_BACKUP not in [s["step"] for s in pending_steps(_plan(), ledger)]


def test_resume_keys_on_step_NAME_not_index():
    """A plan regenerated after a mapping edit can differ in length; an index would
    silently shift and skip the wrong work."""
    ledger = record_completed(new_ledger({}), STEP_BACKUP)
    short = [{"step": STEP_REWRITE_CONTENT}, {"step": STEP_BACKUP}]
    assert [s["step"] for s in pending_steps(short, ledger)] == [STEP_REWRITE_CONTENT]


def test_created_guids_are_kept_so_a_rerun_updates_in_place():
    ledger = record_completed(new_ledger({}), STEP_REWRITE_CONTENT, created={"A": "g1"})
    assert ledger["created"][STEP_REWRITE_CONTENT]["A"] == "g1"


def test_recording_a_completion_clears_a_previous_failure():
    ledger = record_failure(new_ledger({}), STEP_REWRITE_CONTENT, "boom")
    assert record_completed(ledger, STEP_REWRITE_CONTENT)["failed"] is None


def test_a_failure_records_which_step_and_why():
    ledger = record_failure(new_ledger({}), STEP_REWRITE_VIEWS, "residual refs")
    assert ledger["failed"] == {"step": STEP_REWRITE_VIEWS, "detail": "residual refs"}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def test_dry_run_names_the_column_renames():
    assert "`Segment` → `STRING_1`" in render_plan(_plan())


def test_dry_run_explains_that_views_shield_their_content():
    """Otherwise "rewrite_views: 1 object" reads as trivial rather than as the step that
    migrated everything built on it."""
    assert "needs no migration" in render_plan(_plan())


def test_dry_run_states_the_import_MODE():
    """Update-in-place and create-fresh have very different rollbacks, so the operator
    must see which one they are about to run."""
    assert "in place" in render_plan(_plan(same_org=True))
    assert "created fresh" in render_plan(_plan())


def test_dry_run_says_cutover_is_not_included_for_a_NEW_ORG_run():
    assert "Cutover is NOT part of this plan" in render_plan(_plan())


def test_dry_run_does_NOT_mention_cutover_for_a_same_org_run():
    """There is no cutover: the users are already there. Mentioning one would imply a
    step that does not exist."""
    assert "Cutover" not in render_plan(_plan(same_org=True))


# ---------------------------------------------------------------------------
# Segmentation — RLS only matters when the Orgs share physical data
# ---------------------------------------------------------------------------

from ts_cli.migrate.apply_plan import (  # noqa: E402
    SEGMENT_PER_PRINCIPAL, SEGMENT_PHYSICAL, SEGMENT_SHARED, SEGMENT_UNKNOWN,
    target_segmentation,
)


def _var(vtype, values):
    return {"name": "v", "variable_type": vtype,
            "values": [{"org_identifier": o, "value": v} for o, v in values]}


def test_a_table_mapping_with_DIFFERENT_values_per_org_is_physical_segmentation():
    """Publication points each tenant at its own schema. The tenants are already
    separated, and demanding RLS on top would be a false alarm."""
    v = _var("TABLE_MAPPING", [("ACME", "ACME_SCHEMA"), ("GLOBEX", "GLOBEX_SCHEMA")])
    assert target_segmentation([v], "ACME") == SEGMENT_PHYSICAL


def test_a_table_mapping_with_the_SAME_value_everywhere_is_shared():
    """Live-observed on the fixture: `apj_schema` is ALIAS_TESTS in both Primary and ORG2,
    so those Orgs really do read the same rows and RLS is the only separator."""
    v = _var("TABLE_MAPPING", [("Primary", "ALIAS_TESTS"), ("ORG2", "ALIAS_TESTS")])
    assert target_segmentation([v], "ORG2") == SEGMENT_SHARED


def test_a_connection_property_can_also_segment_physically():
    """Different warehouse connection properties per Org point at different data just as
    a schema variable does."""
    v = _var("CONNECTION_PROPERTY", [("ACME", "acme_db"), ("GLOBEX", "globex_db")])
    assert target_segmentation([v], "ACME") == SEGMENT_PHYSICAL


def test_a_USER_PROPERTY_variable_is_per_principal():
    """Resolved per user, so tenant separation is not an Org-level question at all."""
    assert target_segmentation([_var("USER_PROPERTY", [])], "ACME") == SEGMENT_PER_PRINCIPAL


def test_a_value_scoped_to_a_PRINCIPAL_is_per_principal():
    v = {"variable_type": "TABLE_MAPPING",
         "values": [{"org_identifier": "ACME", "value": "x",
                     "principal_identifier": "user1"}]}
    assert target_segmentation([v], "ACME") == SEGMENT_PER_PRINCIPAL


def test_no_readable_variables_is_UNKNOWN_not_assumed_safe():
    """Not knowing how a shared Model separates tenants is not the same as knowing it
    is fine."""
    assert target_segmentation([], "ACME") == SEGMENT_UNKNOWN


def test_a_variable_of_an_IRRELEVANT_type_does_not_imply_sharing():
    """A FORMULA_VARIABLE says nothing about physical location, so it must not be read as
    evidence that the Orgs share data."""
    assert target_segmentation([_var("FORMULA_VARIABLE", [("ACME", "x")])],
                               "ACME") == SEGMENT_UNKNOWN


# --- and what that means for the refusal ---

def test_physically_segmented_orgs_do_NOT_need_RLS():
    """The correction that matters: firing here would train operators to pass
    --allow-unfiltered-target reflexively, destroying the check where it counts."""
    assert unfiltered_target_problem({"SALES": 0}, "Sales",
                                     segmentation=SEGMENT_PHYSICAL) is None


def test_per_principal_segmentation_does_NOT_need_RLS():
    assert unfiltered_target_problem({"SALES": 0}, "Sales",
                                     segmentation=SEGMENT_PER_PRINCIPAL) is None


def test_SHARED_orgs_with_no_RLS_are_still_refused():
    problem = unfiltered_target_problem({"SALES": 0}, "Sales",
                                        segmentation=SEGMENT_SHARED)
    assert problem and "SAME physical data" in problem


def test_the_refusal_offers_the_SEGMENTATION_route_as_well_as_RLS():
    """Adding RLS is not the only fix, and an operator told only about RLS may add it
    where pointing the Orgs at different data is the better answer."""
    problem = unfiltered_target_problem({"SALES": 0}, "Sales", segmentation=SEGMENT_SHARED)
    assert "different data via the publication variable" in problem


def test_UNKNOWN_segmentation_refuses_regardless_of_rls():
    assert unfiltered_target_problem({"SALES": 5}, "Sales", segmentation=SEGMENT_UNKNOWN)


# ---------------------------------------------------------------------------
# Shielded content still has to MOVE — silent data loss otherwise
# ---------------------------------------------------------------------------

from ts_cli.migrate.apply_plan import STEP_MOVE_SHIELDED  # noqa: E402


def _plan_s(shielded, same_org=False):
    return build_apply_plan(
        {"source": "ACME", "target": "ACME NEW"},
        [{"guid": "v1", "name": "V"}], [{"guid": "a1", "name": "A"}],
        {"Segment": "STRING_1"}, {"guid": "tgt", "name": "PUBLISHED"},
        import_mode("ACME", "ACME" if same_org else "ACME NEW", "p", "p"),
        shielded=shielded)


def test_shielded_content_IS_MOVED_in_a_new_org_run():
    """Observed live 2026-07-28: excluding it entirely meant the tenant's Answer simply
    did not exist in the target. The shield removes the column REWRITE, not the move."""
    plan = _plan_s([{"guid": "s1", "name": "OnView", "source_refs": ["v1"]}])
    step = [s for s in plan if s["step"] == STEP_MOVE_SHIELDED][0]
    assert [o["guid"] for o in step["objects"]] == ["s1"]


def test_shielded_content_is_NOT_moved_in_a_same_org_run():
    """There is nowhere to move it to: it stays where it is, and the repointed View keeps
    working underneath it."""
    plan = _plan_s([{"guid": "s1", "name": "OnView", "source_refs": ["v1"]}],
                   same_org=True)
    assert [s for s in plan if s["step"] == STEP_MOVE_SHIELDED][0]["objects"] == []


def test_shielded_content_is_BACKED_UP_either_way():
    """It is in scope for the migration whether or not it moves, so losing it from the
    backup would remove the only copy in a same-Org rollback."""
    plan = _plan_s([{"guid": "s1", "name": "OnView", "source_refs": ["v1"]}],
                   same_org=True)
    assert "s1" in plan[0]["objects"]


def test_the_move_runs_LAST_because_it_needs_the_new_view_guids():
    order = list(STEP_ORDER)
    assert order.index(STEP_MOVE_SHIELDED) > order.index(STEP_REWRITE_VIEWS)


def test_the_dry_run_says_shielded_columns_are_UNCHANGED():
    """An operator seeing "1 object copied" alongside the rewrite steps could reasonably
    assume it was rewritten too."""
    md = render_plan(_plan_s([{"guid": "s1", "name": "OnView", "source_refs": ["v1"]}]))
    assert "columns UNCHANGED" in md


def test_the_dry_run_explains_the_empty_same_org_case():
    """"none" alone reads as "nothing was found", which would hide a scope error."""
    md = render_plan(_plan_s([{"guid": "s1", "name": "V", "source_refs": ["v1"]}],
                             same_org=True))
    assert "stays where it is" in md


# ---------------------------------------------------------------------------
# The segmentation check must read variables UNSCOPED
# ---------------------------------------------------------------------------

def test_segmentation_needs_ALL_orgs_values_to_see_segmentation():
    """Live-verified 2026-07-28: an ORG-SCOPED variable read returns only THAT Org's
    value. From inside ORG2, `apj_schema` looked like a single value and every target was
    classified SHARED -- so the check refused a correctly-segmented deployment.

    Same trap as `tenancy._groups_in_org`: an Org-scoped read is a FILTERED view, and
    treating it as complete inverts the answer. `apply` therefore reads through an
    unscoped session.
    """
    all_orgs = [_var("TABLE_MAPPING", [("Primary", "ALIAS_TESTS"),
                                       ("ORG2", "AMAZON_SALES_DATA")])]
    org_scoped = [_var("TABLE_MAPPING", [("ORG2", "AMAZON_SALES_DATA")])]
    assert target_segmentation(all_orgs, "ORG2") == SEGMENT_PHYSICAL
    # What the buggy Org-scoped read produced -- the exact inversion:
    assert target_segmentation(org_scoped, "ORG2") == SEGMENT_SHARED


def test_the_ctx_defaults_unscoped_to_the_target_rather_than_crashing():
    """A caller that forgets to pass one gets UNKNOWN/SHARED and a refusal, never a
    false pass."""
    from ts_cli.migrate.apply_exec import Ctx
    ctx = Ctx("src", "tgt", None, {})
    assert ctx.unscoped == "tgt"


def test_an_explicit_unscoped_client_is_used_when_given():
    from ts_cli.migrate.apply_exec import Ctx
    ctx = Ctx("src", "tgt", None, {}, unscoped_client="admin")
    assert ctx.unscoped == "admin"
