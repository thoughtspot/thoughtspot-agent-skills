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
| [../../shared/worked-examples/tableau/combo-dual-axis-custom-chart-config.md](../../shared/worked-examples/tableau/combo-dual-axis-custom-chart-config.md) | Step 10a — durable dual-axis combo (line+column) via `custom_chart_config` |
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth setup |
| [../../../tools/ts-cli/README.md](../../../tools/ts-cli/README.md) | `ts spotter answer` — the Spotter last-mile command (Step 12.6) |
| [references/open-items.md](references/open-items.md) | Known validation quirks and workarounds |
| [references/coverage-matrix.md](references/coverage-matrix.md) | Canonical mapped/unmapped construct matrix — cite in Audit mode (A4) and the migration report (Step 12) |
| [references/liveboard-style-themes.md](references/liveboard-style-themes.md) | Step 10.5 curated themes — brand tokens + per-chart `viz_style` color palettes |
| [references/step-3-parse-fields.md](references/step-3-parse-fields.md) | Step 3 TWB field-by-field extraction detail (relation wrapper handling, per-element field mapping, SQL dialect notes, blend date-grain resolution) |
| [references/step-5-tml-generation.md](references/step-5-tml-generation.md) | Step 5 TML generation detail — hard rules, hand-assembly templates, parameter type mapping, formula edge cases, Tableau Sets → column/query sets |
| [references/step-7-review-templates.md](references/step-7-review-templates.md) | Step 7 review-checkpoint and import display templates |
| [references/step-10-liveboard-generation.md](references/step-10-liveboard-generation.md) | Step 10 liveboard generation detail — KPI template, per-encoding search-query rules, liveboard TML template |
| [references/audit-mode-report.md](references/audit-mode-report.md) | Step A4 audit-mode coverage report templates |
| [references/migration-report-format.md](references/migration-report-format.md) | Step 12 migration report format |

---

## Context budget — never Read big tool-output files

This skill's CLI commands write substantial JSON/TML to disk — on a real workbook, `ts
tableau parse` output, `classify-formulas`/`translate-formulas` output, and the generated
TML directory can each run to tens of thousands of tokens. **Never use the Read tool on
these `--out`/`--output` files:**

- `{workbook_name}_parsed.json` (`ts tableau parse`, Step 3)
- `classification.json` / `{workbook_name}_classification.json` / `classification_tiers.json` (`ts tableau classify-formulas`, Steps A3/A4/6/7)
- `formulas_translated.json` (`ts tableau translate-formulas`, Step 5b)
- `table_columns.json`, `parameters.json`, `calc_id_map.json`, `param_name_map.json`, `column_name_map.json`, `table_name_map.json` (intermediate mapping files, Steps 3/5b)
- The generated `*.table.tml` / `*.model.tml` (incl. `*.phase0.model.tml`) / `*.sql_view.tml` / `*.cohort.tml` / `*.liveboard.tml` files under `/tmp/ts_tableau_mig/output/{workbook_name}/`
- `dashboard_spec.json` (input to `ts tableau build-liveboard`, Step 10c)

Instead: consume the command's **stdout compact summary** (the counts, `stats`,
`tier_counts` each command already prints); or `json.load()` the file from disk inside a
Python snippet and print only the fields the step needs; or, only when debugging one
specific failure, Read a targeted excerpt with `offset`/`limit`.

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
- **One `build-model` call per workbook, not one per datasource** (Step 5a/5b) — it already
  emits every used datasource's Model + Table TML in a single invocation. Then one `ts tml
  lint --dir` and one `ts tableau verify --dir` over the whole output directory (Step 6) —
  not one lint/verify per model. A 3-datasource workbook needs 1 build-model + 1 lint + 1
  verify, not 3 of each.
- **Never `--help` a `ts tableau`/`ts tml` command this skill documents.** Every step below
  gives the exact, copy-pasteable invocation (real flag names, from the command's own
  `--help`) — use it as written rather than probing the CLI to rediscover flags it already
  tells you.

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

Translatable tiers: `native`, `lod`, `cumulative`, `pass_through`,
`row_offset_native`, `parameter_ref`. Untranslatable tiers: `untranslatable`,
`row_offset_ambiguous`, `window_ambiguous`, `geospatial`, `circular`, `orphan`, `parameter_query`.

The table below maps those tiers to the human-readable categories used in the report —
kept as reference/documentation now, not as executed classification logic:

| Tier | Description | Examples |
|---|---|---|
| **Native / Set** | Direct ThoughtSpot mapping exists | IF/THEN, IFNULL, DATEDIFF, LEFT, ABS, ROUND, IIF; **bins** (`class='bin'`) → `floor([x]/size)*size` or BIN_BASED cohort; **manual groups** (`class='categorical-bin'`, incl. fields named "… clusters") → `GROUP_BASED` cohort; `Number of Records`/row counts → `count([column])` (**prompt** for the column; default the primary key); **static sets** (`<group>` with `union`/`member`) → `GROUP_BASED` column-set cohort — incl. ones anchored on a **formula column**, with a **`%null%`** member (via `EQ {Null}`), or an **`except` member-list** (via `NE`) (Phase 2a); **Top-N/Bottom-N sets** (`function='end'`) → query set (`cohort_type: ADVANCED`, `COLUMN_BASED`) via a rank formula + parameter-filter formula (Phase 2b); **condition-based sets** (`function='filter'`) → query set with aggregate condition formula (Phase 2c); **member-list intersect** → `GROUP_BASED` cohort of common members (Phase 2c); **all-except-Top-N** → query set with inverted rank filter (Phase 2c); **computed set operations** (intersect/except of mixed types) → multi-formula query set (Phase 2c) |
| **LOD** | LOD expression → `group_aggregate()` | `{FIXED dim : SUM(col)}`; **`TOTAL(SUM(x))`** / percent-of-total → `group_aggregate(..., {}, query_filters())` |
| **Cumulative** | Running calculation → `cumulative_*()` | RUNNING_SUM, RUNNING_AVG |
| **Pass-through** | Valid SQL but no native function → `sql_*_aggregate_op()` | Partitioned RANK, DENSE_RANK |
| **Partial / Unmapped (sets)** | Tableau set construct with no current ThoughtSpot equivalent — logged as deferred, never mis-translated | **set controls** (`level-members` only, no fixed members) → no set object, surface as a liveboard filter; **set actions** (`<action>`) → no equivalent |
| **Row-offset (pass-through)** | `SIZE()` only → answer-level `sql_int_aggregate_op("COUNT(*) OVER()")` | `SIZE()` — only row-offset that still requires SQL pass-through ⚑ flag PT1 |
| **Untranslatable (row-offset ambiguous)** | Row-offset table calcs with unrecoverable intent — omitted | `INDEX`/`LOOKUP`/`FIRST`/`LAST` unconditionally omitted and flagged as untranslatable — no deterministic ThoughtSpot equivalent across all addressing contexts |
| **Untranslatable (window ambiguous)** | Window table calcs — omitted | `WINDOW_SUM`, `WINDOW_AVG`, `WINDOW_MAX`, `WINDOW_MIN`, `WINDOW_COUNT`, `WINDOW_STDEV`, `WINDOW_VAR`, `WINDOW_MEDIAN`, `WINDOW_PERCENTILE` unconditionally omitted and flagged as untranslatable — require worksheet addressing context (sort/partition attributes) this pipeline does not resolve |
| **Untranslatable** | No ThoughtSpot equivalent — will be omitted | `PREVIOUS_VALUE` (true recursion — not the string-aggregation technique); true **k-means clustering** (the analytics-engine "Clusters" calc — **not** `categorical-bin`); **geospatial** — full 13-function set (`MAKEPOINT`, `MAKELINE`, `BUFFER`, `OUTLINE`, `DISTANCE`, `AREA`, `LENGTH`, `INTERSECTS`, `SHAPETYPE`, `DIFFERENCE`, `INTERSECTION`, `SYMDIFFERENCE`, `VALIDATE`) — decompose `MAKEPOINT` lat/lon args to individual attribute columns, omit the spatial formula (see `tableau-formula-translation.md` Geospatial Policy); **embedded-RLS user attributes** (`USERATTRIBUTE`, `USERATTRIBUTEINCLUDES`) — rejected at translate time, see BL-071 |
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

**Per-file report, per-datasource breakdown, and combined multi-workbook summary:**
See [references/audit-mode-report.md](references/audit-mode-report.md) for the full
templates — tier/cross-reference-depth/complexity tables, the coverage-math breakdown,
orphan/needing-review/excluded-formula tables, the data-blending risk table, and the
row-offset/SQL-lookup/pass-through mini-templates.

**Migration coverage** includes everything except Untranslatable. All parameter types
are auto-migratable: static params are created directly in the model TML; SQL-lookup
params are populated by querying the warehouse at migration time. The formula reference
`[Parameters].[Name]` is rewritten to `[Name]` in both cases. Cite
[`references/coverage-matrix.md`](references/coverage-matrix.md) as the canonical source
when classifying a construct as mapped/unmapped or explaining a limitation.

Write the report to `/tmp/ts_tableau_mig/audit/{workbook_name}_audit.md` and display
it inline.

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
ts auth whoami --profile "{profile_name}"
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
  ts metadata search --guid {model_guid} --profile {profile_name}
  ```
  Verify `metadata_type == "LOGICAL_TABLE"` and `metadata_header.worksheetVersion == "V2"`.
  If V1 (a classic worksheet) or not found, say so and re-ask.
