"""Pre-import TML linter — model invariants worth catching before any round trip to
ThoughtSpot, whether or not the server's own validation surfaces them.

Most of these (I1/I2/I4/I5) are invariants `--policy VALIDATE_ONLY` does NOT catch —
ThoughtSpot accepts the TML and then behaves wrong later (silently drops a formula,
flips a measure to an attribute, breaks a join at query time). A couple (I8, I12) ARE
caught by the server (including under VALIDATE_ONLY) but are cheap, purely-structural
checks worth failing on locally, without a live call, especially across a batch of
generated TML. I15 is the misplaced-column-root-key check (BL-232): a `description` under
`properties:` imports with status OK and is then silently discarded. I16 is cross-file
(it needs the Table TML linted alongside the Model): a Model column `AGGREGATE` over a
Table column that is not breaks every AgentQL/SpotQL query on it. I17-I19 are the
join-graph rules (live-probed 2026-10-21): the server rejects a cycle, a second route,
a self-join, or an `on:` naming the wrong tables, but its message names none of the
joins at fault — these do. I20 (a MANY_TO_MANY Model join) and I21 (a
`referencing_join` its own Table TML does not declare; cross-file, like I16) are
rejected with clear messages, but only at import — after a converter has finished.
Rules mirror the invariants in
`agents/shared/schemas/ts-model-conversion-invariants.md`.

CANONICAL-RULE-SET: I1/I2/I4/I5/I8/I12/I13/I14/I15/I16/I17/I18/I19/I20/I21/I22
    The one authoritative enumeration of what this module checks, gated by
    tools/validate/check_lint_invariant_list.py against the findings the code
    actually emits. Do not restate this set anywhere else — name the concept
    ("the model invariants") and link to the doc above. Subset statements in
    prose ("most of these (I1/I2/I4/I5) are …") are fine and are not this.

Pure functions over a parsed TML dict so they are trivially unit-testable.
"""
from __future__ import annotations

import re
from typing import Any

from ts_cli.tml_join_graph import (
    JoinGraph, ambiguous_paths, directed_cycles, node_id, on_clause_refs, on_clause_tables,
)

# Chart types whose rendering needs an explicit encoding — an x/y (+ series) axis map
# (legacy cartesian, `chart.axis_configs`) or the ADVANCED_* shelf model
# (`chart.custom_chart_config`). A tile of one of these types with NEITHER imports cleanly
# but draws BLANK (the hand-authored-off-skill failure mode: a chart type is set, but nothing
# tells the engine which column is the axis vs the series). Tables (GRID_TABLE / PIVOT_TABLE),
# KPI, PIE, GEO_*, TREEMAP, FUNNEL, HEATMAP, SANKEY etc. don't use an x/y axis and are exempt.
# Public alias: emitters import this so the "which charts need an axis" fact has ONE
# definition. A converter copying the list is the drift class BL-217 exists to stop --
# and 17.3 is what a missing copy looks like (Qlik emitted four of these types with no
# axis encoding at all, so its boards imported and rendered blank).
_CHART_NEEDS_AXIS = frozenset({
    "LINE", "COLUMN", "BAR", "AREA",
    "STACKED_COLUMN", "STACKED_BAR", "STACKED_AREA",
    "LINE_COLUMN", "LINE_STACKED_COLUMN",
    "SCATTER", "BUBBLE", "WATERFALL", "PARETO", "WHISKER_SCATTER", "CANDLESTICK",
    "ADVANCED_LINE", "ADVANCED_COLUMN", "ADVANCED_BAR", "ADVANCED_AREA",
    "ADVANCED_STACKED_COLUMN", "ADVANCED_STACKED_BAR", "ADVANCED_STACKED_AREA",
    "ADVANCED_LINE_COLUMN", "ADVANCED_LINE_STACKED_COLUMN",
})
CHART_NEEDS_AXIS = _CHART_NEEDS_AXIS


def _tile_answers(doc: dict):
    """Yield ``(tile_label, answer_dict)`` for a parsed answer OR liveboard/pinboard TML doc.

    A standalone answer has ``doc['answer']``; a liveboard has
    ``doc['liveboard']['visualizations'][].answer``. Anything else yields nothing."""
    if not isinstance(doc, dict):
        return
    a = doc.get("answer")
    if isinstance(a, dict):
        yield a.get("name") or "(answer)", a
    lb = doc.get("liveboard") or doc.get("pinboard")
    if isinstance(lb, dict):
        for v in lb.get("visualizations") or []:
            va = (v or {}).get("answer") if isinstance(v, dict) else None
            if isinstance(va, dict):
                yield va.get("name") or "(visualization)", va


def chart_tiles_missing_axis(doc: dict) -> list:
    """Chart tiles that will import but render blank for lack of an axis encoding.

    Returns ``[{"visual": name, "chart_type": TYPE}, ...]`` for every answer/visualization
    whose ``chart.type`` is in ``_CHART_NEEDS_AXIS`` but which carries neither
    ``chart.axis_configs`` nor ``chart.custom_chart_config``. Empty for model/table TML,
    tables, KPIs, and correctly-encoded charts. Pure — used by both `ts tml lint` (pre-import)
    and `ts tml verify-render` (post-import, re-exported through render_check)."""
    out = []
    for name, a in _tile_answers(doc):
        chart = a.get("chart") if isinstance(a.get("chart"), dict) else {}
        ctype = str(chart.get("type") or "").upper()
        if ctype in _CHART_NEEDS_AXIS and not (chart.get("axis_configs") or chart.get("custom_chart_config")):
            out.append({"visual": name, "chart_type": ctype})
    return out


