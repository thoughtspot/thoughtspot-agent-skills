"""RLS command-layer wiring for `ts aggregate` (Task 23).

The I/O shell that connects the pure `ts_cli/aggregate/rls.py` engine
(extract_rls / candidate_rls_conflict / rls_filter_columns / propagate_rls)
to the `recommend` and `generate` commands. Split out of `commands/aggregate.py`
to keep that module under the file-size gate; imported lazily from within
`recommend`/`generate` (never at aggregate.py's module top), so importing
`_err` from `commands.aggregate` here at module top is not a circular import
(aggregate.py is always fully loaded before this module is first imported).

Two consumers:
- `_attach_rls_conflicts` — `recommend`'s advisory surfacing (never fails).
- `_propagate_rls_or_fail_closed` — `generate`'s security gate: fails CLOSED
  (typer.Exit(1), before any file is written) when the tables-dir can't
  cover the model (so RLS can't be assessed) or the candidate's grain omits
  a required RLS filter column; otherwise returns the propagated `rls_rules`
  block for the aggregate Table TML.
"""
from __future__ import annotations

import typer

from ts_cli.commands.aggregate import _err


def _attach_rls_conflicts(candidates: list, plans: dict, model_tml: dict,
                          table_tmls: dict) -> list:
    """Attach per-candidate RLS conflict info to each candidate dict (Task 23,
    Part A) and return the ids of candidates that conflict.

    No-op (candidates untouched, `[]` returned) when no base Table TML in
    `table_tmls` carries `rls_rules` — `extract_rls` returns `[]` and every
    existing `recommend` caller/test that doesn't export a tables dir keeps
    seeing byte-identical candidate dicts.

    When base RLS exists, every candidate gets `rls: {required, missing}`
    (from `candidate_rls_conflict`, dropping its `present` key — the skill
    only needs required/missing to prompt) and a boolean `rls_conflict` flag
    (`missing` non-empty) — the skill's Step 5e prompts exclude-vs-force-add
    on exactly the candidates flagged here.
    """
    from ts_cli.aggregate.rls import candidate_rls_conflict, extract_rls
    rules = extract_rls(table_tmls)
    if not rules:
        return []
    conflicted = []
    for c in candidates:
        conflict = candidate_rls_conflict(c, plans, model_tml, rules)
        c["rls"] = {"required": conflict["required"], "missing": conflict["missing"]}
        c["rls_conflict"] = bool(conflict["missing"])
        if c["rls_conflict"]:
            conflicted.append(c["id"])
    return conflicted


def _rls_cid_to_name(model_tml: dict) -> dict:
    """`<table>::<col>` column_id -> model display name. `candidate_rls_conflict`
    (rls.py) builds this same map internally to resolve required/missing but
    doesn't expose it — `generate` needs the map itself to build
    `filter_to_aggcol` for `propagate_rls`, so it's rebuilt here rather than
    reimplementing the resolution rls.py already owns."""
    model_cols = (model_tml.get("model") or {}).get("columns") or []
    return {c.get("column_id"): c.get("name") for c in model_cols if isinstance(c, dict)}


def _build_filter_to_aggcol(rules: list, model_tml: dict) -> dict:
    """`(base_table, physical_col) -> aggregate stored column name`, for
    `propagate_rls`. Only called after `candidate_rls_conflict` has confirmed
    `missing == []` for this candidate, so every filter column here is
    guaranteed to resolve to a real model display name that is part of the
    candidate's grain — and `build_aggregate_table_spec` stores a grain
    column under that exact display name (see its `_grain_columns` helper),
    so the display name IS the aggregate's stored column name; no separate
    lookup against the table spec is needed."""
    from ts_cli.aggregate.rls import rls_filter_columns
    cid_to_name = _rls_cid_to_name(model_tml)
    out = {}
    for table, col in rls_filter_columns(rules):
        name = cid_to_name.get(f"{table}::{col}")
        if name:
            out[(table, col)] = name
    return out


