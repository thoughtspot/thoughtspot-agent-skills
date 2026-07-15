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
| F1 | HIGH | correctness | Base row count came from `model_tables[0]` (a dim, no fact join) → garbage compression. **Fixed (part a: fact-anchored base_rows + tests)**; sanity-guard + internal-SpotQL fix remain |
| F6 | LOW (was HIGH) | robustness | INVALIDATED as a bug — the crash was a malformed test candidate (`date_grains` as strings); real bucketed candidates work. Residual: add input-shape validation |
| F8 | MED | correctness | Hard-coded `DOUBLE` for every sum; `SUM(int)`=INT64 → registration failed. **FIXED** — component types now read from base Table TMLs (+ tests) |
| F9 | CRITICAL | capability+UX | Aggregates never route unless the PRIMARY's measures are formulas; skill doesn't detect/warn |
| F3 | HIGH | capability | Candidate generator only emits single-dimension additive grains |
| F5 | HIGH | capability (reuse) | Semi-additive & ratio measures silently dropped, though `measures.py`/`classify-columns` already classify them |
| F12 | HIGH | capability | Role-playing date columns + column-name routing: date aggregates must key on the column users query (or the conformed shared date) |
| F4 | MED | capability | No "one wide table vs N narrow" combine analysis (the highest-value decision, done fully by hand) |
| F15 | MED | correctness/UX | Emits stored components as hidden model columns; should be formula-only over physical cols (also blocks in-place edit) |
| F10/11/13 | MED | verification | **CORRECTED**: SpotQL *does* verify routing incl. semi-additive; Step 7 must pick the wrapper (`AGG` vs `SUM`) via `classify-columns`; its hardcoded `SUM("Sales")` example is wrong for aggregate-formula measures |
| F14 | MED | verification | RLS leak-test (restricted user) not run — routed queries so far ran as bypass admin (open-item #17) |
| F2 | MED | packaging | `ts` uv-tool env lacks `snowflake-connector-python`; connected profiling dies with a bare ImportError |
| F16 | LOW | UX | Model naming is source-first; UI truncation hides the aggregate token |
| F17 | LOW | UX | Aggregate models ship with no description |
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
- *Remaining:* (b) sanity guard — warn + mark `suspect` when `base_rows` < max(agg_rows);
  (c) fix the internal SpotQL construction so profiling stops falling back to the walker.
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

**F9 — primary measures must be formulas (CRITICAL).**
- *Root cause:* routing fires only for formula measures (open-item #0); the skill builds
  aggregates over plain measure columns that can never be routed to, and never says so.
- *Fix (SKILL.md + a preflight in `commands/aggregate.py`):* at `recommend`, classify each
  target measure on the primary via `spotql classify-columns`; if a targeted measure is a
  `raw_measure` (plain column, no aggregating formula), FLAG it and offer the promotion
  transform (plain measure column → formula measure `sum([physical])`, preserving name /
  synonyms / description). Add a `ts aggregate preflight` (or fold into recommend) that reports
  routing-eligibility per measure. Document the promotion as a required step with a backup.
- *Tests:* classifier flags a raw measure; promotion transform round-trips (same values,
  formula measure out).
- *Verify live:* already proven this run — promoting Amount/Quantity flipped routing on.

**F10/11/13 — Step 7 verification method (CORRECTED).**
- *Truth:* `ts spotql generate-sql` DOES reflect routing, including semi-additive, when the
  measure is referenced with the right wrapper. `classify-columns` returns it:
  `raw→SUM`, `aggregate_measure→AGG`, `semiadditive_measure→SUM`.
- *Fix (SKILL.md Step 7):* (1) replace the hardcoded `SUM("Sales")` example with a
  classify-columns-driven wrapper choice per measure; (2) give worked examples for all three
  kinds; (3) keep Search Data API + QUERY_HISTORY as an optional deeper check, not the primary.
- *Tests:* Step-7 helper picks `AGG` for an aggregate-formula measure, `SUM` for semi-additive.
- *Verify live:* done — `SUM("Inventory Balance")`→B, `AGG("Amount")`→A, both SUCCESS.

**F14 — RLS leak-test.**
- *Fix (SKILL.md Step 7 + open-item #17):* require a routed query as a restricted (non-bypass)
  user and confirm returned rows obey the rule; only then mark RLS "enforced", else report
  "attached but unverified". Needs a `{restricted_user_profile}`.
- *Verify live:* outstanding for this deployment (see §4).

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

### Theme D — UX / output  [F16, F17]
- **F16:** name `<Aggregate> (<Source Model>)` (aggregate-first) in `_aggregate_model_name`.
- **F17:** auto-generate a `description` (grain, measures, what routes / what falls back, RLS).

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
   delete the old models. Verify routing after (SpotQL with `AGG`/`SUM` wrappers).
2. **Apply naming** (F16): "Sales by Customer & Product (Dunder Mifflin Sales & Inventory)" and
   "Monthly Sales & Inventory (Dunder Mifflin Sales & Inventory)".
3. **Apply descriptions** (F17).
4. **RLS leak-test** (F14): run a routed query as a restricted user; confirm row filtering.