def _check_viz_table_binding(data: dict) -> list[str]:
    """Viz tiles bound by a bare `fqn` instead of `obj_id`.

    agents/shared/schemas/thoughtspot-liveboard-tml.md is explicit: inside a viz,
    `answer.tables[]` must bind via `obj_id`, because "a viz-level `fqn` is dropped
    on import, leaving the viz with no data source, which renders as an error".

    Every converter emitter used to do the opposite, and the skills mandated a
    binding their own required CLI could not emit (audit 14.2). Recovery was a
    build -> import -> export -> re-import cycle. Flagged pre-import so the cycle
    is never needed: the fix is `obj_id`, derivable from the same GUID via
    tml_common.derive_viz_obj_id.
    """
    out = []
    for name, a in _tile_answers(data):
        for t in (a.get("tables") or []):
            if not isinstance(t, dict):
                continue
            if "fqn" in t and "obj_id" not in t:
                out.append(
                    f"visualization '{name}' binds its data source with a bare viz-level "
                    "`fqn` and no `obj_id` — the fqn is DROPPED on import, leaving the viz "
                    "with no data source (it renders as an error). Use `obj_id` "
                    "(ModelNameNoSpaces-{guid8}); see thoughtspot-liveboard-tml.md."
                )
    return out


def _check_chart_tile_encoding(data: dict) -> list[str]:
    """Chart tiles (answer/liveboard TML) that import cleanly but render BLANK for lack of
    an axis encoding — neither chart.axis_configs nor a custom_chart_config. This is the
    hand-authored-off-skill failure (a real CSM board shipped this way); the converter's
    build-liveboard always emits the encoding, so its absence flags a hand-drawn tile.
    A no-op for model/table docs, which have no tiles."""
    return [
        f"visualization '{tile['visual']}' is a {tile['chart_type']} chart but has no "
        "chart.axis_configs (or custom_chart_config) — it imports but renders blank. "
        "Generate the tile with the converter's build-liveboard, not by hand."
        for tile in chart_tiles_missing_axis(data)
    ]


def lint_tml(data: dict) -> list[str]:
    """Return a list of invariant-violation strings for one parsed TML doc. Empty = clean.

    Auto-detects table vs model TML by the top-level key. Checks the model invariants
    (the module docstring's CANONICAL-RULE-SET) plus the guid-placement rule — see it
    for which of these the server's VALIDATE_ONLY policy does and doesn't also surface.
    """
    if not isinstance(data, dict):
        return ["Top-level TML value must be a mapping"]

    findings: list[str] = []

    # guid must sit at the document root, never nested inside table:/model:.
    for key in ("table", "model"):
        inner = data.get(key)
        if isinstance(inner, dict) and "guid" in inner:
            findings.append(
                f"guid is nested inside '{key}:' — it must be a top-level key "
                f"(sibling of '{key}:'), or omitted on first import."
            )

    findings.extend(_check_chart_tile_encoding(data))
    findings.extend(_check_viz_table_binding(data))

    model = data.get("model")
    if not isinstance(model, dict):
        return findings  # not a model TML — nothing more to check here

    formulas = model.get("formulas") or []
    columns = model.get("columns") or []
    model_tables = model.get("model_tables") or []

    # I1 — every formulas[] id has a paired columns[] entry (formula_id == id).
    paired = {c.get("formula_id") for c in columns if isinstance(c, dict)}
    for f in formulas:
        if not isinstance(f, dict):
            continue
        fid = f.get("id")
        if fid and fid not in paired:
            findings.append(
                f"I1: formula '{fid}' has no paired columns[] entry "
                f"(formula_id: {fid}) — it will be silently dropped on import."
            )

    # I2 — no aggregation: inside a formulas[] entry (only columns[] may carry it).
    for f in formulas:
        if isinstance(f, dict) and isinstance(f.get("properties"), dict) and "aggregation" in f["properties"]:
            findings.append(
                f"I2: formula '{f.get('id', '?')}' has an aggregation: under formulas[] — "
                f"raises 'FORMULA is not a valid aggregation type'. Move it to the columns[] entry."
            )

    # I4 — model_tables[].id (when present) must equal name exactly (case included).
    for t in model_tables:
        if isinstance(t, dict) and "id" in t and t.get("id") != t.get("name"):
            findings.append(
                f"I4: model_tables id '{t.get('id')}' != name '{t.get('name')}' — "
                f"joins silently fail at query time ('{t.get('name')} does not exist in schema')."
            )

    # I5 — a physical-column columns[] entry must not use aggregation: COUNT_DISTINCT
    # (it silently flips column_type MEASURE → ATTRIBUTE; use a `unique count(...)` formula).
    for c in columns:
        if not isinstance(c, dict) or "formula_id" in c:
            continue  # formula columns are exempt; this targets physical columns
        props = c.get("properties") or {}
        if isinstance(props, dict) and props.get("aggregation") == "COUNT_DISTINCT":
            findings.append(
                f"I5: column '{c.get('name', '?')}' uses aggregation: COUNT_DISTINCT — "
                f"this flips MEASURE → ATTRIBUTE silently. Use a `unique count(...)` formula instead."
            )

    # I8 — every column_id in columns[] must be unique. A duplicate is a HARD import
    # rejection ("columns should have unique column_id values"). When a source defines
    # two metrics on one physical column, only one may be a column_id entry; the rest
    # must be formulas[].
    id_counts: dict[str, int] = {}
    for c in columns:
        if not isinstance(c, dict):
            continue
        cid = c.get("column_id")
        if cid:
            id_counts[cid] = id_counts.get(cid, 0) + 1
    for cid, n in id_counts.items():
        if n > 1:
            findings.append(
                f"I8: column_id '{cid}' appears {n} times in columns[] — ThoughtSpot "
                f"rejects the import ('columns should have unique column_id values'). Keep one "
                f"column_id entry and express the other aggregation(s) as formulas[]."
            )

    findings.extend(_check_bare_column_id_single_table(model_tables, columns))
    findings.extend(_check_dangling_formula_refs(formulas, columns))
    findings.extend(_check_duplicate_join_pairs(model_tables))
    findings.extend(_check_join_path_ambiguity(model_tables))
    findings.extend(_check_self_joins(model_tables))
    findings.extend(_check_join_on_tables(model_tables))
    findings.extend(_check_many_to_many_joins(model_tables))
    findings.extend(_check_misplaced_column_root_keys(columns))

    return findings


