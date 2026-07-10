# Design — Databricks Conversion Substrate: `ts databricks parse-mv` / `translate-formulas` / `build-model`

_Date: 2026-07-08 · Skill: `agents/cli/ts-convert-from-databricks-mv` · CLI: `tools/ts-cli` · Backlog: BL-063 Phase 2 (+ BL-032, BL-064)_

Process note: implementation is executed by Sonnet subagents; Fable orchestrates
and audits each PR before merge.

---

## Overview

`ts-convert-from-databricks-mv/SKILL.md` follows the LLM-executes-inline-Python
pattern: Step 5 parses Metric View YAML inline, Step 6 translates Databricks SQL
to ThoughtSpot formula syntax by having the model apply a mapping table by hand,
and Steps 9/9.5 assemble Model TML inline. This is exactly the architecture the
Tableau converter replaced with a deterministic CLI pipeline (`ts tableau parse`
→ `translate-formulas` → `build-model`; `tools/ts-cli/ts_cli/tableau_translate.py`
+ `model_builder.py`).

This spec codifies the same pipeline for Databricks:

```
ts databricks parse-mv  →  ts databricks translate-formulas  →  ts databricks build-model
```

replacing the inline Python in SKILL.md Steps 5, 6, and 9/9.5, closing BL-063's
Databricks phase (2a/2b/2c) and Phase-4 SKILL.md rewiring for this skill, and
folding in the BL-032 GA-construct parser gaps and BL-064 mapping fixes that
must land first.

---

## Goals & Non-Goals

**Goals**
- Deterministic, unit-testable parse/translate/build for Databricks Metric
  Views — same JSON-contract/pure-function discipline as the Tableau pipeline.
- Parse the **current GA** Metric View spec (`fields:`, `materialization:`,
  5-value `window.range`), not the stale v0.1-centric framing.
- Rewire `ts-convert-from-databricks-mv/SKILL.md` Steps 5/6/9/9.5 onto the new
  commands.
- Extract the shared pre-import lint+import procedure (this skill's
  `SKILL.md:1170-1259`, near-identical block in `ts-convert-from-snowflake-sv`
  `SKILL.md:1579-1660`) into one `agents/shared/` reference.
- Give the Databricks Genie notebook-agent effort (`agents/databricks/`,
  BL-005) a deterministic substrate to `%run` instead of re-deriving parsing
  logic in notebook Python.

**Non-Goals**
- `ts-convert-to-databricks-mv` (TS → MV direction; only 2 inline blocks,
  separate effort).
- Snowflake Phase 1a–1c (BL-063's own phasing runs Snowflake first; this spec
  is a deliberate reorder — see Background).
