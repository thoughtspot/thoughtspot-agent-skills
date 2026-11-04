# New audit rules, set 2 (roadmap PR 4.4)

**Status:** design, 2026-11-04. Roadmap row 4.4 (`2026-10-23-audit-v2-roadmap.md`, wave 4):
RLS robustness (G5); IDs, zip codes and coordinates typed MEASURE, and the date-part hint
(G2); many-side alias and Spotter-parameter warnings (G9, G10); flags as 0/1 measures
(G17); slot-named columns with no aliases (G19); D13 (BL-506). The G-numbers come from the
expert rule review (kept outside the repo). The product owner skipped the design questions
(2026-11-04), so every call below is the author's; they are listed at the end.

## Why

Each rule catches something the TML alone shows that the audit misses today:
- **A wrong or missing number:** RLS dropping outer-joined rows, ids and coordinates summed, a semi-additive or group formula with the wrong rollup.
- **A feature that does not work as built:** an alias on the many side, parameters under Spotter, an RLS rule search cannot index.
- **A column a person cannot read:** flags as true/false or 0/1, slot names, redundant date parts.

## Constraints (from the roadmap, PR 4.2 and PR 4.3)

- Rules are catalog entries. A derived field or a code rule is added only where the catalog cannot express the rule.
- Every rule declares `evidence`, and a `heuristic` rule grades at most MEDIUM.
- New ids only, never reused.
- "Physical name" means the column part of `column_id`. A word boundary is `_`, a space or either end of the name.
- A rule at MEDIUM or above must not fire on more than half the sample's Models without a reviewed reason.
- Roadmap rulings 2026-10-23:
  - Date-part columns are usually unnecessary, because date keywords cover them, so they get a LOW hint, not an error.
  - Many-side aliases and Spotter parameters are in rollout, so they get LOW warnings.
- Formula aggregation, as ruled on 2026-11-02:
  - A per-row formula's column aggregation is applied.
  - An aggregate formula's aggregation is ignored.
  - A bare `group_aggregate` / `last_value` / `first_value` (no outer aggregate) applies its aggregation.

## The rules

Measured on the SE demo sample: 144 Models, recaptured 2026-11-04 (four of the earlier 148 were deleted from the cluster). The probe was throwaway and the counts are column/Model counts only. The builder re-measures with the real rules.