# I15 — keys that belong at a columns[] entry's ROOT, as siblings of `name`
# (thoughtspot-model-tml.md, the columns[] field table). A Model import silently
# ignores unknown keys INSIDE `properties`, so one of these placed there validates
# clean, imports with status_code OK, and is then simply gone.
#
# Deliberately a denylist of misplaced-root keys, NOT an allow-list of valid
# `properties` keys: the linter gates imports, and an allow-list would fail a
# legitimate round-tripped Model carrying any property not yet catalogued here.
# This form has no false positives and still closes the class.
# `data_panel_column_groups` is root-level, settled by census rather than by the
# doc-vs-code split it first looked like: docs/reviews/2026-07-30-tml-census.md:150
# records `model.columns[].data_panel_column_groups` 9 times across 3 of 143 real
# Models, at the column ROOT, with zero `properties.`-level sightings. (Two sites
# still call it a properties key — sv_build_sv.py's _UNMAPPED_PROP_KEYS and a CoCo
# SKILL.md — tracked as BL-237, the same doc-vs-code split that produced BL-232's
# fifth site.)
_COLUMN_ROOT_ONLY_KEYS = (
    "description", "name", "column_id", "formula_id", "data_panel_column_groups",
)


def _check_misplaced_column_root_keys(columns: list) -> list[str]:
    """I15 — a column-root key placed inside `properties`, where import drops it.

    BL-232: `description` was emitted under `properties` by five sites across two
    converters and the CoCo mapping doc. Every gate in the repo passed — `ts tml lint`
    included — while every column description was silently discarded at import. Three
    of the five sites were found only on a second pass, which is why this is a lint
    rule and not just five fixes.
    """
    findings: list[str] = []
    for c in columns:
        if not isinstance(c, dict):
            continue
        props = c.get("properties")
        if not isinstance(props, dict):
            continue
        label = c.get("name") or c.get("column_id") or c.get("formula_id") or "?"
        for key in _COLUMN_ROOT_ONLY_KEYS:
            if key in props:
                findings.append(
                    f"I15: column '{label}' has '{key}:' inside properties: — it belongs "
                    f"at the columns[] entry root, as a sibling of 'name'. A Model import "
                    f"SILENTLY IGNORES unknown keys under properties:, so this imports "
                    f"with status OK and the value is lost (contrast 'synonyms', which "
                    f"must stay under properties:)."
                )
    return findings


def _check_duplicate_join_pairs(model_tables: list) -> list[str]:
    """I14 — no ordered table pair may be joined more than once.

    Two joins between the same pair leave the join path ambiguous, and
    ThoughtSpot will not load the Model. A role-played dimension (the same
    physical table reached by several keys — order date vs ship date, or five
    employee roles off one customer row) must be modelled as one aliased
    `model_tables` entry per role, so each pair is joined exactly once.

    This is the invariant a Semantic View source violates by construction: an
    SV scopes names per table and happily declares eight relationships from
    one fact to one date dimension, which is legal there and fatal here
    (BL-202).
    """
    findings: list[str] = []
    for t in model_tables:
        if not isinstance(t, dict):
            continue
        frm = node_id(t)  # alias, else id, else name — tml_join_graph's one definition
        seen: dict[str, list[str]] = {}
        for j in t.get("joins") or []:
            if not isinstance(j, dict):
                continue
            with_ = j.get("with")
            if not with_:
                continue
            seen.setdefault(with_, []).append(j.get("name") or "(unnamed)")
        for with_, names in seen.items():
            if len(names) > 1:
                findings.append(
                    f"I14: '{frm}' joins '{with_}' {len(names)} times "
                    f"({', '.join(names)}) — the join path is ambiguous and "
                    f"ThoughtSpot will not load the Model. Give each role its "
                    f"own aliased model_tables entry (name: the physical table, "
                    f"alias: a unique per-role id) and point one join at each."
                )
    return findings


