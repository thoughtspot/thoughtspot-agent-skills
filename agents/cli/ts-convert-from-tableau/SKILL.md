---
name: ts-convert-from-tableau
description: Convert or import a Tableau workbook (.twb or .twbx) into ThoughtSpot — parses TWB XML, generates table + model TMLs, validates and imports. Optionally migrates dashboards to liveboards with layout approximation. Direction is always Tableau → ThoughtSpot. Not for ThoughtSpot → Tableau or standalone TML exports.
---

# Tableau Workbook → ThoughtSpot

Converts a Tableau workbook into ThoughtSpot objects. Parses the TWB XML to extract
tables, columns, joins, and calculated fields, then generates Table TMLs and a Model
TML per datasource. Optionally converts Tableau dashboards into ThoughtSpot Liveboards
with approximate layout mapping.

Ask one question at a time for **dependent** decisions (where the next question depends on
the answer), waiting for each. But **batch independent questions into a single
multi-question prompt** to cut round-trips and keep the migration fast — e.g. mode + scope,
the count-column + bin-style + cohort-handling decisions, or theme + parameter-chips. See
**Efficiency** in Step 0.

---

## References

| File | Purpose |
|---|---|
| [../../shared/mappings/tableau/tableau-formula-translation.md](../../shared/mappings/tableau/tableau-formula-translation.md) | Tableau → ThoughtSpot formula and function mapping |
| [../../shared/mappings/tableau/tableau-tml-rules.md](../../shared/mappings/tableau/tableau-tml-rules.md) | TML generation rules — critical invariants for valid import |
| [../../shared/schemas/thoughtspot-table-tml.md](../../shared/schemas/thoughtspot-table-tml.md) | Table TML structure reference |
| [../../shared/schemas/thoughtspot-model-tml.md](../../shared/schemas/thoughtspot-model-tml.md) | Model TML structure reference |
| [../../shared/schemas/thoughtspot-sql-view-tml.md](../../shared/schemas/thoughtspot-sql-view-tml.md) | SQL View TML structure — for custom SQL datasources |
| [../../shared/schemas/thoughtspot-liveboard-tml.md](../../shared/schemas/thoughtspot-liveboard-tml.md) | Liveboard TML structure reference |
| [../../shared/schemas/thoughtspot-answer-tml.md](../../shared/schemas/thoughtspot-answer-tml.md) | Answer/visualization TML structure |
| [../../shared/schemas/thoughtspot-chart-types.md](../../shared/schemas/thoughtspot-chart-types.md) | Verified `answer.chart.type` enum (44 values) + analytical-intent → chart-type mapping |
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth setup |
| [references/open-items.md](references/open-items.md) | Known validation quirks and workarounds |
| [references/coverage-matrix.md](references/coverage-matrix.md) | Canonical mapped/unmapped construct matrix — cite in Audit mode (A4) and the migration report (Step 12) |
| [references/liveboard-style-themes.md](references/liveboard-style-themes.md) | Step 10.5 curated themes — brand tokens + per-chart `viz_style` color palettes |

---

## Prerequisites

- ThoughtSpot profile configured — run `/ts-profile-thoughtspot` if not
- `ts` CLI installed: `pip install -e tools/ts-cli`
- Tableau workbook file (`.twb` or `.twbx`) accessible on disk
- Tableau profile configured (optional) — run `/ts-profile-tableau` if migrating workbooks
  with published datasources (`sqlproxy`). Not needed for workbooks with direct connections.
- **The source tables and their data already exist in a warehouse, and a ThoughtSpot
  connection exposes them.** This skill creates ThoughtSpot *logical* objects (Table, Model,
  cohorts, Liveboard) **over existing physical tables** — it does **not** create warehouse
  tables or load/populate data. A ThoughtSpot table binds to a live connection that already
  surfaces the physical table and its columns (see Step 4.5 / `thoughtspot-table-tml.md`); if no
  such connection/table exists, set that up first (the data pipeline is out of scope). The
  skill *may read* the warehouse for confirmation (value formats, ranges, membership) — with
  your authorization — but never loads or modifies data.

---

## CLI-first rule — no inline Python for TML operations

**Every** ThoughtSpot API call, TML generation, formula translation, and model import in
this skill **must** go through a `ts` CLI command. Do not write inline Python scripts to
export/merge/import TML, iterate over formula failures, or assemble model JSON.

| Operation | Use this | NOT this |
|---|---|---|
| Translate formulas | `ts tableau translate-formulas` | Inline Python calling `tableau_translate.py` / the `ts_cli/tableau/` package modules |
| Build/merge model + formulas | `ts tableau build-model --existing-guid` | Manual export → JSON merge → import loop |
| Create tables | `ts tables create` | Raw HTTP calls to the TML import endpoint |
| Export/import TML | `ts tml export` / `ts tml import` | Manual curl or HTTP library calls |

If a CLI command fails or produces wrong results, **fix the CLI** (`tools/ts-cli/`) and
re-run — do not work around it with manual scripting. The CLI encodes months of
edge-case fixes (parameter conflict renaming, cross-reference resolution, iterative
retry, double-aggregation detection) that inline scripts will miss.

---

## Working principle — surface, recommend, resolve

Whenever the parse or generation hits a situation that has no clean 1:1 automatic
translation or needs a judgement call — e.g. a **cross-datasource blend**, a **join key that
doesn't exist / spans two tables**, a **date stored as VARCHAR**, **bins** (formula vs cohort),
an **ambiguous count column**, a **manual group** (cohort vs `if/then`), an **untranslatable
formula**, or a **value-vs-data mismatch** — do **not** silently drop it, guess, or merely
flag it. Instead:

1. **Surface it** — tell the user plainly what was found and why it's not a straight
   translation.
2. **Recommend** — if there's a sound solution (or a small set of options), say which and why,
   with the trade-offs.
3. **Resolve** — with the user's go-ahead, **do it** (build the SQL view, prompt for the
   value, retype the column, create the cohort, etc.). Only fall back to omit-and-flag when no
   solution exists or the user declines.

Default to *enabling* the migration, not abandoning the hard parts. The per-step prompts and
checkpoints below are how this principle is applied in practice.

**Read the actual calculation — never infer from the name.** A worksheet called "Highest
Growth in past 5 years" tells you the *intent*, not the *logic*. Always inspect the real
Tableau definition — the table-calc type (`pcdf`, `pctd`, `running_*`), the **filters**
(Top-N, recent-N-years), the **compute-using/partition**, and the **sort** — and translate
*that*. (Example: that title is really "top 5 sectors by FDI % change over a 6-year window" —
a period comparison, not a raw `growth of` line.)

**Placeholder charts when a full translation isn't possible.** If a viz can't be fully
reproduced, don't silently omit it — build a **placeholder**: a `TABLE` with the columns you
*can* produce, and write a note in **both** the viz's `answer.description` and the Migration
Summary tab that the chart is partial and **needs review**. A visible, labelled stub the user
can finish beats a missing tile.

---

## Step 0 — Overview

On skill invocation, display this plan before doing any work:

---
**ts-convert-from-tableau** — convert a Tableau workbook into ThoughtSpot TML objects,
with optional dashboard-to-liveboard migration.

### Modes

  **A  Audit** — analyse a TWB file (or multiple files) and report migration coverage.
     No ThoughtSpot auth required. No TMLs generated. Use this to assess feasibility
     before committing to a migration.

  **M  Migrate** — full conversion: parse, generate TMLs, validate, and import.

Enter A / M:

### Migrate scope (ask right after M — see Step 1.5)

When the user picks **M**, immediately ask **what to migrate** — this decides which steps run:

  **1  Models + Liveboards** — full flow (tables/models, then dashboards → liveboards). _(default)_
  **2  Tables + Models only** — build the data layer; **skip dashboards/liveboards**
      (skip Steps 8–11; go model → Step 11.5 coverage → Step 12 report).
  **3  Liveboards only** — the model(s) **already exist** in ThoughtSpot; skip table/model
      creation (skip Steps 4–7.5) and build liveboards on a **user-selected existing model**
      (see Step 1.5 model picker). Still parse the TWB for dashboards (Step 3).
  **4  Models only** — tables **already exist** in ThoughtSpot; skip table creation but
      build model(s) with formulas. Reuse existing table GUIDs (Step 4 E/G path).
      (skip Steps 5a table TML generation, 8–11; run Steps 4→5b→5.5→6→7→7.5→11.5→12).
  **5  Tables only** — generate and import table TMLs only; **skip models and liveboards**
      (run Steps 4→4.5→5a→6→12). Useful when tables need to be created/updated before
      a separate model migration pass.

### Steps (Migrate mode)

  1.  Authenticate to ThoughtSpot .......................... auto
  1.5 Choose migration scope (1–5) and pace (F/C) ...... you choose
  2.  Locate and extract the TWB file ...................... you provide path
  3.  Parse TWB XML — extract tables, columns, joins,
      calculated fields, blend relationships,
      table-calc addressing ............................ auto
  3.5 Resolve published datasources (sqlproxy → API) ... auto/you choose  [scope 1,2,4,5]
  3.6 Confirm joins (present/suggest/range join option) . you confirm   [scope 1,2,4]
  4.  Confirm source tables (reuse/GUID/create/search) ..... you choose  [scope 1,2,4,5]
  4.5 Select ThoughtSpot connection (create path only) .... you choose  [scope 1,2,5]
  5.  Generate TML files ................................. auto          [scope 1,2,4,5]
      5a Table TMLs (+ sql_view) ......................... auto          [scope 1,2,5]
      5b Model TML + formula translation ................. auto          [scope 1,2,4]
  5.5 Confirm Spotter (AI search) enablement (default Y) .. you choose   [scope 1,2,4]
  6.  Validate against ThoughtSpot (up to 10 fix cycles) .. auto         [scope 1,2,4,5]
  7.  Review checkpoint + two-phase import:               you confirm   [scope 1,2,4]
      Phase 1: base model (tables, columns, joins, params — NO formulas)
      Phase 2: add formulas (GUID-pinned update, iterative error recovery)
  7.5 Confirm the model is correct (test in Search/Spotter)  you confirm [scope 1,2,4]
  8.  Migrate dashboards? + separate vs single-tabbed (2+) . you choose (skip → Step 12) [scope 1,3]
  9.  Parse dashboard layout and map to grid ............... auto         [scope 1,3]
  9d. Orphan worksheets (not on a dashboard) — add as tiles? you choose   [scope 1,3]
 10c. Choose charting library (Legacy default / Muze) ........ you choose  [scope 1,3]
 10.  Generate liveboard TML (export model for params first) auto         [scope 1,3]
 10f. Add referenced parameters to the header? (default Y) . you choose   [scope 1,3]
 10g. Add a "Migration Summary" tab (migrated/decisions/omitted) auto     [scope 1,3]
 10.5 Pick a liveboard style (curated theme; default) ..... you choose    [scope 1,3]
 11.  Import liveboard ..................................... you confirm   [scope 1,3]
 11.5 Formula coverage answers (every formula testable) ... auto         [scope 1,2,4]
 12.  Migration report (outcomes + links + formula map) ... auto         [scope 1,2,3,4,5]
 12.5 Resume prompt — fix parked formulas? .............. you choose    [scope 1,2,4; if parked]

Confirmation required: Steps 1.5, 3.6, 4.5, 5.5, 7, 7.5, 8, 9d, 11, 12.5
Auto-executed: Steps 1, 3, 5, 6, 9, 10, 11.5, 12
Scope 2 (Tables + Models) skips 8–11; runs 11.5 then 12.
Scope 3 (LB only) skips 4–7.5; runs 1.5a model picker then 8–12.
Scope 4 (Models only) skips 4.5, 5a, 8–11; runs 4(E/G), 5b, 6–7.5, 11.5, 12.
Scope 5 (Tables only) skips 5b, 5.5–7.5, 8–11.5; runs 4, 4.5, 5a, 6, 12.

### Efficiency — keep the migration fast

The flow is interactive, but most of the wall-clock cost is avoidable. Apply these:

- **Batch independent prompts.** Use a single multi-question prompt for decisions that don't
  depend on each other: *mode + scope*; the *count-column + bin-style + cohort-handling*
  decisions; *theme + parameter-chips*. Only serialize genuinely dependent questions
  (e.g. search-scope → connection name).
- **Parse the TWB in one pass.** Extract datasources, columns, calc fields, parameters,
  dashboards, zones, and table-calc addressing in a *single* script — not one Bash call per
  element.
- **Read the model's real `obj_id` once, up front** (Step 10-pre) — exporting the model
  once yields `obj_id` **and** `parameters[].id` **and** the resolved column names. This
  prevents the slow build→import→fail→delete→re-import liveboard cycle (see the obj_id rule
  in Step 7 / Step 10-pre).
- **Don't fetch what you don't need.** Skip `ts connections list` / `ts connections get`
  whenever the user names the connection or the tables are reused (Steps 4/4.5). Skip the
  whole model/table layer entirely in scope 3 (LB only).

### Steps (Audit mode)

  A1.  Locate and extract TWB file(s) ...................... you provide path(s)
  A2.  Parse TWB XML — same extraction as Step 3 .......... auto
  A3.  Classify formulas into translation tiers ............ auto
  A4.  Migration coverage report ........................... auto

No auth, no TML generation, no import. Supports multiple files in one run.

---

If Audit mode, proceed to Step A1. If Migrate mode, proceed to Step 1 (then Step 1.5 picks
the migration scope, which gates the later steps).

---

## Step A1 — Locate TWB File(s) (Audit Mode)

Ask: "Provide the path to a `.twb` or `.twbx` file, or a directory containing multiple
workbooks."

If a directory is provided, find all `.twb` and `.twbx` files recursively. For each
`.twbx`, extract to a temp directory to access the inner `.twb`.

Save the list of TWB paths. Process each file through Steps A2–A4 independently.

---

## Step A2 — Parse TWB XML (Audit Mode)

Run the same extraction as Step 3 (3a through 3e) on each TWB file. Do NOT skip any
datasource type. For extracts, resolve the underlying source (Step 3b) and report it as
migratable via that source; mark as "Extract — no underlying source" only when none
resolves.

---

## Step A3 — Classify Formulas (Audit Mode)

> **MANDATORY (I7) — before classifying any calculated field as untranslatable, open
> [`../../shared/mappings/tableau/tableau-formula-translation.md`](../../shared/mappings/tableau/tableau-formula-translation.md)
> and check its full function table and pass-through section. Do not decide from syntax alone.**

Run the classifier — it shares the migrate-mode translation verdict, so the audit
cannot over- or under-promise coverage:

```bash
ts tableau classify-formulas --input /tmp/ts_tableau_mig/{workbook_name}_parsed.json --output /tmp/ts_tableau_mig/audit/{workbook_name}_classification.json
```

**The classifier works per datasource** — each datasource becomes its own model in
migration, and the same calc *name* can carry a *different* expression in each
datasource, so it must be tiered against its own. For a parsed-workbook input the
output is `{ "datasources": [ {"name", "formulas", "tier_counts", "translate_stats"}, … ],
"tier_counts": <sum across datasources> }`. Each `formulas[]` entry has `tier`, `reason`,
`level`, and `complexity`. Report **per datasource** (Step A4's per-datasource breakdown)
and use the top-level `tier_counts` for the workbook total. (Pass `--datasource "<name>"`
to limit to one; a bare-list input — e.g. Step 5b's `translate-formulas` file — instead
yields a flat `{formulas, tier_counts, translate_stats}`.)

Translatable tiers: `native`, `lod`, `cumulative`, `moving`, `pass_through`,
`row_offset_native`, `parameter_ref`. Untranslatable tiers: `untranslatable`,
`row_offset_ambiguous`, `geospatial`, `circular`, `orphan`, `parameter_query`.

The table below maps those tiers to the human-readable categories used in the report —
kept as reference/documentation now, not as executed classification logic:

| Tier | Description | Examples |
|---|---|---|
| **Native / Set** | Direct ThoughtSpot mapping exists | IF/THEN, IFNULL, DATEDIFF, LEFT, ABS, ROUND, IIF; **bins** (`class='bin'`) → `floor([x]/size)*size` or BIN_BASED cohort; **manual groups** (`class='categorical-bin'`, incl. fields named "… clusters") → `GROUP_BASED` cohort; `Number of Records`/row counts → `count([column])` (**prompt** for the column; default the primary key); **static sets** (`<group>` with `union`/`member`) → `GROUP_BASED` column-set cohort — incl. ones anchored on a **formula column**, with a **`%null%`** member (via `EQ {Null}`), or an **`except` member-list** (via `NE`) (Phase 2a); **Top-N/Bottom-N sets** (`function='end'`) → query set (`cohort_type: ADVANCED`, `COLUMN_BASED`) via a rank formula + parameter-filter formula (Phase 2b); **condition-based sets** (`function='filter'`) → query set with aggregate condition formula (Phase 2c); **member-list intersect** → `GROUP_BASED` cohort of common members (Phase 2c); **all-except-Top-N** → query set with inverted rank filter (Phase 2c); **computed set operations** (intersect/except of mixed types) → multi-formula query set (Phase 2c) |
| **LOD** | LOD expression → `group_aggregate()` | `{FIXED dim : SUM(col)}`; **`TOTAL(SUM(x))`** / percent-of-total → `group_aggregate(..., {}, query_filters())` |
| **Cumulative** | Running calculation → `cumulative_*()` | RUNNING_SUM, RUNNING_AVG |
| **Moving** | Window table calc → `moving_*()` | WINDOW_SUM, WINDOW_AVG (when sort attr determinable) |
| **Pass-through** | Valid SQL but no native function → `sql_*_aggregate_op()` | Partitioned RANK, DENSE_RANK, WINDOW_* without sort context |
| **Partial / Unmapped (sets)** | Tableau set construct with no current ThoughtSpot equivalent — logged as deferred, never mis-translated | **set controls** (`level-members` only, no fixed members) → no set object, surface as a liveboard filter; **set actions** (`<action>`) → no equivalent |
| **Row-offset (native)** | Table calc with recoverable intent → native TS function | `INDEX() <= N` (Top-N filter → `rank()` + query set); `INDEX()` display → `rank()`; `LOOKUP(-N)` → `moving_sum(N,-N)`; `LOOKUP(+N)` → `moving_sum(-N,N)`; `LOOKUP(agg, FIRST())` → `first_value()`; `LOOKUP(agg, LAST())` → `last_value()`; bare `FIRST()`/`LAST()` standalone → omit + log (returns offset, not value) — **all native mappings use native TS functions, work with all column types** |
| **Row-offset (pass-through)** | `SIZE()` only → answer-level `sql_int_aggregate_op("COUNT(*) OVER()")` | `SIZE()` — only row-offset that still requires SQL pass-through ⚑ flag PT1 |
| **Untranslatable** | No ThoughtSpot equivalent — will be omitted | `INDEX`/`LOOKUP`/`FIRST`/`LAST`/`SIZE` **when addressing is ambiguous** (CellInPane, multi-dim Table, or no shelf sort); `PREVIOUS_VALUE` (true recursion — not the string-aggregation technique); true **k-means clustering** (the analytics-engine "Clusters" calc — **not** `categorical-bin`); **geospatial** — full 13-function set (`MAKEPOINT`, `MAKELINE`, `BUFFER`, `OUTLINE`, `DISTANCE`, `AREA`, `LENGTH`, `INTERSECTS`, `SHAPETYPE`, `DIFFERENCE`, `INTERSECTION`, `SYMDIFFERENCE`, `VALIDATE`) — decompose `MAKEPOINT` lat/lon args to individual attribute columns, omit the spatial formula (see `tableau-formula-translation.md` Geospatial Policy); **embedded-RLS user attributes** (`USERATTRIBUTE`, `USERATTRIBUTEINCLUDES`) — rejected at translate time, see BL-071 |
| **Parameter ref (auto)** | References a Tableau parameter with static list/range — parameter auto-created in model | `[Parameters].[Currency]` where Currency has `<member>` values |
| **Parameter ref (query)** | References a Tableau parameter with SQL-lookup list — queryable at migration time | SQL-populated parameter lists (needs connection) |

---

## Step A4 — Migration Coverage Report (Audit Mode)

For each TWB file, produce a coverage report. If multiple files were audited, also
produce a combined summary at the end.

**Source the numbers from `classification.json` (Step A3's `ts tableau classify-formulas`
output) — do not hand-tally tiers.** The output is **per datasource**: iterate
`classification.json`'s `datasources[]` for the per-datasource breakdown (each carries its
own `formulas[]`, `tier_counts`, and `translate_stats` — where `total == translated +
skipped` for that model), and use the top-level `tier_counts` for the workbook total. The
per-formula rows (Row-offset detail, Excluded Formulas, "Needing Review") come from each
`datasources[].formulas[]` entry's `tier`/`level`/`complexity`/`reason` fields.

**Per-file report:**

```
Audit: {workbook_name}
══════════════════════════════════════════════════════

  Datasources:          {N} total
    Live:               {N}
    Extract:            {N} (skipped in migration)
    Published (sqlproxy): {N}

  Physical tables:      {N}
  Custom SQL relations: {N} → will generate sql_view TMLs
  Joins:                {N}

  Calculated fields:    {N} total
  ┌──────────────────────────────────────────────────────┐
  │ Tier                    Count    %     Examples      │
  ├──────────────────────────────────────────────────────┤
  │ Native                  {N}     {%}   IF, DATEDIFF  │
  │ LOD → group_agg         {N}     {%}   {FIXED ...}   │
  │ Cumulative              {N}     {%}   RUNNING_SUM   │
  │ Moving                  {N}     {%}   WINDOW_SUM    │
  │ Pass-through            {N}     {%}   DENSE_RANK    │
  │ Row-offset (native)     {N}     {%}   LAG→moving_sum│
  │ Row-offset (pass-thru)  {N}     {%}   SIZE→COUNT(*) │
  │ Parameter ref (auto)    {N}     {%}   static list   │
  │ Parameter ref (query)   {N}     {%}   SQL lookup    │
  │ Geospatial (omit+log)   {N}     {%}   MAKEPOINT     │
  │ Untranslatable          {N}     {%}   INDEX(ambig)  │
  └──────────────────────────────────────────────────────┘

  Cross-reference depth (formula-to-formula dependencies):
  ┌──────────────────────────────────────────────────────┐
  │ Depth                   Count    %     Note          │
  ├──────────────────────────────────────────────────────┤
  │ Level 0 (self-contained) {N}    {%}   Translate directly │
  │ Level 1 (refs Level 0)   {N}    {%}   Inline from Level 0 │
  │ Level 2+ (deep chains)   {N}    {%}   Multi-level inlining │
  │ Circular dependencies    {N}    {%}   Cannot resolve │
  └──────────────────────────────────────────────────────┘

  Formula complexity (effort estimate):
  ┌──────────────────────────────────────────────────────┐
  │ Complexity              Count    %     Criteria      │
  ├──────────────────────────────────────────────────────┤
  │ Simple (1–2)            {N}     {%}   ≤1 function, no cross-refs, no nesting │
  │ Medium (3–5)            {N}     {%}   2–3 functions or 1 cross-ref or 1 nesting level │
  │ Complex (6+)            {N}     {%}   4+ functions, 2+ cross-refs, or deep nesting │
  └──────────────────────────────────────────────────────┘
  Score = nesting_depth + cross_ref_count + function_count (each function/operator = 1)

  Effective migration coverage:
    Syntax-level:            {N}/{total} ({%}%) — based on tier classification only
    After orphan exclusion:  {N}/{total} ({%}%) — minus {N} orphan inherited calcs
    After dep resolution:    {N}/{total} ({%}%) — minus {N} circular, {N} unresolvable cross-refs
    ──────────────────────
    Realistic estimate:      {N}/{total} ({%}%)

  ⚠ The tier classification reports SYNTAX-LEVEL translatability. The realistic
  estimate accounts for orphan calcs (Step 3g), circular dependencies, and
  unresolvable cross-references. A formula classified "Native" may still not
  migrate if it depends on an orphan or circular chain.

  Tableau Sets (top-level <group> elements — separate from calculated fields):
  ┌──────────────────────────────────────────────────────┐
  │ Set tier                Count    Notes               │
  ├──────────────────────────────────────────────────────┤
  │ Native / column set     {N}      static + member-intersect → GROUP_BASED cohort (2a/2c) │
  │ Query set               {N}      Top-N, condition, all-except-Top-N, mixed ops → ADVANCED (2b/2c) │
  │ Partial / deferred      {N}      set controls + set actions (no equivalent)     │
  └──────────────────────────────────────────────────────┘

  Parameters:           {N} total ({N} static, {N} SQL-lookup — query at migration)
  Dashboards:           {N} (optional liveboard migration)

  ──────────────────────────────────────────────────
  Migration coverage:   {(all except untranslatable-ambiguous) / total}%
                         (all parameters auto-created — static or queried)
  Untranslatable:       {N} formula(s) — will be omitted
  Geospatial:           {N} formula(s) — spatial funcs omitted; lat/lon cols migrated as attributes
  Deferred sets:        {N} (set controls/actions — flagged for manual creation)
  SQL-lookup params:    {N} — need warehouse connection at migration time
  Pass-through formulas (DENSE_RANK, SIZE, etc.) require SQL Passthrough Functions enabled.
  Row-offset native formulas (LAG, LEAD, LOOKUP(agg,FIRST/LAST), INDEX) use native TS functions — no pass-through needed.
  Bare FIRST()/LAST() standalone → omitted (returns offset, not value — no TS equivalent).

  Migration effort estimate:
    Formula translation:  deterministic (CLI pipeline, no LLM calls)
    Phase 1 import:       ~1-2 minutes (tables + base model)
    Phase 2 import:       ~{N} retry cycles expected
      Simple formulas:    {N} — likely import on first try
      Medium formulas:    {N} — may need 1-2 retries
      Complex formulas:   {N} — expect structural fixes
    Estimated total:      {M}-{N} minutes (model only, excludes liveboard)

  Orphan inherited calcs:  {N} formula(s) referencing missing tables
  ┌──────────────────────────────────────────────────────────────────────────┐
  │ These calcs were inherited from a parent/copied datasource and          │
  │ reference tables not present in this datasource. They are               │
  │ non-functional in Tableau and will be excluded from migration.          │
  │                                                                         │
  │ Missing tables: {table1}, {table2}, …                                   │
  │                                                                         │
  │  #   Formula Name              Missing Table Reference                  │
  │  1   {name}                    {TABLE_NAME}                             │
  │  …                                                                      │
  │                                                                         │
  │ (Includes {N} transitive orphans — depend on a direct orphan)           │
  └──────────────────────────────────────────────────────────────────────────┘

  ⚠ Formulas Needing Review:  {N} formula(s)
  ┌──────────────────────────────────────────────────────────────────────────┐
  │  #   Formula Name              Category           What to Verify        │
  ├──────────────────────────────────────────────────────────────────────────┤
  │  1   {name}                    No-keyword LOD      Test with/without    │
  │                                                    search filters       │
  │  2   {name}                    Blend-context        Compare totals      │
  │  3   {name}                    Pass-through SQL     SQL Passthrough on? │
  │  4   {name}                    ifnull stripped      Verify null display │
  │  5   {name}                    sum_if rewrite       Verify aggregation  │
  │  …                                                                      │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ Categories:                                                             │
  │  No-keyword LOD   {AGG([col])} → group_aggregate — filter context may  │
  │                   differ (Tableau: after dim filters, before table-calc)│
  │  Blend-context    Secondary datasource ref — post-agg blend vs row join│
  │  Pass-through SQL sql_*_aggregate_op — requires cluster setting enabled│
  │  ifnull stripped  ifnull(measure,0) removed — TS handles NULLs natively│
  │  sum_if rewrite   sum(if…then…else 0) → sum_if() — semantically equiv │
  └──────────────────────────────────────────────────────────────────────────┘

  Data Blending — post-aggregation semantics:
  ┌──────────────────────────────────────────────────────────────────────────┐
  │ ⚠ Tableau blends aggregate the secondary datasource independently     │
  │ before joining. ThoughtSpot model joins operate at row level.          │
  │ If both sides are fact tables at different grains, aggregation         │
  │ results may differ.                                                    │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ Primary DS          Secondary DS       Link Cols    Risk               │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ {ds_caption}        {ds_caption}       {col1, …}   {HIGH/MED/LOW}     │
  │ …                                                                      │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ Risk: HIGH = both sides have measures (fact×fact — aggregation may     │
  │              diverge)                                                   │
  │       MED  = secondary has measures but likely reference table         │
  │       LOW  = secondary is dimension-only                               │
  └──────────────────────────────────────────────────────────────────────────┘
  Blended datasources:  {N} of {total} — will merge into single model(s)
  Blend relationships:  {M} total
  Star topologies:      {S} (1 primary → 2+ secondaries)
  HIGH-risk blends:     {N} — verify aggregation results post-migration
  ──────────────────────────────────────────────────
```

**Migration coverage** includes everything except Untranslatable. All parameter types
are auto-migratable: static params are created directly in the model TML; SQL-lookup
params are populated by querying the warehouse at migration time. The formula reference
`[Parameters].[Name]` is rewritten to `[Name]` in both cases. Cite
[`references/coverage-matrix.md`](references/coverage-matrix.md) as the canonical source
when classifying a construct as mapped/unmapped or explaining a limitation.

If any formulas are classified as Row-offset, list them:

```
  Row-offset formulas (translated via decision tree):
    - {formula_name}: {tier} — {tableau_expr} → {ts_expr or "omit (ambiguous)"}
    - ...
```

**Excluded formulas** — every formula that will NOT be migrated, grouped by root cause:

```
  Excluded Formulas: {N} total
  ┌──────────────────────────────────────────────────────────────────────────┐
  │ Root Cause               Count  Potential Resolution                    │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ Untranslatable function  {N}    No TS equivalent — SQL view or UDF      │
  │ Missing table in model   {N}    Add source tables, then create formula  │
  │ Circular dependency      {N}    Break cycle by inlining one formula     │
  │ Complex date arithmetic  {N}    Rewrite with TS date funcs or warehouse │
  │ Geospatial function      {N}    Spatial not supported — lat/lon as attr │
  └──────────────────────────────────────────────────────────────────────────┘

  Per-formula detail:
    {Root cause category} ({N}):
    - {formula_name}: {tableau_expr} — {what the user can do}
    - ...
```

If any SQL-lookup parameters exist, note them:

```
  SQL-lookup parameters ({count} — populated from warehouse at migration time):
    - {param_name}: query/column reference from TWB
    - ...
  Values are a point-in-time snapshot. Consider /ts-recipe-parameter-sync for
  ongoing refresh.
```

If any formulas are classified as Pass-through, list them with the generated expression:

```
  Pass-through formulas (require SQL Passthrough Functions enabled):
    - {formula_name}: sql_{type}_aggregate_op("...", ...)
    - ...
```

Write the report to `/tmp/ts_tableau_mig/audit/{workbook_name}_audit.md` and display
it inline.

**Per-datasource breakdown** (when a workbook has multiple datasources):

Report coverage **per datasource**, not just workbook-wide. Different datasources within
the same workbook can have very different effective migration rates (e.g. a full datasource
at 73% vs a copied subset at 54%). A combined number hides this.

```
  Per-datasource coverage:
  ┌──────────────────────────────────────────────────────────────────────────┐
  │ Datasource              Tables  Calcs  Orphans  Realistic Coverage     │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ {ds_name_1}             {N}     {N}    {N}      {N}/{N} ({%}%)         │
  │ {ds_name_2} (copy)      {N}     {N}    {N}      {N}/{N} ({%}%)         │
  └──────────────────────────────────────────────────────────────────────────┘
```

**Combined summary (multiple files):**

