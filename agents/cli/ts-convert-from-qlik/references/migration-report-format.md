# Migration report format (template)

Copy this skeleton, fill every `<…>` from the actual migration, and hand the user
the result as `migration_report.md`. Keep the section order. Use the status
vocabulary exactly: **Migrated · Approximated · NEEDS REVIEW · Skipped**. Never
silently drop a source object — every one appears in a table with a status.

---

# Qlik → ThoughtSpot migration report

**Source:** <app> — *<sheet/dashboard>* &nbsp;&nbsp; **Generated:** <YYYY-MM-DD>
**Target:** <host> / connection `<connection>` / `<db>.<schema>`
**Provenance:** data model = **SOURCE** (read from the warehouse) · charts = **INFERRED** from the dashboard PDF (verify)

## Executive summary

- **Migration complexity:** <Low | Medium | High>
- **Automation %:** <n>% &nbsp;|&nbsp; **Manual %:** <n>%
- **Estimated effort:** <range> engineer-day(s)
- **Risk score:** <Low | Medium | High> — <one-line reason naming the biggest open items>

## Inventory

- **Tables:** <n> &nbsp;|&nbsp; **Columns:** <n>
- **Relationships:** <n> &nbsp;|&nbsp; **Measures:** <n>
- **Sheets:** <n> &nbsp;|&nbsp; **Visuals:** <n>

## Modernization

**Dashboards eliminated:** <… or "none">
**Dashboards merged:** <… or "none">
**Search opportunities:** <single-value cards / ad-hoc questions re-askable via Search>
**Spotter opportunities:** <"explain X by Y/Z" breakdowns → Spotter>
**Semantic improvements:**
- <friendly renames, reusable measures, join cardinality, filters/parameters carried over, note tiles, …>

## Summary by object type

| Object type | In Qlik | Migrated | Approximated | Needs review | Skipped |
|---|---|---|---|---|---|
| Tables | | | | | |
| Relationships | | | | | |
| Measures | | | | | |
| Visuals | | | | | |
| Sheets | | | | | |

## Data model

### Tables
| Table | Status | Note |
|---|---|---|
| <name> | <status> | <note> |

### Relationships → joins
| Relationship | Status | Note |
|---|---|---|
| <FACT[key] → DIM> | <status> | <type, cardinality, caveats> |

### Measures → formulas
| Measure | Complexity | Qlik expression | ThoughtSpot formula | Confidence | Status | Note |
|---|---|---|---|---|---|---|
| <name> | <Simple/Moderate/Complex> | <Qlik expr or "(not recoverable from PDF)"> | <TS formula / output column> | <0–100> | <status> | <note> |

## Report / visuals → answers & liveboards

### Sheet → liveboard
| Sheet | Visual | ThoughtSpot chart | Status | Note |
|---|---|---|---|---|
| <sheet> | <visual / note tile / filter> | <KPI/LINE/COLUMN/BAR/PIE/PIVOT_TABLE/GEO_BUBBLE/NOTE_TILE/…> | <status> | <note> |

### Sheet → liveboard decision
| Sheet | Decision | Liveboard | Status |
|---|---|---|---|
| <sheet> | <Keep / Merge / Eliminate> | <liveboard name or "(eliminated)"> | <status> |

## Manual review (do these in ThoughtSpot)

- **<item> (<NEEDS REVIEW | Approximated>)** — <what the human must confirm and why>

## Verification checklist

- [ ] Pick one known total in Qlik and confirm the SAME number in ThoughtSpot (validates tables + joins + formula end to end). *Tick + cite the value if you verified it live.*
- [ ] Spot-check 2–3 more measures against their Qlik values.
- [ ] Confirm each retained sheet's content is present on its liveboard.
- [ ] Confirm filters / parameters carried over.

## ThoughtSpot Modernization Scorecard

| Category | Score | Recommendation |
|---|---|---|
| Semantic Model | <n>/100 | <…> |
| Search Readiness | <n>/100 | <…> |
| Spotter Readiness | <n>/100 | <…> |
| Liveboards | <n>/100 | <…> |
| AI Readiness | <n>/100 | <…> |
