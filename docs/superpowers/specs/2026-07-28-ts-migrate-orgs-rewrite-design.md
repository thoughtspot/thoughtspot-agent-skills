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

### Qualified `Source::Column` references — rewrite the column half

Found 2026-07-28 on a **second** pass, and missed by the first because the scan looked for
whole-string matches. 82 occurrences across 45 real Liveboards, in the SAME fields that
also hold the bare form:

| Path | Qualified | Bare |
|---|---|---|
| `filters[].column[]` | 25 | 39 |
| `ordered_chips[].name` | 36 | — |
| `views[].view_filters[].column[]` | 7 | 9 |
| `parameter_overrides[].value.name` | 14 | — |

`parameter_overrides[].value.name` did not appear in the first scan at all, precisely
because it only ever holds the qualified form.

Only the **column half** is rewritten. The source half is the Model name, and the
migration pairs tenant Model to published Model *by name*, so it does not change.

**The coverage gate had the same hole** and reported these documents clean. Both were
fixed together — a gate that shares the transform's blind spot is worse than no gate,
because it converts an unknown into a false assurance.

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

## Views SHIELD the content built on them — PROVEN END TO END

Verified 2026-07-28, first on `se-thoughtspot` (the fields are independent) and then
**functionally** on `nebula-damian-alias` (a real repoint preserves the shield).

### The live repoint test

Built in ORG1: two Models over the same physical column (`Segment` in Model A, `STRING_1`
in Model B), a View reading Model A's `Segment` but **exposing** it as `MySegment`, and an
Answer built on the View.

The View was then repointed A → B: `tables[].fqn`, `search_query` and
`search_output_column` all rewritten. `view_columns[].name` was deliberately left alone.

```
VIEW after repoint
  reads from  : T2_ALT_MODEL          <- different Model
  search_query: [STRING_1] [AMOUNT]   <- different column
  name='MySegment'   search_output_column='STRING_1'    <- alias SURVIVED

ANSWER on the view (never touched)
  search_query  : [MySegment] [MyAmount]
  answer_columns: ['MySegment', 'Total MyAmount']
```

And it still **returns data**, which is the check that matters — structural survival is not
functional survival:

```
VIEW           columns ['MySegment']                    rows Closed Lost / Closed Won / Demo
ANSWER on view columns ['MySegment', 'Total MyAmount']  rows [Closed Lost, 3949.3], …
```

The View reads a different Model through a different column name while the untouched Answer
keeps working. **The shield is real.**

### Why it works

A View's output column has **two independent fields**, and 9 of 265 columns inspected on
`se-thoughtspot` already diverge in the wild:

```
name='LINEAMOUNT'      search_output_column='Total LINEAMOUNT'
name='Number of URL'   search_output_column='URL'
name='YM'              search_output_column='Month(YM)'
```

- `search_output_column` binds to the **search result**, which references the source
  Model's columns.
- `name` is the alias **downstream content sees**.

So repointing a View changes what it *reads* without changing what it *exposes*. Rewrite
the View and **every Answer and Liveboard built on it needs no rewriting at all.**

| Field on the View | Action |
|---|---|
| `tables[].fqn` | → published Model guid |
| `search_query` | bracketed tokens → published names |
| `view_columns[].search_output_column` | → published name, **preserving any decoration** |
| `formulas[].expr` | bracketed tokens → published names |
| `view_columns[].name` | **leave unchanged** — this is what shields downstream content |

The decoration matters: `search_output_column` carries aggregation and bucket wrappers
(`Total LINEAMOUNT`, `Month(YM)`), so the rewrite substitutes the column name *inside* the
token rather than replacing the whole value.

### What this means for `audit`

**Dependents must be classified by what they are built on, and the classification changes
the work:**

| Content sits on | Treatment |
|---|---|
| the Model directly | full rewrite (the surface above) |
| a **View** | **no rewrite** — repoint the View instead |
| a Table directly | full rewrite, and flag it: a Model-level column rename never reaches it |

A tenant whose content is mostly View-based is dramatically cheaper to migrate than the
object count suggests, and the audit is what tells you which kind you have. Today it
reports dependents without distinguishing them, so this is a required addition rather than
a refinement.

## Alias scoping: the per-wave merge needs an OVERLAP check, not just a count

Verified 2026-07-28. Two facts change what the wave-level alias step must do:

- **Org-wide aliases use `group: TS_WILDCARD_ALL`**; an empty group is rejected.
- **An ambiguous alias resolves to the BASE column name.** A user matching both a
  `TS_WILDCARD_ALL` entry and a group entry for one column sees `STRING_1`, not either
  alias — *identical values do not help*.

So the specified fail-closed **count** assertion is necessary but not sufficient. A wave
that adds a group-scoped alias where a wildcard one already exists passes the count check
and silently reverts that tenant to generic names, with every entry individually valid and
the import reporting `OK`.

The step must additionally **refuse overlapping scopes** for any (column, Org) pair.

Compounding it: `--merge` is additive and cannot remove an entry, so fixing a bad scope
needs a full non-merge rebuild — which drops anything absent from the input. That is the
same blast radius as the partial-export failure, reached from the other direction.

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

- **Answers** were scanned only as nested Liveboard visualizations. A standalone Answer is
  the same shape, but confirm.
- Whether `custom_name` should be rewritten at all. It is a user-supplied override, so it
  may belong with the labels rather than the references.