- **N (name it)** — exact-name search, filter to V2:
  ```bash
  ts metadata search --subtype WORKSHEET --name "{model_name}" --profile {profile_name}
  ```
  Exactly one V2 match → use it; none/ambiguous → show closest and re-ask.
- **F (filter)** — `--name "%{partial}%"`, keep V2 matches, show a short numbered list
  (name, obj_id, guid) and pick from it.
- **L (list all)** — **warn it's slow**, then `--subtype WORKSHEET --all`, keep V2, show the
  numbered list. Only use when the user can't name/filter.

```bash
# F / L pattern (filter applied client-side to V2 only)
ts metadata search --subtype WORKSHEET --name "%{partial}%" --profile {profile_name}
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

See [references/step-3-parse-fields.md](references/step-3-parse-fields.md) "Redshift and Postgres dialect notes" for the pass-through SQL (`sql_*_op`)
dialect differences from Snowflake (string concat, date truncation, `LISTAGG`, type casting).

See [references/step-3-parse-fields.md](references/step-3-parse-fields.md) for the full field-by-field extraction rules: relation-wrapper handling (the
three TWB XML wrapper shapes to check in order), and per-relation/element extraction for
physical tables, Custom SQL relations, joins, physical columns, calculated fields, and
parameters.

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

See [references/step-3-parse-fields.md](references/step-3-parse-fields.md) "Blend date-grain linking columns (Step 3e)" for how mismatched date grains
between the blend's source and target columns are detected and resolved (date-truncation
formula + SQL View materialization vs a direct join when grains already match).

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

**What the TWB does NOT contain** (it lives only in the published datasource's `.tds`):
- The **physical table structure** (table names, joins, db/schema/table paths)
- The **connection details** (database, schema) that link to the warehouse

This means **formula extraction and translation work without the physical model** — the
`.tds` adds physical table resolution and join definitions, not the formulas.

> **Where the physical model actually is — and how to get it.** The join/table structure is
> **not** returned by the field API. `ts tableau datasource --fields` (VizQL `read-metadata`)
> returns **columns/calcs only**, not tables or joins. The full physical model (tables, joins,
> custom SQL) lives in the published datasource's **`.tds`**. Two ways to obtain and parse it:
> - **Download it** (needs Tableau access): `ts tableau download {datasource_id}` fetches the
>   `.tdsx`; the `.tds` inside carries the model.
> - **Be supplied it**: the user provides the `.tds`/`.tdsx` alongside the `.twb`.
>
> Then **`ts tableau parse` accepts a `.tds`/`.tdsx` directly** (ts-cli ≥ 0.38.0) — its root
> *is* the `<datasource>`, and parse extracts its tables/joins/columns/calcs just like a
> workbook datasource. Feed that to `build-model` GENERATE mode and it builds the multi-table
> model automatically — **no hand-assembly** (see Step 5b "Multi-query datasources"). Without
> the `.tds` (only the `.twb`, no Tableau access), fall back to the hand-built multi-table base
> in Step 5b.

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
- `ts` CLI v0.73.0+ (includes `ts tableau build-model` with `--max-retries`, enriched error
  reporting, GENERATE mode output, and `--table-name-map`)

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
ts metadata search --subtype ONE_TO_ONE_LOGICAL --name "%{table_name}%" --profile {profile_name}
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
ts connections create \
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
ts connections list --profile {profile_name}
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
   ts connections get {connection_id} --profile {profile_name}
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

> **Prerequisite:** ts-cli v0.77.0+.

`ts tableau build-model` (GENERATE mode, no `--existing-guid`) emits Table TML
automatically — **no hand-assembly**. **Run it ONCE for the whole workbook** (below) —
the same call also emits every datasource's Model TML (Step 5b), so 5a and 5b describe
one command's two outputs, not two commands. It writes one `.table.tml` per physical
table identified in Step 3 with `type="table"` to `{output_dir}/{TABLE_NAME}.table.tml`,
across every datasource the workbook uses — a table shared by multiple datasources (e.g.
Set Control's `Orders`, used by all 3 of its datasources) is written once and shared, not
regenerated per datasource. **Custom SQL relations are excluded** — those are handled in
Step 5c.

```bash
ts tableau build-model "{workdir}/{workbook}.twb" --connection "{connection_name}" \
  --output-dir {output_dir} --database "{database}" --schema "{schema}"
```

Pass `--database`/`-D` and `--schema`/`-s` with the `db`/`schema` values resolved in
Step 4.5, so the emitted table(s) bind to the real physical location. Optional flags:
`--datasource "{name}"` scopes the call to one datasource — use it only to intentionally
narrow (e.g. re-running after fixing one datasource's `--table-name-map`), never as a
default per-datasource loop; `--model-name "{name}"` overrides the derived model name
(only meaningful together with `--datasource`); `--dry-run` reports without writing files.

- **Single-table datasources** (the common case): one `.table.tml` with every
  physical column.
- **Multi-table datasources**: one `.table.tml` per table, columns assigned to their
  owning table. A column whose owning table can't be resolved from the parse is left
  off every table (never guessed onto one) and reported in the result JSON's
  `table_columns_unassigned` — **reconcile these with the user before import** (confirm
  the correct table and add the column by hand, or fix the mismatch upstream via
  `--table-name-map` if it's really a table-naming issue).

Follow all rules in `tableau-tml-rules.md` when reviewing the emitted file — in
particular **db_column_name accuracy** (a warehouse loader can normalize names
differently than the TWB), **date-stored-as-VARCHAR** detection, and the
**partial-date-string** pattern (`tableau-tml-rules.md` "Date Column Rules"):
`build-model` carries over the TWB's own type/name metadata and has no live-schema
visibility, so these are still worth a human check before import. Validation
(Step 6) surfaces a wrong binding as `connection not found` or
`column not found in connection`.

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
That's a rule about the **output** (strict separation between models), not an instruction
to run the command once per datasource — see below. How each datasource's model TML is
produced depends on whether it participates in a blend:

**Single-datasource models (the common case — no blend) — GENERATE mode, ONE call for
the whole workbook.** When a datasource has no entry in `blend_graph` (from Step 3e), its
base model TML comes from `ts tableau build-model` in GENERATE mode (no `--existing-guid`)
— **this is the exact same call already made in Step 5a, not a second invocation**:

```bash
ts tableau build-model "{workdir}/{workbook}.twb" \
  --connection "{connection_name}" \
  --output-dir {output_dir} \
  --database "{database}" --schema "{schema}" \
  [--table-name-map {workdir}/table_name_map.json]
