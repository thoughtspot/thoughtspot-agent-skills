"""RLS extraction, grain-conflict detection, and propagation onto an aggregate table.

Pure functions, no I/O, Python 3.9. Task 22 — the skill previously only GATED on
base-table row-level security (refused to import until the user manually
replicated the rule elsewhere); this module instead lets the skill (Task 23,
not this one) auto-propagate the base tables' `rls_rules` onto the aggregate
table (remapped to its own columns) and detect when a candidate's grain omits
a required RLS filter column.

Verified TML shape (see the task-22 brief and
`tools/ts-cli/tests/test_report_matched_columns.py::_TABLE_TML_WITH_RLS` for the
simplified two-block illustration `extract_rls` reads on input — that fixture
predates the discovery below and is fine for `extract_rls`, which never reads
`tables:` itself). The full shape a live UI-created rule round-trips through
import cleanly (live-verified, Task 25) has a THIRD sub-block, `tables`,
naming the owning table — this is the shape `propagate_rls` must EMIT:

    table:
      rls_rules:
        tables:
          - name: Source Table
        table_paths:
          - id: T_1
            table: Source Table
            column: [ZIPCODE]
        rules:
          - name: geo_rule
            expr: "[T_1::ZIPCODE] = ts_groups_int"

Omitting `tables` (the pre-Task-25 bug) is accepted by `extract_rls` on input
(it never reads that key) but rejected on IMPORT of `propagate_rls`'s output
— `OBJECT_NOT_FOUND ... LOGICAL_TABLE` — because the aggregate table doesn't
exist as an object `table_paths`' self-reference can resolve against until
`tables` names it explicitly. See `propagate_rls`'s docstring.

Some builds instead emit a flat list directly under `rls_rules:` (no
`table_paths` wrapper). `agents/shared/erd/parser.py`'s `_rls_rule_list`
normalizes the two *nesting shapes* (dict-with-`rules` vs. flat list) but does
NOT resolve bracket refs to columns — that resolution is this module's job, and
it is unverified for the flat shape. **UNVERIFIED (no in-repo flat-shape TML
example):** in the flat shape there is no `table_paths` indirection, so this
module infers a bracket ref's identifier resolves against the owning table's
own name (a `[<TABLE_NAME>::COL]`-style self-reference), implemented by seeding
the path map with a `{own_table: (own_table, [])}` fallback entry before
resolving refs. Task 23 / live testing must confirm this against a real
flat-shape export — see open-items.md #17.

Rule exprs reference `[<path_id>::<COLUMN>]` and ThoughtSpot system vars
(`ts_groups`, `ts_groups_int`, `ts_username`, `ts_var(...)`, etc.) — the system
vars are never bracket-wrapped, so the `[id::COL]` regex never touches them;
only bracketed column/table refs get remapped in `propagate_rls`, and rule
names are copied verbatim.

Fail-closed: an RLS ref whose path_id is neither a declared `table_paths`
entry nor the owning table name cannot be resolved to a base table, but it
still names a security filter. Rather than silently drop it (which would
report a candidate "securable as-is" while an unsecurable ref exists — a
fail-open leak), such a ref surfaces using its raw ref_id as the pseudo-table,
so it flows through `rls_filter_columns` / `candidate_rls_conflict` as a
required-but-missing column and through `propagate_rls` as an unmapped column
that raises.
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


def _resolve_ref(ref_id: str, path_ids: dict):
    """Resolve one `[ref_id::col]` bracket ref's identifier to a base table.

    Returns the declared path's table when `ref_id` is known, else the raw
    `ref_id` itself (fail-closed: an undeclared ref still names a security
    filter, so it surfaces as a distinct pseudo-table rather than being
    dropped — never resolves to None/silent-skip)."""
    resolved = path_ids.get(ref_id)
    return resolved[0] if resolved is not None else ref_id


def extract_rls(base_table_tmls: dict) -> list:
    """Normalize every base Table TML's `rls_rules` into a flat list of rules.

    `base_table_tmls`: {table_name: parsed Table TML doc}. Returns
    `[{table, name, expr, columns, path_ids}]` — `columns` are the physical
    column names referenced by this rule's expr (deduped, first-seen order),
    `path_ids` is this rule's own `{path_id: (table, [declared cols])}` map
    (shared across rules of the same table; used by `rls_filter_columns` and
    `propagate_rls` to resolve/rewrite each bracket ref). Empty list when no
    table carries RLS.

    `columns` includes every referenced physical column, even one whose
    path_id is undeclared (fail-closed — an unresolvable ref is still a
    security filter and must not vanish).
    """
    out = []
    for table_name, tdict in base_table_tmls.items():
        raw = (tdict.get("table") or {}).get("rls_rules")
        rules_list, path_map = _normalize_rls_block(raw, table_name)
        for r in rules_list:
            expr = r.get("expr") or r.get("expression") or ""
            columns = []
            seen = set()
            for _ref_id, col in _REF.findall(expr):
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
    joined table's column via its own path, not only its owning table's). An
    undeclared path_id surfaces as `(<raw ref_id>, col)` rather than being
    dropped — see `_resolve_ref` (fail-closed).
    """
    out = set()
    for r in rules:
        path_ids = r.get("path_ids") or {}
        for ref_id, col in _REF.findall(r.get("expr", "")):
            out.add((_resolve_ref(ref_id, path_ids), col))
    return out


