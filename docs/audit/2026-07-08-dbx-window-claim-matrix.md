# Databricks Metric View window-claim verification matrix

**Serves:** BL-063 Phase 2 PR 1 (`docs/superpowers/specs/2026-07-08-dbx-conversion-substrate-design.md`,
"Currency-check pre-step" — window-semantics deep analysis). This is the single evidence
artifact the PR's acceptance criteria ("every window mapping ... carries a live-verified
citation ... or is corrected") is checked against.

This file is seeded once (Task 2) with every window-related claim already living in the repo's
Databricks mapping/schema docs and worked examples, plus one new claim (C6a) surfaced during
plan research that isn't in any existing doc. **Do not re-list these claims elsewhere** —
Tasks 3–6 update this one file in place rather than producing a parallel tracker.

## How to read the columns

| Column | Meaning |
|---|---|
| ID | Stable claim identifier (`C1`–`C9`, `C6a`). Referenced by ID from the plan's remaining tasks — do not renumber. |
| Claim | The mapping/behavior being asserted, in the same words as the source doc(s). |
| Source (file:line) | Where the claim currently lives in the repo, and whether/when it was previously live-verified (if at all). |
| Verification method | How Tasks 3–6 will (in)validate the claim — live Databricks + ThoughtSpot number-match, documentation-only cross-check, or docs research. |
| Actual (live) | **Empty until Tasks 4–5 run.** Filled in with the observed result set(s) once the live queries execute against the Task 3 fixture. |
| Verdict | **Empty until Tasks 4–6 run.** One of: `CONFIRMED`, `CORRECTED` (with the fix), or `DEFERRED` (with the reason — see C8). |

Do not edit the `Claim` or `Source` cells once seeded — corrections to a claim found to be
wrong are recorded as a new line in `Verdict`, not by rewriting the original claim text.

## Fixture (Task 3 fills in)

Task 3 provisions the live Databricks fixture data these claims are tested against. Recorded
here once created:

- Catalog: `agent_skills` (Unity-Catalog-managed; appeared in `SHOW CATALOGS`, so no substitution
  needed — `hive_metastore` and `samples` correctly excluded)
- Schema: `ts_dbx_substrate_pr1`
- Fixture table(s): `agent_skills.ts_dbx_substrate_pr1.rolling_fixture` (24 rows),
  `agent_skills.ts_dbx_substrate_pr1.period_fixture` (6 rows)
- Metric View(s) (Task 4): `agent_skills.ts_dbx_substrate_pr1.rolling_mv` (covers C1–C5, C7),
  `agent_skills.ts_dbx_substrate_pr1.period_mv` (covers C6, C6a)
- Row counts / date range: `rolling_fixture` = 24 rows sanity-confirmed (expected 24) — 2
  categories (X, Y) × 12 sequential days, `txn_date` 2026-06-01 .. 2026-06-12. `period_fixture` =
  6 rows sanity-confirmed (expected 6) — 2 categories × 3 months, resolved relative to
  `CURRENT_DATE()` at execution time (2026-07-08) to `txn_date` = 2026-05-15 / 2026-06-15 /
  2026-07-15 (i.e. "current month" = July 2026 for this run).

## Live results convention (Tasks 4–5 append)

Tasks 4 and 5 append the actual observed result sets **under the claim table**, one subsection
per claim ID (e.g. `### C1 — live results`), rather than cramming raw output into the `Actual
(live)` table cell. The table cell holds a short pointer/summary (e.g. "matches, see below" or
the mismatch delta); the subsection holds the full query + result set. Tasks 4–5 do not touch
the `Claim` or `Source` columns.

---

## C1–C9