```

Run it **once per workbook, with no `--datasource`** — it emits every non-blended
datasource's model + table TML in that single call. A 3-datasource workbook (e.g. Set
Control) emits 3 `{slug}.model.tml`/`{slug}.phase0.model.tml` pairs plus the shared
`.table.tml` file(s) from this **one** call — never 3 separate `build-model` runs. Pass
`--datasource "{datasource_name}"` only when you intentionally want to (re)build just one
datasource (e.g. retrying after fixing that datasource's `--table-name-map` entry) — do
NOT loop it per datasource as the default flow.

This runs the same TWB-parse → translate → assemble pipeline described below and writes,
**for each datasource**, two model TML files: `{slug}.phase0.model.tml` (base —
`model_tables`, physical `columns`, `joins`, `parameters`; **no formulas**) and
`{slug}.model.tml` (full model with all formulas, topologically ordered). Step 7 Phase 1
imports each `*.phase0.model.tml` as that datasource's base model. Formulas are added
independently in Step 7 Phase 2, via a separate `build-model --existing-guid` call **per
model** — that phase is inherently one-call-per-GUID (each already-imported model has its
own GUID to merge into) and is unaffected by the "one call" rule above.

`--table-name-map` (optional): a JSON file `{"twb_table_name": "thoughtspot_table_name"}`,
applied workbook-wide (one file covers every datasource's renames — it's looked up by
table name, not scoped to a single datasource). Supply it **only** when the ThoughtSpot
table's TML `name` (from Step 5a) differs from the TWB relation name — warehouse-
normalized names, or a published-datasource TWB where the relation is literally named
`sqlproxy`. Omit the flag when the names already match; the default (no map) behavior is
unchanged.

**Published/sqlproxy datasources bound to an existing table/view — reconcile columns.**
When the datasource is published (`sqlproxy`) and binds to a pre-existing ThoughtSpot
table/view (the consultant/stand-in case), the emitted columns carry Tableau's
`(Custom SQL Query N)` suffixes and may diverge from the view's real names. This is a
deliberate, targeted exception to the "one call for the whole workbook" rule above — each
`--reconcile-table` run binds one specific datasource to one specific existing table GUID,
so `--datasource` is required here, not a loop to avoid. Reconcile:

1. **Plan** — get suggested mappings + drops (no write). `--reconcile-table` requires
   `--profile` (the CLI hard-exits with "--profile is required when using
   --reconcile-table" otherwise):
   ```bash
   ts tableau build-model {workdir}/{workbook}.twb --connection "{connection_name}" \
     --datasource "{datasource_name}" --output-dir {output_dir} \
     --table-name-map {workdir}/table_name_map.json --reconcile-table {table_guid} \
     --reconcile-plan --profile {profile_name}
   ```
2. **Confirm with the user** — present the Plan JSON's `suggested_mappings` (each
   `{from, to, confidence}`) and `unmatched_drop` (columns with no confident match,
   which will be dropped). The Plan has no formula field — formulas that reference a
   dropped column are only known after Apply, surfaced in the result's
   `reconcile_dropped.formulas` (and the Step 12 report), so don't present formula
   impact at this stage. The user confirms/edits each mapping. Write the confirmed
   mappings as a flat `{"<from>": "<to>"}` JSON object (from `suggested_mappings`'
   from/to, dropping confidence) to `{workdir}/column_name_map.json` — **keep it in
   `{workdir}`, NOT `{output_dir}`**: Step 6/7 import with `ts tml import --dir {output_dir}`
   scans `.json` files, so a map file left in the output dir is wrongly ingested as TML.
3. **Apply** — re-run with the confirmed map (writes phased TMLs that bind):
   ```bash
   ts tableau build-model {workdir}/{workbook}.twb --connection "{connection_name}" \
     --datasource "{datasource_name}" --output-dir {output_dir} \
     --table-name-map {workdir}/table_name_map.json --reconcile-table {table_guid} \
     --column-name-map {workdir}/column_name_map.json --profile {profile_name}
   ```

Column-id qualification and suffix/junk stripping are automatic (Tier-1) for every run.
Dropped columns + their formulas appear in the result JSON's `reconcile_dropped` and the
Step 12 report.

Still apply the **Model TML hard rules**, MEASURE/ATTRIBUTE classification guidance, and
Template (see [references/step-5-tml-generation.md](references/step-5-tml-generation.md)) when
**reviewing** the generated `*.phase0.model.tml` — they describe the required shape regardless
of how the file was produced.

**Multi-query datasources** (one datasource that JOINS several Custom SQL Queries server-side)
need a **multi-table model**, not the single table GENERATE mode / `--reconcile-table` produce
— binding to one table silently filters every formula referencing another query's columns as
"Unresolved Custom SQL Query alias" while the base model still imports and looks clean. Prefer
parsing the published datasource's `.tds` (Step 3.5) — `ts tableau parse {file}.tds` +
`build-model` (GENERATE mode) builds the multi-table model automatically. Without a `.tds`,
hand-assemble it. See [references/step-5-tml-generation.md](references/step-5-tml-generation.md)
"Multi-query datasources" for the detection signal and the full hand-assembly procedure.

**Blend-merged models** (multiple datasources connected by a Tableau data blend) need a
**single merged model** built by hand from the `blend_plan` Step 3 emits (`components`,
`ds_table_map`, `joins`) — GENERATE mode only builds one model per single datasource and
cannot produce the cross-datasource joins a blend requires. See
[references/step-5-tml-generation.md](references/step-5-tml-generation.md) "Blend-merged
models" for the full merge procedure (per-component assembly, applying `blend_plan` joins, the
cardinality heuristic, and column-name-conflict disambiguation).

The `model_tables[]` section references both regular tables (from Step 5a) and SQL
Views (from Step 5c) — both are referenced by `name` in the same way.

**Model name:** use the Tableau datasource display name — no prefix (no `TEST_` or environment
markers). Ask the user if they want a different name before importing. See
`../../shared/schemas/ts-model-conversion-invariants.md` (N1).

**Model TML hard rules** and **MEASURE vs ATTRIBUTE classification** — these apply to every
model this step generates; violations cause silent data loss or import rejections with no
clear error. See [references/step-5-tml-generation.md](references/step-5-tml-generation.md)
"Model TML hard rules" for the full I1–I6 list and the classification guidance, and "Template
(hand-assembly shape)" for the YAML structural reference (used directly for blend-merged
models, and as the review reference for GENERATE-mode output).

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

Optional flags (omit unless needed): `--csq-map {workdir}/csq_map.json` — maps a Custom
SQL Query alias to its table name, needed when a formula references a Custom SQL relation
by alias; `--date-columns COL_A,COL_B` — comma-separated date columns to rewrite date
arithmetic against.

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

See [references/step-5-tml-generation.md](references/step-5-tml-generation.md) "Parameter
migration — type mapping and invariants" for the full `param-domain-type`/`datatype` →
ThoughtSpot `data_type`/config mapping table.

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

See [references/step-5-tml-generation.md](references/step-5-tml-generation.md) "Parameter
migration — type mapping and invariants" for the critical parameter invariants (string-typed
`range_config` values, inlining a formula referenced inside `sum()`, and reading back the
assigned parameter UUID for Step 10f).

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

Formula translation rules: use `tableau-formula-translation.md`. Convert Tableau join types
(`full`→`OUTER`, `left`→`LEFT_OUTER`, `right`→`RIGHT_OUTER`, `inner`→`INNER`); write formulas in
topological dependency order (Level 0 first); resolve Tableau internal IDs
(`[Calculation_\d+]`) to display names before translating. LOD expressions
(`{FIXED}`/`{INCLUDE}`/`{EXCLUDE}`) → `group_aggregate()`.

See [references/step-5-tml-generation.md](references/step-5-tml-generation.md) "Formula
translation rules — edge cases and special patterns" for the full rule set: Tableau bins (ask
floor-formula vs cohort vs both), manual groups (`GROUP_BASED` cohort vs an if/then formula),
`Number of Records`, formula-id cross-references, model- vs answer-level formulas,
growth/decline, running/rank/window functions, the pass-through fallback, the
FIRST/LAST/LOOKUP/PREVIOUS_VALUE → LISTAGG string-aggregation technique, geospatial formulas,
embedded-RLS user attributes, the full **row-offset table-calculation decision tree**
(INDEX/LOOKUP/FIRST/LAST/SIZE — Top-N-filter vs native-rank vs native-window-function vs
omit+log, with sort-column resolution), multi-column join-key handling (when a needed key
doesn't physically exist), and cross-datasource (blend) formula reference resolution.

### Tableau Sets → ThoughtSpot column sets (Phase 2a)

> **Construct distinction:** A Tableau **set** is a top-level `<group ...>` element — entirely
> different from a **manual group** (`<column><calculation class='categorical-bin'>`, handled
> above as a `GROUP_BASED` cohort). Sets are identified by the `<group>` XML element; manual
> groups by the calculation `class`. Do NOT confuse the two.

Scan for top-level `<group>` elements and classify each by its `<groupfilter>` tree shape: a
**static** member list (Phase 2a → `GROUP_BASED` column set), a **Top-N/Bottom-N** set (Phase
2b → an `ADVANCED`/`COLUMN_BASED` query set, static or parameter-driven), or an
`except`/`intersect`/condition-based/computed set operation or a dynamic **set control** (Phase
2c — column set, query set, or a plain interactive filter, depending on shape). See
[references/step-5-tml-generation.md](references/step-5-tml-generation.md) "Tableau Sets →
ThoughtSpot column sets (Phase 2a/2b/2c)" for the full per-pattern detection, extraction, and
TML-emission rules (including the IN/OUT `sum_if` translation patterns, the Column-set and
Query-set TML templates, and a worked multi-formula example).

**Emit one `*.cohort.tml` per set** and import cohorts after the model (the payload order in
Step 5.5 already includes `*.cohort.tml`). **Import order for query sets: model (with
parameter) → cohort** — the set's formula references the parameter, which must exist on the
model first.

> **⚠ MANDATORY — flag every set conversion for the user to review.** Set conversions are
> *semantic reinterpretations*, not literal 1:1 translations. For **each** set, surface its
> outcome and ask the user to confirm it matches intent, in **both** the Step 7 review
> checkpoint and the Migration Summary (Step 10g) / Step 12 report — see the reference above
> for the per-set review-line format and which reinterpretations especially need a human eye.

### 5c. SQL View TML — one per custom SQL relation

**As of ts-cli v0.37.0, `ts tableau build-model` emits these automatically** — one
`{model}.{ViewName}.sql_view.tml` per Custom SQL relation, ordered before the model
files so the SQL View exists first (the model references it by name in `model_tables[]`;
no GUID needed). You no longer hand-write them in the normal flow. The template (linked
below) is the reference for the generated shape and for hand-authoring edge cases (e.g. a
Tableau parameter embedded in the SQL, `<[Parameters].[…]>`, which needs substitution).

For each custom SQL relation identified in Step 3b (those with `source_type: "custom-sql"`),
a `.sql_view.tml` file is generated. Follow the rules in `tableau-tml-rules.md` "SQL View
TML Rules" and the full schema in `thoughtspot-sql-view-tml.md`.

**Template:** see [references/step-5-tml-generation.md](references/step-5-tml-generation.md)
"SQL View TML template (Step 5c)" for the full YAML shape.

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
it), via `--order tableau`:

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

`ts tml lint` reads the same `--dir`/`--order` input as `ts tml import`
and exits non-zero on any finding, so it gates the import. **Run it once over the
whole output directory** — not per model file — so the cross-reference check
(model→table/sql_view) sees every table alongside every model in one pass:

```bash
ts tml lint --dir /tmp/ts_tableau_mig/output/{workbook_name} --order tableau
```

Optional flags (rarely needed here): `--model-phase base` drops `*.phaseN.model.tml`
for N>=1 (keeps bare `.model.tml` and `.phase0.model.tml` — not relevant to this skill's
2-file phase0/full split); `--pattern '{glob}'` restricts `--dir` to matching filenames.

Do not import until it reports `"clean": true`. Fix any finding and re-lint.

#### Migration-fidelity gate (`ts tableau verify` — silent drops + mistranslations)

> **Prerequisite:** `--dir` (below) requires ts-cli v0.83.0+. On an older CLI, fall back
> to one `--model` call per base Model TML file.

`ts tml lint` proves the TML is *structurally* valid; it does not prove the model is a
faithful copy of the workbook. Run **`ts tableau verify`** to diff the parsed TWB
(Step 3's `{workbook_name}_parsed.json`) against each generated **base** Model TML. It
catches what a TWB-only coverage count and a server-side `VALIDATE_ONLY` import both miss:

- **Silent drops** — a table, join, or *translatable* formula the workbook had but the
  generated model does not. An untranslatable formula's absence is **not** flagged: tier
  classification is shared with `classify-formulas`, so only a formula that *should* have
  been carried across counts as a drop.
- **Mistranslations** — a formula whose TML translation barely resembles its Tableau
  source (token-level similarity buckets: MATCH / PARTIAL / LOW / MISSING).

**Run it once over the whole output directory with `--dir`** — not once per model:

```bash
ts tableau verify \
  --parse /tmp/ts_tableau_mig/{workbook_name}_parsed.json \
  --dir /tmp/ts_tableau_mig/output/{workbook_name}
