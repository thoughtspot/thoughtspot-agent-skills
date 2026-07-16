---
name: ts-convert-from-twb-to-tml
description: Convert or import a Tableau workbook (.twb or .twbx) into ThoughtSpot — parses TWB XML, generates table + model TMLs, validates and imports. Optionally migrates dashboards to liveboards with layout approximation. Direction is always Tableau → ThoughtSpot. Not for ThoughtSpot → Tableau or standalone TML exports.
---

# Tableau Workbook → ThoughtSpot

Converts a Tableau workbook into ThoughtSpot objects. Parses the TWB XML to extract
tables, columns, joins, and calculated fields, then generates Table TMLs and a Model
TML per datasource. Optionally converts Tableau dashboards into ThoughtSpot Liveboards
with approximate layout mapping.

Ask one question at a time. Wait for each answer before proceeding.

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
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth setup |
| [references/open-items.md](references/open-items.md) | Known validation quirks and workarounds |
| [references/liveboard-style-themes.md](references/liveboard-style-themes.md) | Step 10.5 curated themes — brand tokens + per-chart `viz_style` color palettes |

### Tools used by this skill

| Tool | CLI command | Step | What it does |
|---|---|---|---|
| T1 | `ts twb parse` | 3, A2 | Parse TWB XML → structured JSON (tables, columns, joins, calc fields, params, topo sort) |
| T2 | `ts twb translate-formula` | 3.5, A3 | Classify + translate mechanical formulas; flag judgment-tier for Claude |
| T3 | `ts twb generate-tml` | 5 | Generate Table, SQL View, and Model TMLs from parsed workbook (deterministic) |
| T4 | `ts twb postprocess` | 6 | Deterministic TML fix-up (names, refs, joins, obj_ids, dedup, cross-ref check) |
| T5 | `ts twb validate` | 6.5 | Local proofread + VALIDATE_ONLY + error classification + attempt tracking |
| T7 | `ts twb verify` | 6.7 | Coverage/fidelity audit — TWB↔TML diff for silent drops |

### Context budget rule — NEVER Read tool output files

**Do NOT use the Read tool on `parsed.json`, `translated.json`, or any other `--out`
file produced by the tools above.** These files are consumed on disk by downstream
tools and by generation scripts via `json.load()` — never by reading them into
conversation context. A single `parsed.json` from a real workbook is ~55K tokens;
reading it wastes context, risks compaction, and is always redundant.

- **`ts twb parse`** → use the **stdout compact summary** to announce results
- **`ts twb translate-formula`** → use the **stdout compact object** (`summary`,
  `judgment[]`, `reference[]`, `parameters[]`) for Step 5 decisions
- **Generation scripts** → write Python that does `json.load(open(...))` from disk
- **Debugging a specific failure** → Read only the failing excerpt with `offset`/`limit`

---

## Prerequisites

- ThoughtSpot profile configured — run `/ts-profile-thoughtspot` if not
- `ts` CLI installed: `pip install -e tools/ts-cli`
- Tableau workbook file (`.twb` or `.twbx`) accessible on disk
- **The source tables and their data already exist in a warehouse, and a ThoughtSpot
  connection exposes them.** This skill creates ThoughtSpot *logical* objects (Table, Model,
  cohorts, Liveboard) **over existing physical tables** — it does **not** create warehouse
  tables or load/populate data. A ThoughtSpot table binds to a live connection that already
  surfaces the physical table and its columns (see Step 4 / `thoughtspot-table-tml.md`); if no
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
**ts-convert-from-twb-to-tml** — convert a Tableau workbook into ThoughtSpot TML objects,
with optional dashboard-to-liveboard migration.

### Modes

  **A  Audit** — analyse a TWB file (or multiple files) and report migration coverage.
     No ThoughtSpot auth required. No TMLs generated. Use this to assess feasibility
     before committing to a migration.

  **M  Migrate** — full conversion: parse, generate TMLs, validate, and import.

Enter A / M:

### Steps (Migrate mode)

  1.  Authenticate to ThoughtSpot .......................... auto
  2.  Locate the TWB/TWBX file ............................. you provide path
  2.5 Table mapping file (optional) ........................ you provide path (or skip)
  3.  Parse TWB — `ts twb parse` (T1) .................. auto
  3.5 Classify formulas — `ts twb translate-formula` (T2) auto
  4.  Select ThoughtSpot connection (required) .............. you choose
  4.5 Confirm source tables (reuse vs. create; search) ..... you choose
  5.  Generate TML files — `ts twb generate-tml` (T3) .. auto + LLM judgment
  5.5 Confirm Spotter (AI search) enablement (default Y) ... you choose
  6.  Post-process TMLs — `ts twb postprocess` (T4) .... auto
  6.5 Validate — `ts twb validate` (T5) ................ auto (loop)
  6.7 Coverage audit — `ts twb verify` (T7) ............ auto
  7.  Review checkpoint (formula map + omissions) + import .. you confirm
  7.5 Confirm the model is correct (test in Search/Spotter)   you confirm
  8.  Migrate dashboards? + separate vs single-tabbed (2+) . you choose (skip → Step 12)
  9.  Parse dashboard layout and map to grid ................ auto
  9d. Orphan worksheets (not on a dashboard) — add as tiles? you choose
 10.  Generate liveboard TML ................................ auto
 10f. Add referenced parameters to the header? (default Y) . you choose
 10g. Add a "Migration Summary" tab (migrated/decisions/omitted) auto
 10.5 Pick a liveboard style (curated theme; default) ...... you choose
 11.  Import liveboard ...................................... you confirm
 11.5 Formula coverage answers (every formula testable) .... auto
 12.  Migration report (outcomes + links + formula map) .... auto

Confirmation required: Steps 4.5, 5.5, 7, 7.5, 8, 9d, 11
Auto-executed: Steps 1, 3, 3.5, 5, 6, 6.5, 6.7, 9, 10, 12
Tools used: T1 parse, T2 translate-formula, T3 generate-tml, T4 postprocess, T5 validate, T7 verify

Steps 9–11 (dashboard→liveboard detail) are loaded on demand from
`references/stage2-liveboards.md` only when you migrate dashboards at Step 8 — a
model-only run (Steps 1–7.5, then 11.5–12) never loads them.

### Steps (Audit mode)

  A1.  Locate TWB/TWBX file(s) ............................. you provide path(s)
  A2.  Parse TWB — `ts twb parse` (T1) .................. auto
  A3.  Classify formulas — `ts twb translate-formula` (T2) auto
  A4.  Migration coverage report ............................ auto

No auth, no TML generation, no import. Supports multiple files in one run.
Tools used: T1 parse, T2 translate-formula

---

If Audit mode, proceed to Step A1. If Migrate mode, proceed to Step 1.

---

## Step A1 — Locate TWB File(s) (Audit Mode)

Ask: "Provide the path to a `.twb` or `.twbx` file, or a directory containing multiple
workbooks."

If a directory is provided, find all `.twb` and `.twbx` files recursively. Save the
list of file paths. Process each file through Steps A2–A4 independently.

---

## Step A2 — Parse TWB (Audit Mode)

Run `ts twb parse` on each file with `--out` (full JSON to a file, compact summary to
stdout). The tool handles `.twbx` extraction internally.

```bash
ts twb parse "{file_path}" --out /tmp/ts_tableau_audit/{file_stem}/parsed.json
```

