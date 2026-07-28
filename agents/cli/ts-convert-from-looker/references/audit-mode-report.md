# Audit Mode Report Format

Reference detail for **Audit Mode (A)**: the console coverage-report template, the
CLEAN/CAVEAT/BLOCKED classification rules, and the full `{project_name}_migration_report.md`
document structure. The step's spine (parse without ThoughtSpot auth, classify every field
and tile into a zone, write both the console output and the .md file) stays in `SKILL.md` —
this file is what the spine links out to for the exact template text and classification
tables.

---

## Console coverage report template

```
=== LookML Audit Report ===

Explores found: {n}
Views found:    {n}
Total fields:   {n}

--- Translation coverage ---
  Directly translatable:   {n} ({pct}%)
    - sum, count, average, max, min dimensions
  Formula translation:     {n} ({pct}%)
    - count_distinct → unique count()
    - type: number with SQL → inline + translate
    - filtered measures → count_if / sum_if
  Approximate / review:    {n} ({pct}%)
    - complex SQL with no direct TS equivalent
    - tier dimensions
    - running_total / percent_of_total
  Unsupported / omit:      {n} ({pct}%)
    - type: location
    - type: list
    - derived_table PDT sources (requires SQL review)

--- Per-explore breakdown ---
  {explore_name}:
    Dimensions: {n}  Measures: {n}  Joins: {n}
    Blockers: {list or "none"}

--- Field-level detail ---
  {view.field | looker_type | zone | notes}
===========================
```

---

## `{project_name}_migration_report.md` structure

In addition to the console output above, write a self-explanatory migration
readiness report as `{project_name}_migration_report.md` in the LookML project
directory. Plain markdown — no external library needed.

**Files parsed for the report** (broader than console output — includes dashboards):
- All `*.view.lkml` — dimensions, measures, derived tables
- All `*.model.lkml` — explores, joins, connection
- All `*.dashboard.lookml` — tiles, chart types, dashboard filters (if present)

---

### Classification rules

Assign every field and every dashboard tile to exactly one zone:

**CLEAN** — no post-import action needed:
- Dimensions: `string`, `number`, `yesno`, `date`, `time`
- Measures: `sum`, `count`, `count_distinct`, `average`, `max`, `min`
- Filtered measures (`filters:` on measures)
- Derived measures (`type: number`) — only when all `${}` refs resolve and SQL translates cleanly
- Standard joins (`left_outer`, `inner`, `full_outer` with `sql_on:`)
- PDT / derived tables (`derived_table: { sql: }`)
- Dashboard tiles: `single_value`, `looker_column`, `looker_bar`, `looker_line`,
  `looker_area`, `looker_pie`, `looker_scatter`, `table`, `looker_grid`
- Dashboard filters with `listen:`

**CAVEAT** — migrates but verify after import:
- `value_format_name:` on any field
- `map_layer_name:` on geo dimensions
- `type: zipcode`
- `type: tier` dimension
- `type: running_total`
- `type: percent_of_total`
- `type: number` derived measure with complex SQL
- `looker_donut_multiples` tile (split into N PIE tiles)
- PDT SQL adapted from one warehouse dialect to another
- `extends:` view inheritance (flattened at parse time)

**BLOCKED** — will not appear in ThoughtSpot after migration:
- `type: location`
- `type: list`
- `sql_always_where:` ← **go-live blocker — flag prominently**
- `all_access_grants:` / `required_access_grants:`
- `derived_table: { explore_source: }` (native derived table)
- Liquid/Jinja templating (`{{ }}`) in SQL
- `looker_map` / `looker_geo_choropleth` tile
- `looker_funnel` tile
- Dashboard `link:` (cross-dashboard navigation)
- `sql_always_having:`

---

### .md document structure

Build the document in this order:

**Title (H1):** "Looker → ThoughtSpot Migration Readiness Report"
**Subtitle (italic line under the title):** "Project: {project_name}   |   Generated: {date}"

---

**1. At a Glance** (H2)

Opening paragraph (plain English, no jargon):
> "This report summarises what can be moved from Looker to ThoughtSpot
> automatically, what will need a quick check after the move, and what cannot
> be moved and will need a decision. Use the three sections below to plan
> your next steps."

2-column summary table:

