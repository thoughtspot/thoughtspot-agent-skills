"""Name-collision detection and resolution across columns, formulas,
parameters, and SQL View / relation names produced during Tableau →
ThoughtSpot conversion.
"""
from __future__ import annotations

from ts_cli.formula_common import resolve_name_collisions  # noqa: F401 — moved (BL-063 PR 5)


# ---------------------------------------------------------------------------
# 20. Column/formula name clash detection (BL-046 #7 / BL-050 #9)
# ---------------------------------------------------------------------------

def detect_name_clashes(
    formula_names: set[str],
    column_names: set[str],
) -> dict[str, str]:
    """Detect case-insensitive collisions between formula and column names.

    Returns: { formula_name: suggested_rename }
    """
    col_upper = {c.upper(): c for c in column_names}
    clashes: dict[str, str] = {}
    for fname in formula_names:
        if fname.upper() in col_upper:
            clashes[fname] = f"Formula {fname}"
    return clashes


def apply_name_clash_renames(expr: str, name_clashes: dict[str, str]) -> str:
    """Update ``[formula_X]`` references in *expr* when X was renamed by name-clash detection."""
    for original, renamed in name_clashes.items():
        old_ref = f"[formula_{original}]"
        new_ref = f"[formula_{renamed}]"
        if old_ref in expr:
            expr = expr.replace(old_ref, new_ref)
    return expr


# ---------------------------------------------------------------------------
# Cross-datasource SQL View name disambiguation (SCAL-339750)
# ---------------------------------------------------------------------------

def _sql_view_owns_column(sql_view: dict, column: str) -> bool:
    """True when *column* is one of *sql_view*'s own output columns.

    A view's column is recorded twice — ``name`` (the Tableau caption) and
    ``sql_output_column`` (the remote/physical name) — and a reference may be
    written either way, so both are matched, case-insensitively as everywhere
    else here. Used only to attribute a reference whose relation name is
    ambiguous; see ``_rename_sql_view_in_datasource``.
    """
    if not column:
        return False
    wanted = column.lower()
    return any(
        wanted in {(c.get("name") or "").lower(), (c.get("sql_output_column") or "").lower()}
        for c in sql_view.get("columns") or []
    )


def _rename_sql_view_in_datasource(ds: dict, old: str, new: str) -> None:
    """Apply one SQL View rename across every field in *ds* that carries the name.

    Four surfaces, all keyed off the same string — see
    ``disambiguate_sql_view_names`` for why renaming them here is sufficient:

      1. ``sql_views[].name``   — the emitted ``sql_view:`` TML name, and the
         name ``_sql_view_model_tables`` / ``_sql_view_model_columns`` build
         ``model_tables[].name``, ``column_id`` and join ``on:`` refs from.
      2. ``col_table_map``      — column -> owning relation; the formula
         translator reads this to emit ``[Table::Column]`` refs, so renaming it
         here is what makes translated formulas land on the new name.
      3. ``joins[].left_table`` / ``right_table`` — join endpoints.
      4. ``columns[].table``    — per-column ownership (from the metadata
         record's ``parent-name``). Most Custom-SQL columns are dropped by
         ``_drop_sql_view_shadowed_columns`` before the model is assembled, but
         one the view does not re-expose would otherwise keep the stale name and
         emit a dangling ``column_id``.

    The SQL body and ``sql_output_column`` are deliberately untouched — the
    rename is a ThoughtSpot object-name concern, not a warehouse one.

    Surfaces 2-4 record ownership as a bare relation NAME, so if this datasource
    also declares a PHYSICAL TABLE called ``old`` those entries are ambiguous —
    they belong to the table and to the view alike, and rewriting them all
    repoints the table's own columns and join endpoints at the view. Tableau
    does not produce that shape (a relation name is unique within a datasource,
    across relation types), but the function is public and must not corrupt the
    table if it ever meets one. When the name is ambiguous each reference is
    therefore attributed first — a column by whether the VIEW declares it
    (``_sql_view_owns_column``), a join endpoint by whether that side's key
    column belongs to the view — and anything not attributable to the view is
    left on the physical table. When the name is unambiguous (every real
    workbook) nothing is attributed and the rewrite is unconditional, exactly
    as before.

    The comparison is EXACT, unlike the contested-name test in
    ``disambiguate_sql_view_names``, which lowercases because ThoughtSpot is
    case-insensitive on object names. Ambiguity here is a property of the parse
    representation, where surfaces 2-4 hold an exact string: ``Orders`` and
    ``orders`` are distinguishable keys there, so there is nothing to attribute
    and the rewrite stays unconditional. Matching loosely would withhold the
    rename from a view column the parse did not list, repointing it at the
    physical table.

    Surfaces 2-4 are applied by ``_rename_column_owners`` and
    ``_rename_join_endpoints``; they are split out only to keep each piece under
    the complexity cap, and carry no logic this function did not already have.
    """
    view = next((sv for sv in ds.get("sql_views") or [] if sv.get("name") == old), None)
    ambiguous = view is not None and any(
        (t.get("name") or "") == old for t in ds.get("tables") or []
    )

    def owned(column: str | None) -> bool:
        return _sql_view_owns_column(view, column or "") if ambiguous else True

    for sv in ds.get("sql_views") or []:                      # surface 1
        if sv.get("name") == old:
            sv["name"] = new
    _rename_column_owners(ds, old, new, owned)                # surfaces 2 and 4
    _rename_join_endpoints(ds, old, new, owned, ambiguous)    # surface 3


