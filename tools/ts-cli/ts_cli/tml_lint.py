"""Pre-import TML linter — model invariants worth catching before any round trip to
ThoughtSpot, whether or not the server's own validation surfaces them.

Most of these (I1/I2/I4/I5) are invariants `--policy VALIDATE_ONLY` does NOT catch —
ThoughtSpot accepts the TML and then behaves wrong later (silently drops a formula,
flips a measure to an attribute, breaks a join at query time). A couple (I8, I12) ARE
caught by the server (including under VALIDATE_ONLY) but are cheap, purely-structural
checks worth failing on locally, without a live call, especially across a batch of
generated TML. I15 is the misplaced-column-root-key check (BL-232): a `description` under
`properties:` imports with status OK and is then silently discarded. Rules mirror
invariants I1/I2/I4/I5/I8/I12/I13/I14/I15 in
`agents/shared/schemas/ts-model-conversion-invariants.md`.

Pure functions over a parsed TML dict so they are trivially unit-testable.
"""
from __future__ import annotations

import re
from typing import Any

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
    (I1/I2/I4/I5/I8/I12/I13/I14/I15) plus the guid-placement rule — see the module docstring
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


def _node_id(entry: dict) -> str:
    """A model_tables entry's node identity.

    `alias` wins when present — that is the whole point of an alias, and it is
    what `joins[].with` and `column_id` prefixes reference. Otherwise `id`
    (which I4 already pins to `name`), else `name`.
    """
    return entry.get("alias") or entry.get("id") or entry.get("name") or "?"


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
        frm = _node_id(t)
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


# A bracketed `[TABLE::COL]` reference inside a join `on:` expression. Matches
# regardless of the surrounding operator (`=`, `>=`, `<`, `and`, ...) — we only
# need every bracketed structural ref the expression contains.
_ON_REF_RE = re.compile(r"\[([^\[\]]+?)::([^\[\]]+?)\]")


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
            for table_part, col_part in _ON_REF_RE.findall(on_clause):
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
