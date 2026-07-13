"""RLS extraction, grain-conflict detection, and propagation onto an aggregate table.

Pure functions, no I/O, Python 3.9. Task 22 — the skill previously only GATED on
base-table row-level security (refused to import until the user manually
replicated the rule elsewhere); this module instead lets the skill (Task 23,
not this one) auto-propagate the base tables' `rls_rules` onto the aggregate
table (remapped to its own columns) and detect when a candidate's grain omits
a required RLS filter column.

Verified TML shape (see the task-22 brief and
`tools/ts-cli/tests/test_report_matched_columns.py::_TABLE_TML_WITH_RLS`):

    table:
      rls_rules:
        table_paths:
          - id: T_1
            table: Source Table
            column: [ZIPCODE]
        rules:
          - name: geo_rule
            expr: "[T_1::ZIPCODE] = ts_groups_int"

Some builds instead emit a flat list directly under `rls_rules:` (no
`table_paths` wrapper) — mirrors the two shapes `agents/shared/erd/parser.py`'s
`_rls_rule_list` normalizes. In that flat shape there is no separate path-id
indirection, so a bracket ref's identifier is resolved against the owning
table's own name (a `[<TABLE_NAME>::COL]`-style self-reference) rather than a
declared `table_paths` entry — handled uniformly here by seeding the path map
with a `{own_table: (own_table, [])}` fallback entry before resolving refs.

Rule exprs reference `[<path_id>::<COLUMN>]` and ThoughtSpot system vars
(`ts_groups`, `ts_groups_int`, `ts_username`, `ts_var(...)`, etc.) — the system
vars are never bracket-wrapped, so the `[id::COL]` regex never touches them;
only bracketed column/table refs get remapped in `propagate_rls`, and rule
names are copied verbatim.
"""
from __future__ import annotations

import copy
import re

_REF = re.compile(r"\[([^:\]]+)::([^\]]+)\]")


def _cand_grain_columns(candidate: dict) -> set:
    """Every column in a candidate's grain: dimensions + every date grain's
    column. Duplicated (not shared) from lattice.py/sqlgen.py/generate.py's
    private helpers of a similar name, per this codebase's existing
    convention of keeping each module's own grain-reading self-contained."""
    grains = candidate.get("date_grains")
    if grains is None:
        col = candidate.get("date_column")
        grains = [{"column": col, "bucket": candidate.get("bucket")}] if col else []
    return set(candidate.get("dimensions", [])) | {g["column"] for g in grains if g.get("column")}


def _normalize_rls_block(raw, own_table: str):
    """Normalize one table's `rls_rules` value to (rules_list, path_map).

    Handles both nesting shapes described in the module docstring. `path_map`
    always carries a `{own_table: (own_table, [])}` fallback entry so a flat
    rule list (no `table_paths` at all) can still resolve a bracket ref whose
    identifier is literally the owning table's own name.
    """
    if not raw:
        return [], {}
    if isinstance(raw, dict):
        rules_list = [r for r in (raw.get("rules") or []) if isinstance(r, dict)]
        tp_list = raw.get("table_paths") or []
    else:
        rules_list = [r for r in raw if isinstance(r, dict)]
        tp_list = []

    path_map = {}
    for p in tp_list:
        if isinstance(p, dict) and p.get("id"):
            path_map[p["id"]] = (p.get("table"), list(p.get("column") or []))
    path_map.setdefault(own_table, (own_table, []))
    return rules_list, path_map


def extract_rls(base_table_tmls: dict) -> list:
    """Normalize every base Table TML's `rls_rules` into a flat list of rules.

    `base_table_tmls`: {table_name: parsed Table TML doc}. Returns
    `[{table, name, expr, columns, path_ids}]` — `columns` are the physical
    column names referenced by this rule's expr (deduped, first-seen order),
    `path_ids` is this rule's own `{path_id: (table, [declared cols])}` map
    (shared across rules of the same table; used by `rls_filter_columns` and
    `propagate_rls` to resolve/rewrite each bracket ref). Empty list when no
    table carries RLS.
    """
    out = []
    for table_name, tdict in base_table_tmls.items():
        raw = (tdict.get("table") or {}).get("rls_rules")
        rules_list, path_map = _normalize_rls_block(raw, table_name)
        for r in rules_list:
            expr = r.get("expr") or r.get("expression") or ""
            columns = []
            seen = set()
            for ref_id, col in _REF.findall(expr):
                if ref_id not in path_map:
                    continue  # unresolvable ref — not a known path/table
                if col not in seen:
                    seen.add(col)
                    columns.append(col)
            out.append({
                "table": table_name,
                "name": r.get("name", ""),
                "expr": expr,
                "columns": columns,
                "path_ids": path_map,
            })
    return out


def rls_filter_columns(rules: list) -> set:
    """The (base table, physical column) pairs the RLS exprs filter on.

    Parses each rule's `[id::COL]` refs via that rule's own `path_ids` map
    (not `rule["table"]`/`rule["columns"]` directly — a rule can reference a
    joined table's column via its own path, not only its owning table's).
    """
    out = set()
    for r in rules:
        path_ids = r.get("path_ids") or {}
        for ref_id, col in _REF.findall(r.get("expr", "")):
            resolved = path_ids.get(ref_id)
            if resolved is not None:
                out.add((resolved[0], col))
    return out


