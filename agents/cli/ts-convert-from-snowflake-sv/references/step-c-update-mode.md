This file serves **Mode C: Update an Existing ThoughtSpot Model** (Steps C4–C6) in
`agents/cli/ts-convert-from-snowflake-sv/SKILL.md` — the diff-review console templates,
the change-type → action mapping table, and the post-import coaching handoff message.

---

## Step C4 templates

**Summary**

```
=== Change set for "{model_name}" ===

  ✚ New columns:              {N}   (will be added with generated synonyms + descriptions)
  ✖ Removed columns:          {M}   (flagged only — see note below)
  ✏ Modified descriptions:    {P}   (UPDATE / KEEP per column — default: KEEP)
  ✏ Modified synonyms:        {Q}   (MERGE / UPDATE / KEEP per column — default: MERGE)
  ~ Modified expressions:     {R}   (YES / SKIP per column — confirm before re-translating)
  ~ Join changes:             {S}   (flagged for review)
  = Unchanged columns:        {T}   (no action)
```

**Modified descriptions** — per-column table, default `KEEP`:

| Column | Current (TS Model) | New (from SV) | Action |
|---|---|---|---|
| Amount | Total sales amount in USD | Total revenue in local currency | KEEP |

**Modified synonyms** — per-column table, default `MERGE`:

| Column | Current synonyms | Added by SV | Removed by SV | Action |
|---|---|---|---|---|
| Product Category | category, product group | dept | product group | MERGE |

Options:
- `MERGE` *(default)* — add new SV synonyms, keep existing; never remove coached synonyms
- `UPDATE` — replace existing synonyms entirely with the SV set
- `KEEP` — ignore the SV change; leave existing synonyms untouched

**Modified expressions** — show old and new formula side-by-side. Require `YES / SKIP`
per column — never bulk-apply expression changes.

**Removed columns** — informational list only, no action column:

```
⚠ The following columns exist in the ThoughtSpot Model but are no longer in the SV.
  They are NOT removed automatically — removal may break dependent Answers and Liveboards.
  To remove them safely: run /ts-dependency-manager first, then edit the Model TML manually.
```

---

## Step C5 change-action mapping

| Change type | Action |
|---|---|
| New column | Generate using Step 8 + Step 9 logic — same as create mode |
| Modified description, `UPDATE` | Write to `column.description` |
| Modified description, `KEEP` | Leave untouched |
| Modified synonyms, `MERGE` | Union: add new SV synonyms, keep all existing ones |
| Modified synonyms, `UPDATE` | Replace `properties.synonyms[]` with SV set |
| Modified synonyms, `KEEP` | Leave untouched |
| Modified expression, `YES` | Re-translate using Step 9 logic; update `formulas[].expr` |
| Modified expression, `SKIP` | Leave untouched |
| `ai_context` on any column | **Never touch** |
| Data Model Instructions | **Never touch** |
| Removed columns | **Never touch** |

---

## Step C6 handoff message

```
✓ Model "{model_name}" updated.

⚠ Coaching surfaces that may need review:

  Column AI Context
    {N_new} new columns added — no ai_context yet
    {M_updated} existing columns had descriptions or synonyms changed
    → Run /ts-object-model-coach → surface 1 to review and update ai_context

  Data Model Instructions
    Schema changes (new columns, expression changes, join changes) may affect
    Spotter's default behaviours — particularly time_defaults and aggregation_defaults.
    → Run /ts-object-model-coach → surface 5 to review Instructions

  Removed columns flagged above
    If you intend to remove any of the flagged columns, run /ts-dependency-manager
    first to assess downstream impact before editing the Model TML manually.
```