| | |
|---|---|
| Project | {project_name} |
| Data models | {n} explores → {n} ThoughtSpot models |
| Physical tables | {n} |
| Derived tables (SQL views) | {n} |
| Total fields | {n} ({dimensions} dimensions, {measures} measures) |
| Dashboard tiles | {n} across {n} dashboards |
| **Migrates cleanly** | **{n} items ({pct}%) — no action needed** |
| **Migrates with caveats** | **{n} items ({pct}%) — verify after import** |
| **Cannot migrate** | **{n} items ({pct}%) — manual decision required** |
| Estimated manual effort | {effort} |

Effort estimate: CAVEAT items → 5 min each; BLOCKED items → 30 min each. Round to nearest 30 min.

---

**2. ✅ Section 1 — Migrates Cleanly** (H2)

Explanation paragraph:
> "The items in this section will be fully converted and imported into
> ThoughtSpot automatically. No review or manual steps are needed. Once the
> migration tool runs, these will be available in ThoughtSpot exactly as
> they appear in Looker."

Table 1 — Data layer:

| Item | Count | Detail |
|---|---|---|
| Physical tables | {n} | {comma-separated table names} |
| Derived tables (SQL Views) | {n} | {names} or "None" |
| Joins | {n} | All join types and relationships mapped |
| Explores → ThoughtSpot models | {n} | {explore_names} |

Table 2 — Fields:

| Field category | Count | Notes |
|---|---|---|
| Text / string dimensions | {n} | |
| Number dimensions (IDs, keys) | {n} | |
| Date / timestamp dimensions | {n} | |
| Boolean (yes/no) dimensions | {n} | |
| SUM measures | {n} | |
| COUNT measures | {n} | |
| COUNT DISTINCT measures | {n} | Converted to unique count formula |
| AVERAGE / MAX / MIN measures | {n} | |
| Filtered measures | {n} | Converted to count_if / sum_if |
| Derived (calculated) measures | {n} | SQL translated to ThoughtSpot formula |

Table 3 — Dashboard tiles (only if dashboards found):

| Dashboard | Tile | Chart type | Status |
|---|---|---|---|
| {dashboard_name} | {tile_title} | {type} | Ready |

**"What to do next" (bold):**
> Nothing. Run the migration tool (Migrate mode) and all items in this section
> will import automatically.

---

**3. ⚠️ Section 2 — Migrates But Needs Checking** (H2)

Explanation paragraph:
> "The items below will be imported into ThoughtSpot, but something about them
> needs to be verified or adjusted after the import. The data will be there —
> but the display, formatting, or chart layout may not look exactly right until
> the check is done. Each row tells you what to look for and where to find it
> in ThoughtSpot."

Table — one row per caveat type found; omit rows with count = 0:

| # | What | Count | What to check after import | Where in ThoughtSpot |
|---|---|---|---|---|
| 1 | Number / currency formatting | {n} fields | Numbers may display without currency symbols or decimal rounding (e.g. 1234.56 instead of $1,235) | Worksheet → column settings → Format |
| 2 | Geographic columns | {n} fields ({names}) | State / Country columns need their geographic role set for map searches to work | Worksheet → column settings → Geo |
| 3 | Zip code columns | {n} fields | Zip codes may lose leading zeros (e.g. 01234 displays as 1234) | Run a search on the column and verify; set Geo type to Zip |
| 4 | Multi-donut chart split to PIE tiles | {n} tiles ({names}) | One Looker multi-donut was split into {n} separate pie charts — verify each shows correct segments and filter | Open each pie tile in the liveboard |
| 5 | Tier / bucket dimensions | {n} fields ({names}) | Bucket ranges translated to if/then/else — verify the boundaries match the original | Run a search on the field; compare values to Looker |
| 6 | Running total measures | {n} fields ({names}) | Cumulative sum needs a sort column — verify sort direction is correct | Open an answer using this field and check sort order |
| 7 | Complex calculated measures | {n} fields ({names}) | SQL inlined and translated — spot-check output values against Looker | Side-by-side comparison of a known total recommended |
| 8 | Derived table SQL adapted | {n} views ({names}) | SQL rewritten for the ThoughtSpot warehouse — verify row counts match | Run a search on the SQL view; compare counts to source |