```
Audit Summary: {N} workbook(s)
══════════════════════════════════════════════════════

  Workbook                          Tables  Calcs  Orphans  Coverage
  ─────────────────────────────────────────────────────────────────────
  {workbook_1}                      {N}     {N}    {N}      {%}%
  {workbook_2}                      {N}     {N}    {N}      {%}%
  ...
  ─────────────────────────────────────────────────────────────────────
  Total                             {N}     {N}    {N}      {%}%

  Coverage = realistic estimate (after orphan + circular + cross-ref exclusion)
```

After the audit, exit cleanly. Do NOT proceed to Migrate mode steps.

---

## Step 1 — Authenticate

Run `ts profiles list` to discover available ThoughtSpot profiles. If no profiles
exist, run `/ts-profile-thoughtspot` to create one. If multiple profiles exist,
display a numbered menu and ask the user to choose. If only one profile, use it
automatically.

```bash
ts profiles list
```

Then verify the chosen profile:

```bash
source ~/.zshenv && ts auth whoami --profile "{profile_name}"
```

Save `{base_url}` and `{profile_name}` for all subsequent steps.

---

## Step 1.5 — Choose Migration Scope

Right after auth, ask **what to migrate** (this can be batched with the profile choice when
there are multiple profiles). The answer gates which later steps run:

```
What should I migrate?
  1  Models + Liveboards — build/reuse tables & models, then dashboards → liveboards  (default)
  2  Tables + Models only — build the data layer; skip dashboards/liveboards
  3  Liveboards only — models already exist; skip table/model creation and build
                       liveboards on an existing model I help you pick
  4  Models only — tables already exist in ThoughtSpot; skip table creation,
                   build model(s) referencing existing tables
  5  Tables only — generate and import table TMLs; skip models and liveboards

Migration pace?  (scopes 1, 2, 4 only — omit for scopes 3 and 5)
  F  Fast — import formulas, park any failures, move on  (default)
  C  Complete — after import, attempt to fix each failure (slower)

Enter scope (1-5) and pace (F/C):
```

Apply the scope:

| Scope | Runs | Skips |
|---|---|---|
| **1 Models + Liveboards** | all steps | — |
| **2 Tables + Models only** | 2–7.5, then 11.5 (coverage), 12 | **8–11** (dashboards/liveboards) |
| **3 Liveboards only** | 1.5a model picker, 2–3 (parse, dashboards), 8–12 | **4–7.5** (table/model creation) |
| **4 Models only** | 2–3 (parse), 4 (E/G to find existing tables), 5b (model TML + formulas), 5.5, 6, 7, 7.5, 11.5, 12 | **4.5** (connection — tables already bound), **5a** (table TMLs), **8–11** (liveboards) |
| **5 Tables only** | 2–3 (parse), 4, 4.5, 5a (table TMLs), 6, 12 | **5b** (model), **5.5–7.5**, **8–11** |

Save the pace as `{migration_pace}` (`F` or `C`). Default `F` if the user enters only a
scope number or skips the pace question. For scopes 3 and 5, `{migration_pace}` is always
`F` (no formula imports, so the pace has no effect).

For scope **2**, after Step 7.5 jump straight to Step 11.5 then Step 12.

For scope **3**, there is no model to build — the user selects an **existing** model, and the
liveboard tiles reference *its* columns/formulas. Run **Step 1.5a** below to pick it, then
parse the TWB (Steps 2–3) and continue at Step 8. (Step 9b maps each worksheet's shelves to
the **chosen model's** columns by display name — surface any field that has no matching
column rather than guessing.)

For scope **4**, tables already exist in ThoughtSpot — the user provides GUIDs or searches
for them (Step 4, **E** or **G** path). No connection selection or table TML generation
needed. The model TML references existing tables by GUID. This is the common path for
consultant/remote migrations where tables were loaded separately (e.g. via
`/ts-load-source-data` or manual warehouse provisioning + `ts tables create`). After
Step 7.5, jump to Step 11.5 then Step 12.

For scope **5**, only table TMLs are generated and imported. No model, no formulas, no
liveboard. Useful for a phased migration where tables are set up first, then models are
created in a second pass (scope 4).

### Step 1.5a — Pick an existing model (scope 3 only)

A ThoughtSpot **Model is a `worksheetVersion: V2` logical table** — there is **no `MODEL`
subtype** in `metadata search`. Find models with `--subtype WORKSHEET` (which returns
worksheets *and* models) and keep only those whose `metadata_header.worksheetVersion == "V2"`.

**Prompt how to identify the model — don't list every model by default** (the full list is
slow on a large instance). Mirror the connection picker (Step 4.5):

```
How would you like to choose the model?
  G  GUID         — paste the model's GUID; I'll fetch it directly      (fastest)
  N  Name it      — type the exact model name
  F  Filter       — give a partial string; I'll list matching models
  L  List all     — show every model and pick by number   (slow — scans all worksheets)

Enter G / N / F / L:
```

Resolve the choice:

- **G (GUID)** — fetch directly and confirm it's a model:
  ```bash
  source ~/.zshenv && ts metadata search --guid {model_guid} --profile {profile_name}
  ```
  Verify `metadata_type == "LOGICAL_TABLE"` and `metadata_header.worksheetVersion == "V2"`.
  If V1 (a classic worksheet) or not found, say so and re-ask.
- **N (name it)** — exact-name search, filter to V2:
  ```bash
  source ~/.zshenv && ts metadata search --subtype WORKSHEET --name "{model_name}" --profile {profile_name}
  ```
  Exactly one V2 match → use it; none/ambiguous → show closest and re-ask.
- **F (filter)** — `--name "%{partial}%"`, keep V2 matches, show a short numbered list
  (name, obj_id, guid) and pick from it.
- **L (list all)** — **warn it's slow**, then `--subtype WORKSHEET --all`, keep V2, show the
  numbered list. Only use when the user can't name/filter.

```bash
# F / L pattern (filter applied client-side to V2 only)
source ~/.zshenv && ts metadata search --subtype WORKSHEET --name "%{partial}%" --profile {profile_name}
```

From the chosen model capture and save: `{model_guid}` (`metadata_id`), **`{model_obj_id}`**
(`metadata_obj_id` — the **real** obj_id; see the obj_id rule in Step 7), and `{model_name}`
(`metadata_name`). Then **export it once** (Step 10-pre) to read its columns, formulas, and
`parameters[].id` for building liveboard tiles. Confirm the picked model with the user before
proceeding:

```
Using existing model: {model_name}
  {base_url}/#/data/tables/{model_guid}
  Columns: {n}   Formulas: {f}   Parameters: {names}
Build liveboards on this model? (yes / pick another)
```

---

## Step 2 — Extract TWB File

Ask for the file path if not yet provided.

If the file ends in `.twbx` (a ZIP archive), extract it:

```bash
mkdir -p /tmp/ts_tableau_mig && unzip -o "{twbx_path}" -d /tmp/ts_tableau_mig/
```

Then find the `.twb` inside:

```bash
find /tmp/ts_tableau_mig -name "*.twb" | head -1
```

Save the resolved `.twb` path as `{twb_path}`.

---

## Step 3 — Parse TWB XML

Run the parser and read its JSON — do NOT hand-parse the XML:

```bash
ts tableau parse "{twb_path}" --output /tmp/ts_tableau_mig/{workbook_name}_parsed.json
```

The JSON contains `datasources[]` (each with `tables`, `columns`, `joins`,
`calculated_fields`, `calc_map`, `col_table_map`, `orphan_calcs`), `parameters`,
`param_map`, `blends`, and `table_calc_addressing`. All subsequent steps read
these fields instead of re-deriving them.

The parse output (from the `ts tableau parse` call above) contains the following, extracted from the TWB's XML structure:

### 3a. Workbook name

Take from the filename (strip `.twb`). Save as `{workbook_name}`.

### 3b. For each `<datasource>` element (skip those named `Parameters`)

Each datasource is processed independently for extraction (Steps 3b–3d). **Datasources are
merged into a single model only when they are connected by blend relationships** (detected in
Step 3e). Even when datasources share tables or point at the same database, they are NOT
merged unless a `<datasource-relationship>` explicitly links them. See Step 5b
"Blend-aware model grouping" for the merge procedure.

**Datasource type detection:**
- If the datasource contains `<connection class="sqlproxy">`, it is a **Published
  Datasource** (hosted on Tableau Server). The table name resolves to
  `connection.get('dbname')`, not the literal `[sqlproxy]`.
- If the datasource contains `<extract>`, **do not blindly skip it.** An extract is a
  local snapshot, but it almost always wraps an *underlying* connection that names a real
  table — a file source (`textscan`/CSV, `excel-direct`), a database, etc. What matters
  for migration is that underlying source, because that's what gets queried in the
  warehouse. Look past the `<extract>`/`hyper` connection to the real one:
  - The relation has two parents in `<metadata-records>` — the live source (e.g.
    `[Amazon Sales data.csv]`) and `[Extract]`. **Use the live-source relation; ignore the
    `[Extract]` relation.** The physical table name comes from the live source (mapped to
    its warehouse table per Step 4.5).
  - Only treat a datasource as truly skippable when there is **no** resolvable underlying
    connection (a pure Tableau-authored extract with no source) — and say so in the report.
  - File-based sources (CSV/Excel) imply the data was loaded into the warehouse out of
    band; bind the table to the connection that now exposes it (Step 4/4.5).
- Otherwise, it is a **Live** datasource — proceed with extraction.

**Non-warehouse sources — explicit unsupported policy:** The following Tableau connection
classes are NOT warehouse-bound and cannot be mapped to a ThoughtSpot connection:
`cloudfile:googledrive-excel-direct`, `google-sheets`, `ogrdirect` (spatial/OGR),
`webdata-direct` (web data connector), `CustomMapbox`. When any of these appear as a
datasource's connection class, do NOT assume a warehouse table exists. Instead:
1. Log: `"Datasource '<name>' uses a non-warehouse source (<class>) — cannot map to a ThoughtSpot connection. Skipped; data must be loaded into a warehouse first."`
2. Skip the datasource entirely (do not generate table or model TML for it).
3. Surface in the audit report under a "Skipped sources" section.

**Redshift and Postgres dialect notes:** When `<connection class="redshift">` or
`<connection class="postgres">` is detected, pass-through SQL (`sql_*_op`) formulas
should use the corresponding dialect syntax. Key differences from Snowflake:
- String concatenation: `||` (same as Snowflake)
- Date truncation: `date_trunc('month', col)` (same syntax, both dialects)
- `LISTAGG` → Redshift: `LISTAGG(col, ',') WITHIN GROUP (ORDER BY col)`; Postgres: `string_agg(col, ',' ORDER BY col)`
- Type casting: Redshift uses `::type`; Postgres uses `CAST(x AS type)` or `::type`

No other mapping changes are needed — the Tableau-to-ThoughtSpot formula translation is
warehouse-agnostic (ThoughtSpot formulas are the target, not SQL). The dialect only matters
for `sql_*_op` pass-through functions.

**Relation wrapper handling:** TWB XML wraps `<relation>` elements in one of three
structures. Check in order:
1. `_.fcp.ObjectModelEncapsulateLegacy.false...relation` tag
2. `_.fcp.ObjectModelEncapsulateLegacy.true...relation` tag
3. `<relation>` directly under `<connection class='federated'>` (fallback)

All three contain the same child elements — the wrapper determines where to look.

For each datasource, extract:

**Physical tables** — `<relation>` elements of `type="table"`:
- `name` attribute = table alias used in joins
- `table` attribute = fully-qualified physical table name — may be `[DB].[SCHEMA].[TABLE]`
  format; strip brackets and split on `.` to extract db, schema, and table components
- For Published Datasources (sqlproxy): if table name is `[sqlproxy]`, use
  `connection.get('dbname')` instead

**Custom SQL relations** — `<relation>` elements of `type="text"`:
- These contain raw SQL in the element text content — do NOT try to extract a table name
- Flag the relation as `source_type: "custom-sql"` and save the full SQL text
- Refactor the SQL: replace `<<` with `<`, `>>` with `>`, `==` with `=` (XML encoding
  artifacts from the TWB)
- These will generate a `sql_view:` TML instead of a `table:` TML (see Step 5c)
- Extract column names from the SQL `SELECT` clause aliases for column mapping

**Joins** — `<relation>` elements of `type="join"`:
- `join` attribute = join type (`inner` | `left` | `right` | `full`)
- `<clause>` child = join condition (decode HTML entities: `&quot;`→`"`,
  `&amp;`→`&`, `&lt;`→`<`, `&gt;`→`>`)
- Extract left and right table references from the clause

**Physical columns** — from `<metadata-records>` → `<metadata-record class="column">`:
- `local-name` = column identifier
- `remote-name` = physical column name in the database (use for `db_column_name`)
- `local-type` = Tableau data type
- `parent-name` = which table this column belongs to
- Also extract from `<column>` elements WITHOUT a `<calculation>` child:
  `name` (strip brackets), `datatype`, `role` (dimension/measure), `caption` (display name)

**Calculated fields** — `<column>` elements WITH a `<calculation class="tableau">` child:
- Skip columns where `param-domain-type` is `list` or `range` — these are Tableau
  parameters, not calculated fields
- `caption` or `name` = display name
- `calculation formula` attribute = Tableau expression (decode HTML entities)
- `datatype` attribute
- Build a cross-reference map: Tableau internal names (`[Calculation_1234567890]`) →
  display names. Calculated fields reference each other by internal ID in the TWB XML,
  not by display name — resolve these references before translating formulas.

**Parameters** — `<datasource name="Parameters">` children:
- For each `<column>` with `param-domain-type` attribute:
  - `caption` = display name (used as ThoughtSpot parameter name)
  - `datatype` = `string` | `integer` | `real` | `date` | `boolean`
  - `param-domain-type` = `list` | `range` | `any`
  - `value` attribute or `calculation.formula` = default value
  - `<member value="...">` children = list values (when `param-domain-type="list"`)
  - `<range min="..." max="...">` child = range bounds (when `param-domain-type="range"`)
- Save parameter definitions — these generate `model.parameters[]` in Step 5b
- **SQL-lookup parameters** (where the list values come from a database query rather
  than static `<member>` elements): save the query/column reference — at migration
  time (Step 5b), query the warehouse to populate `list_config.list_choice[]` with
  current values. In audit mode (no connection), flag as "requires connection"

Save the parsed structure internally. Announce a summary:
> Parsed `{workbook_name}`: {N} datasource(s), {N} physical table(s),
> {N} calculated field(s), {N} join(s), {N} dashboard(s)

### 3c. Topological sort of calculated fields

Some calculated fields reference other calculated fields. Sort them so that fields
with no formula-dependencies come first (Level 0), then Level 1, etc. This determines
the order they must appear in the model TML `formulas` section.

Resolve all internal Tableau cross-references (`[Calculation_\d+]` → display name)
before sorting. The topological sort must use display names, not internal IDs.

### 3d. Dashboard metadata (for Step 8 decision)

Count `<dashboard>` elements in the TWB. Save the count and names — this is shown
in Step 8 when asking whether to migrate dashboards.

### 3e. Extract blend relationships (data blending)

Parse the `<datasource-relationships>` element at the workbook root (child of `<workbook>`).
If absent, no blending is used — skip this step.

**Build the blend graph:**