- A `--reverse` flag on any of the three commands.
- A Databricks HTTP client inside `ts-cli`.
- Resolving the MV-on-MV merge case (open-items #1) — stays fail-loud, not a
  supported transform.

---

## Background

**BL-063 and why Databricks jumps the queue.** BL-063 (`docs/backlog.md:1594`)
phased Snowflake first (1a–1c), Databricks second (2a–2c), gated on
*"assess feasibility by 2026-09-30 … only if mapping churn has slowed."* Two
Snowflake quick wins shipped 2026-07-03; phases 1a–4 remain open. This spec
**overrides that order for Databricks**, per explicit user direction: heavy
client demand plus the parallel Genie notebook-agent effort (BL-005) needing a
deterministic substrate now. The feasibility gate isn't dismissed — it's
**mitigated by PR 1** (the currency check), a mandatory precondition rather
than a background assumption.

**The Tableau pattern being mirrored.** `tools/ts-cli/ts_cli/commands/tableau.py`
exposes `parse` (line 98, TWB → JSON), `translate-formulas` (line 143, reads
`classification.json`, calls `tableau_translate.translate_formulas()`, writes a
`stats` block of `translated`/`skipped`/`total`/`levels`), and `build-model`
(line 971, assembles + phases + optionally imports TML). `tableau_translate.py`'s
docstring states the discipline this spec adopts: *"Pure functions: … in, …
out. No I/O, no network calls — trivially unit-testable."*

**What generalizes from `model_builder.py` and what doesn't.** Some transforms
operate on **ThoughtSpot formula text**, not Tableau syntax, and are directly
reusable by import (not copy): `add_formula_prefix()` (line 46, `[Name]` →
`[formula_Name]`), `expr_is_aggregated()`/`fix_double_aggregation()` (lines 84,
89, double-aggregation), `resolve_name_collisions()` (`ts_cli/tableau/naming.py`
— column/formula/parameter clashes are a TS Model TML concern, not Tableau's).
Other transforms are Tableau-domain-specific and don't carry over:
`build_formula_levels()`/`resolve_all_internal_refs()` (`ts_cli/tableau/dag.py`)
compute dependency levels from Tableau's `[Calculation_NNN]` indirection and
feed `split_for_phased_import()` — needed because Tableau's cross-formula
`[formula_X]` references must import in dependency order.

**Databricks doesn't need phased import.** The existing SKILL.md (Concept
Mapping, `SKILL.md:57,96-98`) already inlines `MEASURE()`/`ANY_VALUE()`
cross-measure references at translation time (open-items #4: TS `[formula_X]`
cross-refs fail on first import for this skill). So `translate-formulas`'
dependency DAG determines **inlining order**, not import phasing —
`ts_cli/databricks/build_model.py` needs no `split_for_phased_import()` analog.
Flag this explicitly in PR 3/4 so no one reflexively ports the phasing
machinery. Directly-reusable functions should be **imported from
`ts_cli.tableau.*`/`ts_cli.model_builder`**; if a Databricks case needs a
change, factor the shared logic up (e.g. a new `ts_cli/formula_common.py`)
rather than fork it.

---

## Architecture

### Package layout

```
ts_cli/
  databricks/
    __init__.py
    mv_parse.py       — YAML → structured dict (parse-mv)
    translate.py       — Databricks SQL expr → TS formula; per-formula
                          transforms + inlining-order DAG orchestrator
    build_model.py      — parsed+translated → Table/Model TML dicts
  commands/
    databricks.py       — thin Typer wrappers: arg parsing, file I/O,
                          JSON to stdout / diagnostics to stderr only
```

Constraint: `ts_cli/databricks/*` is stdlib + PyYAML only — no `requests`/
`typer`/`keyring`. This is what makes Genie vendoring (below) possible:
Databricks notebooks can `%run` these modules without the CLI's HTTP/auth deps.
Register via `app.add_typer(databricks.app, name="databricks")` in `cli.py`.

**No Databricks HTTP client in `ts-cli`.** All three commands take
already-fetched YAML/JSON files as input. Auth + `DESCRIBE TABLE EXTENDED`
fetch stays in SKILL.md Steps 1–4 via the external `databricks` CLI
(`SKILL.md:218-241`) — the `ts snowflake` precedent (pure diff/lint over
already-exported DDL), not the `TableauClient` precedent (a full HTTP client
justified by Tableau Server's auth/pagination complexity; a single `DESCRIBE
TABLE EXTENDED` + Statement-Execution poll doesn't warrant a second one).

### Command 1 — `ts databricks parse-mv`

```bash
ts databricks parse-mv {yaml_file_or_-} --output parsed.json
```

Codifies: version routing (`0.1` legacy vs `1.1` GA default,
`databricks-metric-view.md:95-100` — normalize both into one internal shape,
no downstream version branching); source-form classification (4 forms — table
FQN / parenthesized SQL / bare SQL / another metric view,
`ts-from-databricks-rules.md:44-101`); `fields:`/`dimensions:` alias
(`fields:` canonical, checked first); dimension classification (direct /
computed / LOD window); measure classification (simple / `COUNT(DISTINCT)` /
complex / windowed) including BL-032's 5-value `window.range`
(`current|cumulative|trailing|leading|all`) and `inclusive|exclusive` anchor
modifier; `joins:` nested-hierarchy walk (`on`/`using` XOR,
`cardinality:`/`rely:` precedence, `many_to_one` default —
`SKILL.md:456-493`'s `walk_joins()` becomes `parse_joins()`); the
**`materialization:` block** (BL-032/BL-064 #13 — undocumented anywhere today;
PR 1 must document it before this can parse it); metadata (`comment`,
`display_name`, `synonyms`, `format:`); global `filter:`.

MV-on-MV detection needs a live `information_schema.tables` lookup the parser
can't do — `parse-mv` classifies shape only, returning
`source.kind: "ambiguous_fqn"` with `needs_live_check: true`; the SKILL.md step
still runs the live check and fails loud if it resolves to a metric view.

**Error handling:** unknown `version:`, unparseable YAML, or a
syntactically-recognized-but-untranslatable construct (e.g. a subquery inside
a dimension `expr`) go into an `unsupported[]` array **and** cause a non-zero
exit with the list on stderr — never a silent drop.

**Shape sketch** (final field names settled in implementation planning):

```json
{
  "version": "1.1",
  "source": {"kind": "table_fqn", "raw": "catalog.schema.fact_table"},
  "joins": [{"alias": "orders", "source": {"kind": "table_fqn", "raw": "..."},
             "on": "source.ORDER_ID = orders.ORDER_ID", "using": null,
             "cardinality": "many_to_one", "cardinality_source": "rely", "joins": []}],
  "dimensions": [
    {"name": "order_date", "kind": "direct", "expr": "orders.ORDER_DATE",
     "display_name": "Order Date", "synonyms": ["order placed"]},
    {"name": "category_total_revenue", "kind": "lod_window",
     "expr": "SUM(source.LINE_TOTAL) OVER (PARTITION BY products.category.CATEGORY_NAME)",
     "partition_by": ["products.category.CATEGORY_NAME"], "inner_agg": "SUM"}
  ],
  "measures": [
    {"name": "revenue", "kind": "simple", "agg_function": "SUM", "physical_ref": "source.LINE_TOTAL"},
    {"name": "mom_growth_pct", "kind": "complex_cross_measure",
     "expr": "(MEASURE(monthly_revenue) - MEASURE(prior_month_revenue)) / MEASURE(prior_month_revenue) * 100",
     "cross_refs": ["monthly_revenue", "prior_month_revenue"]},
    {"name": "monthly_revenue", "kind": "windowed",
     "window": {"order": "order_month", "range": "current", "semiadditive": "last", "offset": null}}
  ],
  "filter": "NOT is_return AND transaction_status = 'Completed'",
  "materialization": null,
  "unsupported": []
}
```

### Command 2 — `ts databricks translate-formulas`

```bash
ts databricks translate-formulas --input parsed.json --output translated.json \
  --tables tables.json
```

Reads `parsed.json` plus a table/alias → ThoughtSpot-table-name map (resolved
in SKILL.md Step 8A/8B — Tableau's `--table-columns` role). Dimensions and
measures both flow through one pipeline (a computed dimension and a complex
measure are the same problem with a different `column_type`): dot-path
resolution (`alias.COL` → `[TABLE::COL]`); scalar/string/numeric/date function
map ported from `ts-databricks-formula-translation.md` as data (kept in sync
with that doc, same relationship `tableau/functions.py` has to its source
doc); conditional aggregates (`FILTER (WHERE cond)` → `agg_if`); LOD →
`group_aggregate(agg(x), {dims}, query_filters())` (3-arg, mandatory); window
measures per the `ts-from-databricks-rules.md` decision tree
(`moving_sum`/`cumulative_sum`/`last_value`/`sum_if(diff_*...)`); cross-measure
inlining via the dependency DAG (topological substitution, not phased
import — see Background); `COUNT(*)` → `count(1)`; `COUNT(DISTINCT col)` →
`unique count([TABLE::col])` (never `aggregation: COUNT_DISTINCT`).
`leading`/`all` window ranges stay `skipped` with `pending_verification: true`
unless PR 1 resolves them live.

**Per-formula status, never silent:** every dimension/measure lands in
`translated[]` or `skipped[]` with a `reason`, mirroring
`tableau_translate`'s `stats` block.

**Shape sketch:**

```json
{
  "translated": [
    {"name": "revenue", "column_type": "MEASURE", "ts_expr": "sum ( [FACT::LINE_TOTAL] )", "aggregation": "SUM"},
    {"name": "mom_growth_pct", "column_type": "MEASURE",
     "ts_expr": "( sum_if ( ... ) - sum_if ( ... ) ) / sum_if ( ... ) * 100",
     "inlined_refs": ["monthly_revenue", "prior_month_revenue"]}
  ],
  "skipped": [{"name": "trailing_forecast", "reason": "range: leading — PENDING LIVE VERIFICATION (BL-032)"}],
  "dependency_dag": {"mom_growth_pct": ["monthly_revenue", "prior_month_revenue"]},
  "stats": {"total": 14, "translated": 13, "skipped": 1}
}
```

### Command 3 — `ts databricks build-model`

```bash
ts databricks build-model --parsed parsed.json --translated translated.json \
  --tables tables.json --connection "{ts_connection_name}" --output-dir ./out \
  [--existing-guid {guid} --profile {name}] [--dry-run]
# --existing-guid = the update path: stamps guid: at the TML document root so
# import replaces the existing Model — NOT Tableau build-model's MERGE flow
# (no export-and-merge of live formulas).
```

Assembles Table TML (Scenario B, Step 8B's type-mapping rules) and Model TML
(columns, formulas, joins, model-level `filters:` for the MV's global filter,
`spotter_config` per Step 9.5). Reuses `add_formula_prefix`,
`fix_double_aggregation`, `resolve_name_collisions` by import (see
Background) — does **not** need `split_for_phased_import`; writes one Model
TML per Metric View, not a phase-0..N sequence.

Validates against `agents/shared/schemas/thoughtspot-*-tml.md` invariants
(`db_column_name` present, no `fqn:` in `connection:`, `guid:` at document
root, every formula has a matching `columns[]` `formula_id`, no
`aggregation:` in `formulas[]`) before handing off to `ts tml lint`
(SKILL.md's existing gate, `SKILL.md:1170-1191`) — a structural bug surfaces
with a specific field name, not a generic lint failure.

**Output:** `{model_name}.model.tml` (+ `{table_name}.table.tml` for new
tables) to `--output-dir`; with `--profile`, also imports. JSON summary
mirrors `ts tableau build-model`'s per-datasource result (table/column/formula
counts, `window_measures[]` for the Step 10 `⚠ WINDOW` review markers,
`import_status`).

### Genie vendoring (PR 5)

`agents/databricks/deploy.sh` vendors `agents/shared/` **markdown** files
(lines 38-50) via `databricks workspace import` (lines 79-89), and separately
imports `notebooks/ts_client.py` as a **Python notebook**
(`--format SOURCE --language PYTHON`, line 92-93) that Genie skills `%run`
(`agents/databricks/skills/ts-convert-from-databricks-mv/SKILL.md:17-19`).

PR 5 extends the notebook mechanism, not the markdown one: `ts_cli/databricks/
*.py` gets copied alongside `ts_client.py` and imported the same way, landing
at e.g. `.assistant/notebooks/databricks_mv_parse`. Genie SKILL.md steps `%run`
these instead of hand-rolling the logic the CLI-side SKILL.md's Steps 5/6/9
currently spell out inline (today's Genie skill is a thin shell claiming
"identical to the CLI skill" and doing it by hand — this closes that gap). One
mechanism detail is unresolved — see Open Questions.

---

## Currency-check pre-step (mandatory — gates PR 2)

Before parser code is written, PR 1 updates mapping/schema docs to the
**current** GA spec:

- Document the `materialization:` block (BL-032/BL-064 #13 — undocumented
  anywhere today).
- Re-verify `fields:`/`dimensions:` precedence has no stale references left in
  `ts-databricks-properties.md` or the formula-translation doc (BL-064 #2 is
  marked FIXED but PR 1 re-checks).
- **Deep analysis of metric definitions — window semantics (user-flagged).**
  The existing window mappings (the decision tree in
  `ts-from-databricks-rules.md`, the window rows in the formula-translation
  doc, and the window examples in
  `agents/shared/worked-examples/databricks/`) are of **uncertain
  correctness** and must be re-derived, not just re-read:
  1. Build the full semantic map of the MV measure `window:` spec from
     current Databricks docs: `order`, all five `range` values
     (`current|cumulative|trailing N unit|leading N unit|all`), `offset`,
     `semiadditive`, and the `inclusive|exclusive` anchor modifier —
     including default behaviors the docs leave implicit.
  2. **Verify empirically, not by spec-reading**: execute window-measure MVs
     against a live Databricks workspace with small known fixture data and
     record the actual result sets per `range`/`offset`/anchor combination.
  3. For every recorded ThoughtSpot translation
     (`moving_sum`/`cumulative_sum`/`last_value`/`sum_if(diff_*)` patterns),
     run the TS-side equivalent against matching data and confirm the
     **numbers match** — a windows-scoped slice of the parked
     conversion-fidelity angle (repo-audit angle 15). Any mismatch corrects
     the mapping doc + worked example before any code encodes it.
  4. Findings land in the authoritative docs (`databricks-metric-view.md`
     window section + `ts-from-databricks-rules.md` decision tree); if the
     analysis outgrows those sections, a dedicated
     `agents/shared/mappings/ts-databricks/window-semantics.md` is
     acceptable — settle in implementation planning.
  A confirmed result for `leading`/`all` lets Command 2 codify those ranges
  directly instead of the `pending_verification` skip path (currently PENDING
  in `databricks-metric-view.md:68-70` and both mapping docs).
- BL-064 medium items 5–13: fix whichever intersect `materialization`, window
  ranges, or `fields:` (must-fix); defer the rest to a follow-up BL-064 PR if
  unrelated to this parser.
- Bump the `<!-- currency: databricks — ... -->` anchors on every file touched
  to the PR 1 merge date.

PR 1 ships before PR 2 starts — parser naming/behavior matches the post-fix
docs, avoiding a rename pass later.

---

## Delivery plan — 5 sequential PRs

Off `wip/dbx-substrate` (or `feat/*` branches cut from it), each independently
reviewable and mergeable. Normal branching protocol — no direct merge to `main`.

**PR 1 — Currency check + window deep-analysis + mapping/schema fixes +
anchor bumps.** Docs only, no `ts-cli` code — but includes live Databricks
and ThoughtSpot verification runs (window semantics, step 2/3 of the
currency pre-step). *Acceptance:* BL-032 PENDING items resolved (with a
live-test citation) or re-flagged with today's date; `materialization:`
documented; **every window mapping and window worked-example either carries a
live-verified citation (Databricks result set + matching TS result) or is
corrected**; all four Databricks currency anchors bumped;
`check_mapping_currency.py` clean.

**PR 1.5 — Dimension/metric semantic deep-dive (added 2026-07-09, user-approved).**
PR 1's C6 finding exposed a failure class: mappings "live-verified" only at a
non-discriminating query shape. Four remaining constructs share that risk profile
and get the same claim-matrix + discriminating-experiment treatment before PR 3
freezes semantics into code: (a) LOD dimensions × filters — does
`group_aggregate(..., query_filters())` match DBX's window-over-filtered-or-unfiltered
choice; (b) cross-measure ratio inlining × grain — ratio-of-sums divergence when the
query grain differs from the MV grain; (c) global `filter:` × window ordering — filter
applied before or after window computation, both platforms; (d) semi-additive ×
date-range filters — last-in-data vs last-in-filtered-range. Method and assets reuse
PR 1's (deterministic fixtures, claim matrix, DBX_DAMIAN connection, searchdata
workaround). *Acceptance:* each of the four constructs carries a discriminating
live-verified verdict (or dated PENDING + blocker) in a claim matrix; corrections
applied to mapping docs/worked examples with the same citation discipline as PR 1;
anchors updated. Does NOT block PR 2 (parse-mv is structural) — blocks PR 3.

**PR 2 — `ts databricks parse-mv`.** New `ts_cli/databricks/__init__.py`,
`mv_parse.py`, `commands/databricks.py` (parse-mv only), registered in
`cli.py`. Covers all BL-032 GA constructs. Tests:
`tools/ts-cli/tests/test_databricks_parse.py`. *Acceptance:* parses every YAML
example in `databricks-metric-view.md` (v0.1 basic-sales, v1.1 single-source,
Dunder Mifflin Sales MV, Dunder Mifflin Inventory MV) with zero
`unsupported[]` entries; fails loud on a malformed/unknown-version fixture;
tests green; MINOR version bump.

**PR 3 — `ts databricks translate-formulas`.** `ts_cli/databricks/translate.py`
+ subcommand. Encodes the full `ts-databricks-formula-translation.md` decision
flowchart. Tests: `test_databricks_translate.py`, one class per transform
(mirrors `test_tableau_translate.py`). *Acceptance:* every formula in the four
`agents/shared/worked-examples/databricks/ts-from-databricks*.md` examples
translates to the exact TS text recorded there **as re-verified/corrected by
PR 1's window deep-analysis** — the golden fixtures are the post-PR-1
versions, never the possibly-wrong pre-analysis ones; `leading`/`all` skip
with `pending_verification: true` unless PR 1 resolved them; MINOR bump.

**PR 4 — `ts databricks build-model` + SKILL.md rewiring.**
`ts_cli/databricks/build_model.py` + subcommand. Rewire SKILL.md Steps 5, 6,
9, 9.5 onto the three commands; Step 10 reads `window_measures[]`/`skipped[]`
from JSON. **Live end-to-end verification gates merge**: run the rewired skill
against a real Metric View (Dunder Mifflin fixtures already referenced in the
worked examples) through to an imported ThoughtSpot Model, confirmed via
`ts metadata search` + `ts tml export` (Step 11b's existing pattern) — not
just unit tests. Update `tools/smoke-tests/smoke_ts_from_databricks.py` as the
live-verification entry point. Skill version: MINOR + Changelog entry dated at
PR creation; ts-cli: MINOR. *Acceptance:* smoke test passes live; no inline
`yaml.safe_load`/formula-assembly Python remains in Steps 5/6/9;
`check_skill_cli_usage.py`/`check_skill_flag_usage.py` clean.

**PR 5 — Shared lint+import extraction + Genie vendoring/adoption.** Extract
the pre-import lint+import procedure (this skill's `SKILL.md:1170-1259`,
`ts-convert-from-snowflake-sv`'s `SKILL.md:1579-1660`) to one shared
reference; both SKILL.md files link to it. `deploy.sh` vendors
`ts_cli/databricks/*.py` as notebooks; Genie SKILL.md `%run`s them.
*Acceptance:* `check_consistency`/`check_references` clean on the new shared
file; Genie SKILL.md changelog bumped; manual Genie-runtime review per
`.claude/rules/runtime-coverage.md` (outside the automated mirror-sync
tooling).

---

## Testing & verification

Pure-function unit tests, no live connection, in `tools/ts-cli/tests/`:
`test_databricks_parse.py`, `test_databricks_translate.py`,
`test_databricks_build_model.py` — one class per transform, modeled on
`test_tableau_translate.py`/`test_model_builder.py`. The verified worked
examples become golden-file regression fixtures: if a mapping change alters
output, the test fails loudly instead of silently drifting from
documented-verified behavior. Live verification is required only at PR 4 —
PRs 2/3 ship on unit tests alone, mirroring how `ts tableau parse`/
`classify-formulas` shipped before `build-model`'s live gate.
`smoke_ts_from_databricks.py` (updated in PR 4) is the live-verification entry
point per `.claude/rules/branching.md`'s merge criteria.

**Live-test environments (confirmed available):** Databricks via the
`Production` profile (`databricks` CLI alias `ts-production`, default catalog
`hive_metastore`) for PR 1's window experiments and PR 4's end-to-end run;
ThoughtSpot via the `se-thoughtspot` profile for the TS-side number-match and
model import. Destructive/import steps still pause for user authorization.

---

## Constraints & validators

| Validator / rule | Requirement here |
|---|---|
| `check_module_health.py` (CC cap 15) | No new baseline entries — keep functions small; follow `ts_cli/tableau/`'s package split (`conditionals.py`, `lod.py`, `functions.py`, …) from the start, not as a retrofit. |
| `check_file_size.py` (warn 500 / fail 1000) | `commands/databricks.py` stays thin (arg parsing + I/O only); split pure modules before hitting the warn threshold. |
| `check_version_sync.py` | Bump `__init__.py` + `pyproject.toml` together, one MINOR bump per PR that adds a command (PRs 2–4). |
| `check_skill_flag_usage.py` | SKILL.md flags must match real Typer options — update together. |
| `check_skill_cli_usage.py` | No inline TML-assembling heredocs left in SKILL.md after PR 4. |
| `.claude/rules/versioning.md` | Skill version bumps at PR-open time; `ts-convert-from-databricks-mv` gets MINOR in PR 4 (new capability, workflow steps unchanged). |
| `CHANGELOG.md` | Same-day entries for PRs 2–4's ts-cli bumps and PR 4's SKILL.md rewiring, per the batch-dating convention. |
| `tools/ts-cli/CLAUDE.md` "Adding a command" | Apply exactly, per new command (PRs 2–4): module, `cli.py` registration, `README.md` entry, SKILL.md update, unit tests, version bump both files. |
| `check_mapping_currency.py` | PR 1's anchor bumps prevent it flagging the touched files as stale. |

---

## Error handling philosophy

- **`parse-mv`**: fails loud on unknown `version:`, unparseable YAML, or a
  recognized-but-untranslatable construct — listed in `unsupported[]` *and*
  a non-zero exit with the list on stderr. Never a silent drop.
- **`translate-formulas`**: every formula resolves to `translated[]` or
  `skipped[]` with a `reason` — never silently absent.
- **`build-model`**: validates TML invariants before handing off to
  `ts tml lint`, so a structural bug surfaces with a specific field name
  rather than a generic lint failure or a live import rejection.

---

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Mapping surface still churning (BL-063's original concern) | PR 1 absorbs churn before code is written. If PR 1 finds more high-severity drift than BL-064 already catalogued, stop and re-raise feasibility before PR 2. |
| A subagent reflexively ports `split_for_phased_import`/`build_formula_levels` believing they're required | Called out explicitly in Background and PR 4 scope — the "no phased import" reasoning is written down. |
| PR 4 live verification depends on the Dunder Mifflin/e-commerce fixture workspace matching the worked examples | Same fixtures the shipped worked examples already depend on — drift there is a pre-existing problem, not one this PR introduces. |
| Genie multi-module vendoring (PR 5) has no exact existing precedent (only single-notebook `ts_client.py`) | Scoped to PR 5 only; doesn't block PRs 1–4. Flagged as an open question, not pre-decided. |
| `leading`/`all` ranges and the `inclusive`/`exclusive` default stay unverified past PR 1 | `translate-formulas` marks them `skipped`/`pending_verification` rather than guessing — same behavior as today's SKILL.md, enforced in code. |
| Existing window mappings/worked examples may be **wrong**, and PR 3 uses them as golden fixtures (user-flagged) | PR 1's window deep-analysis re-derives semantics empirically (live Databricks result sets + TS-side number-match) and corrects docs/examples before any code encodes them; PR 3 pins against the post-PR-1 versions only. |

---

## Open questions

- **Genie multi-module `%run` composition (PR 5 only) — RESOLVED 2026-07-10.**
  `%run` loads one notebook at a time; `ts_cli/databricks/` has three pure
  modules plus internal imports between them — **and** `build_model.py`
  deliberately imports shared pure functions from
  `ts_cli.tableau.naming`/`ts_cli.model_builder` (see Background), so the
  vendorable surface is wider than the `databricks/` directory alone. Options
  considered: (a) separate `%run` imports, each self-contained (requires
  avoiding cross-module imports inside the vendored copies, or vendoring the
  shared functions too); (b) concatenate the full transitive pure-function
  closure into one vendored notebook at deploy time.

  Resolved on **option (b)**, implemented as `agents/databricks/build_mv_lib.py`
  (run by `deploy.sh` at deploy time, never committed output): it concatenates
  the transitive closure — `tml_lint.py`, `tml_common.py`, `formula_common.py`,
  and the `databricks/mv_*.py` modules — into one generated `databricks_mv_lib`
  notebook, stripping every `from ts_cli.*` import so names resolve in the
  single exec namespace. Rationale: `%run` has no selective/partial import, so
  option (a) would require either duplicating the shared pure functions into
  each vendored copy (drift risk) or hand-maintaining per-module self-containment;
  option (b) instead lets the in-function cross-imports (e.g. `build_model.py` →
  `formula_common.py`) resolve naturally once everything shares one namespace.
  Determinism is enforced by two build-time gates rather than by convention:
  `assert_no_duplicate_top_level_names` (a name defined in two source modules
  would otherwise silently shadow one when concatenated) and a `compile(...,
  "exec")` syntax gate on the generated source before it's written.

No other open questions — architecture, JSON contracts, delivery sequencing,
and error-handling philosophy are settled per the fixed decisions this spec
documents.