`stdout` is a compact structural summary; the full structured JSON (datasources, tables,
columns, joins, calculated fields topo-sorted by level, parameters, dashboards) lands at
the `--out` path and feeds Step A3 and A4. Announce from the summary — don't read the file.

Do NOT skip any datasource type. For extracts, the parser resolves the underlying source
and reports it as migratable; mark as "Extract — no underlying source" only when none
resolves.

---

## Step A3 — Classify Formulas (Audit Mode)

Run `ts twb translate-formula` in batch mode on the parsed JSON from Step A2, with
`--out` so stdout stays compact:

```bash
ts twb translate-formula --input /tmp/ts_tableau_audit/{file_stem}/parsed.json --out /tmp/ts_tableau_audit/{file_stem}/translated.json
```

The compact stdout gives you the `summary` tier counts (`translatable`/`query_time`/
`untranslatable`/`judgment`) directly — that's exactly what the coverage report in Step A4
needs — plus the `judgment[]` formulas to describe. The full per-formula detail (`tier`,
`deterministic`, `translated`, `reason` for every formula) is in the `--out` file if you
need to enumerate specifics.

### Tier reference (produced by the tool)

| Tier | Description | Examples |
|---|---|---|
| **Native / Set** | Direct ThoughtSpot mapping exists | IF/THEN, IFNULL, DATEDIFF, LEFT, ABS, ROUND, IIF; **bins** (`class='bin'`) → `floor([x]/size)*size` or BIN_BASED cohort; **manual groups** (`class='categorical-bin'`, incl. fields named "… clusters") → `GROUP_BASED` cohort; `Number of Records`/row counts → `count([column])` (**prompt** for the column; default the primary key) |
| **LOD** | LOD expression → `group_aggregate()` | `{FIXED dim : SUM(col)}`; **`TOTAL(SUM(x))`** / percent-of-total → `group_aggregate(..., {}, query_filters())` |
| **Cumulative** | Running calculation → `cumulative_*()` | RUNNING_SUM, RUNNING_AVG |
| **Moving** | Window table calc → `moving_*()` | WINDOW_SUM, WINDOW_AVG (when sort attr determinable) |
| **Pass-through** | Valid SQL but no native function → `sql_*_aggregate_op()` | Partitioned RANK, DENSE_RANK, WINDOW_* without sort context |
| **Untranslatable** | No ThoughtSpot equivalent — will be omitted | LOOKUP, INDEX, SIZE(), PREVIOUS_VALUE; true **k-means clustering** (the analytics-engine "Clusters" calc — **not** `categorical-bin`) |
| **Parameter ref (auto)** | References a Tableau parameter with static list/range — parameter auto-created in model | `[Parameters].[Currency]` where Currency has `<member>` values |
| **Parameter ref (query)** | References a Tableau parameter with SQL-lookup list — queryable at migration time | SQL-populated parameter lists (needs connection) |

### What the tool handles vs. what needs judgment

- **`deterministic: true`** — the tool produced a complete translation. Use it as-is in
  Step 5. These include: IF/THEN/ELSE, ZN→ifnull, LEN→strlen, CASE→if/else, date
  functions, math functions, string functions, simple aggregations.
- **`deterministic: false`** (query-time) — the tool flagged it for Claude to handle in
  Step 5. These include: LOD expressions, window/running functions (need context from
  worksheet shelves), growth/decline patterns, blend references.
- **`tier: untranslatable`** — no ThoughtSpot equivalent. Omit from `formulas[]` in Step 5
  and document in the limitations report.

**Parameter references.** Detect `[Parameters].[...]` pattern — this is Tableau's
cross-datasource parameter reference syntax. These formulas use translatable syntax
(IF/CASE/WHEN). Cross-reference the parameter name against the parameter definitions
extracted in Step A2/3:
- If the parameter has static `<member>` list values or a `<range>` → **Parameter ref
  (auto)** — the parameter will be auto-created in the model TML, formula translates
  with a simple `[Parameters].[Name]` → `[Name]` prefix strip
- If the parameter has no static values (SQL-lookup populated) → **Parameter ref
  (query)** — auto-migratable at migration time (requires warehouse connection to
  populate list values), but flagged separately in audit mode since no connection
  is available

**LOD first.** Check `{FIXED|INCLUDE|EXCLUDE}` before other tiers — LOD expressions
may also contain functions like SUM that would match Native.

For each formula, also check:
- Does it reference other calculated fields? (cross-reference depth)
- Does it use functions from the untranslatable list?
- Does it mix translatable and untranslatable patterns?

---

## Step A4 — Migration Coverage Report (Audit Mode)

For each TWB file, produce a coverage report. If multiple files were audited, also
produce a combined summary at the end.

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
  │ Parameter ref (auto)    {N}     {%}   static list   │
  │ Parameter ref (query)   {N}     {%}   SQL lookup    │
  │ Untranslatable          {N}     {%}   LOOKUP        │
  └──────────────────────────────────────────────────────┘

  Parameters:           {N} total ({N} static, {N} SQL-lookup — query at migration)
  Dashboards:           {N} (optional liveboard migration)

  ──────────────────────────────────────────────────
  Migration coverage:   {(all except untranslatable) / total}%
                         (all parameters auto-created — static or queried)
  Untranslatable:       {N} formula(s) — will be omitted
  SQL-lookup params:    {N} — need warehouse connection at migration time
  Pass-through formulas require SQL Passthrough Functions enabled.
  ──────────────────────────────────────────────────
```

**Migration coverage** includes everything except Untranslatable. All parameter types
are auto-migratable: static params are created directly in the model TML; SQL-lookup
params are populated by querying the warehouse at migration time. The formula reference
`[Parameters].[Name]` is rewritten to `[Name]` in both cases.

If any formulas are classified as Untranslatable, list them:

```
  Untranslatable formulas (will be omitted):
    - {formula_name}: {reason} — {expression excerpt}
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

**Combined summary (multiple files):**

```
Audit Summary: {N} workbook(s)
══════════════════════════════════════════════════════

  Workbook                          Tables  Calcs  Coverage
  ─────────────────────────────────────────────────────────
  {workbook_1}                      {N}     {N}    {%}%
  {workbook_2}                      {N}     {N}    {%}%
  ...
  ─────────────────────────────────────────────────────────
  Total                             {N}     {N}    {%}%
```

After the audit, exit cleanly. Do NOT proceed to Migrate mode steps.

---

## Step 1 — Authenticate

Read `~/.claude/thoughtspot-profiles.json`. If multiple profiles exist, display a
numbered menu and ask the user to choose. If only one profile, use it automatically.

```bash
source ~/.zshenv && ts auth whoami --profile "{profile_name}"
```

Save `{base_url}` and `{profile_name}` for all subsequent steps.

---

## Step 2 — Locate TWB/TWBX File

Ask for the file path if not yet provided. Accept `.twb` or `.twbx` — the `ts twb
parse` tool (Step 3) handles `.twbx` extraction internally.

Save the file path as `{twb_path}`.

Create the output directory:

```bash
mkdir -p /tmp/ts_tableau_mig/output
```

---

## Step 2.5 — Table Mapping File (Optional)

Ask: "Do you have a table mapping file that maps Tableau source tables to ThoughtSpot
target tables? (Provide file path, or type "skip" to skip)"