| Id | Title | What fires | Evidence | Severity | Sample (probe) |
|---|---|---|---|---|---|
| **S12** (G5a) | RLS table outer-joined without a null clause | A Model join of type LEFT_OUTER, RIGHT_OUTER or OUTER whose optional side is a Table carrying RLS rules, none of which calls `isnull`. The docs say RLS joins are INNER by default, so a user under the rule silently loses that table's unmatched rows. The optional side is the `with` table for LEFT_OUTER, the declaring table for RIGHT_OUTER, and both for OUTER. | fact | LOW until a live probe confirms the drop (backlog), then MEDIUM | 0 (479 outer joins; 8 RLS Tables) |
| **S13** (G5c, G5d) | RLS rule search cannot index | An RLS rule whose expression names neither `ts_groups*` nor `ts_username`, or that uses `!=` / `<>`. Per the RLS implementation docs, ThoughtSpot builds no suggestion index for it; that includes rules built only on `ts_org`, `ts_email_domain` or custom variables. | fact | LOW | 1 (`!=`) |
| **D17** (G2) | Identifier, coordinate or date part summed | A visible physical MEASURE column. Its name or physical name reads as an id, key, code, sku, zip/postal code, latitude/longitude, or a date part (year, quarter, month, week, day, fiscal year), with aggregation SUM or unset. Excludes count words: "number", "num", "no". | heuristic | MEDIUM | 86 columns (40 id-like, 46 date parts) in about 35 Models |
| **H13** (G2 hint) | Date-part columns beside a date | One finding per Model that has a DATE / DATE_TIME column and also visible ATTRIBUTE columns whose name reads as a date part, with a non-date type. Date keywords (`yearly`, `monthly`, …) cover these. Lists the first five. | heuristic | LOW | about 30 Models |
| **D18** (G9) | Copy of a table on the many side | A Model table whose role is fact or factless (`@table_role`, the 4.1 classifier) and whose Table (`fqn`) appears more than once in the Model, as a copy or alias. A fact merely renamed, appearing once, is not a copy. The docs say copies of many-side tables are not supported in Models; the feature is in rollout. | fact | LOW | at most 6 Models (to re-measure) |
| **A9** (G10) | Parameters under Spotter | A Spotter-enabled Model whose formulas name a Model parameter. The docs say Spotter does not support parameters; this is in rollout. | fact | LOW | 6 Models |
| **H14** (G17) | Flags shown as true/false or 0/1 | One finding per Model with visible flag columns: a BOOL / BOOLEAN data type, or a name starting `is_`/`has_`/`was_`/`can_`/`should_`/`flag_` or ending `_flag`/`_ind`/`_indicator`. MEDIUM-free by design: a flag is legitimate, only its presentation is the smell. Lists the first five. | heuristic | LOW | about 37 Models (110 BOOL columns) |
| **D13** (G1 formula half, BL-506) | Group or semi-additive formula with the wrong rollup | A MEASURE column surfacing a bare `group_aggregate` / `last_value` / `first_value` formula (exactly the three the ruling names; the `group_*` shorthands and `*_in_period` spellings wait on BL-509) (its aggregation is applied), whose name reads as a rate (D14's words) and whose aggregation is SUM. Unset is not flagged until BL-509 settles whether it is valid. | heuristic | MEDIUM | 0 (22 such formulas: 18 SUM, 4 AVERAGE; none rate-named) |

Categories: S12 and S13 in S; D13, D17 and D18 in D; H13 and H14 in H; A9 in A. No band
is set beyond the severities above. The builder may adjust a word list if the real rule
reads differently from the probe, and must record why.

### Out of scope (backlog)

- **G5b, an RLS rule walking a one-to-many join:** waits for BL-410's live probe, the same reason S11 leaves diamonds out.
- **G5e and G5f** (the tenant compared through different keys across a Model's tables; `isnull` on the secured table's own key) are judgement calls. Filed as one backlog item (BL-512).
- **Unset aggregation in D13, and its `group_*` / `*_in_period` shapes:** wait on BL-509.
- **H15 (G19, slot-named columns):** the audit does not fetch column aliases (a Beta export option), so it cannot tell an already-aliased slot column from a bare one; 0 on the sample. BL-514, with the alias fetch.
- **A live probe of S12's consequence** (an RLS Table on the optional side of a LEFT_OUTER join, with and without `isnull`), before raising S12 to MEDIUM: BL-511.
- **The audit's Model export drops a whole batch of 50 when one GUID is gone** (found recapturing the sample). Filed as BL-510; the fix is in `audit/context.py`, not a rule.

## Fixtures and tests

Each rule gets a `fires` and a `silent` fixture in `tests/audit_rule_fixtures/<category>.py`, plus these edge tests:

| Rule | Edge tests |
|---|---|
| S12 | a LEFT_OUTER join where the RLS table is the required side stays silent; a rule with `isnull` stays silent; RIGHT_OUTER and OUTER read the right side |
| S13 | `ts_groups_int` counts as a groups variable; `!=` fires even with `ts_groups` present |
| D17 | "Number of Orders" stays silent; AVERAGE is not reported; a formula column is not read; `rate_card_id`-style names keep D14 apart |
| H13 | silent without a date column; silent when the date-part column has a DATE type |
| D18 | an alias on a dimension stays silent |
| A9 | a Model that is not Spotter-enabled stays silent; a parameter name inside a quoted literal does not count |
| H14 | silent on hidden flags |
| D13 | `sum(group_aggregate(...))` stays silent; AVERAGE stays silent |

The gate passes, and on the sample `fire-rates` shows no new rule warns.

## Calls made without the product owner (check these)

- The eight ids and categories above. G5b, G5e, G5f and G19 (H15) are deferred.
- **S12 is a fact rule at LOW** until a live probe confirms the docs' consequence (builder check, 2026-11-04).
- **S13 merges the review's (c) and (d):** both mean "no suggestion index".
- **D17 leaves out "number", "num" and "no":** on the sample 6 of 10 "number" hits are counts.
- **D17 also covers date parts typed MEASURE.** H13 is the gentler hint for date-part attributes.
- **H13 and H14 are LOW** and report once per Model, so they don't flood the report.
- **D18 needs a real copy** (the Table twice), not just a renamed fact.
- **D18 and A9 are LOW** per the rollout ruling.
- **D13 skips unset aggregation** until BL-509.
