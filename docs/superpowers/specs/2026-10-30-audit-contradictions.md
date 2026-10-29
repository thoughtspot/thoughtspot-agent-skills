# The BL-406 contradictions (roadmap PR 2.2), with BL-461 and BL-462

**Status:** built to the product owner's rulings (roadmap "Rulings already made": the 16
contradictions follow the decision sheet's recommendations) · **Roadmap:**
`2026-10-23-audit-v2-roadmap.md`, wave 2, PR 2.2

## The sixteen, after PR 2.1

| Rule | Ruling | Here |
|---|---|---|
| S3, D6, A5, D2 | Settled by PR 2.1 (retired or merged) | — |
| A4 | Retitle: it checks the Model description, not Spotter config | Title "Model has no description" |
| D7 | Identical HIGH; partial MEDIUM only with a shared fact | Code rule `model_overlap`; shared fact = a table both Models contain that reads as a fact (more than 3 MEASURE columns) in either, by `@fact_table_set` |
| D11 | Coded severities kept; fix wording and reach | INFO worded by the join's cardinality; a referencing join's cardinality falls back to its Table's `joins_with` entry — which export never fills, so the reach stays open as BL-496 |
| H10 | MEDIUM when also orphan (Model-name hits only) | Code rule reads `@dependent_count`, H4's test; column hits stay LOW |
| D1, D5, D9, H1, H2, S1, S2, S5 | Code is right | No change to behaviour. Their catalog descriptions, which generate the check catalog, state the coded behaviour; S5's ("api key … as a whole word") and H2's (case) were corrected to match the code |

The decision sheet's companion notes are left to the PRs that own them: H2's "The "/"A "
boilerplate and S1's word boundaries (PR 2.3), D1's and H10's grading into data (PR 2.4),
the alias lookups in D10, D11 and H3 (PR 2.3).

## BL-461 and BL-462

- **D9** matches `\bsql_[a-z_]+_aggregate_op\b`: double, date and every other type. A scalar
  `sql_<type>_op` is not an aggregate pass-through and stays out.
- **P18** also reads the formula a column surfaces (new field `@formula_expr`) for
  `unique count`, `unique_count_if` and `group_unique_count`. Its message says "Distinct
  count on …", since a formula has no COUNT_DISTINCT aggregation to name.

## Choices the rulings left open

- **What "a shared fact" means.** A table both Models contain that reads as a fact in
  **either** of them: the fact test counts physical MEASURE columns only, so the same
  fact table reads as a dimension in a Model that measures it through formulas, and
  "in both" dropped two real duplicate pairs on the SE demo sample (independent review).
  Tables are found by alias, else name, so D7 does not inherit BL-305. The fact test is
  the one wave 4 replaces with join-direction inference; D7 picks that up through
  `@fact_table_set`.
- **D11's reach is not closed.** Exported Table TML carries no join cardinality (0 of 165
  in the 2026-07-30 census, 0 of 527 on the sample), so the fallback finds nothing today
  and about a fifth of joins stay unjudged. BL-496 holds the follow-up.
- **H10 now reads Set data** (`uses: [dependents, sets]`), as H4 does, so turning H4 and
  H5 off no longer drops Set discovery from an H run while H10 is on.

## Verification

- Pins moved for D7, D9, D11, H10 and P18 (output in the PR); two edge probes updated
  and D7's MEDIUM probe removed (no pinned input has a shared fact; the new tests hold
  it); the D11 strict xfail now passes as a plain test.
- New tests per behaviour (`tests/test_audit_contradictions.py`, H10 in
  `test_audit_rules_human.py`), each checked against a deliberate mutation.
- The 148-Model SE demo sample replayed on main and on the branch: only D7, H10 and P18
  move (D7 3 MEDIUM → 2, H10 21 LOW → 18 LOW + 3 MEDIUM, P18 0 → 56 INFO); every
  other finding is identical. The support-case Model was not available.