| ID | Claim | Source (file:line) | Verification method | Actual (live) | Verdict |
|---|---|---|---|---|---|
| C1 | `range: trailing N day` (no modifier) → `moving_sum([m], N, 0, [date])` | `ts-from-databricks-rules.md:652-654`, `ts-databricks-formula-translation.md:280-282`, `ts-databricks-properties.md:97`; live-verified 2026-05-28 in `worked-examples/databricks/ts-from-databricks.md` (revenue_7d_rolling) **before** the `exclusive`-default was confirmed | Live DBX + TS number-match | See `### C1 — live results` below (Query A1, 24 rows) — day_index=6 matches the hand-computed exclusive-window arithmetic exactly | — (needs Task 5 TS-side match) |
| C2 | Anchor default is `exclusive` for `trailing`/`leading` | `databricks-metric-view.md:452`, `ts-from-databricks-rules.md:574-581`, `ts-databricks-formula-translation.md:318-325` — all three say the same `moving_sum` equivalence in C1 "predates" this confirmation and "needs re-verification" | Live DBX (compare `trailing N day` vs. `trailing N day exclusive` vs. `trailing N day inclusive` on the same data) | See `### C2 — live results` below — `trailing3_default` == `trailing3_exclusive` and `leading3_default` == `leading3_exclusive` at all 24 rows, including matched boundary NULLs | **CONFIRMED** (live 2026-07-08, DBX-only — decidable without TS) |
| C3 | `range: leading N day` → candidate `moving_sum([m], 0, N, [date])` | `ts-from-databricks-rules.md:672-681`, `ts-databricks-formula-translation.md:297-307`, `databricks-metric-view.md:446` — all marked PENDING LIVE VERIFICATION | Live DBX + TS number-match | See `### C3 — live results` below — leading3_inclusive/exclusive match hand-computed values exactly at day_index=6 | — (needs Task 5 TS-side match) |
| C4 | `range: all` → candidate partition-wide `group_aggregate(...)` | `ts-from-databricks-rules.md:683-691`, `ts-databricks-formula-translation.md:309-316`, `databricks-metric-view.md:447` — all marked PENDING LIVE VERIFICATION | Live DBX + TS number-match | See `### C4 — live results` below — `all_amount`=780 (X) / 12780 (Y) at every row, confirmed **per-category**, not table-wide (would be 13560); Query A2 cross-check matches exactly | — (needs Task 5 TS-side match) |
| C5 | `range: cumulative` → `cumulative_sum([m], [date])` | `ts-from-databricks-rules.md:666-670`, `ts-databricks-formula-translation.md:467-472`, `ts-databricks-properties.md:98` — not flagged PENDING but **never exercised in any worked example** | Live DBX + TS number-match | See `### C5 — live results` below — cumulative_amount matches hand-computed running total (210 / 6210) at day_index=6 | — (needs Task 5 TS-side match) |
| C6 | `range: current` + `offset: -N <unit>` (period filter) → `sum_if(diff_months/quarters/years([date], today())=N, [m])` | `ts-from-databricks-rules.md:620-631`, `ts-databricks-formula-translation.md:429-465`; live-verified 2026-05-25 in `worked-examples/databricks/ts-to-databricks.md` (Monthly/Prior Month Revenue) **but only ever queried at a single point in time, not across a multi-month trend** — see the wall-clock-vs-row-relative ambiguity below | Live DBX (3-hypothesis discriminator, Task 4 Query B1) + TS number-match | See `### B1 — full result set` and `### C6 — live results` below — Query B1 output matches hypothesis (c) row-relative exactly, refuting (a) and (b) | **WRONG (DBX-confirmed, live 2026-07-08)** — the documented mapping is wall-clock `today()`-based; actual Databricks behavior is row-relative to each output row's period. Correction (the replacement formula) is Task 6's job — not written here. |
| C7 | `range: current`, `order:` raw date, `semiadditive: last/first` (true semi-additive) → `last_value`/`first_value(sum([m]), query_groups(), {[date]})` | `ts-from-databricks-rules.md:589-609`; `last` live-verified 2026-05-25 (`ts-to-databricks.md` Inventory Balance); **`first` never exercised in any worked example** | Live DBX + TS number-match (re-confirm `last`, newly confirm `first`) | See `### C7 — live results` below — Query A2: X→last=12/first=1, Y→last=112/first=101; matches hand-computed expectation exactly; first live exercise of `semiadditive: first` | — (needs Task 5 TS-side match) |
| C8 | Offset at quarter/year grain (`-3 month`→quarter offset -1, `-1 year`→month offset -12) | `ts-from-databricks-rules.md:616-630`, `ts-databricks-formula-translation.md:433-438` — documented as symmetric extrapolations of C6, **never live-tested** (only `-1 month` was exercised in the worked example) | Documentation-only cross-check (Task 6) — not re-tested live; same underlying mechanism as C6, budget does not cover every grain | — | Deferred — inherits C6's verdict |
| C9 | `materialization:` block | Undocumented anywhere except the one-line mention at `databricks-metric-view.md:99` and the anchor text in `ts-databricks-properties.md:1` ("materialization Public Preview") | Docs research only (Task 1) — no live SQL needed unless Task 1 finds it changes parseable shape | — | — |