def _check_join_path_ambiguity(model_tables: list) -> list[str]:
    """I17 — the directed join graph must have one route between any two tables.

    An arrow runs from a join's MANY side to its ONE side, so `cardinality` sets it, not
    which entry declares the join (a ONE_TO_MANY points from `with:` back to the entry).
    Three shapes, all rejected at import with nothing but a code ("Schema validation
    failed", live-probed 2026-10-21): a cycle that follows the arrows (13123); two
    arrow-following routes from one table to another (13124); and two joins on the same
    arrow declared from different entries — an M:1 under A plus a 1:M under B (13124).
    Two fact tables sharing a date dimension form a loop only when direction is ignored,
    and that Model imports fine, so it is never flagged. Two joins declared under one
    entry to the same target are I14's case and keep its id.
    """
    graph = JoinGraph(model_tables)
    findings: list[str] = []
    for src, dst, edges in graph.parallel_arrows():
        findings.append(
            f"I17: {len(edges)} joins run from '{src}' to '{dst}' "
            f"({', '.join(f'{e.name} under {e.frm}' for e in edges)}) — two routes "
            f"between one pair, so ThoughtSpot rejects the Model (error 13124, 'Schema "
            f"validation failed'). A ONE_TO_MANY join points from its with: table back to "
            f"the table it is declared under. Keep one join, or alias '{dst}' per role."
        )
    for cycle in directed_cycles(graph):
        findings.append(
            f"I17: the joins form a cycle ({' -> '.join(cycle)}) — ThoughtSpot rejects "
            f"the Model (error 13123, 'Schema validation failed'). A join graph must not "
            f"lead back to a table it started from: remove one of these joins, or alias "
            f"the table the cycle returns to so the second role is a separate node."
        )
    for src, target, a, b in ambiguous_paths(graph):
        findings.append(
            f"I17: two join paths reach '{target}' from '{src}' "
            f"({' -> '.join(a)}; {' -> '.join(b)}) — ThoughtSpot rejects the Model "
            f"(error 13124, 'Schema validation failed'). Alias '{target}' once per role "
            f"(name: the physical table, alias: a per-role id) and point one path at each."
        )
    return findings


def _check_self_joins(model_tables: list) -> list[str]:
    """I18 — a Model may not join a table to itself, aliased or not.

    Rejected in every form probed live (2026-10-21): direct (14565, 'INTERNAL ERROR'),
    to an alias of itself, and between two aliases of one table (13125). An
    employee -> manager hierarchy has to be flattened in the warehouse (a view carrying
    the manager's columns), not modelled as a join.
    """
    graph = JoinGraph(model_tables)
    return [
        f"I18: join '{e.name}' ({e.frm} -> {e.to}) joins physical table "
        f"'{graph.physical[e.frm]}' to itself — ThoughtSpot does not support self-joins "
        f"in a Model, with or without an alias (error 13125 / 14565). Flatten the "
        f"hierarchy in the warehouse (a view carrying the parent's columns) and join that."
        for e in graph.edges if graph.is_self_join(e)
    ]


def _check_join_on_tables(model_tables: list) -> list[str]:
    """I19 — a join's `on:` may name only its two tables, by PHYSICAL name.

    A third table, or an alias name in place of the physical one, is rejected with
    'Invalid srcTable or destTable in join expression' (live-probed 2026-10-21; the
    alias case for an ordinary join, not only a self-join). Side order is free —
    `[TO::x] = [FROM::y]` imports fine, so it is not checked. Joins without an
    inline `on:` (a `referencing_join` to Table TML) and self-joins (I18) are skipped.
    """
    graph = JoinGraph(model_tables)
    findings: list[str] = []
    for e in graph.edges:
        on = e.join.get("on")
        if not on or graph.is_self_join(e):
            continue
        phys_from, phys_to = graph.physical[e.frm], graph.physical[e.to]
        allowed = {phys_from.lower(), phys_to.lower()}
        aliases = {e.frm.lower(): phys_from, e.to.lower(): phys_to}
        for table in on_clause_tables(on):
            t = table.lower()
            if t in allowed:
                continue
            if t in aliases:
                findings.append(
                    f"I19: join '{e.name}' ({e.frm} -> {e.to}) names alias '{table}' in "
                    f"its on: clause — on: takes PHYSICAL table names; write "
                    f"'{aliases[t]}' (with: is what selects the alias). ThoughtSpot "
                    f"rejects this: 'Invalid srcTable or destTable in join expression'."
                )
            else:
                findings.append(
                    f"I19: join '{e.name}' ({e.frm} -> {e.to}) names '{table}' in its "
                    f"on: clause, which is neither of its two tables ('{phys_from}', "
                    f"'{phys_to}') — ThoughtSpot rejects this: 'Invalid srcTable or "
                    f"destTable in join expression'."
                )
    return findings


