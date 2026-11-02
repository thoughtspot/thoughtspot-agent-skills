# New audit rules, set 1 (roadmap PR 4.3)

**Status:** design, 2026-11-02. Roadmap row 4.3 (`2026-10-23-audit-v2-roadmap.md`, wave
4): "undocumented visible measures (G4); hidden ordinary columns (new); one term naming two
columns (G3); non-additive physical columns or LOD/last-value formulas summed (G1, as
corrected); redundant or conflicting Table-level joins (G14); join key type mismatch
(G11); technical columns visible (G15)". The G-numbers come from the expert rule review
(kept outside the repo). The product owner skipped the design questions (2026-11-02); every
call below is the author's and is listed at the end.

## Why

Each of these is something the TML alone shows and the audit misses today, and each either
gives a wrong number (G1, G11, G14), makes search or Spotter pick the wrong column (G3,
G15), or leaves a reader guessing what a number means (G4); the hidden-column rule is the
roadmap's "a large number of hidden ordinary columns is a smell" ruling.

## Constraints (from the roadmap and PR 4.2)

- Rules are catalog entries (`ts_cli/audit/catalog/rules/*.yaml`); no `check_*` functions.
  A derived field or a code rule only where the catalog cannot express it.
- Every rule declares `evidence`; a `heuristic` rule grades at most MEDIUM.
- Formula `aggregation:` is ignored in query generation except for `group_aggregate` and
  `last_value`/`first_value` with no aggregation inside, so additivity checks target
  physical columns and those formulas only (roadmap ruling, 2026-10-23). **Corrected
  2026-11-02:** a per-row formula's aggregation is used too, so D14 now reads per-row
  formulas (the roadmap constraint is amended).
- Hidden formulas used by other formulas are legitimate; hidden ordinary (physical)
  columns in number are the smell.
- New ids only; an id is never reused (A5, D2, D4, D6, H6, P5, P9, P10, P12, S3, S6–S9 are
  retired).
- Every rule ships `fires`/`silent` examples on synthetic fixtures; a rule at MEDIUM or above
  must not fire on more than half the sample's Models without a reviewed reason (PR 4.2).

## The rules

Measured on the 148-Model SE demo sample with a throwaway probe (counts only); the builder
re-measures with the real rules and reports in the PR.