```

`--dir` verifies every full Model TML in that directory (`*.model.tml`, excluding the
formula-less `*.phase0.model.tml` base models) in one call, aggregating the per-model
reports into one JSON report + one combined exit code — non-zero if ANY model has an
ERROR. A multi-datasource workbook's models are still each checked independently (no
cross-model coupling); this is one CLI call producing N per-model results, not a
looser check. (`--model {path}` still verifies a single model file on its own, for the
rare case a single model needs re-checking after a fix — optional flags are mutually
exclusive: exactly one of `--model`/`--dir` per call.)

It prints a JSON report to stdout (top-level `models[]`, one entry per model, plus a
`summary` with the aggregate `errors`/`warnings`/`models_with_errors`) and a human summary
to stderr. How to act on it:

- **structural ERROR** (a translatable formula / table / join dropped) — a blocker to a
  *faithful* migration. Investigate before importing: fix the build, or confirm the drop is
  expected (e.g. an orphan calc carved out in Step 3g) and proceed knowingly.
- **formula_equivalence PARTIAL / LOW** (WARNING) — spot-check those formulas' TML against
  the source. A low score is often a legitimate rewrite (e.g. a `DATEDIFF`/`DATEADD` unit
  function whose ThoughtSpot name can't be statically token-matched), not a bug — confirm,
  don't blindly "fix".
- **limitation_coverage** (advisory) — reports how many untranslatable formulas exist; it
  echoes, and does not replace, the Step 11.5 / Step 12 coverage report, which stays the
  authoritative gap list.

Treat a `structural` ERROR (on any model) as the gate; PARTIAL/LOW and advisory findings
are review prompts. (Cross-reference dangling-ref checking is `ts tml lint --dir`'s job,
above — verify is about source-vs-output fidelity, not TML internal consistency.)

Validate (up to 10 fix cycles). `--policy VALIDATE_ONLY` checks without persisting:

```bash
ts tml import --dir /tmp/ts_tableau_mig/output/{workbook_name} \
  --order tableau --policy VALIDATE_ONLY --profile {profile_name}
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

See [references/step-7-review-templates.md](references/step-7-review-templates.md) "Pre-import review summary" for the exact shape (tables created/reused,
model column/parameter/Spotter summary, per-formula translation lines with tier/pass-through/
untranslatable markers, the Sets review lines, the omitted-formula list, blended-model and
HIGH-risk-blend detail, and the yes/no/file prompt).

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
`--order tableau` sorts by TML type (table → sql_view → model → cohort → liveboard).
GENERATE-mode output contains `*.phase0.model.tml` (base) and `*.model.tml` (full);
blend-merged output contains bare `.model.tml` files. Both pass through unchanged.

**Before importing, check for duplicates** — if Phase 1 has already been imported (e.g.
from a retry or previous attempt), search for existing models by name before importing.
If a duplicate exists, delete it with `ts metadata delete` before proceeding, or pin its
GUID and import with `--no-create-new` to update in place.

Import with `--create-new`:

```bash
ts tml import --dir /tmp/ts_tableau_mig/output/{workbook_name} \
  --order tableau --policy ALL_OR_NONE --create-new --profile {profile_name}
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

See [references/step-7-review-templates.md](references/step-7-review-templates.md) "Phase 1.5 — base model review checkpoint" for the exact prompt shape
(model link, table/column/join/parameter counts, the verification checklist, and the
yes/search/no choice).

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
  --output-dir {workdir}/output \
  [--column-name-map {workdir}/column_name_map.json]
```

**`--column-name-map` (published/sqlproxy reconcile only):** if Step 5b produced a
confirmed `{workdir}/column_name_map.json` (the datasource bound to a pre-existing
table/view whose column names diverged, e.g. `DISCOUNT_RED_DOLLAR` → `DM_DISCOUNT_RED_DOLLAR`),
pass the **same** map here. Phase 2 re-derives formulas from the TWB against the live
model, so without the map any formula referencing a renamed column stays bare and is
filtered out. Omit the flag when Step 5b needed no map (names already matched).

This command runs the full formula pipeline internally:
1. Re-parses the TWB to extract calculated fields and parameters
2. **Migrates missing parameters onto the model first** (ts-cli ≥ 0.35.0) — a formula that
   references a parameter the model lacks is unresolvable, so any TWB parameter not already on
   the model is added before formula import. No separate parameter step is needed.
3. Translates all formulas through the transform pipeline
4. Runs `validate_pre_import()` — reports warnings for IN-with-parens, non-existent
   functions (`add_quarters`/`add_years`), bare date literals, unbalanced parens/brackets,
   missing else clauses, and other structural issues
5. Applies `formula_` prefix for cross-references (resolves the I9 invariant)
6. Detects and fixes double aggregation (`sum([formula_X])` where X is already aggregated)
7. **Filters unresolvable references deterministically** (ts-cli ≥ 0.35.0): `sqlproxy::`,
   `Custom SQL Query`, bare column refs, unconverted concat, **qualified `[TABLE::COL]` refs
   whose column is absent from the model**, and the **transitive cross-formula cascade**
   (drop a formula whose referenced formula was dropped) — all caught pre-import, no import
   round-trips
8. Table-qualifies each bare column ref to its **real owning table** (multi-table models),
   not the anchor
9. Merges new formulas into the existing model (skips formulas already present)
10. Imports with up to **10** (CLI default, `--max-retries`) retry cycles, cascade-dropping a
    failing formula's dependents in the same cycle. Because the deterministic classes above
    are caught pre-import, the retry budget is only for genuine server-side rejections — a
    large multi-table model no longer needs a high `--max-retries` (previously exceeding the
    cap rolled the whole ALL_OR_NONE batch back to zero)

Parse the JSON output to report results to the user:

See [references/step-7-review-templates.md](references/step-7-review-templates.md) "Phase 2 — `build-model --existing-guid` JSON output shape" for the exact
field list (`formulas_translated`/`skipped`/`filtered`/`added`, `formulas_dropped_on_import`
with `name`/`expr`/`error`/`original_tableau`, `validation_warnings`, `updated_model_guid`).

**If `formulas_dropped_on_import` is empty (or absent):** Report success. Proceed to
Step 7.5 regardless of migration pace.

**If `formulas_dropped_on_import` is non-empty — behaviour depends on `{migration_pace}`:**

### Fast mode (`{migration_pace}` = `F`)

Report the parked count and a summary table, then move on:

See [references/step-7-review-templates.md](references/step-7-review-templates.md) "Fast mode — Phase 2 complete report" for the exact report shape (imported
count, parked count, and the parked-formula summary table).

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

See [references/step-7-review-templates.md](references/step-7-review-templates.md) "Complete mode — fix cycle complete report" for the exact report shape
(fixed count, remaining-parked count, per-formula fixed/still-parked lists).

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
| `parent_zone` + `param` | the enclosing `<zone>`'s `id` and its `param` (`vert` = vertical container / stacks children top-to-bottom; `horz` = horizontal container / places children left-to-right). **Keep the nesting** — don't flatten to a coordinate list; the container tree is the layout's real structure (9c). |
| `floating` | `floating="true"` on the zone — a free-positioned overlay, not part of a container. Handle separately in 9c. |

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

### 9c. Map the dashboard to the ThoughtSpot 12-column grid

ThoughtSpot liveboards use a **12-column responsive grid** (`layout.tiles[]` with
`x`/`y`/`width`/`height` in grid units). Tableau dashboards are a **tree of horizontal and
vertical layout containers** (with absolute 0–100,000 coords as a fallback). Map the **tree**,
not the raw coordinates — the container structure is what makes the migrated board look like
the source; a flat y-band scan misgroups zones whenever two containers share a y range.

**Container-tree walk (primary method):**

1. **Walk the `<zones>` tree** from 9a. A **`vert`** container stacks its children into
   successive **rows**; a **`horz`** container lays its children **side-by-side within one
   row**. Recurse: a `horz` inside a `vert` is one row split into columns; a `vert` inside a
   `horz` is a column split into stacked rows.
2. **Columns within a horizontal container** — split 12 columns **proportionally to each
   child's `w` relative to its siblings' total `w`** (not the whole dashboard). Normalize with
   **largest-remainder** so `col_span`s sum to **exactly 12** with no slivers: floor each
   share, then hand the leftover columns to the zones with the largest fractional remainders.
   Enforce a **minimum `col_span` of 2** (merge or bump anything smaller) so no tile is an
   unreadable sliver.
3. **Rows / height** — give each row a `row_span` from the zone's **aspect ratio**, so charts
   keep roughly their source shape: `row_span ≈ round(col_span × (h/w) × 0.5)`, clamped to a
   per-type floor — **KPI/number ≥ 3, note/text ≥ 2, chart ≥ 6, table ≥ 8**. Stack rows top to
   bottom, each starting at the previous row's bottom (`y += prev row_span`).
4. **Fallback to the band method** only when the tree is unavailable (rare — e.g. a
   hand-edited TWB with flat zones): group zones within ~2,000 y-units into a band, sort bands
   top-to-bottom and zones left-to-right within a band, then apply the same proportional
   column split + aspect-ratio height as above.

**Floating zones** (`floating="true"`) overlap the tiled layout and have no grid equivalent.
Don't try to reproduce the overlap: place each floating zone as its **own full-or-partial-width
tile** in reading order (by y then x) after the tiled zones, and **note in the Migration
Summary** that it was a floating overlay flattened into the flow.

Save the grid layout as a list of tiles with `zone_id`, `zone_type`, `worksheet_name`,
`col` (x), `col_span` (width), `row_span` (height), `y` — ready for Step 10c. Column spans in
each row must sum to 12; keep a stable left-to-right order matching the source.

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
ts tml export {model_guid} --profile {profile_name}
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
| **dual-axis combo** (two mark classes, e.g. `Bar` + `Line`, on a synchronized/secondary axis) | `ADVANCED_LINE_COLUMN` (Muze) — see the combo rule below |

**Combo / dual-axis rule (Muze path only).** A Tableau **dual-axis** worksheet — two `<pane>`
marks with different mark classes (typically `Bar` + `Line`) and a secondary/synchronized
axis — is a combo chart. On the **Muze** path (Step 10-charts = M) emit `ADVANCED_LINE_COLUMN`
with both measures on `axis_configs.y` and let ThoughtSpot **auto-resolve** the line vs the
column — this imports cleanly. **Do NOT hand-author `chart.custom_chart_config`:** its column
refs are **GUIDs** assigned only after an answer exists, so a fresh import with display names
fails with `Invalid GUID string` (live-verified; `ts tml lint` does not catch it — a real /
`VALIDATE_ONLY` import does). To durably pin the exact line-vs-column split + dual axis, use
capture-and-replay: import the auto-resolved combo, set it in the UI, **export** (the exported
`custom_chart_config` now has real GUIDs), and replay that config on re-import. On the
**Legacy** path (or an older cluster without Muze) split it into a separate COLUMN tile and
LINE tile and flag the merged axis as a migration gap. Full detail + both paths:
[`../../shared/worked-examples/tableau/combo-dual-axis-custom-chart-config.md`](../../shared/worked-examples/tableau/combo-dual-axis-custom-chart-config.md).

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

See [references/step-10-liveboard-generation.md](references/step-10-liveboard-generation.md)
"KPI viz template (Step 10a)" for the full KPI viz YAML (substitute column names, UUIDs, and
colors).

### 10b. Build search queries

`search_query` is a ThoughtSpot search string of **bracketed column display names**, not
a "sum sales" phrase. Build it from the worksheet shelves:

See [references/step-10-liveboard-generation.md](references/step-10-liveboard-generation.md)
"Build search queries — per-encoding rule set (Step 10b)" for the full rule set: measure/
dimension/date-bucket references, Top-N + sort fidelity, currency/number/percent column
`format`, Color-shelf/small-multiples fidelity (Muze `slice-with-color`/`trellis-by` vs
Legacy), cumulative/moving measures, the two growth/decline forms (`growth of` keyword vs an
answer-level period-comparison formula with a worked example), and answer-level vs model
formula placement.

### 10c. Build liveboard TML

**Emit the base Answer + Liveboard TML deterministically — don't hand-write it.** Assemble a
dashboard spec from Steps 9/9b/9c and run:

```bash
ts tableau build-liveboard --input dashboard_spec.json --output-dir ./out
```

Optional flags (only needed if `--input` is a bare `ts tableau parse` output rather than a
full spec — not the case here, since the spec below already carries `model_name`):
`--model-name`, `--model-fqn` (GUID — more robust than name), `--report-name`.

The spec is one object per dashboard → visuals → fields, each field tagged with its Tableau
`shelf` (`columns`/`rows`/`color`) or an explicit `role`, plus `measure: true/false`; carry
the Step 9c grid placement as each visual's `tile`. The command does the role-aware axis
layout (Columns→x, Color→series/color, Rows→pivot rows, measures→y — a `PIVOT_TABLE` gets
`axis_configs` or it renders blank), applies the chart-type requirement floor (flags a chart
short of the measures it needs — never silently downgrades), and assembles one tabbed
liveboard with every answer embedded. Full spec shape: `tools/ts-cli/README.md`
(`ts tableau build-liveboard`) / `ts_cli/tableau/liveboard.py`.

**Presentation polish rides in the spec, not a second hand-edit pass.** Anything the
auto-builder can't express — a hand-tuned **combo/dual-axis** (`custom_chart_config`, Step
10a), a **KPI sparkline** (`client_state_v2`, Step 10a), per-column **`format`** (Step 10b),
or a **theme** `viz_style` (Step 10.5) — goes on that visual's `override` (verbatim answer
spec) or `formats`/`client_state_v2`/`custom_chart_config`/`viz_style` keys, which the
command replays into the emitted TML. Add tiles with no Tableau source visual via
`extra_visuals[]`.

> The command consumes a spec you assemble from the Step 9 parse; fully **extracting** the
> per-visual shelves/roles inside `ts tableau parse` (so the spec is produced end-to-end with
> no hand-assembly) is a tracked follow-on — see open item #20.

See [references/step-10-liveboard-generation.md](references/step-10-liveboard-generation.md)
"Liveboard TML template (Step 10c)" for the full YAML — the reference for what the command
emits, and the shape to match when hand-tuning an `override`. Follow
`../../shared/schemas/thoughtspot-liveboard-tml.md` exactly.

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