def candidate_rls_conflict(candidate: dict, plans: dict, model_tml: dict, rules: list) -> dict:
    """Which RLS filter columns (as MODEL display columns) does this
    candidate's grain omit?

    `plans` is accepted for signature parity with sibling candidate-scoped
    functions (`lattice.covers`, `generate.build_aggregate_table_spec` take
    the same `(candidate, plans, model_tml, ...)` ordering) but is not needed
    by this grain-membership check.

    Each RLS filter (base table, column) is mapped to the model column whose
    `column_id` is `<table>::<column>`; a filter column not modeled at all —
    or one whose path_id was undeclared and so resolved to a pseudo-table via
    `_resolve_ref` (fail-closed) — still appears (falling back to the raw
    `<table>::<column>` string, which is never a grain display name, so it can
    never be `present`). It is thus never silently dropped from
    `required`/`missing`: a candidate can never be reported securable
    (`missing == []`) while an unresolvable or un-modeled RLS ref exists —
    omitting an un-modeled security-relevant column would be worse than
    surfacing an unresolvable display name.

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


def propagate_rls(base_rules: list, agg_table_name: str, filter_to_aggcol: dict) -> dict:
    """Build the `rls_rules` block to attach to the AGGREGATE table's TML.

    Emits THREE sub-blocks, in this order — `tables`, `table_paths`, `rules`
    — matching the known-good shape a live UI-created rule re-imports as
    (live-verified, Task 25; see the module docstring). `tables` is
    `[{"name": agg_table_name}]` — one entry, since the aggregate is always a
    single table. **This block is load-bearing, not decorative:** omitting it
    (the pre-Task-25 bug) made a live import of this exact TML fail with
    `OBJECT_NOT_FOUND ... LOGICAL_TABLE` — `table_paths`' self-reference to
    `agg_table_name` apparently resolves against `tables`, not independently.

    `table_paths` is one merged entry (id `"<agg_table_name>_1"`, mirroring
    the `"<name>_1"` self-path convention documented in
    `agents/shared/schemas/thoughtspot-sets-tml.md`) pointing at
    `agg_table_name`, carrying every aggregate physical column the RLS filters
    need. Every rule's expr is rewritten so each `[<old_path>::<BASECOL>]`
    becomes `[<agg_path>::<AGGCOL>]`; the rule name and any non-bracketed
    `ts_*` system-var portion of the expr are copied verbatim (system vars are
    never bracket-wrapped, so the rewrite regex never touches them).

    Multiple base tables (each contributing their own rule(s)) collapse onto
    this SAME single aggregate block — one `tables`/`table_paths` entry, all
    rules listed — since the aggregate is one table no matter how many base
    tables fed it.

    `filter_to_aggcol` is keyed by the **`(base table, physical column)`
    tuple** — exactly the pair `rls_filter_columns` emits and
    `candidate_rls_conflict` resolves — NOT the bare column name. The table
    qualifier is load-bearing for correctness: two base tables that each
    RLS-filter on a same-named physical column (e.g. both a fact and a dim
    have `REGION`) map to DISTINCT aggregate columns; keying by bare column
    name would silently collapse them onto one aggregate column and emit a
    valid, lint-clean rule enforcing the WRONG row restriction (a leak). The
    value is the aggregate table's physical column name for that filter.

    Every RLS filter `(table, col)` referenced by `base_rules` must have an
    entry — including one that resolved via the fail-closed pseudo-table path
    (`_resolve_ref`) for an undeclared path_id. A missing one raises
    `ValueError` naming every offending `(table, col)` (the caller — Task 23 —
    guarantees coverage via `candidate_rls_conflict`'s conflict check or the
    force-add path in `add_rls_columns_to_candidate`, so this is a
    programming-error / fail-closed guard, not expected user-facing behavior).

    Returns `{}` when `base_rules` is empty (no RLS to propagate).
    """
    if not base_rules:
        return {}

    needed = []
    seen_needed = set()
    for rule in base_rules:
        path_ids = rule.get("path_ids") or {}
        for ref_id, col in _REF.findall(rule.get("expr", "")):
            key = (_resolve_ref(ref_id, path_ids), col)
            if key not in seen_needed:
                seen_needed.add(key)
                needed.append(key)

    missing = [k for k in needed if k not in filter_to_aggcol]
    if missing:
        raise ValueError(
            "propagate_rls: missing aggregate column mapping for RLS filter "
            f"column(s) {sorted(missing)} — cannot propagate RLS without a "
            "grain column for every filter (force-add or exclude the "
            "affected candidate first)."
        )

    agg_path_id = f"{agg_table_name}_1"
    agg_cols = []
    for key in needed:
        agg_col = filter_to_aggcol[key]
        if agg_col not in agg_cols:
            agg_cols.append(agg_col)

    rules_out = []
    for rule in base_rules:
        path_ids = rule.get("path_ids") or {}
        expr = rule.get("expr", "")

        def _remap(match, path_ids=path_ids):
            ref_id, col = match.group(1), match.group(2)
            key = (_resolve_ref(ref_id, path_ids), col)
            if key not in filter_to_aggcol:
                return match.group(0)  # not a filter ref we resolved — copy verbatim
            return f"[{agg_path_id}::{filter_to_aggcol[key]}]"

        rules_out.append({"name": rule.get("name", ""), "expr": _REF.sub(_remap, expr)})

    return {
        "tables": [{"name": agg_table_name}],
        "table_paths": [{"id": agg_path_id, "table": agg_table_name, "column": sorted(agg_cols)}],
        "rules": rules_out,
    }