# A bracketed reference of any kind. `formula_`-prefixed ones are id references
# and must resolve; `TABLE::COL` and plain display-name refs are other checks'
# business (XREF / I9 respectively).
#
# Deliberately NOT string-literal aware: a `[formula_x]` sequence inside a quoted
# literal (e.g. `'see [formula_x]'`) would be scanned as a reference. Accepted
# risk — the payload would have to be a formula whose *text* names a formula id,
# and the failure mode is a visible finding a human dismisses, not a silent pass.
# Tokenizing the ThoughtSpot formula grammar here would couple the linter to
# sv_sql.py's tokenizer for no gain in the cases that occur.
_BRACKET_REF_RE = re.compile(r"\[([^\[\]]+)\]")


def _expr_formula_ref_misses(
    formulas: list, declared: set,
) -> list[tuple[str, str]]:
    """(context, ref) for each `[formula_*]` in an expr matching no declared id."""
    out: list[tuple[str, str]] = []
    for f in formulas:
        if not isinstance(f, dict):
            continue
        expr = f.get("expr")
        if not isinstance(expr, str):
            continue
        context = f"formula '{f.get('id') or f.get('name') or '?'}'"
        for ref in dict.fromkeys(_BRACKET_REF_RE.findall(expr)):
            if ref.startswith("formula_") and ref not in declared:
                out.append((context, ref))
    return out


def _column_formula_id_misses(
    columns: list, declared: set,
) -> list[tuple[str, str]]:
    """(context, ref) for each columns[].formula_id matching no declared id."""
    out: list[tuple[str, str]] = []
    for c in columns:
        if not isinstance(c, dict):
            continue
        ref = c.get("formula_id")
        if isinstance(ref, str) and ref and ref not in declared:
            out.append((f"column '{c.get('name', '?')}'", ref))
    return out


def _check_dangling_formula_refs(formulas: list, columns: list) -> list[str]:
    """I13 — every `formula_*` id reference must match a declared `formulas[].id`.

    A bracket reference matching no declared id is not resolved by ThoughtSpot as
    a cross-reference: it is parsed as search tokens, so the formula either fails
    to import or imports as a silently-broken measure. Distinct from I9, which
    says to use the id form at all — this says the id you used must exist.

    Promoted from BL-178 per the two-bucket rule (BL-183): the from-Snowflake
    converter shipped five weeks of Model TML in which *every* measure referenced
    an id that was never declared, and `lint_tml`, `check_tml.py` and
    `build-model`'s own lint_findings all reported clean
    (`docs/reviews/2026-07-29-ossie-tpcds-fidelity.md` F9 / §3.9). This check
    would have caught it on the commit that introduced it.

    Purely structural over a single document — no live instance, no judgment.

    A document that declares NO formula ids is skipped entirely, matching
    `tools/validate/check_tml.py`'s `if formula_ids:` guard (the two must agree, or
    the same TML lints differently in the CLI and in CI). An empty `formulas[]` is
    a formula-free or phase-1 model, not a document full of broken references; the
    orphan-column direction is I1's job.
    """
    declared = {
        f.get("id") for f in formulas
        if isinstance(f, dict) and f.get("id")
    }
    if not declared:
        return []
    misses = (_expr_formula_ref_misses(formulas, declared)
              + _column_formula_id_misses(columns, declared))
    return [
        f"I13: {context} references '{ref}', which matches no formulas[].id "
        f"in this document — ThoughtSpot parses an unresolvable bracket "
        f"reference as search tokens, so the formula fails to import or "
        f"imports silently broken."
        for context, ref in dict.fromkeys(misses)
    ]


def _check_bare_column_id_single_table(model_tables: list, columns: list) -> list[str]:
    """I12 — a bare (no "::") column_id on a single-table model is rejected at
    import ("These column_id/formula_id values are incorrect") — live-verified
    2026-07-23, se-thoughtspot. Scoped to single-table models: multi-table
    column-ownership resolution is a separate, harder problem (BL follow-up
    #2/#4) with its own pre-existing, out-of-scope unresolvable-column cases
    this check must not false-positive on. A missing column_id is out of scope
    too (not what this check targets — see I1 for formula-only columns).
    """
    if len(model_tables) != 1:
        return []
    findings: list[str] = []
    for c in columns:
        if not isinstance(c, dict):
            continue
        cid = c.get("column_id")
        if isinstance(cid, str) and cid and "::" not in cid:
            findings.append(
                f"I12: column_id '{cid}' is not TABLE::col-qualified — "
                f"ThoughtSpot rejects this at import ('These column_id/formula_id "
                f"values are incorrect'), even on a single-table model."
            )
    return findings