> **A parameter chip is only valuable when a formula that CONSUMES the parameter is on the
> board (live-verified 2026-07-05).** ThoughtSpot **drops any unreferenced parameter** on
> import ("Dropping unreferenced parameters … ordered chips … will be dropped") — so adding a
> chip for a param no tile uses is not just pointless, it fails. Map Tableau parameters by how
> they're used:
> - **A model formula consumes the param as a value** (a bin size, a threshold, a dynamic
>   selector a tile displays) → add the chip (below). The chip will stick because the tile
>   references it.
> - **Filter-type param** (e.g. `Category Tier`, `Engagement Type` — used only inside an
>   `if [Param]=… then …` filter/category formula) → the idiomatic ThoughtSpot form is a
>   **liveboard filter** on the underlying column (`filters[]` in
>   `thoughtspot-liveboard-tml.md`), *not* a parameter chip.
> - **Display-toggle param** (e.g. `Metric`, `Top 10` that drove Tableau **sheet-swapping** —
>   show the Sales sheet vs the Units sheet) → **no ThoughtSpot equivalent.** Build explicit
>   per-metric tiles, or omit. Do **not** try to force a chip with a raw `[Param]`-selector
>   tile — such a tile isn't a valid query and gets dropped.

If parameter creation failed in Step 5b, fix the parameter first (check `range_config` string
values, cross-formula inlining) before proceeding.

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

> **Spotter-seeded coverage tiles.** Step 12.6 can build coverage tiles here too — seeding
> `search_query` from Spotter's returned `tokens` and the chart type from its
> `visualization_type` — for measures Spotter expressed and you verified. Same tile shape and
> `ALL_OR_NONE` re-import rules; the only difference is where the search came from.

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

See [references/migration-report-format.md](references/migration-report-format.md) for the
full report template — the Overview table, per-workbook Objects/Decisions/Formula-mapping/
Sets/Parked/Excluded/Needing-review sections, and the exact status vocabulary and review
category reference. Every calculated field from Step 3 must appear in exactly one row of the
Formula mapping table; ground each excluded-formula root cause in
[`references/coverage-matrix.md`](references/coverage-matrix.md).

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

## Step 12.6 — Spotter Last-Mile (Parked Formulas)

> **Scope gate:** runs for scopes **1, 2, 4** (wherever formulas are imported).
> **Condition:** only runs when `{parked_formulas}` is still non-empty *after* Step 12.5,
> **and** Spotter is enabled on the model (Step 5.5 = Y). Requires **ts-cli ≥ v0.53.0**.
> **Optional** — offer it; never run it silently.

Deterministic rewriting (Step 12.5) fixes formulas whose ThoughtSpot equivalent is
*syntactically* derivable from the Tableau expression. What remains parked is usually a
measure whose *intent* is clear in English ("year-over-year growth of profit", "distinct
customers this quarter") even though no mechanical translation exists. Spotter — the
model's own AI — can often express that intent as a valid ThoughtSpot Search. This step
asks Spotter, shows you what it produced, and lets you **verify then adopt or leave
parked**. It never auto-adopts: Spotter's answer is a *suggestion to check against the
source numbers*, exactly like every other non-1:1 resolution in this skill (see the
**surface, recommend, resolve** principle at the top).

Prompt:

```
{N} formula(s) are still parked and Spotter is enabled on the model.
Ask Spotter to express each as a ThoughtSpot Search? [Y / n] (default: Y)

  Y  Yes    — ask Spotter per formula, show its tokens, you verify + adopt/park
  N  No     — leave them parked; the Step 12 report stands
```

**If N:** end here; the report is unchanged.

**If Y:** for each parked measure that is *expressible as a plain-English question* (skip
structural / table-addressing artifacts — Spotter answers questions about data, not
row-offset window mechanics):

1. **Phrase the intent** as a natural-language question from the parked record's
   `original_tableau` expression and name — e.g. `SUM([Profit])` growth-vs-prior-year →
   `"year over year growth of profit by month"`.
2. **Ask Spotter** (CLI-first — never a raw `requests` call):

   ```bash
   ts spotter answer "year over year growth of profit by month" \
     --model {model_guid} --profile {profile_name}
   ```

   Output is JSON: `{status, tokens, display_tokens, visualization_type, errors}`.
   - `status: SUCCESS` → `display_tokens` is the human-readable Search Spotter chose
     (e.g. `Profit growth of Profit by Order Date monthly`); `tokens` is the raw form.
   - `status: FORBIDDEN` → the profile's user lacks `CAN_USE_SPOTTER` or view access to
     the model. Stop the step, tell the user, and leave the formulas parked (this is an
     entitlement issue, not a translation failure).
   - `status: SPOTTER_ERROR` → Spotter could not answer (or is not enabled). Leave that
     formula parked; continue with the rest.
3. **Verify the numbers — do not trust the tokens blind.** Present Spotter's
   `display_tokens` next to the original Tableau expression, then confirm the result
   matches the source. Reuse the existing verification paths rather than eyeballing:
   run the tokens as a coverage answer (Step 11.5) or fetch the value with
   `ts spotql fetch-data` against the model and compare to the Tableau workbook's number.
4. **Adopt or park (user decides):**
   - **Match + user approves** → adopt. If Spotter's expression maps cleanly to a model
     formula, add it via the Step 12.5 fix cycle (or `ts model promote-formula` if it was
     built as an answer formula), so it becomes a first-class ✅ Migrated formula. Move it
     out of ⏸ Parked.
   - **Mismatch, or user unsure** → leave parked. Record Spotter's suggested tokens in the
     parked record so a human can pick it up later — but it stays ⏸, not ✅.

5. **Materialize a coverage viz from Spotter's answer (opt-in, human-approved).** For each
   adopted measure, offer to build a **Step 11.5 coverage tile** directly from Spotter's
   answer so the number is visible in-product, not just in the report:
   - `search_query` ← Spotter's returned **`tokens`** (the raw Search expression it produced;
     `display_tokens` is the human-readable form to show in the confirm prompt).
   - `display_mode` / chart type ← Spotter's **`visualization_type`**:
     `Table` → `TABLE_MODE` (omit the `chart:` block); `Chart` → `CHART_MODE` with the
     chart type chosen from the Step 10a intent mapping (a single measure by a date → `KPI`
     or `LINE`; by a dimension → `BAR`); `Undefined` → default to a `KPI`/`BAR`.
   - `description` ← the original Tableau expression + `via Spotter last-mile` (same
     convention as Step 11.5), so a reviewer sees source ↔ migrated side by side.
   - **Show the tile spec and ask before adding it** — never auto-append to the liveboard.
     On approval, add it to the "Formula coverage" tab (or as a standalone answer for a
     model-only workbook) and re-import in place with `ALL_OR_NONE` (Step 11.5 rules).
   This reuses the Step 11.5 machinery — it just seeds the tile from Spotter's answer instead
   of a hand-built search. A tile is only ever added for a measure whose number you verified
   in step 3 and the user approved; an unverified Spotter suggestion never becomes a tile.

**Never** promote a Spotter suggestion to ✅ without a confirmed number match — an
AI-generated Search that *looks* right but returns different numbers is worse than an
honestly-parked formula. When in doubt, park it and say so in the report.

