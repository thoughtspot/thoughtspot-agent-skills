---
name: ts-convert-from-tableau
description: Convert or import a Tableau workbook (.twb or .twbx) into ThoughtSpot — parses TWB XML, generates table + model TMLs, validates and imports. Optionally migrates dashboards to liveboards via SpotterViz. Direction is always Tableau → ThoughtSpot. Not for ThoughtSpot → Tableau or standalone TML exports.
---

# Tableau Workbook → ThoughtSpot

Converts a Tableau workbook into ThoughtSpot objects. Parses the TWB XML to extract
tables, columns, joins, and calculated fields, then generates Table TMLs and a Model
TML per datasource. Optionally converts Tableau dashboards into ThoughtSpot Liveboards
via **SpotterViz** (ThoughtSpot's own MCP server for building dashboards from
natural-language instructions) — there is no hand-authored-TML liveboard path.

Ask one question at a time for **dependent** decisions (where the next question depends on
the answer), waiting for each. But **batch independent questions into a single
multi-question prompt** to cut round-trips and keep the migration fast — e.g. mode + scope,
or the count-column + bin-style + cohort-handling decisions. See **Efficiency** in Step 0.

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
| [../../shared/schemas/thoughtspot-chart-types.md](../../shared/schemas/thoughtspot-chart-types.md) | Verified `answer.chart.type` enum (44 values) + analytical-intent → chart-type mapping (used for Step 11.5 coverage tiles, and for intent wording in Step 10's SpotterViz instructions) |
| [../../shared/schemas/spotterviz-liveboard-build.md](../../shared/schemas/spotterviz-liveboard-build.md) | Step 1.6/Step 10 — SpotterViz connectivity setup, the `is_spotter_enabled` gate, build-instruction composition, known gotchas |
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth setup |
| [../../../tools/ts-cli/README.md](../../../tools/ts-cli/README.md) | `ts spotter answer` — the Spotter last-mile command (Step 12.6) |
| [references/open-items.md](references/open-items.md) | Known validation quirks and workarounds |
| [references/coverage-matrix.md](references/coverage-matrix.md) | Canonical mapped/unmapped construct matrix — cite in Audit mode (A4) and the migration report (Step 12) |
| [references/step-3-parse-fields.md](references/step-3-parse-fields.md) | Step 3 TWB field-by-field extraction detail (relation wrapper handling, per-element field mapping, SQL dialect notes, blend date-grain resolution) |
| [references/step-5-tml-generation.md](references/step-5-tml-generation.md) | Step 5 TML generation detail — hard rules, hand-assembly templates, parameter type mapping, formula edge cases, Tableau Sets → column/query sets |
| [references/step-7-review-templates.md](references/step-7-review-templates.md) | Step 7 review-checkpoint and import display templates |
| [references/step-10-liveboard-generation.md](references/step-10-liveboard-generation.md) | Zone extraction field reference + container-tree grid mapping algorithm (Step 9) — groundwork for composing Step 10's SpotterViz build instructions |
| [references/audit-mode-report.md](references/audit-mode-report.md) | Step A4 audit-mode coverage report templates |
| [references/migration-report-format.md](references/migration-report-format.md) | Step 12 migration report format + Step 10 Migration Summary / Step 12.6 coverage-tile detail |
| [references/changelog-archive.md](references/changelog-archive.md) | Full changelog history below the versions kept inline |

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
- The generated `*.table.tml` / `*.model.tml` (incl. `*.phase0.model.tml`) / `*.sql_view.tml` / `*.cohort.tml` files under `/tmp/ts_tableau_mig/output/{workbook_name}/`

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

**Read the actual calculation — never infer from the name.** A worksheet titled "Highest
Growth in past 5 years" tells you the *intent*, not the *logic*. Inspect the real Tableau
definition — table-calc type, filters (Top-N, recent-N-years), compute-using/partition, and
sort — and translate *that* (a title can hide a period comparison, not a raw `growth of`).

**Placeholder charts when a full translation isn't possible.** Don't silently omit a viz
that can't be fully reproduced — build a `TABLE` placeholder with the columns you *can*
produce, and note in both `answer.description` and the Migration Summary tab that it's
partial and needs review. A visible, labelled stub beats a missing tile.

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
  1.6 Confirm SpotterViz MCP connectivity .................. auto/you choose [scope 1,3]
  2.  Locate and extract the TWB file ...................... you provide path
  3.  Parse TWB XML — extract tables, columns, joins,
      calculated fields, blend relationships,
      table-calc addressing ............................ auto
  3.5 Resolve published datasources (API or .tds) ... auto/you choose  [scope 1,2,4,5]
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
 10.  Build liveboard via SpotterViz (is_spotter_enabled gate,
      build instructions, poll to completion) ............ you confirm   [scope 1,3]
 11.5 Formula coverage answers (every formula testable) ... auto         [scope 1,2,4]
 12.  Migration report (outcomes + links + formula map) ... auto         [scope 1,2,3,4,5]
 12.5 Resume prompt — fix parked formulas? .............. you choose    [scope 1,2,4; if parked]

Confirmation required: Steps 1.5, 1.6 (only if not connected), 3.6, 4.5, 5.5, 7, 7.5, 8, 9d, 10, 12.5
Auto-executed: Steps 1, 3, 5, 6, 9, 11.5, 12
(Per-scope runs/skips: see the table in Step 1.5.)

### Efficiency — keep the migration fast

The flow is interactive, but most of the wall-clock cost is avoidable. Apply these:

- **Batch independent prompts** — single multi-question prompt for decisions that don't
  depend on each other (*mode + scope*; *count-column + bin-style + cohort-handling*);
  serialize only genuinely dependent questions.
- **Parse the TWB in one pass** — datasources, columns, calc fields, parameters, dashboards,
  zones, table-calc addressing in a *single* script, not one Bash call per element.
- **Read the model's real `obj_id` once, right after import** (Step 7) — SpotterViz's
  `data_source_id` (Step 10) and the Step 11.5 coverage answers both need it; capturing it
  once avoids re-deriving it later.
- **Don't fetch what you don't need** — skip `ts connections list`/`get` when the user names
  the connection or tables are reused (Steps 4/4.5); skip the model/table layer in scope 3.
- **One `build-model` call per workbook, not per datasource** (Step 5a/5b) — plus one `ts
  tml lint --dir` and one `ts tableau verify --dir` over the whole output directory (Step 6).
  3 datasources = 1 build-model + 1 lint + 1 verify, not 3 of each.
- **Never `--help` a `ts tableau`/`ts tml` command this skill documents** — every step gives
  the exact, copy-pasteable invocation; use it as written.

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

**The classifier works per datasource** — each datasource becomes its own model, and the
same calc *name* can carry a *different* expression per datasource, so it's tiered against
its own. Parsed-workbook input output: `{"datasources": [{"name", "formulas", "tier_counts",
"translate_stats"}, …], "tier_counts": <sum across datasources>}`, each `formulas[]` entry
carrying `tier`/`reason`/`level`/`complexity`. Report **per datasource** (Step A4) and use
the top-level `tier_counts` for the workbook total. (`--datasource "<name>"` limits to one; a
bare-list input yields a flat `{formulas, tier_counts, translate_stats}`.)

Translatable tiers: `native`, `lod`, `cumulative`, `pass_through`,
`row_offset_native`, `parameter_ref`. Untranslatable tiers: `untranslatable`,
`row_offset_ambiguous`, `window_ambiguous`, `geospatial`, `circular`, `orphan`, `parameter_query`.

Those tiers map to human-readable report categories (Native/Set, LOD, Cumulative,
Pass-through, Partial/Unmapped sets, Row-offset pass-through, Untranslatable
row-offset/window-ambiguous, Untranslatable, Parameter ref auto/query) — kept as
reference/documentation now, not as executed classification logic. See
[references/audit-mode-report.md](references/audit-mode-report.md) "Tier reference
(Step A3)" for the full tier → category → example table.

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

**Tableau Sets (BL-088) — same rule, a different field.** Each `datasources[]` entry also
carries `sets[]` (`[{name, set_type, tier}, ...]`) and `sets_tier_counts`
(`column_set`/`query_set`/`deferred`, the exact rows the "Tableau Sets" table needs); the
top-level `sets_tier_counts` sums them for the workbook total — same source-from-JSON rule
as formulas, reusing `build-model`'s own Phase-2a/2b/2c classification.

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

Notes beyond the table above: **scope 3** has no model to build — run **Step 1.5a** below to
pick an **existing** model, then parse the TWB (Steps 2–3) and continue at Step 8 (Step 9b
maps each worksheet's shelves to the chosen model's columns by display name, surfacing any
unmatched field). **Scope 4** — tables already exist in ThoughtSpot; the user provides GUIDs
or searches for them (Step 4, **E**/**G** path) and the model TML references them by GUID —
this is the common consultant/remote path where tables were loaded separately (e.g. via
`/ts-load-source-data` or manual provisioning + `ts tables create`). **Scope 5** is useful
for a phased migration where tables are set up first and models follow in a scope-4 pass.

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
(`metadata_name`). Then **export it once** to read its columns and formulas — this is what
Step 10's SpotterViz build instructions describe tiles against — and confirm its
`properties.spotter_config.is_spotter_enabled` (Step 10's gate) while you're there. Confirm
the picked model with the user before proceeding:

```
Using existing model: {model_name}
  {base_url}/#/data/tables/{model_guid}
  Columns: {n}   Formulas: {f}   Parameters: {names}
Build liveboards on this model? (yes / pick another)
```

---

## Step 1.6 — Confirm SpotterViz Connectivity

> **Scope gate:** runs for scopes **1** and **3** (the only scopes that build liveboards).
> **Skip for scope 2, 4, 5.**

This skill builds liveboards exclusively via **SpotterViz**, ThoughtSpot's own MCP server
for building Liveboards from natural-language instructions — there is no hand-authored-TML
fallback. Check now, before doing any parsing work, so a missing connection surfaces early
rather than after the model is already built.

Check whether the SpotterViz MCP tools are loaded this session (tool names under
`mcp__claude_ai_ThoughtSpot_Spotter__*` — try `check_connectivity`). If connected, confirm
and continue to Step 2.

**If not connected**, walk the user through setup — see
[`../../shared/schemas/spotterviz-liveboard-build.md`](../../shared/schemas/spotterviz-liveboard-build.md)
for the exact MCP config, the restart requirement, and the interactive OAuth login (none of
which can be completed in a non-interactive session). Then ask:

```
SpotterViz isn't connected yet — liveboard generation (Step 10) needs it, with no
hand-authored-TML fallback in this skill.

  Y  I've set it up — recheck connectivity
  N  Proceed without it — I understand liveboards can't be built this session

Enter Y / N:
```

**On N:** proceed with the migration normally through Step 7.5/11.5/12 (Model/Table work is
unaffected), but when Step 8 is reached, tell the user again that dashboards can't be
migrated to liveboards this session and skip straight to Step 11.5/12 — don't silently drop
the dashboards without saying so a second time, in case the user forgot.

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
`param_map`, `blends`, `table_calc_addressing`, `dashboards`, `sets_detected`, and
`skipped_datasources` (datasources found but not migrated, with a reason — check it
whenever the datasource count looks low). All subsequent steps read these fields
instead of re-deriving them.

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
- If the datasource contains `<extract>`, **do not blindly skip it.** It almost always
  wraps an *underlying* connection that names a real table (file source, database, etc.) —
  that's what gets queried in the warehouse. Look past the `<extract>`/`hyper` connection:
  the relation has two parents in `<metadata-records>` — the live source (e.g.
  `[Amazon Sales data.csv]`) and `[Extract]`. **Use the live-source relation; ignore
  `[Extract]`** (table name comes from the live source, mapped to its warehouse table per
  Step 4.5). Only treat a datasource as truly skippable when there is **no** resolvable
  underlying connection — say so in the report. File-based sources (CSV/Excel) imply the
  data was loaded into the warehouse out of band; bind to the connection exposing it now.
- Otherwise, it is a **Live** datasource — proceed with extraction.

**Non-warehouse sources — explicit unsupported policy:** `cloudfile:googledrive-excel-direct`,
`google-sheets`, `ogrdirect` (spatial/OGR), `webdata-direct`, `CustomMapbox` are NOT
warehouse-bound and cannot map to a ThoughtSpot connection — do NOT assume a warehouse table
exists. Log `"Datasource '<name>' uses a non-warehouse source (<class>) — cannot map to a
ThoughtSpot connection. Skipped; data must be loaded into a warehouse first."`, skip the
datasource entirely (no table/model TML), and surface it in the audit report's "Skipped
sources" section.

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
`PctRank` | `None`), `address_offset` (int or `None`), and `address_value` (the raw
`<address><value>` token, or `None` when the element is absent).

Each `<worksheet>`'s `<column-instance>` elements can carry their own `<table-calc>` —
these are **view-level overrides** that take precedence over the column-level definition
for that worksheet. Read them from `table_calc_addressing.ws_overrides` (same entry shape,
keyed by worksheet name then calc ID).

**Resolution order** when translating a table-calc formula used on worksheet W:
1. Check `table_calc_addressing.ws_overrides[W][calc_id]` — view-level override
2. Fall back to `table_calc_addressing.column_level[calc_id]` — column-level definition
3. If neither exists, treat as `ordering_type='Rows'` (Tableau default)

`table_calc_addressing.warnings` (also echoed to stderr) lists entries whose
`<address><value>` was non-numeric — Tableau writes `false` / `"All Pages"` there for
non-offset addressing modes. Those entries parse normally except `address_offset`, which
is `None`; the token itself is kept in `address_value`, so a non-offset mode is
distinguishable from an absent `<address>` (where both are `None`) without reading the
warning text. It is a **skip, not a failure**: note it in the Step 12 report, don't stop.

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

> Runs only if Step 3 found a `<connection class="sqlproxy">` (its `dbname` names the
> published datasource). Skipped when every datasource connects to a warehouse directly.

The TWB carries the calculated fields and column definitions; it lacks the **physical table
structure** (tables, joins, db/schema paths), which lives only in the datasource's `.tds`.
Resolving it needs either the Tableau API or the `.tds`/`.tdsx` itself. Detail — what's
in/out of the TWB, how to get the `.tds`, field-resolution and CSV-download mechanics — is
in [references/step-3-parse-fields.md](references/step-3-parse-fields.md) "Published
datasource (sqlproxy) resolution detail (Step 3.5)".

### Flow

> **ASK before any API call.** The user may have no access to the customer's Server — a
> failed call wastes 30–60 seconds and confuses the flow.

Prompt — **always, before any API call**:

```
Found {N} published datasource(s) hosted on Tableau Server:
  - {ds_caption_1} ({M} columns, {C} calculated fields extracted from TWB)
  - {ds_caption_2} ({M} columns, {C} calculated fields extracted from TWB)

The TWB already contains all column definitions and calculated fields.
What's missing is the physical model (table names, joins, db/schema paths).
It can come from the Server, or from the .tds file itself.
  Y  Yes, I have Server access — query the Tableau API   (requires /ts-profile-tableau)
  T  I have the .tds/.tdsx file(s)  — parse them directly
  N  Neither — proceed with TWB metadata only            (consultant/remote migrations)

Enter Y / T / N:
```

**T (has the file)** — ask for each path, `ts tableau parse {file}.tds`, merge its
tables/joins/db-schema into the matching parsed datasource, then proceed to Step 4 as **Y**
does. No Server access needed; `parse` accepts `.tds`/`.tdsx` directly.

**N (no API access)** — proceed with TWB-embedded metadata (columns + calc fields already
extracted; physical table names come from `<metadata-record>` `parent-name`). **Skip to
Step 3.6** (join confirmation) — the user provides/confirms joins and table mappings
manually. This is the normal path for consultant/remote migrations.

**Y (has API access)** — query the Tableau API to resolve columns (`ts tableau datasources
--name "{dbname}"` then `ts tableau datasource {id} --fields`), merge the resolved
fields into the parsed datasource, and proceed to Step 4. For **textscan**/**excel-direct**
sources, also offer to download and validate the source data (`ts tableau download
{datasource_id} --output-dir {output_dir}`) — see the reference above for the exact
commands, the `fields` array shape, and the CSV-validation handling.

### Prerequisites

- Tableau profile configured via `/ts-profile-tableau` (optional — skill degrades gracefully)
- `ts` CLI v0.73.0+

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
  by default.** Once chosen, **pass `--connection "{connection_name}"` to `ts metadata search`** —
  do not hand-filter. `filter_by_connection` (`commands/metadata.py:35`) **casefolds**
  both sides, so the old "keep results whose `dataSourceName` **equals** the name"
  instruction dropped rows the CLI keeps (`APJ_TAB` vs `apj_tab`) — finding 11.1.
- **I (entire instance)** → run the name search above with no connection filter.

Match on table name (`metadata_name`). **Connection scoping is already done** by the
`--connection` flag above — do NOT re-filter on `metadata_header.dataSourceName` here: the
flag casefolds and a hand comparison does not, so re-applying it against the name you typed
drops every row the flag kept (finding 11.1, 2026-08-26). (db/schema also appear in `metadata_header` —
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

**C — create a new connection.** Supported here for **Snowflake** via key-pair auth only —
anything else (or password/OAuth) is out of scope: direct the user to create it in the
ThoughtSpot UI, then return on the **E** path. Collect name, account identifier, user, role,
warehouse, and the **unencrypted PKCS#8 private key** (`.p8`) path, then run:

```bash
ts connections create \
  --name "{connection_name}" \
  --account "{account}" --user "{user}" --role "{role}" --warehouse "{warehouse}" \
  --database "{database}" \
  --private-key-path "{key_path}" \
  --profile {profile_name}
```

The role needs `USAGE` on the database/schema and `SELECT` on the tables; the matching
**public** key must already be registered on the Snowflake user. **Credential handling
(required): never ask the user to paste a private key, password, or secret into the
conversation** — the key is passed by file path only and the command never echoes it. Use
the returned `name` as `{connection_name}`.

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

**T — trust the name** directly, skipping `ts connections list` — faster on large instances;
import returns a clear error (`"Connection 'X' not found"`) if wrong.

**Compound prompt (N or T path)** — offer db/schema confirmation in the same prompt to
eliminate sequential questions, replacing the separate loop below when all three are given
in one response:

```
Connection: ____________  (exact ThoughtSpot connection name)
Database:   ____________  (or press Enter to use '{twb_extracted_db}')
Schema:     ____________  (or press Enter to use '{twb_extracted_schema}')
```

For N/F/L, fetch the connections once (auto-paginated, returns all):

```bash
ts connections list --profile {profile_name}
```

Resolve the user's choice against that result: **N** — match the typed name against
returned `name` values (case-sensitive); exactly one match → use it, no match → show
closest names and re-ask (never fabricate a name the list doesn't contain). **F** — keep
connections whose `name` contains the string (case-insensitive), show a short numbered list
(name, type, database); one match → auto-select and confirm, none → widen or switch to
**L**. **L** — show the full numbered list (`{name} ({type}) — {database}`) and pick by
number.

If only one connection exists in total, auto-select it and confirm regardless of the choice.
Save the selected connection's exact `name` value as `{connection_name}`.

**Resolving db / schema / table for new tables.** Each new table needs the `{db}`,
`{schema}`, and `{db_table}` it maps to on the chosen connection. The TWB's paths are the
*source environment's* — they may not match the target connection (e.g. a consultant running
in their own environment) — so always confirm before using them:

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

**Y** → use the TWB-extracted values directly. **D** → ask for the target `{db}`/`{schema}`
once and apply to all tables (the common consultant scenario — same database, different
name). **T** → walk through each table and confirm/override individually (tables spanning
multiple databases/schemas in the target).

If the user doesn't know the correct paths, **ask first** (usually instant — they know it);
only if they're unsure, fetch the connection schema to resolve names:
```bash
ts connections get {connection_id} --profile {profile_name}
```
**Expect nothing back** — live-probed 2026-08-26, the warehouse hierarchy is empty for
every auth type. Ask the user and take the names from them.

A connection is **required** for any table being created — there is no skip path. A
ThoughtSpot table is a logical object over a **live** connection to a physical table that
must already exist; never offer placeholders or a dry-run mode (they only produce objects
that can never bind to data). No suitable connection: **Snowflake** source → create one via
the **C** path above; anything else, or password/OAuth → stop and tell the user the
connection must be created first in the ThoughtSpot UI (out of this skill's scope).

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
automatically — **no hand-assembly**. **Run it ONCE for the whole workbook** (below) — the
same call also emits every datasource's Model TML (Step 5b), so 5a and 5b describe one
command's two outputs, not two commands. It writes one `.table.tml` per physical table
(`type="table"`) to `{output_dir}/{TABLE_NAME}.table.tml` across every datasource the
workbook uses — a table shared by multiple datasources is written once and shared, not
regenerated per datasource. **Custom SQL relations are excluded** — handled in Step 5c.

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

Generate one model per datasource the workbook **actually uses** (strict separation between
models — a rule about the *output*, not a per-datasource command loop). How each
datasource's model TML is produced depends on whether it participates in a blend:

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
datasource's model + table TML in that single call (a 3-datasource workbook emits 3 model
pairs + the shared table TML from this one call — never 3 separate runs). Pass
`--datasource "{datasource_name}"` only to intentionally (re)build one datasource — never
loop it per datasource as the default flow.

This writes, per datasource, `{slug}.phase0.model.tml` (base — no formulas) and
`{slug}.model.tml` (full, topologically ordered). Step 7 Phase 1 imports the phase0 file;
formulas are added independently in Phase 2 via `build-model --existing-guid` **per model**
(inherently one-call-per-GUID, unaffected by the "one call" rule above).

`--table-name-map` (optional): a workbook-wide JSON file `{"twb_table_name":
"thoughtspot_table_name"}`. Supply it **only** when the ThoughtSpot table's TML `name`
(Step 5a) differs from the TWB relation name (warehouse-normalized names, or a published
datasource literally named `sqlproxy`); omit when names already match.

**Published/sqlproxy datasources bound to an existing table/view — reconcile columns.**
When the datasource binds to a pre-existing ThoughtSpot table/view (the consultant/stand-in
case), emitted columns carry Tableau's `(Custom SQL Query N)` suffixes that may diverge from
the view's real names — `--reconcile-table` (Plan → confirm with user → Apply) is a
deliberate exception to the "one call" rule. See
[references/step-5-tml-generation.md](references/step-5-tml-generation.md) "Published/
sqlproxy datasources bound to an existing table/view — reconcile columns (Step 5b)" for the
exact 3-step command sequence and the `column_name_map.json` placement gotcha.

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

**Generate the calc-id map from TWB parse:** each `<column>` element has both a `name`
attribute (e.g. `[Calculation_6076974422807080981]`) and a `caption` (display name) — build
a JSON map from name → caption and save to `{workdir}/calc_id_map.json`
(`{"Calculation_6076974422807080981": "Revenue Growth %", ...}`).

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

**Output** (`formulas_translated.json`) has `translated[]`/`skipped[]`/`stats` — see
[references/step-5-tml-generation.md](references/step-5-tml-generation.md)
"`translate-formulas` output shape (Step 5b)" for the exact shape. Use `translated`
entries to populate `formulas[]` and paired `columns[]` in the model TML. Review `skipped`
entries — some may be recoverable with a `--calc-map` or by manual inlining. `stats.levels`
shows dependency depth (key = level, `-1` = circular); it maps to the audit cross-reference
depth table from Step A3/A4.

### Parameter migration (Tableau → ThoughtSpot `parameters[]`)

When the TWB has a `Parameters` datasource (Step 3), generate `parameters[]` entries
in the model TML. Omit `id` — ThoughtSpot assigns it on import.

See [references/step-5-tml-generation.md](references/step-5-tml-generation.md) "Parameter
migration — type mapping and invariants" for the full `param-domain-type`/`datatype` →
ThoughtSpot `data_type`/config mapping table.

**Value cleanup:** Tableau wraps string member values in double quotes (`'"USD"'` → strip
to `USD`); Tableau date defaults use `#` delimiters (`#2026-05-10#` → strip to `2026-05-10`,
then format `MM/DD/YYYY`).

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
`range_config` values, inlining a formula referenced inside `sum()`).

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

**As of ts-cli v0.87.0, `ts tableau build-model` emits these automatically** — one
`{model}.{SetName}.cohort.tml` per translatable Set (static/`%null%`/`except`/intersect →
`GROUP_BASED` column set; Top-N/Bottom-N/all-except-Top-N/condition-based/mixed computed
ops → `ADVANCED`/`COLUMN_BASED` query set), written alongside the model files in the SAME
`build-model` call — no separate command, no hand-assembly in the normal flow:

```bash
ts tableau build-model {twb_file} --connection {connection_name} \
  --output-dir /tmp/ts_tableau_mig/output/{workbook_name} --database {db} --schema {schema}
```

The result JSON's `cohorts_emitted` (`[{name, set_type}, ...]`) and `cohorts_deferred`
(`[{name, set_type, reason}, ...]`) report exactly what happened to every Set in that
datasource. A dynamic **Set Control** (no fixed members) and an unclassifiable `<group>`
shape are never converted — they land in `cohorts_deferred` with the reason.

Detection + the exact per-type TML shape are documented in full in
[references/step-5-tml-generation.md](references/step-5-tml-generation.md) "Tableau Sets →
ThoughtSpot column sets (Phase 2a/2b/2c)" — read it if a `cohorts_deferred` reason needs
investigating, or to hand-build an edge case the CLI didn't classify (also covers the IN/OUT
`sum_if` translation patterns for consuming a cohort in a formula).

**Import order for query sets: model (with parameter) → cohort** — the set's formula
references the parameter, which must exist on the model first; the payload order in
Step 5.5 already reflects this (cohorts land alongside the full model file, never the
formula-less phase-0 base).

> **⚠ A freshly generated cohort's `worksheet:` block has NO `obj_id` yet — patch it in
> after the model's first import, same as the existing obj_id read-back rule (Step 7 note
> "A requested obj_id on a fresh model is NOT honored").** `build-model` GENERATE mode
> (no `--existing-guid`) can't know the model's real `obj_id` before the model exists, so
> the emitted cohort binds by `id`/`name` only. **Live-verified 2026-07-23** (`VALIDATE_ONLY`
> against se-thoughtspot/APJ_TAB, `TableauSetControlUseCases.twbx`): importing the model +
> cohort together in one `--dir` batch with no `obj_id` fails every cohort with `"Worksheet
> not found for referencedObjectId , fqn , and name <Model>"` (error 14500) — confirms the
> 1.5.3/1.13.0 obj_id-required finding still holds. **Fix:** import the model first, read
> back its real `obj_id` (import response `objId` / `metadata search --guid` / export —
> see the obj_id rule in Step 7), rewrite the
> cohort file's `worksheet.obj_id` to that value, then import the cohort(s). `ts tml lint`
> does not catch this (it's a live-import-only failure, not a structural TML defect —
> lint stays clean either way); only a real/`VALIDATE_ONLY` import surfaces it.

