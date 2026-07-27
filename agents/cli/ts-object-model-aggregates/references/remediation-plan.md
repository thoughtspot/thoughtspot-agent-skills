# Aggregate Advisor — Remediation Design & Plan

Derived from one end-to-end build (2 aggregates on "Dunder Mifflin Sales & Inventory",
a live aggregate-aware cluster). Findings log: `PROCESS_FINDINGS.md` (F1–F17). This plan turns each
finding into a concrete change in `ts-object-model-aggregates` (SKILL.md) and/or `ts-cli`
(`ts_cli/aggregate/*`), with root cause, fix, target files, tests, and verification.

Repo conventions honoured: changes land on a `wip/agg-advisor-hardening` branch → PR to
main; every CLI change gets unit tests in `tools/ts-cli/tests/`; live-verified items move to
VERIFIED in `references/open-items.md`; version bump at PR time.

---

## 1. Finding inventory (corrected)

| ID | Severity | Category | One-line |
|----|----------|----------|----------|
| F1 | HIGH | correctness | Base row count came from `model_tables[0]` (a dim, no fact join) → garbage compression. **Fixed (part a: fact-anchored base_rows + tests)**; sanity-guard + internal-AgentQL fix remain |
| F6 | LOW (was HIGH) | robustness | INVALIDATED as a bug — the crash was a malformed test candidate (`date_grains` as strings); real bucketed candidates work. Residual: add input-shape validation |
| F8 | MED | correctness | Hard-coded `DOUBLE` for every sum; `SUM(int)`=INT64 → registration failed. **FIXED** — component types now read from base Table TMLs (+ tests) |
| F9 | CRITICAL | capability+UX | Aggregates inert unless PRIMARY measures are formulas. **ADDRESSED** — `recommend` now emits `routing_ineligible_measures`; SKILL.md 5a preflight gate + promotion instructions (optional: codify promotion as a CLI cmd) |
| F3 | HIGH | capability | Candidate generator only emits single-dimension additive grains |
| F5 | HIGH | capability (reuse) | Semi-additive & ratio measures silently dropped, though `measures.py`/`classify-columns` already classify them |
| F12 | HIGH | capability | Role-playing date columns + column-name routing: date aggregates must key on the column users query (or the conformed shared date) |
| F4 | MED | capability | No "one wide table vs N narrow" combine analysis (the highest-value decision, done fully by hand) |
| F15 | MED | correctness/UX | Emits stored components as hidden model columns; should be formula-only over physical cols (also blocks in-place edit) |
| F10/11/13 | MED | verification | **CORRECTED**: AgentQL *does* verify routing incl. semi-additive; Step 7 must pick the wrapper (`AGG` vs `SUM`) via `classify-columns`; its hardcoded `SUM("Sales")` example is wrong for aggregate-formula measures |
| F14 | MED | verification | RLS leak-test (restricted user) not run — routed queries so far ran as bypass admin (open-item #17) |
| F2 | MED | packaging | `ts` uv-tool env lacks `snowflake-connector-python`; connected profiling dies with a bare ImportError |
| F16 | LOW | UX | **FIXED** — model name is now aggregate-first `<aggregate> (<source>)` |
| F17 | LOW | UX | **FIXED** — `generate` auto-writes a description (grain, measures, routing, RLS) |
| F7 | — | POSITIVE | RLS fail-closed guard + rule remap works; keep as the model for other guards |

---

## 2. Design by theme

### Theme A — Correctness bugs (unblock the tool)  [F1, F6, F8]

**F1 — base row count misattributed to `model_tables[0]`. Part (a) FIXED this branch.**
- *Root cause:* `sqlgen.build_base_count_sql` did `COUNT(*) FROM model_tables[0]` with NO
  fact join — arbitrary export order put an 8-row dimension (DM_CATEGORY) first, so
  `base_rows=8` and every compression ratio was garbage.
- *Fix (DONE):* new `sqlgen.base_table_name(model_tml)` resolves the measure-owning fact
  (plain measure `column_id` table, or formula measure's `[TABLE::col]` ref; most measures
  wins; falls back to `model_tables[0]`). `build_base_count_sql` now anchors on it. Unit
  tests: dim-listed-first and formula-measure cases both assert the fact, not the dim.
- *Part (b) DONE:* `commands/aggregate.flag_suspect_base_rows` warns + sets
  `base_rows_suspect` when `base_rows < max(agg_rows)` (an aggregate can't exceed its base),
  in both connected and manual profile paths (unit-tested).
- *Remaining (c):* fix the internal AgentQL construction so profiling stops falling back to
  the walker (needs live repro of why generate-sql returned QUERY_GEN_ERROR per candidate).
- *Verify live (on skill re-run):* re-profile; base must be ~1.2M, not 8.

**F6 — INVALIDATED (operator error, not a tool bug). Downgraded HIGH → LOW.**
- *What actually happened:* the crash came from a malformed injected candidate —
  `date_grains: ['MONTHLY']` (list of strings) instead of the real
  `[{'column','bucket'}]` shape `recommend` emits. `generate._grain_columns` does
  `g['column']`, so a bare string raised `TypeError: string indices must be integers`
  (and the RLS path likewise choked on the malformed shape).
- *Verified offline:* correctly-shaped bucketed candidates AND the `date_column`/`bucket`
  compat shim both pass `_grain_columns` cleanly. The monthly path is not blocked.
- *Residual (LOW):* the tool raises a bare `TypeError`/`AttributeError` on a malformed
  candidate dict. Optional hardening: validate `date_grains` shape at the `generate`
  entry and raise a clear `ValueError` naming the offending candidate.
- *Tests:* a malformed-shape candidate raises a clear validation error, not a bare TypeError.

**F8 — measure sum types. FIXED this branch.**
- *Root cause:* `generate` hard-coded `DOUBLE` for every SUM/MIN/MAX component (only COUNT
  was INT64), but `SUM(integer)` stays integer in the warehouse → `ts tables create` failed
  the CDW type check (`DataType DOUBLE does not match ... quantity_sum`).
- *Fix (DONE, `aggregate/generate.py` + threaded `table_tmls` through `commands/aggregate.py`):*
  model MEASURE columns carry no `data_type`, but the base Table TMLs do — new
  `_measure_source_type()` resolves each component's source physical column (plain measure
  `column_id`, or a formula measure's `[TABLE::col]` ref) and reads its type from the base
  Table TML. SUM/MIN/MAX preserve the source type; COUNT stays INT64; DOUBLE fallback when
  `table_tmls` is absent (backward compatible).
- *Tests (DONE):* SUM(int)→INT64, SUM(double)→DOUBLE, formula-measure source resolution, and
  the no-table_tmls fallback.
- *Verify live (on skill re-run):* register a table with an integer measure, no manual patch.

### Theme B — Verification is trustworthy  [F9, F10/11/13, F14]

**F9 — primary measures must be formulas (CRITICAL). ADDRESSED this branch.**
- *Root cause:* routing fires only for formula measures (open-item #0); the skill built
  aggregates over plain measure columns that can never be routed to, and never said so.
- *Fix (DONE):* `recommend` now folds in `commands/aggregate.routing_ineligible_measures`
  (reuses `spotql_ops.classify_model_columns`) and emits `routing_ineligible_measures`
  `[{measure, reason, remedy}]` in candidates.json + stdout. SKILL.md Step 5a adds a
  preflight GATE: if non-empty, stop and promote each plain measure to a formula
  (`sum([physical])`, same name/synonyms) with a backup, before generating. Unit-tested
  (flags only raw_measure; empty when all formulas).
- *Optional follow-up:* codify the promotion transform as a `ts` command (done by hand /
  SKILL.md prose for now).
- *Verified live:* promoting Amount/Quantity flipped routing on (2026-07-15).

**F10/11/13 — Step 7 verification method (CORRECTED).**
- *Truth:* `ts agentql generate-sql` DOES reflect routing, including semi-additive, when the
  measure is referenced with the right wrapper. `classify-columns` returns it:
  `raw→SUM`, `aggregate_measure→AGG`, `semiadditive_measure→SUM`.
- *Fix (DONE, SKILL.md Step 7 rewritten):* Step 7 now runs `ts agentql classify-columns`
  first and references each measure with the right wrapper (raw→SUM, aggregate_measure→AGG,
  semiadditive→SUM); the wrong `SUM("Sales")` example is gone; Search Data API +
  QUERY_HISTORY noted as an optional deeper check.
- *Tests:* Step-7 helper picks `AGG` for an aggregate-formula measure, `SUM` for semi-additive.
- *Verify live:* done — `SUM("Inventory Balance")`→B, `AGG("Amount")`→A, both SUCCESS.

**F14 — RLS leak-test. Procedure DONE; live run still owed.**
- *Fix (DONE, SKILL.md Step 7):* the leak-test query now uses the correct wrapper; procedure
  requires a routed query as a restricted (non-bypass) user, confirming rows obey the rule
  before marking RLS "enforced" (else "attached but unverified"). Needs `{restricted_user_profile}`.
- *Verify live:* still owed on the skill re-run (open-item #17).

### Theme C — Capability (the value gap; all designs done by hand this run)  [F3, F5, F12, F4, F15]

**F3 — multi-dimension candidates.**
- *Fix (`aggregate/lattice.py`, `scoring.py`):* generate multi-dim rollups (combinations of
  co-queried dimensions), not only single-dim; rank them in the same marginal-gain curve.

**F5 — semi-additive & ratio measures (reuse, not new knowledge).**
- *Root cause:* `measures.py` already classifies SUM/MIN/MAX/COUNT/AVG/ratio and
  `spotql_ops.classify_expr` already tags `semiadditive_measure`; the lattice just doesn't
  consume them, so those measures are dropped from candidates.
- *Fix:* wire `measures.py` rewrite plans into `lattice`/`generate` so:
  - *semi-additive* (`last_value(sum(col),…,{date})`) → store month-end component
    (`last_value … OVER (PARTITION BY period,dims ORDER BY date …)`) + emit formula
    `last_value(sum([component]),query_groups(),{[date col]})`. (Pattern proven this run.)
  - *ratio* (`safe_divide(sum(a),sum(b))`) → store `a_sum`,`b_sum` components + emit the ratio
    formula over them (routing then works because the outer op is a formula).

**F12 — role-playing / conformed date columns.**
- *Root cause:* routing matches column names; a model may expose several date columns
  (`Order Date`, `Balance Date`) plus a shared conformed date (`Transaction Date` = the date
  dim). A single date aggregate can only route for the column it exposes.
- *Fix (`lattice.py` + SKILL.md):* detect role-playing dates (multiple model date columns
  resolving to one shared `DM_DATE_DIM` key). Rule: if the target measures span facts that
  share the conformed date (e.g. sales + inventory), key the aggregate on the **conformed**
  date column and set `date_aggregation_info` on it; if a measure is only ever queried by its
  role-specific date, key on that. Warn when a requested combined grain can't satisfy
  column-name routing.

**F4 — combine-vs-split analysis.**
- *Fix (`scoring.py` + SKILL.md Step 5):* after single-/multi-dim candidates, compute the
  combined-grain row count and compare total scan cost of 1 wide table vs N narrow ones;
  surface functional-dependency collapses (e.g. Customer Name → State) that make extra columns
  free. Present as an explicit "consolidation" recommendation.

**F15 — formula-only model emission.**
- *Fix (`aggregate/generate.build_aggregate_model_tml`):* emit formulas over the physical
  component column (`sum([TABLE::amount_sum])`) with NO hidden component model column — matching
  the primary's own pattern. Cleaner UI and avoids the in-place-edit "deleted columns have
  dependents" trap. (Import of the formula-only shape confirmed live this run.)
- *Verify:* confirm routing still fires on the formula-only shape (measure identity is the
  formula name, unchanged) before adopting.

### Theme D — UX / output  [F16, F17] — DONE
- **F16 (DONE):** `_write_model_artifact` names the model `<aggregate> (<source>)`
  (aggregate-first) so the distinguishing token survives UI truncation.
- **F17 (DONE):** `_aggregate_description()` auto-writes a description (grain via
  `_grain_summary`, measures, routing behaviour, RLS note) onto the aggregate Model TML.
  Both unit-tested; `_grain_summary` tolerates malformed date-grain shapes (F6 lesson).

### Theme E — Packaging  [F2]
- Add a `snowflake` extra (`thoughtspot-cli[snowflake]`); on ImportError in
  `ts aggregate profile`, print the exact `uv tool install thoughtspot-cli --with
  snowflake-connector-python` remedy.

### Keep  [F7]
- RLS fail-closed + rule-remap is the reference pattern; extend the same rigor to CLS
  (currently a manual gate) as a follow-up.

---

## 3. Sequencing

- **Phase 0 — unblock (correctness + packaging):** F1, F6, F8, F2. Small, high-confidence, each
  with a unit test + one live re-check on Dunder Mifflin.
- **Phase 1 — trustworthy verification:** F9 (preflight + promotion), F10/11/13 (Step-7 rewrite
  using classify-columns), F14 (leak-test procedure). Makes the skill stop over-claiming.
- **Phase 2 — capability:** F5 (wire existing measure classification), F3 (multi-dim), F12
  (conformed/role date), F4 (combine analysis), F15 (formula-only emission). The big value; do
  F5 + F15 first (mostly wiring existing pieces), then F3/F12/F4.
- **Phase 3 — UX:** F16, F17.

Each phase = its own PR. Live re-verification on the aggregate-aware cluster is the merge gate
(open-items.md items flip to VERIFIED).

---

## 4. This deployment — finish-up items (separate from the skill work)

The two aggregates are built and routing-verified, but to match the three refinements:
1. **Recreate A & B formula-only** (F15) — the in-place update is blocked; recreate fresh
   (formula over physical component, no component columns), re-patch primary with new GUIDs,
   delete the old models. Verify routing after (AgentQL with `AGG`/`SUM` wrappers).
2. **Apply naming** (F16): "Sales by Customer & Product (Dunder Mifflin Sales & Inventory)" and
   "Monthly Sales & Inventory (Dunder Mifflin Sales & Inventory)".
3. **Apply descriptions** (F17).
4. **RLS leak-test** (F14): run a routed query as a restricted user; confirm row filtering.

---

## 5. Phase 2 progress (branch feat/agg-advisor-phase2 — live-validated 2026-07-15)

**DONE + LIVE-VALIDATED** on the aggregate-aware cluster (full recommend→profile→generate→
route re-run of Dunder Mifflin):
- **F5-ratio** — `safe_divide(sum,sum)` now decomposed; the ratio measure generates a routable
  `safe_divide(sum([num]),sum([den]))` aggregate. Live: Average Revenue Per Unit routes to the
  aggregate with exact numbers.
- **_resolve physical-path fix** — a measure component's `source_column` is often a physical
  `TABLE::COL` path (any formula measure; a ratio's num/den); `_resolve` now accepts it. Without
  this every candidate covering a formula measure was skipped during profiling.
- **F8 per-component typing** — each component typed from its OWN `source_column` (ratio den of
  an int column → INT64), not the measure's first ref. Live: table registered with no manual patch.
- **Re-validated live** (all already merged via #244): F1(a) base_rows=1,208,243 not 8; F1(b)
  guard; F2 connector; F9 routing_ineligible; F16 naming; F17 description; F10/11/13 generate-sql
  routing via classify-columns wrappers. Profiler now yields the correct compression ranking
  automatically.

**REMAINING (not done — deferred as higher-risk / needs careful supervised work):**
- **F5-semi-additive** (`last_value(...)`, e.g. Inventory Balance) — **SAFE SLICE DONE
  (recognize + surface + recipe); full auto-generation DEFERRED.** measures.classify_measure now
  classifies it `SEMIADDITIVE` (decomposable=False → stays correctly excluded from candidates, no
  wrong-number risk); `recommend` surfaces it under `semiadditive_measures` with a pointer to the
  hand-build recipe (`references/semiadditive-recipe.md`, verified live: month-end pattern +
  mandatory 3,828 numeric gate). **Why auto-gen is deferred:** the AgentQL-compiler-reuse shortcut
  does NOT work — AgentQL has no date-bucket fn (build_spotql groups by raw date) and
  `wrap_as_ddl` buckets with a PLAIN re-aggregation, but a period-end snapshot needs a *window*
  (`last_value OVER (PARTITION BY grain ORDER BY date)`) neither layer emits. Full auto-generation
  therefore requires a new windowed-DDL generator — real, wrong-numbers-sensitive work, left as a
  backlog item to do only if it recurs enough to justify the risk.
- **F3 multi-dim** — `lattice._merge_similar_dimsets` only unions dim-sets with jaccard≥0.5
  (overlap); disjoint single-dims never combine. Add a consolidated-union candidate per date-col
  group, BUT guard multi-fact join feasibility (a naive union can mix facts with no join path,
  e.g. Amount×BalanceDate) — cap to dims reachable from the measures' fact.
- **F12 conformed date**, **F4 combine-vs-split**, **F1(c)** AgentQL fallback root cause,
  **F14** restricted-user RLS leak-test (needs a non-bypass profile).