def _check_table_col_ref(
    ref: str,
    context: str,
    ref_to_table: dict[str, str],
    columns_ci: dict[str, set[str]],
) -> list[str]:
    """Return findings for one structural ``TABLE::COL`` reference, or [] if it resolves.

    Shared by the join `on:` clause check and the `column_id` check (checks 3 & 4)
    — both need to resolve TABLE against ``ref_to_table`` (name-or-alias) and then
    confirm COL exists in that table's generated column set.
    """
    if "::" not in ref:
        return []
    table_part, col_part = ref.split("::", 1)
    table_key = table_part.lower()
    if table_key not in ref_to_table:
        return [
            f"XREF: {context} references table '{table_part}' which is not "
            f"a model table — 'column_id not found' on import."
        ]
    physical = ref_to_table[table_key]
    physical_cols = columns_ci.get(physical.lower())
    if physical_cols is None:
        return []  # table itself wasn't generated — already reported by check 1
    if col_part.lower() not in physical_cols:
        return [
            f"XREF: {context} references column '{col_part}' which does not "
            f"exist on table '{physical}' — 'column_id not found' on import."
        ]
    return []


def _check_model_tables_exist(model_tables: list[dict], tables_ci: dict[str, str]) -> list[str]:
    """Check 1 — every model_tables[].name must have actually been generated."""
    findings: list[str] = []
    for t in model_tables:
        name = t.get("name")
        if name and name.lower() not in tables_ci:
            findings.append(
                f"XREF: model_tables references table '{name}' which was not "
                f"generated — import will fail ('{name} does not exist in schema')."
            )
    return findings


def _check_join_targets(
    model_tables: list[dict],
    ref_to_table: dict[str, str],
    columns_ci: dict[str, set[str]],
) -> list[str]:
    """Checks 2 & 4 — join targets (`with`) and any `[TABLE::COL]` refs inside `on:`."""
    findings: list[str] = []
    for t in model_tables:
        src_name = t.get("name", "?")
        for j in t.get("joins") or []:
            if not isinstance(j, dict):
                continue
            target = j.get("with")
            if target and target.lower() not in ref_to_table:
                findings.append(
                    f"XREF: join on '{src_name}' targets '{target}' which is not "
                    f"a model table — 'destination is missing' or '{target} does "
                    f"not exist in schema' on import."
                )
            on_clause = j.get("on") or ""
            # every bracketed ref, whatever the operator; server escapes (`dim\.csv`) undone
            for table_part, col_part in on_clause_refs(on_clause):
                findings.extend(
                    _check_table_col_ref(
                        f"{table_part}::{col_part}", f"join on '{src_name}'",
                        ref_to_table, columns_ci,
                    )
                )
    return findings


def _check_column_ids(
    columns: list,
    ref_to_table: dict[str, str],
    columns_ci: dict[str, set[str]],
) -> list[str]:
    """Check 3 — every `column_id: TABLE::COL` in columns[] resolves TABLE/COL."""
    findings: list[str] = []
    for c in columns:
        if not isinstance(c, dict):
            continue
        col_id = c.get("column_id")
        if not col_id or not isinstance(col_id, str):
            continue
        findings.extend(
            _check_table_col_ref(col_id, f"column '{c.get('name', col_id)}'", ref_to_table, columns_ci)
        )
    return findings


def lint_cross_references(model_tml: dict, tables: dict[str, set[str]]) -> list[str]:
    """Return dangling-cross-reference findings for a Model TML. Empty = clean.

    ``tables`` maps each generated table/sql_view NAME to the set of column names
    it provides (e.g. read off freshly-emitted Table/SQL View TML). This catches a
    Model that references a table or column that was never generated — a class of
    import rejection that only surfaces after a round trip to the server otherwise.

    Checks (all case-insensitive on names/columns, matching ThoughtSpot's own
    case-insensitivity on identifiers):

    1. Every ``model_tables[].name`` exists as a key in ``tables``.
    2. Every join target (``model_tables[].joins[].with``) resolves to a
       ``model_tables[]`` entry (matched by ``name`` or, when present, ``alias`` —
       the schema allows a self-join/role-playing table to be addressed by its
       alias, see agents/shared/schemas/thoughtspot-model-tml.md).
    3. Every ``column_id: TABLE::COL`` in ``columns[]`` resolves TABLE to a
       ``model_tables[]`` entry, and COL exists in that table's generated column set.
    4. Every ``[TABLE::COL]`` reference inside a join ``on:`` clause resolves the
       same way as (3).

    Only the structural ``TABLE::COL`` refs in ``column_id`` and joins are checked.
    ``formulas[].expr`` is not inspected — formula-internal ``[formula_*]`` id refs
    and bare (no ``::``) column refs are out of scope for this check.

    Pure function, no I/O.
    """
    if not isinstance(model_tml, dict):
        return []
    model = model_tml.get("model")
    if not isinstance(model, dict):
        return []

    # Case-insensitive index of the tables/sql_views actually generated.
    tables_ci: dict[str, str] = {name.lower(): name for name in tables}
    columns_ci: dict[str, set[str]] = {
        name.lower(): {c.lower() for c in cols} for name, cols in tables.items()
    }

    model_tables = [t for t in (model.get("model_tables") or []) if isinstance(t, dict)]

    # Every reference name a model_tables[] entry can be addressed by (its `name`
    # AND, when present, its `alias`) -> the entry's physical table name, so a
    # column-set lookup always keys into `tables` by the real generated name.
    ref_to_table: dict[str, str] = {}
    for t in model_tables:
        name = t.get("name")
        alias = t.get("alias")
        if name:
            ref_to_table.setdefault(name.lower(), name)
        if alias:
            ref_to_table.setdefault(alias.lower(), name or alias)

    findings: list[str] = []
    findings.extend(_check_model_tables_exist(model_tables, tables_ci))
    findings.extend(_check_join_targets(model_tables, ref_to_table, columns_ci))
    findings.extend(_check_column_ids(model.get("columns") or [], ref_to_table, columns_ci))
    return findings