### Docs-research notes (Task 1)

Task 1 (`docs/audit/2026-07-08-dbx-window-docs-findings.md`) ran before the live tasks and
sharpens several rows below. These notes do **not** change any Verdict or Verification method
— live verification (Tasks 3–5) and the Task 6 doc cross-check still own those columns.

**C1** — Task 1 confirms, via verbatim quote from the `yaml-reference` page, that the
`trailing`/`leading` default is `exclusive`. This independently reinforces the concern already
flagged in C2's citation: the `moving_sum([m], N, 0, [date])` equivalence in this row predates
that confirmation and needs re-verification against exclusive (anchor-row-not-included)
semantics, not just against an unspecified default.

**C2** — Confirmed word-for-word via two independent pages: `yaml-reference` — "The default is
`exclusive`."; `advanced-techniques` — "`exclusive` (default)". Matches
`databricks-metric-view.md:452` exactly. Task 1 also found that the `inclusive|exclusive`
modifier applies **only** to `trailing`/`leading` — `all`, `current`, and `cumulative` do not
accept it (not previously stated explicitly in the repo).

**C3** — The `leading <n> <unit>` definition ("Rows from the anchor row going forward by the
specified time units...") was reconfirmed verbatim from `advanced-techniques` on 2026-07-08.
Still spec-only — no live verification performed by Task 1 — so the PENDING status is
unchanged; this just confirms the spec hasn't drifted since the repo's last read.

**C4** — The `all` definition ("All rows regardless of the window ordering value") was
reconfirmed verbatim on 2026-07-08. Still spec-only; PENDING status unchanged.

**C5** — The `cumulative` definition ("All rows where the window ordering value is less than or
equal to the anchor row's value") was confirmed verbatim, consistent with the repo's existing
paraphrase. Still never exercised against live data.

**C6** — Task 1 newly confirms an offset boundary rule not previously recorded in the repo: "If
the shifted frame falls outside the available data, the measure evaluates to NULL." Task 4's
Query B1 should include an out-of-range offset case to check this NULL behavior alongside the
wall-clock/row-relative discriminator (see C6a).

**C7** — `semiadditive` values (`first`, `last`) confirmed verbatim, matching
`databricks-metric-view.md:510` exactly. No new information specific to `first`; it remains
never exercised live.

**C8** — Task 1 confirms the `offset` unit vocabulary is closed: `day`, `days`, `month`,
`months`, `year`, `years` only — no native `week` or `quarter` unit exists in Databricks. This
confirms the C8 approach (expressing quarter/year grain via month-multiples, e.g. `-3 month`
for a quarter) is the only representable form in Databricks' own grammar — there is no
alternative native syntax to cross-check the extrapolation against.

**C9** — Task 1 substantially documents the `materialization:` block: top-level key, `schedule`
/ `mode` / `materialized_views` fields (with `mode` currently only accepting `relaxed` per the
docs), a verbatim YAML example, and confirmed `Public Preview` status. The repo cross-check in
that file confirms `databricks-metric-view.md` still does not document this block (only the
forward-looking BL-032 note at line 99) and that `ts-databricks-properties.md:1`'s anchor
("materialization Public Preview") is correct. This is new content for Task 6 to add, not a
correction of an existing repo claim. Task 1 also flagged an open question — whether a
non-`relaxed` `mode` value 400s or is silently accepted — as a candidate for Task 3's fixture
design if materialization is in scope for the live experiment.

---

## Live results (Tasks 3–4)

All statements below ran live against `agent_skills.ts_dbx_substrate_pr1` on 2026-07-08. Both
Metric Views (`rolling_mv`, `period_mv`) parsed and created successfully on the first attempt —
no `range`/modifier failed to parse (`trailing`/`leading` `inclusive`/`exclusive`, `range: all`,
and `offset` all parsed cleanly), so no claim needed a PENDING re-flag for a parse failure.

### C1 — live results

**Query A1:**
```sql
SELECT cat, txn_date,
  MEASURE(daily_amount)        AS daily_amount,
  MEASURE(trailing3_default)   AS trailing3_default,
  MEASURE(trailing3_inclusive) AS trailing3_inclusive,
  MEASURE(trailing3_exclusive) AS trailing3_exclusive,
  MEASURE(leading3_default)    AS leading3_default,
  MEASURE(leading3_inclusive)  AS leading3_inclusive,
  MEASURE(leading3_exclusive)  AS leading3_exclusive,
  MEASURE(cumulative_amount)   AS cumulative_amount,
  MEASURE(all_amount)          AS all_amount
FROM agent_skills.ts_dbx_substrate_pr1.rolling_mv
GROUP BY cat, txn_date
ORDER BY cat, txn_date
```

Full 24-row result (this result set also feeds C2, C3, C4, C5 below — not repeated per claim):

| cat | txn_date | daily_amount | trailing3_default | trailing3_inclusive | trailing3_exclusive | leading3_default | leading3_inclusive | leading3_exclusive | cumulative_amount | all_amount |
|---|---|---|---|---|---|---|---|---|---|---|
| X | 2026-06-01 | 10 | NULL | 10 | NULL | 90 | 60 | 90 | 10 | 780 |
| X | 2026-06-02 | 20 | 10 | 30 | 10 | 120 | 90 | 120 | 30 | 780 |
| X | 2026-06-03 | 30 | 30 | 60 | 30 | 150 | 120 | 150 | 60 | 780 |
| X | 2026-06-04 | 40 | 60 | 90 | 60 | 180 | 150 | 180 | 100 | 780 |
| X | 2026-06-05 | 50 | 90 | 120 | 90 | 210 | 180 | 210 | 150 | 780 |
| X | 2026-06-06 | 60 | 120 | 150 | 120 | 240 | 210 | 240 | 210 | 780 |
| X | 2026-06-07 | 70 | 150 | 180 | 150 | 270 | 240 | 270 | 280 | 780 |
| X | 2026-06-08 | 80 | 180 | 210 | 180 | 300 | 270 | 300 | 360 | 780 |
| X | 2026-06-09 | 90 | 210 | 240 | 210 | 330 | 300 | 330 | 450 | 780 |
| X | 2026-06-10 | 100 | 240 | 270 | 240 | 230 | 330 | 230 | 550 | 780 |
| X | 2026-06-11 | 110 | 270 | 300 | 270 | 120 | 230 | 120 | 660 | 780 |
| X | 2026-06-12 | 120 | 300 | 330 | 300 | NULL | 120 | NULL | 780 | 780 |
| Y | 2026-06-01 | 1010 | NULL | 1010 | NULL | 3090 | 3060 | 3090 | 1010 | 12780 |
| Y | 2026-06-02 | 1020 | 1010 | 2030 | 1010 | 3120 | 3090 | 3120 | 2030 | 12780 |
| Y | 2026-06-03 | 1030 | 2030 | 3060 | 2030 | 3150 | 3120 | 3150 | 3060 | 12780 |
| Y | 2026-06-04 | 1040 | 3060 | 3090 | 3060 | 3180 | 3150 | 3180 | 4100 | 12780 |
| Y | 2026-06-05 | 1050 | 3090 | 3120 | 3090 | 3210 | 3180 | 3210 | 5150 | 12780 |
| Y | 2026-06-06 | 1060 | 3120 | 3150 | 3120 | 3240 | 3210 | 3240 | 6210 | 12780 |
| Y | 2026-06-07 | 1070 | 3150 | 3180 | 3150 | 3270 | 3240 | 3270 | 7280 | 12780 |
| Y | 2026-06-08 | 1080 | 3180 | 3210 | 3180 | 3300 | 3270 | 3300 | 8360 | 12780 |
| Y | 2026-06-09 | 1090 | 3210 | 3240 | 3210 | 3330 | 3300 | 3330 | 9450 | 12780 |
| Y | 2026-06-10 | 1100 | 3240 | 3270 | 3240 | 2230 | 3330 | 2230 | 10550 | 12780 |
| Y | 2026-06-11 | 1110 | 3270 | 3300 | 3270 | 1120 | 2230 | 1120 | 11660 | 12780 |
| Y | 2026-06-12 | 1120 | 3300 | 3330 | 3300 | NULL | 1120 | NULL | 12780 | 12780 |

**C1 finding:** at day_index=6 (interior row, 5 buffer days both sides), X `trailing3_default`=120
matches the hand-computed **exclusive** window (d3+d4+d5 = 30+40+50 = 120), not an
inclusive-of-anchor sum (which would be 150). The repo's candidate mapping
(`moving_sum([m], N, 0, [date])`) needs re-examination on the TS side (Task 5) for whether
ThoughtSpot's own `moving_sum` semantics are exclusive or inclusive of the anchor row — that
comparison is out of scope here. No Verdict recorded for C1 itself.

### Boundary-row observations (day_index 1–3, 10–12) — feeds C1–C5, Task 6 doc update

At day_index=1 (0 preceding rows available): `trailing3_default` / `trailing3_exclusive` are both
`NULL` for both categories. At day_index=2 (1 preceding row, less than the requested 3):
`trailing3_exclusive` returns the **partial sum** of the single available row (X=10, Y=1010) —
not NULL, not an error. Day_index=3 (2 preceding rows): partial sum of those 2 rows (X=30,
Y=2030). Only from day_index=4 onward is the window full (3 rows).

The tail side is symmetric: day_index=12 (0 following rows) → `leading3_default` /
`leading3_exclusive` both NULL; day_index=11 (1 following row) → partial sum of that row (X=120,
Y=1120); day_index=10 (2 following rows) → partial sum of those 2 rows (X=230, Y=2230).

`trailing3_inclusive` / `leading3_inclusive` never hit the zero-row NULL case, because they
always include the anchor row itself (minimum 1 row) — e.g. day_index=1 `trailing3_inclusive`=10
(X), day_index=12 `leading3_inclusive`=120 (X).

**Rule observed:** Databricks trailing/leading windows return a **partial-window sum** when
1..N-1 rows are available in the requested direction, and **NULL** only when **zero** rows are
available in that direction (for `exclusive`/default `trailing`/`leading`) — never an error and
never silently substituting 0. This is not documented anywhere in the repo today; flagged for
Task 6's schema-doc update.

### C2 — live results

Same query as C1 (Query A1) — see the full 24-row result set above. Comparing
`trailing3_default` against `trailing3_exclusive`, and `leading3_default` against
`leading3_exclusive`, column-by-column across all 24 rows: they are **identical at every single
row**, including the boundary rows where both are NULL together (day_index=1 trailing,
day_index=12 leading). E.g. at day_index=6: X `trailing3_default`=120=`trailing3_exclusive`=120;
`leading3_default`=240=`leading3_exclusive`=240. Same pattern holds for Y and at every other
day_index.

**Verdict: CONFIRMED (live, DBX-only, 2026-07-08).** This is decided entirely from Databricks'
own output — no ThoughtSpot comparison is needed to determine that the anchor default for
`trailing`/`leading` is `exclusive`. Matches `databricks-metric-view.md:452` /
`ts-from-databricks-rules.md:574-581` / `ts-databricks-formula-translation.md:318-325` exactly.

### C3 — live results

Same query as C1 (Query A1). At day_index=6: `leading3_inclusive` X=210 (d6+d7+d8=60+70+80=210),
Y=3210; `leading3_exclusive` X=240 (d7+d8+d9=70+80+90=240), Y=3240 — both match the
hand-computed expectations exactly. The candidate mapping (`moving_sum([m], 0, N, [date])`)
still needs TS-side confirmation (Task 5) — no Verdict recorded here.

### C4 — live results

Same query as C1 (Query A1), plus Query A2 below. `all_amount` = 780 for every X row
(10+20+...+120 = 780) and 12780 for every Y row (1010+...+1120 = 12780) at all 12 day_index
values each — confirming `range: all` is scoped **per category**, not across the full 24-row
fixture (which would show 13560 = 780+12780 everywhere). This matches the brief's expectation,
so it is recorded as a **confirming observation**, not a discrepancy requiring escalation. Query
A2's `all_amount_check` (grouped at category-only grain) matches Query A1's per-row `all_amount`
exactly for both categories (780 / 12780) — no grain-dependent scope change observed. The
candidate mapping (`group_aggregate(...)`) still needs TS-side confirmation (Task 5) — no
Verdict recorded here.

### C5 — live results

Same query as C1 (Query A1). At day_index=6: `cumulative_amount` X=210 (d1..d6 =
10+20+30+40+50+60 = 210), Y=6210 (1010+1020+1030+1040+1050+1060 = 6210) — matches the
hand-computed running-total expectation exactly. The candidate mapping
(`cumulative_sum([m], [date])`) still needs TS-side confirmation (Task 5) — no Verdict recorded
here.

### C7 — live results

**Query A2:**
```sql
SELECT cat,
  MEASURE(balance_last)  AS balance_last,
  MEASURE(balance_first) AS balance_first,
  MEASURE(all_amount)    AS all_amount_check
FROM agent_skills.ts_dbx_substrate_pr1.rolling_mv
GROUP BY cat
ORDER BY cat
```

| cat | balance_last | balance_first | all_amount_check |
|---|---|---|---|
| X | 12 | 1 | 780 |
| Y | 112 | 101 | 12780 |

Matches the hand-computed expectation exactly: X's `balance` runs 1..12 across day_index 1..12,
so `last`=12 (day 12's balance), `first`=1 (day 1's balance); Y's `balance` runs 101..112, so
`last`=112, `first`=101. `all_amount_check` matches Query A1's `all_amount` exactly (see C4) —
no query-grain-dependent mismatch. This is the first live exercise of `semiadditive: first` in
the repo (previously only `last` was exercised, in `ts-to-databricks.md` Inventory Balance) —
confirms `first` parses and collapses correctly at category grain, same as `last`. TS-side
mapping confirmation (`first_value`) is Task 5's job — no Verdict recorded here.

### B1 — full result set (feeds C6, C6a)

**Query B1:**
```sql
SELECT cat, txn_month,
  MEASURE(month_amount)         AS month_amount,
  MEASURE(current_month_amount) AS current_month_amount,
  MEASURE(prior_month_amount)   AS prior_month_amount
FROM agent_skills.ts_dbx_substrate_pr1.period_mv
GROUP BY cat, txn_month
ORDER BY cat, txn_month
```

Executed live 2026-07-08 (current wall-clock month = July 2026; `period_fixture` dates resolved
to 2026-05-15 / 2026-06-15 / 2026-07-15):

| cat | txn_month | month_amount | current_month_amount | prior_month_amount |
|---|---|---|---|---|
| X | 2026-05-01 | 100 | 100 | NULL |
| X | 2026-06-01 | 200 | 200 | 100 |
| X | 2026-07-01 | 300 | 300 | 200 |
| Y | 2026-05-01 | 1100 | 1100 | NULL |
| Y | 2026-06-01 | 1200 | 1200 | 1100 |
| Y | 2026-07-01 | 1300 | 1300 | 1200 |

### C6 — live results

Comparing the X-category rows (2-mo-ago / 1-mo-ago / current-mo) against the three brief
hypotheses:

| Hypothesis | current: 2mo-ago | current: 1mo-ago | current: current-mo | prior: 2mo-ago | prior: 1mo-ago | prior: current-mo |
|---|---|---|---|---|---|---|
| (a) wall-clock-constant | 300 | 300 | 300 | 200 | 200 | 200 |
| (b) wall-clock-filtered | 0 | 0 | 300 | 0 | 200 | 0 |
| (c) row-relative | 100 | 200 | 300 | null/0 | 100 | 200 |
| **ACTUAL** | **100** | **200** | **300** | **NULL** | **100** | **200** |

**Hypothesis (c) — row-relative — matches exactly**, including the `NULL` (not 0) for the
out-of-range offset at the 2-months-ago row, consistent with Task 1's docs finding ("if the
shifted frame falls outside the available data, the measure evaluates to NULL"). Cat Y shows the
identical pattern +1000, as predicted by the brief.

**Verdict (DBX-only, decidable without Task 5): WRONG.** `range: current` (with or without
`offset`) is **row-relative to each output row's own period** (as ordered by the `order:`
dimension, `txn_month`) — it is **not** anchored to wall-clock `today()`. The existing C6 mapping
(`sum_if(diff_months([date], today())=N, [m])`) would produce hypothesis (a) or (b) shaped
output; neither matches the actual result. The documented mapping is wrong for any query
spanning more than the single current wall-clock period. Writing the corrected mapping (a
`LAG`/window-based per-period expression, not a wall-clock filter) into the docs is Task 6's
job — only the refutation is recorded here.

This also affects **C8** (deferred, inherits C6's verdict): Task 6 should re-examine C8's
month/quarter/year offset extrapolation once C6's mapping is rewritten, since C8 assumed the
same (now-refuted) wall-clock mechanism.

### C6a — live results

Same Query B1 and result set as C6 above — this is the query designed specifically to
discriminate the wall-clock-vs-row-relative ambiguity C6a raised.

**Verdict (DBX-only, live 2026-07-08): RESOLVED — row-relative.** Hypothesis (c) matches
exactly; hypotheses (a) and (b) are both refuted by the actual data (see the comparison table
under C6). This closes the ambiguity C6a flagged during plan research: Databricks' `range:
current [+ offset]` is a per-row, period-relative shift, not a wall-clock-`today()` filter.
TS-side comparison (Task 5) and the doc correction itself (Task 6) remain open.

---

## New claim surfaced during plan research (not in any backlog item — flag prominently)

| ID | Claim | Why suspect | Verification method |
|---|---|---|---|
| C6a | The existing C6 translation assumes Databricks' `range: current [+ offset]` is anchored to **wall-clock `today()`** (matching what `sum_if(..., today())` computes). An equally plausible reading — and the one that would make "monthly revenue" chart sensibly across a historical trend rather than going flat/zero outside the current wall-clock month — is that Databricks' `range: current` + `offset` is a **row-relative shift** (like `LAG`/`LEAD` relative to each output row's own `order:` period), independent of wall-clock date. These two readings (plus a third: wall-clock-anchored but only nonzero on the matching row, which is what `sum_if(...,today())` literally computes) produce different result *shapes* when queried across multiple periods — the worked example only ever queried a single snapshot, so it could not have distinguished them. | Live DBX Query B1 (Task 4) — 3-hypothesis table already designed; TS-side comparison (Task 5) — Actual (live): see `### C6a — live results` below — hypothesis (c) row-relative confirmed, resolving the ambiguity. Verdict (DBX-only, live 2026-07-08): **RESOLVED — row-relative**; wall-clock hypotheses (a) and (b) both refuted. TS-side comparison (Task 5) and doc correction (Task 6) still pending. |

### Docs-research notes (Task 1)

**C6a** — Task 1's docs research found that the `current` range is defined relative to "the
anchor row's value" (i.e., each output row in the query), not to wall-clock `today()`. This is
a data point consistent with — but not dispositive for — the row-relative hypothesis; it does
not by itself resolve the ambiguity, since `offset`'s interaction with that per-row anchor is
not spelled out in the docs (see the open questions list in
`2026-07-08-dbx-window-docs-findings.md`, which explicitly leaves "whether `offset` composes
with `range: trailing`/`leading`/`all`" — and, by extension, exactly how the anchor row and
`offset` interact for `range: current` — as unresolved). The wall-clock-vs-row-relative question
remains fully open for Task 4's Query B1 and Task 5's TS-side comparison.
