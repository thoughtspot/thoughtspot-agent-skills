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
- ThoughtSpot-side objects (Task 5): first attempt 2026-07-08 was **blocked** at table
  registration (see the historical BLOCKED subsections below, retained as diagnostic record);
  resolved 2026-07-09 when the user created a dedicated scratch connection **`DBX_DAMIAN`**
  (`b9e709c6-b951-4b50-a816-b450e6aee278`, OAUTH_WITH_SERVICE_PRINCIPAL, host
  `dbc-3472b2da-8a4e.cloud.databricks.com`, warehouse `c6ed539a60038b93` — same
  workspace + warehouse as Tasks 3–4 — exposing catalog `agent_skills`). Objects created
  2026-07-09, recorded here **for Task 9's cleanup** (`ts metadata delete` targets):
  - Table `PR1_ROLLING_FIXTURE` — `362a3f19-65df-41ac-ad27-432e7c66df10`
  - Table `PR1_PERIOD_FIXTURE` — `34141c51-59f9-4025-93a2-fe8d1dcb8c1d`
  - Model `PR1_Rolling_Window_Fixture` — `f7a0a352-40cf-4e68-ad7c-561f8664e5dc`
  - Model `PR1_Period_Window_Fixture` — `ae534e9e-6e67-41cb-9930-7a581d79cefe`

  (The `DBX_DAMIAN` connection itself is user-created scratch infrastructure — Task 9 should
  ask the user whether to remove it after the four objects above are deleted. Databricks-side
  `rolling_fixture`/`period_fixture`/`rolling_mv`/`period_mv` from Tasks 3–4 still need Task 9
  cleanup as originally planned.)

### Cleanup (Task 9, 2026-07-09)

- **Databricks:** `DROP SCHEMA IF EXISTS agent_skills.ts_dbx_substrate_pr1 CASCADE` executed via
  `databricks api post /api/2.0/sql/statements --profile ts-production` (warehouse
  `c6ed539a60038b93`) — `status.state: SUCCEEDED`. Confirmed with
  `SHOW SCHEMAS IN agent_skills LIKE 'ts_dbx_substrate_pr1'` → `total_row_count: 0`. This
  removes `rolling_fixture`, `period_fixture`, `rolling_mv`, and `period_mv` in one statement.
- **ThoughtSpot:** `ts metadata delete f7a0a352-40cf-4e68-ad7c-561f8664e5dc
  ae534e9e-6e67-41cb-9930-7a581d79cefe 362a3f19-65df-41ac-ad27-432e7c66df10
  34141c51-59f9-4025-93a2-fe8d1dcb8c1d --profile se-thoughtspot` (models before tables) →
  `{"deleted": [all 4 guids]}`. Confirmed with
  `ts metadata search --profile se-thoughtspot --name "PR1_%"` → `[]`.