def candidate_rls_conflict(candidate: dict, plans: dict, model_tml: dict, rules: list) -> dict:
    """Which RLS filter columns (as MODEL display columns) does this
    candidate's grain omit?

    `plans` is accepted for signature parity with sibling candidate-scoped
    functions (`lattice.covers`, `generate.build_aggregate_table_spec` take
    the same `(candidate, plans, model_tml, ...)` ordering) but is not needed
    by this grain-membership check.

    Each RLS filter (base table, column) is mapped to the model column whose
    `column_id` is `<table>::<column>`; a filter column not modeled at all
    still appears (falling back to the raw `column_id` string) so it is never
    silently dropped from `required`/`missing` — omitting an un-modeled
    security-relevant column would be worse than surfacing an unresolvable
    display name.

    Returns `{"required": [...], "present": [...], "missing": [...]}`, all
    sorted for determinism. `missing` empty means the candidate is securable
    as-is.
    """
    model_cols = (model_tml.get("model") or {}).get("columns") or []
    cid_to_name = {c.get("column_id"): c.get("name") for c in model_cols if isinstance(c, dict)}

    required = set()
    for table, col in rls_filter_columns(rules):
        cid = f"{table}::{col}"
        required.add(cid_to_name.get(cid) or cid)

    grain = _cand_grain_columns(candidate)
    present = {d for d in required if d in grain}
    missing = required - present

    return {
        "required": sorted(required),
        "present": sorted(present),
        "missing": sorted(missing),
    }


def add_rls_columns_to_candidate(candidate: dict, missing_display_cols) -> dict:
    """Return a copy of `candidate` with `missing_display_cols` force-added to
    `dimensions`. Deterministic ordering (sorted); nothing else is recomputed
    — Task 23 re-profiles the candidate if needed."""
    new_candidate = copy.deepcopy(candidate)
    dims = set(new_candidate.get("dimensions", [])) | set(missing_display_cols)
    new_candidate["dimensions"] = sorted(dims)
    return new_candidate


def propagate_rls(base_rules: list, agg_table_name: str, display_to_aggcol: dict) -> dict:
    """Build the `rls_rules` block to attach to the AGGREGATE table's TML.

    Emits one merged `table_paths` entry (id `"<agg_table_name>_1"`, mirroring
    the `"<name>_1"` self-path convention documented in
    `agents/shared/schemas/thoughtspot-sets-tml.md`) pointing at
    `agg_table_name`, carrying every aggregate physical column the RLS filters
    need. Every rule's expr is rewritten so each `[<old_path>::<BASECOL>]`
    becomes `[<agg_path>::<AGGCOL>]`; the rule name and any non-bracketed
    `ts_*` system-var portion of the expr are copied verbatim (system vars are
    never bracket-wrapped, so the rewrite regex never touches them).

    `display_to_aggcol` is keyed by the same column name that appears inside
    a base rule's `[id::COL]` reference — i.e. the physical base column, which
    in this codebase's convention is also the aggregate grain column's stored
    name (`generate.py`'s `_grain_columns`/`build_aggregate_table_spec` use a
    candidate's display-named grain columns directly as the aggregate table's
    physical column names, with no separate renaming step) — mapped to the
    aggregate table's physical column name for that same filter. Every RLS
    filter column referenced by `base_rules` must have an entry; a missing one
    raises `ValueError` naming every offending column (the caller — Task 23 —
    guarantees this via `candidate_rls_conflict`'s conflict check or the
    force-add path in `add_rls_columns_to_candidate`, so this is a
    programming-error guard, not expected user-facing behavior).

    Returns `{}` when `base_rules` is empty (no RLS to propagate).
    """
    if not base_rules:
        return {}

    needed = []
    seen_needed = set()
    for rule in base_rules:
        path_ids = rule.get("path_ids") or {}
        for ref_id, col in _REF.findall(rule.get("expr", "")):
            if ref_id not in path_ids:
                continue
            if col not in seen_needed:
                seen_needed.add(col)
                needed.append(col)

    missing = [c for c in needed if c not in display_to_aggcol]
    if missing:
        raise ValueError(
            "propagate_rls: missing aggregate column mapping for RLS filter "
            f"column(s) {sorted(missing)} — cannot propagate RLS without a "
            "grain column for every filter (force-add or exclude the "
            "affected candidate first)."
        )

    agg_path_id = f"{agg_table_name}_1"
    agg_cols = []
    for col in needed:
        agg_col = display_to_aggcol[col]
        if agg_col not in agg_cols:
            agg_cols.append(agg_col)

    rules_out = []
    for rule in base_rules:
        path_ids = rule.get("path_ids") or {}
        expr = rule.get("expr", "")

        def _remap(match, path_ids=path_ids):
            ref_id, col = match.group(1), match.group(2)
            if ref_id not in path_ids or col not in display_to_aggcol:
                return match.group(0)  # not a filter ref we resolved — copy verbatim
            return f"[{agg_path_id}::{display_to_aggcol[col]}]"

        rules_out.append({"name": rule.get("name", ""), "expr": _REF.sub(_remap, expr)})

    return {
        "table_paths": [{"id": agg_path_id, "table": agg_table_name, "column": sorted(agg_cols)}],
        "rules": rules_out,
    }