If no CAVEAT items found: write single line "No items in this category. ✅"

**"What to do next" (bold):**
> Import the TML files first — Section 1 items come in automatically. Then go
> through each row above in the ThoughtSpot UI. Most checks take 5–10 minutes.
> Estimated time for this section: {effort_section2}.

---

**4. ❌ Section 3 — Cannot Be Migrated** (H2)

Explanation paragraph:
> "The items below will not appear in ThoughtSpot after the migration. The
> tool skips them because there is no equivalent feature. For each one,
> decide whether to rebuild it manually, accept it as a known gap, or leave
> it out of this migration phase."

Table — one row per blocker type found; omit rows with count = 0;
flag `sql_always_where:` rows with "⚠️ Go-live blocker" in the Recommended action column:

| # | What | Count | Why it cannot migrate | Recommended action |
|---|---|---|---|---|
| 1 | Row-level security rules | {n} explores | Looker's always-on row filters have no ThoughtSpot TML equivalent | ⚠️ Go-live blocker — configure Row Level Security in ThoughtSpot Admin before giving users access |
| 2 | Column-level access grants | {n} fields | Looker permission groups have no TML equivalent | Set column visibility per group manually in ThoughtSpot after import |
| 3 | Spatial / map dimensions | {n} fields ({names}) | No lat/lon spatial column type in ThoughtSpot | Keep as plain number columns; use geo address config if map display is needed |
| 4 | Map chart tiles | {n} tiles ({names}) | No map chart type in ThoughtSpot Liveboard TML | Rebuild as a table or bar chart; or use ThoughtSpot's built-in geo search |
| 5 | Native derived tables | {n} views ({names}) | Defined using a Looker explore, not raw SQL | Rewrite as raw SQL in Looker first, then re-run the audit |
| 6 | Dynamic SQL (Liquid/Jinja) | {n} fields ({names}) | Template expressions cannot be resolved without Looker | Provide the resolved literal values (e.g. actual schema name) and re-run |
| 7 | Multi-value list dimensions | {n} fields ({names}) | No multi-value column type in ThoughtSpot | Use a text concatenation formula post-migration if needed |
| 8 | Funnel chart tiles | {n} tiles ({names}) | No funnel chart type in ThoughtSpot Liveboard TML | Replaced with a table placeholder — rebuild as a funnel in ThoughtSpot UI |
| 9 | Cross-dashboard navigation | {n} links | ThoughtSpot liveboards have no tile-to-liveboard links in TML | Add navigation links manually after import |

If no BLOCKED items found: write single line "No items in this category. ✅"

**"What to do next" (bold):**
> For each row above, assign one of:
> • Rebuild — recreate the feature manually in ThoughtSpot after migration
> • Accept gap — document and inform end users what will not be available
> • Descope — exclude from this phase and revisit later
> If row-level security is listed above, resolve it before go-live — users
> may otherwise see data they should not have access to.

---

**5. Appendix — Full Field Inventory** (H2)

Explanation: "Complete list of all fields in this project and their migration status."

Table:

| View / Table | Field name | Looker type | Zone | Notes |
|---|---|---|---|---|
| {view_name} | {field_name} | {type} | ✅ Clean / ⚠️ Caveat / ❌ Blocked | {reason if caveat or blocked} |

---

**6. Technical Summary** (H2 — last section in the doc, for developers and technical reviewers)

Explanation line: "Raw output from the migration analysis tool — field-by-field breakdown for technical review."

Render the full console output verbatim inside a fenced code block — this is the same
`=== LookML Audit Report ===` ... `===========================` block shown under
**Audit Mode (A)** above, generated once and written to both the terminal and this
section of the doc. No duplication of logic needed.

---

#### Console output (print to terminal after the .md file is written)

Print the same block (`=== LookML Audit Report ===` through `===========================`,
shown under **Audit Mode (A)** above) to the terminal, then append this trailing footer
and the file path line:

```
  ✅  Migrates cleanly:      {n} items ({pct}%)
  ⚠️   Needs checking:        {n} items ({pct}%)
  ❌  Cannot migrate:         {n} items ({pct}%)
  Estimated manual effort:  {effort}

Migration report written → {path}/{project_name}_migration_report.md
```
