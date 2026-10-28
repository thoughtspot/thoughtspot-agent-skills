# `ts audit run` owns scope and fetch (roadmap PR 1.3, BL-407)

**Status:** decisions taken by the product owner 2026-10-28 · **Roadmap:**
`2026-10-23-audit-v2-roadmap.md`, wave 1, PR 1.3

## Problem

The ts-audit skill's Steps 3–4 have the LLM do mechanical work: search for Models, tell
Models from legacy Worksheets, filter them to the chosen connections by hand, then export
every Model's TML into a cache that `ts audit run` never reads (BL-407: 1–5 minutes and an
API call per object, for nothing). That breaks roadmap principle 1 — deterministic code
decides, the LLM orchestrates — and the hand connection filter is fragile: a Model's
search result rarely carries a connection name (28 of 2,190 Models on the SE demo
cluster, 2026-10-28), so the filter has to go through the Model's Tables.

## Decisions (2026-10-28)

1. **Step 4 is dropped.** Step 5 (renumbered 4) always passes `--snapshot-out` into the
   run folder, so a re-run with other angles or the other assessment replays from disk
   (`--snapshot-in`) with no API calls.
2. **Connection scope: any Table.** A Model is in scope when any of its Tables, directly
   or through a View, is on a selected connection. Cross-connection Models are included.

## Design

### CLI surface

```
ts audit run --models GUID ...            # unchanged
ts audit run --all-models                 # every Model the user can see
ts audit run --all-models --connection "Snowflake Prod" --connection "BQ"
ts audit run ... --dry-run                # resolve scope, print the inventory, fetch nothing else
```

- Exactly one of `--models` / `--all-models` (or `--snapshot-in`). `--connection` is
  repeatable and requires `--all-models`.
- `--dry-run` prints `{"models": [{guid, name}], "model_count", "legacy_worksheets_skipped",
  "connections", "tables_by_connection", "views_not_followed"}` and exits. The skill shows this as the
  inventory and asks to proceed. A scope resolving to zero Models exits non-zero with the
  reason, never runs an empty audit.

### Resolution (new module `ts_cli/audit/scope.py`)

Pure functions, tested without a cluster, plus one thin I/O function:

- `select_models(rows)` — Model search rows → Models. A Model is
  `metadata_header.worksheetVersion == "V2"`; anything else is a legacy Worksheet, counted
  and skipped. (Verified live 2026-10-28: 2,190 V2, 23 without a version.)
- `tables_on_connections(rows, names)` — Table search rows whose
  `metadata_header.dataSourceName` matches a name, **case-insensitively** (casefold, the
  `filter_by_connection` rule; a hand comparison was the old failure).
- `models_reached(start, dependents_of, model_guids, max_depth=4)` — breadth-first from the
  Tables over LOGICAL_TABLE dependents. A dependent in `model_guids` is a Model in scope;
  any other dependent is followed as a View. Visited-guarded and depth-capped, so stacked
  Views and cycles terminate. Needs no per-object subtype lookup: the Model set is already
  known, which is what makes it cheap enough for a whole estate (the migrate module's
  `dependents_through_views` looks up each dependent's subtype, one call each).
- `resolve_scope(client, all_models, connections)` — the I/O: one paginated Model search;
  with connections, one paginated Table search and batched dependents calls (reusing
  `commands/metadata.py`'s `_build_dependents_payload` / `_normalize_dependents_response`).

### Skill changes (ts-audit, MINOR: new options replace manual steps)

- Step 2c keeps its question; the answer becomes `--connection` flags.
- Step 3 becomes "Confirm scope": run `ts audit run ... --dry-run`, show the inventory,
  confirm. The hand filter, the worksheet/Model sorting and the "why not
  `--connection`" note go.
- Step 4 (export) is deleted; Steps 5–7 become 4–6.
- New Step 4 runs with `--snapshot-out <run dir>/snapshot`; a follow-up audit of the same
  scope uses `--snapshot-in`.

## Review changes (2026-10-28, before merge)

An independent review found, and this PR fixes: a Model the user may not export
(`edoc: null` inside an HTTP 200) crashed the whole audit, which `--all-models` makes easy
to hit, and is now a per-Model warning; a misspelt connection beside a good one narrowed the
scope silently, and now exits 1 naming it (`tables_by_connection`); dependents are fetched 15
sources per call with a 300 s timeout, as `context.py` does; hidden Tables are searched;
Views cut off by the depth cap are reported (`views_not_followed`); repeated rows from
offset paging are dropped; `--dry-run` honours `--output` and refuses `--snapshot-out`.

## Out of scope

- Scoping by tag, owner or folder (not asked for).
- Replacing the snapshot's fetch with a cache keyed on `modified` (the snapshot covers
  re-runs within a session; cross-session reuse can be a later item if it is wanted).

## Verification

- Unit tests for the pure functions: V2/legacy split, casefolded connection match, direct
  and through-View reach, a View cycle, the depth cap, zero-Model scope.
- Live, on the SE demo cluster: `--dry-run --all-models --connection <one>` cross-checked
  against the Models whose exported Table TML names that connection, for a sample, so the
  any-Table rule is proven where it is enforced rather than on fixtures.
- No finding changes (scope selects Models; rules are untouched): pinned-findings test
  unchanged.