| Id | Title | What fires | Evidence | Severity | Sample (probe) |
|---|---|---|---|---|---|
| A7 (G4) | Visible measures without a description | Per Model: the share of its visible MEASURE columns (physical and formula) with a blank root `description` | measure | LOW when any; MEDIUM above 75% | 91 Models any; 65 above 75% |
| H11 (new) | Many hidden ordinary columns | Per Model: the share of its physical columns (a `column_id`, no `formula_id`) that are hidden **without a reason H3 recognises** — not referenced by a formula (`@referenced_by_formula`) and not the last carrier of a joined table (`@is_sole_join_carrier`) — and not a key named in one of the Model's joins (`@is_join_key`; amended after review: hiding keys is good modelling). H3 reports each such column; H11 says when there are many | measure | LOW above 25%; MEDIUM above 50% | 0 after the amendment (4 before, all resting on hidden keys) |
| A8 (G3) | One search term naming two columns | Per Model: a term — a visible column's name or synonym, compared trimmed and case-insensitively — that names two or more visible columns. One finding per Model listing the terms (first five) and their count | fact | MEDIUM when a column's **name** is another's synonym or name; LOW when only synonyms are shared | 47 Models: 32 name collisions, 344 shared synonyms |
| D14 (G1) | Rate-like column summed | A physical MEASURE column whose name or the column part of its `column_id` reads as a non-additive quantity (price, rate, ratio, pct/percent/percentage, avg/average, balance, unit cost, per unit — whole words) with `aggregation` SUM or unset | heuristic | MEDIUM | 124 columns in 51 Models |
| D15 (G14) | Duplicate Table-level joins | A Table TML whose `joins_with` holds two joins to the same destination (by `destination.fqn`, else name) **with the same `on`** (compared without whitespace): MEDIUM when their type or cardinality differ (a query's result depends on which is taken), LOW when identical (a redundant copy). Two joins to one destination on different keys is role-playing, not a conflict | fact | LOW/MEDIUM | 0 Tables (2 Tables repeat a destination, on different keys) |
| D16 (G11) | Join keys of different types | A join (inline or referencing) whose `on` pairs two columns whose Table-level data types differ by family (string, integer, decimal, date/time, boolean); a key whose Table TML is not in scope is unknown and not reported, and so — through the type lookup P6 shares, keyed by Model alias — is a key of an aliased table (backlog: fixing it moves P6's pins) | fact | MEDIUM | 0 of 689 typed joins |
| H12 (G15) | Technical columns visible | A visible physical column whose physical name (the column part of its `column_id`) reads as pipeline plumbing: an `etl`/`dw`/`stg`/`staging`/`checksum`/`row_hash`/`hash_diff`/`row_num`/`record_source` token, a `loaded_`/`ingested_`/`inserted_` + `at`/`by`/`on`/`ts`/`date` name, or a leading underscore. Amended after review: the first list (`batch`, `load`, `sys`, `audit`, `hash`, `created_`/`updated_`/`modified_`) matched 25 columns that were all business data | heuristic | LOW | 0 after the amendment |

Categories: A7 and A8 in A (AI readiness: Spotter reads descriptions and terms); H11, H12 in H;
D14–D16 in D (D16 also P, beside P6's key-type rule). D13 is not used. A7 overlaps A1
(blank descriptions over all visible columns) on purpose: it singles out measures, the
columns Spotter explains numbers with, and is LOW unless most of them are blank. The builder may adjust a band if the
real rule fires differently from the probe, recording why.

### Out of scope (backlog)

- **A summed semi-additive formula** (G1's formula half). Nothing in the repo shows that a
  bare `last_value(col, ...)` surfaced with SUM gives a wrong number (the repo's own note in
  `spotql_ops.py` says formula `aggregation` is ignored), and it fired once on the sample.
  Backlog item: verify live, then add as a fact rule (D13 left free for it).
- **Aliased join keys typed as unknown** (D16, P6): the shared type lookup keys by Model
  alias while a referencing join's `on` names Tables. Fixing it moves P6's pins; backlog.

- **Redundant joins** (G14's other half): a Model inline join repeating a Table-level join
  is the norm (369 of 575 inline joins on the sample); flagging it would be noise. Filed as
  a backlog item to decide whether it matters at all.
- Profile-specific (Spotter) bands for A7/A8 — added if the fire rates call for it.

## Fixtures and tests

Per rule, a `fires` and a `silent` fixture in `tests/audit_rule_fixtures/<category>.py`
(synthetic, the shared builders), plus edge tests: A8 trimming and case, name-vs-synonym
grading, hidden columns not counted; D14 whole-word matching (`separate` is not `rate`),
non-SUM aggregation not reported, formulas not counted, `_` treated as a word boundary;
D15 role-playing joins (same destination, different `on`) silent; H11 a hidden column a
formula references not counted; D16 unknown types not reported,
integer widths equal; H12 hidden columns not reported, display names ignored (physical
name only). Gate passes; `fire-rates` on the sample shows no new rule warns.

## Calls made without the product owner (check these)

- The seven ids and categories above; G1's formula half (D13) deferred until verified live.
- "Physical name" is the column part of `column_id` (the Table's column name), not the
  warehouse `db_column_name`, so D14 and H12 read the Model TML alone.
- H11 counts only hidden columns H3 would not excuse.
- D15 fires only on a true duplicate (same destination and `on`).
- A7 overlaps A1 on purpose.
- D16 does not see aliased tables' keys this PR.
- A7's lines (LOW any, MEDIUM above 75%) chosen so it does not fire at MEDIUM on most Models.
- A8 grades a name collision above a shared synonym.
- G14 narrowed to conflicting Table-level joins; redundant joins deferred.
- D14's and H12's word lists.
- H11's lines (25%, 50%).
