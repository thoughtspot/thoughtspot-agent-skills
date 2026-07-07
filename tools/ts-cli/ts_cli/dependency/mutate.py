"""ts_cli.dependency.mutate — pure TML mutation helpers behind `ts dependency mutate`.

Extracted from `agents/cli/ts-dependency-manager/SKILL.md` Step 9 (the mutation/import
engine, roughly lines 1150-1930) as part of BL-083 PR1 — codifying the skill's
safety-critical REMOVE/REPOINT logic into deterministic, tested Python instead of
inline pseudocode a model re-derives from prose on every run. This module is the PURE
half of that engine: dict -> dict transforms only, no network calls, no filesystem
I/O, no `ThoughtSpotClient` import. The I/O shell (export/import over the network,
backup file writes, rollback) lives in `ts_cli.commands.dependency`.

Contract, matching the pattern already established in `snowflake_ops.py` /
`spotql_ops.py`:

- The low-level helpers (`sanitize_search_query`, `remove_columns_from_*`,
  `repoint_*`) operate on a TML *section* dict (the `answer:` / `view:` / `model:` /
  `table:` body, not the full document) and MUTATE IT IN PLACE, returning the same
  object. This matches `test_dependency_helpers.py`'s `remove_columns_from_answer`
  contract (`test_mutates_in_place`: "New implementation mutates the dict in-place —
  caller must deepcopy before calling"). Every other low-level helper in this module
  follows the same contract for consistency, including `remove_columns_from_view` and
  the model-section helpers — none of which need their own internal deepcopy, because:
- The two top-level dispatchers (`apply_remove`, `apply_repoint`) take a FULL parsed
  TML document (the `.tml` object from `ts tml export --parse`, or a bare `{"tml":
  {...}}` item with the wrapper already unwrapped), `copy.deepcopy()` it ONCE at the
  boundary, route to the right low-level helper(s), and return the mutated copy. The
  original input is never touched — callers can safely mutate/re-use it.

Corrected-during-extraction bug (documented per the repo's audit precedent in
`snowflake_ops.py`'s `normalise_expr` docstring — fix latent bugs found while
extracting into a tested module, and say so): SKILL.md's inline
`remove_columns_from_answer` snippet (~line 1483) computes the formula-name set to
strip from `answer_columns` via `{f["name"] for f in a.get("formulas", []) if f["id"]
in formula_ids_to_remove}` in the SAME statement that reassigns `a["formulas"]` on the
line above — since `a["formulas"]` has already been overwritten with the FILTERED
list by the time that comprehension runs, the set is always empty and the `name`
condition is a no-op. `test_dependency_helpers.py`'s duplicate of this function computes
`formula_names` as a local BEFORE reassigning `a["formulas"]`, which is the intended
behaviour (a removed formula's display name must also be scrubbed from
`answer_columns`, in case a stray column entry references it by name rather than by
`formula_id`). This module follows the test file's corrected order, per this repo's
tie-break rule (test file is the executable/tested contract; SKILL.md prose can drift).

RENAME-mode helpers (`rename_in_search_query`, `rename_column_in_answer`,
`rename_column_in_view`, `rename_column_in_set`, `remove_model_joins` used only by the
rename path) are DELIBERATELY NOT extracted here. See the note at the top of
`agents/cli/ts-dependency-manager/SKILL.md`: RENAME is not supported by the skill
(TS's TML import API can apply a rename while still returning `status_code: ERROR`,
with no atomicity guarantee — open-item #15). Those functions are dead code for an
unsupported mode; porting them would just be carrying untested dead weight forward.
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any, Dict, Iterable, List, Optional

TmlSection = Dict[str, Any]
TmlDoc = Dict[str, Any]


# ---------------------------------------------------------------------------
# Search-query sanitization (SKILL.md ~1416)
# ---------------------------------------------------------------------------

def sanitize_search_query(query_str: Optional[str], cols_to_remove: Iterable[str]) -> str:
    """Strip `[col_name]` tokens from a ThoughtSpot search_query string.

    ThoughtSpot rejects the import of any Answer/View whose `search_query` still
    references a column that no longer exists (open-items.md #3) — this sanitizer
    is mandatory before removing a column from a dependent Answer or View.
    """
    if not query_str:
        return query_str
    for col in cols_to_remove:
        query_str = re.sub(r"\s*\[" + re.escape(col) + r"\]\s*", " ", query_str)
    return query_str.strip()


# ---------------------------------------------------------------------------
# Answer helpers (SKILL.md ~1434-1518)
# ---------------------------------------------------------------------------

def convert_answer_to_table(answer_dict: TmlSection) -> TmlSection:
    """Switch an Answer to TABLE_MODE so it remains valid after a chart-axis column
    is stripped. Mutates and returns `answer_dict`. Used for the REMOVE_CHART ->
    CONVERT_TO_TABLE fix path — skipping this is not an option for column-removal
    cleanup, since ThoughtSpot rejects the import at error 14544 if the column is
    still referenced by an active chart axis.
    """
    answer_dict["display_mode"] = "TABLE_MODE"
    return answer_dict


def _strip_answer_search_query(a: TmlSection, cols_to_remove: List[str]) -> None:
    """Sanitize `search_query` — MUST happen or ThoughtSpot will reject the import
    (open-items.md #3). Mutates `a` in place.
    """
    if a.get("search_query"):
        a["search_query"] = sanitize_search_query(a["search_query"], cols_to_remove)


def _strip_answer_columns(a: TmlSection, cols_to_remove: List[str]) -> None:
    """Remove matching entries from top-level `answer_columns[]`. Mutates `a` in place."""
    a["answer_columns"] = [
        c for c in a.get("answer_columns", [])
        if c.get("name") not in cols_to_remove
    ]


def _strip_answer_table_view(a: TmlSection, cols_to_remove: List[str]) -> None:
    """Strip `table.ordered_column_ids` and `table.table_columns`. Mutates `a` in place."""
    tbl = a.get("table", {})
    if tbl.get("ordered_column_ids"):
        tbl["ordered_column_ids"] = [
            c for c in tbl["ordered_column_ids"] if c not in cols_to_remove
        ]
    tbl["table_columns"] = [
        c for c in tbl.get("table_columns", [])
        if c.get("column_id") not in cols_to_remove
    ]


def _strip_answer_chart_view(a: TmlSection, cols_to_remove: List[str]) -> None:
    """Strip chart_columns and color/size/shape axis bindings ONLY — x/y axis
    removal requires removing the entire chart visualization; that decision is
    made one level up (Step 6 / the liveboard viz_decisions in apply_remove).
    Mutates `a` in place.
    """
    chart = a.get("chart", {})
    chart["chart_columns"] = [
        c for c in chart.get("chart_columns", [])
        if c.get("column_id") not in cols_to_remove
    ]
    for axis in chart.get("axis_configs", []):
        for key in ("color", "size", "shape"):  # x/y excluded — see REMOVE_CHART path
            if key in axis and isinstance(axis[key], list):
                axis[key] = [v for v in axis[key] if v not in cols_to_remove]


def _strip_answer_formulas(a: TmlSection, cols_to_remove: List[str]) -> None:
    """Remove formulas[] that reference a removed column, and any answer_columns[]
    entries for that formula, matched by formula_id OR by the formula's display
    name. Mutates `a` in place.
    """
    formula_ids_to_remove = {
        f["id"] for f in a.get("formulas", [])
        if any(col in f.get("expr", "") for col in cols_to_remove)
    }
    if formula_ids_to_remove:
        # Capture display names BEFORE reassigning a["formulas"] — see module
        # docstring's "Corrected-during-extraction bug" note.
        formula_names = {
            f["name"] for f in a.get("formulas", []) if f["id"] in formula_ids_to_remove
        }
        a["formulas"] = [f for f in a.get("formulas", []) if f["id"] not in formula_ids_to_remove]
        a["answer_columns"] = [
            c for c in a.get("answer_columns", [])
            if c.get("formula_id") not in formula_ids_to_remove
            and c.get("name") not in formula_names
        ]


def _strip_answer_cohorts(a: TmlSection, cols_to_remove: List[str]) -> None:
    """Remove answer-level cohorts (sets) whose anchor_column_id is being removed.
    The set's display name also appears in answer_columns[] and may be in
    search_query. Mutates `a` in place.
    """
    set_names_to_remove = {
        c["name"] for c in a.get("cohorts", [])
        if c.get("config", {}).get("anchor_column_id") in cols_to_remove
    }
    if set_names_to_remove:
        a["cohorts"] = [
            c for c in a.get("cohorts", [])
            if c["name"] not in set_names_to_remove
        ]
        a["answer_columns"] = [
            c for c in a.get("answer_columns", [])
            if c.get("name") not in set_names_to_remove
        ]
        if a.get("search_query"):
            a["search_query"] = sanitize_search_query(
                a["search_query"], list(set_names_to_remove)
            )


def remove_columns_from_answer(answer_dict: TmlSection, cols_to_remove: List[str]) -> TmlSection:
    """Remove column references from an Answer TML section (the `answer:` body).

    Mutates `answer_dict` in place and returns it — caller is responsible for
    deepcopy-ing beforehand if the original must be preserved (see module docstring).

    Handles: search_query, answer_columns[], table view (ordered_column_ids +
    table_columns), chart view (chart_columns + color/size/shape axis bindings
    ONLY — x/y axis removal requires removing the entire visualization, handled by
    the REMOVE_CHART decision path one level up), formulas[] that reference a
    removed column (and any answer_columns[] entries for that formula, matched by
    formula_id OR by the formula's display name), and answer-level cohorts (sets)
    whose anchor_column_id is being removed.
    """
    a = answer_dict

    _strip_answer_search_query(a, cols_to_remove)
    _strip_answer_columns(a, cols_to_remove)
    _strip_answer_table_view(a, cols_to_remove)
    _strip_answer_chart_view(a, cols_to_remove)
    _strip_answer_formulas(a, cols_to_remove)
    _strip_answer_cohorts(a, cols_to_remove)

    return a


# ---------------------------------------------------------------------------
# View helpers (SKILL.md ~1780-1811)
# ---------------------------------------------------------------------------

def _strip_view_search_query(v: TmlSection, cols_to_remove: List[str]) -> None:
    """Sanitize `search_query` (same rule as Answers — open-items.md #3). Mutates
    `v` in place.
    """
    if v.get("search_query"):
        v["search_query"] = sanitize_search_query(v["search_query"], cols_to_remove)


def _strip_view_columns(v: TmlSection, cols_to_remove: List[str]) -> None:
    """Remove `view_columns[]` entries whose column_id references the removed
    column (matched by substring — real view column_ids are prefixed, e.g.
    `Orders_1::Revenue`) OR whose name exactly matches. Mutates `v` in place.
    """
    v["view_columns"] = [
        c for c in v.get("view_columns", [])
        if not any(col in c.get("column_id", "") for col in cols_to_remove)
        and c.get("name") not in cols_to_remove
    ]


def _strip_view_formulas(v: TmlSection, cols_to_remove: List[str]) -> None:
    """Remove formulas[] whose expr references a removed column, and their
    view_columns[] entries (matched by column_id == formula_id). Mutates `v` in
    place.
    """
    formula_ids_to_remove = {
        f["id"] for f in v.get("formulas", [])
        if any(col in f.get("expr", "") for col in cols_to_remove)
    }
    if formula_ids_to_remove:
        v["formulas"] = [f for f in v.get("formulas", []) if f["id"] not in formula_ids_to_remove]
        v["view_columns"] = [
            c for c in v.get("view_columns", []) if c.get("column_id") not in formula_ids_to_remove
        ]


def _strip_view_joins(v: TmlSection, cols_to_remove: List[str]) -> None:
    """Remove joins[] whose `on` expression references a removed column. Mutates
    `v` in place.
    """
    v["joins"] = [
        j for j in v.get("joins", [])
        if not any(col in j.get("on", "") for col in cols_to_remove)
    ]


def remove_columns_from_view(view_dict: TmlSection, cols_to_remove: List[str]) -> TmlSection:
    """Remove column references from a View TML section (the `view:` body).

    Mutates `view_dict` in place and returns it. Handles: search_query,
    view_columns[] (matched by substring on column_id — real view column_ids are
    prefixed, e.g. `Orders_1::Revenue` — OR exact match on name), formulas[] that
    reference a removed column (and their view_columns[] entries, matched by
    column_id == formula_id), and joins[] whose `on` expression references a
    removed column.
    """
    v = view_dict

    _strip_view_search_query(v, cols_to_remove)
    _strip_view_columns(v, cols_to_remove)
    _strip_view_formulas(v, cols_to_remove)
    _strip_view_joins(v, cols_to_remove)

    return v


# ---------------------------------------------------------------------------
# Model / Worksheet section helper — unifies SKILL.md ~1334 (source removal) and
# fix_model() ~1882 (dependent Model removal). Both call sites are identical logic.
# ---------------------------------------------------------------------------

def _references_column(text: Optional[str], cols_to_remove: Iterable[str]) -> bool:
    """True if `text` references any of `cols_to_remove` as a whole token.

    Uses a word-boundary match (no alphanumeric/underscore on either side) so a
    reference to the base column name inside a qualified `TABLE::COLUMN` id or a
    `[TABLE::COLUMN]` formula token is caught, WITHOUT false-matching a longer name
    that merely contains it (e.g. removing `CATEGORY_NAME` must not match
    `SUB_CATEGORY_NAME` or `DM_CATEGORY::CATEGORY_NAME_FULL`).

    This is why the model helper below can strip a base-table column from a dependent
    Model even when the Model exposes it under a friendly alias — the column entry has
    `name: "Product Category"` but `column_id: "DM_CATEGORY::CATEGORY_NAME"`, and the
    Model's measure formulas reference `[DM_CATEGORY::CATEGORY_NAME]` in their expr.
    Matching on `name` alone (the pre-BL-083-PR2 behaviour) missed both — found live
    on se-thoughtspot, open-items #24.
    """
    if not text:
        return False
    return any(
        re.search(r"(?<![A-Za-z0-9_])" + re.escape(col) + r"(?![A-Za-z0-9_])", text)
        for col in cols_to_remove
    )


def _model_column_targeted(col: TmlSection, cols_to_remove: Iterable[str]) -> bool:
    """A model column is targeted for removal if its `name` is in `cols_to_remove` OR
    its `column_id` references one of them as a whole token — so an aliased exposure of
    a base column (`name: "Product Category"`, `column_id: "DM_CATEGORY::CATEGORY_NAME"`)
    is caught; matching `name` alone missed it (open-items #24)."""
    return (col.get("name") in cols_to_remove
            or _references_column(col.get("column_id", ""), cols_to_remove))


def _model_removed_formula_ids(section: TmlSection, cols_to_remove: List[str]) -> set:
    """Formula ids to drop from a model section: those backing a targeted column (its
    `formula_id`), plus those whose `expr` references a removed column."""
    from_columns = {
        c.get("formula_id") for c in section.get("columns", [])
        if _model_column_targeted(c, cols_to_remove) and c.get("formula_id")
    }
    return {
        f.get("id") for f in section.get("formulas", [])
        if f.get("id") in from_columns or _references_column(f.get("expr", ""), cols_to_remove)
    }


def remove_columns_from_model_section(section: TmlSection, cols_to_remove: List[str]) -> TmlSection:
    """Strip columns from a Model/Worksheet TML section (the `model:`/`worksheet:` body).

    Mutates `section` in place and returns it. A column is targeted (see
    `_model_column_targeted`) by `name` OR `column_id` whole-token match, so an aliased
    exposure of a base column is caught (matching `name` alone missed it, open-items #24).
    Handles:

    - columns[]: removes targeted columns.
    - formulas[]: removes a formula backing a removed column OR whose `expr` references a
      removed column (`_model_removed_formula_ids`); then cascades once — any column
      backed by a now-removed formula is dropped too (an orphaned measure column would
      otherwise reference a missing formula).
    - model_tables[].joins whose `on` clause references a removed column (required — TS
      rejects an import with an orphaned join condition, open-items.md #4).
    - model-level filters[] whose `column` list references a removed column (required —
      TS rejects with error_code 14518 "Invalid filter column", open-items.md #12).

    Note: `model_tables` entries use `joins` (both the Scenario A referencing form and
    the Scenario B inline form) — `joins_with` only exists at the table/view level,
    never on `model_tables`, so only `joins` is checked here.
    """
    m = section
    removed_formula_ids = _model_removed_formula_ids(m, cols_to_remove)

    m["formulas"] = [f for f in m.get("formulas", []) if f.get("id") not in removed_formula_ids]
    m["columns"] = [
        c for c in m.get("columns", [])
        if not _model_column_targeted(c, cols_to_remove)
        and c.get("formula_id") not in removed_formula_ids
    ]
    for tbl in m.get("model_tables", []):
        tbl["joins"] = [
            j for j in tbl.get("joins", [])
            if not _references_column(j.get("on", ""), cols_to_remove)
        ]
    m["filters"] = [
        f for f in m.get("filters", [])
        if not any(_references_column(c, cols_to_remove) for c in f.get("column", []))
    ]
    return m


# ---------------------------------------------------------------------------
# Connection Table helper (SKILL.md ~1375)
# ---------------------------------------------------------------------------

def remove_columns_from_table_section(table_section: TmlSection, cols_to_remove: List[str]) -> TmlSection:
    """Strip columns from a connection Table TML section (the `table:` body).

    Mutates `table_section` in place and returns it.
    """
    table_section["columns"] = [
        c for c in table_section.get("columns", [])
        if c.get("name") not in cols_to_remove
    ]
    return table_section


# ---------------------------------------------------------------------------
# Feedback helper (SKILL.md ~1859)
# ---------------------------------------------------------------------------

def remove_columns_from_feedback(feedback_section: TmlSection, cols_to_remove: List[str]) -> TmlSection:
    """Drop `nls_feedback.feedback[]` entries that reference a removed column.

    An entry is dropped if any removed column name appears anywhere in
    `json.dumps(entry)` — feedback entries embed column references in several
    different nested shapes (search_tokens, formula_info, ...), so a whole-entry
    text scan is the only reliable way to catch all of them (matches SKILL.md's
    approach exactly). Mutates `feedback_section` in place and returns it.
    """
    entries = feedback_section.get("feedback", [])
    feedback_section["feedback"] = [
        e for e in entries
        if not any(col in json.dumps(e) for col in cols_to_remove)
    ]
    return feedback_section


# ---------------------------------------------------------------------------
# Repoint helpers (SKILL.md ~1529-1661) — obj_id-first matching with fqn fallback.
# ---------------------------------------------------------------------------

def repoint_answer(
    answer_dict: TmlSection,
    source_guid: Optional[str],
    target_guid: str,
    target_name: str,
    column_gap: List[str],
    *,
    source_obj_id: Optional[str] = None,
    target_obj_id: Optional[str] = None,
) -> TmlSection:
    """Update an Answer TML body's `tables[]` entry to point at `target_guid`/
    `target_obj_id` instead of `source_guid`/`source_obj_id`, then remove any
    `column_gap` columns absent from the target. Mutates and returns `answer_dict`.

    Matching prefers obj_id (when `source_obj_id` is given) over fqn — this avoids
    VERSION_CONFLICT (error 14009) on builds that track content versions via obj_id.
    """
    a = answer_dict

    for tbl in a.get("tables", []):
        matched = False
        if source_obj_id and tbl.get("obj_id") == source_obj_id:
            matched = True
        elif tbl.get("fqn") == source_guid:
            matched = True

        if matched:
            if target_obj_id:
                tbl["obj_id"] = target_obj_id
                tbl.pop("fqn", None)
            else:
                tbl["fqn"] = target_guid
                tbl.pop("obj_id", None)
            tbl["name"] = target_name
            tbl["id"] = target_name

    if column_gap:
        a = remove_columns_from_answer(a, column_gap)

    return a


def _repoint_view_tables(
    v: TmlSection,
    source_guid: Optional[str],
    target_guid: str,
    target_name: str,
    *,
    source_obj_id: Optional[str],
    target_obj_id: Optional[str],
) -> Optional[str]:
    """Update `v["tables"]` entries matching `source_guid`/`source_obj_id` to point
    at the target. Returns the matched entry's original display name (or None if
    no entry matched) so the caller can rename table_paths[]/joins[] references.
    Mutates `v` in place.
    """
    old_name = None
    for tbl in v.get("tables", []):
        matched = False
        if source_obj_id and tbl.get("obj_id") == source_obj_id:
            matched = True
        elif tbl.get("fqn") == source_guid:
            matched = True

        if matched:
            old_name = tbl.get("name")
            if tbl.get("id") == old_name:
                tbl["id"] = target_name
            if target_obj_id:
                tbl["obj_id"] = target_obj_id
                tbl.pop("fqn", None)
            else:
                tbl["fqn"] = target_guid
                tbl.pop("obj_id", None)
            tbl["name"] = target_name

    return old_name


def _rename_view_table_refs(v: TmlSection, old_name: Optional[str], target_name: str) -> None:
    """Rename the old table reference in `table_paths[]`/`joins[]`
    (source/destination) when the table's display name changes. Mutates `v` in
    place.
    """
    if not old_name or old_name == target_name:
        return
    for tp in v.get("table_paths", []):
        if tp.get("table") == old_name:
            tp["table"] = target_name
    for j in v.get("joins", []):
        if j.get("source") == old_name:
            j["source"] = target_name
        if j.get("destination") == old_name:
            j["destination"] = target_name


def repoint_view(
    view_dict: TmlSection,
    source_guid: Optional[str],
    target_guid: str,
    target_name: str,
    column_gap: List[str],
    *,
    source_obj_id: Optional[str] = None,
    target_obj_id: Optional[str] = None,
) -> TmlSection:
    """Update a View TML body to point at `target_guid` instead of `source_guid`.

    Prefers obj_id matching when available (avoids VERSION_CONFLICT / error 14009).
    Falls back to fqn when obj_id is absent. Also renames the old table reference in
    `table_paths[]`/`joins[]` (source/destination) when the table's display name
    changes. Mutates and returns `view_dict`.
    """
    v = view_dict

    old_name = _repoint_view_tables(
        v, source_guid, target_guid, target_name,
        source_obj_id=source_obj_id, target_obj_id=target_obj_id,
    )
    _rename_view_table_refs(v, old_name, target_name)

    if column_gap:
        v = remove_columns_from_view(v, column_gap)

    return v


def _repoint_model_tables(
    m: TmlSection,
    source_name: Optional[str],
    target_name: str,
    *,
    source_obj_id: Optional[str],
    target_obj_id: Optional[str],
    source_guid: Optional[str],
    target_guid: Optional[str],
) -> None:
    """Update `model_tables[]` entries matching source (obj_id, then fqn, then
    name) to point at the target, and rewrite that table's `joins`/`joins_with`
    `with`/`on` references from `source_name` to `target_name`. Mutates `m` in
    place.
    """
    for tbl in m.get("model_tables", []):
        matched = False
        if source_obj_id and tbl.get("obj_id") == source_obj_id:
            matched = True
        elif source_guid and tbl.get("fqn") == source_guid:
            matched = True
        elif tbl.get("name") == source_name:
            matched = True

        if matched:
            tbl["name"] = target_name
            if target_obj_id:
                tbl["obj_id"] = target_obj_id
                tbl.pop("fqn", None)
            elif target_guid:
                tbl["fqn"] = target_guid
                tbl.pop("obj_id", None)

        for join_key in ("joins", "joins_with"):
            for j in tbl.get(join_key, []):
                if j.get("with") == source_name:
                    j["with"] = target_name
                on_clause = j.get("on", "")
                if source_name and f"[{source_name}::" in on_clause:
                    j["on"] = on_clause.replace(
                        f"[{source_name}::", f"[{target_name}::")


def _repoint_model_columns(m: TmlSection, source_name: Optional[str], target_name: str) -> None:
    """Rewrite `columns[].column_id` prefixes from `source_name::` to
    `target_name::`. Mutates `m` in place.
    """
    for col in m.get("columns", []):
        cid = col.get("column_id", "")
        if source_name and cid.startswith(f"{source_name}::"):
            col["column_id"] = cid.replace(
                f"{source_name}::", f"{target_name}::", 1)


def _repoint_model_formulas(m: TmlSection, source_name: Optional[str], target_name: str) -> None:
    """Rewrite `formulas[].expr` references from `[source_name::` to
    `[target_name::`. Mutates `m` in place.
    """
    for formula in m.get("formulas", []):
        expr = formula.get("expr", "")
        if source_name and f"[{source_name}::" in expr:
            formula["expr"] = expr.replace(
                f"[{source_name}::", f"[{target_name}::")


def _repoint_model_description(m: TmlSection, source_name: Optional[str], target_name: str) -> None:
    """Replace any mention of `source_name` in `description` with `target_name`.
    Mutates `m` in place.
    """
    desc = m.get("description", "")
    if source_name and source_name in desc:
        m["description"] = desc.replace(source_name, target_name)


def repoint_model(
    model_dict: TmlSection,
    source_name: Optional[str],
    target_name: str,
    column_gap: List[str],
    *,
    source_obj_id: Optional[str] = None,
    target_obj_id: Optional[str] = None,
    source_guid: Optional[str] = None,
    target_guid: Optional[str] = None,
) -> TmlSection:
    """Repoint a Model's `model_tables[]` entry from source to target.

    Updates model_tables obj_id/fqn/name, joins `with`/`on` clauses, column_id
    prefixes, formula expressions, and any mention of `source_name` in the
    description. Prefers obj_id when available; falls back to fqn, then to a name
    match. Mutates and returns `model_dict`.
    """
    m = model_dict

    _repoint_model_tables(
        m, source_name, target_name,
        source_obj_id=source_obj_id, target_obj_id=target_obj_id,
        source_guid=source_guid, target_guid=target_guid,
    )
    _repoint_model_columns(m, source_name, target_name)
    _repoint_model_formulas(m, source_name, target_name)
    _repoint_model_description(m, source_name, target_name)

    if column_gap:
        m = remove_columns_from_model_section(m, column_gap)

    return m


# ---------------------------------------------------------------------------
# Top-level dispatchers — take a FULL parsed TML document (single top-level type
# key, optionally with nls_feedback), deepcopy it once, route to the right
# helper(s), and return the mutated copy. See module docstring for the contract.
# ---------------------------------------------------------------------------

def _apply_remove_liveboard(
    liveboard: TmlSection,
    cols_to_remove: List[str],
    source_guid: Optional[str],
    viz_decisions: Dict[str, str],
) -> TmlSection:
    """REMOVE-path liveboard handling (SKILL.md ~1704-1761), simplified for the
    pure-mutate contract: the full skill additionally classifies each viz's chart
    role (X_AXIS/Y_AXIS/COLOR_BINDING/...) in Step 4/6 to decide whether a viz even
    NEEDS a decision; that classification requires context this module doesn't have
    (chart role classification lives in Step 4, not Step 9, and is out of scope for
    this extraction — see BL-083 PR1 scope note). Here every viz whose answer
    references `source_guid` (or every viz, when `source_guid` is None) gets an
    explicit decision from `viz_decisions` (default "CONVERT_TO_TABLE").
    """
    lb = liveboard
    vizzes_to_remove = set()

    for viz in lb.get("visualizations", []):
        viz_id = viz.get("id", "")
        answer = viz.get("answer", {})
        tables = answer.get("tables", [])
        targets_source = source_guid is None or any(t.get("fqn") == source_guid for t in tables)
        if not targets_source:
            continue

        decision = viz_decisions.get(viz_id, "CONVERT_TO_TABLE")
        if decision == "REMOVE":
            vizzes_to_remove.add(viz_id)
            continue

        # CONVERT_TO_TABLE (default): switch this viz's display_mode and strip the column.
        answer = convert_answer_to_table(answer)
        answer = remove_columns_from_answer(answer, cols_to_remove)
        viz["answer"] = answer

    if vizzes_to_remove:
        lb["visualizations"] = [
            v for v in lb.get("visualizations", [])
            if v.get("id") not in vizzes_to_remove
        ]

    # Liveboard-level filter updates — a filter whose column list is fully emptied
    # is dropped entirely.
    updated_filters = []
    for filt in lb.get("filters", []):
        new_cols = [c for c in filt.get("column", []) if c not in cols_to_remove]
        if new_cols:
            filt["column"] = new_cols
            updated_filters.append(filt)
    lb["filters"] = updated_filters

    return lb


def apply_remove(
    tml_doc: TmlDoc,
    cols_to_remove: List[str],
    *,
    source_guid: Optional[str] = None,
    viz_decisions: Optional[Dict[str, str]] = None,
) -> TmlDoc:
    """Apply a REMOVE operation to a full parsed TML document.

    `tml_doc` is the `.tml` object from `ts tml export --parse` (a dict with exactly
    one top-level type key from `answer|model|worksheet|view|table|liveboard`,
    optionally plus `nls_feedback`). Deepcopies `tml_doc` once, routes to the
    matching low-level helper, and returns the mutated copy — the input is never
    touched.

    `source_guid`/`viz_decisions` are liveboard-only: `viz_decisions` maps
    `{viz_id: "CONVERT_TO_TABLE" | "REMOVE"}` (default "CONVERT_TO_TABLE" for any viz
    not in the map). When `source_guid` is None for a liveboard, every visualization
    is treated as targeting the source (useful when the caller already pre-filtered
    to only the relevant liveboard).
    """
    doc = copy.deepcopy(tml_doc)
    viz_decisions = viz_decisions or {}

    if "answer" in doc:
        doc["answer"] = remove_columns_from_answer(doc["answer"], cols_to_remove)
    elif "view" in doc:
        doc["view"] = remove_columns_from_view(doc["view"], cols_to_remove)
    elif "model" in doc:
        doc["model"] = remove_columns_from_model_section(doc["model"], cols_to_remove)
    elif "worksheet" in doc:
        doc["worksheet"] = remove_columns_from_model_section(doc["worksheet"], cols_to_remove)
    elif "table" in doc:
        doc["table"] = remove_columns_from_table_section(doc["table"], cols_to_remove)
    elif "liveboard" in doc:
        doc["liveboard"] = _apply_remove_liveboard(
            doc["liveboard"], cols_to_remove, source_guid, viz_decisions,
        )

    if "nls_feedback" in doc:
        doc["nls_feedback"] = remove_columns_from_feedback(doc["nls_feedback"], cols_to_remove)

    return doc


def apply_repoint(
    tml_doc: TmlDoc,
    *,
    source_guid: Optional[str],
    target_guid: str,
    target_name: str,
    column_gap: List[str],
    source_obj_id: Optional[str] = None,
    target_obj_id: Optional[str] = None,
) -> TmlDoc:
    """Apply a REPOINT operation to a full parsed TML document.

    `tml_doc` is the `.tml` object from `ts tml export --parse` (a dict with exactly
    one top-level type key from `answer|model|worksheet|view|table|liveboard`).
    Deepcopies `tml_doc` once, routes to the matching low-level helper(s), and
    returns the mutated copy — the input is never touched.

    Routing: answer -> repoint_answer; view -> repoint_view; model/worksheet ->
    repoint_model (using the section's own `name` as `source_name`); liveboard ->
    repoint_answer applied to every visualization whose answer references
    `source_guid`. `table` documents are not repoint targets (a Table is always the
    REPOINT source/target reference, never itself repointed) and pass through
    unchanged.
    """
    doc = copy.deepcopy(tml_doc)

    if "answer" in doc:
        doc["answer"] = repoint_answer(
            doc["answer"], source_guid, target_guid, target_name, column_gap,
            source_obj_id=source_obj_id, target_obj_id=target_obj_id,
        )
    elif "view" in doc:
        doc["view"] = repoint_view(
            doc["view"], source_guid, target_guid, target_name, column_gap,
            source_obj_id=source_obj_id, target_obj_id=target_obj_id,
        )
    elif "model" in doc:
        section = doc["model"]
        doc["model"] = repoint_model(
            section, section.get("name"), target_name, column_gap,
            source_obj_id=source_obj_id, target_obj_id=target_obj_id,
            source_guid=source_guid, target_guid=target_guid,
        )
    elif "worksheet" in doc:
        section = doc["worksheet"]
        doc["worksheet"] = repoint_model(
            section, section.get("name"), target_name, column_gap,
            source_obj_id=source_obj_id, target_obj_id=target_obj_id,
            source_guid=source_guid, target_guid=target_guid,
        )
    elif "liveboard" in doc:
        lb = doc["liveboard"]
        for viz in lb.get("visualizations", []):
            answer = viz.get("answer", {})
            tables = answer.get("tables", [])
            if any(t.get("fqn") == source_guid for t in tables):
                viz["answer"] = repoint_answer(
                    answer, source_guid, target_guid, target_name, column_gap,
                    source_obj_id=source_obj_id, target_obj_id=target_obj_id,
                )

    return doc