- **`DBX_DAMIAN` connection:** left in place, untouched, per instruction (useful for PR 4's
  live e2e later) — confirmed still present via
  `ts metadata search --profile se-thoughtspot --name "DBX_DAMIAN" --type CONNECTION`
  (`isDeleted: false`).

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
| C1 | `range: trailing N day` (no modifier) → `moving_sum([m], N, 0, [date])` | `ts-from-databricks-rules.md:652-654`, `ts-databricks-formula-translation.md:280-282`, `ts-databricks-properties.md:97`; live-verified 2026-05-28 in `worked-examples/databricks/ts-from-databricks.md` (revenue_7d_rolling) **before** the `exclusive`-default was confirmed | Live DBX + TS number-match | See `### C1 — live results` below (Query A1, 24 rows) — day_index=6 matches the hand-computed exclusive-window arithmetic exactly. TS side: `### C1/C3 — TS-side number-match (Task 5)` below | **CORRECTED (live TS 2026-07-09)** — `moving_sum([m], N, 0, [date])` spans **N+1 rows (N preceding + anchor)** and reproduces DBX `trailing N day inclusive`, NOT the exclusive default. Fixes (both matched all 24 rows incl. boundary NULLs/partials): default/`exclusive` → `moving_sum([m], N, -1, [date])`; `inclusive` → `moving_sum([m], N-1, 0, [date])`. **Task 6 worked-example correction (2026-07-09):** `worked-examples/databricks/ts-from-databricks.md` `revenue_7d_rolling` (`trailing 7 day`, no modifier = exclusive) — old formula `moving_sum ( [TRANSACTIONS::unit_price] * [TRANSACTIONS::quantity] , 7 , 0 , [TRANSACTIONS::transaction_date] )` (reproduces `trailing 8 day inclusive`) corrected to new formula `moving_sum ( [TRANSACTIONS::unit_price] * [TRANSACTIONS::quantity] , 7 , -1 , [TRANSACTIONS::transaction_date] )` (reproduces `trailing 7 day` exclusive/default, matching the MV's declared window) — updated at lines ~317/335/494 and Key Patterns item 9 of that file. **2026-07-09 PR1.5 E1: verdict shown to be density-conditional; see 2026-07-09-dbx-semantic-claim-matrix.md** |
| C2 | Anchor default is `exclusive` for `trailing`/`leading` | `databricks-metric-view.md:452`, `ts-from-databricks-rules.md:574-581`, `ts-databricks-formula-translation.md:318-325` — all three say the same `moving_sum` equivalence in C1 "predates" this confirmation and "needs re-verification" | Live DBX (compare `trailing N day` vs. `trailing N day exclusive` vs. `trailing N day inclusive` on the same data) | See `### C2 — live results` below — `trailing3_default` == `trailing3_exclusive` and `leading3_default` == `leading3_exclusive` at all 24 rows, including matched boundary NULLs | **CONFIRMED** (live 2026-07-08, DBX-only — decidable without TS) |
| C3 | `range: leading N day` → candidate `moving_sum([m], 0, N, [date])` | `ts-from-databricks-rules.md:672-681`, `ts-databricks-formula-translation.md:297-307`, `databricks-metric-view.md:446` — all marked PENDING LIVE VERIFICATION | Live DBX + TS number-match | See `### C3 — live results` below — leading3_inclusive/exclusive match hand-computed values exactly at day_index=6. TS side: `### C1/C3 — TS-side number-match (Task 5)` below | **CORRECTED (live TS 2026-07-09)** — `moving_sum([m], 0, N, [date])` spans **N+1 rows (anchor + N following)** and matches neither DBX form (d6 X: 300 vs. excl 240 / incl 210). Fixes (both matched all 24 rows incl. boundary NULLs/partials): default/`exclusive` → `moving_sum([m], -1, N, [date])`; `inclusive` → `moving_sum([m], 0, N-1, [date])`. **2026-07-09 PR1.5 E1: verdict shown to be density-conditional; see 2026-07-09-dbx-semantic-claim-matrix.md** |
| C4 | `range: all` → candidate partition-wide `group_aggregate(...)` | `ts-from-databricks-rules.md:683-691`, `ts-databricks-formula-translation.md:309-316`, `databricks-metric-view.md:447` — all marked PENDING LIVE VERIFICATION | Live DBX + TS number-match | See `### C4 — live results` below — `all_amount`=780 (X) / 12780 (Y) at every row, confirmed **per-category**, not table-wide (would be 13560); Query A2 cross-check matches exactly. TS side: `### C4/C5/C7 — TS-side number-match (Task 5)` below | **CONFIRMED (live TS 2026-07-09)** — `group_aggregate(sum([m]), {[cat]}, query_filters())` returns 780 (X) / 12780 (Y) at every row-grain row AND at category grain, matching DBX exactly. (Note for Task 6: the fixture formula hard-codes the partition dim; the general emission rule for deriving the partition set from the MV query grain is a docs question, not a number question.) |
| C5 | `range: cumulative` → `cumulative_sum([m], [date])` | `ts-from-databricks-rules.md:666-670`, `ts-databricks-formula-translation.md:467-472`, `ts-databricks-properties.md:98` — not flagged PENDING but **never exercised in any worked example** | Live DBX + TS number-match | See `### C5 — live results` below — cumulative_amount matches hand-computed running total (210 / 6210) at day_index=6. TS side: `### C4/C5/C7 — TS-side number-match (Task 5)` below | **CONFIRMED (live TS 2026-07-09)** — `cumulative_sum([m], [date])` matches DBX `cumulative_amount` at **all 24 rows** (X d6=210, d12=780; Y d6=6210, d12=12780) |
| C6 | `range: current` + `offset: -N <unit>` (period filter) → `sum_if(diff_months/quarters/years([date], today())=N, [m])` | `ts-from-databricks-rules.md:620-631`, `ts-databricks-formula-translation.md:429-465`; live-verified 2026-05-25 in `worked-examples/databricks/ts-to-databricks.md` (Monthly/Prior Month Revenue) **but only ever queried at a single point in time, not across a multi-month trend** — see the wall-clock-vs-row-relative ambiguity below | Live DBX (3-hypothesis discriminator, Task 4 Query B1) + TS number-match | See `### B1 — full result set` and `### C6 — live results` below — Query B1 output matches hypothesis (c) row-relative exactly, refuting (a) and (b). TS side: `### C6/C6a — TS-side number-match (Task 5)` below | **CORRECTED (live TS 2026-07-09)** — the documented wall-clock `sum_if(diff_months([date], today())=N, [m])` mapping produces hypothesis-(b) output (X: 0/0/300 current, 0/200/0 prior) and FAILS to reproduce DBX's row-relative actual. The fix: `offset: -N` → **`moving_sum([m], N, -N, [date])`** (LAG(N) idiom; verified for N=1: NULL/100/200 (X), NULL/1100/1200 (Y) — exact match to DBX `prior_month_amount` incl. the out-of-range NULL); `range: current` with no offset → plain `sum([m])` at query grain (100/200/300 matches DBX `current_month_amount`). **Caveat (goes into the Task 6 doc rewrite): valid only with exactly one row per period in the order column** — general use needs a period-grain pre-aggregation. **Task 6 worked-example correction (2026-07-09):** `worked-examples/databricks/ts-to-databricks.md` Formula 5/6 (`Monthly Revenue`/`Prior Month Revenue`) and Key Patterns item 7 — the TS→Databricks `window: [{range: current, offset: -1 month}]` mapping for the source formula `sum_if(diff_months([date], today())=-1, [m])` is **unchanged** (still the closest available Databricks construct — DBX has no wall-clock primitive), but a caveat was added: this mapping only faithfully reproduces the source formula's wall-clock intent for a single-current-period snapshot query (the pattern actually live-tested on 2026-05-25); it diverges from the source formula's intent for a multi-period trend query, because the DBX side is row-relative. Old text presented the mapping as an unqualified equivalence; new text carries the caveat inline at Formula 5, Formula 6, and Key Patterns item 7. |
| C7 | `range: current`, `order:` raw date, `semiadditive: last/first` (true semi-additive) → `last_value`/`first_value(sum([m]), query_groups(), {[date]})` | `ts-from-databricks-rules.md:589-609`; `last` live-verified 2026-05-25 (`ts-to-databricks.md` Inventory Balance); **`first` never exercised in any worked example** | Live DBX + TS number-match (re-confirm `last`, newly confirm `first`) | See `### C7 — live results` below — Query A2: X→last=12/first=1, Y→last=112/first=101; matches hand-computed expectation exactly; first live exercise of `semiadditive: first`. TS side: `### C4/C5/C7 — TS-side number-match (Task 5)` below | **CONFIRMED (live TS 2026-07-09)** — `last_value(sum([m]), query_groups(), {[date]})` / `first_value(...)` at category grain return X→12/1, Y→112/101 — exact match to DBX Query A2 for both `last` and (first-ever live exercise) `first` |
| C8 | Offset at quarter/year grain (`-3 month`→quarter offset -1, `-1 year`→month offset -12) | `ts-from-databricks-rules.md:616-630`, `ts-databricks-formula-translation.md:433-438` — documented as symmetric extrapolations of C6, **never live-tested** (only `-1 month` was exercised in the worked example) | Documentation-only cross-check (Task 6) — not re-tested live; same underlying mechanism as C6, budget does not cover every grain | — | Deferred — C6 CORRECTED (2026-07-09): C8's wallclock sum_if extrapolations inherit the refutation and must be rewritten against the row-relative moving_sum(m,N,-N,d) fix; see Task-6 note under C6 live results |
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

### C1, C3, C4, C5, C7 — TS-side attempt (Task 5, 2026-07-08) — BLOCKED (resolved 2026-07-09 via dedicated connection DBX_DAMIAN)

> **Historical record.** The blocker below was resolved on 2026-07-09: the user created a
> dedicated scratch connection `DBX_DAMIAN` exposing `agent_skills`, sidestepping the
> `add-tables` 500 entirely (no connection-update call needed). The diagnostic is retained
> because the `updateConnectionV2` 500 and the missing-`authenticationType` gap in
> `ts_cli/commands/connections.py::add_tables()` are tracked as **BL-095** in
> `docs/backlog.md`. The
> actual TS-side results are in `### C1/C3 — TS-side number-match (Task 5)` and
> `### C4/C5/C7 — TS-side number-match (Task 5)` below.

Task 5 first ran live against ThoughtSpot profile `se-thoughtspot` on 2026-07-08 to build the
`PR1_Rolling_Window_Fixture` Model and number-match the candidate `moving_sum` /
`group_aggregate` / `cumulative_sum` / `last_value`/`first_value` formulas against the Query
A1/A2 actuals above. **The attempt stopped at table registration (brief Step 2) — no Model
was ever imported and no SpotQL query ran**, so C1/C3/C4/C5/C7 have no TS-side result to
record. Details:

**Connection discovery (brief Step 1):** `ts connections list --profile se-thoughtspot --type
DATABRICKS` returned 11 connections. None is named after this project; the host each points
to had to be cross-checked via `ts tml export {id}` (the `connection.properties[].host`
field) against the `Production` Databricks profile's host
(`dbc-3472b2da-8a4e.cloud.databricks.com`, from `~/.claude/databricks-profiles.json`, the
same profile Tasks 3–4 used). Exactly one connection matches:
**`dl-databricks`** (`5e7a6105-aaa6-42d7-88cd-21b62e496bd7`, `PERSONAL_ACCESS_TOKEN` auth,
`http_path: /sql/1.0/warehouses/6a882f6a859e0002` — a different SQL warehouse than Task 3/4's
`c6ed539a60038b93`, same workspace/metastore). This is **not an idle connection**: `ts
connections get` / `connection/search` with `include_details: true` shows it is owned by
`denise.lee`, last modified 2026-06-12, with several existing production tables registered
(`dim_retapp_products`, `dim_retapp_stores`, `dl_fact_retapp_sales_current`, …) — i.e. a
colleague's live connection with unrelated real content on it, not a throwaway test
connection.

**Registration failure:** `agent_skills` is not in `dl-databricks`'s `selected_databases`
(only `["samples", "hive_metastore"]`), so `ts tables create` failed immediately with
`Database with name: agent_skills does not exist in connection: dl-databricks` (expected —
the table's warehouse database must be registered on the connection first). The documented
fix, `ts connections add-tables {id}`, failed on every attempt with a generic 500:

```
ThoughtSpot API 500 on POST https://se-thoughtspot-cloud.thoughtspot.cloud/api/rest/2.0/connections/5e7a6105-aaa6-42d7-88cd-21b62e496bd7/update
{"error":{"message":{"debug":{"code":10000,"incident_id_guid":"...","trace_id_guid":"tracing-disabled","debug":"[null]"}}}}
```

Per `.claude/rules/api-research.md`, queried `mcp__SpotterCode__get-rest-api-reference
(apiName: "updateConnection")` before further live probing, which surfaced
`updateConnectionV2` (`POST /api/rest/2.0/connections/{id}/update`, 10.4.0.cl+) and a spec
detail `ts-cli`'s `add_tables()` doesn't send: *"If the `authentication_type` is anything
other than SERVICE_ACCOUNT, you must explicitly provide the `authenticationType` property in
the payload — otherwise the API defaults to SERVICE_ACCOUNT."* `ts_cli/commands/
connections.py::add_tables()` omits `authenticationType` entirely, so for a
`PERSONAL_ACCESS_TOKEN` connection like `dl-databricks` the backend silently treats the
request as SERVICE_ACCOUNT — a plausible cause of a server-side error. To test this without
editing `tools/ts-cli/` (out of scope for this task — live-work rules restrict edits to this
file), a scratch script in the task's scratchpad dir reused `ts_cli.client.ThoughtSpotClient`
+ `resolve_profile` (no manual auth/token handling) to add the missing
`authenticationType: "PERSONAL_ACCESS_TOKEN"` field, with and without `validate: true`. Both
variants still 500'd with the same generic `code: 10000` / `debug: "[null]"` body — no more
informative than the original. **The same call against `revult_dbx_connection`** (a
different, `SERVICE_ACCOUNT`-authenticated Databricks connection, whose stored hierarchy
`ts connections get` *does* return successfully, proving that connection itself is healthy)
**also 500'd**, with default (correct) `authenticationType`. Four payload variants × two
differently-configured, independently-healthy connections, uniform generic 500 — this points
to a backend/instance-level defect in `updateConnectionV2` on this ThoughtSpot Cloud build,
not a fixable client-payload bug and not something specific to `dl-databricks`.

**Why this is BLOCKED rather than worked around:** (1) `ts connections create` is explicitly
disallowed by the brief (wrong auth model — key-pair vs. this profile's PAT/OAuth — and "do
not create unilaterally"); (2) reconstructing a full `configuration` block to retry the update
with `validate: true` would require resending `dl-databricks`'s real Databricks credentials,
which the API never exposes (TML export and `connection/search` both redact the token to
`""`/`"******"`) — guessing or blanking that field risks corrupting a colleague's live,
in-use connection, so this was not attempted; (3) `dl-databricks` already carries unrelated
production tables owned by another engineer — continuing to probe its `update` endpoint
beyond the diagnostics above was judged an unacceptable risk to someone else's live setup;
(4) editing `tools/ts-cli/` to fix the missing `authenticationType` is the correct long-term
fix (flagging as a candidate BL item below) but is out of scope for this task's live-work
rules. No table, model, or other object was created in ThoughtSpot for C1/C3/C4/C5/C7 — every
attempt failed before any create/import call, so there is nothing to record as a GUID and
nothing for Task 9 to clean up on the ThoughtSpot side for the rolling-window Model.

**Follow-up recommendation (not filed as a BL item by this task — Task 6/backlog owner's
call):** (a) fix `ts_cli/commands/connections.py::add_tables()` to send `authenticationType`
matching the connection's own auth type; (b) even with that fix, re-verify the endpoint
against a connection this session hasn't already spent its shared-resource budget on, ideally
with the connection owner's awareness, since the uniform 500 across two connections suggests
the fix alone may not be sufficient; (c) ask the user whether a scratch Databricks connection
should be created (via the ThoughtSpot UI, by someone with `CAN_CREATE_OR_EDIT_CONNECTIONS`)
specifically for PR1-style live substrate work, rather than reusing colleagues' production
connections for future tasks like this one.

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

### C6/C6a — TS-side attempt (Task 5, 2026-07-08) — BLOCKED (resolved 2026-07-09 via dedicated connection DBX_DAMIAN)

> **Historical record** — same resolution as the C1/C3/C4/C5/C7 BLOCKED section above. The
> actual TS-side C6/C6a results are in `### C6/C6a — TS-side number-match (Task 5)` below.

Task 5 initially planned to build the `PR1_Period_Window_Fixture` Model with the two wallclock
`sum_if(diff_months(...)=N, ...)` candidates plus, per the brief's decision tree (Databricks
resolved to hypothesis (c) row-relative, so the wallclock candidates were expected to FAIL),
the row-relative correction candidate `moving_sum([PR1_PERIOD_FIXTURE::amount], 1, -1,
[PR1_PERIOD_FIXTURE::txn_date])`. **None of this ran** — the blocker is identical to, and
upstream of, the one documented in `### C1, C3, C4, C5, C7 — TS-side attempt (Task 5) —
BLOCKED` above: `PR1_PERIOD_FIXTURE` could not be registered on the one ThoughtSpot connection
(`dl-databricks`) that points at the Task 3/4 Databricks workspace, because `ts connections
add-tables` (`POST /api/rest/2.0/connections/{id}/update`) 500s uniformly regardless of
payload shape or which connection is targeted. See that section for the full diagnostic
(connection discovery, the `authenticationType` spec gap found via
`get-rest-api-reference(apiName: "updateConnection")`, and the corrected-payload retry that
still 500'd against two independently-healthy connections).

**Consequence for C6/C6a (as assessed on 2026-07-08):** the DBX-side verdicts already recorded
above (C6: **WRONG**, C6a: **RESOLVED — row-relative**) were unaffected — both were decided
entirely from the Databricks side per Task 4. What remained PENDING at the time was the
TS-side half: confirming that `moving_sum([m], 1, -1, [date])` reproduces the row-relative
shape. **That confirmation ran on 2026-07-09 and passed** — see `### C6/C6a — TS-side
number-match (Task 5)` below; the C6 verdict is now CORRECTED with the verified fix.

---

## TS-side number-match results (Task 5, live 2026-07-09)

All queries below ran live on 2026-07-09 against `se-thoughtspot`, connection `DBX_DAMIAN`,
models `PR1_Rolling_Window_Fixture` (`f7a0a352-40cf-4e68-ad7c-561f8664e5dc`) and
`PR1_Period_Window_Fixture` (`ae534e9e-6e67-41cb-9930-7a581d79cefe`), against the same
Databricks fixture tables Tasks 3–4 used (`agent_skills.ts_dbx_substrate_pr1.*`).

**Execution-path note (affects how the queries were run, not the numbers):** the SpotQL
endpoints (`/callosum/v1/v2/data/spotql/generate-sql` / `fetch-data`) return a bare,
empty-body **HTTP 500 for any payload on this se-thoughtspot build** — including an empty
request body, which a live handler would reject as a structured 400 — so `ts spotql
fetch-data` was unusable (its output normalises to `status: UNKNOWN`). `ts spotql
classify-columns --model` works fine (it classifies from exported TML; no server SpotQL
dependency) and confirmed the expected AGG-wrapping classification for every formula column.
Data was fetched via the stable v2 **`POST /api/rest/2.0/searchdata`** endpoint (spec
confirmed via `get-rest-api-reference(apiName: "searchData")`) with search-token queries,
through a scratchpad script that reuses `ts_cli.client.ThoughtSpotClient` for auth — the
documented open-items-style exception in `.claude/rules/ts-cli.md`, since ts-cli has no
`searchdata` command yet. Two search-token findings worth keeping: date bucketing must be
forced with `[Txn Date].'daily'` (bare `[Txn Date]` auto-buckets monthly; the unquoted
`.daily` form is rejected), and the query grain must include **only** `Cat` + the date —
adding `Day Index` would enter the window partition (ThoughtSpot partitions window formulas
by all query dims except the ORDER-BY attrs) and collapse every window to a single row.

**Import iterations (rolling model):** 2 content iterations + 1 planned in-place update.
(1) First import failed with `Mixing aggregated (moving_sum(...)) and non aggregated (amount)
tokens are not supported` on the `Trail N=3/4 minus current` candidates — fixed by wrapping
the bare column: `... - sum([PR1_ROLLING_FIXTURE::amount])`. (2) Second import succeeded.
(3) After the first result set showed the offset semantics (below), the model was updated
in place (guid at document root) to add three direct-window correction candidates. The period
model imported first-try. Unrelated tooling note: `ts tml import --file` **hangs forever when
run with an open non-TTY stdin** (e.g. a background shell) — `_stdin_has_piped_content()` in
`tools/ts-cli/ts_cli/commands/tml.py:182` blocks on `sys.stdin.read()`; workaround is
`< /dev/null`, candidate ts-cli fix for the Task 8 backlog entry.

### C1/C3 — TS-side number-match (Task 5)

Search query: `[Cat] [Txn Date].'daily' [Amount] [Trail N=2] [Trail N=3] [Trail N=4]
[Trail N=3 minus current] [Trail N=4 minus current] [Lead (0,3)] [Lead (0,4)] [Lead (-2,3)]
[Lead (-3,3)] [Cumulative] [All (LOD candidate)]` — 24 rows returned; then a second pass with
the three direct-window candidates added. Full X-category TS result (Y is the identical
pattern with the +1000 base, matching DBX):

| Txn Date | Amount | Trail N=2 | Trail N=3 | Trail N=4 | Trail N=3 minus cur | Trail N=4 minus cur | Lead (0,3) | Lead (0,4) | Lead (-2,3) | Lead (-3,3) | Trail excl (3,-1) | Lead excl (-1,3) | Lead incl (0,2) | Cumulative | All (LOD) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 06-01 | 10 | 10 | 10 | 10 | 0 | 0 | 100 | 150 | 70 | 40 | NULL | 90 | 60 | 10 | 780 |
| 06-02 | 20 | 30 | 30 | 30 | 10 | 10 | 140 | 200 | 90 | 50 | 10 | 120 | 90 | 30 | 780 |
| 06-03 | 30 | 60 | 60 | 60 | 30 | 30 | 180 | 250 | 110 | 60 | 30 | 150 | 120 | 60 | 780 |
| 06-04 | 40 | 90 | 100 | 100 | 60 | 60 | 220 | 300 | 130 | 70 | 60 | 180 | 150 | 100 | 780 |
| 06-05 | 50 | 120 | 140 | 150 | 90 | 100 | 260 | 350 | 150 | 80 | 90 | 210 | 180 | 150 | 780 |
| 06-06 | 60 | 150 | 180 | 200 | 120 | 140 | 300 | 400 | 170 | 90 | 120 | 240 | 210 | 210 | 780 |
| 06-07 | 70 | 180 | 220 | 250 | 150 | 180 | 340 | 450 | 190 | 100 | 150 | 270 | 240 | 280 | 780 |
| 06-08 | 80 | 210 | 260 | 300 | 180 | 220 | 380 | 500 | 210 | 110 | 180 | 300 | 270 | 360 | 780 |
| 06-09 | 90 | 240 | 300 | 350 | 210 | 260 | 420 | 420 | 230 | 120 | 210 | 330 | 300 | 450 | 780 |
| 06-10 | 100 | 270 | 340 | 400 | 240 | 300 | 330 | 330 | 120 | NULL | 240 | 230 | 330 | 550 | 780 |
| 06-11 | 110 | 300 | 380 | 450 | 270 | 340 | 230 | 230 | NULL | NULL | 270 | 120 | 230 | 660 | 780 |
| 06-12 | 120 | 330 | 420 | 500 | 300 | 380 | 120 | 120 | NULL | NULL | 300 | NULL | 120 | 780 | 780 |

**Candidate PASS/FAIL vs. the DBX Query A1 targets** (trailing3 default/excl = 120, incl =
150; leading3 default/excl = 240, incl = 210 at day 6 X; full-column comparison across all
24 rows):

| TS candidate | Day-6 X value | Matches DBX column | Full 24-row match incl. boundaries |
|---|---|---|---|
| `Trail N=2` = `moving_sum(m, 2, 0, d)` | 150 | `trailing3_inclusive` | **PASS — all 24 rows** (d1=10, never NULL — same as DBX inclusive) |
| `Trail N=3` = `moving_sum(m, 3, 0, d)` | 180 | — (spans 4 rows: d3..d6) | FAIL — matches nothing; closest: inclusive (150, off by +30) |
| `Trail N=4` = `moving_sum(m, 4, 0, d)` | 200 | — (spans 5 rows) | FAIL |
| `Trail N=3 minus current` | 120 | `trailing3_default/exclusive` **except boundary** | PARTIAL — matches interior + partial-window rows but returns **0, not NULL** at d1 (DBX: NULL). Superseded by the direct form below |
| `Trail N=4 minus current` | 140 | — | FAIL |
| **`Trail excl (3,-1)` = `moving_sum(m, 3, -1, d)`** | **120** | **`trailing3_default` = `trailing3_exclusive`** | **PASS — all 24 rows**, incl. NULL at d1 and partial sums at d2 (10) / d3 (30) |
| `Lead (0,3)` = `moving_sum(m, 0, 3, d)` | 300 | — (spans 4 rows: d6..d9) | FAIL — closest: exclusive (240, off by +60) |
| `Lead (0,4)` = `moving_sum(m, 0, 4, d)` | 400 | — | FAIL |
| `Lead (-2,3)` = `moving_sum(m, -2, 3, d)` | 170 | — (rows +2..+3 only) | FAIL |
| `Lead (-3,3)` = `moving_sum(m, -3, 3, d)` | 90 | — (single row +3, LEAD(3)) | FAIL |
| **`Lead excl (-1,3)` = `moving_sum(m, -1, 3, d)`** | **240** | **`leading3_default` = `leading3_exclusive`** | **PASS — all 24 rows**, incl. NULL at d12 and partial sums at d11 (120) / d10 (230) |
| **`Lead incl (0,2)` = `moving_sum(m, 0, 2, d)`** | **210** | **`leading3_inclusive`** | **PASS — all 24 rows** (d12=120, never NULL — same as DBX inclusive) |

**Semantics settled by this grid:** ThoughtSpot's `moving_sum(m, start, end, d)` window
**always includes the anchor row when the [start, end] offset range covers offset 0** — so
`(N, 0)` spans N+1 rows (N preceding + anchor), which is DBX **inclusive** semantics for a
window of N+1... i.e. `moving_sum(m, N, 0, d)` ≡ `trailing (N+1) day inclusive`, NOT
`trailing N day` (default/exclusive). This resolves the C1-flagged ambiguity between
`thoughtspot-formula-patterns.md:326-334`'s offset table and
`ts-databricks-formula-translation.md`'s "N preceding + current" phrasing: **both were
right about TS behaviour; the repo's DBX mapping was wrong** because DBX's default is
exclusive-of-anchor. The corrected general mappings (all verified at every row of the
fixture, both categories, including boundary NULL/partial behaviour, which also matches
DBX's partial-window rule exactly):

| DBX Metric View range | Corrected TS formula |
|---|---|
| `trailing N day` (default) / `trailing N day exclusive` | `moving_sum([m], N, -1, [date])` |
| `trailing N day inclusive` | `moving_sum([m], N-1, 0, [date])` |
| `leading N day` (default) / `leading N day exclusive` | `moving_sum([m], -1, N, [date])` |
| `leading N day inclusive` | `moving_sum([m], 0, N-1, [date])` |

### C4/C5/C7 — TS-side number-match (Task 5)

`Cumulative` (`cumulative_sum([m], [date])`) and `All (LOD candidate)`
(`group_aggregate(sum([m]), {[cat]}, query_filters())`) are in the 24-row table above:
`Cumulative` matches DBX `cumulative_amount` at **every row** (X: 10/30/60/100/150/210/280/
360/450/550/660/780; Y: +1000 pattern to 12780) — **C5 CONFIRMED**. `All (LOD)` = 780 for
every X row / 12780 for every Y row, per-category exactly as DBX — **C4 CONFIRMED** at row
grain.

Category-grain query (mirror of DBX Query A2): `[Cat] [Balance Last] [Balance First]
[All (LOD candidate)]`:

| Cat | Balance Last | Balance First | All (LOD) |
|---|---|---|---|
| X | 12 | 1 | 780 |
| Y | 112 | 101 | 12780 |

Exact match to DBX Query A2 (X: 12/1/780, Y: 112/101/12780) — **C7 CONFIRMED** for both
`semiadditive: last` → `last_value(sum([m]), query_groups(), {[date]})` and
`semiadditive: first` → `first_value(...)`; and the C4 grain cross-check matches (780/12780
at category grain = the same values as every row-grain row, mirroring DBX's grain-stable
behaviour).

### C6/C6a — TS-side number-match (Task 5)

Search query (period model): `[Cat] [Txn Date].'monthly' [Amount] [Current Month (wallclock
candidate)] [Prior Month (wallclock candidate)] [Prior Month (row-relative candidate)]` —
6 rows:

| Cat | Month | Amount | Current Month (wallclock) | Prior Month (wallclock) | Prior Month (row-relative) |
|---|---|---|---|---|---|
| X | 2026-05 | 100 | 0 | 0 | NULL |
| X | 2026-06 | 200 | 0 | 200 | 100 |
| X | 2026-07 | 300 | 300 | 0 | 200 |
| Y | 2026-05 | 1100 | 0 | 0 | NULL |
| Y | 2026-06 | 1200 | 0 | 1200 | 1100 |
| Y | 2026-07 | 1300 | 1300 | 0 | 1200 |

Comparison against DBX Query B1's actual (`current_month_amount` = 100/200/300,
`prior_month_amount` = NULL/100/200 for X; +1000 for Y):

- `sum_if(diff_months([date], today())=0, [m])` → 0/0/300 — the hypothesis-(b) wall-clock
  shape, exactly as the brief's decision tree predicted. **FAIL** vs. DBX actual.
- `sum_if(diff_months([date], today())=-1, [m])` → 0/200/0 — hypothesis (b). **FAIL.**
- **`moving_sum([m], 1, -1, [date])`** → NULL/100/200 (X), NULL/1100/1200 (Y) — **exact
  match** to DBX `prior_month_amount`, **including the NULL (not 0) at the out-of-range
  first row** (mirroring the Task 1 docs finding and the DBX actual).
- The plain `Amount` measure at this grain (100/200/300) matches DBX `current_month_amount`
  exactly — i.e. `range: current` with **no** offset is simply the per-period aggregate.

**C6 verdict: CORRECTED** with `moving_sum([m], N, -N, [date])` for `offset: -N <unit>`
(verified at N=1) and plain `sum([m])` for offset-less `range: current`. **Caveat carried
into the Task 6 doc rewrite:** the `moving_sum` LAG idiom shifts by *rows*, not periods —
it is only correct when the query returns exactly one row per period in the order column
(true for this fixture, per `thoughtspot-formula-patterns.md:314`'s LAG(1) idiom notes);
the general emission needs a period-grain pre-aggregation or an explicit statement of this
precondition. **C6a: TS-side comparison complete** — the row-relative reading is confirmed
reproducible on the ThoughtSpot side; the ambiguity is fully closed on both platforms.

---

## New claim surfaced during plan research (not in any backlog item — flag prominently)

| ID | Claim | Why suspect | Verification method |
|---|---|---|---|
| C6a | The existing C6 translation assumes Databricks' `range: current [+ offset]` is anchored to **wall-clock `today()`** (matching what `sum_if(..., today())` computes). An equally plausible reading — and the one that would make "monthly revenue" chart sensibly across a historical trend rather than going flat/zero outside the current wall-clock month — is that Databricks' `range: current` + `offset` is a **row-relative shift** (like `LAG`/`LEAD` relative to each output row's own `order:` period), independent of wall-clock date. These two readings (plus a third: wall-clock-anchored but only nonzero on the matching row, which is what `sum_if(...,today())` literally computes) produce different result *shapes* when queried across multiple periods — the worked example only ever queried a single snapshot, so it could not have distinguished them. | Live DBX Query B1 (Task 4) — 3-hypothesis table already designed; TS-side comparison (Task 5) — Actual (live): see `### C6a — live results` below — hypothesis (c) row-relative confirmed, resolving the ambiguity. Verdict (DBX-only, live 2026-07-08): **RESOLVED — row-relative**; wall-clock hypotheses (a) and (b) both refuted. TS-side comparison (Task 5, live 2026-07-09): **CONFIRMED** — the wallclock `sum_if` candidates reproduce hypothesis (b) (not the DBX actual), and the row-relative `moving_sum([m], 1, -1, [date])` candidate reproduces DBX's actual exactly (see `### C6/C6a — TS-side number-match (Task 5)` below). **Doc correction (Task 6) complete 2026-07-09** — see the C6 row's Task 6 correction note above and the rewritten Period Filter sections in `ts-from-databricks-rules.md` / `ts-databricks-formula-translation.md` / `ts-databricks-properties.md`. |

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

---

## `fields:`/`dimensions:` alias re-check (BL-064 #2, Task 6 Step 7)

Re-checked 2026-07-09 — **clean**. Grepped `fields:`/`dimensions:` across
`ts-databricks-properties.md`, `ts-databricks-formula-translation.md`,
`ts-from-databricks-rules.md`, and `databricks-metric-view.md`. Every occurrence is
consistent with the current rule (`fields:` is the GA-canonical key, `dimensions:`
is the accepted legacy alias, `fields:` checked first):

- `ts-from-databricks-rules.md:38` states the rule directly and correctly.
- `databricks-metric-view.md:214-217` (added at GA, 2026-04) documents the rule in
  full, reiterated inline as a comment on the `dimensions:` key at both schema
  examples (single-source and multi-source with joins).
- `ts-databricks-properties.md:1` currency-anchor comment references the
  `fields:`/`dimensions:` synonym as already-confirmed; no body content restates it
  incorrectly.
- `ts-databricks-formula-translation.md` has no `fields:`/`dimensions:` occurrences
  at all — not applicable.

One minor staleness fixed in passing (not a "`dimensions:`-only" correctness bug,
just an outdated cross-reference): `databricks-metric-view.md`'s "Version 0.1 —
Single Source (legacy)" intro note (originally lines 98-100) said the `fields:`
alias was "tracked in BL-032" as a forward-looking item, even though the alias is
already fully documented later in the same file (lines 214-217, added when GA
landed). Reworded to point at the existing documentation instead of implying it
was still outstanding. No `dimensions:`-only stragglers found — BL-064 #2 remains
FIXED with fresh evidence.

---

## Task 6 scope note — TS→Databricks direction (`ts-to-databricks-rules.md`, `ts-convert-to-databricks-mv/SKILL.md`)

Not in Task 6's original file list (which covers the `from`-direction skill and the
shared schema/mapping/properties files), but discovered while correcting those
files: `agents/shared/mappings/ts-databricks/ts-to-databricks-rules.md` contained
the identical pre-2026-07-09 wrong/pending claims (C1: `moving_sum(m, N, 0, d)` ↔
`trailing N day`; C6: wall-clock `sum_if(..., today())` ↔ `window`/`offset`; a
`range: leading` PENDING LIVE VERIFICATION note). **Fixed 2026-07-09** as part of
this task, since it is a shared mapping file in the same directory carrying the
mirror-direction claims of the files already corrected above — see its Window
Measures Classification, Period-Filter Measures, and Rolling Window Measures
sections.

**Deferred:** `agents/cli/ts-convert-to-databricks-mv/SKILL.md` (the sibling skill
to `ts-convert-from-databricks-mv`, used for the reverse TS → Databricks
direction) has the same wrong/pending claims duplicated inline (Concept Mapping
table lines ~45-54, decision tree/examples ~lines 592-736, and a changelog entry
at 1.0.2 describing the PENDING flag). This is a separate skill with its own
version/changelog outside Task 6's scope — flagging here for a follow-up PR
(candidate `BL-NNN`) rather than fixing unilaterally, since correcting it also
requires a version bump per `.claude/rules/versioning.md`.

**Update 2026-07-09:** fixed in this same PR (commit a2bb05d, skill v1.0.3) — no follow-up needed.