This step is **entirely optional**. If the user skips it, Steps 4/4.5 resolve tables
from the connection hierarchy as usual. If the user provides a mapping file, its entries
override the connection-based resolution for the tables it covers.

### Mapping file format

A plain text file with one mapping per line. Each line has a source (left) and target
(right) separated by `:` or `-`. Whitespace around separators is trimmed.

**Simple mapping** — one Tableau table → one ThoughtSpot target:

```
PARTNER_DM.PX_TBL_TAB_DS_CLICKSTREAM_PAGE_LEVEL_AGG : STG_DATALAKEHOUSE.ENTERPRISE_WAREHOUSE_RPT.VW_PX_TBL_TAB_DS_CLICKSTREAM_PAGE_LEVEL_AGG_RPT
DATA_SCIENCE.CUSTOMER_SEGMENTS - STG_DATALAKEHOUSE.ENTERPRISE_WAREHOUSE_RPT.VW_CUSTOMER_SEGMENTS_RPT
```

**Multi-source mapping** — multiple Tableau tables (comma-separated) consolidated into one
target view (typically a custom SQL replacement):

```
NG_VIEWS.SHIPT_CATEGORY_SERVICE_PRODUCT_CATEGORIZATIONS,
PRD_DATALAKEHOUSE.PARTNER_DM.dim_product_details_unified,
PRD_DATALAKEHOUSE.PARTNER_DM.px_tbl_tab_ds_clickstream_popular_category_events : STG_DATALAKEHOUSE.ENTERPRISE_WAREHOUSE_RPT.VW_PARTNER_CLICKSTREAM_CATEGORY_PRODUCTS_RPT
```

Multi-source entries may span multiple lines — the continuation lines are
comma-terminated and the final source is followed by the separator (`:` or `-`).

The target (right side) is always a fully qualified `DB.SCHEMA.TABLE` or
`DB.SCHEMA.VIEW`. An optional parenthesized note may follow the target — ignore it
(it is a human comment, not part of the name).

### How to parse and use the mapping

Read the file and build a `{table_mapping}` dictionary:

```python
table_mapping = {
    "PARTNER_DM.PX_TBL_TAB_DS_CLICKSTREAM_PAGE_LEVEL_AGG": {
        "db": "STG_DATALAKEHOUSE",
        "schema": "ENTERPRISE_WAREHOUSE_RPT",
        "db_table": "VW_PX_TBL_TAB_DS_CLICKSTREAM_PAGE_LEVEL_AGG_RPT"
    },
    ...
}
```

For multi-source entries, map **each** source table to the same target. These typically
correspond to custom SQL datasources in the TWB — the multiple source tables were joined
in Tableau's custom SQL and the target is a pre-built view that replaces that SQL.

Matching is **case-insensitive** on the source side. A source like
`PARTNER_DM.PX_TBL_TAB_DS_CLICKSTREAM_PAGE_LEVEL_AGG` matches a parsed TWB table named
`Partner_DM.px_tbl_tab_ds_clickstream_page_level_agg`. Match on the rightmost components
— a two-part source `SCHEMA.TABLE` matches a three-part parsed name
`DB.SCHEMA.TABLE` if the schema and table match.

Save `{table_mapping}` — it is consumed in:

- **Step 4/4.5** — for any table that appears in `{table_mapping}`, use the mapped
  `db`/`schema`/`db_table` instead of resolving from the connection hierarchy. Tables
  NOT in the mapping still resolve from the connection as before.
- **Step 5** — when generating Table TMLs and model `model_tables[]` entries, use the
  mapped names for tables that have an override.

Display the loaded mapping to the user for confirmation:

```
Loaded {N} table mapping(s):

  Tableau source                                    → ThoughtSpot target
  PARTNER_DM.PX_TBL_TAB_DS_CLICKSTREAM_PAGE_LEVEL_AGG → STG_DATALAKEHOUSE.ENTERPRISE_WAREHOUSE_RPT.VW_PX_TBL_TAB_DS_CLICKSTREAM_PAGE_LEVEL_AGG_RPT
  DATA_SCIENCE.CUSTOMER_SEGMENTS                    → STG_DATALAKEHOUSE.ENTERPRISE_WAREHOUSE_RPT.VW_CUSTOMER_SEGMENTS_RPT
  …

Proceed with these mappings? (yes / no):
```

If the user says no, discard and continue without mappings (fall back to connection
resolution).

---

## Step 3 — Parse TWB (`ts twb parse`)

Run the `ts twb parse` tool (T1) to extract all structured data from the TWB.
**Use `--out` so the full JSON is written to a file and only a compact summary comes
back to you** — the full parse of a real workbook is ~55K tokens; you do not need it in
context to report structure. Downstream tools read the file directly.

```bash
ts twb parse "{twb_path}" --out /tmp/ts_tableau_mig/output/{workbook_name}/parsed.json
```

`stdout` is a small summary (`counts`, per-datasource breakdown, dashboard names); the full
structured JSON lands at the `--out` path as `parsed.json`. **Do not read `parsed.json` into
context at this step** — announce the summary from stdout and move on. (The later tools —
`translate-formula`, `postprocess`, `generate-tml` — consume the file on disk.) The tool handles:

- `.twbx` extraction (unzips automatically)
- Datasource type detection (live, extract with underlying source, published/sqlproxy)
- Physical tables (`type="table"`) with db/schema/table components
- Custom SQL relations (`type="text"`) with the full SQL text (XML entities decoded)
- Joins with type and clause conditions
- Physical columns from `<metadata-records>` (local-name, remote-name, data type, parent)
- Calculated fields with Tableau expressions (HTML entities decoded, internal cross-refs
  resolved: `[Calculation_\d+]` → display names)
- Parameters (list values, range bounds, defaults, SQL-lookup flags)
- Topological sort of calculated fields by dependency level (Level 0 first)
- Dashboard metadata (count and names)
- Relation wrapper handling (ObjectModelEncapsulateLegacy variants + fallback)

**Output structure** — the JSON contains:

```json
{
  "workbook_name": "...",
  "datasources": [
    {
      "name": "...",
      "type": "live|extract|sqlproxy",
      "tables": [...],
      "custom_sql": [...],
      "joins": [...],
      "columns": [...],
      "calculated_fields": [{"name": "...", "formula": "...", "level": 0, ...}],
      "parameters": [...]
    }
  ],
  "dashboards": [{"name": "..."}]
}
```

Save `{workbook_name}`. Announce a summary from the stdout `counts` (no file read needed):
> Parsed `{workbook_name}`: {N} datasource(s), {N} physical table(s),
> {N} calculated field(s), {N} join(s), {N} dashboard(s)

### Important rules the parser enforces

- Each datasource is independent — **never merge datasources** (see `tableau-tml-rules.md`
  "One model per Tableau datasource")
- Extracts are resolved to their underlying source; only purely synthetic extracts are
  skipped
- Custom SQL relations are flagged as `source_type: "custom-sql"` → generate `sql_view:`
  TML in Step 5c (not table TML)
- Calculated fields are sorted topologically — Level 0 has no dependencies, Level 1
  depends on Level 0, etc. This determines formula order in the model TML

---

## Step 3.5 — Classify Formulas (`ts twb translate-formula`)

Run the formula classifier/translator (T2) on the parsed output from Step 3. **Use `--out`
so the full per-formula translation is written to a file and stdout carries only what needs
your judgment** — on a typical workbook the vast majority of formulas are deterministic
(e.g. 122 of 125), and you should not spend context re-reading those:

```bash
ts twb translate-formula --input parsed.json --out /tmp/ts_tableau_mig/output/{workbook_name}/translated.json
```

`stdout` returns a compact object — read **this**, not the full file:

```json
{
  "summary": {"total": 125, "translatable": 122, "query_time": 1, "untranslatable": 2, "judgment": 3, "regex_fallbacks": 0},
  "judgment": [
    {
      "caption": "Regional Average",
      "level": 1,
      "original": "{FIXED [Region] : AVG([Sales])}",
      "translated": "",
      "tier": "lod",
      "deterministic": false,
      "reason": "LOD expression — needs judgment for group_aggregate translation"
    }
  ],
  "reference": [
    {"caption": "Total sales", "level": 0, "tier": "translatable", "translated": "sum ( [Sales] )"}
  ],
  "parameters": [{"caption": "Threshold", "internal_name": "p1", "datatype": "integer", "domain_type": "range"}]
}
```

Save `{workbook_name}/translated.json` as `{formula_translations}` (the on-disk full file).
The compact stdout feeds Step 5 (TML generation):

- **`judgment[]`** — the only formulas needing your reasoning (`deterministic: false`).
  These reappear in T3's `decisions-needed.json` (Step 5.1), where you resolve them
  via `decisions.json` using the judgment rules (LOD → `group_aggregate()`, window →
  `cumulative_*`/`moving_*`, growth patterns). `tier` guides which rules apply;
  `tier: untranslatable` ones are omitted from `formulas[]` until decided.
- **`reference[]`** — every formula's final `translated` expression, in topological `level`
  order. This is what you write into the model TML `formulas[]`, and it is how
  **cross-formula references, parameter references, and multi-level dependencies stay
  resolvable**: any `[formula_...]` a judgment formula points at is here, already translated,
  in dependency order. Do not re-translate `reference` entries — they are final.
- **`parameters[]`** — every parameter (name + type), so `[Parameters].[X]` references
  resolve and Step 5 can build `model.parameters[]` without reopening `parsed.json`.

If you ever need a formula's `original` alongside its translation for a deterministic
formula, it is in the `--out` file — but you should not need to load it.

---

## Step 4 — Select ThoughtSpot Connection

List available connections and let the user select:

```bash
source ~/.zshenv && ts connections list --profile {profile_name}
```

`ts connections list` auto-paginates and returns all connections. Display the results
as a numbered list showing connection name, type, and database. If only one connection
exists, auto-select it and confirm with the user.

```
Available ThoughtSpot connections:

  1. SNOWFLAKE_PROD    (RDBMS_SNOWFLAKE)   — PROD_DB
  2. ANALYTICS_DW      (RDBMS_SNOWFLAKE)   — ANALYTICS_DB

Which connection should the generated tables use? (Enter number):
```

Save the selected connection's exact `name` value as `{connection_name}`. This name is
used in SQL View TMLs (where `connection.name` is required) and for schema resolution.

### 4a — Ask for database and schema (required)

After the user selects a connection, ask for the database and schema. Both are
required — the generated Table and SQL View TMLs need these to bind to the correct
warehouse location.

```
Database for the source tables:
Schema:
```

Do not offer a skip option. If the user is unsure, they can check their warehouse
or the connection hierarchy. Save as `{default_db}` and `{default_schema}`.

### 4b — Resolve table locations

Resolution depends on what the user provided:

**If `{table_mapping}` exists (from Step 2.5):** for each physical table from Step 3,
first check `{table_mapping}`. If the table has a mapping entry, use the mapped
`db`/`schema`/`db_table` directly — do NOT resolve from the connection hierarchy.
If the mapped target is not found in the connection, warn the user but proceed — the
mapping is authoritative.

Fetch the connection hierarchy scoped to the user's database and schema — this returns
just the table list for that scope (fast, small response):

```bash
source ~/.zshenv && ts connections get {connection_id} --database {default_db} --schema {default_schema} --profile {profile_name}
```

Match each TWB table name against the returned table list (case-insensitive). For every
match, use `{default_db}` / `{default_schema}` / matched table name as the resolved
triplet. For any TWB table **not found** in the scoped hierarchy, warn the user — the
table may live in a different schema, or the name may differ.

```bash
# For key-pair authenticated connections (e.g. profile testing_4), add --auth-type:
ts connections get {connection_id} --auth-type KEY_PAIR --profile {profile_name}
```

**Key-pair connections:** If the connection uses key-pair authentication (e.g.
Snowflake key-pair), pass `--auth-type KEY_PAIR` on every `ts connections get` call
for that connection — without it, the API returns an empty hierarchy.

The response is always `{"databases": [ {name, schemas:[{name, tables:[{name, type,
columns:[{name, data_type}]}]}]} ]}`. Parse it to extract available databases, schemas,
and table names.

**Do NOT fetch columns at this stage.** Only resolve `{db}`, `{schema}`, `{db_table}` for
each table — do not drill down to the column level with `--table`. Column names come from
the TWB parse output (`physical_columns[]` from Step 3) and are used directly as
`db_column_name` in the generated table TMLs. This skips the per-table column fetch (the
slowest part of table resolution). If any column name is wrong (warehouse renamed it, CSV
loader normalized it), validation (Step 6.5) catches it with `column not found in
connection` — at that point, fetch columns for **only** the failing table(s) and fix all
mismatches in one pass (see Step 6.5 "Column mismatch recovery").

If the response has no databases (empty `databases`), the database or schema name
may be wrong — ask the user to double-check and provide corrected values.