def _assert_tables_dir_covers_model(model_tml: dict, table_tmls: dict,
                                    tables_dir: str, candidate_id: str) -> None:
    """Fail-closed INPUT guard for the RLS check below (Task 23 review fix).

    The RLS guard is only as strong as the base Table TMLs it reads: an empty
    or incomplete `--tables-dir` would make `extract_rls` return `[]`,
    silently skip propagation, and emit an UNSECURED aggregate — a fail-OPEN
    leak, since the aggregate might draw from an RLS'd base table whose TML
    simply wasn't loaded. For a security control this must fail CLOSED on
    missing input: refuse to proceed unless every `model_tables` entry has a
    loaded Table TML. (`recommend`'s advisory RLS surfacing tolerates a
    missing dir — it's not a gate; `generate`, which actually emits the
    artifact, does not.)"""
    model_tables = (model_tml.get("model") or {}).get("model_tables") or []
    expected = [t.get("name") for t in model_tables
                if isinstance(t, dict) and t.get("name")]
    missing = [n for n in expected if n not in table_tmls]
    if not table_tmls or missing:
        detail = (str(missing) if missing else
                  "ALL — the directory is empty or has no loadable Table TML files")
        _err(
            f"cannot assess row-level security for {candidate_id}: the "
            f"--tables-dir '{tables_dir}' did not provide a Table TML for every "
            f"base table of the primary Model (missing: {detail}). Without the "
            "base Table TMLs the aggregate's RLS cannot be evaluated, and "
            "emitting the aggregate anyway could leak rows an RLS rule is "
            "meant to hide. Re-run Step 3's Table TML export so a "
            "<NAME>.tml.yaml exists for every model_tables entry, then retry."
        )
        raise typer.Exit(code=1)


def _propagate_rls_or_fail_closed(cand: dict, plans: dict, model_tml: dict,
                                  table_tmls: dict, agg_table_name: str,
                                  candidate_id: str, tables_dir: str) -> dict:
    """Extract base-table RLS (Task 23, Part B) and propagate it onto the
    aggregate table, remapped to the aggregate's own grain columns.

    FAILS CLOSED — `_err(...)` + `typer.Exit(1)`, raised before `generate`
    writes ANY file (ddl.sql/table_spec.json/table.tml.yaml/agg_model.tml.yaml/
    primary_patched.tml.yaml) — in two cases: (1) the `--tables-dir` didn't
    load a Table TML for every base table, so RLS can't even be assessed
    (`_assert_tables_dir_covers_model` — a fail-OPEN-on-bad-input guard); or
    (2) the candidate's grain still omits a required RLS filter column. An
    aggregate that can't be assessed or can't be secured must never be
    emitted, not even partially.

    Returns `{}` (no-op) only when the tables-dir DID cover the model and no
    covered base Table TML carries `rls_rules`.

    No `--rls-force-add` flag exists on this command (deliberately — see the
    task-23 brief's "pick the simpler" option): the skill offers exclude-vs-
    force-add on a conflicting candidate at the recommend/pick-cutoff step
    (`ts-object-model-aggregates` SKILL.md Step 5e), applying
    `ts_cli.aggregate.rls.add_rls_columns_to_candidate` directly to
    `candidates.json` before calling `generate` — so by the time this
    function recomputes the conflict, a force-added candidate's grain already
    covers every RLS column and this check passes.
    """
    from ts_cli.aggregate.rls import candidate_rls_conflict, extract_rls, propagate_rls
    _assert_tables_dir_covers_model(model_tml, table_tmls, tables_dir, candidate_id)
    rules = extract_rls(table_tmls)
    if not rules:
        return {}
    conflict = candidate_rls_conflict(cand, plans, model_tml, rules)
    if conflict["missing"]:
        _err(
            f"cannot generate a secured aggregate for {candidate_id}: the base "
            f"table(s) enforce row-level security on {conflict['missing']}, which "
            "this candidate's grain omits. An aggregate table without an "
            "equivalent RLS rule would let any user who can query it (directly or "
            "via routing) see rows they aren't authorized for. Force-add the "
            "missing column(s) to the candidate's grain "
            "(ts_cli.aggregate.rls.add_rls_columns_to_candidate, applied to "
            "candidates.json) and re-profile, or exclude this candidate."
        )
        raise typer.Exit(code=1)
    filter_to_aggcol = _build_filter_to_aggcol(rules, model_tml)
    return propagate_rls(rules, agg_table_name, filter_to_aggcol)
