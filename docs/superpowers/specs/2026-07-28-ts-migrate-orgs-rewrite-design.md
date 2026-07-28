# Org migration, revised: rewrite content, do not lift scaffolding

**Date:** 2026-07-28
**Supersedes the architecture in** [`2026-07-15-ts-org-migrate-design.md`](2026-07-15-ts-org-migrate-design.md).
Phase 0 (`scan-sets`) and Phase 1 (`audit`) in that spec are unaffected and still stand.

## Why the previous architecture is being replaced, not patched

The 2026-07-15 design avoided rewriting content by lifting the tenant's Tables and Models
into the target Org and renaming columns once at the Model level, letting the change cascade
to dependents. That was O(columns) instead of O(objects), and it was the whole reason for
the scaffolding.

Two live findings removed the foundation:

- **BL-148** — the lifted scaffolding collides **by name** with the published objects. It is
  structural: `audit` pairs tenant Model to published Model *by name*, so they always share
  one, and reference resolution is fqn-then-name.
- **BL-149** — the rename cascade is **asynchronous**. `answer_columns` and `table_columns`
  update immediately; `search_query` does not, so an export taken right after a rename is
  internally inconsistent.

And the underlying reason both bite: **content TML has no physical anchor.** A Liveboard
references columns purely by display name, including `table_columns[].column_id`, which is
the *display name* and not a `TBL::COL` binding. Only `tables[].fqn` is stable.

So the rewriting the old design existed to avoid was never avoidable. Accepting it makes
the design smaller.

## The design

For each content object: **export, rewrite two things, import.**

```
tables[].fqn          <ACME Model guid>  →  <published Model guid>
column references     "Segment"          →  "STRING_1"
```

That is the migration. What it deletes from the old design:

| Old step | Why it existed | Now |
|---|---|---|
| Lift scaffolding Tables + Models | give content something to bind to | **gone** (with BL-148) |
| Rename Model columns | make the cascade fix content for free | **gone** (with BL-149) |
| Repoint | move content off scaffolding | **merged into the rewrite** |
| Cleanup scaffolding | undo the lift | **gone** |
| Provision a connection in the target | lifted Tables carry a `connection` block | **gone** — nothing is lifted |

Eight steps become three. The source Org is **untouched** again, which restores it as the
rollback, and the connection problem disappears in every topology.

## Topology: all three combinations are one code path

| | 1. Same Org, same cluster | 2. New Org, same cluster | 3. New Org, new cluster |
|---|---|---|---|
| Content | updated in place | created fresh | created fresh |
| `create_new` | `false`, keep `guid` | `true`, strip `guid` | `true`, strip `guid` |
| Clients | one | two Org-scoped, one profile | two profiles |
| Rollback | restore from backup (weakest) | delete the Org | delete the Org |
| Cutover | none | move users | move users |

Only one thing varies, and it follows from a single question:

```
same Org  →  keep the guid, create_new: false
new Org   →  strip the guid, create_new: true
```

Cluster needs no special handling: it is a property of the profile, and source and target
clients are already independent.

**Case 1 caveats.** Publishing the master Model *into* the source Org puts a second object
of the same name beside the tenant's own, so rename the tenant's Model first (safe: its
content binds by `fqn`, which stays alive in-Org). Its rollback is also the weakest, because
the backup is the only safety net.

**Case 3 caveats.** Tags, schedules and sharing are per-cluster and need re-establishing.
The per-Org aliases live on the *target* cluster's Primary Model.

## The rewrite surface — measured, not guessed

Scanned four of the richest Liveboards on `se-thoughtspot` (41, 28, 27 and 19
visualizations, with filters and chart configs) by taking each Liveboard's underlying Model
columns and recording every path where one appears.

### Whole-string references — rewrite the value

| Path | Hits |
|---|---|
| `visualizations[].answer.answer_columns[].name` | 112 |
| `visualizations[].answer.table.table_columns[].column_id` | 112 |
| `visualizations[].answer.table.ordered_column_ids[]` | 112 |
| `visualizations[].answer.chart.chart_columns[].column_id` | 112 |
| `visualizations[].answer.chart.axis_configs[].x[]` | 56 |
| `visualizations[].answer.chart.axis_configs[].y[]` | 26 |
| `visualizations[].answer.chart.axis_configs[].color[]` | 24 |
| `filters[].column[]` | 7 |
| `ordered_chips[].name` | 7 |
| `views[].view_filters[].column[]` | 7 |
| `visualizations[].answer.answer_columns[].custom_name` | 5 |
| `visualizations[].answer.chart.axis_configs[].category[]` | 1 |

### Bracketed tokens — rewrite inside the string

| Path | Hits | Example |
|---|---|---|
| `visualizations[].answer.search_query` | 319 | `[sales] [store] [date].'last 12 months' top 5` |
| `visualizations[].answer.formulas[].expr` | 48 | `to_string ( [date] , "%d-%m-%y" )` |

### Nested JSON blob — parse, rewrite named fields, re-serialise

`client_state_v2` (on both `chart` and `table`) is a JSON string, and its column references
sit in **named fields**, not as loose substrings:

```
columnProperties[].columnId    = "Total sales"      ← rewrite
systemSeriesColors[].serieName = "Total sales"      ← rewrite
axisProperties[].id            = "3352d226-…"       ← GUID, leave alone
```

Being structured is what makes this safe. A substring pass over the blob would corrupt it;
a parsed pass over two known fields will not.

### Must NOT be rewritten

Two paths matched a column name exactly but are **user-facing labels, not references**:

- `visualizations[].answer.name` — the visualization title. Three matched a column name
  coincidentally; rewriting would rename the user's chart.
- `filters[].display_name` — the filter's label.

`answer.name` also produced 134 *substring* matches (titles like "Sales by Region"), which
is exactly the class a naive find-and-replace would mangle.

## The completeness gate

**The scan above is the test.** Run it over a corpus of real Liveboards after a rewrite and
assert that no source-Org column name survives anywhere except the excluded label paths.

That converts "did we catch every field?" from a judgement into an assertion, and it is
re-runnable when the platform adds a field. This is the single most important piece of the
build: the failure mode of a partial rewrite is an object that imports cleanly and renders
wrong.

## Build order

1. `ts migrate rewrite` — the pure transform: `(content TML, column map, target Model guid)
   → content TML`. Pure functions, no I/O, unit-testable against captured fixtures.
2. The coverage assertion, wired as a test over real exported Liveboards.
3. Rework `apply` to export → rewrite → import, with the `create_new` switch above.
4. Delete the scaffolding code paths rather than leaving them unreachable.

`ts dependency mutate` already performs this class of TML transform, including
`search_query` handling, and should be extended rather than duplicated.

## Open

- **Views** sitting between content and the Model were not in the scanned corpus. They may
  carry their own column references and need the same treatment.
- **Answers** were scanned only as nested Liveboard visualizations. A standalone Answer is
  the same shape, but confirm.
- Whether `custom_name` should be rewritten at all. It is a user-supplied override, so it
  may belong with the labels rather than the references.