The parse-JSON `blends` field (Step 3) is this graph — `{source_ds_caption:
[{target_ds, column_mappings}]}`, with federated IDs already resolved to
datasource captions (matching each datasource's `name` from Step 3b). Treat
`blend_graph` in the rest of this document as shorthand for that field.

**What to log:**
- Number of blend relationships found
- For each: primary datasource → secondary datasource, with linking columns listed

**Date-grain linking columns:**

When a `<column-instance>` has a `derivation` other than `"None"` (e.g. `"Month"`,
`"Month-Trunc"`, `"Year"`, `"Year-Trunc"`), the blend links at a specific time grain.
For the ThoughtSpot model join, the physical date column is used directly — ThoughtSpot's
date bucketing at query time handles the grain alignment.

However, if the source and target columns are physically different date columns with
different native grains (e.g. source has daily `Order Date`, target has monthly
`Month of Order Date` that is already pre-truncated), the join requires a
**date-truncation formula** or **SQL View** to materialize the matching grain.

**Resolution strategy:**
1. If both columns are date/datetime type and the derivation indicates a truncation
   (`Month-Trunc`, `Year-Trunc`), emit a model formula:
   `date_trunc ( 'month' , [TABLE::Order Date] )` and use that formula as the join key
   via a SQL View (the formula can't be a direct join key in model TML).
2. **Surface the grain mismatch** to the user in the review checkpoint with a recommendation:
   - "Blend links `Order Date` (daily) to `Month of Order Date` (monthly) at month grain.
     Recommend: create a SQL View with `DATE_TRUNC('MONTH', ORDER_DATE) AS ORDER_MONTH` and
     join on `ORDER_MONTH = MONTH_OF_ORDER_DATE`."
3. If both columns are the same physical type and grain, use them directly in the join `on`
   clause — no materialization needed.

**No model merging happens here** — this step only extracts the relationships. Model
merging happens in Step 5b.

---

## Step 3f — Table-calc addressing extraction

For every datasource, scan `<column>` elements that have a `<calculation class='tableau'>`
child containing a `<table-calc>` element. This is the **column-level addressing map** —
read it from the parse-JSON `table_calc_addressing.column_level` field (Step 3): keyed by
calc internal ID (e.g. `[Calculation_953355781789577216]`), each entry has
`ordering_type` (`Rows` | `Columns` | `Table` | `CellInPane` | `Field`), `ordering_field`,
`order_fields` (list), `quick_calc_type` (`PctTotal` | `PctDiff` | `Difference` |
`PctRank` | `None`), and `address_offset` (int or `None`).

Each `<worksheet>`'s `<column-instance>` elements can carry their own `<table-calc>` —
these are **view-level overrides** that take precedence over the column-level definition
for that worksheet. Read them from `table_calc_addressing.ws_overrides` (same entry shape,
keyed by worksheet name then calc ID).

**Resolution order** when translating a table-calc formula used on worksheet W:
1. Check `table_calc_addressing.ws_overrides[W][calc_id]` — view-level override
2. Fall back to `table_calc_addressing.column_level[calc_id]` — column-level definition
3. If neither exists, treat as `ordering_type='Rows'` (Tableau default)

---

## Step 3g — Orphan calc detection (copied datasources)

When a Tableau datasource is a **copy** of another (common with published datasource
clones), it inherits **all calculated fields** from the original — including ones that
reference tables no longer present in the copy. These orphan calcs are non-functional in
Tableau and will fail at ThoughtSpot import.

Each datasource's `orphan_calcs` (parse-JSON field, Step 3) is this list — captions of
calcs that directly reference a table missing from the datasource, plus calcs that
transitively depend on a direct orphan.

**What to log** (if any orphans found):
> ⚠ Datasource `{name}`: {N} orphan calc(s) reference missing tables: {table1, table2, …}
> These are non-functional inherited fields and will be excluded from migration.

**In migrate mode:** surface the orphan count and the missing tables before proceeding.
Ask the user to confirm exclusion — in rare cases they may want to add the missing tables
to the connection and model instead:
> {N} calculated fields reference tables not in this datasource ({table1, table2, …}).
> These appear to be inherited from a parent datasource and are non-functional.
> **E** — Exclude them (default, recommended)
> **A** — Add the missing tables to the model (you'll need to confirm they exist in Step 4)

If the user chooses **A**, add the missing tables to the datasource's table list and
re-run Step 4 table confirmation for the new tables only. Remove the affected calcs
from `orphan_calcs` so they enter the translation pipeline.

**In audit mode:** no prompt — just report the orphan count in the A4 audit report.

---

## Step 3.5 — Resolve Published Datasources (sqlproxy)

> Runs only if Step 3 detected one or more datasources with `<connection class="sqlproxy">`.
> Skipped entirely if all datasources have direct warehouse connections.

When a Tableau workbook references a **published datasource** on Tableau Server/Cloud,
the TWB XML contains `<connection class="sqlproxy">` with a `dbname` attribute naming the
published datasource.

**What the TWB DOES contain for sqlproxy datasources** (extract these in Step 3b regardless
of API access — they are `<column>` elements directly under the `<datasource>` element):
- All **calculated fields** with full Tableau formula text (same as direct-connection
  datasources)
- **Column definitions** with captions, datatypes, and roles
- **Metadata records** (local-name, remote-name, local-type, parent) — often complete enough
  for column mapping

**What the TWB does NOT contain** (only available via the Tableau API):
- The **physical table structure** (table names, joins, db/schema/table paths)
- The **connection details** (database, schema) that link to the warehouse

This means **formula extraction and translation work without API access** — the Tableau API
adds physical table resolution and join definitions, not the formulas.

### Flow

> **ASK before querying the Tableau API.** The user may be a consultant conducting a remote
> migration without access to the customer's Tableau Server. Do NOT attempt any API call
> before asking — a failed API call wastes 30–60 seconds and confuses the flow.

1. Prompt — **always, before any API call**:

   ```
   Found {N} published datasource(s) hosted on Tableau Server:
     - {ds_caption_1} ({M} columns, {C} calculated fields extracted from TWB)
     - {ds_caption_2} ({M} columns, {C} calculated fields extracted from TWB)

   The TWB already contains all column definitions and calculated fields.
   The Tableau API would additionally resolve the physical table structure
   (table names, joins, db/schema paths) — but this is optional.

   Do you have access to the Tableau Server hosting these datasources?
     Y  Yes — query the Tableau API for table structure   (requires /ts-profile-tableau)
     N  No  — proceed with TWB metadata only              (common for consultant/remote migrations)

   Enter Y / N:
   ```

2. If the user chooses **N** (no API access):
   - Log: `"Proceeding with TWB-embedded metadata — {M} columns, {C} calculated fields
     already extracted. Physical table names and joins will be confirmed manually in
     Steps 3.6 and 4."`
   - The TWB's `<column>` elements (captions, datatypes, roles) and `<metadata-records>`
     (local-name → remote-name mapping) provide enough for formula translation and column
     mapping. The physical table names come from `<metadata-record>` `parent-name` attributes
     (e.g. `[Custom SQL Query3]`, `[Table_Name]`).
   - **Skip to Step 3.6** (join confirmation) — the user will provide or confirm joins and
     table mappings manually. This is the normal path for consultant/remote migrations.
   - Continue to Step 4 with the TWB column info.

3. For each sqlproxy datasource, extract `dbname` from the `<connection>` element, then:

   **Progress label:** `"Querying Tableau API (not ThoughtSpot) to resolve published datasource columns…"`
   — make it clear this is a Tableau Server query, not a ThoughtSpot metadata search.

   ```bash
   # Find the published datasource by name
   ts tableau datasources --profile {PROFILE} --name "{dbname}"
   ```

   Parse the JSON output to get the datasource `id`.

   ```bash
   # Get field metadata
   ts tableau datasource {id} --profile {PROFILE} --fields
   ```

   The `fields` array contains:

   | Field | Use |
   |---|---|
   | `fieldCaption` | Column display name → ThoughtSpot column name |
   | `dataType` | `real`/`integer`/`string`/`date`/`datetime`/`boolean` → TS data type |
   | `columnClass` | `COLUMN` (physical), `CALCULATION` (formula), `BIN`, `GROUP` |
   | `formula` | For calculated fields — the Tableau formula text for Step 5 translation |

4. Merge the resolved fields into the parsed datasource structure, replacing opaque
   sqlproxy column references with real names and types. Proceed to Step 4.

5. For **textscan** (CSV) or **excel-direct** sources: offer to download the source data
   for warehouse provisioning. This is essential when the data only exists in Tableau Cloud
   and has not been loaded into a warehouse:

   ```bash
   # Download the published datasource content
   ts tableau download {datasource_id} --profile {PROFILE} --output-dir {output_dir}
   ```

   The command downloads the TDSX archive, extracts it, and **validates CSV files** for row
   integrity (column count consistency, corrupt lines). Check the `validation` result:

   - If `is_valid: false` — report the corrupt lines and offer to auto-fix (strip them)
     before proceeding to warehouse load. The DunderMifflin live test (2026-06-26) found a
     corrupt line (`1tou`) in a Tableau Cloud textscan download — this is a known Tableau
     artifact.
   - If `is_valid: true` — proceed; the CSV is clean for loading.

   Surface: "The data for datasource '{name}' is a {type} file hosted on Tableau Cloud. It
   needs to be loaded into a warehouse table before ThoughtSpot can connect to it. I've
   downloaded and validated it — {row_count} rows, {status}. Shall I help set up the warehouse
   table? (This will require a Snowflake/Databricks connection.)"

   If the user says yes, this is the handoff point for **BL-010 (`ts-load-source-data`)** when
   that skill is built. Until then, guide the user through manual warehouse provisioning
   (CREATE TABLE + stage + COPY INTO for Snowflake, or INSERT VALUES for Databricks).

### Prerequisites

- Tableau profile configured via `/ts-profile-tableau` (optional — skill degrades gracefully)
- `ts` CLI v0.29.0+ (includes `ts tableau build-model` with `--max-retries`, enriched error
  reporting, GENERATE mode phased output, and `--table-name-map`)

---

## Step 3.6 — Join Confirmation

Joins define the model's query behavior — **never silently add joins that aren't in the TWB**.

### When the TWB parse found joins (from `<relation type="join">` or `<object-graph><relationships>`)

Present them to the user for confirmation:

```
Joins found in workbook ({N} total):
  1. TABLE_A LEFT JOIN TABLE_B ON TABLE_A.COL = TABLE_B.COL
  2. TABLE_A LEFT JOIN TABLE_C ON TABLE_A.COL = TABLE_C.COL

Do these look correct? (Y/N/Edit)
```

If the user edits, accept updated join definitions and continue.

### When the TWB parse found NO joins (common with published datasources/sqlproxy)

```
⚠ No join definitions found in the workbook file.
This is normal for published datasources — joins are defined server-side.

Tables in this datasource: TABLE_A, TABLE_B, TABLE_C, ...

To build the model, I need join definitions. Options:
  D  Define joins — I'll suggest based on matching column names, you confirm
  S  Skip joins — create separate single-table models (no multi-table queries)
  P  Provide — paste or describe join definitions
```

If the user picks **D**, suggest joins based on shared column names between tables:

```
Suggested joins (based on shared column names):
  TABLE_A.PROMOTION_ID = TABLE_B.PROMOTION_ID (LEFT_OUTER, MANY_TO_ONE)
  TABLE_A.PROMOTION_ID = TABLE_C.PROMOTION_ID (LEFT_OUTER, MANY_TO_ONE)

Accept suggested joins? (Y/N/Edit)
```

### Range join alternative

When the parse detects date-range filter formulas (e.g., `[DATE] >= [START_DATE] AND
[DATE] <= [END_DATE]`) AND separate fact/dimension tables with start/end date columns,
surface an additional option:

```
💡 Detected date-range filter pattern. ThoughtSpot supports range joins:
  FACT.DATE >= DIM.START_DATE and FACT.DATE < DIM.END_DATE

This is more efficient than a filter formula. Use a range join instead? (Y/N)
```

See `tableau-tml-rules.md` "Range join alternative" for the TML syntax.

---

## Step 4 — Confirm Source Tables (ask before searching)

This is the **first** thing after the parse — **before** selecting a connection, searching
ThoughtSpot, or fetching any schema. Getting the order wrong wastes the user's time:
scanning the whole instance, or pulling a connection's schema, when the user already knows
whether the tables exist is pure overhead (and the connection-schema fetch is slow and can
404). **Ask first; act second.** This step only **asks and confirms** — it never loads or
modifies warehouse data. It mirrors `ts-convert-from-databricks-mv` Step 7.

> **Do NOT run `ts metadata search`, `ts connections list`, or `ts connections get` until
> the user has answered the question in 4a.** No exploratory "let me just check" searches —
> the answer decides whether *any* search runs, and at what scope. An ungated
> `ts metadata search --all` on a large instance is exactly the wasted work this step exists
> to prevent.

### 4a — Present the table inventory and ask

> **Scope 4 (Models only):** tables already exist by definition. Skip choices N and ? —
> present only **E** and **G** and default to G if the user has the GUIDs. The user chose
> scope 4 specifically because the tables are in ThoughtSpot already.

Show the full inventory of physical tables from Step 3, then ask whether they already exist
as ThoughtSpot Table objects:

```
Source tables referenced by {workbook_name} ({N} total):
  1. P1-UK-Bank-Customers
  …

Do these already exist as ThoughtSpot Table objects?
  E  Exist       — reuse them (I'll search for their GUIDs)
  G  Have GUIDs  — provide GUIDs directly (fastest, no search needed)
  N  Don't exist — create new on a connection            (default)
  ?  Not sure    — search ThoughtSpot to check (avoids creating duplicates)

Enter E / G / N / ? :
```

If the tables differ in status (some exist, some don't), accept a per-table answer.

### 4b — Act on the answer

- **N (don't exist)** → **no search.** Go to **Step 4.5** to pick the connection, then
  create Table TMLs in Step 5a (the default path).

  > **Deduplication note:** if you are migrating **multiple workbooks** that share the same
  > published datasource, the tables from the first migration already exist. Choosing **N**
  > again creates duplicates. If this is a second (or later) workbook migration, consider
  > **E**, **G**, or **?** instead to reuse the tables already in ThoughtSpot.

- **G (have GUIDs)** → **no search.** For each table, ask the user to provide the GUID
  (the `id` value from ThoughtSpot, e.g. from a previous migration or from the UI). Use
  the provided GUIDs in the model's `model_tables[]` entries and **skip generating Table
  TMLs** for those tables. If the user has GUIDs for some tables but not all, treat the
  remaining tables as **N** (create via Step 4.5 + 5a).

- **E (exist)** → search to find the GUIDs — but **choose the scope first** (4c).
  Searching ensures the tables are not duplicated and resolves their GUIDs automatically.

- **? (not sure)** → search — **choose the scope first** (4c). Report what was / wasn't
  found; reuse the found ones, treat not-found tables as create (Step 4.5 + 5a).
  This is the safest option when migrating into an instance that may already have
  some of these tables.

### 4c — Choose the search scope (E and ? paths only)

A whole-instance scan is the slow path. Always offer the narrower option, and search by
**table-name pattern** (`--name`) so the API does the filtering — never pull every table
and filter locally:

```
How should I search for these tables?
  C  Within a specific connection — fastest; I'll list connections and search that one
  I  Entire ThoughtSpot instance  — broader, slower

Enter C / I :
```

```bash
# Targeted by name — both scopes start here (NOT `--all`)
source ~/.zshenv && ts metadata search --subtype ONE_TO_ONE_LOGICAL --name "%{table_name}%" --profile {profile_name}
```

- **C (within a connection)** → **first identify the connection using the
  N (name it) / F (filter by substring) / L (list all) prompt in Step 4.5 — present that
  prompt and let the user choose; do NOT run `ts connections list` and dump every connection
  by default.** Once the connection is chosen, run the name search above and **keep only
  results whose `metadata_header.dataSourceName` equals the chosen connection name**
  (verified 2026-06-16: each search result carries its connection in
  `metadata_header.dataSourceName`, e.g. `"APJ_TAB"`). Fastest, and unambiguous when the
  same table name exists on several connections.
- **I (entire instance)** → run the name search above with no connection filter.

Match on table name (`metadata_name`) and, for the connection scope,
`metadata_header.dataSourceName`. (db/schema also appear in `metadata_header` —
`database_stripes` / `schema_stripes` — use them to disambiguate same-named tables within
one connection.) For each table found, reuse its
name/GUID in the model's `model_tables[]` and **skip generating a Table TML** for it in
Step 5a. If a table the user said **Exists** is not found, say so and confirm before falling
back to create.

> Only fall back to `--all` (fetch every table) when no usable name pattern can be formed
> (e.g. the name is too generic). Tell the user that cost before running it.

### 4d — Confirm any missing sources before proceeding

If any table the plan intends to **create** is *not found* on the chosen connection,
surface it and require confirmation — this is the silent-failure case (a model TML that
points at a table the connection can't see still *imports* cleanly, yet every search and
liveboard built on it comes back empty):

```
⚠ The following table(s) are not visible to connection "{connection_name}":
    - {db}.{schema}.{db_table}
  Their models will import, but searches return no data until the data is loaded
  and visible to the connection. This skill does not load data.

  Proceed anyway (generate the TMLs as-is)?   (yes / no):
```

Do not proceed past this warning without the user's confirmation.

---

## Step 4.5 — Select ThoughtSpot Connection (create path or connection-scoped search)

Run this **only when a table will be created** (the **N** path, or tables not found on the
**E** / **?** paths) or to scope a connection search in 4c. **If every table was matched to
an existing object, skip this step** — reusing tables needs no connection work.

**First: use an existing connection or create a new one.** Ask:

```
The generated tables need a ThoughtSpot connection that can reach the source database.
  E  Use an existing connection
  C  Create a new connection   (Snowflake source only, key-pair auth)

Enter E / C:
```

> **When to create:** a ThoughtSpot connection only sees databases its warehouse
> **role** is granted. If no existing connection's role can see the source database,
> table creation fails with *"Database … does not exist in connection"* — that is the
> signal to create one (do **not** trial-and-error existing connections to find out).

**C — create a new connection.** Supported here for **Snowflake** sources via key-pair
auth. Collect the connection name, Snowflake account identifier, user, role, warehouse,
and the path to the **unencrypted PKCS#8 private key** (`.p8`), then run:

```bash
source ~/.zshenv && ts connections create \
  --name "{connection_name}" \
  --account "{account}" --user "{user}" --role "{role}" --warehouse "{warehouse}" \
  --database "{database}" \
  --private-key-path "{key_path}" \
  --profile {profile_name}
```

The role must have `USAGE` on the database/schema (and `SELECT` on the tables). The
matching **public** key must already be registered on the Snowflake user. **Credential
handling (required):** never ask the user to paste a private key, password, or secret
into the conversation — the key is passed **by file path only** and `ts connections
create` never echoes it. If the source is **not** Snowflake, or password/OAuth is
required, connection creation is out of this skill's scope: direct the user to create
the connection in the ThoughtSpot UI, then return on the **E** path. Use the returned
`name` as `{connection_name}`.

**E — use an existing connection. Don't dump the full list by default** — a long
connection list is noise when the user already knows the one they want. Ask:

```
How would you like to identify the connection?
  N  Name it     — type the exact connection name; I'll use it directly
  F  Filter      — give a partial string; I'll list only connections that match
  L  List all    — show every connection and pick by number
  T  Trust       — type the name and skip validation (faster — import will fail
                   cleanly if the name is wrong)

Enter N / F / L / T:
```

**T — trust the name.** Use the typed name directly without running `ts connections list`.
This skips validation but is faster on instances with many connections. The import will
return a clear error (`"Connection 'X' not found"`) if the name is wrong.

**Compound prompt (N or T path).** When the user takes the N or T path, offer the
db/schema confirmation in the same prompt to eliminate sequential questions:

```
Connection: ____________  (exact ThoughtSpot connection name)
Database:   ____________  (or press Enter to use '{twb_extracted_db}')
Schema:     ____________  (or press Enter to use '{twb_extracted_schema}')
```

This replaces the separate db/schema confirmation loop below when the user provides
all three in one response.

For N/F/L, fetch the connections once (auto-paginated, returns all):

```bash
source ~/.zshenv && ts connections list --profile {profile_name}
```

Resolve the user's choice against that result:

- **N (name it)** — match the typed name against the returned `name` values
  (case-sensitive). Exactly one match → use it. No match → show the closest names and
  re-ask. Don't fabricate a name the list doesn't contain — the table TML needs the exact,
  case-sensitive connection name.
- **F (filter)** — keep connections whose `name` contains the string (case-insensitive),
  show them as a short numbered list (name, type, database), and pick from that. One match
  → auto-select and confirm; none → widen the string or switch to **L**.
- **L (list all)** — show the full numbered list and pick by number:

  ```
  Available ThoughtSpot connections:
    1. SNOWFLAKE_PROD    (RDBMS_SNOWFLAKE)   — PROD_DB
    2. ANALYTICS_DW      (RDBMS_SNOWFLAKE)   — ANALYTICS_DB

  Which connection should the generated tables use? (Enter number):
  ```

If only one connection exists in total, auto-select it and confirm regardless of the choice.
Save the selected connection's exact `name` value as `{connection_name}`.

**Resolving db / schema / table for new tables.** Each new table needs the `{db}`,
`{schema}`, and `{db_table}` it maps to on the chosen connection. The Tableau workbook
contains the *source environment's* database paths — these may not match the target
ThoughtSpot connection (e.g. a consultant running the migration in their own environment
with a different database). Always confirm before using them.

Show the TWB-extracted paths and ask:

```
The Tableau workbook references these source database paths:
  - {source_db}.{source_schema}.{table_1}
  - {source_db}.{source_schema}.{table_2}
  …

Do these match your ThoughtSpot connection's database and schema?
  Y  Yes — use these paths as-is
  D  Different database/schema — I'll provide the correct values
  T  Per-table — some match, some don't (I'll confirm each)

Enter Y / D / T:
```

- **Y** → use the TWB-extracted `{db}`, `{schema}`, and `{db_table}` values directly.
- **D** → ask for the target `{db}` and `{schema}` once. Apply them to all tables (table
  names stay the same unless the user overrides). This is the common consultant scenario
  where all tables live in the same database but under a different name.
- **T** → walk through each table and confirm or override its `{db}`, `{schema}`, and
  `{db_table}`. Use this when tables span multiple databases or schemas in the target.

If the user doesn't know the correct paths:

1. **Ask the user** for the db / schema (and table name if it differs from the source) —
   usually instant, and they know it.
2. **Only if they're unsure**, fetch the connection schema to resolve names:
   ```bash
   source ~/.zshenv && ts connections get {connection_id} --profile {profile_name}
   ```
   This uses the v1 `fetchConnection` endpoint — it can be slow and returns 404 on some
   connection types, so treat it as the **fallback, not the default**. If it returns no
   tables (empty `externalDatabases`) or fails, ask the user for the names directly.

A connection is **required** for any table being created — there is no skip path.
ThoughtSpot tables are logical objects over a **live** connection: the physical table must
already exist in the database and the connection must already exist for the table to be
created at all. Do not offer placeholders or a dry-run mode — they only produce objects
that can never bind to data. If the user has no suitable connection: for a **Snowflake**
source, create one via the **C** path above (key-pair auth); for any other source, or when
password/OAuth is required, stop and tell them the connection must be created first in the
ThoughtSpot UI (that connection setup is out of this skill's scope).

Use the connection's exact **name** in every table TML and SQL View TML — never a GUID. The
v2 API cannot search connections by name, so the name string is both necessary and
sufficient; do not try to resolve it to an ID. See
`../../shared/schemas/thoughtspot-table-tml.md` "Connection Reference".

---

## Step 5 — Generate TML Files

Create output directory:

```bash
mkdir -p /tmp/ts_tableau_mig/output/{workbook_name}
```

### 5a. Table TML — one per physical table (skip custom SQL relations)

> **Scope gate:** runs for scopes 1, 2, 5. **Skip for scope 3** (LB only — no tables)
> and **scope 4** (Models only — tables already exist; use GUIDs from Step 4).

For each physical table identified in Step 3 with `type="table"`, generate a
`.table.tml` file. **Skip custom SQL relations** — those are handled in Step 5c.

Follow all rules in `tableau-tml-rules.md`.

**Template:**

```yaml
table:
  name: TABLE_NAME
  db: RESOLVED_DATABASE
  schema: RESOLVED_SCHEMA
  db_table: physical_table_name
  connection:
    name: "{connection_name}"       # exact ThoughtSpot connection name, case-sensitive — NOT a GUID
  columns:
  - name: COLUMN_NAME
    db_column_name: COLUMN_NAME
    data_type: VARCHAR              # VARCHAR | INT64 | DOUBLE | FLOAT | BOOL | DATE | DATETIME
    properties:
      column_type: ATTRIBUTE        # or MEASURE
      aggregation: SUM              # only if MEASURE — SUM | AVERAGE | COUNT
    db_column_properties:
      data_type: VARCHAR            # must match data_type above
```

Key rules:
- `connection.name` is **required** — a ThoughtSpot logical table must sit on a connection
  that already exposes the physical table and its columns. Use the connection **name**
  directly (case-sensitive); never look up a GUID — the v2 API cannot search connections
  by name, and the name is what the TML needs. See `../../shared/schemas/thoughtspot-table-tml.md`
  "Connection Reference".
- Use the `db`, `schema` values resolved from Step 4.5 (the connection is required, so these
  are always real).
- **`db_column_name` must match the physical column the connection exposes — not the
  Tableau name.** When a file source (CSV/Excel) was loaded into the warehouse, the loader
  usually normalizes names (`Item Type` → `ITEM_TYPE`: spaces→`_`, upper-cased). Use the
  warehouse column name for `db_column_name` (and the friendly Tableau caption for the
  model column's display `name`). If unsure, the connection schema from Step 4.5
  (`externalDatabases`) lists the real column names; validation reports
  `column not found in connection` when they don't match.
- **Date stored as VARCHAR — flag it.** If the Tableau column is typed `date`/`datetime`
  but the warehouse column is **VARCHAR** (common when a CSV date loaded as text), binding
  it as VARCHAR loses all date capability (no buckets/trends/relative-date filters; Spotter
  won't read it as time). The TS column `data_type` must match the physical column, so you
  can't just declare `DATE`. Surface it and offer: **(a)** retype at the source (warehouse
  `ALTER`/reload to a real `DATE` — outside this skill; needs the user) then bind as `DATE`,
  or **(b)** keep VARCHAR and add a `to_date([col])` **derived formula column** for
  date analytics. Don't silently bind a date as a string.
- **Partial date strings must produce a full `YYYY-MM-DD` date.** When a source column
  contains a year-only value (e.g. `_2016_17`, `FY2016`, `2016`) and needs to become a
  DATE, always append `-01-01` (or `-01` for year-month) to produce a complete date.
  A bare-year conversion like `to_date('2016', 'yyyy')` produces an ambiguous value that
  ThoughtSpot cannot bucket (`.yearly`, `.monthly`), use for KPI sparklines, or filter as
  a date range. If the datasource already uses a **SQL View**, apply the conversion in the
  SQL query (`TO_DATE(SUBSTRING(col, 2, 4) || '-01-01', 'YYYY-MM-DD')`). If it uses a
  **regular table**, apply it as a model formula
  (`to_date ( concat ( substr ( [col] , 1 , 4 ) , '-01-01' ) , 'yyyy-MM-dd' )`). See `tableau-tml-rules.md`
  "Date Column Rules" for the full pattern table.
- Use `INT64` for Tableau `integer` — **never `INT`**
- `db_column_properties` is **required** on every column
- No `guid` or `fqn` sections
- If validation (Step 6) returns `connection not found`, the name/case is wrong; if it
  returns `column not found in connection`, the physical table/column the connection sees
  doesn't match `db_table`/`db_column_name` — both are surfaced there, so a wrong binding
  fails loudly rather than silently.

Write each file to `/tmp/ts_tableau_mig/output/{workbook_name}/{TABLE_NAME}.table.tml`.

### 5b. Model TML — one per datasource (strict separation)

> **Scope gate:** runs for scopes 1, 2, 4. **Skip for scope 3** (LB only — model already
> exists) and **scope 5** (Tables only — no model generated).

> **Prerequisite:** the generate-mode path below requires `ts` CLI v0.29.0+
> (`ts tableau build-model --table-name-map`). See Prerequisites above.

Before generating model TML, read `agents/shared/schemas/thoughtspot-model-tml.md` for the
correct structure. Key: use `model_tables` (not `tables`) for table references; `guid:` goes
at the document root (not nested inside `model:`); every formula needs a paired `columns[]`
entry with matching `formula_id`.

Generate one model per datasource the workbook **actually uses** — don't blindly merge
independent datasources, but also don't materialize an unused model for every datasource.
How that model TML is produced depends on whether the datasource participates in a blend:

**Single-datasource models (the common case — no blend) — GENERATE mode.** When a
datasource has no entry in `blend_graph` (from Step 3e), build its base model TML with
`ts tableau build-model` in GENERATE mode (no `--existing-guid`) instead of hand-assembling
it:

```bash
ts tableau build-model {workdir}/{workbook}.twb \
  --connection "{connection_name}" \
  --datasource "{datasource_name}" \
  --output-dir {output_dir} \
  [--table-name-map {workdir}/table_name_map.json]
```

This runs the same TWB-parse → translate → assemble pipeline described below and writes
**phased** model TML files: `{slug}.phase0.model.tml` (base — `model_tables`, physical
`columns`, `joins`, `parameters`; **no formulas**), then `{slug}.phase1.model.tml`,
`{slug}.phase2.model.tml`, … (one phase per formula dependency level). **This step (5b)
only needs `*.phase0.model.tml`** — that file is the Phase-1 base model built in Step 7.
The `.phase1+` files are not consumed anywhere in this skill's import flow: formulas are
added independently in Step 7 Phase 2, via a separate `build-model --existing-guid` call
that re-derives them from the TWB against the live, already-imported model.

`--table-name-map` (optional): a JSON file `{"twb_table_name": "thoughtspot_table_name"}`.
Supply it **only** when the ThoughtSpot table's TML `name` (from Step 5a) differs from the
TWB relation name — warehouse-normalized names, or a published-datasource TWB where the
relation is literally named `sqlproxy`. Omit the flag when the names already match; the
default (no map) behavior is unchanged.

Still apply the **Model TML hard rules**, MEASURE/ATTRIBUTE classification guidance, and
Template below when **reviewing** the generated `*.phase0.model.tml` — they describe the
required shape regardless of how the file was produced.

**Blend-merged models (multiple datasources spanning one connected component) — hand
assembly.** GENERATE mode builds one model per single datasource — it cannot produce the
merged, multi-datasource model a blend relationship requires (inline cross-datasource
joins, column-conflict renaming across datasources). **Blend-aware model grouping**
(requires `blend_plan` from Step 3e):

`ts tableau parse` emits a `blend_plan`: `components` (each `{primary, members}`),
`ds_table_map` (datasource caption → ThoughtSpot table name), and `joins`
(`{with, table, on, type, cardinality}`). Use these directly — one model per
component, joins as given. The cardinality is a `MANY_TO_ONE` default; confirm it
in the Step 7 review. (TML file assembly from `blend_plan` is still done here per
the template below — see the deferred follow-up to codify emission.) When
`blend_plan["components"]` is non-empty, datasources connected by blend relationships
produce a **single merged model** instead of separate models, assembled by hand as
described below.

The merge procedure:

1. **One model per component.** For each entry in `blend_plan["components"]`, generate a
   single model TML named after that entry's `primary` datasource's display name,
   containing:
   - All `model_tables[]` entries from every member datasource (tables + SQL views),
     resolved via `blend_plan["ds_table_map"]`
   - All `columns[]` from every member datasource (with `column_id` prefixed by the
     correct table name: `TABLE_NAME::col_name`)
   - All `formulas[]` from every member datasource
   - The joins from `blend_plan["joins"]` whose `table` belongs to this component
     (see next step)

   For multi-table datasources (internal joins within one datasource), the blend link
   column determines which table is the join anchor. Resolve the link column from Step 3e
   to its owning table via the column-to-table mapping already built in Step 3b.

2. **Apply the blend joins as given.** `blend_plan["joins"]` already covers every blend
   edge across every component — star topologies (one primary, multiple secondaries) and
   transitive chains alike, not just edges from the primary. Append each join
   (`{with, table, on, type, cardinality}`) to the `model_tables[]` entry named by the
   join's `table`, in the shape the Template below shows.

   **Cardinality heuristic:** `blend_plan` always emits `MANY_TO_ONE`. If the secondary
   datasource has no dimension-only columns (all columns are measures or aggregated), it
   is likely a fact table → override to `MANY_TO_MANY`. Surface the choice in the review
   checkpoint (Step 7) so the user can confirm or override.

3. **Datasources not in any blend** are not part of this hand-assembly procedure at all —
   they use the GENERATE-mode path above.

4. **Column name conflicts:** when merging, if two datasources define columns with the same
   display name but different semantics, disambiguate by prefixing with the datasource
   display name (e.g. `Orders Revenue` vs `Targets Revenue`). Log every rename.

The `model_tables[]` section references both regular tables (from Step 5a) and SQL
Views (from Step 5c) — both are referenced by `name` in the same way.

**Model name:** use the Tableau datasource display name — no prefix (no `TEST_` or environment
markers). Ask the user if they want a different name before importing. See
`../../shared/schemas/ts-model-conversion-invariants.md` (N1).

**Model TML hard rules** — these apply to every model this step generates.
Violations cause silent data loss or import rejections with no clear error.
See `../../shared/schemas/ts-model-conversion-invariants.md` for full detail.

> **I1 — Every `formulas[]` entry must have a paired `columns[]` entry** with `formula_id:`
> matching the formula's `id`. An unpaired formula is silently dropped on import.
>
> **I2 — Never add `aggregation:` to a `formulas[]` entry.** It belongs only on `columns[]`
> entries. Adding it to `formulas[]` causes `FORMULA is not a valid aggregation type`.
>
> **I3 — Add `index_type: DONT_INDEX`** on every `columns[]` entry that has a `formula_id`
> and `column_type: MEASURE`.
>
> **I4 — `with:` must exactly match the target table's `name:`.** (In ThoughtSpot, `with:`
> resolves against `name`, not an `id`. If you add an `id:` field to a `model_tables` entry,
> it must equal `name:` exactly — same case, same characters — or joins break with
> `"{table} does not exist in schema"` at query time.)
>
> **I5 — `COUNTD(x)` → `unique count ( [T::x] )` formula entry, never `aggregation: COUNT_DISTINCT`.**
> Using `aggregation: COUNT_DISTINCT` silently flips `column_type` from MEASURE to ATTRIBUTE.
>
> **I6 — Connection referenced by name, never GUID.** In every table and sql_view TML block,
> use `connection: name: "{name}"` — the display name from Step 4.5. GUIDs are environment-specific
> and will fail on any ThoughtSpot instance other than the one they were exported from.
> See `../../shared/schemas/ts-model-conversion-invariants.md` (I1–I6).

> **MEASURE vs ATTRIBUTE classification — don't under-classify, or tiles show no value.**
> A column/formula tagged `ATTRIBUTE` when it should be `MEASURE` imports fine but renders
> as a dimension — KPIs and chart y-axes come up **empty**. Classify deliberately
> (live-verified 2026-06-17):
> - **Formula is a MEASURE if it (transitively) produces a number** — it contains an aggregate
>   (`sum`/`average`/`max`/`min`/`count`/`group_aggregate`) or a ratio (`/`), **or it references
>   another MEASURE formula** by `[formula_<id>]`. The reference case is the trap: a dynamic
>   selector like `if [Param] = 'All' then [formula_Overall_Pct] else [formula_True_Pct]` has no
>   aggregate of its *own* but is a measure because every branch is one. Resolve measure-ness
>   over the formula dependency graph, not just the formula's own text.
> - **A numeric physical column defaults to MEASURE** (`INT64`/`DOUBLE`) **unless it is clearly a
>   dimension** — a key/id (`*_ID`), a calendar number (`FISCAL_*_NUM`, `*_YEAR`, `*_QUARTER`),
>   a name (`*_NAME`), or a date. Tableau's `role` is an unreliable signal here: counts like
>   `QA_FALSE`, `TP_CONNECTIONS`, `BRAND_ID_COUNT` arrive with no `measure` role and would
>   otherwise be mis-tagged ATTRIBUTE. When unsure, prefer MEASURE for a plain numeric metric.
> - **Bare (unbracketed) column references** appear in Tableau formulas (e.g.
>   `SUM(CONSISTENCY_NUMERATOR)`, not `SUM([CONSISTENCY_NUMERATOR])`). Qualify **every** physical
>   column name to `[TABLE::COL]`, not only the bracketed ones, or the formula fails with
>   *"Search did not find …"*.

**Template** (hand-assembly shape — used directly for blend-merged models; also the
structural reference for reviewing GENERATE-mode output above):

```yaml
model:
  name: "Datasource Display Name"
  properties:
    spotter_config:
      is_spotter_enabled: true  # set by Step 5.5 — Spotter is on by default
  model_tables:
  - name: TABLE_NAME
    joins:                      # only if this table has joins to others
    - with: OTHER_TABLE         # must match OTHER_TABLE's name exactly (same case)
      on: "[TABLE_NAME::JOIN_COL] = [OTHER_TABLE::JOIN_COL]"
      type: LEFT_OUTER          # INNER | LEFT_OUTER | RIGHT_OUTER | OUTER
      cardinality: ONE_TO_MANY
  - name: OTHER_TABLE
  parameters:                   # omit if no Tableau parameters to migrate
  - name: Currency
    data_type: VARCHAR
    default_value: "USD"
    list_config:
      list_choice:
      - value: USD
      - value: CAD
      - value: GBP
  formulas:                     # omit section entirely if no translatable calculated fields
  - id: formula_Formula Name    # id: "formula_" + display name
    name: Formula Name
    expr: "ThoughtSpot expression"
    properties:
      column_type: MEASURE      # or ATTRIBUTE — NO aggregation: here (I2)
  - id: formula_Unique Customers   # COUNTD(x) → unique count formula, NOT aggregation: COUNT_DISTINCT (I5)
    name: Unique Customers
    expr: "unique count ( [TABLE_NAME::customer_id] )"
    properties:
      column_type: MEASURE
  columns:
  - name: display_name
    column_id: TABLE_NAME::COLUMN_NAME
    properties:
      column_type: ATTRIBUTE    # or MEASURE
  - name: Formula Name          # paired columns[] entry for every formulas[] entry (I1)
    formula_id: formula_Formula Name   # must match the formula's id exactly
    properties:
      column_type: MEASURE
      aggregation: SUM
      index_type: DONT_INDEX    # always on computed MEASURE formula columns (I3)
  - name: Unique Customers      # paired entry for the COUNTD formula (I1 + I5)
    formula_id: formula_Unique Customers
    properties:
      column_type: MEASURE
      aggregation: SUM
      index_type: DONT_INDEX
```

### Formula translation — CLI pipeline (`ts tableau translate-formulas`)

Use the CLI command to translate Tableau calculated fields to ThoughtSpot formula syntax.
This replaces ad-hoc translation and applies all 14 transforms from
[`../../shared/mappings/tableau/tableau-formula-translation.md`](../../shared/mappings/tableau/tableau-formula-translation.md)
in the mandatory execution order.

**Orphan exclusion:** Before building the translation input, remove any calcs in
`orphan_calcs` (from Step 3g). These reference missing tables and will fail at import.
Do not include them in `classification.json` — they are reported separately in the
"Excluded Formulas" section of the migration report (root cause: "Orphan inherited calc —
references table not in datasource").

**Inputs needed:**
- `classification.json` — from the Step 3 TWB parse (formula name, caption, expression, datatype, role), **excluding orphan calcs**
- `table_columns.json` — `{"COLUMN_NAME": "TABLE_NAME"}` map (column → owning table) from Step 5a table generation. The CLI uses this for `[COL]` → `[TABLE::COL]` scoping; a table-keyed shape silently disables all scoping.
- `parameters.json` — from the Step 3 parameter extraction (internal name → caption mapping)
- `--tables` — comma-separated list of tables in THIS model (used for a coverage warning; scoping itself comes from `--table-columns`)
- `--calc-map` (optional) — `{"Calculation_NNN": "Display Caption"}` map from the TWB
  `<column>` elements, needed when formulas reference other calculated fields by internal ID

**Generate the calc-id map from TWB parse:**

When the TWB parse (Step 3) extracts calculated fields, each `<column>` element has both
a `name` attribute (e.g. `[Calculation_6076974422807080981]`) and a `caption` attribute
(the display name). Build a JSON map from name → caption:

```bash
# calc_id_map.json: {"Calculation_6076974422807080981": "Revenue Growth %", ...}
```

Save to `{workdir}/calc_id_map.json`.

**Run the translation:**

```bash
ts tableau translate-formulas \
  --input {workdir}/classification.json \
  --tables TABLE_A,TABLE_B,TABLE_C \
  --table-columns {workdir}/table_columns.json \
  --parameters {workdir}/parameters.json \
  --param-map {workdir}/param_name_map.json \
  --calc-map {workdir}/calc_id_map.json \
  --datasource "{datasource_name}" \
  --output {workdir}/formulas_translated.json
```

**Output** (`formulas_translated.json`):

```json
{
  "translated": [
    {"name": "Revenue Growth %", "expr": "...", "column_type": "MEASURE", "level": 0}
  ],
  "skipped": [
    {"name": "Complex Calc", "reason": "validation: unmapped Tableau function: SPLIT",
     "level": 1, "original": "...", "attempted_expr": "..."},
    {"name": "Circular A", "reason": "circular or unresolvable dependency", "level": -1, "original": "..."}
  ],
  "stats": {
    "total": 163, "translated": 107, "skipped": 56,
    "levels": {"0": 85, "1": 18, "2": 4},
    "param_conflicts": 2, "param_renames": 1, "name_clashes": 0,
    "ifnull_stripped": 3, "agg_if_conversions": 5
  }
}
```

Use `translated` entries to populate `formulas[]` and paired `columns[]` in the model TML.
Review `skipped` entries — some may be recoverable with a `--calc-map` or by manual
inlining. `stats.levels` shows dependency depth (key = level, `-1` = circular); it maps
to the audit cross-reference depth table from Step A3/A4.

### Parameter migration (Tableau → ThoughtSpot `parameters[]`)

When the TWB has a `Parameters` datasource (Step 3), generate `parameters[]` entries
in the model TML. Omit `id` — ThoughtSpot assigns it on import.

**Type mapping:**

| Tableau `param-domain-type` | Tableau `datatype` | ThoughtSpot `data_type` | Config |
|---|---|---|---|
| `list` | `string` | `CHAR` | `list_config` with `list_choice[]` from `<member>` values. **Use `CHAR`, not `VARCHAR`** — a string **parameter** typed `VARCHAR` is rejected on import (*"Invalid parameter"*); the model-TML string parameter type is `CHAR` (live-verified 2026-06-17). This is parameters only — table *columns* still use `VARCHAR`. |
| `list` | `date` | `DATE` | `list_config` with date values (strip `#` delimiters) |
| `list` | `integer` | `INT64` | `list_config` |
| `list` | `real` | `DOUBLE` | `list_config` |
| `range` | `integer` | `INT64` | `range_config` with `range_min`, `range_max` — **unless the `<range>` has a `granularity` attribute (step size); then use `list_config`** (see note below) |
| `range` | `real` | `DOUBLE` | `range_config` — same granularity rule applies |
| `range` | `date` | `DATE` | Free-form (no `range_config` — ThoughtSpot range is numeric only) |
| `any` | any | mapped type | Free-form (no config) |
| `list` | `boolean` | `BOOL` | `list_config` with `'true'`/`'false'` values |

**Value cleanup:**
- Tableau wraps string member values in double quotes: `'"USD"'` → strip to `USD`
- Tableau date defaults use `#` delimiters: `#2026-05-10#` → strip to `2026-05-10`
  then format as `MM/DD/YYYY` (ThoughtSpot's date parameter format)

**Stepped range → `list_config` (not `range_config`):** A Tableau `<range>` parameter
that has a `granularity` attribute (step size) enumerates to a **small discrete choice
list** → use `list_config` (enumerate min→max by step), NOT `range_config` (which cannot
express the step). Plain ranges (no `granularity`) keep `range_config`.

> **Note:** A parameter that drives a Top-N/Bottom-N set's `count` should be `list_config`
> (discrete choices — live-verified ground truth used `list_config`; `range_config` loses
> the step). Example: `<range granularity='5' min='5' max='25'/>` → `list_choice: [5, 10,
> 15, 20, 25]`, `data_type: INT64`.

**SQL-lookup parameters:** If a parameter's list values come from a database query
(no static `<member>` elements in the TWB), query the warehouse at migration time to
populate `list_config.list_choice[]`:
1. Extract the SQL query or column reference from the Tableau parameter definition
2. Execute against the warehouse connection from Step 4.5
3. Use the distinct result values as `list_choice[]` entries
4. Log in `MIGRATION_LIMITATIONS.md` that these values are a point-in-time snapshot

If the selected connection cannot be queried for the values, omit the parameter and
log the omission with the original SQL query for manual recreation.

**Critical parameter invariants (from live-instance testing):**
- `range_config` values (`range_min`, `range_max`, `default_value`) **must be strings**
  in the TML — `range_min: "1"`, not `range_min: 1`. Bare integers cause
  `"Invalid YAML/JSON syntax in file"` on import. This applies even when the parameter's
  `data_type` is `INT64` or `DOUBLE`.
- When a formula references another formula inside `sum()` — e.g.
  `sum([Attrition Count])` where `Attrition Count` is `if(x='Yes') then 1 else 0` —
  ThoughtSpot rejects it with *"Function sum expects 1st argument to be Numeric"*. The
  fix is to **inline the referenced formula's expression**: write
  `sum ( if ( [x] = 'Yes' ) then 1 else 0 )` directly, not `sum ( [Attrition Count] )`.
  Apply this when any MEASURE formula references another formula column inside an
  aggregation function.
- After importing a model with parameters, **export the model** and read the
  `parameters[].id` field — ThoughtSpot assigns the UUID on import. You need this UUID
  for Step 10f (liveboard parameter chips).

### Formula reference translation

In Tableau, calculated fields reference parameters as `[Parameters].[Parameter Name]`.
In ThoughtSpot, parameters are referenced as `[Parameter Name]` (no prefix, no table
qualifier). Apply this transformation:

```
Tableau:     [Parameters].[Currency]
ThoughtSpot: [Currency]
```

This is a simple prefix strip: `[Parameters].[X]` → `[X]`. Apply AFTER resolving
Tableau internal cross-references (`[Calculation_\d+]`) and BEFORE translating function
syntax.

> **MANDATORY (I7) — before classifying any calculated field as untranslatable, open
> [`../../shared/mappings/tableau/tableau-formula-translation.md`](../../shared/mappings/tableau/tableau-formula-translation.md)
> and check its full function table and pass-through section. Do not decide from syntax alone.**
> See `../../shared/schemas/ts-model-conversion-invariants.md` (I7).

Formula translation rules: use `tableau-formula-translation.md`.
- Convert Tableau join types: `full` → `OUTER`, `left` → `LEFT_OUTER`,
  `right` → `RIGHT_OUTER`, `inner` → `INNER`
- Write formulas in topological dependency order (Level 0 first)
- Resolve Tableau internal IDs (`[Calculation_\d+]`) to display names before translating
- **LOD expressions** (`{FIXED}`, `{INCLUDE}`, `{EXCLUDE}`) → `group_aggregate()` — see
  the LOD section in `tableau-formula-translation.md`
- **`TOTAL(SUM(x))` / percent-of-total** → `group_aggregate(..., {}, query_filters())`
- **Tableau bins** (`class='bin'`): **prompt the user** for how to create each one — there
  are two valid representations and the choice is theirs:

  ```
  This workbook has {N} bin field(s):
    - Age (bin):     binned on [Age],     size = parameter "Age Groups" (dynamic)
    - Balance (bin): binned on [Balance], size = parameter "Balance (bin) Parameter" (dynamic)

  How should each bin be created?
    F  floor() formula        — keeps it dynamic when the size is parameter-driven
    C  cohort / column set     — native BIN_BASED set, fixed bin size
    B  both
  (default: F for parameter-driven bins, C for fixed-size bins)
  ```

  - **F — `floor()` formula**: `floor([x]/size)*size` referencing the migrated parameter
    (resolve its internal name to the parameter caption) or a literal for fixed size. Stays
    dynamic if parameter-driven.
  - **C — cohort**: a separate **`cohort:` TML object** (`cohort_grouping_type: BIN_BASED`,
    `anchor_column_id`, `bins.{minimum_value,maximum_value,bin_size}`) bound to the model by
    `obj_id`. A cohort needs a fixed range — **prompt the user for `minimum_value`,
    `maximum_value`, and `bin_size`**, offering the Tableau parameter's default as the
    suggested `bin_size`. If the user can't supply the range, **fall back to a warehouse
    lookup** (`SELECT MIN/MAX`, with their authorization) — prompt first, DB lookup second.
    See the Bins section in `tableau-formula-translation.md` and
    `../../shared/schemas/thoughtspot-sets-tml.md`. Generate as `*.cohort.tml` and import
    **after** the model.
  - **B — both**: emit the formula *and* the cohort.

  Offer the smart default per bin (F for dynamic, C for fixed) so the user can just accept.
- **Manual groups** (`class='categorical-bin'`) → a **`GROUP_BASED` cohort** (`*.cohort.tml`):
  one `groups[]` entry per `<bin>`, its `<value>` list → the condition `value[]`, the calc's
  `default` → `null_output_value`. **Classify by the calculation `class`, not the field name** —
  a field called "… (clusters)" is usually a `categorical-bin` (translatable), not k-means.
  Only true statistical clustering is untranslatable. Bind by the model `obj_id`; import after
  the model. Watch the value-format caveat (stored values must match the group's values).
  - **Cohort vs. `if/then` formula:** if each group is a **contiguous, non-overlapping range**,
    an `if … then … else if … then … else …` formula is cleaner (ThoughtSpot has **no `CASE`** —
    use the if/then/else-if chain); if groups are **arbitrary/interleaved value sets**, use the
    cohort (a range formula would misclassify). Check membership before choosing — see the
    categorical-bin section in `tableau-formula-translation.md`.
- **`Number of Records` / row-count fields** → `count([column])`. **Prompt the user for which
  column to count** (default the table's primary key); carry the same choice into dependent
  formulas (e.g. percent-of-total). Don't emit `sum(1)`.
- **Referencing one formula from another:** use the **formula id** `[formula_<id>]`, **not**
  its display name `[<Name>]` — the name form errors *"Search did not find …"*. E.g.
  `[formula_Attrition Count] / sum([T::EMPLOYEECOUNT])`. (Column refs still use `[T::COL]`.)
- **Model-level vs answer-level formulas.** A calculated field used across many worksheets
  belongs in the **model** `formulas[]` (reusable). One used by **only a single worksheet**
  can instead be an **answer-level formula** on that liveboard viz (`answer.formulas[]`,
  with a matching `answer_columns[]` entry) — keeping the model lean. Decide by reuse: shared
  → model; viz-specific → answer-level.
- **Growth / decline (Tableau `pcdf` / percent-difference / running-percent table calcs).**
  Prefer the **`growth of`** search keyword when the breakdown is over a **date**:
  `growth of [Measure] by [Date]` (this is a viz `search_query`, not a model formula). If
  there is **no date** (e.g. growth across a *sector* attribute), build explicit
  this-period vs last-period formulas and a percentage — but when a date exists, `growth of`
  is the right tool.
- **Running calculations** (`RUNNING_SUM`, etc.) → `cumulative_sum()`, etc.
- **Rank functions** → `rank()`
- **Window functions** (WINDOW_SUM, WINDOW_AVG, etc.) → `moving_sum()`, `moving_average()`,
  etc. — requires identifying the sort dimension from the worksheet shelf. See "Window /
  Moving Functions" in `tableau-formula-translation.md`.
- **Pass-through fallback** for formulas with valid Snowflake SQL but no native ThoughtSpot
  function (partitioned RANK, DENSE_RANK, WINDOW_* when sort dimension is unknown): use
  `sql_*_aggregate_op()` pass-through functions — see "Pass-Through Fallback" in
  `tableau-formula-translation.md`. Always prefer native functions first.
- **Comma-separated-list / string-concatenation technique** (FIRST/LAST/LOOKUP/PREVIOUS_VALUE used
  together to build one delimited string of a column's values — e.g. Jonathan Drummey's CSV-list /
  set-member-list dashboards): do **NOT** omit — translate the *intent* to **`LISTAGG` string
  aggregation** (`sql_string_aggregate_op ( "LISTAGG({0}, ', ') WITHIN GROUP (ORDER BY {0})" , [col] )`,
  answer-level, ⚑ flag for review per PT1) or a plain table of the values. The feeder/`Last` scaffolding
  calcs collapse into the one LISTAGG formula. See `tableau-formula-translation.md` "String aggregation".
- **Geospatial formulas** — full 13-function set (`MAKEPOINT`, `MAKELINE`, `BUFFER`, `OUTLINE`,
  `DISTANCE`, `AREA`, `LENGTH`, `INTERSECTS`, `SHAPETYPE`, `DIFFERENCE`, `INTERSECTION`,
  `SYMDIFFERENCE`, `VALIDATE`): omit the spatial formula entirely. For `MAKEPOINT(lat, lon)`,
  ensure the underlying latitude and longitude columns are migrated as individual `ATTRIBUTE`
  columns — they are useful for filtering and display even without a map visualization. For
  `DISTANCE`/`BUFFER`/`AREA`/`LENGTH`/`INTERSECTS`/`DIFFERENCE`/`INTERSECTION`/`SYMDIFFERENCE`,
  flag more prominently (the spatial computation is lost, not just the wrapper). See
  `tableau-formula-translation.md` "Geospatial Policy". Log each omission.
- **Embedded-RLS user attributes** (`USERATTRIBUTE`, `USERATTRIBUTEINCLUDES`): rejected at
  translate time — no CLI translation yet. See `tableau-formula-translation.md` "Untranslatable
  Patterns" and BL-071 for the ABAC `ts_var()` translation candidate.
- **Row-offset table calculations** (`INDEX`, `LOOKUP`, `FIRST`, `LAST`, `SIZE` —
  standalone, NOT as `WINDOW_*`/`RUNNING_*` offset args). Apply the tiered decision tree
  from `tableau-formula-translation.md` "Row-Offset Table Calculations":

  1. **Top-N filter intent** — `INDEX() <= N` or `INDEX() = N` inside an IF/CASE or set
     filter → route to the existing query-set machinery (Step 5b query-set emission).
     Use `rank ( [measure] , 'desc' )` + filter formula `[rank] <= N`.

  2. **Native rank** — `INDEX()` used for display row numbering where `ordering_type` is
     `Field` with a single date/continuous dimension → `rank ( [measure] , 'asc' )`.

  3. **Native window functions** — sort is unambiguously recoverable from the
     `<table-calc>` addressing (Step 3f) + worksheet shelf (Step 9b). Uses native
     ThoughtSpot functions (no SQL pass-through, works with all column types):
     - `INDEX()` → `rank ( sum ( [measure] ) , 'asc' )` (ranks by value, not row position — acceptable)
     - `LOOKUP(agg, N)` where N < 0 (LAG) → `moving_sum ( [measure] , abs(N) , -abs(N) , [sort_col] )`
     - `LOOKUP(agg, N)` where N > 0 (LEAD) → `moving_sum ( [measure] , -N , N , [sort_col] )`
     - `LOOKUP(agg, FIRST())` → `first_value ( sum ( [measure] ) , query_groups ( ) , { [sort_col] } )`
     - `LOOKUP(agg, LAST())` → `last_value ( sum ( [measure] ) , query_groups ( ) , { [sort_col] } )`
     - Bare `FIRST()` / `LAST()` standalone → **omit + log** (these return row *offsets* in
       Tableau, not data values — `FIRST()` = distance-to-first-row, `LAST()` = distance-to-last-row;
       no TS equivalent). Exception: `FIRST()+1` for row numbering → `rank()` approximation.
     - `SIZE()` → `sql_int_aggregate_op ( "COUNT(*) OVER ()" )` ⚑ flag PT1 (only row-offset needing pass-through)
     - All are **answer-level only** (in `answer.formulas[]`, not model `formulas[]`).
     - **SQL pass-through alternative:** when exact SQL semantics are needed (e.g.,
       partitioned LEAD/LAG with date bucketing), `sql_*_aggregate_op` works if the
       ORDER BY date expression matches the search query's date aggregate (e.g.,
       `start_of_month([date])` with `[date].monthly`) and all shelf GROUP BY columns
       are in PARTITION BY. See `tableau-formula-translation.md` "SQL pass-through alternative".

  4. **Omit + log** — addressing is ambiguous (`ordering_type='CellInPane'`, multi-dim
     `Table`, or no deterministic shelf sort). Log: `"[func]() — addressing context is
     ambiguous (ordering_type={type}); omit + log."` This is the current behavior,
     preserved for genuinely unrecoverable cases.

  **Resolving the sort column:** Use the `table_calc_addressing` / `ws_table_calc_overrides`
  maps from Step 3f. Check the worksheet override first, then fall back to the column-level
  definition. Map `ordering_type` to a sort column per the resolution table in
  `tableau-formula-translation.md` "Row-Offset Table Calculations". If resolution fails,
  fall through to Tier 4.

- **`PREVIOUS_VALUE()` (true recursion)** — still untranslatable (recursive CTE, not a
  scalar expression). Omit + log. The string-aggregation exception (FIRST/LAST/LOOKUP/
  PREVIOUS_VALUE CSV technique → LISTAGG) takes precedence and is handled above.
- **Other truly untranslatable formulas** (k-means clustering, geospatial): unchanged — omit
  from `formulas[]` entirely, omit the corresponding `columns[]` entry, and log the
  omission. See `tableau-formula-translation.md` "Untranslatable Patterns".
- Every join MUST have a non-empty `on` field. Multi-column joins are fine —
  `on: "[A::k1] = [B::k1] AND [A::k2] = [B::k2]"`.
- **Join keys must be physical columns — you cannot join on a model formula.** And a
  ThoughtSpot relationship is **binary**: a join's `on` cannot span more than two tables, so
  **multi-table join keys must be co-located into ONE relation first** (e.g. targets keyed by
  `(month, category)` where `month` derives from one table and `category` lives on another →
  build a **single SQL view spanning both** so both keys sit on one relation). If a needed
  key simply **doesn't exist** (e.g. month-of-order-date when orders only have a full
  `ORDER_DATE`), **stop and advise the user**; don't skip it or fake a formula key. Present
  the **two ways to make the column(s) physically exist**, and let the user choose:
  1. **ThoughtSpot SQL View** (a `sql_view` TML — Step 5c): write the derived/pre-aggregated
     columns into a `SELECT` over the connection (`DATE_TRUNC('month', ORDER_DATE) AS …`,
     `GROUP BY …`). Its `sql_output_columns` are physical → valid multi-column join keys. Fast,
     stays entirely in TML, no warehouse change. Use this as the foundation table for the model.
  2. **Database table/view** the user creates in the warehouse, then **adds to the connection**
     so ThoughtSpot can see it — then bind a normal Table TML to it. More setup (DB work +
     connection refresh) but governed/reusable outside this model.
  State exactly what the object needs to expose (which derived/aggregated columns, at what
  grain) so the user can act. A ThoughtSpot join can be multi-column; the keys just have to be
  real columns the relation exposes.
- **Cross-datasource formulas (Tableau data blends).** When datasources are merged into a
  single model via blend-aware grouping (Step 5b), cross-datasource references resolve
  naturally — all columns from all blended datasources exist in the same model. A formula
  like `SUM([Sales]) - SUM([OtherDS].[Target])` becomes
  `sum ( [ORDERS::Sales] ) - sum ( [TARGETS::Target] )` because both `ORDERS` and `TARGETS`
  are `model_tables[]` entries in the same model.

  **Reference resolution:** Tableau formulas reference other datasources in two formats:
  - **By federated ID:** `[federated.xxx].[column_name]` (the internal XML format)
  - **By caption:** `[Datasource Caption].[column_name]` (the display format)

  During formula translation:
  1. Detect the datasource prefix (`[federated.xxx]` or `[Caption]`) using the
     `ds_id_to_caption` mapping from Step 5b — match against both IDs and captions
  2. Strip the prefix, leaving just `[column_name]`
  3. Resolve the column name against the merged model's `columns[]` (it will exist because
     the secondary datasource's columns were included in the merge)
  4. Prefix with the correct `TABLE_NAME::` for the ThoughtSpot model reference

  **If a cross-datasource formula references a datasource NOT in the blend group** (shouldn't
  happen in well-formed workbooks, but possible in hand-edited TWBs): log a warning and omit
  the formula with a flag in the audit report.
- No `fqn` in `model_tables`
- `obj_id` is optional on fresh import — omit it unless repointing an existing model

### Tableau Sets → ThoughtSpot column sets (Phase 2a)

> **Construct distinction:** A Tableau **set** is a top-level `<group ...>` element (a named
> in/out partition on a dimension column). It is **entirely different** from a **manual group**
> (`<column><calculation class='categorical-bin'>`) — which is already handled above as a
> `GROUP_BASED` cohort. Do NOT confuse the two. Sets are identified by the `<group>` XML
> element; manual groups by the calculation `class`.

**Detection — scan for top-level `<group>` elements in the datasource XML.**

For each `<group>` element, inspect its `<groupfilter>` tree and classify:

- **Static set (Phase 2a — translate):** the groupfilter tree contains **only**
  `function='union'` and `function='member'` nodes (optionally `function='level-members'`).
  There is **no** `function='end'` and **no** `function='except'`/`'intersect'`.

  Extract:
  - `caption` attribute → set name
  - The `level='[Dimension]'` attribute on the groupfilter → anchor column → its ThoughtSpot
    column **display name** (map via the model's column mapping). **If `level` is a calculated
    field** (`[Calculation_NNN]`, i.e. a set anchored on a derived dimension like
    `YEAR([Order Date])`): **resolve the internal ID to the calc's display name** via the calc
    cross-reference map (Step 3), and **ensure that calc is emitted as a model formula column**
    (an ATTRIBUTE formula, e.g. `year ( [Order Date] )`) so the set has a column to anchor on.
    Column sets **can** anchor on a formula column by its display name (live-verified 2026-06-12 —
    a set anchored on the `Sales Rep` formula column imported cleanly). Never emit the raw
    `Calculation_NNN` id as `anchor_column_id`.
  - Each child `<groupfilter function='member' member='...'/>` → a member value:
    - **HTML-decode** the value (`&quot;` → `"`, `&amp;` → `&`, `&lt;` → `<`, `&gt;` → `>`)
    - Strip Tableau's surrounding double-quotes from string values (e.g. `'"Aaron Bergman"'` → `Aaron Bergman`)
    - **Match `filter_value_type` to the anchor's type** — text → `STRING`; a numeric calc anchor
      (e.g. `year()` → integer, member `2018`) → `DOUBLE`; a date anchor → `DATE_FILTER` (per 1.5.9).
    - **`%null%` member → use the literal `{Null}` grouping value.** NULL **is** selectable in a column
      set (live-verified 2026-06-12 — the UI emits the token `{Null}` for a null selection). Emit a
      condition `operator: EQ, value: ["{Null}"], filter_value_type: STRING`.
      - **`%null%` *included*** (a `union`/member set putting NULL **in** the set) → add the `EQ {Null}`
        condition alongside the member-list condition with `combine_type: ANY` (in the list **or** null).
      - **`%null%` *excluded*** (an `except` removing NULL) → no condition needed: nulls already fall to
        the catch-all "out" bucket via `combine_non_group_values`. (Or be explicit with `NE`/no-`{Null}`.)
      No formula alternative is required for null — column sets handle it directly via `{Null}`.

- **Top-N / Bottom-N set (Phase 2b — TRANSLATE to a query set):** groupfilter tree contains
  `function='end'` (with `count` and/or `order` child/attributes). Translate to a
  `cohort_type: ADVANCED` / `COLUMN_BASED` query set in **one of two forms, chosen by `count`:**
  - **Literal `count='N'` (static N)** → the simplest form: the embedded answer's `search_query`
    is a plain **`top N [dimension] [measure]`** (or **`bottom N …`**) keyword search (anchor
    dimension first, then measure) — **no formulas, no parameter**. (The `top N` keyword
    search_query IS correct for a fixed N.)
  - **`count='[Parameters].[X]'` (dynamic, parameter-driven N)** → a **rank formula +
    parameter-filter formula**, with N read from the migrated model parameter. This is the only
    form that stays in sync with the parameter as the user changes it. (B2VBWeek11 uses this.)

  Detection (applies to both forms):
  - `end='top'` → `top N` keyword / `rank(..., 'desc')`; `end='bottom'` → `bottom N` keyword /
    `rank(..., 'asc')`.
  - The `order` child's `expression` (e.g. `SUM([measure])`) → the ranking measure (and, in the
    dynamic form, the rank's aggregation). If the ordering measure is a *derived/conditional*
    field (null-pad, IF-exclude), use the plain underlying measure and **flag** the dropped nuance.
  - `count` type selects the form: `[Parameters].[X]` → dynamic (filter references the migrated
    model param `[<alias>::<param>]`); a literal `N` → static (`top N`/`bottom N` keyword).
  - The innermost `level='[Dim]'` → anchor/return column display name.

  Extract:
  - Set `caption` → cohort name.
  - Ordering measure column display name (via the model's column mapping).
  - Parameter name (if `count` is a parameter reference) — must already exist on the model
    (migrated via the Parameters datasource → `model.parameters[]`).

  Emit one `*.cohort.tml` per Top-N/Bottom-N set — see **Query-set TML emission** below.
  Log: `"Set '<name>' is a Top-N/Bottom-N set → translated to a ThoughtSpot query set (rank
  formula + parameter-filter, Phase 2b) — flag for review."`

  Flag dropped nuances: if the ordering measure is conditional/null-padded, note the
  simplification: `"Dropped null-padding / conditional ranking — using plain <measure>; verify
  ranking matches the Tableau set."`

- **`except` of a member-list (TRANSLATABLE) — column set with `NE`:** an `except` whose excluded
  side is a `union`/`member` list (e.g. *all categories except {Furniture, %null%}*) maps to a column
  set: one group with an `operator: NE` condition per excluded member, `combine_type: ALL` ("not A AND
  not B"). `operator: NE` is a valid cohort operator (live-verified 2026-06-12). Any `%null%` in the
  excluded side needs no condition — it's already excluded by `combine_non_group_values` (catch-all).
  Anchor + member rules are the same as a static set.
- **`intersect` of two member lists (Phase 2c — TRANSLATABLE):** groupfilter tree has
  `function='intersect'` and **both** children are member/union sub-trees (no `function='end'`,
  `'filter'`, or nested set-op). Compute the **set intersection at conversion time** — the members
  common to both lists. Emit a `GROUP_BASED` column set with `operator: EQ` conditions for the
  shared members (same emission as a static set). If the intersection is empty, log and skip:
  `"Set '<name>' intersect yields zero common members — omitted."` Otherwise log:
  `"Set '<name>' is an intersect of two member lists → column set (GROUP_BASED, {N} common members, Phase 2c) — flag for review."`

- **`except` where the excluded side is a Top-N/Bottom-N (Phase 2c — TRANSLATABLE):** groupfilter
  tree has `function='except'` and the excluded child contains `function='end'`. This means "all
  dimension values EXCEPT the Top/Bottom N" — the **complement** of the Top-N set. Translate to a
  query set using an **inverted rank filter**: `[formula_rank] > N` (or `> [param]`) instead of
  `<= N`. All other emission rules are identical to Phase 2b (same rank formula, same anchor/measure,
  same static-vs-dynamic form selection). Log:
  `"Set '<name>' is 'all except Top/Bottom-N' → query set with inverted rank filter (Phase 2c) — flag for review."`

- **Condition-based set (Phase 2c — TRANSLATE to a query set):** groupfilter tree contains
  `function='filter'` (with a `quantitative` or `expression` child specifying an aggregate condition
  like `SUM([Sales]) > 10000`). This is a Tableau set created via the **Condition tab** — membership
  is determined by an aggregate condition evaluated per dimension member at query time.

  Detection:
  - `function='filter'` in the groupfilter tree (distinct from `'end'` which is Top-N).
  - The condition expression is in the `expression` attribute or a `<groupfilter function='quantitative'>`
    child with `<groupfilter function='range' from='...' to='...'/>` bounds.
  - The `level='[Dim]'` attribute → anchor column display name (same resolution as static/Top-N sets).

  Extract:
  - Set `caption` → cohort name.
  - The aggregate expression (e.g. `SUM([Sales])`) → translate through the formula translation
    reference to a ThoughtSpot formula.
  - The comparison operator and threshold(s) from the `range` element or the expression itself.

  Emit as a query set (`cohort_type: ADVANCED`, `cohort_grouping_type: COLUMN_BASED`) with:
  - One formula: the translated condition as a boolean expression
    (e.g. `sum ( [Model_1::Sales] ) > 10000`). Set `properties.column_type: ATTRIBUTE`.
  - `search_query: "[<measure>] [<dimension>] [formula_condition] [formula_condition] = true"`
  - Same `answer` structure as the Top-N query set (tables, table_paths, answer_columns, display_mode).

  Log: `"Set '<name>' is a condition-based set (condition: <expr>) → query set with condition
  formula (Phase 2c) — flag for review."`

- **Computed set operations — intersect / except of mixed types (Phase 2c — TRANSLATE to a
  multi-formula query set):** a set operation (`intersect` or `except`) where at least one side
  is a computed set (Top-N, condition-based) and the other is a member list, a computed set, or
  `level-members` (all). The query set's embedded answer can hold **multiple formulas** — compose
  each side's filter logic into the same answer and combine via the `search_query`.

  **Composition rules — build one formula per side, then combine:**

  | Side type | Formula to generate |
  |---|---|
  | Member list (`union`/`member`) | `formula_members`: `[Model_1::Dim] = 'val1' or [Model_1::Dim] = 'val2' or ...` (one `or` per member). Set `properties.column_type: ATTRIBUTE`. |
  | Top-N (`function='end'`) | `formula_rank`: `rank ( sum ( [Model_1::measure] ) , 'desc' )` + `formula_topn`: `[formula_rank] <= N` (or `<= [Model_1::param]`). Same as Phase 2b. |
  | Condition (`function='filter'`) | `formula_cond`: translated aggregate condition (e.g. `sum ( [Model_1::Sales] ) > 10000`). Set `properties.column_type: ATTRIBUTE`. |

  **Combining in `search_query`:**

  | Operation | search_query pattern |
  |---|---|
  | **Intersect** (A ∩ B) | `"[measure] [dimension] ... [formula_a] = true [formula_b] = true"` — both filters must pass (AND). |
  | **Except** (A EXCEPT B) | `"[measure] [dimension] ... [formula_a] = true [formula_b] = false"` — A passes, B fails. For Top-N exclusion, invert the rank filter: `[formula_rank] > N` instead of `<= N`, then use `= true`. |

  The `answer_columns`, `table_columns`, and `ordered_column_ids` include the dimension, the
  aggregated measure, and every formula column. The `display_mode` is `TABLE_MODE`.

  **Example — "East States ∩ Top 10 by Revenue":**
  ```yaml
  cohort:
    name: East Top Revenue
    answer:
      formulas:
      - id: formula_members
        name: member_filter
        expr: "[Model_1::State] = 'NY' or [Model_1::State] = 'CA' or [Model_1::State] = 'TX'"
        properties:
          column_type: ATTRIBUTE
      - id: formula_rank
        name: rank
        expr: "rank ( sum ( [Model_1::Revenue] ) , 'desc' )"
        properties:
          column_type: ATTRIBUTE
      - id: formula_topn
        name: topn_filter
        expr: "[formula_rank] <= 10"
      search_query: "[Revenue] [State] [formula_rank] [formula_members] = true [formula_topn] = true"
      # ... tables, table_paths, answer_columns, display_mode as per Phase 2b
    config:
      cohort_type: ADVANCED
      cohort_grouping_type: COLUMN_BASED
      anchor_column_id: State
      return_column_id: State
  ```

  Log: `"Set '<name>' is a computed set operation (<op> of <type-A> and <type-B>) → query set
  with {N} formulas (Phase 2c) — flag for review."`

  **Deeply nested set-ops:** if a side is itself a set operation (e.g. `(A ∩ B) EXCEPT C`),
  recursively decompose — flatten all member lists into one `or` formula, and each computed side
  into its own formula pair. The search_query combines all filters. Flag deeply nested cases
  prominently: `"Nested set operation — {depth} levels deep; verify the combined filter logic."`

- **Set control / dynamic set (no static members) → an interactive filter; drop the scaffolding.** A set
  whose groupfilter tree is **`level-members` only** (`ui-enumeration="all"`, `ui-builder="filter-group"`)
  has no fixed membership — it's a Tableau **Set Control** the user toggles live, usually feeding
  `IF [Set] THEN measure ELSE NULL` calcs. **That set + IF-calc machinery is Tableau scaffolding to fake
  interactive filtering — ThoughtSpot does it natively.** Translate the *intent*, not the scaffolding:
  1. **Migrate the anchor as a model formula column** if it's a calc (e.g. `01. Month` =
     `DATE(DATETRUNC('month',[Order Date]))` → `start_of_month ( [Order Date] )`) — a useful filterable
     dimension. (Same calc-anchor rule as a static set.)
  2. **Map the control to an interactive filter** on that column (Step 10). The filter *is* the selection.
  3. **Drop the `IF [Set] THEN measure ELSE NULL` referencing calcs** — do NOT migrate them as formulas.
     The measure + filter replaces them (`sum(sales)` filtered to the chosen months). Treat them like the
     "redundant pass-through formula" case: recognize the intent and collapse to the native pattern.
  4. **Do not emit a cohort.** The only case needing more than a filter is a genuine side-by-side
     **in-set vs out-set comparison** viz — handle that with a grouping attribute (a real static column set)
     or two answers; flag it specifically rather than generalising a "capability gap" onto every control.
  Log: `"Set '<name>' is a dynamic Set Control → mapped to a filter on <anchor> (anchor calc migrated as a column); its IF-[Set] scaffolding calcs were collapsed into measure+filter, not migrated."`
- **Worksheet set action (no equivalent — defer):** a `<action>` element that adds/removes
  members from a set based on viz selection. No ThoughtSpot equivalent. Log:
  `"Set action on '<set name>' has no ThoughtSpot equivalent — omitted."`

**Emit one `*.cohort.tml` per static set** — see "Column-set TML emission" below. **Emit one
`*.cohort.tml` per Top-N/Bottom-N set** — see "Query-set TML emission" below. Import
cohorts after the model (the payload order in Step 5.5 already includes `*.cohort.tml`).
**Import order for query sets: model (with parameter) → cohort** — the set's formula
references the parameter, which must exist on the model first.

> **⚠ MANDATORY — flag every set conversion for the user to review.** Set conversions are
> *semantic reinterpretations*, not literal 1:1 translations — a column set, a filter, dropped
> scaffolding, or a deferral may not behave exactly like the Tableau set. For **each** set, surface
> its outcome and ask the user to confirm it matches intent, in **both** the Step 7 review checkpoint
> and the Migration Summary (Step 10g) / Step 12 report. Show a per-set line with its kind and how it
> was handled, e.g.:
> ```
> Sets ({N}) — review each result matches intent:
>   ✓ State Set            → column set (GROUP_BASED, 3 members)         [verify membership]
>   ✓ Category Set         → column set via NE (except {Furniture})      [verify exclusion + nulls]
>   ✓ Year Set             → column set on formula column "Order Year"   [verify the calc + values]
>   ⚠ Customer Group 1     → column set (231 members)                    [large list — spot-check]
>   ⚙ 01. Month Set        → interactive filter on "Order Month"; IF-[Set] calcs collapsed to
>                            measure+filter, NOT migrated                [confirm filter ≈ the control]
>   ✓ State_TopN           → query set (rank desc by SUM gallons, N=topN param)   [verify ranking + N]
>   ✓ State_BottomN        → query set (rank asc by SUM gallons, N=topN param)    [verify ranking + N]
>   ✓ Region_Intersect     → column set (GROUP_BASED, 4 common members from intersect)   [verify membership]
>   ✓ State_NotTopN        → query set (inverted rank desc, all except top N)          [verify ranking + N]
>   ✓ HighRevCustomers     → query set (condition: SUM(Revenue) > 10000)               [verify condition]
>   ✓ East_TopRevenue     → query set (member-list ∩ Top-N, 3 formulas)              [verify combined filter]
> ```
> The reinterpreted ones (`except`→`NE`, `%null%`→`{Null}`, formula-anchor, set-control→filter,
> collapsed `IF [Set]` calcs, **Top-N/Bottom-N → query set**, **condition-based → query set**,
> **member-list intersect → computed common members**, **all-except-Top-N → inverted rank**)
> especially need a human eye — call them out explicitly, don't bury them. For Top-N/Bottom-N
> and condition-based sets, explicitly call out any dropped ranking nuances (null-padding,
> conditional measure) or simplified conditions so the user can verify the result matches intent.

#### Set IN/OUT semantics — the column set IS the In/Out classification

A Tableau set returns a **boolean per row** — every dimension value is either a **member (IN)** or
not (**OUT**). The migrated `GROUP_BASED` column set already encodes exactly that: its group label is
the **In** value and the `combine_non_group_values` catch-all (`null_output_value`) is the **Out**
value. So the three ways Tableau uses In/Out all map cleanly — translate the *intent*, don't migrate
the `IF [Set]` scaffolding calcs:

- **Compare In vs Out** (e.g. "Compare In vs Out" / "Part to Whole" dashboards) → **group a measure by
  the cohort column** (`[measure] [Set]` → two groups, In vs Out). Native — this is the comparison; it
  is **not** a capability gap for a static set.
- **In/Out measure** (`IF [Set] THEN [Sales] END` / `Set Sales` / `Group 1 Sales`) → a **conditional
  aggregate**. Three equivalent forms (all live-verified 2026-06-12) — a column set **is**
  formula-referenceable as `[<cohort name>] = '<in/out label>'`:
  - **Literal translation** (mirrors Tableau's `IF [Set] THEN x END` exactly):
    `sum ( if ( [Product Category set] = 'in' ) then [Sales] else null )`.
  - **`sum_if` shorthand** (preferred, esp. for large member lists — no inlining):
    `sum_if ( [Product Category set] = 'in' , [Sales] )` (and `… = 'out'` for OUT). Family:
    `sum_if`/`average_if`/`count_if`/`unique_count_if`/`max_if`/`min_if`.
  - **Dimension + member list** (no cohort dependency; fine for small lists):
    `sum_if ( [Category] in { 'Furniture','Technology' } , [Sales] )` /
    `sum_if ( not ( [Category] in { 'Furniture','Technology' } ) , [Sales] )`.
  - ⚠️ **Pitfall (cohort-ref forms):** the cohort **name must differ from its group labels** — a
    name==label collision (e.g. cohort `Focus Categories` with group also `Focus Categories`) makes the
    formula fail with *"Search did not find …"*. Emit distinct labels (group `in`, out `out`); see the
    emission template.
- **Filter to In / Out** → filter on the cohort column = the In label (or the Out label).
- **`IF [Set] THEN [dimension]` label calcs** (`In`, `Out`, `Set Label`) → the cohort column itself
  (its two labels), or the dimension filtered to In/Out.

Pick `sum_if(...)` when In and Out are wanted as **separate measure columns** (KPIs, side-by-side, an
In/Out ratio) — reference the cohort for large lists, the dimension for small; pick **grouping by the
cohort** for an in-vs-out **breakdown** viz. Either way the pile of `IF [Set] THEN …` calcs collapses onto the one
column set / a couple of `sum_if`s — don't emit them as per-row formulas.

See `../../shared/schemas/thoughtspot-sets-tml.md` (column set + query set) and the live-verified
worked examples `../../shared/worked-examples/tableau/static-set-to-column-set.md` (column set) and
`../../shared/worked-examples/tableau/topn-set-to-query-set.md` (Top-N/Bottom-N query set).

#### Column-set TML emission (static set → `GROUP_BASED` cohort)

For each static set detected above, generate a `.cohort.tml` file with the following shape:

```yaml
# guid omitted on first import
cohort:
  name: "<set caption>"              # from the Tableau set's group caption attribute
  config:
    cohort_type: SIMPLE
    cohort_grouping_type: GROUP_BASED
    anchor_column_id: "<dimension display name>"  # ThoughtSpot column DISPLAY name (live-verified), from groupfilter level=
    combine_non_group_values: true          # DEFAULT CATCH-ALL: every value not matched by a group — incl. NULL — combined into one group
    null_output_value: "out"                # OUT label for the catch-all — keep DISTINCT from the cohort name (see below)
    groups:
    - name: "in"                     # IN label — MUST differ from the cohort `name` above, or formula refs
                                     # (`sum_if([<cohort>] = 'in', …)`) fail with "Search did not find" (live-verified).
                                     # Formula refs must match this label EXACTLY (case-sensitive).
      combine_type: ANY              # ANY = membership in the value list ("in set")
      conditions:
      - operator: EQ                 # PROVEN pattern (changelog 1.5.6, from a working column set):
        column_name: "<dim name>"    #   operator: EQ with a MULTI-VALUE list = "in set".
        value: ["Aaron Bergman", "Aaron Hawkins", ...]  # NOT operator: IN.
        filter_value_type: STRING    # STRING for text anchors; for a DATE anchor use DATE_FILTER
                                     # + date_filter_values instead (changelog 1.5.9).
  worksheet:                         # BINDING FIELD IS `worksheet:` NOT `model:` (live-verified — `model:` → "Table cant be empty")
    id: "<model display name>"
    name: "<model display name>"
    obj_id: "<model obj_id>"         # stable object id, e.g. TEST_SV_..._AI_CONTEXT-889a704f (from the model's exported TML header)
```

Key rules:
- `anchor_column_id` and `column_name` = the dimension's ThoughtSpot **display name** (live-verified —
  works even for a multi-table model). Map from `level='[Dimension]'` via the same column mapping as Step 5b.
- `combine_non_group_values: true` is the **default catch-all**: every value not matched by a group
  condition — including NULL — is combined into one group, labelled by `null_output_value`. This
  mirrors Tableau's in/out semantics: unmatched + NULL rows land in the catch-all ("out") bucket.
- Member values must be **HTML-decoded** and have Tableau's surrounding double-quotes stripped,
  AND converted to the column's **stored** format, not Tableau's display format (changelog 1.5.6:
  e.g. `01.Apr.15` → `2015-04-01`) — display-format values match nothing.
- Membership uses `operator: EQ` with the full value list + `combine_type: ANY` (proven in 1.5.6) —
  do **not** use `operator: IN`. For a **DATE** anchor, switch each condition to
  `filter_value_type: DATE_FILTER` + `date_filter_values` (changelog 1.5.9), not `STRING`/`value[]`.
- **`%null%` is selectable as a grouping value** — column sets DO support NULL membership (live-verified
  2026-06-12). To **include** null in the set, add a condition `operator: EQ, value: ["{Null}"],
  filter_value_type: STRING` to the group (with `combine_type: ANY` so it's "in the list OR null"). To
  **exclude** null, omit it (the catch-all already excludes it). The literal token is `{Null}`. No
  IF/THEN/ELSE formula alternative is needed for null.
- **`except` / not-in** → `operator: NE` (live-verified 2026-06-12): one `NE` condition per excluded
  value, `combine_type: ALL`. (`except {Furniture, %null%}` → `NE Furniture`; null auto-excluded.)
- Bind the set to its model via the **`worksheet:`** block (`id`/`name` = the model display name;
  `obj_id` = the model's stable object id, from the model's exported TML header) — **not** `model:`.
  Using `model:` fails import with `"Invalid save request, Table cant be empty"` (live-verified
  2026-06-12: set "Focus Categories" created on model `TEST_SV_DMSI_AI_CONTEXT` only after switching
  `model:` → `worksheet:`).
- No top-level `guid` on first import.
- File extension: `<SetName>.cohort.tml`; write to
  `/tmp/ts_tableau_mig/output/{workbook_name}/`

Write each file to `/tmp/ts_tableau_mig/output/{workbook_name}/{DatasourceName}.model.tml`.

#### Query-set TML emission (Top-N/Bottom-N → ADVANCED cohort)

For each Top-N/Bottom-N set detected above, generate a `.cohort.tml` file. There are **two
forms** (see classification above): the **dynamic** form (parameter-driven N — a rank formula +
parameter-filter formula, live-verified 2026-06-12 against se-thoughtspot, model
`TEST_SV_DMSI_AI_CONTEXT`), and the simpler **static** form (fixed N — a `top N`/`bottom N`
keyword search, no formulas) shown after it. Cross-refs:
`../../shared/schemas/thoughtspot-sets-tml.md` (query set section) +
`../../shared/worked-examples/tableau/topn-set-to-query-set.md`.

**Dynamic form (parameter-driven N — `count='[Parameters].[X]'`):**

```yaml
# guid omitted on first import
cohort:
  name: "<set caption>"
  answer:
    tables:
    - id: "<model display name>"
      name: "<model display name>"
      obj_id: "<model obj_id>"
    table_paths:
    - id: "<model display name>_1"          # self-path alias used by the formulas
      table: "<model display name>"
    formulas:
    - id: formula_filter
      name: filter
      expr: "[formula_rank] <= [<model display name>_1::<paramName>] "
      was_auto_generated: false
    - id: formula_rank
      name: rank
      expr: "rank ( sum ( [<model display name>_1::<measure col>] ) , 'desc' )"   # 'asc' for Bottom-N
      properties:
        column_type: ATTRIBUTE
      was_auto_generated: false
    search_query: "[<measure>] [<dimension>] [formula_rank] [formula_filter] = true"
    answer_columns:
    - name: <dimension display name>
    - name: "<aggregated measure display name>"   # e.g. "Total gallons" for a SUM measure
    - name: rank
    table:
      table_columns:
      - column_id: <dimension display name>
        show_headline: false
      - column_id: "<aggregated measure display name>"
        show_headline: false
      - column_id: rank
        show_headline: false
      ordered_column_ids:
      - <dimension display name>
      - rank
      - "<aggregated measure display name>"
      client_state: ""
    display_mode: TABLE_MODE
  worksheet:
    id: "<model display name>"
    name: "<model display name>"
    obj_id: "<model obj_id>"
  config:
    cohort_type: ADVANCED
    anchor_column_id: <dimension display name>
    return_column_id: <dimension display name>
    cohort_grouping_type: COLUMN_BASED
    hide_excluded_query_values: true
    group_excluded_query_values: "Excluded values"
    pass_thru_filter:
      accept_all: false
```

Key rules:
- **Parameter prerequisite (dynamic form)** — the `count` parameter MUST be on the model first
  (already migrated via the Parameters datasource → `model.parameters[]`). The set's
  `formula_filter` references it as `[<model display name>_1::<paramName>]`. **Import order:
  model (with param) → cohort.** (The static form below has no parameter dependency.)
- **Top vs Bottom** — `end='top'` → `rank(sum(measure), 'desc')`; `end='bottom'` →
  `rank(sum(measure), 'asc')` (user-confirmed 2026-06-12).
- Rank aggregation = the set's `order` expression aggregation (SUM here). Translate the
  ordering measure to its TS column; if it's a derived/conditional field, use the plain
  measure + **flag** the dropped nuance for review.
- `table_paths` alias = `<model display name>_1`; all `formulas[].expr` column refs use
  `[<alias>::<col>]`. `answer_columns`, `config`, and `table.*` use **display names** (no alias).
- `answer_columns` measure entry uses the **aggregated display name** ThoughtSpot generates
  (`Total <measure>` for a SUM measure, e.g. `Total gallons`).
- A **stepped range parameter** (Tableau `<range granularity='5' min='5' max='25'/>`) maps
  to `list_config` (enumerate min→max by step: `[5,10,15,20,25]`), NOT `range_config`. See
  the Parameter migration section for this rule.
- Bind via `worksheet:` (id/name/obj_id) — NOT `model:` (same rule as column sets).
- No top-level `guid` on first import.
- File: `<SetName>.cohort.tml` → `/tmp/ts_tableau_mig/output/{workbook_name}/`.

**Static form (fixed N — literal `count`):** no formulas, no parameter; the `top N`/`bottom N`
keyword `search_query` defines membership. Use this when the Tableau set's `count` is a literal.

```yaml
# guid omitted on first import
cohort:
  name: "<set caption>"
  answer:
    tables:
    - id: "<model display name>"
      name: "<model display name>"
      obj_id: "<model obj_id>"
    search_query: "top 10 [<dimension>] [<measure>]"   # anchor dimension FIRST, then measure; "bottom 10 …" for Bottom-N; N is the literal count
    answer_columns:
    - name: <dimension display name>
    - name: "<aggregated measure display name>"         # e.g. "Total gallons"
    table:
      table_columns:
      - column_id: <dimension display name>
        show_headline: false
      - column_id: "<aggregated measure display name>"
        show_headline: false
      ordered_column_ids:
      - <dimension display name>
      - "<aggregated measure display name>"
      client_state: ""
    display_mode: TABLE_MODE
  worksheet:
    id: "<model display name>"
    name: "<model display name>"
    obj_id: "<model obj_id>"
  config:
    cohort_type: ADVANCED
    anchor_column_id: <dimension display name>
    return_column_id: <dimension display name>
    cohort_grouping_type: COLUMN_BASED
    hide_excluded_query_values: false       # false = show a remainder bucket (label below); true = hide non-members
    group_excluded_query_values: "Others"   # label for the non-member remainder bucket
    pass_thru_filter:
      accept_all: false
```
> Live-verified 2026-06-12 against se-thoughtspot (set "Static Top 10" on model
> `TEST_SV_DMSI_AI_CONTEXT`). The `top N [dimension] [measure]` keyword `search_query` (**anchor
> dimension first, then measure**) is the correct representation for a fixed-N query set — no
> formulas, no parameter. `hide_excluded_query_values` is a display choice: `false` keeps a
> remainder bucket (labelled by `group_excluded_query_values`, e.g. "Others"); `true` hides
> non-members.

### 5c. SQL View TML — one per custom SQL relation

For each custom SQL relation identified in Step 3b (those with `source_type: "custom-sql"`),
generate a `.sql_view.tml` file. Follow the rules in `tableau-tml-rules.md` "SQL View
TML Rules" and the full schema in `thoughtspot-sql-view-tml.md`.

**Template:**

```yaml
sql_view:
  name: "Datasource Custom SQL"
  connection:
    name: "Connection Display Name"
  sql_query: |
    SELECT col1, col2, col3
    FROM catalog.schema.table_name
    WHERE condition = 'value'
  sql_view_columns:
  - name: COL1
    sql_output_column: col1
    data_type: VARCHAR
    properties:
      column_type: ATTRIBUTE
  - name: COL2
    sql_output_column: col2
    data_type: DOUBLE
    properties:
      column_type: MEASURE
      aggregation: SUM
```

Key rules:
- `connection.name` is **required** — use `{connection_name}` from Step 4.5
- `sql_query` contains the full SQL text from the Tableau `<relation>` element (decode
  HTML entities)
- `sql_output_column` must match a column name or alias from the SQL query output
- Map Tableau column datatypes to ThoughtSpot types using the same mapping as table TMLs
- No `db`, `schema`, `db_table`, or `db_column_properties` fields
- File extension: `*.sql_view.tml`

Write each file to `/tmp/ts_tableau_mig/output/{workbook_name}/{Name}.sql_view.tml`.

The model TML (Step 5b) references these SQL Views by name in `model_tables[]`, just
like regular tables.

---

## Step 5.5 — Spotter Enablement

> **Scope gate:** runs for scopes 1, 2, 4. **Skip for scope 3** (model already exists)
> and **scope 5** (no model generated).

Before validating, confirm whether Spotter (AI search) should be enabled for each model
— the same step `ts-convert-from-snowflake-sv` and `ts-convert-from-databricks-mv` run.
Spotter is the primary natural-language interface for a Model, and a migrated workbook
almost always exists to be queried this way, so the default is **yes**.

```
Enable Spotter (AI search) for this model? [Y / n] (default: Y)
```

Write the answer into the model TML `properties` block (see the Step 5b template):

```yaml
model:
  properties:
    spotter_config:
      is_spotter_enabled: true   # or false if the user declines
```

On an in-place update of an existing model, preserve its current setting unless the user
asks to change it. Default new models to enabled.

---

## Step 6 — Validate and import TMLs

`ts tml import`/`ts tml lint` read a directory of TML files directly via `--dir`, ordered
tables first, then SQL views, then models (so a model's tables are validated alongside
it), via `--order tableau`. **Base model selection:** GENERATE mode (Step 5b) writes
phased files `{slug}.phase0.model.tml`, `{slug}.phase1.model.tml`, … — this pre-import
validation only wants the base, so pass `--model-phase base` to drop every
`*.phase1.model.tml`+ file (unused by this skill) while keeping bare `*.model.tml`
(hand-assembled, blend-merged) and `*.phase0.model.tml` (GENERATE-mode base):

#### Pre-import validation gate (`ts tml lint` — I1 / I2 / I4 / I5 / I8)

Before running `ts tml import`, lint the generated TMLs with **`ts tml lint`** — a
parser-based check of the hard invariants in
[`../../shared/schemas/ts-model-conversion-invariants.md`](../../shared/schemas/ts-model-conversion-invariants.md)
that `--policy VALIDATE_ONLY` does **not** catch (ThoughtSpot accepts the TML and then
behaves wrong, or rejects it on import):

- **I1** — every `formulas[]` entry has a paired `columns[]` entry (`formula_id:` == `id:`). *(Unpaired formula silently dropped.)*
- **I2** — no `aggregation:` inside any `formulas[]` entry. *(Raises "FORMULA is not a valid aggregation type".)*
- **I4** — every `model_tables[]` `id:` (when present) equals its `name:`. *(Mismatch makes joins silently fail.)*
- **I5** — no physical-column `aggregation: COUNT_DISTINCT`; use a `unique count ( [TABLE::col] )` formula. *(Silently flips MEASURE → ATTRIBUTE.)*
- **I8** — no duplicate `column_id` across `columns[]`. *(Hard import rejection: "columns should have unique column_id values".)*

`ts tml lint` reads the same `--dir`/`--order`/`--model-phase` input as `ts tml import`
and exits non-zero on any finding, so it gates the import:

```bash
ts tml lint --dir /tmp/ts_tableau_mig/output/{workbook_name} --order tableau --model-phase base
```

Do not import until it reports `"clean": true`. Fix any finding and re-lint.

Validate (up to 10 fix cycles). `--policy VALIDATE_ONLY` checks without persisting:

```bash
ts tml import --dir /tmp/ts_tableau_mig/output/{workbook_name} \
  --order tableau --model-phase base --policy VALIDATE_ONLY --profile {profile_name}
```

For each cycle:

1. Parse the validation response. Each element has a `status.status_code` of `OK`,
   `WARNING`, or `ERROR`. Only `ERROR` blocks; `WARNING` does not.
2. **Expected WARNING (ignore):** `Table with id null not found. Matching with
   db/schema/dbTable` with `status_code: WARNING`. A freshly generated table TML has no
   GUID, so ThoughtSpot matches it by db/schema/dbTable instead — this is normal for a
   new table and is not a problem. (Note: a *clean* binding still shows this warning; it
   does not mean the connection failed.)
3. **Real ERRORs to fix:** `connection not found` (wrong `connection.name`/case) and
   `column not found in connection` (the connection doesn't expose that `db_table`/column)
   are genuine `ERROR`s — the table won't bind. Fix the name or the column mapping.
4. For any other **errors**, identify the affected TML file and the specific issue. Apply
   the fix from the error table in `tableau-tml-rules.md`.
5. Rewrite the affected TML file in place.
6. Re-validate.

After 10 cycles with remaining errors, stop and report to the user:
- Errors that persist after all retries
- Which fix was attempted for each
- Ask whether to proceed with import anyway or make manual corrections

---

## Step 7 — Review Checkpoint & Import

> **Scope gate:** runs for scopes 1, 2, 4. **Skip for scope 3** (model already exists)
> and **scope 5** (no model — tables imported in Step 6 only).

Before importing, show the user a review summary — the same convention the
`ts-convert-from-snowflake-sv` and `ts-convert-from-databricks-mv` skills use. The user
should see exactly how every calculated field was translated, and what (if anything)
will **not** migrate, *before* committing — not discover omissions only in the Step 12
report afterward. Source each formula's `tier`/`level`/`complexity` from the same
`ts tableau classify-formulas` output Step A3 uses — never re-derive tiers by hand.
Step 7 reviews **one model (one datasource) at a time**, so:
- **Reusing the Step A3 audit run** (`{workbook_name}_classification.json`): that file is
  **per datasource** — read the `datasources[]` entry whose `name` matches the datasource
  you're importing, and use *its* `formulas[]`/`tier_counts` (not the top-level workbook
  totals).
- **Generating it now** from the `classification.json` already built for Step 5b's
  `translate-formulas` call (a **bare list** for this one datasource — the classifier
  accepts either shape) yields a flat `{formulas, tier_counts, translate_stats}`:

```bash
ts tableau classify-formulas --input {workdir}/classification.json --output {workdir}/classification_tiers.json
```

```
Ready to import to {base_url}:

Tables:
  ✓ {TABLE_NAME}   → create new on connection "{connection_name}"
  ↺ {TABLE_NAME}   → reuse existing object (GUID {guid})        # if Step 4.5 reuse
  …

Model: {datasource_name}
  Columns: {n} total — {a} attribute(s), {m} measure(s), {f} formula(s)
  Parameters: {p}  ({names or "none"})
  Spotter (AI search): enabled / disabled   # from Step 5.5

Formula translations ({F} total):
  ✓ {name}  [{tier}]:        {tableau_expr}  →  {ts_expr}
  ⚙ {name}  [pass-through]:   {tableau_expr}  →  {sql_*_op expr}
       (works only with SQL Passthrough Functions enabled in ThoughtSpot admin)
  ⚠ {name}  [untranslatable]: OMITTED — {reason}

Sets ({S}) — semantic reinterpretations, REVIEW each matches intent:   # omit section if no sets
  ✓ {name} → column set ({GROUP_BASED, N members | NE except | {Null} | formula-col anchor})  [what to verify]
  ✓ {name} → query set (rank {desc|asc} by SUM {measure}, N={param|literal})   [verify ranking + N]
  ⚙ {name} → interactive filter on {anchor} (set control; IF-[Set] calcs collapsed to measure+filter)
  ⊘ {name} → DEFERRED ({intersect/computed except 2c | set action}) — manual

Will NOT migrate ({K}):
  - {name}: {reason}
  # if none: "Nothing omitted — full coverage."

Dashboards: {N}  (liveboard migration offered after import)

Blended models: {N} model(s) merged from {M} datasources via data blending
  - {primary_ds} ← {secondary_ds} on [{col1}, {col2}]  (LEFT_OUTER, {cardinality})

  ⚠ HIGH-risk blend(s): {N}  (both sides have measures — fact×fact)
    {primary} ← {secondary}: Tableau aggregates {secondary} to {link_cols} grain
    before joining. ThoughtSpot joins at row level — aggregation may diverge.
    Options:
      R — proceed with row-level join (ThoughtSpot chasm trap may handle it)
      S — create a SQL View that pre-aggregates the secondary to the linking grain
      M — keep as separate models (no blend merge)

Proceed?
  yes   — import the table + model TMLs
  no    — cancel
  file  — write the TMLs to /tmp/ts_tableau_mig/output/{workbook_name}/ without importing
```

Tiers are the Step A3 set: Native, LOD, Cumulative, Moving, Pass-through, Row-offset
(native), Row-offset (pass-through), Parameter ref, Untranslatable. Show `⚠ … OMITTED`
for every untranslatable formula (and its dropped `columns[]` entry), `⚙ … pass-through`
for every formula needing SQL Passthrough (SIZE pass-through only — LAG/LEAD/FIRST/LAST/INDEX
now use native TS functions), and `↻ … row-offset (native)` for row-offset formulas
translated to native functions (`moving_sum`, `first_value`, `last_value`, `rank`) — so
the un-migratable and caveated items are flagged here, up front, for the user to weigh.
**Always include the Sets section when the workbook has sets** (per the MANDATORY set-review
rule in Step 5b) — set conversions are semantic reinterpretations, so the user must confirm
each matches intent before import.

Reviewer checks before import:
- Every translated division has a div-by-zero guard (FT "Division-by-zero" section)

**Row-offset table calculations.** For each formula classified as Row-offset (native or
pass-through), display:
- The original Tableau formula
- The resolved sort column and how it was determined (from `<table-calc>` `ordering_type`/
  `ordering_field`, or from worksheet shelf)
- The ThoughtSpot translation (native `rank()` or answer-level `sql_*_aggregate_op`)
- For pass-throughs: the full SQL template with the resolved column names filled in

Ask the user to confirm the sort resolution is correct before proceeding to import.
If any sort resolution looks wrong, the user can override it or choose to omit that
formula instead.

Wait for confirmation. **no** cancels. **file** writes the TMLs and skips to Step 12
(report only, no import). **yes** imports using the two-phase approach below.

### Two-phase import (recommended)

Import in two phases so formula errors never block the base model. See
[`../../shared/mappings/tableau/tableau-tml-rules.md`](../../shared/mappings/tableau/tableau-tml-rules.md)
"Two-phase model import" for the rationale.

**Phase 1 — Base model (no formulas):**

Build the model TML with `model_tables[]`, physical `columns[]`, `joins[]`, and
`parameters[]` only. **No `formulas[]` section and no formula `columns[]` entries.**
This is guaranteed to succeed if the table TMLs bind correctly to the connection. For a
GENERATE-mode model (Step 5b), this is exactly the `*.phase0.model.tml` file — it already
has no formulas. For a blend-merged model, it's the hand-assembled `.model.tml` file.

The Phase 1 payload is tables + sql_views + base model + cohorts, in that order —
`--order tableau --model-phase base` selects **only** `*.phase0.model.tml` from
GENERATE-mode output (the `.phase1+` files are cumulative formula layers not used by
this skill; Phase 2 below re-derives formulas independently) and passes blend-merged
`.model.tml` files (no "phase" in the name) through unaffected.

**Before importing, check for duplicates** — if Phase 1 has already been imported (e.g.
from a retry or previous attempt), search for existing models by name before importing.
If a duplicate exists, delete it with `ts metadata delete` before proceeding, or pin its
GUID and import with `--no-create-new` to update in place.

Import with `--create-new`:

```bash
ts tml import --dir /tmp/ts_tableau_mig/output/{workbook_name} \
  --order tableau --model-phase base --policy ALL_OR_NONE --create-new --profile {profile_name}
```

Parse the response. Extract the GUID for each imported object. **Capture the model GUID
from the Phase 1 import response** (`response.object[0].header.id_guid`) — this is
required for Phase 2 (`--existing-guid`). If the import response does not include a GUID
(e.g. update case), search for the model:

```bash
ts metadata search --type LOGICAL_TABLE --name '{model_name}' --profile {profile_name}
```

Save the GUID as `{model_guid}`.

On failure, fix the table/connection errors and retry — Phase 1 errors are always
structural (wrong connection name, missing column), never formula syntax.

**Phase 1.5 — Base model review checkpoint:**

After Phase 1 succeeds, pause and let the user verify the base model before adding
formulas. This catches structural issues (wrong table bindings, missing columns, broken
joins) before they compound into Phase 2 retry cycles:

```
Base model imported: {model_name}
  {base_url}/#/data/tables/{model_guid}

  Tables:     {N} bound to connection "{connection_name}"
  Columns:    {N} physical columns ({a} attribute, {m} measure)
  Joins:      {N}
  Parameters: {names or "none"}

  Please verify in ThoughtSpot:
    1. Open the model link above
    2. Check that all tables show data (no "table not found" errors)
    3. Confirm column types look correct (especially date columns)
    4. If joins exist, try a search spanning two tables

  Ready to add {F} translated formulas (Phase 2)?
    yes    — proceed to formula import
    search — try some searches first (suggest test questions)
    no     — stop here; model is ready for manual formula work
```

If the user chooses **search**, suggest 3 natural-language test questions grounded in the
model's physical columns (no formulas yet). After testing, re-prompt yes/no.

**Phase 2 — Add formulas via `build-model`:**

After the user confirms the base model, add all translated formulas in one CLI call.
`build-model` parses the TWB directly — do not prepare intermediate files
(`classification.json`, `table_columns.json`, `parameters.json`, `calc_id_map.json`)
for it. Those files are inputs to `ts tableau translate-formulas` (Step 5b), not to
`build-model`.

**The `--datasource` value must match the full datasource name as shown in the TWB parse
output, including any `| Project : ...` suffix** (e.g.
`"cpg_merch_promotion_prod | Project : Production Data Sources"`, not just
`"cpg_merch_promotion_prod"`). The TWB parse (Step 3) reports the full name.

```bash
ts tableau build-model {workdir}/{workbook}.twb \
  --existing-guid {model_guid} \
  --profile {profile_name} \
  --datasource "{datasource_name}" \
  --output-dir {workdir}/output
```

This command runs the full formula pipeline internally:
1. Re-parses the TWB to extract calculated fields and parameters
2. Translates all formulas through the 14-transform pipeline
3. Runs `validate_pre_import()` — reports warnings for IN-with-parens, non-existent
   functions (`add_quarters`/`add_years`), bare date literals, unbalanced parens/brackets,
   missing else clauses, and other structural issues
4. Applies `formula_` prefix for cross-references (resolves the I9 invariant)
5. Detects and fixes double aggregation (`sum([formula_X])` where X is already aggregated)
6. Filters unresolvable references (sqlproxy, bare column refs, unconverted concat)
7. Merges new formulas into the existing model (skips formulas already present)
8. Imports with up to 25 (CLI default, `--max-retries`) retry cycles, dropping failing formulas on each retry

Parse the JSON output to report results to the user:

```
{
  "formulas_translated": N,
  "formulas_skipped": N,
  "formulas_filtered": N,
  "formulas_added": N,
  "formulas_skipped_existing": N,
  "formulas_dropped_on_import": [
    {
      "name": "Formula Name",
      "expr": "attempted ThoughtSpot expression",
      "error": "ThoughtSpot error message",
      "original_tableau": "raw Tableau expression"
    }
  ],
  "validation_warnings": [...],
  "updated_model_guid": "guid",
  "import_status": "OK"
}
```

**If `formulas_dropped_on_import` is empty (or absent):** Report success. Proceed to
Step 7.5 regardless of migration pace.

**If `formulas_dropped_on_import` is non-empty — behaviour depends on `{migration_pace}`:**

### Fast mode (`{migration_pace}` = `F`)

Report the parked count and a summary table, then move on:

```
Phase 2 complete:
  ✅ {formulas_added} formulas imported successfully
  ⏸ {len(dropped)} formulas parked (will appear in final report)

Parked formulas:
  | # | Name | Error (summary) |
  |---|------|-----------------|
  | 1 | {name} | {error truncated to ~60 chars} |

These are recorded for the migration report. You can attempt fixes
after the migration is complete (Step 12.5).

Proceeding to model confirmation...
```

Save `{parked_formulas}` (the full list of dicts from `formulas_dropped_on_import`)
for use in Steps 12 and 12.5.

### Complete mode (`{migration_pace}` = `C`)

Enter the **formula fix cycle** — a bounded loop that attempts to fix and re-import
each dropped formula:

**Caps:**
- Max formulas to attempt: **15** (if more are dropped, park the rest)
- Max attempts per formula: **3**

**Process (in dependency order — level-0 formulas first):**

For each dropped formula (up to 15):

1. **Analyze the error** — read the `error` and `expr` fields from the dropped dict
2. **Determine if fixable:**
   - Skip if the error references another parked formula (dependency chain — fix the
     dependency first, then retry this one)
   - Skip if the error indicates a missing table/column in the model (structural issue,
     not an expression fix)
3. **Attempt a fix:**
   - Rewrite the expression based on the error (e.g. parenthesise, fix function name,
     add `TABLE::` qualifier, wrap date literal in `to_date()`)
   - Export the current model: `ts tml export {model_guid} --profile {profile_name} --parse`
   - Add the fixed formula as a new `formulas[]` entry with matching `columns[]` entry
   - Import: `ts tml import --profile {profile_name} --policy ALL_OR_NONE` (with `guid` pinned)
   - On success: formula is now ✅ Migrated; remove from parked list
   - On failure: record the new error; decrement attempt counter; try a different fix
   - After 3 failures: mark as ⏸ Parked (exhausted)

4. **After fixing level-0 formulas**, retry level-1+ formulas whose dependencies are
   now imported (they may succeed without expression changes)

Report after the fix cycle:

```
Fix cycle complete:
  ✅ {fixed_count}/{total_attempted} formulas fixed and imported
  ⏸ {remaining_parked} formulas remain parked

Fixed:
  - {name1}: {what was changed}

Still parked:
  - {name2}: {error after last attempt}
```

Save `{parked_formulas}` (the remaining parked list) for Steps 12 and 12.5.

---

Report validation warnings regardless of pace:
- If `validation_warnings` is non-empty: surface warnings — these indicate formulas
  that may have syntax issues but were still attempted

Do **not** manually assemble TML, write Python scripts to add formulas, or call
`ts tml import` directly for Phase 2. The `build-model --existing-guid` command
handles translation, prefix, validation, merge, and retry internally.

> **Updating something that already exists.** If Step 4.5 found an existing object, or a
> first import already created one and you need to re-import (e.g. to set Spotter, fix a
> column type), do **not** re-run with `--create-new`. **Pin the object's `guid` at the TML
> root and import with `--no-create-new`** — this is true for **tables, models, AND
> liveboards alike**. Re-importing *without* the root `guid` does **not** reliably update in
> place: it can create a **duplicate** with a new GUID (observed on tables — a re-import
> without `guid` churned the table's identity and left an orphan), even though the object
> "matches" by name/db/schema. **Always** capture the `id_guid` from the first import, write
> it back into the TML root, and re-import with `--no-create-new`. Verify the returned
> `id_guid` matches; a new GUID means you just made a duplicate — delete the orphan.

Save the imported GUIDs internally as `{datasource_guids}` and `{table_guids}` — these
are used by Step 10 if the user proceeds with dashboard migration. Also save
`{formula_column_map}` (Tableau calc field caption → ThoughtSpot formula display name)
and `{parameter_map}` from the TWB parse.

> **A requested `obj_id` on a fresh model is NOT honored — read back the REAL one.** When
> you import a brand-new model, ThoughtSpot **ignores** any `obj_id` you put in the TML and
> assigns its own, derived as `{Model-Name-with-dashes}-{guid8}` (e.g. requested
> `P1UKBankCustomers-bankdemo1` became `P1-UK-Bank-Customers-49347340`). **Never reuse the
> obj_id you wrote into the TML for downstream references** — capture the model's *actual*
> `obj_id` after import and use only that for:
> - every liveboard viz `answer.tables[].obj_id` (Step 10c) — a wrong obj_id makes **every
>   tile fail to bind** (`"No table with object_id … found"`), forcing a delete + re-import;
> - the cohort `worksheet.obj_id` (Step 5b) — cohort binding is more lenient (it may resolve
>   by name and still import), but use the real obj_id anyway for correctness.
>
> Capture it from any of these (cheapest first): the **import response header** `objId`;
> `ts metadata search --guid {model_guid}` → `metadata_obj_id`; or the model export
> (Step 10-pre). Save it as `{model_obj_id}`. Doing this **once, up front** (Step 10-pre,
> alongside the parameter UUIDs) is the single biggest speed win — it removes the
> build→fail→delete→re-import liveboard cycle entirely.

Save the model's real `{model_obj_id}` now (read it from the import response `objId`).

---

## Step 7.5 — Confirm the Model (before any liveboards)

> **Scope gate:** runs for scopes 1, 2, 4. **Skip for scope 3** and **scope 5**.

Pause and have the user verify the model is correct **before** building liveboards on it.
Every liveboard viz references this model's columns and formulas, so a wrong model means
re-doing every tile — far cheaper to catch it here. (Do this even when there are no
dashboards — a verified model is the deliverable either way.)

Present a confirmation summary and wait:

```
Model imported: {model_name}
  {base_url}/#/data/tables/{model_guid}

  Tables:     {table list}
  Columns:    {N} — {a} attribute, {m} measure, {f} formula
  Parameters: {names + type}            (or "none")
  Spotter:    enabled / disabled

  Translated formulas — please sanity-check:
    {name}: {ts_expr}
    ...
  Omitted (untranslatable): {names}     (or "none")

  Try these in Search/Spotter to confirm it behaves:
    - "{suggested NL question 1}"
    - "{suggested NL question 2}"
    - "{suggested NL question 3}"

Does the model look correct? (yes → continue / describe changes)
```

Suggest 3–5 natural-language test questions grounded in the model's actual columns and
formulas (mirrors the snowflake/databricks skills). If the user asks for changes, edit the
model TML and **re-import in place** — include the model's `guid` at the document root and
import with `--no-create-new` (a model has no natural key, so omitting the root `guid`
creates a duplicate; see Step 7). Re-confirm, then proceed. Do not start Step 8 until the
user confirms the model.

---

## Step 8 — Migrate Dashboards?

**Scope gate:** if the user chose **scope 2 (Tables + Models only)**, **scope 4 (Models
only)**, or **scope 5 (Tables only)** in Step 1.5, skip this entire step and Steps 9–11 —
go straight to **Step 11.5** (coverage, scopes 2/4) then **Step 12**. In **scope 3
(Liveboards only)** this step is the entry point (the model came from Step 1.5a); the
liveboard tiles reference that model's columns (Step 10-pre export).

If Step 3d found zero `<dashboard>` elements, skip to **Step 11.5** (a model-only workbook
still benefits from coverage answers), then Step 12.

Otherwise (scope 1 or 3 with dashboards), present the decision:

```
The workbook contains {N} dashboard(s):
  - {dashboard_name_1}
  - {dashboard_name_2}
  ...

Would you like to migrate these to ThoughtSpot Liveboards?
This maps Tableau dashboard layout to a 12-column grid with chart and note tiles.

  Y  Yes — migrate dashboards to liveboards
  N  No  — skip to summary

Enter Y / N:
```

If **N**, skip to Step 12.

**When there are 2+ dashboards, also ask how to package them:**

```
This workbook has {N} dashboards. Create:
  S  Separate liveboards — one per dashboard
  T  A single liveboard with one tab per dashboard   (+ the Migration Summary tab)

Enter S / T:
```

ThoughtSpot liveboards support `layout.tabs[]`, so **T** puts each dashboard on its own tab
in one liveboard (often tidier for a related set), while **S** keeps them independent. Either
way, add the Step 10g Migration Summary as a final tab.

---

## Step 9 — Parse Dashboard Layout and Map to Grid

### 9a. Zone extraction

For each `<dashboard>` element in the TWB, walk `<zones>` → `<zone>` elements
recursively. For each leaf zone, extract:

| Field | Source |
|---|---|
| `zone_id` | `id` attribute |
| `zone_type` | `type` attribute (`text`, `title`, `viz`, `bitmap`, `web`, `extension`, `metric`) |
| `worksheet_name` | `name` attribute (for `viz` zones) |
| `x`, `y`, `w`, `h` | `x`, `y`, `w`, `h` attributes (Tableau uses 0–100,000 coordinate space) |
| `text_content` | `<formatted-text>` child text (for `text` / `title` zones) |

Classify each zone:
- **Chart zones**: a worksheet viz — a leaf zone carrying a `name` (worksheet name) and no
  more specific sub-type. These become visualization tiles.
- **Text/title zones**: `type="text"` or `type="title"` → becomes a note tile (Step 10c).
- **Skip**: `type="bitmap"` (images), `type="web"`, `type="extension"`, `type="metric"`,
  `type="filter"` (quick filters — handled via liveboard `filters[]`, not as tiles),
  `type="paramctrl"` (parameter controls — the migrated model `parameters[]` cover these),
  `type="color"`/`type="legend"` (legend zones — ThoughtSpot draws its own),
  `type="flipboard"`/`type="flipboard-nav"` (Tableau Story-style flipboards — no ThoughtSpot
  liveboard equivalent). **Before skipping a flipboard/story dashboard, salvage its content:**
  a flipboard usually re-presents worksheets already migrated from another dashboard (check —
  it may reference **no unique worksheets**), but it often carries **narrative captions**
  (analyst commentary). Migrate any unique worksheets as vizzes and preserve the narrative
  text as **note tiles** rather than losing it; only the flip *interaction* itself is dropped.
  A single
  worksheet often emits several zones (the viz plus its color/filter companions); keep the
  viz zone, drop the companions, and de-duplicate by worksheet name.

### 9b. Worksheet shelf data

For each chart zone's `worksheet_name`, find the corresponding `<worksheet>` element
in the TWB. Extract:
- Columns shelf (`<datasource-dependencies>` → `<column>` with shelf `column`)
- Rows shelf → shelf `row`
- Mark type: `<mark class="{type}">` (bar, line, circle/scatter, square, text, pie)
- Color encoding: column on `color` shelf
- Size encoding: column on `size` shelf
- Aggregation: from column `caption` prefix (`SUM(...)`, `AVG(...)`, etc.)

### 9c. Map coordinates to ThoughtSpot 12-column grid

ThoughtSpot liveboards use a **12-column responsive grid**. Tableau dashboards use
absolute pixel coordinates (0–100,000 range).

Use a band-based approach:

1. **Group zones by y-band** — zones within 2,000 units of each other vertically are
   in the same row band.
2. **Sort bands** from smallest y to largest y (top to bottom).
3. **Within each band**, sort zones by x (left to right).
4. **Assign columns**: divide 12 columns proportionally by each zone's `w` relative to
   the total dashboard width. Round to nearest integer; ensure columns sum to 12.
5. **Assign height**: convert Tableau `h` to ThoughtSpot height units (1 unit ≈ 1/20th
   of the dashboard height; minimum 4 units).
6. **Assign y position**: start from 0; each new row band starts at the bottom of the
   previous band.

Save the grid layout as a list of tiles with `zone_id`, `zone_type`, `worksheet_name`,
`col`, `col_span`, `row_span`, `y`.

### 9d. Orphan worksheets — surface and prompt to include

A workbook often contains worksheets that aren't placed on **any** dashboard being migrated.
By default they produce no tile — but the author built them for a reason, and the model fully
supports them, so the user should **decide**, not have them silently dropped (surface →
recommend → resolve).

1. **Detect.** Compute the set of worksheets referenced by the dashboard(s) being migrated
   (the `name` on each chart zone). Any `<worksheet>` in the TWB not in that set is an orphan.
2. **Describe each.** Read the orphan's shelves (as in 9b) and state, in one line, **what it
   shows** and its **ThoughtSpot equivalent** — not just the name. E.g.
   *"`Attrition Yes/No Count` — pie of headcount split by Attrition (Yes/No) → PIE
   `[Attrition] [Total Employee Count]`."* A bare name leaves the user unable to choose.
3. **Recommend.** Say whether each looks worth adding (a meaningful, distinct view) or is
   likely a draft/superseded by a tile already on the dashboard.
4. **Prompt** (per the references — ask, don't assume). Offer: add **all**, add a **subset**
   (name which), or **none**. For any the user picks, build them as additional tiles in Step 10
   (same chart-type resolution, theming, and grid placement as dashboarded vizzes) and append
   them after the dashboard's own tiles.
5. **Record the outcome** in the Migration Summary (Step 10g): which orphans existed, which
   were added, which were left off (and that the model still supports them via Spotter).

**This is a MUST-ASK step — never skip the prompt or decide on the user's behalf.** Orphans
frequently include an overall-rate or breakdown view the author drafted but forgot to place.
Even when the dashboard looks complete, the user may want the extra coverage. When
recommending, default to **"add as tiles"** for orphans that represent a distinct, useful
view (a different aggregation, a different dimension breakdown) — the user can always decline.

---

## Step 10 — Generate Liveboard TML

### 10-pre. Export model — capture obj_id, parameters, and resolved column names (BEFORE generating TML)

**Do this first, before writing any liveboard YAML.** One export of each model referenced by
the liveboard gives you everything the tiles need — do it once and reuse:

```bash
source ~/.zshenv && ts tml export {model_guid} --profile {profile_name}
```

From the export (and/or `ts metadata search --guid {model_guid}`) record:
- **`obj_id`** — the model's **real** `obj_id` (the export root / `metadata_obj_id`). Save as
  `{model_obj_id}` and use it for **every** liveboard viz `answer.tables[].obj_id`. **Do NOT
  use the obj_id you wrote into the model TML** — a fresh model's requested obj_id is
  reassigned by ThoughtSpot, and a stale ref makes every tile fail to bind (see the obj_id
  rule in Step 7). This is the fix for the build→fail→delete→re-import cycle.
- `parameters[]` — for each, `name` (display name) and `id` (the UUID ThoughtSpot assigned,
  needed for `parameter_overrides[].key` in Step 10f). **If you skip this, Step 10f cannot be
  completed** — the UUIDs aren't in the TWB or the import response.
- column + formula **display names** — the exact names tiles must reference (and, in scope 3,
  the only columns available; map TWB shelf fields to these and surface any with no match).

(In **scope 3 / Liveboards only**, the model already exists from Step 1.5a — this export is
the single source of its obj_id, columns, formulas, and parameter UUIDs.)

### 10-charts. Choose the charting library (ask once)

Before resolving chart types, ask the user which charting library to target — **default
Legacy**:

```
Which charting library should the liveboard use?
  L  Legacy charts — portable, work on every cluster                           (default)
  M  Muze charts (new charting library) — early access; the target cluster
     must have it enabled (e.g. SE). Closer to Tableau's shelves (Color →
     slice-with-color, small multiples → trellis-by) for a more faithful migration.

Enter L / M:
```

- **L (Legacy, default):** emit the legacy chart types with `chart.axis_configs`
  (the rest of Step 10 as written).
- **M (Muze):** for **cartesian/pivot** intents (bar, column, line, area, their stacked
  forms, line+column combos, pivot) emit the `ADVANCED_*` type with `chart.custom_chart_config`
  (shelf model: `x-axis` / `y-axis` / `slice-with-color` / `trellis-by`); **fall back to the
  Legacy type** for every other intent (pie, scatter/bubble, heatmap, treemap, sankey,
  funnel, waterfall, pareto, spider, geo, KPI). Map a Tableau **Color** encoding →
  `slice-with-color` and **small multiples** → `trellis-by`. Never put `custom_chart_config`
  on a Legacy type (import fails). See
  [`../../shared/schemas/thoughtspot-chart-types.md`](../../shared/schemas/thoughtspot-chart-types.md)
  "New charting library" for the verified shelf spec and rules.

### 10a. Resolve chart types

**Default to CHART_MODE with the closest chart type — TABLE_MODE is a last resort.**
Only use `TABLE_MODE` for explicit crosstabs (Tableau `text` mark class) or when there
is genuinely no chart type that can render the data. For untranslatable visualizations
(k-means cluster, forecast), build a **CHART_MODE placeholder** with the most representative
type (SCATTER for cluster inputs, LINE for forecast historical trend) and flag for review
in the description — never fall back to TABLE_MODE as a lazy alternative.

| Tableau mark class / zone | ThoughtSpot `chart.type` |
|---|---|
| `bar` | `BAR` |
| `line` | `LINE` |
| `circle` / `point` | `SCATTER` |
| `square` | `BAR` |
| `pie` | `PIE` |
| `area` | `AREA` |
| `text` (crosstab) | `TABLE` (display_mode `TABLE_MODE`) |
| Map (lat/long generated + geo role) | `GEO_BUBBLE` (or `GEO_AREA` for a filled/choropleth map) |
| "Measure Names / Measure Values" KPI block | `KPI` — **one tile per measure** (see KPI rule below) |

For the **authoritative `answer.chart.type` enum (44 valid values)**, per-type shelf shapes,
the geo/candlestick caveats, and a full **analytical-intent → chart-type** mapping (for
choosing a better chart than the source used), see
[`../../shared/schemas/thoughtspot-chart-types.md`](../../shared/schemas/thoughtspot-chart-types.md).
`GAUGE` is **not** a valid type, and one invalid enum value fails the whole import — validate
the type before importing.

**KPI rule.** A Tableau scorecard/KPI worksheet (Measure Names + Measure Values, no
dimension) maps poorly to a single tile. Emit **one KPI viz per measure** — that's the
idiomatic ThoughtSpot KPI (headline + sparkline + period-over-period). **ALWAYS include a date
when the model has one** — this applies to *every* KPI tile (not just measure blocks), and is
easy to forget. Date selection: **0 date fields → static KPI (measure only); exactly 1 →
include it automatically; 2+ → ask the user which.** Use the data's grain (`[Date].yearly`
for annual data, `[Date].monthly` otherwise) — the default is monthly, so set `.yearly`
explicitly for annual sources. So a "count of sectors" KPI in a workbook with a `Fiscal Year`
column is `[Total Sectors] [Fiscal Year].yearly`, **not** a bare `[Total Sectors]`.

For the trend/sparkline to actually render, three things are required:

1. The date must be in **both** `chart_columns` and on axis **`x`**, with the measure on `y`
2. A `table:` block with `table_columns` and `ordered_column_ids`
3. **`client_state_v2` on the `chart:` block** with `showSparkline: true` in the
   `kpiColumnProperties` — without this, the KPI renders as a plain number with no trend line

See `thoughtspot-liveboard-tml.md` "KPI sparkline `client_state_v2`" for the verified
template. The template requires:
- `kpiDisplayProperties` at the chart level (`showChange`, `showChangeAs: "PERCENT"`)
- Per-column `kpiColumnProperties` with `showSparkline: true` on **both** the date and
  measure columns
- `axisProperties` with fresh UUIDs (use `python3 -c "import uuid; print(uuid.uuid4())"`)
- Optional `seriesColors` to match the chosen theme palette

Full KPI viz template (substitute column names, UUIDs, and colors):

```yaml
chart:
  type: KPI
  chart_columns:
  - column_id: "{ResolvedMeasure}"
  - column_id: "{ResolvedDate}"
  axis_configs:
  - x:
    - "{ResolvedDate}"
    y:
    - "{ResolvedMeasure}"
  client_state: ""
  client_state_v2: >-
    {"version": "V4DOT2",
     "chartProperties": {"gridLines": {}, "responsiveLayoutPreference": "USER_PREFERRED_ON",
       "chartSpecific": {"dataFieldArea": "column"},
       "kpiDisplayProperties": {"showChange": true, "showChangeAs": "PERCENT",
         "changeInterpretation": "UPWARD_IS_GOOD", "linkChangeColorsWithAnomaly": true}},
     "columnProperties": [
       {"columnId": "{ResolvedDate}", "columnProperty": {"kpiColumnProperties":
         {"showAbbreviatedPreviousDate": false, "showSparkline": true,
          "showComparisonDate": true, "showCurrentDateLabel": true,
          "showPreviousDateLabel": true, "showPreviousValue": true}}},
       {"columnId": "{ResolvedMeasure}", "columnProperty": {"kpiColumnProperties":
         {"showAbbreviatedPreviousDate": false, "showSparkline": true,
          "showComparisonDate": true, "showCurrentDateLabel": true,
          "showPreviousDateLabel": true, "showPreviousValue": true}}}],
     "axisProperties": [
       {"id": "{uuid1}", "properties": {"axisType": "Y", "linkedColumns": ["{ResolvedMeasure}"], "isOpposite": false}},
       {"id": "{uuid2}", "properties": {"axisType": "X", "linkedColumns": ["{ResolvedDate}"]}}],
     "seriesColors": [{"serieName": "{ResolvedMeasure}", "color": "{hex}"}]}
  viz_style: '{"overrides": {"column_properties": [{"column_id": "{ResolvedMeasure}", "properties": {"color": "{hex}"}}]}}'
table:
  table_columns:
  - column_id: "{ResolvedMeasure}"
    headline_aggregation: SUM
  - column_id: "{ResolvedDate}"
    headline_aggregation: MIN-MAX
  ordered_column_ids:
  - "{ResolvedDate}"
  - "{ResolvedMeasure}"
  client_state: ""
  client_state_v2: >-
    {"tableVizPropVersion": "V1",
     "columnProperties": [
       {"columnId": "{ResolvedDate}", "columnProperty": {}},
       {"columnId": "{ResolvedMeasure}", "columnProperty": {}}]}
```

### 10b. Build search queries

`search_query` is a ThoughtSpot search string of **bracketed column display names**, not
a "sum sales" phrase. Build it from the worksheet shelves:

- Reference each measure by its model column name: `[Total Revenue]` — the column's own
  default aggregation applies; do **not** prepend `sum`.
- Reference each dimension/attribute by name: `[Sales Channel]`.
- Date on a shelf → **dotted** bucket from the TWB `datetrunc`/`datepart`:
  `[Ship Date].yearly`, `[Order Date].monthly`. A bare `monthly` token is rejected.
- Top-N (Tableau Top filter) → append `top N`, e.g. `[Item Type] [Total Revenue] top 5`.
- **Percentage format for ratio measures.** A contribution / percent-of-total / growth-rate
  measure should display as a percent, not `0.07`. Set `format` on its `answer_columns[]` entry
  (`category: PERCENTAGE`, `percentageFormatConfig.decimals`) — see
  `../../shared/schemas/thoughtspot-answer-tml.md` "answer_columns[] fields". Detect from the
  formula (`/ TOTAL(...)`, `/ {FIXED ...}`, `growth of`) or the Tableau column's own % format.
- **Cumulative / moving measures** → reference the **measure column** by name with the
  worksheet's shelf attribute as the trailing sort arg: `cumulative_sum ( [Sales] , [Month] )`,
  `moving_average ( [Sales] , 2 , 0 , [Order Date] )` — these are **answer-level** formulas (not
  model columns). See `tableau-formula-translation.md` Running/Moving sections.
- **Growth / decline.** Two cases — read the worksheet's actual filters/table-calc to choose:
  - **A trend of growth over time** (`pcdf` with no Top-N, every period shown) → the
    `growth of` keyword: supply the bare date *and* its bucket, `growth of [Measure] by [Date]
    [Date].yearly [dim]` (default is **monthly**, so set `.yearly` for annual; dotted-only
    `by [Date].yearly` fails to tokenize). Resolved columns: `Growth of Total {Measure}` +
    `{Bucket}(Date)` — bind chart columns to those (export-patch).
  - **"Top/bottom N by growth over a window"** (`pcdf` **plus a Top-N filter + a recent-N-years
    filter** — e.g. "highest growth in past 5 years") → a **period-comparison**, best built as
    **answer-level formulas** on that one viz (it's viz-specific):
    ```yaml
    formulas:
    - id: formula_Val Start   # FDI in the start year
      expr: "group_aggregate ( sum ( [Measure] ) , query_groups () , query_filters () + { year_name ( [Date] ) = '2012' } )"
    - id: formula_Val End     # FDI in the end year
      expr: "group_aggregate ( sum ( [Measure] ) , query_groups () , query_filters () + { year_name ( [Date] ) = '2016' } )"
    - id: formula_Growth
      expr: "( [formula_Val End] - [formula_Val Start] ) / [formula_Val Start]"
    # search_query: "[Sector] [formula_Growth] top 5 by [formula_Growth]"   (bottom 5 = decline)
    ```
    Anchor years: **dynamic vs the actual data range matters.** `max([Date])` is **not allowed
    inside a formula filter** (`"Search did not find max("`), so you can't compute the data's
    latest year in-formula. Options: (a) **dynamic** via `currentdate()` —
    `year ([Date]) = year ( currentdate () )` and `… - 5` — correct for **live/refreshing**
    data, but returns **nothing** if the data is historical (e.g. ends 2016 while "today" is
    2026); (b) **anchor to the data's real bounds** (latest year and latest−5) when the
    dataset is static — functional, matches the "past 5 years" intent. Choose by whether the
    source refreshes; if unsure, **ask the user**. Format `Growth` as a percentage. This is the
    faithful translation of the `pcdf` + Top-N + window pattern — not a raw `growth of` line.
- A formula used by only this one viz can be an **answer-level formula** (`answer.formulas[]`
  + an `answer_columns[]` entry) rather than a model formula — see Step 5b.
- Calculated fields: translate the Tableau caption to the ThoughtSpot formula name via
  `{formula_column_map}`.

### 10c. Build liveboard TML

Follow `../../shared/schemas/thoughtspot-liveboard-tml.md` exactly — the structure below
is what actually imports and renders (an earlier `fqn`-based, minimal-chart form did not).

```yaml
liveboard:
  name: Dashboard Name
  description: "Migrated from Tableau workbook"
  visualizations:
  - id: Viz_1
    answer:
      name: Worksheet Name
      tables:
      - id: "Model Name"
        name: "Model Name"
        obj_id: "{model_obj_id}"            # the model's REAL obj_id from Step 10-pre (NOT the one you wrote into the model TML, NOT fqn — a viz-level fqn is dropped on import)
      search_query: "[Sales Channel] [Total Revenue]"
      answer_columns:                         # RESOLVED names (see below)
      - name: Sales Channel
      - name: Total Total Revenue
      chart:                                  # complete block, or omit entirely
        type: PIE
        chart_columns:
        - column_id: Sales Channel
        - column_id: Total Total Revenue
        axis_configs:
        - x: [Sales Channel]
          y: [Total Total Revenue]
      display_mode: CHART_MODE
  - id: Note_1                                # Tableau text / title zone → note tile
    note_tile:
      html_parsed_string: |-
        <p><strong>Title text</strong></p>
        <p>Body text from the Tableau text zone.</p>
  layout:
    tiles:
    - visualization_id: Viz_1
      x: 0
      y: 0
      height: 6
      width: 8
    - visualization_id: Note_1
      x: 8
      y: 0
      height: 6
      width: 4
```

**Critical naming rule (this is what breaks vizzes).** `chart_columns`, `axis_configs`,
and `table.table_columns` must reference the **resolved** answer-column names, not raw
model names:
- aggregated measure → `Total {Measure}` (`SUM([Total Revenue])` → `Total Total Revenue`)
- **model formula with embedded aggregation** (e.g. `sum([A] * [B])`) → resolves to the
  **formula name as-is**, no "Total" prefix. Example: formula "Commission Earned" with
  `sum(...)` expression → `Commission Earned`, NOT `Total Commission Earned`.
- bucketed date → `{Bucket}(col)` (`[Ship Date].yearly` → `Year(Ship Date)`)
- **KPI date auto-bucketing:** a bare date in a KPI `search_query` (e.g. `[Date]`) is
  auto-bucketed to **monthly** — resolved name becomes `Month(Date)` and the search_query
  gains `.monthly`. Specify `[Date].daily` explicitly if you want `Day(Date)` instead.
- attribute → unchanged

ThoughtSpot re-resolves `answer_columns` from `search_query` on import but does **not** fix
`chart_columns`/`axis_configs`. Reliable loop: build with your best-guess resolved names,
import, **export the liveboard**, copy the exact resolved names back into
`chart_columns`/`axis_configs`, and re-import. Use `obj_id` (never bare `fqn`) for the
table ref, and don't hand-author `client_state_v2` — leave styling to defaults.

Note tiles use `note_tile.html_parsed_string` (HTML) and have **no `answer`** — not the
old `viz_type: NOTE_TILE`/`content` form.

**Do NOT create a note tile just for the dashboard title.** ThoughtSpot liveboards have
native `name` and `description` fields — use them instead. Set `liveboard.name` to the
dashboard title and `liveboard.description` to any subtitle or context text. Only create
a note tile for a Tableau text zone that carries **content beyond the title** — instructions,
annotations, embedded links, or multi-paragraph context that belongs inside the board.

### 10d. Beautify layout

Apply layout optimization to each liveboard TML:

1. **Sort tiles** by y, then x.
2. **Pack rows from y=0** — reset y values so tiles start at 0 with no gaps.
3. **Fill 12 columns per row** — if a row's tiles don't span all 12 columns, expand
   the rightmost tile's width to fill.
4. **Minimum tile height** — enforce minimum height of 4 units.
5. **Remove empty rows** — if a row has no tiles, remove it.

Rewrite the `layout.tiles` section with corrected coordinates.

### 10e. Group related tiles into sections, and label everything clearly

A flat grid of tiles reads as a dump; a grouped, well-labelled liveboard reads as a
designed product. Two cheap, high-value steps:

**Group related vizzes into sections** (`groups[]` + `group_layouts[]` — see
`../../shared/schemas/thoughtspot-liveboard-tml.md` "Sections (groups)" and "Tabbed +
Groups"). Infer groupings from what the vizzes have in common rather than leaving
everything loose:
- All the per-measure **KPI tiles** → one "Key Metrics" section.
- Vizzes that share a **breakdown dimension** (e.g. two charts both by *Sales Channel*) →
  a section named for that dimension ("Channel Performance").
- Vizzes that share a **subject** (e.g. top-products + a geographic map) → e.g.
  "Product & Geographic Analysis".
- Give each group a short `name` and a one-line `description`.
A Tableau dashboard has no native sections, so this is an inference — keep it light
(2–4 groups), and don't force a viz into a group it doesn't fit; ungrouped tiles are fine.

**Groups work with tabs — but the nesting is specific.** When using `layout.tabs[]`:
1. Define `groups[]` at the liveboard level with `visualizations:` listing member viz IDs
2. In each tab's `tiles[]`, place **group IDs** as tiles (`visualization_id: Group_1`) —
   NOT individual viz IDs
3. Nest `group_layouts[]` **inside each tab** (not at the top-level `layout`)
4. Individual vizzes only appear inside `group_layouts[].tiles[]`
5. Ungrouped vizzes (e.g. note tiles) go directly in `tabs[].tiles[]`

**Common mistake:** putting individual viz IDs in `tabs[].tiles[]` alongside groups, or
putting `group_layouts` at the layout root instead of inside each tab — both cause
"Group was dropped because it has no valid visualizations" on import.

**Write meaningful names and descriptions on every viz.** Don't ship raw worksheet names
like `Sheet 1` or terse labels. Set `answer.name` to a clear title and add a one-line
`answer.description` stating what the tile shows (these surface as the tile title and its
info tooltip):

```yaml
answer:
  name: "Revenue by Country"
  description: "Total revenue distribution across countries; bubble size = revenue volume."
```

Prefer the Tableau worksheet caption when it's descriptive; otherwise synthesize a title
from the columns on the shelves (`{measure} by {dimension}`, `Monthly {measure} Trend`,
`Top {N} {dimension} by {measure}`). Keep descriptions to one factual sentence.

**Every viz MUST have an `answer.description` — no exceptions.** This includes fully
translated charts, not just placeholders. The description should state what the chart shows
and name the Tableau source worksheet. Example:

```yaml
answer:
  name: "Top 5 Item Types by Revenue"
  description: "Horizontal bar of top 5 item types ranked by total revenue. Source: Tableau worksheet 'Top 5 Item Type Revenue wise'."
```

For placeholder/partial vizzes, also note what's missing and that it needs review.

### 10f. Surface referenced parameters in the liveboard header

**This step is MANDATORY when the model has parameters — do not skip it.** If parameter
creation failed in Step 5b, fix the parameter first (check `range_config` string values,
cross-formula inlining) before proceeding. A Tableau dashboard with a parameter control
zone expects the parameter to be surfaced on the liveboard; omitting it silently loses
interactivity.

If any viz on the liveboard **references a model parameter** (directly, or via a formula/bin
it uses — e.g. an `Age (bin)` driven by an `Age Groups` parameter), the parameter can be
shown as a **header chip** so users can change it live. For each referenced parameter,
**ask the user — default yes:**

```
Add parameter "{name}" to the liveboard header so users can adjust it? [Y/n]  (default Y)
```

On **yes**, add it to the liveboard header via `ordered_chips[]` and `parameter_overrides[]`
(see `../../shared/schemas/thoughtspot-liveboard-tml.md`):

```yaml
liveboard:
  parameter_overrides:
  - key: "{parameter_uuid}"
    value:
      name: "{Model Name}::{Parameter Name}"
      id: "{parameter_uuid}"
      # override_value: "..."   # only to change the default
  ordered_chips:
  - name: "{Model Name}::{Parameter Name}"
    type: PARAMETER
```

The `{parameter_uuid}` is assigned when the model imports — resolve it by exporting the
model (`ts tml export {model_guid} --parse`) and reading its `parameters[].id`. Chip names
are scope-qualified: `Model Name::Parameter Name`.

### 10g. Add a "Migration Summary" tab

Add a final **"Migration Summary"** tab to each liveboard — a single note tile that records
what the migration did, so it's reviewable **in-product** (not just in a side file). The user
can edit or delete it. Use the **tabs** layout (`layout.tabs[]`): the migrated content is the
first tab, the summary is the last. The note tile's `html_parsed_string` has three sections:

```
1. Items migrated      — each viz/tile and how (chart type, search), formulas, cohorts, params
2. Decisions made      — non-obvious choices (unpivot via SQL view, bins=cohort vs formula,
                          count column, growth via `growth of`, theme, top/bottom approximations…)
3. Partial / placeholder — vizzes that couldn't be fully reproduced but were built as
                          placeholders (forecast → historical trend; cluster → underlying inputs);
                          flag each "needs review" + what's missing
4. Items NOT migrated  — only things with genuinely nothing to show, untranslatable formulas,
                          the flipboard interaction, orphan worksheets, data-fidelity gaps — reason each
```

Per the placeholder principle, **forecast/cluster vizzes are placeholders, not omissions** —
show the reproducible part (a forecast's historical trend; a cluster's input columns) and
flag for review; reserve "not migrated" for things with literally nothing to render.

This is the same content as `MIGRATION_LIMITATIONS.md` (Step 12) plus the positive items —
keep them consistent. If a workbook has multiple liveboards, give each its own summary
covering that liveboard, and note model-level decisions on the first.

**Record the orphan-worksheet outcome.** Orphans are surfaced and decided in **Step 9d** (not
here). In the Migration Summary, list which orphans existed, which were added as tiles, and
which were left off — noting that any calc fields/cohorts they introduced are still on the
model (usable via Spotter/search). (Example: the FDI `Groups` cohort exists on the model, but
its `Groups` worksheet wasn't dashboarded — so nothing referenced it until added deliberately.)

Write each liveboard to
`/tmp/ts_tableau_mig/output/{workbook_name}/{dashboard_name}.liveboard.tml`.

---

## Step 10.5 — Liveboard Style

A migrated liveboard looks intentional when it carries a coherent style rather than the
bare default. Offer the user a **curated theme** (one pick), then write it into the
liveboard. A complete theme is **three layers** — board/group/tile brand tokens
(`style.style_properties`), per-object assignments (`style.overrides[]`), **and** a matching
per-chart color palette (`chart.viz_style`). The full token reference is in
`../../shared/schemas/thoughtspot-liveboard-tml.md` ("Liveboard styling"); the
ready-to-apply per-theme recipes (tokens + `viz_style` palettes) are in
[references/liveboard-style-themes.md](references/liveboard-style-themes.md) — read it and
apply the chosen theme's three layers verbatim.

**MUST present ALL 6 themes plus option 0 — do not truncate the list.** Presenting a
subset removes the user's choice. Use the exact prompt below:

```
Pick a style for the liveboard(s):
  1  Clean & Minimal     — light gray, sharp borders (data-first, default)
  2  Cool Professional   — blue, corporate/executive
  3  Fresh & Modern      — mint/teal, contemporary
  4  Soft Lavender       — purple, elegant/calm
  5  Warm Tones          — peach/orange, friendly/customer-facing
  6  High Contrast KPIs  — dark KPI tiles for maximum headline impact
  0  None                — leave ThoughtSpot defaults

Enter 1–6 or 0:
```

**Apply the theme to EVERY chart tile — don't skip any.** When a theme defines a chart
palette (`viz_style`), set it on *all* chart vizzes uniformly, including formula-/growth-based
tiles and ones added late. A common miss is theming the straightforward bars/pies but leaving
a growth or computed tile on the default color — verify every chart tile got both its
`tile_brand_color` override **and** its `viz_style`.

**Confirm the theme on every workbook — never apply it silently.** In a multi-workbook run,
remember the previous pick and offer it as the **default** ("Style for this liveboard?
[default: High Contrast KPIs]"), so the user can press through to stay consistent or change
it per workbook. Always surface the choice; do not assume the last theme carries over without
showing it. Apply the theme by
writing `style.style_properties` and, where the theme colors groups/tiles, per-object
`style.overrides[]`:

```yaml
style:
  style_properties:
  - name: lb_brand_color
    value: LBC_C            # theme's liveboard color
  - name: lb_border_type
    value: CURVED           # SHARP for Clean & Minimal
  - name: kpi_hero_font_size
    value: M
  overrides:                # set each group/tile to the theme's GBC_/TBC_ token
  - object_id: Group_1
    style_properties:
    - name: group_brand_color
      value: GBC_C
```

Theme → token map:

The base brand colors per theme (quick glance — **the verified, complete recipe incl.
border type, per-tile colors, KPI emphasis, and `viz_style` palette is in
[references/liveboard-style-themes.md](references/liveboard-style-themes.md), which is
authoritative**):

| Theme | `lb_brand_color` | `group_brand_color` | non-KPI `tile_brand_color` |
|---|---|---|---|
| Clean & Minimal | `LBC_A` | `GBC_A` | `TBC_A` |
| Cool Professional | `LBC_C` | `GBC_C` | `TBC_C` |
| Fresh & Modern | `LBC_D` | `GBC_D` | `TBC_D` |
| Soft Lavender | `LBC_B` | `GBC_B` | `TBC_B` |
| Warm Tones | `LBC_G` | `GBC_G` | `TBC_G` |
| High Contrast KPIs | `LBC_A` | — | KPI tiles `TBC_I`–`TBC_P` (dark) |

Border type and KPI-tile treatment **vary per theme** — read the reference file, don't
assume. `TBC_I`–`TBC_P` are valid **only on KPI tiles** — never apply a dark tile color to
a chart/table tile.

**Post-apply verification.** After importing a themed liveboard, export it and verify:
1. Every chart viz has a `chart.viz_style` entry with the theme's color palette
2. Every viz has a `style.overrides[]` entry with the correct `tile_brand_color`
3. KPI tiles have `tile_kpi_color` and `is_highlighted` if the theme specifies them
4. No viz is missing from the overrides list (common miss: late-added or computed tiles)
If any are missing, add them and re-import.

---

## Step 11 — Import Liveboard

Display a summary:
```
Ready to import {N} liveboard(s) to {base_url}:
  - {dashboard_name_1}
  - {dashboard_name_2}
  ...
```

Ask: "Import now? (yes/no)"

On confirmation, import every liveboard TML in the output directory. Use `--pattern
'*.liveboard.tml'` to select only liveboard files, `--policy PARTIAL` so successfully
imported liveboards are kept even if some fail, and `--create-new` since these are new
objects:

```bash
ts tml import --dir /tmp/ts_tableau_mig/output/{workbook_name} \
  --pattern '*.liveboard.tml' --policy PARTIAL --create-new --profile {profile_name}
```

Parse the response for import errors. Show any failures with detail.

**Re-importing a liveboard in place** (a styling/param-chip/coverage pass after the first
import): set `guid` **and** `obj_id` to the existing object's values and import with
`--no-create-new`. **The single thing that matters: `guid`/`obj_id` must be TOP-LEVEL keys of
the TML document — siblings of `liveboard:`, NOT nested inside it.**

```json
{ "guid": "<existing>", "obj_id": "<existing>", "liveboard": { "name": ..., "visualizations": ... } }
```

Nesting them as `liveboard.guid` (a natural mistake when you build the dict as `{"liveboard": {...}}`
and set `d["liveboard"]["guid"]`) means the import never matches the existing object and **forks a
duplicate with a new guid — every time, regardless of `--policy`**. (This is the same top-level
placement tables/models use, which is why those updated in place while liveboards kept forking.)
`--policy` is irrelevant to the match; either `ALL_OR_NONE` or `PARTIAL` works once the guid is
top-level. Read the existing `obj_id` from the search result (`metadata_obj_id`) or a prior
export, and **verify the returned `id_guid` is unchanged** afterward; if it changed, the guid was
mis-placed — fix it and delete the stale duplicate.

For each successfully imported liveboard, display the URL:

```
{base_url}/#/pinboard/{liveboard_guid}
```

---

## Step 11.5 — Formula Coverage Answers

> **Scope gate:** runs for scopes 1, 2, 4. **Skip for scope 3** (liveboard-only — formulas
> belong to the pre-existing model) and **scope 5** (no model or formulas).

A workbook often defines **more formulas than its dashboards actually visualize** — and a
model-only workbook (no dashboards) visualizes none. Those formulas are valid on the model but
have no quick way to be *seen and tested*. So make every formula reachable:

1. **Find uncovered formulas.** From the model's formula columns (plus any answer-level formulas
   built in Step 10), subtract those already referenced by a liveboard tile. The remainder are
   uncovered. (For a model-only workbook, **all** formulas are uncovered.)
2. **Build one simple answer per uncovered formula** — a minimal, testable viz:
   - A measure → a KPI (`[Formula]`) or a small BAR by a natural dimension (`[Region] [Formula]`).
   - A string/label formula → a `TABLE_MODE` tile (`[Region] [Formula]`).
   - Apply the same conventions as Step 10b (resolved names, `%` format for ratios, sort attrs
     for cumulative/moving).
   - **Put the original Tableau formula in the answer's `description`** (e.g.
     `description: "Coverage tile for Rank of profit  ·  Tableau: RANK_UNIQUE(SUM([Profit]),'desc')"`)
     so a reviewer can compare the source expression to the migrated one without leaving the tile.
3. **Where they live:**
   - **Liveboard exists** → add a **"Formula coverage"** tab to it (one tile per uncovered
     formula). Keeps everything testable in one place. Re-import in place (see the
     `ALL_OR_NONE` rule above).
   - **No liveboard** (model-only) → create **standalone saved answers** (one per formula) bound
     to the model, so each is independently openable.
4. **Note it** in the Step 12 report (a formula's coverage tile/answer counts as ✅ reachable).

For table-mode coverage tiles, **omit the `chart` block** and set `display_mode: TABLE_MODE`
(`chart.type: TABLE` is invalid; stick to verified chart types — `BAR/LINE/PIE/KPI/AREA` — for
the charted tiles, and let table tiles render via `display_mode` with no chart block).

This is the safety net that makes a migration verifiable: no formula is migrated "blind."

---

## Step 12 — Migration Report

> **Scope gate:** runs for **all scopes** (1–5). Every migration produces a report.

Produce a **written migration report** — not just a console line. Write it to
`/tmp/ts_tableau_mig/output/MIGRATION_REPORT.md` and display it inline. The report is the
artifact the user reviews to understand what happened and to click straight through to each
created object, so **every object reference is a hyperlink** and **every formula is accounted
for**.

**One report, accumulating across files.** When the skill is run repeatedly in a loop (one
workbook at a time), **append** each workbook's section to the same `MIGRATION_REPORT.md` and
refresh the overview table — don't scatter one report per workbook. (A per-workbook
`MIGRATION_LIMITATIONS.md` may still be written for the untranslatable/pass-through detail.)

### Hyperlinks

Build links from `{base_url}` (Step 1) and the GUID returned at import:
- Model / table: `{base_url}/#/data/tables/{guid}`
- Liveboard: `{base_url}/#/pinboard/{guid}`
- Answer (standalone): `{base_url}/#/saved-answer/{guid}`

### Report structure

```markdown
# Tableau → ThoughtSpot Migration Report
_Generated {date} · ThoughtSpot: {base_url} · Connection: {connection_name}_

## Overview

| # | Source workbook (.twb) | Outcome | Model | Liveboard |
|---|---|---|---|---|
| 1 | Amazon Sales.twb | ✅ Model + Liveboard | [Amazon Sales]({link}) | [Amazon Dashboard]({link}) |
| 2 | arms_viz.twb | ◑ Model only (no dashboards) | [arms]({link}) | — |
| 3 | legacy.twb | ⊘ No action | — | — |

Outcome legend: **✅ Model + Liveboard** · **◑ Model only** · **⊘ No action** (why).

---

## {workbook_name}

**Source:** `{twb path}` · **Outcome:** {outcome} · **Connection:** {connection_name}

**Objects created**
| Type | Name | Link |
|---|---|---|
| Table | {name} | [{guid8}]({link}) |
| Model | {name} | [{guid8}]({link}) |
| Liveboard | {name} | [{guid8}]({link}) |

**What was done** — datasources, tables/SQL views, joins, model, Spotter, # tiles, theme.

**Decisions made** — the non-obvious calls (blend → one SQL view, bins = formula vs cohort,
dynamic vs anchored YoY, orphan worksheets added/left off, separate vs tabbed liveboards…).

**Formula mapping** — every calculated field, with status:
| Tableau field | Tableau expression | ThoughtSpot expression | Status |
|---|---|---|---|
| Total sales | `SUM([Sales])` | `sum([ORDERS::SALES])` | ✅ Migrated (model) |
| Cumulative sales | `RUNNING_SUM(SUM([Monthly sales]))` | `cumulative_sum([Sales])` | ✅ Migrated (answer-level) |
| Sales growth rate | `(SUM(curr)-SUM(prev))/SUM(prev)` | `([formula_Current…]-…)/…` | ◑ Partial — N/A on this data (dynamic, data ends 2024) |
| Relative difference | `LOOKUP([Total sales],-1)…` | `growth of [Total sales] by [Order Date]` | ◑ Partial — realized as a growth viz, not a column |
| Profit forecast | `MODEL_QUANTILE(…)` | — | ⊘ Not migrated — no ThoughtSpot equivalent (placeholder tile built) |

Status values: **✅ Migrated** (model or answer-level — say which), **◑ Partial** (built but
with a caveat — approximation, N/A on current data, placeholder), **⏸ Parked** (import
attempted, failed, deferred — show error and potential fix), **⊘ Not migrated** (omitted
before import; give the reason). Every calculated field from Step 3 must appear in exactly
one row.

**Sets** — every Tableau set, how it was handled, and what to verify (per the MANDATORY set-review
rule). Set conversions are semantic reinterpretations — list each so the user can confirm intent:
| Tableau set | Kind | ThoughtSpot result | Review |
|---|---|---|---|
| State Set | static | column set (GROUP_BASED, 3 members) | verify membership |
| Category Set | `except` | column set via `NE` (except Furniture; nulls excluded) | verify exclusion |
| Year Set | static, calc-anchored | column set on formula column `Order Year` | verify calc + values |
| 01. Month Set | set control | filter on `Order Month`; IF-[Set] calcs collapsed to measure+filter | confirm filter ≈ control |
| State_TopN | Top-N | ✓ query set (rank desc by SUM, N=topN param) | verify ranking + N |
| State_BottomN | Bottom-N | ✓ query set (rank asc by SUM, N=topN param) | verify ranking + N |

**⏸ Parked formulas** — formulas that `build-model` attempted to import but failed after
retry cycles. Only present when `{parked_formulas}` is non-empty. Include the attempted
expression and error so the user (or Step 12.5) can diagnose:

| # | Name | Attempted Expression | Error | Original Tableau | Potential Fix |
|---|------|---------------------|-------|------------------|--------------|
| 1 | {name} | `{expr}` | {error} | `{original_tableau}` | {LLM assessment of what might fix it} |

If the Complete-mode fix cycle was run, note which formulas were fixed (moved to ✅) and
which exhausted their 3 attempts. Include the last error for exhausted formulas.

**Excluded formulas** — every ⊘ row from the formula mapping table, grouped by root cause.
Include the root cause summary first, then per-formula detail under each heading:

Root cause summary:
| Root Cause | Count | Potential Resolution |
|---|---|---|
| Orphan inherited calc | {N} | Non-functional — references tables not in this datasource (copied from parent). Add missing tables or leave excluded |
| Missing table in model | {N} | Add source table(s) to the connection and model, then create the formula |
| Untranslatable function | {N} | No ThoughtSpot equivalent — consider a SQL view or Snowflake UDF |
| Circular dependency | {N} | Break the cycle by inlining one formula into the other |
| Complex date arithmetic | {N} | Rewrite with ThoughtSpot date functions or pre-compute in warehouse |
| Geospatial function | {N} | Spatial functions not supported — lat/lon columns migrated as attributes |

### {Root cause category} ({N} formulas)
| # | Formula Name | Tableau Expression | Potential Resolution |
|---|---|---|---|
| 1 | {name} | `{expr}` | {specific to this formula — what the user can do} |

Omit root cause categories with zero formulas. Ground each root cause and potential
resolution in [`references/coverage-matrix.md`](references/coverage-matrix.md) — it is
the canonical mapped/unmapped construct reference.

**⚠ Formulas needing review** — formulas that WERE migrated (✅ in the mapping table) but
require user verification. The ThoughtSpot behaviour may differ from Tableau in specific
conditions. List every flagged formula with a specific verification question:

| # | Formula Name | Review Category | What to Verify |
|---|---|---|---|
| 1 | {name} | No-keyword LOD | Test with/without search filters — does the value change as expected? |
| 2 | {name} | Blend-context | Row-level join may produce different aggregation — compare totals |
| 3 | {name} | Pass-through SQL | Confirm SQL Passthrough Functions is enabled on the cluster |
| 4 | {name} | `ifnull` stripped | NULL handling deferred to ThoughtSpot — verify nulls display correctly |
| 5 | {name} | `sum_if` rewrite | Simplified from `if/then/else` — verify aggregation matches |

Review category reference:
| Category | When flagged | What to verify |
|---|---|---|
| No-keyword LOD | `{AGG([col])}` → `group_aggregate(..., {}, query_filters())` | Tableau computes after dimension filters, before table-calc filters — no exact TS match. Test with/without search filters. If the formula should be an absolute total, change `query_filters()` to `{}`. |
| Blend-context | Formula references columns from a blended secondary datasource | Row-level join may aggregate differently than Tableau's post-agg blend — compare totals |
| Pass-through SQL | `sql_*_aggregate_op` or `sql_*_op` functions | Requires SQL Passthrough Functions enabled; verify SQL dialect matches your warehouse |
| `ifnull` stripped | `ifnull(measure, 0)` wrapper removed (default) | NULL handling deferred to ThoughtSpot query engine — verify nulls display correctly in charts/tables |
| `sum_if` rewrite | `sum(if(cond) then expr else 0)` → `sum_if(cond, expr)` (default) | Semantically equivalent but verify aggregation matches original |

Omit categories with zero formulas. The `ifnull` stripped and `sum_if` rewrite counts come
from the `translate_formulas` stats (`ifnull_stripped`, `agg_if_conversions`).
```

A console one-liner (`Tables: N · Models: N · Liveboards: N`) is fine as a closing line, but
the markdown report above is the deliverable. Keep it consistent with each liveboard's
in-product **Migration Summary** tab (Step 10g) and any `MIGRATION_LIMITATIONS.md`.

---

## Step 12.5 — Resume Prompt (Fix Parked Formulas)

> **Scope gate:** runs for scopes **1, 2, 4** (wherever formulas are imported).
> **Condition:** only runs when `{parked_formulas}` is non-empty.

After delivering the Step 12 report, prompt:

```
{N} formula(s) are parked. Would you like me to attempt fixes now?

  Y  Yes — analyze each error and attempt a rewrite  (up to 15 formulas, 3 attempts each)
  N  No  — leave parked; fix manually in ThoughtSpot
  S  Select — pick which ones to attempt

Enter Y / N / S:
```

**If N:** End the migration. The report stands as-is.

**If S:** Show the parked formulas with numbers. The user picks which to attempt (e.g.
`1,3,5` or `1-5`). Apply the same caps (max 15, max 3 attempts each).

**If Y or S:** Enter the same fix cycle as the Complete-mode cycle in Step 7 Phase 2:

1. Export the current model: `ts tml export {model_guid} --profile {profile_name} --parse`
2. For each selected formula (in dependency order):
   a. Analyze the `error` and `expr` from the parked record
   b. Skip if the error references another parked formula (fix dependencies first)
   c. Rewrite the expression based on the error
   d. Add as a new `formulas[]` entry with matching `columns[]` entry
   e. Import: `ts tml import --profile {profile_name} --policy ALL_OR_NONE` (GUID pinned)
   f. On success: move to ✅ Migrated
   g. On failure after 3 attempts: remains ⏸ Parked
3. After fixing level-0 formulas, retry level-1+ whose dependencies were just fixed

After the cycle, **regenerate the Step 12 report** with updated formula statuses. Parked
formulas that were fixed move to ✅ in the formula mapping table; the ⏸ Parked section
shrinks or disappears.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.22.1 | 2026-07-04 | **Fix: audit classifies per datasource, not flattened (live-test finding).** `ts tableau classify-formulas` on a multi-datasource workbook previously flattened all datasources' calcs into one `translate-formulas` call, which deduped by name — mis-tiering a calc *name* shared across datasources whose *expression* differs (e.g. SUM vs COUNTD) and misreporting coverage (per-datasource totals didn't reconcile). Now classifies per datasource (each → its own model); output is `{datasources:[{name,formulas,tier_counts,translate_stats}], tier_counts:<summed>}`, each datasource's `translate_stats` reconciles. Steps A3/A4 read per-datasource. Prereq ts-cli v0.32.1. |
| 1.22.0 | 2026-07-04 | **Codify highest-value/risk inline logic (Components A/D).** New `ts tableau parse` (blend graph, table-calc addressing, orphan calcs) replaces inline Python in Steps 3/3e/3f/3g. New `ts tableau classify-formulas` shares the migrate translation verdict, fixing the audit-vs-migrate divergence (Steps A3/A4/7). Blend graph computation moved to tested helpers (`build_blend_plan`), consumed via parse output (Step 5b Python removed). `ts tml import/lint` gain `--order tableau` / `--model-phase base` / `--pattern`, replacing the inline payload-builder heredocs in Steps 6/7/11; the anti-drift validator now guards those too. Prereq ts-cli v0.32.0. TML-template emission and spec-table relocation deferred. |
| 1.21.0 | 2026-07-03 | Wire `ts tableau build-model` generate mode into Phase-1 base-model step (BL-085 p1); add `--table-name-map` flag; blend-merge path unchanged. Prereq ts-cli v0.29.0 |
| 1.20.3 | 2026-07-03 | Full 13-function Tableau spatial set (was 5 documented, 0 enforced) + USERATTRIBUTE/USERATTRIBUTEINCLUDES now rejected loudly at translate time (was silent pass-through / undocumented). Requires ts-cli v0.28.1 |
| 1.20.2 | 2026-07-03 | ACOS/ASIN/ATAN/COT now rejected loudly at translate time (was silent pass-through). Requires ts-cli v0.26.5 |
| 1.20.1 | 2026-07-03 | Doc refresh: output schema + flag fixes, mapping-file greatest/least + pipeline-table alignment, matrix/open-items verification pass (5 stale items closed, incl. tabs #9), gap documentation (hierarchies, aliases, actions, fiscal year, inverse trig) |
| 1.20.0 | 2026-07-03 | LEFT/RIGHT/MID/UPPER/LOWER/STARTSWITH/ENDSWITH/SQUARE/SIGN/trig/PI/RADIANS/DEGREES/DATEPARSE now CLI-translated; unmapped functions and unknown date units rejected loudly at translate time; scalar MAX/MIN and IN(...) scan bugs fixed. Requires ts-cli v0.26.0 |
| 1.19.1 | 2026-07-02 | Update code-structure reference to new ts_cli/tableau/ package (BL-069) |
| 1.19.0 | 2026-06-28 | **Migration Pace — Fast vs Complete.** (1) New Step 1.5 pace choice: **F**ast (default) parks failed formulas and moves on; **C**omplete enters a bounded fix cycle (max 15 formulas, 3 attempts each) after `build-model`. (2) Step 7 Phase 2 now branches on pace — Fast reports parked count and proceeds; Complete enters export→fix→import loop for each dropped formula. (3) New ⏸ Parked formula status in Step 12 migration report — shows attempted expression, error, original Tableau, and potential fix. (4) New Step 12.5 resume prompt — after the report, offers Y/N/S to attempt fixes on parked formulas (same fix cycle, same caps). (5) `build-model` `--max-retries` flag (default 10, was hardcoded). (6) `formulas_dropped_on_import` enriched from `list[str]` to `list[dict]` with `name`, `expr`, `error`, `original_tableau` fields. Prerequisite: ts-cli v0.20.0. |
| 1.18.0 | 2026-06-28 | **Wire `ts tableau build-model` into SKILL.md + close validation gaps + dual-join alias detection.** (1) Step 7 Phase 2 rewritten: replaces 40 lines of inline Python formula assembly with a single `ts tableau build-model --existing-guid` call (root cause of 1,389 tool calls in the Ads migration). (2) `validate_pre_import()` now called from `build-model` command (both flows) — catches IN-with-parens, non-existent functions (`add_quarters`/`add_years`), and bare date literals before import. (3) `add_formula_prefix()` + `fix_double_aggregation()` now run in the generate-files flow (previously only in the merge flow). (4) Date parameter normalization: Tableau `#YYYY-MM-DD#` → ThoughtSpot `MM/DD/YYYY`. (5) `--existing-guid` flow returns `updated_model_guid` in JSON output. (6) Dual-join table alias detection: when the same physical table appears twice with different `name` attributes (e.g. `d_partner` / `d_partner1`), both are preserved with `alias_of` tracking. (7) New `check_skill_cli_usage.py` regression validator prevents drift back to inline Python TML assembly. Prerequisite bumped to ts-cli v0.19.0. |
| 1.17.0 | 2026-06-27 | **Add `ts tableau build-model` CLI command and migration scopes 4/5.** (1) New `model_builder.py` module (ts-cli 0.18.0): deterministic TWB→model-TML pipeline with pure functions for all 8 model-level transforms — `formula_` prefix for cross-references, double-aggregation detection/fix, name collision resolution (formula/param→rename, column/formula→drop column), parameter extraction/ordering, phased import splitting by dependency level. Resolves BOTH `[Calculation_NNN]` and copy-style `[Field (copy)_NNN]` internal refs (root cause of prior translation failures). (2) `build_formula_levels` computes correct dependency DAG from raw calcs before reference resolution — fixes all-at-level-0 bug. CPG Merch DS1: 6 dependency levels, 7 import phases. (3) New scopes: **4 Models only** (tables exist, build model+formulas), **5 Tables only** (generate/import table TMLs only). Per-step scope annotations on all steps. 28 unit tests. |
| 1.16.0 | 2026-06-27 | **Close the audit-vs-migration gap: CLI formula translation pipeline, two-phase import, join confirmation, cross-reference depth reporting.** (1) New Step 5b CLI reference: `ts tableau translate-formulas` (ts-cli 0.16.0) — deterministic 14-step Tableau→ThoughtSpot formula translation with dependency DAG, cross-reference resolution via inlining, column scoping, parameter conflict detection. Replaces ad-hoc LLM translation. (2) Step 7 two-phase model import: Phase 1 imports base model (tables, columns, joins, params — no formulas) for guaranteed success; Phase 2 adds formulas with GUID-pinned update and iterative error recovery (up to 5 cycles). One bad formula no longer blocks the entire import. (3) Step 3.6 join confirmation: detected joins presented for user confirmation; missing joins (common with published datasources/sqlproxy) suggested from shared column names with explicit D/S/P prompt — never silently added. (4) Step A3/A4 cross-reference depth reporting: Level 0/1/2+/circular counts plus "effective migration coverage" that distinguishes syntax-level translatability from what actually migrates after dependency resolution. Coverage matrix entries #113–#116. |
| 1.15.0 | 2026-06-17 | Step 4.5 connection step now offers **E — use existing / C — create a new connection** (Snowflake-source only, key-pair auth via `ts connections create`). Adds the "Database does not exist in connection → role can't see it → create one" guidance and a credential-handling guardrail (private key by file path only; never pasted into chat). Non-Snowflake sources / password / OAuth remain out of scope → create in the UI and use the E path. Mirrors the connection-step change in ts-convert-from-snowflake-sv. |
| 1.14.2 | 2026-06-17 | Replace the hand-written pre-import grep gate with `ts tml lint` (parser-based; now also catches **I8** duplicate `column_id`). From the full audit sweep (codification, angle 11). |
| 1.14.1 | 2026-06-17 | **Measure-classification + string-parameter-type fixes (from the Catalog Health live migration).** (1) Step 5b parameter mapping: a string **parameter** must be `CHAR`, **not `VARCHAR`** — ThoughtSpot rejects a `VARCHAR` list parameter on import (table *columns* are unaffected). (2) New **MEASURE vs ATTRIBUTE classification** rule in Step 5b: a formula is a MEASURE if it *transitively* produces a number (own aggregate/ratio **or references another MEASURE formula** by `[formula_<id>]` — e.g. a dynamic `if [Param] then [formula_…Pct]` selector); a numeric physical column **defaults to MEASURE** unless it's clearly a dimension (`*_ID`/`*_NUM`/`*_NAME`/date) — Tableau's `role` under-tags counts; and **bare unbracketed column refs** must be qualified to `[TABLE::COL]`. Under-classifying as ATTRIBUTE makes KPIs/chart y-axes render empty. (Assumes PR #92 → v1.14.0 merges first; renumber if not.) |
| 1.14.0 | 2026-06-17 | **Add a charting-library choice (Step 10-charts): prompt Legacy (default, portable) vs Muze (new charting library, early access).** On Muze, emit `ADVANCED_*` + `custom_chart_config` (shelf model `x-axis`/`y-axis`/`slice-with-color`/`trellis-by`) for cartesian/pivot intents — mapping Tableau's Color shelf → `slice-with-color` and small multiples → `trellis-by` for a closer migration — and fall back to Legacy types for non-cartesian intents (pie/scatter/geo/etc.). Backed by the expanded `thoughtspot-chart-types.md` "Muze charting library" spec (verified live on se-thoughtspot 2026-06-17: Muze/`ADVANCED_*` family = 10 cartesian/pivot types only; `custom_chart_config` on a Legacy type is rejected; pivot/combo/simple charts auto-resolve). |
| 1.13.1 | 2026-06-17 | Cite the new shared **`thoughtspot-chart-types.md`** reference (verified 44-value `answer.chart.type` enum + analytical-intent → chart-type mapping) from the References table and Step 10a; note that `GAUGE` is invalid and one bad enum value fails the whole import. (Reference promoted from `docs/` to `agents/shared/schemas/` and added to the CoCo stage-copy list.) |
| 1.13.0 | 2026-06-16 | **Add a migration-scope choice, fix the model `obj_id` reuse bug, and add efficiency guidance.** (1) New **Step 1.5 — migration scope**: ask right after auth whether to migrate **Models + Liveboards** (default), **Tables + Models only** (skip Steps 8–11), or **Liveboards only** (skip Steps 4–7.5, build on an existing model). New **Step 1.5a model picker** for the LB-only path mirrors the connection prompt — **G** GUID / **N** name / **F** filter / **L** list-all (slow); models are found via `--subtype WORKSHEET` filtered to `metadata_header.worksheetVersion == "V2"` (there is no `MODEL` subtype). Steps annotated with the scopes that run them. (2) **obj_id read-back rule (Step 7 + 10-pre + 10c)**: a requested `obj_id` on a *fresh* model import is **not honored** — ThoughtSpot reassigns `{Name-with-dashes}-{guid8}`. Reusing the written obj_id made every liveboard tile fail to bind and forced a delete + re-import. Now: read the model's **real** obj_id back (import-response `objId` / `metadata search --guid` / export) and use only that for viz `tables[].obj_id` and cohort `worksheet.obj_id`. (3) **Efficiency** block + relaxed the one-question rule: batch independent prompts, parse the TWB in one pass, capture obj_id + parameter UUIDs + resolved names in a single Step 10-pre export. |
| 1.12.1 | 2026-06-16 | **Extend the N/F/L connection prompt into the Step 4c connection-scoped search path.** The 4c "C — within a connection" path now explicitly presents the Step 4.5 N (name it) / F (filter by substring) / L (list all) prompt to identify the connection — it must NOT run `ts connections list` and dump every connection by default. Broadened the Step 4.5 title to "(create path or connection-scoped search)" so it's the canonical home of the prompt for both the create and the search-scope cases. Mirrors the same fix in ts-convert-from-snowflake-sv and ts-convert-from-databricks-mv. |
| 1.12.0 | 2026-06-16 | Step 4.5 connection selection: add a **how-to-identify-the-connection prompt** (N name it / F filter by partial string / L list all) before dumping the full connection list. Fetch once via `ts connections list`, then use the typed name directly, show a filtered subset, or show the full numbered list. Single connection still auto-selects. Mirrors the same prompt added to ts-convert-from-snowflake-sv and ts-convert-from-databricks-mv. |
| 1.11.0 | 2026-06-16 | **Reorder Step 4 / 4.5 so the source-table question comes first — don't waste time on unnecessary ThoughtSpot searches.** New **Step 4 — Confirm Source Tables** runs immediately after the parse and *before* any connection selection or search, with an explicit guard: do NOT run `ts metadata search` / `ts connections list` / `ts connections get` until the user answers E (exist) / N (don't) / ? (not sure). New **4c scoped-search choice** for the E/? paths — **C** search within a specific connection (fastest) vs **I** entire instance — and always search by `--name "%table%"` pattern, never `--all`-then-filter. Connection selection moves to **Step 4.5 (create path only)**, skipped entirely when every table is reused; the slow/404-prone `ts connections get` v1 schema fetch is now a documented fallback (ask the user for db/schema first). Mirrors the `ts-convert-from-databricks-mv` Step 7/8 ask-before-search flow. |
| 1.10.0 | 2026-06-14 | Add row-offset table-calc translation (BL-024): tiered decision tree for INDEX/LOOKUP/FIRST/LAST/SIZE — native rank/Top-N, native window functions (`moving_sum`, `first_value`, `last_value`, `rank`), or omit based on `<table-calc>` addressing recoverability. New Step 3f extracts addressing context from TWB XML. Live-verified 2026-06-15: SQL pass-through `ORDER BY` fails for DATE/numeric columns; replaced with native TS functions that work for all column types. |
| 1.9.1 | 2026-06-12 | **Fix static query-set `search_query` token order** (v1.9.0 follow-up, now live-verified). A static (fixed-N) Top-N query set's search is **`top N [dimension] [measure]`** — anchor dimension FIRST, then measure — not `[measure] [dimension]`. Verified against an exported set "Static Top 10" on se-thoughtspot (model `TEST_SV_DMSI_AI_CONTEXT`). Also corrected the static-form `config` defaults to the verified values: `hide_excluded_query_values: false` (shows an "Others" remainder bucket) + `group_excluded_query_values: "Others"`, with a note that hide/show is a display choice. Dropped the "static-form export not yet captured" caveat — it's now ground-truthed. Added the verified static export to `thoughtspot-sets-tml.md`. (Dynamic form unchanged.) |
| 1.9.0 | 2026-06-12 | **Top-N/Bottom-N sets → ThoughtSpot query sets (BL-009 Phase 2b).** Replace Phase-2b deferral with a verified translation: Tableau `<group>` whose `<groupfilter>` tree contains `function='end'` → `cohort_type: ADVANCED`, `cohort_grouping_type: COLUMN_BASED` cohort, in **one of two forms by `count`**: (a) **dynamic** (parameter-driven N, `count='[Parameters].[X]'`) — embedded answer with a rank formula (`rank(sum(measure),'desc'/'asc')` for top/bottom) + a parameter-filter formula (`[formula_rank] <= [<alias>::<param>]`), N read from the migrated model parameter (live-verified ground truth); (b) **static** (fixed N, literal `count='N'`) — a plain `search_query: "top N [measure] [dimension]"` / `"bottom N …"` keyword search, no formulas (the `top N` keyword form is correct for fixed N — not wrong). Detection rules: `end='top'` → `top N`/`'desc'`; `end='bottom'` → `bottom N`/`'asc'`. Both emission templates added (Section 5b). **Stepped range → `list_config`:** a Tableau `<range granularity='N' .../>` parameter enumerates min→max by step → `list_config` (NOT `range_config` which loses the step); a count parameter for a Top-N set must use `list_config`. Import order: model (with param) → cohort. Tier table + audit coverage table updated (Top-N moved from "Partial/deferred" → "Native/Set"). Dropped nuances (null-pad, conditional measure) flagged for review. All live-verified 2026-06-12 on se-thoughtspot (model `TEST_SV_DMSI_AI_CONTEXT`). New worked example `worked-examples/tableau/topn-set-to-query-set.md`. Schema `thoughtspot-sets-tml.md` updated with verified COLUMN_BASED pattern. |
| 1.8.1 | 2026-06-12 | Add `FIRST()`/`LAST()` to the untranslatable table-calc detection (tier table + Audit classifier regex + translation step) — missing from the skill's own classifier though the mapping reference listed them; precedence note: untranslatable only standalone, not as `WINDOW_*`/`RUNNING_*` offset args. **AND recognise the comma-separated-list / string-concatenation technique** (FIRST/LAST/LOOKUP/PREVIOUS_VALUE building one delimited string) → translate the *intent* to **`LISTAGG` string aggregation** (`sql_string_aggregate_op`, answer-level, ⚑ flag for review) or a table, instead of omitting; the feeder/`Last` scaffolding collapses into the one formula. Live-verified the LISTAGG answer-level formula on se-thoughtspot. New "String aggregation" section in `tableau-formula-translation.md`. **Plus set IN/OUT consumption (all live/UI-verified):** column sets ARE formula-referenceable — `IF [Set] THEN x END` → `sum ( if ( [Set] = 'in' ) then x else null )` or `sum_if ( [Set] = 'in' , x )` (or dimension-direct `sum_if ( [dim] in {…} , x )`); compare in-vs-out → group a measure by the cohort (`[Amount] [Set]`); filter on it for in/out. Pitfall: cohort **name must differ from its `in`/`out` labels** (a name==label collision fails "Search did not find"); emit distinct lowercase `in`/`out` labels; formula label must match exactly (case-sensitive). Added verified consumption answer TML (measures + group-by breakdown) to the worked example. (Found via TableauSetControlUseCases.) |
| 1.8.0 | 2026-06-12 | Translate Tableau static sets → ThoughtSpot column sets (`cohort_type: SIMPLE`, `cohort_grouping_type: GROUP_BASED`); detect and log Top-N sets (`function='end'`) as Phase-2b deferred, set operations (`except`/`intersect`) as Phase-2c deferred, and set actions as no-equivalent — none mis-translated (BL-009 Phase 2a). Live-verified on se-thoughtspot: bind via `worksheet:` (id/name/obj_id) NOT `model:`; anchor/column_name use display names; `operator: EQ` + value list. Added worked example `worked-examples/tableau/static-set-to-column-set.md`. UI-verified set capabilities: `%null%` members ARE representable via the `{Null}` grouping value (`EQ ["{Null}"]`); `except` member-lists → `operator: NE`; sets can anchor on a **formula column** (resolve calc id → display name, emit the backing formula); set controls (`level-members` only) → no set object, surface as a liveboard filter. Top-N (→ query set) + `intersect`/computed `except` remain deferred. |
| 1.7.0 | 2026-06-12 | Add Phase-1 Tableau function mappings (DATEPARSE, EXP, trig, STARTSWITH/ENDSWITH, PI/RADIANS/DEGREES composites, PROPER/ASCII/CHAR/REGEXP/FINDNTH pass-through, WINDOW_*/RUNNING_COUNT table-calc notes) (BL-009 Phase 1). Fix trig unit bug (Tableau radians→ThoughtSpot degrees conversion). Fix UPPER/LOWER (no native — use sql_string_op pass-through). Fix REGEXP_MATCH (sql_bool_op, returns boolean). Drop ⚠ confirm markers on docs-confirmed functions. Adopt PT1 pass-through policy (scalar reliable; flag aggregate pass-through for review). Document NULL-in-IF/ELSE behavior — matches Tableau via SQL CASE, faithful, no auto-guard (BL-002). |
| 1.6.0 | 2026-06-12 | Add pre-import validation gate (I1/I2/I4/I5) before model TML import (BL-001). |
| 1.5.43 | 2026-06-11 | Add **partial-date-to-full-date rule** to Step 5a: year-only strings (e.g. `_2016_17`, `FY2016`) must produce a full `YYYY-MM-DD` date (append `-01-01`). Bare-year conversions break ThoughtSpot date bucketing, KPI sparklines, and date filters. Apply in SQL View query when one exists, otherwise as a model formula. Companion rule added to `tableau-tml-rules.md` "Date Column Rules". Also fixed duplicate SQL View TML Rules section in that file. |
| 1.5.42 | 2026-06-11 | Add **Step 10-pre** — export model and check for parameters BEFORE generating any liveboard TML. Fixes repeated Step 10f misses: the parameter UUID lookup was positioned after TML generation, making it easy to skip. Now the UUID is collected upfront so `parameter_overrides`/`ordered_chips` are part of the initial TML, not an afterthought. |
| 1.5.41 | 2026-06-11 | KPI sparkline fix: `client_state_v2` with `showSparkline: true` is **required** on KPI chart blocks — without it, only a plain number renders (no trend line, no comparison). Added full KPI viz template to Step 10a with `chart:` + `table:` blocks, `kpiDisplayProperties`, per-column `kpiColumnProperties`, and axis UUIDs. Updated `thoughtspot-liveboard-tml.md` schema to document the exception and provide verified template. |
| 1.5.40 | 2026-06-11 | Eight learnings from the 3-workbook demo migration (Amazon/FDI/HR): **(1)** Title note tiles are unnecessary — use `liveboard.name`/`description` instead; only create note tiles for substantive text zones. **(2)** Parameter `range_config` values must be strings; `sum([formula_ref])` needs inlining; export model post-import to capture parameter UUIDs. **(3)** Step 10f (parameter on liveboard) is now mandatory — do not skip; fix failed params first. **(4)** Step 9d (orphan worksheets) reinforced as must-ask with "add" as default recommendation. **(5)** CHART_MODE is the default — TABLE_MODE only for explicit crosstabs; untranslatable vizzes get CHART_MODE placeholders (SCATTER for clusters, LINE for forecasts). **(6)** Theme picker must show all 6 options; post-apply verification step added. **(7)** `answer.description` required on every viz (not just placeholders), naming the Tableau source worksheet. **(8)** Updated Step 10c template accordingly. |
| 1.5.39 | 2026-06-11 | Add I6 (connection by name, never GUID) to Step 5b callout; callout now covers I1–I6. |
| 1.5.38 | 2026-06-11 | Add Model TML hard rules (I1–I5) callout to Step 5b with paired `formula_id`/`DONT_INDEX` template and COUNTD → `unique count` example. Add mandatory formula-reference gate (I7) to Step 5b and Step A3. Add model name N1 citation (bare datasource name, no prefix). |
| 1.5.37 | 2026-06-10 | **Corrects the liveboard in-place rule (1.5.32/1.5.36 were wrong about *why*):** the only thing that matters is that `guid`/`obj_id` are **top-level keys of the TML doc — siblings of `liveboard:`, not nested inside it**. Nesting `liveboard.guid` makes every re-import fork a duplicate regardless of `--policy` (the `PARTIAL`-forks claim was a red herring — it was the nesting all along; models worked only because their guid was already top-level). Plus two review fixes: **(a)** detect & drop **redundant pass-through formulas** (`SUM([col])`/`[col]` of an existing physical column — e.g. `Total sales`, `Monthly sales` vs physical `Sales`); use the physical column, note the collapse. **(b)** put the **original Tableau formula in each coverage answer's `description`** for side-by-side review. |
| 1.5.36 | 2026-06-10 | Three fixes from the Multiple Calculated Fields review: **(1)** new **Step 11.5 — Formula coverage answers**: every formula not on a dashboard tile (or *all* of them, for a model-only workbook) gets a simple testable answer — a "Formula coverage" tab on the liveboard, or standalone saved answers when there's no liveboard. **(2)** `cumulative_*`/`moving_*` must take the **worksheet's shelf attribute as the trailing sort arg** and reference the **measure column** by name (`cumulative_sum([Sales],[Month])`), not `sum()`. **(3)** apply **`PERCENTAGE` format** (`answer_columns[].format`) to contribution/percent-of-total/growth measures. Also: **in-place liveboard re-import must use `ALL_OR_NONE`** — `PARTIAL` forks a duplicate even with `guid`+`obj_id` pinned; and `chart.type: TABLE` is invalid (omit the chart block for `TABLE_MODE` tiles). |
| 1.5.35 | 2026-06-10 | Rewrite **Step 12** into a written **MIGRATION_REPORT.md**: an overview table of every source `.twb` → outcome (✅ Model + Liveboard / ◑ Model only / ⊘ No action) with **hyperlinks** to each created object, a per-workbook section (what done / decisions / partial / not migrated), and a **full formula-mapping table** (Tableau expr → ThoughtSpot expr → status ✅/◑/⊘) covering *every* calc field. One accumulating report across a multi-file loop. (Requested while migrating Multiple Calculated Fields.) |
| 1.5.34 | 2026-06-10 | Four formula-translation fixes from the Multiple Calculated Fields stress test (all in `tableau-formula-translation.md`): **(1)** `rank()` needs the **direction arg** — `rank(m,'desc')`, 1-arg fails; **(2)** `cumulative_*`/`moving_*` are **query-time only — invalid in model formulas** (*"Search did not find"*), realize them on the viz's `search_query` (so a `RUNNING_SUM`/`WINDOW_*` field → answer-level, not a model column; a nested `EXP(WINDOW_AVG(LOG()))` can't be a model column at all); **(3)** string concat uses **`concat(a,b)`**, not `+` (Tableau overloads `+`); **(4)** year-comparison calcs should be **dynamic** (`year(today())` / `year(add_years(today(),-1))`) not the workbook's hardcoded years — but surface the data-fidelity tradeoff when the data is frozen in the past. |
| 1.5.33 | 2026-06-10 | Promote orphan-worksheet handling from a Step-10 footnote to a real **Step 9d** that **prompts** the user (add all / subset / none) — describing *what each orphan shows* + its TS equivalent and a recommendation, not just naming it; picked orphans become extra tiles. Don't silently drop them. (Raised on HR: `Attrition Yes/No Count`, `department`.) |
| 1.5.32 | 2026-06-10 | **Liveboard in-place update needs both `guid` AND `obj_id` pinned** — `--no-create-new` + `guid` alone still forked a duplicate (new `obj_id`). Same rule as tables/models: set `liveboard.guid` + `liveboard.obj_id` to the existing object's values before re-import. (Caught re-importing HR liveboard for the KPI-emphasis/param-chip pass.) |
| 1.5.31 | 2026-06-10 | Cross-formula references use the **formula id** `[formula_<id>]`, not the display name `[<Name>]` (name form errors "Search did not find"); column refs stay `[T::COL]`. (Caught on HR `Attrition Percentage` referencing `Attrition Count`.) |
| 1.5.30 | 2026-06-10 | Apply the placeholder principle to **forecast/cluster vizzes** — build them as placeholders (forecast → historical trend; cluster → input columns as a table) and flag "needs review", rather than omitting. Migration Summary now has a "Partial / placeholder" section distinct from "Not migrated". (Caught: FDI had Cluster/Trend Forecast omitted instead of placeholdered.) |
| 1.5.29 | 2026-06-10 | Flag **orphan worksheets** (in the workbook but on no dashboard → no tile) in the Migration Summary; note their calc fields/cohorts are still on the model (Spotter-usable) and offer to add them as tiles. Caught: FDI `Groups` cohort on the model but its worksheet wasn't dashboarded, so nothing used it. |
| 1.5.28 | 2026-06-10 | Theme application must cover **every chart tile** — set the theme's `viz_style` palette on all chart vizzes (incl. formula/growth tiles), not just the straightforward ones (caught: FDI growth bars left on default color). |
| 1.5.27 | 2026-06-10 | Dynamic-period growth limitation: **`max([date])` is not allowed in a formula filter** (can't compute the data's latest year in-formula). For *live* data use `currentdate()`-relative anchors; for *historical/static* data (e.g. ends 2016) `currentdate()` returns empty, so anchor to the data's real bounds. Choose by whether the source refreshes — ask if unsure. |
| 1.5.26 | 2026-06-10 | Three principles (from FDI growth tiles): **(1) read the actual calculation, not the worksheet title** (inspect table-calc type, filters, Top-N, sort) to pick the translation. **(2) "Top/bottom N by growth over a window"** (`pcdf` + Top-N + recent-years filter) → a **period-comparison** built from **answer-level** `group_aggregate(..., query_filters() + { year_name([Date]) = 'YYYY' })` formulas + `Growth = (end-start)/start` + `top/bottom N` (anchor years hardcoded or dynamic). **(3) Placeholder charts**: when a viz can't be fully translated, build a `TABLE` of the columns you can produce and flag it for review in the viz description + Migration Summary — don't silently omit. |
| 1.5.25 | 2026-06-10 | Strengthen the KPI rule: **ALWAYS include a date on every KPI tile when the model has one** (not just measure blocks) — easy to miss; use the data's grain (`.yearly` for annual). E.g. a Total Sectors KPI in a workbook with Fiscal Year is `[Total Sectors] [Fiscal Year].yearly`, not a static `[Total Sectors]`. |
| 1.5.24 | 2026-06-10 | Correct the `growth of` date-period syntax: set the grain with `by [Date] [Date].yearly` (bare date + bucket); **default is monthly**, so apply `.yearly` for annual data (dotted-only `by [Date].yearly` fails to tokenize). Resolved cols `Growth of Total {Measure}` + `{Bucket}(Date)`. Also add **Step 8 prompt: separate liveboards vs one tabbed liveboard** when a workbook has 2+ dashboards. |
| 1.5.23 | 2026-06-10 | `growth of` syntax quirk (from FDI): no dotted bucket in the `by` clause (`by [Date].yearly` fails to tokenize) — ThoughtSpot auto-buckets; resolved columns are `Growth of Total {Measure}` + `{Bucket}(Date)`; bind chart columns to those (export-patch). |
| 1.5.22 | 2026-06-10 | Add **Step 10g — "Migration Summary" tab**: a note-tile tab on each liveboard listing (1) items migrated, (2) decisions made, (3) items not migrated + reasons — reviewable in-product, editable/deletable by the user. Mirrors `MIGRATION_LIMITATIONS.md` plus the positive items. Uses the `layout.tabs[]` form. |
| 1.5.21 | 2026-06-10 | Two formula principles (from FDI): **single-viz formulas can be answer-level** (`answer.formulas[]`) rather than model-level — keep the model lean; reuse decides. **Growth/decline** (`pcdf`/percent-difference table calc) → `growth of [measure] by [date]` when a date is present (else this/last-period formulas). |
| 1.5.20 | 2026-06-10 | Add a top-level **working principle — surface, recommend, resolve**: when a non-1:1 situation is hit (blend, missing/multi-table join key, VARCHAR date, bins, count column, manual group, value-vs-data mismatch, untranslatable formula), inform the user, recommend a solution, and attempt to resolve it with their go-ahead — don't silently drop/guess/flag. Default to enabling the migration. |
| 1.5.19 | 2026-06-10 | Reconcile the "**never merge datasources**" rule with the blend reality: it guards against *blind* collapse, but a deliberate **cross-datasource blend** is realized as **one** model (co-locate keys in a SQL view + join). Add: **build only the models the workbook actually uses** — a datasource that exists only to feed a blend folds into the model that uses it, not a standalone unused model. |
| 1.5.18 | 2026-06-10 | Refine join/blend handling from the Dual Axis workbook: ThoughtSpot relationships are **binary** — a join key spanning two tables must be **co-located into one SQL view**; and **don't pre-aggregate to dodge fan-out** — ThoughtSpot **handles fan/chasm traps**, so a line-level view joined to a per-group table computes `sum()` correctly. Net result: a blend usually becomes **one model** on a single line-level view, not multiple. |
| 1.5.17 | 2026-06-10 | Joins: **keys must be physical columns — you cannot join on a model formula.** When a join/blend needs a column that doesn't exist (e.g. month-of-order-date), **advise the user of two remediation paths**: (1) a ThoughtSpot **SQL View** (`sql_view` TML, derived/pre-aggregated columns → physical join keys) used as the model foundation, or (2) a **DB table/view** the user creates and adds to the connection, then bind to it. State exactly what columns/grain are needed; multi-column joins OK; mind fan-out. Cross-datasource formulas are blends → realize via such a join or omit+flag. |
| 1.5.16 | 2026-06-10 | Add **Step 10f**: when a liveboard viz references a model parameter (directly or via a bin/formula), **ask (default yes) to add it to the header** as a chip — writes `ordered_chips[]` + `parameter_overrides[]` (resolve the parameter UUID from the exported model). |
| 1.5.15 | 2026-06-10 | Step 10.5: **confirm the theme on every workbook, defaulting to the previous selection** — never apply silently. Surface the choice (default = last pick) so the user can keep or override per liveboard. |
| 1.5.14 | 2026-06-10 | Refine flipboard/story handling: before skipping such a dashboard, **salvage its content** — migrate any unique worksheets and preserve narrative captions as **note tiles**; only the flip *interaction* is dropped (not visualizations or commentary). |
| 1.5.13 | 2026-06-10 | Add explicit **prerequisite**: the source tables + data already exist in a warehouse and a ThoughtSpot connection exposes them. The skill creates logical TS objects over existing physical tables; it does not create/load warehouse data (data pipeline is out of scope). |
| 1.5.12 | 2026-06-09 | Correct the "never read the warehouse" framing: for data-dependent info (bin ranges, stored value format, group-membership existence) the skill should **prompt the user first**, and **fall back to a warehouse lookup (with authorization)** if they can't supply it — reading data for confirmation is allowed (only data *loading/modifying* stays out of scope). |
| 1.5.11 | 2026-06-09 | Correctness fix: ThoughtSpot has **no `CASE`** — the manual-group / range translations now say `if … then … else if … then … else …` (and membership via `or`-chained `if`), not "CASE". |
| 1.5.10 | 2026-06-09 | Promote the VARCHAR-date handling from a note to actual **Step 5a guidance**: detect a Tableau date column bound to a VARCHAR warehouse column, flag it, and offer (a) retype at source → bind as DATE, or (b) a `to_date()` derived column. |
| 1.5.9 | 2026-06-09 | GROUP_BASED cohort on a **DATE** anchor column: conditions use `filter_value_type: DATE_FILTER` + `date_filter_values: [{type: EXACT_DATE, date: MM/DD/YYYY, oper: "="}]` (not `STRING`/`value[]`), `combine_type: ANY` for set membership. Retyping the anchor (VARCHAR→DATE) requires switching the condition shape accordingly. |
| 1.5.8 | 2026-06-09 | Correct the in-place-update rule: **tables also need their root `guid` pinned** to re-import in place — re-importing a table TML without a `guid` can create a duplicate (new GUID) and orphan the original, not update it (observed on Bank). Pin `guid` for tables/models/liveboards alike; verify the returned `id_guid`. |
| 1.5.7 | 2026-06-09 | Two data-fidelity notes (from Bank): (1) a date-like column stored as **VARCHAR** should be flagged + offered a fix (retype at source, or `to_date()` derived column) so date buckets/Spotter work. (2) A `categorical-bin`'s values are a **snapshot of the TWB's data** — if the warehouse holds different data, the cohort matches nothing (silently empty); flag as a data-fidelity limitation, not a translation error. |
| 1.5.6 | 2026-06-09 | GROUP_BASED cohort specifics (from a working column set): each condition needs **`filter_value_type`** (STRING/DOUBLE/…) + `combine_type`; config `combine_non_group_values: true` + `null_output_value`; `operator: EQ` with a multi-value list = "in set". **Convert group values to the column's STORED format, not Tableau's display** (`01.Apr.15` → `2015-04-01`) or they match nothing. |
| 1.5.5 | 2026-06-09 | Add the **cohort-vs-formula decision for manual groups**: contiguous non-overlapping ranges → an `if/then/else if` formula (cleanest; ThoughtSpot has no `CASE`); arbitrary/interleaved value sets → `GROUP_BASED` cohort (a range formula would misclassify). Decide by checking group membership/contiguity first; parse string dates with `to_date` for range tests. |
| 1.5.4 | 2026-06-09 | Fix misclassification: Tableau **`categorical-bin`** (manual value groups — even when the field is named "… clusters") is **translatable** → `GROUP_BASED` cohort (`groups[]`/`conditions[]`, `default` → `null_output_value`). **Classify by calculation `class`, not field name.** Only true k-means clustering stays untranslatable. Updated formula mapping, Step A3 tiers, Step 5b. (Found via Bank's "Date Joined (clusters)".) |
| 1.5.3 | 2026-06-09 | Cohort binding fix: a model needs a **set `obj_id`** for a cohort to reference it — a fresh model has none, and `fqn`-only refs fail with "Worksheet not found". Set the model's root `obj_id` explicitly, re-import in place, then point `cohort.worksheet.obj_id` at it (same `obj_id` a liveboard viz uses). Documented in the Bins/cohort section. |
| 1.5.2 | 2026-06-09 | When bins are detected, **prompt the user** for how to create each (F `floor()` formula / C cohort set / B both) with a smart default (F for parameter-driven, C for fixed) — rather than auto-deciding. For the cohort path, **prompt for `minimum_value`/`maximum_value`/`bin_size`** (prompt first; a warehouse lookup is an acceptable fallback). |
| 1.5.1 | 2026-06-09 | Add the **cohort (column set) alternative for fixed-size bins**: dynamic (parameter-driven) bins stay `floor()` formulas, but a **fixed** bin size → a `cohort:` TML object (`BIN_BASED`, `anchor_column_id`, `bins.min/max/bin_size`) bound to the model by `obj_id`, generated as `*.cohort.tml` and imported after the model. Documented in the formula mapping (Bins section) + Step 5b; payload order includes cohorts. |
| 1.5.0 | 2026-06-09 | `Number of Records`/row-count fields → **`count([column])` with a user prompt** for which column (default primary key), not `sum(1)` — carried into dependent formulas (percent-of-total). Updated the formula mapping + Step 5b rules. |
| 1.4.9 | 2026-06-09 | Add **Step 7.5 — confirm the model before liveboards** (present columns/formulas/parameters/Spotter + suggested Search/Spotter test questions; re-import in place on changes). Add `paramctrl` and `flipboard`/`flipboard-nav` to the Step 9a skip list (parameter controls covered by model parameters; Story flipboards have no liveboard equivalent — skip + flag). |
| 1.4.8 | 2026-06-09 | Formula coverage (from Bank workbook): map **Tableau bins** (`class='bin'`) → `floor([x]/size)*size` using the migrated size-parameter; **`TOTAL(SUM(x))`/percent-of-total** → `group_aggregate(..., {}, query_filters())` (same family as Snowflake/Databricks); **`Number of Records`** → `sum(1)`. Reclassify in Step A3 (bins=Native, TOTAL=LOD), add **clustering** to Untranslatable. Updated `tableau-formula-translation.md` with a Bins section + TOTAL rows. |
| 1.4.7 | 2026-06-09 | Record **High Contrast KPIs** theme (user-confirmed), completing all **6/6** curated themes in `references/liveboard-style-themes.md`: neutral `LBC_A`/`GBC_A`/`TBC_A` base, darkest KPI tiles `TBC_I` + `is_highlighted`, **`kpi_hero_font_size: XL`** (extends S/M/L — schema updated), **and vivid warm chart palette (`#FF8C66`/`#FFB399`) with purple KPI sparklines** — the contrast is charts *and* KPI tiles, confirmed intentional (not the neutral charts I'd first assumed). Lesson: a theme's `viz_style` chart palette is an independent design choice — confirm, don't assume neutral or brand-hue. |
| 1.4.6 | 2026-06-09 | Record **Warm Tones** theme (verified TML): `LBC_G`/`CURVED`, KPI tiles `TBC_O`, peach/orange series palette (`#FF8C66`/`#FFB399`). Noted the per-theme dark KPI token varies (K/L/J/O) and to match KPI sparkline `viz_style` to the theme. |
| 1.4.5 | 2026-06-09 | Record **Soft Lavender** theme (verified TML): `LBC_B`/`CURVED`, KPI tiles `TBC_J`, purple series palette (`#6B4E9C`/`#B8A3DC`) — and it also themes the KPI sparklines via per-KPI `viz_style`, a detail the slate themes omit. |
| 1.4.4 | 2026-06-09 | Record **Fresh & Modern** theme (verified TML): `LBC_D`/`CURVED`, KPI tiles emphasized via `TBC_L`, and — unlike the slate themes — a genuine **teal/mint chart series palette** (`#22636B`/`#4ECDC4`). Confirms chart `viz_style` palette varies per theme. |
| 1.4.3 | 2026-06-09 | Record **Cool Professional** theme recipe in `references/liveboard-style-themes.md` (verified TML): `LBC_C`/`SHARP`, KPI tiles emphasized via `TBC_K` + `tile_kpi_color: TKS_A` + `is_highlighted`, neutral-slate chart palette. Document the KPI-emphasis pattern and that border type varies per theme; make the reference file authoritative over the quick-glance token table. |
| 1.4.2 | 2026-06-09 | Document **`chart.viz_style`** (per-series/legend color palette — the third styling layer) in the answer schema; add `references/liveboard-style-themes.md` recording each Step 10.5 theme as brand tokens + `viz_style` palettes (Clean & Minimal recorded from a verified export; others pending reference TML). Step 10.5 now applies all three style layers. |
| 1.4.1 | 2026-06-09 | Add **Step 10e** — group related vizzes into labelled sections (KPIs → "Key Metrics"; shared-dimension charts → a named section) and require clear `answer.name` + one-line `answer.description` on every viz (no raw `Sheet 1` titles). Clarify KPI trend needs the date in `chart_columns` **and** axis `x`. |
| 1.4.0 | 2026-06-09 | Add **Step 10.5 — Liveboard style**: offer 6 curated themes (Clean & Minimal, Cool Professional, Fresh & Modern, Soft Lavender, Warm Tones, High Contrast KPIs) that write `style.style_properties` + per-object `style.overrides[]` using the `LBC_/GBC_/TBC_/TKS_` color-token system; ask once and reuse across a batch. Document the full styling layer (tokens, scopes, hex reference, overrides, themes) in the liveboard schema; clarify it is TML-level styling, distinct from embed-time `--ts-var-*` CSS theming. |
| 1.3.0 | 2026-06-09 | Add **Step 5.5 — Spotter enablement** (default Y; `model.properties.spotter_config.is_spotter_enabled`) + Spotter line in the Step 7 review, mirroring snowflake/databricks. Rewrite liveboard generation (Step 9/10) from verified behaviour: bind vizzes by **`obj_id`** not `fqn`; emit a **complete chart block** (`chart_columns`+`axis_configs`) using **resolved** column names (`Total {Measure}`, `{Bucket}(date)`); dotted date buckets (`[Order Date].monthly`); note tiles use `note_tile.html_parsed_string` (not `viz_type: NOTE_TILE`); KPI blocks → one KPI tile per measure with a date (0→static / 1→auto / 2+→prompt); export-then-patch loop for resolved names; skip filter/legend zones. **Extracts no longer blanket-skipped** — resolve the underlying source (CSV/Excel/db) and migrate that. `db_column_name` must match the warehouse's (possibly normalized) column name. Document the in-place-update trap: models/liveboards need a root `guid` or `--no-create-new` duplicates them. Companion doc updates: liveboard schema (note tiles, groups/sections + `group_layouts`, viz `obj_id`, expanded `style_properties`) and answer schema (`client_state_v2` structure). |
| 1.2.0 | 2026-06-09 | Add Step 4.5 — present the Step 3 table inventory and ASK whether tables exist / don't exist / unsure; search ThoughtSpot only when the user says exist or unsure (never auto-search up front). Fix table-TML contract: `connection.name` is **required** (was wrongly "no connection section") — a table must bind to a connection that exposes the physical table. **Removed placeholder db/schema and the connection `skip` path entirely** (no dry-run mode) — a TS table is a live object over an existing connection, so emitting stubs only yields unusable objects; if no connection exists, stop. Aligns table TMLs with the shared schema and the snowflake/databricks skills. Fix import I/O: `ts tml import` reads a **JSON array of TML strings** on stdin (not a zip); build payload tables→sql_views→models; add `--create-new` for fresh objects; clarify that `Table with id null not found` is a benign new-table WARNING (no GUID → matches by db/schema/dbTable), distinct from `connection not found`/`column not found` ERRORs. Add a Step 7 **review checkpoint** (mirrors snowflake/databricks): present per-formula translations `source → ts_expr` with tiers, flag pass-through and untranslatable/OMITTED items, and offer yes/no/file — so caveats and un-migratable items surface before import, not only in the Step 12 report. Search/confirm only, never loads data |
| 1.1.0 | 2026-06-09 | Custom SQL → sql_view TML, connection listing, formula fallback, obj_id fix, datasource separation |
| 1.0.0 | 2026-06-09 | Initial release — merged from ts-model-from-tableau + ts-liveboard-from-tableau |
