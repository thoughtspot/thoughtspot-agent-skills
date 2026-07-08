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

- Catalog: `TBD`
- Schema: `TBD`
- Fixture table(s): `TBD`
- Metric View(s): `TBD`
- Row counts / date range: `TBD`

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
| C1 | `range: trailing N day` (no modifier) → `moving_sum([m], N, 0, [date])` | `ts-from-databricks-rules.md:652-654`, `ts-databricks-formula-translation.md:280-282`, `ts-databricks-properties.md:97`; live-verified 2026-05-28 in `worked-examples/databricks/ts-from-databricks.md` (revenue_7d_rolling) **before** the `exclusive`-default was confirmed | Live DBX + TS number-match | — | — |
| C2 | Anchor default is `exclusive` for `trailing`/`leading` | `databricks-metric-view.md:452`, `ts-from-databricks-rules.md:574-581`, `ts-databricks-formula-translation.md:318-325` — all three say the same `moving_sum` equivalence in C1 "predates" this confirmation and "needs re-verification" | Live DBX (compare `trailing N day` vs. `trailing N day exclusive` vs. `trailing N day inclusive` on the same data) | — | — |
| C3 | `range: leading N day` → candidate `moving_sum([m], 0, N, [date])` | `ts-from-databricks-rules.md:672-681`, `ts-databricks-formula-translation.md:297-307`, `databricks-metric-view.md:446` — all marked PENDING LIVE VERIFICATION | Live DBX + TS number-match | — | — |
| C4 | `range: all` → candidate partition-wide `group_aggregate(...)` | `ts-from-databricks-rules.md:683-691`, `ts-databricks-formula-translation.md:309-316`, `databricks-metric-view.md:447` — all marked PENDING LIVE VERIFICATION | Live DBX + TS number-match | — | — |
| C5 | `range: cumulative` → `cumulative_sum([m], [date])` | `ts-from-databricks-rules.md:666-670`, `ts-databricks-formula-translation.md:467-472`, `ts-databricks-properties.md:98` — not flagged PENDING but **never exercised in any worked example** | Live DBX + TS number-match | — | — |
| C6 | `range: current` + `offset: -N <unit>` (period filter) → `sum_if(diff_months/quarters/years([date], today())=N, [m])` | `ts-from-databricks-rules.md:620-631`, `ts-databricks-formula-translation.md:429-465`; live-verified 2026-05-25 in `worked-examples/databricks/ts-to-databricks.md` (Monthly/Prior Month Revenue) **but only ever queried at a single point in time, not across a multi-month trend** — see the wall-clock-vs-row-relative ambiguity below | Live DBX (3-hypothesis discriminator, Task 4 Query B1) + TS number-match | — | — |
| C7 | `range: current`, `order:` raw date, `semiadditive: last/first` (true semi-additive) → `last_value`/`first_value(sum([m]), query_groups(), {[date]})` | `ts-from-databricks-rules.md:589-609`; `last` live-verified 2026-05-25 (`ts-to-databricks.md` Inventory Balance); **`first` never exercised in any worked example** | Live DBX + TS number-match (re-confirm `last`, newly confirm `first`) | — | — |
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

## New claim surfaced during plan research (not in any backlog item — flag prominently)

| ID | Claim | Why suspect | Verification method |
|---|---|---|---|
| C6a | The existing C6 translation assumes Databricks' `range: current [+ offset]` is anchored to **wall-clock `today()`** (matching what `sum_if(..., today())` computes). An equally plausible reading — and the one that would make "monthly revenue" chart sensibly across a historical trend rather than going flat/zero outside the current wall-clock month — is that Databricks' `range: current` + `offset` is a **row-relative shift** (like `LAG`/`LEAD` relative to each output row's own `order:` period), independent of wall-clock date. These two readings (plus a third: wall-clock-anchored but only nonzero on the matching row, which is what `sum_if(...,today())` literally computes) produce different result *shapes* when queried across multiple periods — the worked example only ever queried a single snapshot, so it could not have distinguished them. | Live DBX Query B1 (Task 4) — 3-hypothesis table already designed; TS-side comparison (Task 5) |

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
