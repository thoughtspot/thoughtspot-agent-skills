# Migration Report Format (Step 11)

Reference detail for **Step 11 — Migration summary report**: the console summary block
template and the full `{project_name}_migration_summary.md` structure (Migrate mode). The
step's spine (write the console block, then the .md file, to `{reports_dir}`) stays in
`SKILL.md` — this file is what the spine links out to for the exact template text.

---

## Console summary block

```
=== LookML → ThoughtSpot Migration Summary ===

Source project: {project directory}
ThoughtSpot profile: {profile name}
Explore(s) migrated: {list}

--- Tables ---
  Registered:  {count}
  Skipped:     {count} (PDT / derived — listed below)

--- Model(s) ---
  Imported:    {count}
  Formulas:    {count total} ({count} translated, {count} approximate, {count} omitted)

--- Liveboards ---
  Imported:    {count}
  Tiles:       {count total} ({count} chart, {count} KPI, {count} table, {count} placeholder)

--- Untranslatable / Omitted ---
  {List each with: field name, LookML type, reason, recommendation}

--- Approximations (review recommended) ---
  {List each with: field name, original SQL, ThoughtSpot formula, what may differ}

--- Output files ---
  Zip (UI import):   {explore_name}_tml.zip          ← upload via Data → TML Import in ThoughtSpot UI
  TML files:         {output_dir}/*.table.tml, {output_dir}/*.model.tml   (staging — /tmp, not persisted)
  Reports folder:    {reports_dir}                    ← one level above the LookML source, persists
    Gaps file:          {explore_name}_migration_gaps.md
    Migration summary:  {project_name}_migration_summary.md  (written below)
    Migration details:  migration_details.md  (only if dashboards were converted — Step 10h; includes the Liveboard URL once)

--- Next steps ---
1. Open ThoughtSpot and search the model to confirm formulas return expected values.
2. Review any items in the "Approximations" list above.
3. For omitted geospatial or list fields, plan a manual workaround.

Migration summary written → {reports_dir}/{project_name}_migration_summary.md
==============================================
```

---

## `{project_name}_migration_summary.md` structure (Migrate Mode)

After printing the console summary above, write a self-contained post-migration
summary report as `{project_name}_migration_summary.md` in `{reports_dir}`
(defined in Step 7.5 — one level above the LookML source, not the /tmp TML staging
dir). Plain markdown — no external library needed.

**Title (H1):** "Looker → ThoughtSpot Migration Summary"
**Subtitle (italic line under the title):** "Project: {project_name}   |   Migrated: {date}"

---

**1. Migration Overview** (H2)

Opening paragraph (plain English):
> "This report documents what was migrated from Looker to ThoughtSpot, what needs
> to be verified after import, and what could not be migrated automatically. Use
> the sections below to complete your go-live checklist."

2-column summary table:

| | |
|---|---|
| Project | {project_name} |
| ThoughtSpot profile | {profile_name} |
| Explore(s) migrated | {list} |
| Tables registered | {n} |
| Tables skipped (PDT/derived) | {n} |
| Models imported | {n} |
| Liveboards imported | {n} |
| Formulas translated | {n} ({n} exact, {n} approximate, {n} omitted) |
| **Items ready to use** | **{n} — no action needed** |
| **Items to verify** | **{n} — spot-check recommended** |
| **Items not migrated** | **{n} — manual decision required** |

---

**2. ✅ Migrated Objects** (H2)

Table — one row per imported object:

| Object type | Name | GUID | Notes |
|---|---|---|---|
| Table | {table_name} | {guid} | |
| Model | {model_name} | {guid} | {explore_name} explore |
| Liveboard | {liveboard_name} | {guid} | {n} tiles |

For skipped tables (PDT / native derived table), add a row with GUID = "— skipped" and the reason.

---

**3. ⚠️ Approximations — Verify After Import** (H2)

Explanation paragraph:
> "The items below were imported but may not behave identically to Looker.
> Each row tells you what to check and where to find it in ThoughtSpot."

Table — one row per approximation; omit if none:

| # | Field | Original SQL / type | ThoughtSpot formula | What may differ | Where to check |
|---|---|---|---|---|---|
| {n} | {view.field} | {original} | {ts_formula} | {caveat} | Worksheet → search on field |

If no approximations: write single line "No approximations recorded. ✅"

---

**4. ❌ Fields Not Migrated** (H2)

Explanation paragraph:
> "The items below were skipped because ThoughtSpot has no equivalent feature.
> For each one, decide whether to rebuild manually, accept as a known gap, or defer."

Table — one row per omitted field; omit section if none:

| # | Field | LookML type | Reason | Recommended action |
|---|---|---|---|---|
| {n} | {view.field} | {type} | {reason} | {action} |

Flag any `sql_always_where:` rows with "⚠️ Go-live blocker" in the Recommended action column.

If no omitted fields: write single line "No fields were omitted. ✅"

---

**5. Gaps Checklist** (H2)

Explanation line: "Items from the migration gaps file that require manual follow-up."

Render the full content of `{reports_dir}/{explore_name}_migration_gaps.md` verbatim
inside a fenced code block.

If the gaps file is empty or does not exist: write "No open gaps recorded. ✅"

---

**6. Next Steps** (H2)

Numbered list:
1. Open ThoughtSpot and search each migrated model to confirm formulas return expected values.
2. Work through the "Approximations" table above — most checks take 5–10 minutes each.
3. For each omitted field, assign: Rebuild / Accept gap / Descope.
4. If row-level security was omitted (sql_always_where), configure ThoughtSpot RLS before go-live.
5. Share this report with your ThoughtSpot administrator to track completion.

---

#### Console output addition

Append this line to the existing console summary block after printing:

```
Migration summary written → {reports_dir}/{project_name}_migration_summary.md
```