# --- I16: semantic-layer measure aggregation, Model vs Table ------------------

def table_aggregations(table: dict) -> dict[str, tuple]:
    """``{column name or db_column_name, lower-case: (column_type, aggregation)}`` for one
    parsed ``table:`` body. Both names are indexed, as a Model ``column_id`` may use either."""
    out: dict[str, tuple] = {}
    for c in table.get("columns") or []:
        if not isinstance(c, dict):
            continue
        p = c.get("properties") or {}
        role = (p.get("column_type"), p.get("aggregation"))
        for key in (c.get("name"), c.get("db_column_name")):
            if key:
                out.setdefault(str(key).lower(), role)
    return out


def _check_many_to_many_joins(model_tables: list) -> list[str]:
    """I20 — a Model join's `cardinality` may not be MANY_TO_MANY.

    Rejected at import, error 14528: "Invalid value MANY_TO_MANY of field
    ...joins...cardinality. Allowed values are MANY_TO_ONE, ONE_TO_MANY, ONE_TO_ONE"
    (live-probed 2026-10-21). A Table TML's `joins_with` lists MANY_TO_MANY in its own
    vocabulary; that was not probed, so only Model joins are checked. A many-to-many
    relationship needs a bridge table (two MANY_TO_ONE joins), modelled in the warehouse.
    """
    findings: list[str] = []
    for t in model_tables:
        if not isinstance(t, dict):
            continue
        for j in t.get("joins") or []:
            if isinstance(j, dict) and str(j.get("cardinality") or "").upper() == "MANY_TO_MANY":
                findings.append(
                    f"I20: join '{j.get('name') or j.get('referencing_join') or '(unnamed)'}' "
                    f"({node_id(t)} -> {j.get('with', '?')}) is MANY_TO_MANY — ThoughtSpot "
                    f"rejects it (error 14528: allowed values are MANY_TO_ONE, ONE_TO_MANY, "
                    f"ONE_TO_ONE). Model the relationship through a bridge table, joined "
                    f"MANY_TO_ONE from each side, or drop the join."
                )
    return findings


def table_join_names(tables: dict) -> dict[str, set]:
    """physical table name (lower) -> the names of its Table TML `joins_with[]` entries.
    `tables` maps a table name to its parsed `table:` body (the I21 input)."""
    return {str(name).lower(): {jw.get("name") for jw in (body or {}).get("joins_with") or []
                                if isinstance(jw, dict) and jw.get("name")}
            for name, body in (tables or {}).items()}


def lint_referencing_joins(model_tml: dict, join_names: dict[str, set]) -> list[str]:
    """I21 — a `referencing_join` must name a join in its OWN entry's Table TML.

    A Model join that references a Table TML join sits under the entry whose Table
    declares it. Placed under the other table — or naming a join that table does not
    have — it is rejected at import, error 14504 "Relationships do not exist" (live-
    probed 2026-10-21: the same join imports under its declaring table and fails under
    its destination). Cross-file: only entries whose Table TML is in the batch
    (`join_names`, from `table_join_names`) are checked — a Model linted alone has no
    ground truth for what its Tables declare.
    """
    model = (model_tml or {}).get("model")
    if not isinstance(model, dict):
        return []
    findings: list[str] = []
    for t, ref in _undeclared_refs(model, join_names):
        findings.append(
            f"I21: '{node_id(t)}' references join '{ref}', which its Table TML "
            f"('{t.get('name')}') does not declare{_declared_on(ref, model, join_names)}. "
            f"ThoughtSpot rejects this (error 14504, 'Relationships do not exist')."
        )
    return findings


def lint_rls_join_cycles(model_tml: dict, table_bodies: dict, notes: list = None) -> list[str]:
    """I22 — an RLS rule's join must not close a cycle with the Model's joins.

    ThoughtSpot checks a Model's joins for cycles at import (I17), but applies an RLS
    rule's joins only when a query runs. When the rule on a table walks back into the
    Model's graph, query generation sees one table with two roots and fails with
    "Guid Mismatch" (BACH 12325) — on a support case it broke Liveboard filtering for
    every user under the rule. Graph mechanics: `tml_rls_graph`. Cross-file, as I21 is —
    only Tables linted in the same batch (`table_bodies`, physical name -> `table:`
    body) contribute RLS joins, so a Model linted alone is silent, not passed. A path
    that cannot be walked is not a finding (it would fail lint for a gap in our reading
    of the TML); pass a list as `notes` to collect it — `ts tml lint` prints those to
    stderr.
    """
    from ts_cli.tml_rls_graph import rls_join_cycles

    model = (model_tml or {}).get("model")
    if not isinstance(model, dict):
        return []
    findings: list[str] = []
    for hit in rls_join_cycles(model.get("model_tables") or [], table_bodies or {},
                               notes=notes):
        e, cycle = hit["rls_edge"], hit["cycle"]
        back = " -> ".join(cycle[1:])
        via = f" (Model joins: {', '.join(hit['model_joins'])})" if hit["model_joins"] else ""
        findings.append(
            f"I22: RLS on '{e.table}' joins out to '{cycle[1]}' ('{e.join}'), and joins "
            f"lead back {back}{via} — a loop query generation cannot resolve (it "
            f"fails with \"Guid Mismatch\"). Drop one of the two joins, or point the Model "
            f"at a copy of '{e.table}' without this RLS rule."
        )
    return findings