def _rename_column_owners(ds: dict, old: str, new: str, owned) -> None:
    """Surfaces 2 and 4 of ``_rename_sql_view_in_datasource`` — the two places a
    column records its owning relation by name (``col_table_map`` values and
    ``columns[].table``). ``owned`` decides attribution; it is constantly true
    when the name is unambiguous."""
    col_table_map = ds.get("col_table_map") or {}
    for col, table in col_table_map.items():
        if table == old and owned(col):
            col_table_map[col] = new
    for c in ds.get("columns") or []:
        if c.get("table") == old and owned(c.get("name")):
            c["table"] = new


def _rename_join_endpoints(ds: dict, old: str, new: str, owned, ambiguous: bool) -> None:
    """Surface 3 of ``_rename_sql_view_in_datasource`` — a join endpoint, which
    (unlike a column) carries no name of its own, so an ambiguous one is
    attributed by whether THAT side's key column belongs to the view. A clause
    with no keys is therefore left on the physical table."""
    for j in ds.get("joins") or []:
        for side, key in (("left_table", "left"), ("right_table", "right")):
            if j.get(side) != old:
                continue
            if ambiguous and not any(owned(k.get(key)) for k in j.get("keys") or []):
                continue
            j[side] = new


def disambiguate_sql_view_names(datasources: list[dict]) -> list[dict]:
    """Make every emitted SQL View name unique across the whole workbook.

    Tableau names an unnamed Custom SQL relation ``Custom SQL Query`` and numbers
    later ones *within the same datasource* (``Custom SQL Query1``, ...), so the
    name is unique per datasource and nothing more. ``build-model`` emits every
    datasource of a workbook into ONE output directory and one ThoughtSpot
    namespace, where ``model_tables[].name`` resolves by name against a single
    Table/SQL-View namespace — so N datasources that each contain an unnamed
    Custom SQL relation produced N SQL View documents all called
    ``Custom SQL Query``, each model pointing at an ambiguous object. The
    filenames were already disambiguated by datasource slug; the object names
    were not. Found by an audit of real Tableau workbooks, where several
    datasources each declaring an unnamed Custom SQL relation emitted views under
    one name and the models built from them resolved against whichever imported
    last. Reproduce by constructing that shape — two datasources, each carrying
    one unnamed ``<relation type='text'>``.

    A name is CONTESTED when more than one datasource declares it, or when a
    PHYSICAL table anywhere in the workbook claims it (the table keeps the name —
    it must match the warehouse object, so a table is never renamed). A contested
    name is resolved by qualifying EVERY owning SQL View; an uncontested one is
    left exactly as written, so a workbook with no collision is untouched.

    Qualifying every owner — rather than letting the first keep the bare name —
    is what makes the result stable ACROSS DATASOURCES: inserting, removing or
    reordering an unrelated datasource cannot rename a view. Under the
    first-owner-wins rule it could: adding a datasource ahead of ``Goals`` moved
    the bare name to the newcomer and renamed ``Goals``, which on a re-migration
    silently repoints every object bound to the old name. (A name going from
    uncontested to contested still renames — that is inherent, since an
    uncontested name is by definition left alone.)

    That is the guarantee, and it is not absolute order-independence. Two views
    in ONE datasource whose names differ only in case share a qualifier, so
    which one is ``Base (D)`` and which is ``Base (D 2)`` follows their
    declaration order. It is deterministic for a given workbook, and either
    outcome is internally consistent — every rewrite keys on the view's own
    exact spelling, so its references follow whichever name it received — but
    re-saving the workbook with those two relations reordered can swap them.
    Tableau numbers sibling relations rather than case-varying them, so the
    pair has to be hand-renamed to arise at all.

    Renames use the repo's existing collision idiom — ``Base (Qualifier)`` then
    ``Base (Qualifier N)``, as ``qlik/build_model.py`` and ``powerbi/build_model.py``
    use for colliding columns and as Tableau itself uses for colliding captions
    (``BEHAVIOR (Custom SQL Query2)``). The qualifier is the owning datasource
    name. The ordinal fallback fires only when that exact qualified string is
    already claimed by some other view.

    Comparison is case-insensitive because ThoughtSpot is case-insensitive on
    object names — two views differing only in case would still be ambiguous.

    Called once per ``build-model`` invocation, on the FULL datasource list
    before any ``--datasource`` filter, so a given datasource's view gets the
    same name whether or not the run was filtered. Mutates and returns
    *datasources* (same list) so it can wrap the assignment at the call site.
    """
    physical = {
        t["name"].lower()
        for ds in datasources
        for t in (ds.get("tables") or [])
        if t.get("name")
    }
    # Keyed case-insensitively (see above) but carrying each owner's OWN
    # spelling, so a rename preserves how that datasource wrote the name.
    owners: dict[str, list[tuple[dict, str]]] = {}
    for ds in datasources:
        for sv in ds.get("sql_views") or []:
            if sv.get("name"):
                owners.setdefault(sv["name"].lower(), []).append((ds, sv["name"]))

    taken = set(physical) | set(owners)
    for key, ds_list in owners.items():
        if len(ds_list) < 2 and key not in physical:
            continue                      # uncontested — leave it exactly as written
        for ds, name in ds_list:
            candidate = f"{name} ({ds['name']})"
            n = 2
            while candidate.lower() in taken:
                candidate = f"{name} ({ds['name']} {n})"
                n += 1
            taken.add(candidate.lower())
            _rename_sql_view_in_datasource(ds, name, candidate)
    return datasources