After the step, **regenerate the Step 12 report**: adopted formulas move to ✅ (note
"via Spotter last-mile" in the mapping table); the ⏸ Parked section lists any that Spotter
suggested-but-unverified with its tokens for manual follow-up.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.37.0 | 2026-07-23 | **Extract-wrapper column ownership fix (col_table_map XREF/dropped columns).** Prereq ts-cli v0.86.0 — no skill-instruction changes, `build-model`'s own output is more correct. On a federated Custom-SQL + hyper-Extract workbook (Tableau writes each column's metadata twice — once under the live connection, once more mirrored under the extract's own connection), column ownership was resolving to the excluded Extract-wrapper relation's internal name instead of the live table, dangling `column_id` (`ts tml lint` XREF) and dropping the column from Table TML. Fixed by reusing the same wrapper-exclusion `_extract_tables` already applies, so the live relation always wins. Also fixed an adjacent bug this exposed — a file-backed relation's own name containing a literal `.` (e.g. a CSV extract's `some_table.csv1`) was truncated to its last dot-segment. Live-confirmed on `Demo WB 3 with SQL join.twbx`: 6 XREF findings → 0, `ts tml lint --dir` clean (was `false`), previously-dropped dim-table columns now emitted on a real table. The same map feeds formula scoping too: `TableauSetControlUseCases.twbx` and a plain single-table workbook each had a formula silently referencing a never-emitted `[Extract::col]` table (invisible to `ts tml lint`, which doesn't parse formula bodies) — now correctly scoped to the real table. No regression: Ads Commercial Dashboard output byte-identical. |
| 1.36.0 | 2026-07-23 | **Quick closeout — nested-if warning, Custom-SQL param substitution, native-Set nudge (BL-060/093/131).** Prereq ts-cli v0.85.0 — no skill-instruction changes, three small `build-model`/`translate-formulas` output improvements. **BL-060:** a comparison operator binding directly before `if` (e.g. `sum(X) < if(Y) then Z else W` — valid Tableau, fails ThoughtSpot import without explicit parens) now surfaces as a `validate_pre_import()` warning, mirroring the shipped bare-else check. Live-confirmed on Ads Commercial Dashboard's `Dimensions: TrafficLight` formula. **BL-093:** a `<[Parameters].[Name]>` token embedded in Custom SQL (invalid warehouse SQL as-is) is now resolved before SQL View emission — a parsed parameter's default value is substituted in (with a `validation_warnings` note that the value is now static), an unresolved token gets a `NEEDS-REVIEW` warning instead of silently passing through. No `<[Parameters]` token survives into emitted SQL when a default exists. See `references/coverage-matrix.md` #131. **BL-131:** `build-model` now warns (stderr) and reports `sets_detected` in its result JSON when a workbook has native Tableau Sets (`<group>` — static/Top-N/condition-based) — a nudge that the Phase-2a/2b/2c set→cohort step (Step 5b) is still owed on an automated/Stage-1 run, since GENERATE mode doesn't perform that conversion itself. Excludes Tableau's internal `crossjoin` combined-field `<group>`s (auto-named `Action (...)`/`Tooltip (...)`, not user Sets) so the count stays accurate. Live-confirmed: `TableauSetControlUseCases.twbx` → `sets_detected: 10` + warning; a no-Set workbook → 0; Ads Commercial Dashboard (14 crossjoin groups, 0 real Sets) → 0, correctly not warned. |
| 1.35.0 | 2026-07-23 | **Multi-table quality follow-ups — junk columns, column/formula drops on collision, db_table (BL follow-up: junk cols, Sub-Category XREF, Region drop).** Prereq ts-cli v0.84.0 — no skill-instruction changes, `build-model`'s own output is more correct. **Junk columns:** `__tableau_internal_object_id__` no longer leaks into Model TML on the multi-table path (was only filtered single-table) — Ads Commercial Dashboard: 26 → 0. **Column/formula drops on collision:** (1) a physical column referenced by one datasource but not another sharing the same table name (e.g. `TableauSetControlUseCases.twbx`'s three datasources all declaring a single-table `Orders`) is no longer dropped from Table TML when the last datasource processed is written — Table TML for a shared table name now accumulates the union of every datasource's referenced columns instead of the last write clobbering the rest (`ts tml lint --dir` on Set Control: 1 XREF finding → clean, no hand-editing). (2) a calc field whose caption collides with a physical column's internal name (Ads' `Region`) is still correctly auto-renamed to `"Formula Region"` at generation time, but `ts tableau verify` no longer misreports that as a silent drop (structural ERROR → 0); the rename is also now visible in `build-model`'s `name_renames` result field. **db_table:** Table TML `db_table` now prefers the parser's own extracted `db_table` field over re-slugging the table's display name — fixes a real wrong-output case for a Tableau-assigned alias of a table joined twice (Ads' `d_partner1` aliasing `d_partner`: was emitting `db_table: d_partner1`, a table that doesn't exist in the warehouse; now correctly `d_partner`). |
| 1.34.0 | 2026-07-23 | **Token-reduction — one `build-model`/`lint`/`verify` call per workbook, exact CLI examples (no `--help` probing).** Benchmark runs made 5-7 `ts tableau … --help` calls per session because steps described commands in prose without exact flags — every `ts tableau`/`ts tml lint` step this skill uses now embeds a canonical copy-pasteable invocation (real flag names, sourced from each command's own `--help`) plus a one-line note on the key optional flags (`translate-formulas` `--csq-map`/`--date-columns`, `build-liveboard` `--model-name`/`--model-fqn`/`--report-name`, `tml lint` `--model-phase`/`--pattern`). Separately: Step 5b's "one per datasource (strict separation)" framing was leading agents to run `build-model` once per datasource (3 build + 3 lint + 3 verify on a 3-datasource workbook) even though a single call over the whole workbook already emits every used datasource's Model + Table TML (confirmed live on `TableauSetControlUseCases.twbx`: 1 call → 3 `.model.tml` pairs + the shared `.table.tml`, byte-identical to the old 3-call loop). Steps 5a/5b now state the one-call rule explicitly (`--datasource` is for intentional scoping only, never a default loop) while keeping the per-datasource *output* separation unchanged; Step 6 now runs `ts tml lint --dir` and the new `ts tableau verify --dir` (ts-cli v0.83.0+) once each over the whole output directory instead of once per model. New "Efficiency" bullets in Step 0 restate all three rules. No conversion-output change — procedure + CLI-doc precision only. Arbiter: Set Control (3 datasources) now needs 1 build-model + 1 lint + 1 verify, was 3+3+3. Prereq ts-cli v0.83.0. |
| 1.33.0 | 2026-07-23 | **Multi-table/federated follow-ups — strip db_column_name disambig suffix, dedupe Extract-wrapper tables (BL follow-up #2/#3/#4).** **#2:** Tableau's caption-collision disambiguation suffix (` (table_name)`, e.g. `LineItemId (agg_booked_monthly)`) no longer leaks into a generated Table TML's `db_column_name` — now sourced from the metadata-record's `remote-name` (the real warehouse column name), matching Step 3's own documented rule. Was breaking join cross-references between the colliding tables ("column_id not found" at import) — live regression on `Ads Commercial Dashboard.twb`: `ts tml lint --dir` went from 2 XREF findings to clean. Columns are also now stamped with their owning table from the same metadata, so multi-table `column_id` is `TABLE::col`-qualified (previously bare once two tables' same-physical-name columns lost their (accidental) suffix-based uniqueness). **#4:** the hyper `Extract` cache wrapper relation (schema-scoped `[Extract]`, written by Tableau alongside every live-source table) is no longer parsed as a physical table — was emitting a duplicate `.table.tml` per table (Ads: 25 → 13 tables) that silently overwrote a shared table run-to-run across datasources (`TableauSetControlUseCases.twbx` Set Control: `Orders` + `Extract` → `Orders` only). Per Step 3b: use the live-source relation, ignore `[Extract]`. **#3 (live-verified, not a code bug today):** `VALIDATE_ONLY` on se-thoughtspot/`APJ_TAB` confirms ThoughtSpot rejects a bare `column_id` (no `TABLE::` prefix) even on a single-table model (error 14547); audited every GENERATE-flow branch and found today's single-table path already qualifies correctly, pinned by a new regression test. Added invariant I12 + a `ts tml lint` check (bare `column_id` on a single-table model) as the permanent guard. Prereq ts-cli v0.82.0. |
| 1.32.0 | 2026-07-23 | **Formula translation fixes — wire documented REGEXP/FINDNTH mappings, fix REPLACE + LOD no-space bugs.** `ts tableau build-model` no longer drops `REGEXP_EXTRACT`/`REGEXP_MATCH`/`REGEXP_REPLACE`/`FINDNTH` as "unmapped Tableau function" — they were already documented (`tableau-formula-translation.md` "Pass-Through Fallback") but never wired into `functions.py::map_functions`/removed from `validate.py::_UNMAPPED_FUNCTIONS` (an AST-spike finding). `REPLACE` re-mapped off an invalid bare `replace(...)` native call (live-confirmed error 14516) onto the same `sql_string_op` pass-through form. Fixed an LOD keyword-whitespace bug: a grand-total `{FIXED: agg}`/`{INCLUDE: agg}`/`{EXCLUDE: agg}` (no space before the colon) previously fell through the keyword regex and silently emitted invalid `{ FIXED }` TML. Regression on `ElevateYourTableauSkills-10AdvancedTricks.twbx`: 38/54 → 50/54 formulas now translate. Live-verified `VALIDATE_ONLY` (se-thoughtspot/`APJ_TAB`): all 5 formula types return OK; bare `replace(...)` negative control confirms 14516. `references/coverage-matrix.md` moves these from Unmapped to Mapped (#126-130); reference doc's self-contradictory "passed through untranslated" line corrected. Prereq ts-cli v0.81.0. |
| 1.31.0 | 2026-07-23 | **Docs refactor — context-budget rule + reference extraction (no logic changes).** Added a "Context budget — never Read big tool-output files" section listing the real `--out`/`--output` JSON and generated-TML paths this skill produces. Extracted reference-heavy detail (long TML templates, worked examples, exhaustive rule tables, edge-case enumerations) out of Steps 5, 10, A4, 7, 12, and 3's field-mapping detail into `references/step-5-tml-generation.md`, `references/step-10-liveboard-generation.md`, `references/step-7-review-templates.md`, `references/audit-mode-report.md`, `references/migration-report-format.md`, and `references/step-3-parse-fields.md`, each linked back from its step's spine. Cuts SKILL.md from 4,402 to ~2,900 lines (~34%); every Step heading and all step logic/prompts/commands are unchanged. |
| 1.30.0 | 2026-07-23 | build-model emits Table TML per physical table (parity with other converters). |
| 1.29.1 | 2026-07-22 | Stop emitting vestigial `*.phase1+.model.tml` files in GENERATE mode — only `*.phase0.model.tml` (base) and `*.model.tml` (full) are written. `--model-phase base` no longer needed in lint/import commands. Prereq ts-cli v0.73.0. |
| 1.29.0 | 2026-07-18 | **Step 6 migration-fidelity gate — `ts tableau verify`.** After the `ts tml lint` structural gate, diff the Step 3 parse output (`{workbook}_parsed.json`) against each generated base Model TML to catch what a TWB-only coverage count and a server-side `VALIDATE_ONLY` import both miss: **silent drops** (a translatable formula / table / join the workbook had but the model doesn't — untranslatable formulas correctly excluded via the shared `classify-formulas` tiers) and **mistranslations** (token-level LCS similarity buckets MATCH/PARTIAL/LOW/MISSING). A `structural` ERROR gates a faithful migration; PARTIAL/LOW + limitation-coverage are review prompts, not blocks. Complements (does not replace) the Step 11.5 / Step 12 coverage report; cross-reference dangling-ref checking stays `ts tml lint --dir`'s job. Prereq ts-cli v0.62.0. |
| 1.28.0 | 2026-07-15 | **Spotter last-mile + chart/layout fidelity.** (1) **New Step 12.6 — Spotter Last-Mile:** after Step 12.5 leaves a measure parked, optionally ask Spotter to express its intent as a ThoughtSpot Search via the new `ts spotter answer` command (wraps `POST /api/rest/2.0/ai/answer/create`; returns `tokens`/`display_tokens`). Opt-in, gated on Spotter enablement (Step 5.5) + `CAN_USE_SPOTTER`; **surfaces** the suggested Search, requires a **verified number match** (Step 11.5 coverage answer or `ts spotql fetch-data`) before adopting, else leaves it ⏸ Parked. Never auto-adopts. Can materialize an adopted measure as a Step 11.5 coverage tile seeded from Spotter's `tokens` + `visualization_type` (human-approved). (2) **Step 10a combo/dual-axis fidelity:** a Tableau dual-axis (Bar + Line) viz → `ADVANCED_LINE_COLUMN` + both measures on `axis_configs.y`, which ThoughtSpot auto-resolves; the exact split is pinned via capture-and-replay of an exported (GUID-based) `custom_chart_config` (hand-authored display-name configs error `Invalid GUID string` on fresh import — live-verified); new shared worked example. (3) **Step 9c layout fidelity:** container-tree walk (horz/vert) with proportional column split (largest-remainder → sum 12) + aspect-ratio height + floating-zone handling, replacing the flat y-band heuristic. (4) **Step 10b format + color/mark fidelity:** currency/number/decimal formats → `answer_columns[].format`; Color shelf → Muze `slice-with-color`; small multiples → `trellis-by`; series palettes → `viz_style`; measure sort → `sorted by`. (5) **Step 10c now emits answer + liveboard TML deterministically** via the new `ts tableau build-liveboard` command — role-aware axis layout (Columns→x, Color→series, Rows→pivot, measures→y; pivot gets `axis_configs` or renders blank), a chart-type requirement floor (flags, never downgrades), and overrides capture-and-replay (`format`/`client_state_v2`/`custom_chart_config`/`viz_style`), replacing the hand-written per-viz YAML. ThoughtSpot-side emission ported from the verified standalone Power BI converter; 26 unit tests. **Live-verified on ps-internal 2026-07-15** (real model round-trip): fixed two bugs the live import caught that lint did not — bucketed dates now use the resolved output name (`Month(Date)`), and a display-name `custom_chart_config` is dropped in favour of `ADVANCED_LINE_COLUMN` auto-resolution (its refs must be GUIDs). Open item #20 (build-liveboard live-verified; parser role-extraction is the remaining follow-on); #17–#19 track the other live gaps (Spotter call, currency/number format sub-config, sort token). Prereq ts-cli v0.55.0. |
| 1.27.1 | 2026-07-15 | JSON/VARIANT path access: emit `['key']` bracket notation in `sql_*_op` pass-throughs — ThoughtSpot's formula parser rejects warehouse colon-and-dot path syntax (e.g. Snowflake `PARSE_JSON(...):a.b`) carried via `RAWSQL_*`. Verified for Snowflake 2026-07-15. |
| 1.27.0 | 2026-07-08 | **Parse published-datasource `.tds`/`.tdsx` for the physical model (BL-089 M8).** `ts tableau parse` and `ts tableau build-model` now accept a `.tds`/`.tdsx` (root *is* `<datasource>`) — extracting its real tables/joins/columns/calcs — so a multi-query published datasource builds a multi-table model **automatically via GENERATE mode, no hand-assembly**. Get the `.tds` via `ts tableau download {id}` (the `.tds` inside the `.tdsx`) or a user-supplied file. Step 3.5 corrected: the field API (VizQL `read-metadata`) returns **columns/calcs only, not tables/joins** — the physical model lives in the `.tds`. Step 5b "Multi-query datasources" now leads with the `.tds` path; hand-assembly is the fallback for when only the `.twb` is available. Prereq ts-cli v0.38.0. |
| 1.26.0 | 2026-07-06 | **Custom SQL → SQL View is now automated in `build-model`** (Step 5a/5c), realizing what the skill documented since 1.1.0. `ts tableau build-model` extracts `<relation type='text'>` Custom SQL (SQL + columns from `metadata-record` `parent-name`/`remote-name`, decoding `<<`/`>>`/`==`), emits a `.sql_view.tml` per relation, and references it by name in `model_tables[]` (no GUID at emit time). Physical/SQL-View column dedup prevents duplicate-name import failures; formula resolvability no longer blanket-drops qualified `[SQL View::col]` refs. Verified end-to-end live on ps-internal (parse → emit → import → searchdata returns correct numbers) and against real workbooks (single-CTE + Tableau's 6-query ts_users). Known follow-ons: drop the extract table when its Custom SQL becomes a view; substitute/flag Tableau params embedded in SQL. Prereq ts-cli v0.37.0. |
| 1.25.0 | 2026-07-05 | **Multi-query datasource → multi-table model guidance + liveboard parameter rule (BL-090).** Step 5b: new "Multi-query datasources" subsection — a published/sqlproxy datasource that joins several Custom SQL Queries must become a **multi-table model** (a single-view reconcile silently filters the other queries' formulas as "Unresolved Custom SQL Query alias"); documents detection, greedy table-set cover + shared-key join confirmation, hand-built base → `build-model --existing-guid` (which now auto-migrates parameters, validates qualified columns, cascade-drops, and table-qualifies bare refs to the real owning table), plus **(M14)** collision-renamed formulas, **(M15)** absent-column data-gap surfacing, **(M16)** measure classification on all-ATTRIBUTE table exports. Step 7 Phase-2 pipeline list updated: parameter auto-migration, deterministic qualified-column + cross-formula-cascade filtering, `--max-retries` default 25→10. Step 10f: parameter chips only stick when a param-consuming formula tile is on the board (ThoughtSpot drops unreferenced params) — filter-type params → liveboard filters; display-toggle params (sheet-swap) → per-metric tiles or omit. Live-verified in the CPG Merch migration (tentpole 119/119, prod 137/163). Prereq ts-cli v0.36.1. |
| 1.24.0 | 2026-07-04 | Phase 2 (`build-model --existing-guid`) honors `--column-name-map`, recovering formulas on reconcile-renamed columns |
| 1.23.0 | 2026-07-04 | **build-model column-schema reconciliation for published/sqlproxy datasources.** Tier-1 (always-on): strip `(Custom SQL Query N)` suffixes, drop `__tableau_internal` junk, qualify `column_id` as `table::col` (fixes "column_id incorrect" on existing-table binds), dedupe. Tier-2 (opt-in `--reconcile-table {guid}`): reconcile emitted columns against a target table's real schema — `--reconcile-plan` emits suggested name mappings + drops; skill confirms with the user; `--column-name-map` applies (drops unmapped-absent columns + dependent formulas). Live-verified 2026-07-04 against `vw_dim_promo` on se-thoughtspot (tentpole datasource): reconcile-plan → confirm (rejected a false `UPDATED_AT`→`MAX_UPDATED_AT` suggestion) → apply → base model `VALIDATE_ONLY = OK` (the pre-fix "column_id incorrect" failure is resolved). Prereq ts-cli v0.33.0. |
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