> **⚠ MANDATORY — flag every set conversion for the user to review.** Set conversions are
> *semantic reinterpretations*, not literal 1:1 translations, even when the CLI performs
> them automatically. For **each** entry in `cohorts_emitted`/`cohorts_deferred`, surface its
> outcome and ask the user to confirm it matches intent, in **both** the Step 7 review
> checkpoint and the Migration Summary (Step 10) / Step 12 report — see the reference above
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

> **Emitted names may be qualified.** A name contested across the workbook becomes
> `Base (Datasource)` — object name and filename both. See that file's "Name uniqueness
> is workbook-wide", which also covers hand assembly.

**Template:** see [references/step-5-tml-generation.md](references/step-5-tml-generation.md)
"SQL View TML template (Step 5c)" for the full YAML shape.

Key rules (the rest are in `tableau-tml-rules.md` "Key differences from table TML"):
- `connection.name` is **required** — use `{connection_name}` from Step 4.5
- `sql_query` contains the full SQL text from the Tableau `<relation>` element (decode
  HTML entities)

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
parser-based check of hard invariants **I1, I2, I4, I5, I8** (see
[`../../shared/schemas/ts-model-conversion-invariants.md`](../../shared/schemas/ts-model-conversion-invariants.md)
for the full definitions; I1/I2 detail also in
[references/step-5-tml-generation.md](references/step-5-tml-generation.md) "Model TML hard
rules") that `--policy VALIDATE_ONLY` does **not** catch (ThoughtSpot accepts the TML and
then behaves wrong, or rejects it on import). `ts tml lint` reads the
same `--dir`/`--order` input as `ts tml import` and exits non-zero on any finding, so it
gates the import. **Run it once over the whole output directory** — not per model file — so
the cross-reference check (model→table/sql_view) sees every table alongside every model in
one pass:

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
(Step 3's `{workbook_name}_parsed.json`) against each generated **base** Model TML — it
catches **silent drops** (a table/join/*translatable* formula the workbook had that the
model doesn't — an untranslatable formula's absence is not flagged, since tier
classification is shared with `classify-formulas`) and **mistranslations** (a formula whose
TML barely resembles its Tableau source — MATCH/PARTIAL/LOW/MISSING similarity buckets).

**Run it once over the whole output directory with `--dir`** — not once per model
(`--model {path}` is only for the rare single-file re-check after a fix):

```bash
ts tableau verify \
  --parse /tmp/ts_tableau_mig/{workbook_name}_parsed.json \
  --dir /tmp/ts_tableau_mig/output/{workbook_name}
```

This aggregates every full Model TML's per-model report (`models[]` + `summary`) into one
JSON on stdout, non-zero exit if ANY model has an ERROR, plus a human summary on stderr. How
to act on it — **structural ERROR** (translatable formula/table/join dropped) is the gate:
investigate before importing, fix the build or confirm the drop is expected (e.g. an orphan
calc from Step 3g) and proceed knowingly. **formula_equivalence PARTIAL/LOW** (WARNING) is a
review prompt: spot-check against the source — often a legitimate rewrite (e.g. a
`DATEDIFF`/`DATEADD` unit function that can't statically token-match), not a bug.
**limitation_coverage** (advisory) echoes, and does not replace, the Step 11.5/12 coverage
report. (Dangling-ref checking is `ts tml lint --dir`'s job, above — verify is about
source-vs-output fidelity, not TML internal consistency.)

Validate (up to 10 fix cycles). `--policy VALIDATE_ONLY` checks without persisting:

```bash
ts tml import --dir /tmp/ts_tableau_mig/output/{workbook_name} \
  --order tableau --policy VALIDATE_ONLY --profile {profile_name}
```

For each cycle: parse the response (`status.status_code` `OK`/`WARNING`/`ERROR` — only
`ERROR` blocks). **Expected WARNING (ignore):** `Table with id null not found. Matching
with db/schema/dbTable` — a freshly generated table TML has no GUID, so ThoughtSpot matches
by db/schema/dbTable instead; normal, even on a clean binding. **Real ERRORs:** `connection
not found` (wrong name/case) and `column not found in connection` (connection doesn't
expose that `db_table`/column) — fix the name or mapping. For any other error, identify the
affected file, apply the fix from `tableau-tml-rules.md`'s error table, rewrite the file in
place, and re-validate.

After 10 cycles with remaining errors, stop and report: errors that persist, the fix
attempted for each, and ask whether to proceed with import anyway or make manual corrections.

---

## Step 7 — Review Checkpoint & Import

> **Scope gate:** runs for scopes 1, 2, 4. **Skip for scope 3** (model already exists)
> and **scope 5** (no model — tables imported in Step 6 only).

Before importing, show the user a review summary (same convention as
`ts-convert-from-snowflake-sv`/`ts-convert-from-databricks-mv`) — the user should see
exactly how every calculated field was translated and what will **not** migrate *before*
committing, not discover omissions only in the Step 12 report. Source each formula's
`tier`/`level`/`complexity` from the same `classify-formulas` output Step A3 uses — never
re-derive tiers by hand. Step 7 reviews **one model (one datasource) at a time**, so:
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
- Row-offset table calculations — see
  [references/step-7-review-templates.md](references/step-7-review-templates.md)
  "Row-offset table calculations review (Step 7)" for what to display and confirm

Wait for confirmation. **no** cancels. **file** writes the TMLs and skips to Step 12
(report only, no import). **yes** imports using the two-phase approach below.

### Two-phase import (recommended)

Import in two phases so formula errors never block the base model. See
[`../../shared/mappings/tableau/tableau-tml-rules.md`](../../shared/mappings/tableau/tableau-tml-rules.md)
"Two-phase model import" for the rationale.

**Phase 1 — Base model (no formulas):**

Build the model TML with `model_tables[]`, physical `columns[]`, `joins[]`, and
`parameters[]` only — **no `formulas[]`, no formula `columns[]` entries.** Guaranteed to
succeed if the table TMLs bind correctly. For GENERATE-mode (Step 5b) this is exactly the
`*.phase0.model.tml` file; for a blend-merged model, the hand-assembled `.model.tml`.

The Phase 1 payload is tables + sql_views + base model + cohorts, in that order —
`--order tableau` sorts by TML type. GENERATE-mode output (`*.phase0.model.tml` +
`*.model.tml`) and blend-merged output (bare `.model.tml`) both pass through unchanged.

> **Cohorts from a fresh model still need the obj_id read-back (Phase 2a note above)** —
> a single `--dir` batch import does **not** resolve a cohort's model reference against a
> model in the *same* batch (live-verified: error 14500 "Worksheet not found", even with
> the base model included). Import tables + sql_views + base model first (no cohorts in
> that call), read back the model's real `obj_id`, patch every `*.cohort.tml`'s
> `worksheet.obj_id`, then import the cohort(s) — before, or interleaved with, Phase 2.

**Before importing, check for duplicates** — if Phase 1 was already imported (a retry or
previous attempt), search for existing models by name first; delete a duplicate with
`ts metadata delete`, or pin its GUID and import with `--no-create-new` to update in place.

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

**Phase 1.5 — Base model review checkpoint:** after Phase 1 succeeds, pause and let the user
verify the base model before adding formulas — catches structural issues (wrong bindings,
missing columns, broken joins) before they compound into Phase 2 retry cycles. See
[references/step-7-review-templates.md](references/step-7-review-templates.md) "Phase 1.5 —
base model review checkpoint" for the exact prompt shape. If the user chooses **search**,
suggest 3 natural-language test questions grounded in the model's physical columns (no
formulas yet), then re-prompt yes/no.

**Phase 2 — Add formulas via `build-model`:**

After the user confirms the base model, add all translated formulas in one CLI call.
`build-model` parses the TWB directly — do not prepare intermediate files for it
(`classification.json`/`table_columns.json`/`parameters.json`/`calc_id_map.json` are inputs
to `ts tableau translate-formulas`, Step 5b, not to `build-model`).

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

This command runs the full formula pipeline internally (re-parse → migrate missing
parameters onto the model → translate → `validate_pre_import()` → `formula_` prefixing →
double-aggregation fix → deterministic unresolvable-reference filtering → table-qualify →
merge → import with up to 10 retry cycles) — see
[references/step-5-tml-generation.md](references/step-5-tml-generation.md)
"`build-model --existing-guid` internal pipeline (Step 7 Phase 2)" for the full 10-step
breakdown. A large multi-table model no longer needs a high `--max-retries` (previously
exceeding the cap rolled the whole `ALL_OR_NONE` batch back to zero) since the deterministic
filter classes are now caught pre-import.

Parse the JSON output to report results to the user:

See [references/step-7-review-templates.md](references/step-7-review-templates.md) "Phase 2 — `build-model --existing-guid` JSON output shape" for the exact
field list (`import_status`, `formulas_translated`/`skipped`/`filtered`/`added`,
`formulas_dropped_on_import` with `name`/`expr`/`error`/`original_tableau`,
`validation_warnings`, `updated_model_guid`).

**Check `import_status` first — an empty `formulas_dropped_on_import` alone isn't success.**
A hard failure not attributable to one formula exits non-zero with `import_status: ERROR`
and an empty `formulas_dropped_on_import` too. If `import_status` isn't `"OK"`, report
`import_error` and stop.

**If `import_status == "OK"` and `formulas_dropped_on_import` is empty (or absent):**
Report success. Proceed to Step 7.5 regardless of migration pace.

**If `formulas_dropped_on_import` is non-empty — behaviour depends on `{migration_pace}`:**

### Fast mode (`{migration_pace}` = `F`)

Report the parked count and a summary table, then move on:

See [references/step-7-review-templates.md](references/step-7-review-templates.md) "Fast mode — Phase 2 complete report" for the exact report shape (imported
count, parked count, and the parked-formula summary table).

Save `{parked_formulas}` (the full list of dicts from `formulas_dropped_on_import`)
for use in Steps 12 and 12.5.

### Complete mode (`{migration_pace}` = `C`)

Enter the **formula fix cycle** — a bounded loop that attempts to fix and re-import each
dropped formula. **Caps:** max 15 formulas attempted (park the rest), max 3 attempts each.

**Process** (dependency order — level-0 first), for each dropped formula (up to 15):

1. **Analyze** — read `error`/`expr` from the dropped dict.
2. **Skip if not fixable** — the error references another parked formula (dependency chain
   — fix that one first) or indicates a missing table/column (structural, not an expression
   fix).
3. **Attempt a fix** — rewrite the expression per the error (parenthesise, fix function
   name, add `TABLE::` qualifier, wrap date literal in `to_date()`), export the current
   model (`ts tml export {model_guid} --profile {profile_name} --parse`), add the fixed
   formula as a new `formulas[]`+`columns[]` pair, import (`ts tml import --profile
   {profile_name} --policy ALL_OR_NONE`, `guid` pinned). Success → ✅ Migrated, remove from
   parked; failure → record the new error, decrement attempt counter, try a different fix;
   after 3 failures → ⏸ Parked (exhausted).
4. **After level-0 is fixed**, retry level-1+ formulas whose dependencies are now imported
   (may succeed with no expression change).

Report after the fix cycle:

See [references/step-7-review-templates.md](references/step-7-review-templates.md) "Complete mode — fix cycle complete report" for the exact report shape
(fixed count, remaining-parked count, per-formula fixed/still-parked lists).

Save `{parked_formulas}` (the remaining parked list) for Steps 12 and 12.5.

---

Report validation warnings regardless of pace:
- If `validation_warnings` is non-empty: surface warnings. Entries are not all about
  formulas — an entry marked `kind: "join"` reports a join `_extract_joins` skipped
  (its `name` is the datasource, not a formula), and belongs in the report's Join
  warnings section. An entry without that marker is a formula that may have syntax
  issues but was still attempted, or carries `review_notes` (assumed-Sunday weekday; week
  start, BL-334) — surface them; `review_required` ones go under Formulas needing review.

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
> - SpotterViz's `data_source_id` (Step 10) — the guid is enough, but the obj_id is the
>   same cheap capture and the Step 11.5 coverage answers need it too;
> - every Step 11.5 coverage-answer `answer.tables[].obj_id` — a wrong obj_id makes **every
>   tile fail to bind** (`"No table with object_id … found"`), forcing a delete + re-import;
> - the cohort `worksheet.obj_id` (Step 5b) — cohort binding is more lenient (it may resolve
>   by name and still import), but use the real obj_id anyway for correctness.
>
> Capture it from any of these (cheapest first): the **import response header** `objId`;
> `ts metadata search --guid {model_guid}` → `metadata_obj_id`; or a model export. Save it as
> `{model_obj_id}`. Doing this **once, up front** is the single biggest speed win — it
> removes the build→fail→delete→re-import cycle entirely for every downstream reference.

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
only)**, or **scope 5 (Tables only)** in Step 1.5, skip this entire step and Steps 9–10 —
go straight to **Step 11.5** (coverage, scopes 2/4) then **Step 12**. In **scope 3
(Liveboards only)** this step is the entry point (the model came from Step 1.5a); the
SpotterViz build (Step 10) describes tiles against that model's columns.

**If Step 1.6 ended with the user declining SpotterViz setup**, skip this step (and 9, 10)
the same way — tell the user again that dashboards can't be migrated to liveboards this
session, then go straight to Step 11.5/12.

If Step 3d found zero `<dashboard>` elements, skip to **Step 11.5** (a model-only workbook
still benefits from coverage answers), then Step 12.

Otherwise (scope 1 or 3 with dashboards, and SpotterViz connected), present the decision:

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

**T** describes each dashboard as its own tab in one SpotterViz build; **S** builds them as
independent liveboards. Either way, Step 10 asks SpotterViz to add a Migration Summary tab.

---

## Step 9 — Parse Dashboard Layout and Map to Grid

### 9a. Zone extraction

For each `<dashboard>` element in the TWB, walk `<zones>` → `<zone>` elements
recursively. For each leaf zone, extract `zone_id`, `zone_type`, `worksheet_name`,
`x`/`y`/`w`/`h`, `text_content`, `parent_zone`+`param`, and `floating` — see
[references/step-10-liveboard-generation.md](references/step-10-liveboard-generation.md)
"Zone extraction field reference (Step 9a)" for the exact attribute source of each field.
**Keep the `parent_zone` nesting** — don't flatten to a coordinate list; the container tree
is the layout's real structure (9c).

Classify each zone:
- **Chart zones**: a worksheet viz — a leaf zone carrying a `name` (worksheet name) and no
  more specific sub-type. These become visualization tiles.
- **Text/title zones**: `type="text"` or `type="title"` → becomes a note/annotation in the
  Step 10 SpotterViz build instructions.
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
vertical layout containers** (with absolute 0–100,000 coords as a fallback). Map the
**container tree**, not raw coordinates — a flat y-band scan misgroups zones whenever two
containers share a y range. See
[references/step-10-liveboard-generation.md](references/step-10-liveboard-generation.md)
"Container-tree grid mapping algorithm (Step 9c)" for the full walk/split/height algorithm
(the `vert`/`horz` recursion, the largest-remainder 12-column split, the aspect-ratio row
height, the y-band fallback, and floating-zone handling). **Invariant: column spans in each
row must sum to exactly 12**, with a minimum `col_span` of 2 per tile.

Save the grid layout as a list of tiles with `zone_id`, `zone_type`, `worksheet_name`,
`col` (x), `col_span` (width), `row_span` (height), `y`. Step 10's SpotterViz build
instructions don't need literal pixel/grid coordinates, but this relative layout — which
zones share a row, which are grouped, left-to-right order — is exactly what turns "here are
six tiles" into a clear description of the source dashboard's actual structure. Column spans
in each row must sum to 12; keep a stable left-to-right order matching the source.

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
   (name which), or **none**. For any the user picks, describe them as additional tiles in
   Step 10's SpotterViz build instructions, appended after the dashboard's own tiles.
5. **Record the outcome** in the Migration Summary (Step 10): which orphans existed, which
   were added, which were left off (and that the model still supports them via Spotter).

**MUST-ASK — never skip the prompt or decide on the user's behalf**, even when the dashboard
looks complete; orphans frequently include an overall-rate or breakdown view the author
drafted but forgot to place. Default the recommendation to **"add as tiles"** for orphans
representing a distinct, useful view — the user can always decline.

---

## Step 10 — Build Liveboard via SpotterViz

> **Scope gate:** runs for scopes **1, 3**, and only when Step 1.6 confirmed SpotterViz
> connectivity. If the user declined setup at Step 1.6, this step does not run — Step 8
> already told the user why and routed to Step 11.5/12 instead.

This skill builds every liveboard through **SpotterViz** — there is no hand-authored-TML
path. See
[`../../shared/schemas/spotterviz-liveboard-build.md`](../../shared/schemas/spotterviz-liveboard-build.md)
for the full procedure (connectivity, the `is_spotter_enabled` gate, build-instruction
composition, polling, and known gotchas). The condensed steps:

1. **Re-confirm `is_spotter_enabled` on the target model.** Export it
   (`ts tml export {model_guid} --profile {profile_name} --parse`) and check
   `properties.spotter_config.is_spotter_enabled`. If `false` or absent, ask the user to
   enable it (even if Step 5.5 declined AI search generally — SpotterViz depends on this
   specific property regardless), set it `true`, and re-import in place (existing
   `guid`/`obj_id` at the document root, `--no-create-new`) before proceeding. If they
   decline, liveboard generation cannot proceed for that model.
2. **Compose build instructions**, one per dashboard (or one per tab, if Step 8 chose
   **T**). Use Step 9's zone classification, worksheet shelves, and relative layout to
   describe — in plain language — what each tile should show and how tiles group together;
   use `thoughtspot-chart-types.md`'s analytical-intent vocabulary for chart-intent wording.
   Append any Step 9d orphan worksheets the user chose to add. Ask for a final **Migration
   Summary** tab in the same instructions, covering: items migrated (and how), decisions
   made, partial/placeholder items (what's missing, why), and items not migrated (and why)
   — see [references/migration-report-format.md](references/migration-report-format.md)
   "Migration Summary content" for the exact four-section shape; keep it consistent with
   the Step 12 report.
3. **Call `create_dashboard`** (new liveboard) or `modify_dashboard` (iterating on one
   already built this session) with a `title`, the composed `instructions`, and
   `data_source_id` set to the model's `{model_obj_id}` (captured in Step 7).
4. **Poll `get_dashboard_status`** until `completed` (capture the returned Liveboard
   guid/URL), `needs_input` (relay the question to the user verbatim, get an answer,
   resubmit), or `failed` (report plainly — never treat as success).
5. **Display the result:**
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
   SpotterViz built in Step 10), subtract those already referenced by a liveboard tile. The
   remainder are uncovered. (For a model-only workbook, **all** formulas are uncovered.)
2. **Build one simple answer per uncovered formula** — a minimal, testable viz, hand-authored
   as Answer TML (see `../../shared/schemas/thoughtspot-answer-tml.md`) — this is the one place
   in this skill that still hand-authors TML, since it's a single-tile test fixture, not a
   dashboard:
   - A measure → a KPI (`[Formula]`) or a small BAR by a natural dimension (`[Region] [Formula]`).
   - A string/label formula → a `TABLE_MODE` tile (`[Region] [Formula]`).
   - Reference columns by their **resolved display name**, and use the model's real `obj_id`
     (see the obj_id rule in Step 7) for `answer.tables[].obj_id` — a wrong obj_id makes the
     tile fail to bind.
   - **Put the original Tableau formula in the answer's `description`** (e.g.
     `description: "Coverage tile for Rank of profit  ·  Tableau: RANK_UNIQUE(SUM([Profit]),'desc')"`)
     so a reviewer can compare the source expression to the migrated one without leaving the tile.
3. **Where they live:**
   - **Liveboard exists** (built via SpotterViz, Step 10) → add a **"Formula coverage"** tab to
     it (one tile per uncovered formula). Export the liveboard, append the tab, and re-import in
     place: set `guid` **and** `obj_id` to the existing object's values, import with
     `--no-create-new`, and keep both **top-level keys of the TML document — siblings of
     `liveboard:`, not nested inside it** (nesting them as `liveboard.guid` means the import
     never matches and forks a duplicate with a new guid, every time, regardless of `--policy`).
     Verify the returned `id_guid` is unchanged afterward.
   - **No liveboard** (model-only) → create **standalone saved answers** (one per formula) bound
     to the model, so each is independently openable.
4. **Note it** in the Step 12 report (a formula's coverage tile/answer counts as ✅ reachable).

For table-mode coverage tiles, **omit the `chart` block** and set `display_mode: TABLE_MODE`
(`chart.type: TABLE` is invalid; charted tiles must use a verified chart type —
`BAR/LINE/PIE/KPI/AREA`).

> **Spotter-seeded coverage tiles.** Step 12.6 can build coverage tiles here too — seeding
> `search_query` from Spotter's returned `tokens` and the chart type from its
> `visualization_type` — for measures Spotter expressed and you verified. Same tile shape and
> re-import rules as above; the only difference is where the search came from.

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
in-product **Migration Summary** tab (requested in Step 10's SpotterViz build instructions)
and any `MIGRATION_LIMITATIONS.md`.

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

**If Y or S:** Enter the **exact same fix cycle** as Complete mode (Step 7 Phase 2, above:
analyze error → skip if fixable-blocked → rewrite → export/add/import with GUID pinned →
✅ on success or ⏸ after 3 failures → retry level-1+ once level-0 is fixed) — start by
exporting the current model (`ts tml export {model_guid} --profile {profile_name} --parse`).

After the cycle, **regenerate the Step 12 report** with updated formula statuses. Parked
formulas that were fixed move to ✅ in the formula mapping table; the ⏸ Parked section
shrinks or disappears.

---

## Step 12.6 — Spotter Last-Mile (Parked Formulas)

> **Scope gate:** runs for scopes **1, 2, 4** (wherever formulas are imported).
> **Condition:** only runs when `{parked_formulas}` is still non-empty *after* Step 12.5,
> **and** Spotter is enabled on the model (Step 5.5 = Y). Requires **ts-cli ≥ v0.53.0**.
> **Optional** — offer it; never run it silently.

Deterministic rewriting (Step 12.5) fixes formulas syntactically derivable from the Tableau
expression. What remains parked is usually a measure whose *intent* is clear in English
even though no mechanical translation exists — Spotter can often express that intent as a
ThoughtSpot Search. This step asks Spotter, shows what it produced, and lets you **verify
then adopt or leave parked** (never auto-adopts — same **surface, recommend, resolve**
principle as the rest of this skill).

Prompt:

```
{N} formula(s) are still parked and Spotter is enabled on the model.
Ask Spotter to express each as a ThoughtSpot Search? [Y / n] (default: Y)

  Y  Yes    — ask Spotter per formula, show its tokens, you verify + adopt/park
  N  No     — leave them parked; the Step 12 report stands
```

**If N:** end here; the report is unchanged.

**If Y:** for each parked measure expressible as a plain-English question (skip structural/
table-addressing artifacts — Spotter answers questions about data, not row-offset window
mechanics): (1) phrase the intent as a natural-language question from the parked record's
`original_tableau` expression and name (e.g. `SUM([Profit])` growth-vs-prior-year →
`"year over year growth of profit by month"`); (2) ask Spotter (CLI-first, never raw
`requests`):

```bash
ts spotter answer "year over year growth of profit by month" \
  --model {model_guid} --profile {profile_name}
```

Output JSON `{status, tokens, display_tokens, visualization_type, errors}`: `SUCCESS` →
`display_tokens` is the human-readable Search (`tokens` is the raw form); `FORBIDDEN` → the
profile's user lacks `CAN_USE_SPOTTER`/view access — stop the step, tell the user, leave
parked (entitlement issue, not translation failure); `SPOTTER_ERROR` → leave that formula
parked, continue with the rest. (3) **Verify the numbers — never trust the tokens blind.**
Present `display_tokens` next to the original Tableau expression and confirm the result
matches the source (run as a Step 11.5 coverage answer, or `ts agentql fetch-data` against
the model and compare). (4) **Adopt or park (user decides):** match + approval → adopt (add
via the Step 12.5 fix cycle, or `ts model promote-formula` for an answer formula — becomes
✅ Migrated); mismatch or unsure → leave ⏸ Parked, recording Spotter's suggested tokens for
manual follow-up.

5. **Materialize a coverage viz from Spotter's answer (opt-in, human-approved)** — for each
   adopted measure, offer to build a Step 11.5 coverage tile seeded from Spotter's answer.
   See [references/migration-report-format.md](references/migration-report-format.md)
   "Step 12.6 — materializing a Spotter last-mile coverage tile" for the field mapping
   (`search_query`/`display_mode`/`description`) and the ask-before-adding rule. A tile is
   only ever added for a measure whose number was verified in step 3 and the user approved.

**Never** promote a Spotter suggestion to ✅ without a confirmed number match — an
AI-generated Search that *looks* right but returns different numbers is worse than an
honestly-parked formula. When in doubt, park it and say so in the report.

After the step, **regenerate the Step 12 report**: adopted formulas move to ✅ (note
"via Spotter last-mile" in the mapping table); the ⏸ Parked section lists any that Spotter
suggested-but-unverified with its tokens for manual follow-up.

---


### String comparisons become case-insensitive (BL-333)

ThoughtSpot lowercases both sides of every string comparison (`=`, `!=`, `in { }`, `<`/`>`, `contains`, `strpos`; live-probed 2026-10-06/07). A source comparison that is case-sensitive (Tableau follows its data source; on a live Snowflake or Databricks connection comparisons are case-sensitive) therefore matches more rows after conversion: `'abc'` now equals `'ABC'`, and ordering comparisons can change. This is an accepted, documented trade-off. Where exact case matters for a specific formula, hand-edit it to `sql_bool_op ( "{0} = {1}" , [col] , 'x' )` (or `CONTAINS({0}, {1})`). See `agents/shared/schemas/thoughtspot-formula-patterns.md` → "String comparison is case-insensitive".

## Changelog

| Version | Date | Summary |
|---|---|---|
| 2.0.0 | 2026-10-22 | **BREAKING — liveboard generation moves to SpotterViz, dropping the hand-authored-TML path entirely; plus Model/formula-engine fixes (ts-cli v0.182.0).** Parser false positives (function-name scans now mask literals/`[ref]`s first), nested-`group_aggregate` detection (checks span containment, not match-count), LOD brace-scanning (single-pass stack scanner skipping `[ref]` spans), `convert_string_concat` gated on `datatype == "string"`, import-retry no longer fails open or reports success on an unattributable failure, parameter types `INT64`/`DATE`, `range_config` → `range_min`/`range_max`, and mapping-doc fixes (nested-`group_aggregate` workaround, ratio-explosion, `WINDOW_AVG`/`STDEV` reconstruction, CHAR-parameter casts, dynamic-grain `DATETRUNC`) — backlog BL-403/404. **Liveboard generation:** new Step 1.6 confirms SpotterViz MCP connectivity before any parsing work (scope 1/3), with setup instructions if it's missing and a clear "liveboards can't be built this session, Model/Table work is unaffected" message if the user proceeds without it. Step 10 checks which Tableau fields actually survived model-build before describing any tile, re-confirms `is_spotter_enabled`, composes natural-language build instructions from Step 9's zone/shelf/layout extraction, calls `create_dashboard`/`modify_dashboard`, polls to completion, **then verifies every tile actually runs and returns data** — retry once, and record any still-failing tile in the Migration Summary and Step 12 report. Removed: the charting-library choice (Legacy/Muze), hand-authored chart-type/search-query/layout-beautify/grouping rules, parameter header chips, and the 6-theme styling pass — none apply to a SpotterViz-built liveboard. See `../../shared/schemas/spotterviz-liveboard-build.md` for the full procedure and known gotchas. Step 11 (hand-authored TML import) removed; Step 11.5's coverage answers still hand-author a single-tile Answer TML (unaffected) and absorbed the top-level `guid`/`obj_id` re-import rule Step 11 used to carry. |

**Older entries (v1.0.0–v1.46.0):** see [references/changelog-archive.md](references/changelog-archive.md) for the full history — the operative rules/gotchas from those entries are already reflected in the procedure above.
