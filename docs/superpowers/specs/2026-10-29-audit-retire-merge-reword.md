# Retire, merge, reword (roadmap PR 2.1, BL-406)

**Status:** built to the product owner's rulings of 2026-10-23 (roadmap "Rulings already
made") · **Roadmap:** `2026-10-23-audit-v2-roadmap.md`, wave 2, PR 2.1

## What changes

| Rule | Now | Why (the ruling) |
|---|---|---|
| S3 | retired | Says "no CLS or masking" but never reads column security. It comes back when it reads Column Security Rules. |
| P9 | retired | Search indexing has nothing to do with query performance. |
| S8 | retired | A text column in an RLS rule is not a security problem. |
| P5 | retired | No date limit on fact tables is a design choice, and its fact detection is wrong. |
| D6 | retired | Grain is keys and dates, not the share of attributes. |
| A5 | retired as a rule; becomes a score | The Spotter readiness score is no longer a finding. It shows in each Model's header and in a heatmap column. |
| D2 → P6 | D2 retired; P6 takes both halves | String-typed join keys are **LOW**; a join on more than one key pair is **INFO**. P6 is in categories P and D. |
| D4 → P4 | D4 retired; P4 kept | "Every join applied on every query": one rule in categories P and D. |
| S9 → P14 | S9 retired; P14 kept | A function in an RLS rule is a performance issue, not a security one. P14 stays in P only. |
| P2 | reworded, lower severity | A row-level formula is recomputed by the warehouse on every query; materialise heavy ones as a column in ETL. LOW above 5, MEDIUM above 10 (was MEDIUM / HIGH). |

## Choices the rulings left open

- **Retired rules keep their logic** (S3, P9, S8, P5, D6), as rule-authoring.md
  allows, as a record of what each checked. They cannot run again under these ids: the
  history gate refuses reactivating a retired id, under a profile too, so a check that
  comes back (S3 reading Column Security Rules) is a new rule with a new id. D2, D4, S9
  and A5 drop their logic: D2 and D4 would duplicate the rule they merged into, S9
  likewise, and A5's code rule is deleted because the score is now computed for the
  report.
- **P6 in D as well as P.** The ruling names categories only for D4→P4. D2 sat in D,
  and a multi-key join is a modelling observation, so P6 joins D too; otherwise the
  Data Modeling tab would lose both join-key findings.
- **P2's "modest severity"** is read as one step down at each band. P2's test of what
  is "row-level" (no `aggregation` on the surfacing column) is unchanged; the
  expression-based test is PR 2.4.
- **The readiness score's lines** (Ready at 80 or more, Needs work at 50 or more) stay
  where A5 had them. They are constants beside the scoring function, because the score
  is no longer a rule and so has no catalog entry to hold them. It is computed only
  when the AI Readiness category ran, since that is when AI instructions are fetched.
  A Model whose lookup failed scores as uncoached, as A5 did.

## Not in this PR

The 16 contradictions (PR 2.2), noise fixes (2.3) and grading into data (2.4).
BL-461 (D9's regex) and BL-462 (P18 and `unique count`) go with PR 2.2, which already
touches D9.

## Verification

- Every retired or changed pinned rule is re-pinned. The before/after output is in the PR.
- Before/after finding counts per rule, from a random sample of the SE demo cluster's
  Models (148 audited) replayed offline from one snapshot (aggregates only; the snapshot
  stays outside the repository).
- **Not done:** roadmap principle 4 also asks for a before/after on the support-case
  Model. That Model is kept outside the repository and was not available to this run;
  the change removes or regrades findings only for the rules listed above, which the
  pinned inputs and the sample both cover.
- The report is rendered from the replay to check the header and heatmap score.