def _undeclared_refs(model: dict, join_names: dict[str, set]):
    """(model_tables entry, referencing_join) pairs whose entry's Table TML is in the
    batch and does not declare that join."""
    for t in model.get("model_tables") or []:
        if not isinstance(t, dict):
            continue
        declared = join_names.get(str(t.get("name") or "").lower())
        if declared is None:
            continue  # that Table's TML is not in the batch
        for j in t.get("joins") or []:
            ref = j.get("referencing_join") if isinstance(j, dict) else None
            if ref and ref not in declared:
                yield t, ref


def _declared_on(ref: str, model: dict, join_names: dict[str, set]) -> str:
    """Where a misplaced join IS declared, as a message suffix ('' if nowhere in batch)."""
    display = {str(e.get("name") or "").lower(): e.get("name")
               for e in model.get("model_tables") or [] if isinstance(e, dict)}
    owners = sorted(display.get(n, n) for n, names in join_names.items() if ref in names)
    return (f" — it is declared on '{owners[0]}', so the join belongs under that table's "
            f"entry") if owners else ""


def lint_model_table_aggregation(model_tml: dict, tables: dict[str, dict]) -> list[str]:
    """I16 — a Model column marked ``MEASURE``/``AGGREGATE`` must sit on a Table column
    that is ``AGGREGATE`` too.

    ``AGGREGATE`` is how a semantic-layer measure (Metric View, Semantic View) is
    passed through to the platform's own measure function. UI search reads the Model's
    aggregation, but AgentQL / SpotQL reads the **Table's**: with the Table at ``SUM`` an
    ``AGG()`` query is refused at generation and a ``SUM()`` query is sent as plain
    ``SUM(col)``, which the platform rejects (Databricks:
    ``METRIC_VIEW_MISSING_MEASURE_FUNCTION``). Verified 2026-10-07 on two DBX Models
    whose search worked while every AgentQL aggregate failed; setting the Tables to
    ``AGGREGATE`` fixed both.

    The reverse — Table ``AGGREGATE``, Model not — is deliberately NOT flagged: the same
    day a Model ATTRIBUTE over an ``AGGREGATE`` Table column searched correctly, so there
    is no observed failure to gate on. A Model column with no explicit ``aggregation`` is
    not flagged either (it may be inheriting).

    ``tables`` maps each Table name in the batch to :func:`table_aggregations` output.
    Tables not in the batch are skipped — there is nothing to compare against. Pure.
    """
    model = model_tml.get("model") if isinstance(model_tml, dict) else None
    if not isinstance(model, dict):
        return []
    tables_ci = {name.lower(): cols for name, cols in tables.items()}
    ref_to_table = _model_table_refs(model)
    findings: list[str] = []
    for c in model.get("columns") or []:
        finding = _i16_finding(c, ref_to_table, tables_ci)
        if finding:
            findings.append(finding)
    return findings


def _model_table_refs(model: dict) -> dict[str, str]:
    """Every name a model_tables entry is addressed by (name, alias) -> its name, lower-case."""
    refs: dict[str, str] = {}
    for t in model.get("model_tables") or []:
        if isinstance(t, dict) and t.get("name"):
            refs.setdefault(t["name"].lower(), t["name"].lower())
            if t.get("alias"):
                refs.setdefault(t["alias"].lower(), t["name"].lower())
    return refs


def _i16_finding(col: Any, ref_to_table: dict[str, str], tables_ci: dict[str, dict]) -> str | None:
    """The I16 finding for one Model column, or None."""
    if not isinstance(col, dict):
        return None
    cid = col.get("column_id")
    if (col.get("properties") or {}).get("aggregation") != "AGGREGATE" \
            or not isinstance(cid, str) or "::" not in cid:
        return None
    tpart, cpart = cid.split("::", 1)
    tcols = tables_ci.get(ref_to_table.get(tpart.lower(), tpart.lower()))
    role = tcols.get(cpart.lower()) if tcols is not None else None
    if role is None or role[1] == "AGGREGATE":
        return None
    table_role = "/".join(x for x in role if x) or "no role"
    return (
        f"I16: Model column '{col.get('name', cid)}' is MEASURE/AGGREGATE but Table column "
        f"'{cid}' is {table_role} — AgentQL/SpotQL uses the Table's aggregation, so every "
        f"aggregate query on it fails while UI search works. Set the Table column to "
        f"MEASURE/AGGREGATE as well."
    )