A connection is **required** — there is no skip path. ThoughtSpot tables are logical
objects over a **live** connection: the physical table must already exist in the database
and the connection must already exist for the table to be created at all. You cannot
generate a usable table without one, so do not offer placeholders or a dry-run mode —
they only produce objects that can never bind to data. If the user has no suitable
connection, stop and tell them a connection exposing the source tables must be created
first (the data pipeline / connection setup is out of this skill's scope).

Use the selected connection's exact **name** in every table TML and SQL View TML — never
a GUID. The v2 API cannot search connections by name, so the name string is both
necessary and sufficient; do not try to resolve it to an ID. See
`../../shared/schemas/thoughtspot-table-tml.md` "Connection Reference".

---

## Step 4.5 — Confirm Source Tables & Search Decision

Step 4 resolved a `{db}`/`{schema}`/`{db_table}` for each physical table — but resolving
a *name* is not the same as confirming the table is actually there. A model TML that
points at a table the connection can't see will still *import* cleanly, yet every search
and liveboard built on it comes back empty. That failure is silent and easy to miss, so
confirm the source situation before generating anything. This step only **searches and
confirms** — it never loads or modifies warehouse data (that is the data pipeline's job,
not this skill's). It mirrors `ts-convert-from-databricks-mv` Step 8.

### 4.5a — Present the table list and ask (do NOT search yet)

Show the user the full inventory of physical tables from Step 3, then ask whether those
tables already exist as ThoughtSpot Table objects. **Ask before searching.** Searching
ThoughtSpot for every table on every run is wasteful when the user already knows the
answer — so the search is gated behind the user's response, not run up front.

```
Source tables referenced by {workbook_name} ({N} total):

  1. AGENT_SKILLS.AMAZON_SALES_DATA.AMAZON_SALES_DATA
  2. AGENT_SKILLS.DUAL_AXIS_EXAMPLE.LISTOFORDERS
  …

Do these already exist as ThoughtSpot Table objects?
  E  Exist      — reuse them (I'll look up their GUIDs)
  N  Don't exist — create new Table TMLs            (default)
  ?  Unsure     — search ThoughtSpot to find out

Enter E / N / ? :
```

If the tables differ in status (some exist, some don't), the user can say so — accept a
per-table answer or let them point out the exceptions.

### 4.5b — Act on the answer

- **N (don't exist)** → create a new Table TML for each in Step 5a (the default path).
  No search.
- **E (exist)** or **? (unsure)** → **MUST search ThoughtSpot before proceeding.** Do NOT
  skip this search or assume tables don't exist. "Unsure" means "I don't know — go check."
  Run:

  ```bash
  source ~/.zshenv && ts metadata search --subtype ONE_TO_ONE_LOGICAL --all --profile {profile_name}
  ```

  Match on database + schema + table name (`metadata_header.database_stripes`,
  `metadata_header.schema_stripes`, `metadata_name`). For each table found, reuse its
  name/GUID in the model's `model_tables[]` and **skip generating a Table TML** for it in
  Step 5a. For **?**, report what was/wasn't found and treat the not-found ones as create.
  For **E**, if a table the user expected is not found, say so and confirm before falling
  back to create.

  **Why this matters:** creating a new Table TML for a table that already exists on the
  cluster causes duplicate objects or import conflicts during validation. The search takes
  seconds; fixing the conflict takes much longer.

### 4.5c — Confirm any missing sources before proceeding

If any table the plan intends to **create** is *not found* in the connection, surface it
and require confirmation — this is the silent-failure case:

```
⚠ The following table(s) are not visible to connection "{connection_name}":
    - {db}.{schema}.{db_table}
  Their models will import, but searches return no data until the data is loaded
  and visible to the connection. This skill does not load data.

  Proceed anyway (generate the TMLs as-is)?   (yes / no):
```

Do not proceed past this warning without the user's confirmation.

---

## Step 5 — Generate TML Files (`ts twb generate-tml` + LLM Judgment)

This step has two parts: **T3** (deterministic CLI tool) handles mechanical TML
generation, then **Claude** answers T3's `decisions-needed.json` with a
`decisions.json` and re-runs T3 — Claude decides, the tool writes.

### 5.0 Run T3 — deterministic TML generation

T3 reads `parsed.json` + `translated.json` from disk and writes all Table, SQL View,
and Model TMLs in a single pass. It handles column mapping, join generation, parameter
migration, and all `deterministic: true` formulas from T2 — no LLM reasoning needed.

```bash
ts twb generate-tml \
  --input  /tmp/ts_tableau_mig/output/{workbook_name}/parsed.json \
  --translated /tmp/ts_tableau_mig/output/{workbook_name}/translated.json \
  --connection "{connection_name}" \
  --database "{db}" \
  --schema "{schema}" \
  --out /tmp/ts_tableau_mig/output/{workbook_name}
```

Add `--table-map "{mapping_file}"` if the user provided a mapping file in Step 2.5.

T3 runs in under 1 second and writes all `.table.tml`, `.sql_view.tml`, and
`.model.tml` files to the output directory.

**Check the summary JSON for warnings before moving on.** T3 never guesses
silently — anything it could not resolve is reported:

- `dropped_joins[]` — a join whose table reference could not be resolved to a
  generated table/view. Investigate the named tables; if the join is real,
  patch it into the model TML manually (`model_tables[].joins[]` with
  `with`/`on`/`type`).
- `unassigned_columns[]` — a column whose `parent_table` matched no generated
  table (common source: stray metadata from a custom SQL query's underlying
  table). Confirm each one is genuinely redundant before ignoring; if it
  belongs in the model, add it to the right table's TML with a correct
  `column_id`.
- `decisions_needed` — count + filename of the formula questions file. Handled
  in Step 5.1 below.

If none of these appear, T3 resolved everything — skip to Step 5.5.

### 5.1 LLM Judgment — answer `decisions-needed.json`, re-run T3

**Never hand-edit model TMLs to add or fix formulas.** Hand-patches are wiped
by any T3 re-run, drift from the TML conventions, and leave no audit trail.
Instead, formula judgment is expressed as data and applied by the tool:

1. **Read** `decisions-needed.json` from the output directory (compact — do
   not read parsed.json or any model TML). Each entry carries everything
   needed to decide: the original Tableau formula, why it wasn't
   deterministic, the auto-translation (if any), the definitions of sibling
   formulas it references (`referenced_formulas`), the worksheets that use it
   with their rows/cols shelves (`used_in_sheets` — critical for window
   calcs: it tells you what LOOKUP/RUNNING_* offsets traverse), and per-model
   available columns and parameters (`context`).

2. **Write** `decisions.json` — resolve ALL entries in one pass:

   ```json
   { "decisions": [
     { "caption": "<exact caption from decisions-needed.json>",
       "action": "use_expr",
       "name": "Clean Display Name",
       "expr": "sum ( [SESSIONS] ) / sum ( [PREV_SESSIONS] )",
       "column_type": "MEASURE",
       "reason": "LOOKUP(prev) equivalent via materialized PREV_* columns" },
     { "caption": "...", "action": "approve" },
     { "caption": "...", "action": "skip",
       "reason": "no model equivalent; propose Answer-level growth in Step 11.5" }
   ] }
   ```

   - `use_expr` — supply the ThoughtSpot expression (apply the formula rules
     below). `name` is optional and renames the formula (use it when the
     Tableau caption is raw formula text). `expr` may only reference names
     listed in `context` / `referenced_formulas` — unknown refs are rejected.
   - `approve` — accept the `auto_expr` of an `included_auto` entry as-is
     (stops it re-appearing in future question files).
   - `skip` — exclude the formula, with a reason; it lands in
     `skipped_by_decision[]` and the Step 12 migration report.

3. **Re-run T3** with the decisions:

   ```bash
   ts twb generate-tml \
     --input  .../parsed.json --translated .../translated.json \
     --connection "{connection_name}" -d "{db}" -s "{schema}" \
     --out .../{workbook_name} \
     --decisions .../{workbook_name}/decisions.json
   ```

   T3 applies each `use_expr` through the same schema path as deterministic
   formulas (id/`formula_id` matching, aggregation placement, dependency
   order) and validates every reference. Re-runs are idempotent — decisions
   are an input, never an edit.

4. **Check the new summary**: `invalid_decisions[]` must be empty (fix the
   listed refs in decisions.json and re-run); `omitted_formulas[]` should now
   contain only formulas you deliberately left undecided.

Keep `decisions.json` in the output directory — it is the audit trail of
every LLM formula decision and makes the whole run reproducible.

**Formula translation rules for `use_expr` decisions:** see "Formula
handling" below and `tableau-formula-translation.md` — the same rules that
govern deterministic translations apply to your expressions.

### 5a. Table TML — one per physical table (skip custom SQL relations)

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
- Use the `db`, `schema` values resolved from Step 4 (the connection is required, so these
  are always real).
- **`db_column_name` — use the column name from the TWB parse output** (`physical_columns[]`
  from Step 3, the `name` field). In most cases this matches the warehouse column exactly.
  When it doesn't (CSV/Excel loader normalized names like `Item Type` → `ITEM_TYPE`),
  validation (Step 6.5) catches it with `column not found in connection` — the column
  mismatch recovery in Step 6.5 then fetches the real warehouse columns for that table
  and fixes all mismatches in one pass. Do NOT fetch columns from the connection upfront
  just to populate `db_column_name` — that is the slow path Step 4 explicitly avoids.
- **Date stored as VARCHAR — flag it.** If the Tableau column is typed `date`/`datetime`
  but the warehouse column is **VARCHAR** (common when a CSV date loaded as text), binding
  it as VARCHAR loses all date capability (no buckets/trends/relative-date filters; Spotter
  won't read it as time). The TS column `data_type` must match the physical column, so you
  can't just declare `DATE`. Surface it and offer: **(a)** retype at the source (warehouse
  `ALTER`/reload to a real `DATE` — outside this skill; needs the user) then bind as `DATE`,
  or **(b)** keep VARCHAR and add a `to_date([col])` **derived formula column** for
  date analytics. Don't silently bind a date as a string.
- Use `INT64` for Tableau `integer` — **never `INT`**
- `db_column_properties` is **required** on every column
- No `guid` or `fqn` sections
- If validation (Step 6) returns `connection not found`, the name/case is wrong; if it
  returns `column not found in connection`, the physical table/column the connection sees
  doesn't match `db_table`/`db_column_name` — both are surfaced there, so a wrong binding
  fails loudly rather than silently.

Write each file to `/tmp/ts_tableau_mig/output/{workbook_name}/{TABLE_NAME}.table.tml`.

### 5b. Model TML — one per datasource (strict separation)

Generate one `.model.tml` per datasource the workbook **actually uses** — don't blindly
merge independent datasources, but also don't materialize an unused model for every
datasource. **Exception:** a genuine **cross-datasource blend** (a formula referencing
another datasource) is realized as **one** model by co-locating the link keys in a SQL view
and joining the other datasource in (see the join/blend rules in 5b and
`tableau-tml-rules.md` "One model per Tableau datasource").

The `model_tables[]` section references both regular tables (from Step 5a) and SQL
Views (from Step 5c) — both are referenced by `name` in the same way.

**Formula scoping — critical:** When populating `model.formulas[]`, use ONLY the
calculated fields from the specific datasource that this model derives from
(`parsed.datasources[N].calculated_fields`). **Never** search across datasources
by formula name. Multiple datasources can have formulas with the same caption
(e.g. "Graph Metric", "Membership Status") but completely different expressions.
Using the wrong datasource's formula body produces a model referencing columns
that don't exist in its tables. See `tableau-tml-rules.md` "Formula scoping"
for the full rule.

**Template:**

```yaml
model:
  name: "Datasource Display Name"
  properties:
    spotter_config:
      is_spotter_enabled: true  # set by Step 5.5 — Spotter is on by default
  model_tables:
  - name: TABLE_NAME
    joins:                      # only if this table has joins to others
    - with: OTHER_TABLE
      on: "[TABLE_NAME::JOIN_COL] = [OTHER_TABLE::JOIN_COL]"
      type: LEFT_OUTER          # INNER | LEFT_OUTER | RIGHT_OUTER | OUTER
      cardinality: ONE_TO_MANY
  - name: OTHER_TABLE
  parameters:                   # omit if no Tableau parameters to migrate
  - name: Currency
    data_type: CHAR              # CHAR for strings — not VARCHAR (parameters only)
    default_value: "USD"
    list_config:
      list_choice:
      - value: USD
      - value: CAD
      - value: GBP
  formulas:                     # omit section entirely if no translatable calculated fields
  - id: formula_Formula Name
    name: Formula Name
    expr: "ThoughtSpot expression"
  columns:
  - name: display_name
    column_id: TABLE_NAME::COLUMN_NAME
    properties:
      column_type: ATTRIBUTE    # or MEASURE
```

### Parameter migration (Tableau → ThoughtSpot `parameters[]`)

When the TWB has a `Parameters` datasource (Step 3), generate `parameters[]` entries
in the model TML. Omit `id` — ThoughtSpot assigns it on import.

**Type mapping:**

| Tableau `param-domain-type` | Tableau `datatype` | ThoughtSpot `data_type` | Config |
|---|---|---|---|
| `list` | `string` | `CHAR` | `list_config` with `list_choice[]` from `<member>` values — model parameters use `CHAR` for strings (not `VARCHAR`; `VARCHAR` causes error 14516) |
| `list` | `date` | `DATE` | `list_config` with date values (strip `#` delimiters) |
| `list` | `integer` | `INT64` | `list_config` |
| `list` | `real` | `DOUBLE` | `list_config` |
| `range` | `integer` | `INT64` | `range_config` with `range_min`, `range_max` |
| `range` | `real` | `DOUBLE` | `range_config` |
| `range` | `date` | `DATE` | Free-form (no `range_config` — ThoughtSpot range is numeric only) |
| `any` | any | mapped type | Free-form (no config) |
| `list` | `boolean` | `BOOL` | `list_config` with `'true'`/`'false'` values |

**Value cleanup:**
- Tableau wraps string member values in double quotes: `'"USD"'` → strip to `USD`
- Tableau date defaults use `#` delimiters: `#2026-05-10#` → strip to `2026-05-10`
  then format as `MM/DD/YYYY` (ThoughtSpot's date parameter format)

**SQL-lookup parameters:** If a parameter's list values come from a database query
(no static `<member>` elements in the TWB), query the warehouse at migration time to
populate `list_config.list_choice[]`:
1. Extract the SQL query or column reference from the Tableau parameter definition
2. Execute against the warehouse connection from Step 4
3. Use the distinct result values as `list_choice[]` entries
4. Log in `MIGRATION_LIMITATIONS.md` that these values are a point-in-time snapshot

If the selected connection cannot be queried for the values, omit the parameter and
log the omission with the original SQL query for manual recreation.

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

### Formula handling

For formulas where T2 returned `deterministic: true`, use the `translated` expression
directly — no further work needed. For `deterministic: false` formulas, apply the
judgment rules below. Use `tableau-formula-translation.md` as the reference.

- Convert Tableau join types: `full` → `OUTER`, `left` → `LEFT_OUTER`,
  `right` → `RIGHT_OUTER`, `inner` → `INNER`
- Write formulas in topological dependency order (Level 0 first — from T1's topo sort)
- Internal cross-references are already resolved by T1 (`[Calculation_\d+]` → display names)
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
- **Truly untranslatable formulas** (LOOKUP, INDEX, SIZE, PREVIOUS_VALUE, etc.): omit
  from `formulas[]` entirely, omit the corresponding `columns[]` entry, and log the
  omission for the Step 12 limitations report. Never generate a placeholder — incorrect
  syntax fails the entire model import.
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
- **Cross-datasource formulas (Tableau data blends).** A formula that references another
  datasource (`SUM([Sales]) - SUM([OtherDS].[Target])`) is a **blend**, not a single-model
  formula — models are per-datasource. To realize it, bring the other side into one relation
  via a **join** (which usually needs the materialization above). **Do NOT pre-aggregate the
  view to dodge fan-out** — ThoughtSpot's query generation **handles fan/chasm traps** (it
  aggregates each fact independently), so a per-group dimension table (e.g. targets by
  category/month) joined to per-line facts computes `sum(measure)` correctly without
  double-counting. Keep the view **line-level**; the view exists only to materialize/co-locate
  the join key, not to aggregate. The result is usually **one model**, not one-per-datasource.
  If the user doesn't want the extra object, omit the blend and flag it; never reference a
  second datasource from a model formula.
- No `fqn` in `model_tables`
- `obj_id` is optional on fresh import — omit it unless repointing an existing model

Write each file to `/tmp/ts_tableau_mig/output/{workbook_name}/{DatasourceName}.model.tml`.

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
- `connection.name` is **required** — use `{connection_name}` from Step 4
- `sql_query` contains the full SQL text from the Tableau `<relation>` element (decode
  HTML entities)
- `sql_output_column` must match a column name or alias from the SQL query output
- Map Tableau column datatypes to ThoughtSpot types using the same mapping as table TMLs
- No `db`, `schema`, `db_table`, or `db_column_properties` fields
- File extension: `*.sql_view.tml`

Write each file to `/tmp/ts_tableau_mig/output/{workbook_name}/{Name}.sql_view.tml`.

The model TML (Step 5b) references these SQL Views by name in `model_tables[]`, just
like regular tables.

### Self-check — TML generation (verify before post-processing)

Re-read every generated table, sql_view, and model TML and confirm ALL of these hold.
Fix any violation before moving to Step 5.5. Many of these are also caught by the T4
post-processor (Step 6) and T5 proofread (Step 6.5), but catching them here avoids
wasted fix cycles.

**Table TMLs:**
- [ ] Every column has `db_column_name` (even when it equals `name`)
- [ ] `connection.name` is present and exact (case-sensitive, not a GUID)
- [ ] Data types are `VARCHAR | INT64 | DOUBLE | FLOAT | BOOL | DATE | DATETIME` (never `INT`)
- [ ] Every column has `db_column_properties` with matching `data_type`

**Model TML formulas:**
- [ ] All conditionals use `if ( ) then ... else ...` (no `CASE`, no `WHEN`, no `END`)
- [ ] `else if` is two words (not `ELSEIF`)
- [ ] Spaces around all operators and parentheses — `if ( a = b ) then c else d`
- [ ] String literals use single quotes — `'value'` not `"value"`
- [ ] String concatenation uses `concat ( a , b )` — never `+` on strings
- [ ] `rank()` has two arguments — `rank ( measure , 'desc' )` (one-arg fails)
- [ ] No `cumulative_*` or `moving_*` in `formulas[]` (these are answer-level only)
- [ ] Column refs use `[Table::Column]`, formula refs use `[formula_Name]` (not `[Name]`)
- [ ] No `aggregation:` inside `formulas[]` entries (only in `columns[]`)
- [ ] No `fqn` in `model_tables[]`
- [ ] Every join has a non-empty `on` field with physical columns only (no formula refs)
- [ ] Join types are `INNER | LEFT_OUTER | RIGHT_OUTER | OUTER` (never `FULL_OUTER`)

---

## Step 5.5 — Spotter Enablement

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

## Step 6 — Post-process TMLs (`ts twb postprocess`)

Run the deterministic post-processor (T4) on the generated TMLs. This fixes names,
references, joins, and structure without changing the semantic content Claude authored.

```bash
ts twb postprocess "/tmp/ts_tableau_mig/output/{workbook_name}" "{twb_path}"
```

The tool performs, in order:
1. **Name mapping** — loads/creates `name_mapping.json` for consistent formula/param/column
   names across files and re-runs
2. **SQL registry** — qualifies `FROM`/`JOIN` references with full `db.schema.table` FQNs
3. **Table TML logical names** — fixes display names to match the mapping
4. **SQL View TML logical names** — same for sql_view objects
5. **Model joins** — patches join `on` clauses and `with` references
6. **Model column names** — aligns column display names with the mapping
7. **Parameter injection** — ensures model parameters are correctly wired
8. **Formula reference translation** — fixes `[formula_*]` cross-refs in model formulas
9. **Model table references** — fixes `model_tables[].name` to match actual table names
10. **Formula column refs** — strips table prefixes where needed
11. **Object ID injection** — assigns `obj_id` values for cross-referencing
12. **Deduplication** — removes duplicate formula IDs and empty model tables
13. **Cross-reference check** — validates that every formula, column, and join ref resolves

If the tool reports cross-reference errors, fix the affected TML file and re-run.

---

## Step 6.5 — Validate (`ts twb validate`)

Run the validation harness (T5). It performs a **local proofread** first, then (if a
profile is provided) a **VALIDATE_ONLY** dry-run against ThoughtSpot.

**HARD RULE — no imports until Step 7.** Steps 1–6.7 are read-only against the cluster.
The ONLY tool that touches the cluster in this phase is `ts twb validate`, which uses
`VALIDATE_ONLY` (no objects created). **Never call `ts tml import` to debug a validation
error** — even if the validator returns a generic message (e.g. "Schema validation failed"
with no detail). Instead: strip the TML to a minimal version, re-validate, and add parts
back incrementally — all via `ts twb validate`, never `ts tml import`. The first
actual `ts tml import` happens in **Step 7**, after the user explicitly confirms.

```bash
ts twb validate "/tmp/ts_tableau_mig/output/{workbook_name}" --profile {profile_name}
```

The tool returns structured JSON:

```json
{
  "status": "VALID | INVALID | PROOFREAD_FAIL | EXHAUSTED",
  "attempt": 3,
  "exhausted": false,
  "fixable": [{"file": "...", "message": "...", "classification": "fixable"}],
  "locked": [{"file": "...", "message": "...", "classification": "locked"}],
  "warnings": [{"file": "...", "message": "...", "classification": "warning"}]
}
```

### Error classification (deterministic — the tool decides, not Claude)

| Class | Examples | Action |
|---|---|---|
| **fixable** | missing `db_column_name`, formula_id mismatch, bad ref, connection not found, column not found | Claude fixes the TML file → re-run Step 6 (postprocess) → re-validate |
| **locked** | error codes 14537/14540/14516, LOOKUP/QUALIFY/INDEX/SIZE/PREVIOUS_VALUE patterns | **Never fix** — preserve the file as-is, document in limitations report |
| **warning** | "id null not found" (benign for new tables) | Ignore — treated as pass |

### The validate loop

```
validate → INVALID + fixable errors? → Claude fixes ONE file → postprocess → validate
                                        (loop, up to soft cap ~10)
         → VALID?                    → proceed to Step 6.7
         → LOCKED errors only?       → preserve + document, proceed to Step 6.7
         → EXHAUSTED (hard cap ~15)? → STOP, report to user (fail-safe)
```

**On each fixable error:**
1. Read the error message and the affected file (the tool's `file` field identifies it)
2. Apply the fix — consult `tableau-tml-rules.md` error table.
   **Exception — errors in a formula that came from a decision:** fix the
   entry in `decisions.json` and re-run `ts twb generate-tml --decisions`
   (Step 5.1) instead of editing the model TML; hand-edits are lost on the
   next T3 run.
3. Re-run `ts twb postprocess` (Step 6) to re-normalize
4. Re-run `ts twb validate` (Step 6.5)

### Column mismatch recovery

When validation returns `column not found in connection` for a table, do NOT fix just
the one failing column and re-validate. Instead, fetch **all** columns for that table
in one call and diff them against the entire TML:

```bash
source ~/.zshenv && ts connections get {connection_id} \
  --database {db} --schema {schema} --table {db_table} \
  --profile {profile_name}
```

This returns the full column list with names and data types. Then:

1. **Collect** every `db_column_name` in that table's TML
2. **Diff** each against the fetched warehouse column list
3. For each TML column NOT found in the warehouse:
   - Find the closest match (case-insensitive, then fuzzy — e.g. `ITEM_TYPE` →
     `ITEM_TYPE_CD`) from the warehouse list
   - Fix the `db_column_name` (and `data_type` / `db_column_properties.data_type` if
     the warehouse type differs)
4. Fix **all** mismatches in that table's TML in one edit — not one per validate cycle

This turns what would be N validate cycles (one per bad column) into one fetch + one
bulk fix. Only tables with at least one `column not found` error trigger the fetch —
tables that passed validation are never fetched.

If the same validate round flags `column not found` on multiple tables, fetch and fix
all of them before re-entering the validate loop.

**On LOCKED errors:** do NOT attempt to fix. The tool has classified these as unfixable
(SQL execution failures, unsupported functions, cascade errors). Preserve the TML as-is
and document each in the Step 12 limitations report.

**On generic errors (e.g. "Schema validation failed" with no detail):** the cluster gives
no actionable message. Debug by **isolating** — write a minimal model TML (one table, two
columns, no formulas/parameters) to a temp file, validate that, then add parts back one
at a time (add the join, re-validate; add parameters, re-validate; add formulas,
re-validate). All of this uses `ts twb validate` — never `ts tml import`. Common
causes of generic 13122: (a) unjoined tables in the model (ThoughtSpot requires all
`model_tables` to be connected via joins), (b) `data_type: VARCHAR` on a parameter (must
be `CHAR`), (c) `fqn` referencing a non-existent GUID, (d) ambiguous table names with no
`fqn` disambiguation.

**On EXHAUSTED:** the tool's hard cap (~15 attempts) has been reached. Stop and report:
- Errors that persist after all retries
- Which fix was attempted for each
- Ask the user whether to proceed with import anyway, make manual corrections, or abandon

### Proofread checks (run locally, no API call needed)

The tool catches these common mistakes before hitting the cluster:
- `FULL_OUTER` join type (must be `OUTER`)
- `INT` data type (must be `INT64`)
- `CASE WHEN` in formula expressions (must be if/then/else)
- `fqn:` in `model_tables[]` entries
- `cumulative_`/`moving_` in model-level formulas (answer-level only)
- Missing `db_column_properties` on table columns

---

## Step 6.7 — Coverage Audit (`ts twb verify`)

After validation passes (or only LOCKED errors remain), run the coverage/fidelity audit
(T7) to catch **silent drops** — things the validate gate can't see:

```bash
ts twb verify "{twb_path}" "/tmp/ts_tableau_mig/output/{workbook_name}"
```

The tool parses both the original TWB and the generated TMLs, then diffs them:
- Every table in the TWB accounted for in a table/sql_view TML?
- Every join in the TWB present in the model TML?
- Every formula in the TWB either translated or documented as untranslatable?
- Every parameter migrated?
- Tokenized formula comparison (TWB expression vs TS expression) for fidelity

The output is a coverage report. Review any **drops** (TWB elements with no TML
counterpart) and **mismatches** (formula tokens that diverge unexpectedly). Fix any
genuine gaps before proceeding to Step 7.

Silent drops are the #1 source of "it imported fine but something's missing" — this step
catches them before the human review checkpoint.

---

## Step 7 — Review Checkpoint & Import

**This is the first step that writes to the cluster.** Nothing before this point
(Steps 1–6.7) should have called `ts tml import`. If you reach this step and objects
already exist on the cluster from earlier steps, something went wrong — surface it to the
user before proceeding.

Before importing, show the user a review summary — the same convention the
`ts-convert-from-snowflake-sv` and `ts-convert-from-databricks-mv` skills use. The user
should see exactly how every calculated field was translated, and what (if anything)
will **not** migrate, *before* committing — not discover omissions only in the Step 12
report afterward. Reuse the formula tier classification from Step 3.5/Step 5. The review
is now informed by the T5 validation results (any LOCKED errors) and the T7 coverage
audit (any silent drops).

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

Will NOT migrate ({K}):
  - {name}: {reason}
  # if none: "Nothing omitted — full coverage."

Dashboards: {N}  (liveboard migration offered after import)

Proceed?
  yes   — import the table + model TMLs
  no    — cancel
  file  — write the TMLs to /tmp/ts_tableau_mig/output/{workbook_name}/ without importing
```

Tiers are from Step 3.5 (T2): Native, LOD, Cumulative, Moving, Pass-through, Parameter ref,
Untranslatable. Also include any LOCKED errors from T5 validation (Step 6.5) and any
coverage gaps from T7 verification (Step 6.7). Show `⚠ … OMITTED` for every
untranslatable formula (and its dropped `columns[]` entry) and `⚙ … pass-through` for
every formula needing SQL Passthrough — so the un-migratable and caveated items are
flagged here, up front, for the user to weigh.

Wait for confirmation. **no** cancels. **file** writes the TMLs and skips to Step 12
(report only, no import). **yes** imports:

On confirmation, build the JSON payload in dependency order (tables → sql_views →
models → cohorts). Pass `--create-new` because these are brand-new objects with no
GUID — without it, the default `--no-create-new` only updates existing objects. (Do
**not** pass `--create-new` if you are re-importing TML that already carries a GUID —
that silently creates a duplicate.)

```bash
cd /tmp/ts_tableau_mig/output/{workbook_name}
python3 - > /tmp/ts_tableau_mig/{workbook_name}_payload.json <<'PY'
import json, glob
order = sorted(glob.glob("*.table.tml")) + sorted(glob.glob("*.sql_view.tml")) + sorted(glob.glob("*.model.tml")) + sorted(glob.glob("*.cohort.tml"))
print(json.dumps([open(f).read() for f in order]))
PY
cat /tmp/ts_tableau_mig/{workbook_name}_payload.json \
  | ts tml import --policy ALL_OR_NONE --create-new --profile {profile_name}
```

Parse the response. Extract the GUID for each imported object. On failure, show the
error and stop.

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

---

## Step 7.5 — Confirm the Model (before any liveboards)

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

If the T1 parsed JSON (Step 3) contains zero dashboards, skip to **Step 11.5** (a
model-only workbook still benefits from coverage answers), then Step 12.

Otherwise, present the decision:

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

### If Y — load Stage 2

The dashboard→liveboard detail (Steps 9–11: layout parsing, liveboard TML generation,
styling, import) lives in **[references/stage2-liveboards.md](references/stage2-liveboards.md)** —
a separate file so a model-only run never loads it. **Read that file now and follow Steps
9–11 there**, then **return here for Step 11.5**. When you come back, you'll have the
liveboard imported and its tiles known (needed to compute "uncovered" formulas below).

---

## Step 11.5 — Formula Coverage Answers

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
with a caveat — approximation, N/A on current data, placeholder), **⊘ Not migrated** (omitted;
give the reason). Every calculated field from Step 3 must appear in exactly one row.

**Partial / not migrated** — repeat the ◑/⊘ rows with the reason and what the user can do.
```

A console one-liner (`Tables: N · Models: N · Liveboards: N`) is fine as a closing line, but
the markdown report above is the deliverable. Keep it consistent with each liveboard's
in-product **Migration Summary** tab (Step 10g) and any `MIGRATION_LIMITATIONS.md`.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
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
