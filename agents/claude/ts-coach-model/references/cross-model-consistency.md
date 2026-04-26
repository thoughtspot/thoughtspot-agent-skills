# Cross-Model Consistency Check — `ts-coach-model`

The most common cause of "the dashboards disagree" complaints in production is
that the same column name has different definitions across the Models a user
can reach. Spotter doesn't disambiguate between them — when a user types
`amount by region`, it picks one column from one Model. If the user happens to
hit a different Model the next day, they get a different number for the same
question.

This is the central failure mode flagged by enterprise text-to-SQL benchmarks
([Axius, "The 7-Table Fallacy"](https://axiussdc.substack.com/p/the-7-table-fallacy-why-text-to-sql)
— accuracy drops from 95% on clean schemas to 39% on enterprise ones with
4,000+ columns and abbreviated names). Their proposed fix is to embed
semantics directly in data structures rather than rely on naming alone. We
can't change the product, but we CAN detect collisions across Models the user
controls and force a documentation / rename / alignment decision before
coaching.

---

## When this runs

[SKILL.md Step 4.5](../SKILL.md), after the existing-AI-assets critique
(Step 4) and before the Step 5 scope menu. Always runs — the result feeds
into the Step 5 critique summary regardless of which surfaces the user picks
in Step 5.

The user can opt out by selecting `0` (none) on the Step 5 surface menu
when offered the cross-Model option. They can also choose to defer review
to a later run; in that case the file is generated but no decisions are
required to proceed.

---

## What we compare

For each column in the target Model, search all Models the user can read in
their org and compare against same-named columns elsewhere:

| Signal | Why it matters | Heuristic |
|---|---|---|
| `db_column_name` | Different warehouse source ⇒ almost always different meaning | Exact match required |
| `column_type` | Measure vs attribute mismatch is structurally divergent | Exact match required |
| `aggregation` | sum vs avg = different semantics for the same name | Exact match required |
| Formula expression | Two formulas with the same name but different math | String-equal after whitespace normalisation |
| `ai_context` text | Two AI Context blocks that contradict each other | Substring conflict heuristic — flag if either contains a phrase the other negates (`includes returns` vs `excludes returns`) |

We do **not** compare:
- Display-name spelling variants ("Amount" vs "Total Amount" vs "Order Amount")
  — exact-name matching only, to keep false-positive rate low
- Synonyms — synonyms are alternative names for one column on one Model;
  collisions across Models on a synonym are too noisy to be useful
- Description text — humans use this for catalog browsing; cross-Model
  description divergence is expected (Models have different audiences)

---

## How we enumerate the corpus

```python
# 1. Find all Models the current user can read.
ts metadata search --subtype WORKSHEET --profile {profile_name}
# (then filter to Models, not Worksheets, via metadata_header.contentUpgradeId)

# 2. For each Model, export TML with --fqn (we need db_column_name and the
#    full column property block).
ts tml export {guid} --profile {profile_name} --fqn

# 3. Build a lookup: column_display_name → list of (model_guid, model_name,
#    column_block, formula_block, ai_context, db_column_name)
```

**Cost.** A tenant with 50 Models means 50 TML exports. Cache each export by
`(model_guid, modified_time_in_millis)` — re-running the skill on a Model
that hasn't changed is free. First run is slow; subsequent runs cost
~1 export per Model that's been touched since the last run.

**Permissions.** The check only sees Models the *current user* can read. If
canonical Models exist in another org or under a different ownership, they
won't appear. Surface this caveat in the explainer block.

---

## Outcome rules

When a column has at least one collision, the proposed RouteAction is set
according to a decision tree:

```
divergent on db_column_name OR column_type?
  → propose RENAME (definitions are structurally different)

divergent on aggregation OR formula expression OR ai_context?
  → propose ALIGN if this Model's definition looks canonical
    (heuristic: oldest creation_time, or most recently modified, or the only
    one with non-empty ai_context — pick one signal, document it)
  → otherwise propose DOCUMENT_DIFFERENCE

no divergence (all collisions are identical)?
  → propose KEEP_AS_IS, mark as "duplicates exist but agree"

cannot determine?
  → NEEDS_REVIEW — the user has institutional knowledge the skill doesn't
```

The user always has the final say. The proposed action is a starting point
for the review; the user changes it if the heuristic is wrong.

---

## Output format

`{run_dir}/cross_model_consistency.md` with the explainer block from
[review-explainers.md](review-explainers.md) Block 6, followed by:

```markdown
| # | RouteAction | Column | # of collisions | Other Models | Divergent on | Suggested rationale |
|---|---|---|---|---|---|---|
| 1 | RENAME | Amount | 2 | "Q3 Sales", "Anant Copy" | db_column_name (DM_ORDER.AMOUNT vs DM_ORDER_DETAIL.LINE_TOTAL) | This Model is at order-line grain; "Q3 Sales" is at order-header grain. Different things. |
| 2 | KEEP_AS_IS | Customer Name | 4 | "Anant Copy", "Test Copy", "Sidharth Copy", "Anurag Copy" | (no divergence — all 4 use DM_CUSTOMER_BIRD.NAME) | Identical definition across all collisions. |
| 3 | ALIGN | Inventory Balance | 1 | "TestCopy" | formula expression (last_value vs first_value) | This Model uses last_value (snapshot), which is the documented Inventory Balance semantic. TestCopy is wrong. |
```

The "Suggested rationale" column is auto-generated from the heuristics —
the user edits it as needed. When the user picks `DOCUMENT_DIFFERENCE`,
the rationale text is what gets appended to this column's `ai_context` as
a `# CONFLICTS_WITH:` annotation.

---

## ai_context annotation format

For columns marked `DOCUMENT_DIFFERENCE`, the skill appends to the existing
`ai_context` block:

```yaml
ai_context: |
  meaning:    Dollar value of one order-line item (one row in DM_ORDER_DETAIL).
  unit:       USD.
  ...
  # CONFLICTS_WITH:
  #   Model "Q3 Sales" (guid=abc...): uses DM_ORDER.AMOUNT (order-header grain).
  #     Rationale for keeping both: Q3 Sales is a flash report at the order
  #     level; this Model is the canonical line-level view.
```

Future Spotter index passes will see the conflict notice. Future runs of
this skill will detect the `# CONFLICTS_WITH:` markers and skip re-flagging
those collisions unless the underlying definitions change.

---

## Tradeoff to flag in the explainer

The cross-Model scan produces both **true positives** (real silent
divergence — fix this) and **legitimate-difference false positives**
(per-domain Models that intentionally scope `Amount` to their slice). The
`INTENTIONAL_DIFFERENCE` and `DOCUMENT_DIFFERENCE` outcomes exist for the
second case. The skill should not pressure the user into spurious cleanup;
the explainer block makes this explicit by showing all six allowed
outcomes side-by-side.

---

## Verification status

This logic is **NOT yet verified** against a live tenant — see
[open-items.md](open-items.md) #15 for the calibration test:

1. Run on a tenant with ≥ 20 Models the user can read
2. Sample 10 collisions; for each, check whether the heuristic-proposed
   RouteAction matches what a domain expert would pick
3. Tune the "canonical Model" heuristic if the proposal is wrong > 30% of
   the time
4. Tune the substring-conflict heuristic for ai_context divergence

Until verified, the skill should always default the proposed action to
`NEEDS_REVIEW` rather than the heuristic's pick.
