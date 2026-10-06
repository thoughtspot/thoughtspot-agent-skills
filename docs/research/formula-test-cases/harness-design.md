# Formula fidelity harness: design

**Goal.** Give each test case a source formula, input rows and an expected value from an oracle. Translate the formula, run the ThoughtSpot formula on the same rows, and compare. Today `ts formula translate --validate execute` proves only that the formula imports and returns *some* rows. This harness proves it returns the *right* value.

**Proposed home:** `tools/formula-fidelity/`, a sibling of `tools/ossie-roundtrip/`, with cases in `tools/formula-fidelity/cases/<source>/` and one LICENSE file per source directory. It reuses `ts_cli` code (the `formula_translate` scratch-Model lifecycle and the AgentQL client) rather than re-implementing it (`.claude/rules/ts-cli.md`). If it needs a new CLI verb, that verb is `ts formula verify` (later), not inline `requests`.

## 1. Test-case format (one JSONL line per case)

```json
{
  "id": "lo-date_time-networkdays-0003",
  "dialect": "excel",                       // excel|sheets|tableau|dax|qlik|sisense|snowflake|databricks|thoughtspot
  "formula": "=NETWORKDAYS(A1,B1,C1:C3)",
  "shape": "scalar",                        // scalar (one input row → one value) | aggregate (rows → one value) | grouped
  "inputs": {
    "row": {"A1": {"type":"DATE","v":"2012-10-01"}, "B1": {"type":"DATE","v":"2013-03-01"}},
    "range": {"C1:C3": {"type":"DATE","v":["2012-11-22","2012-12-04","2013-01-21"]}}
  },
  "expected": {"type":"INT","v":107},       // or {"type":"ERROR","v":"#DIV/0!"} / {"type":"NULL"} / {"type":"BLANK"}
  "tolerance": {"rel":1e-12},              // declared at authoring time, never widened after a failure
  "oracle": {"tier":"silver","by":"libreoffice-test-suite","engine_version":"core@<sha>",
             "cross_check":[{"tier":"bronze","by":"formulas 1.3.4","v":107}]},
  "session": {"week_start":"monday","tz":"UTC","date_system":1900},
  "provenance": {"source":"LibreOffice/core sc/qa/unit/data/functions/date_time/fods/networkdays.fods",
                 "row":4,"commit":"<sha>","licence":"MPL-2.0","retrieved":"2026-10-06"},
  "expect_translation": "direct",           // from the function map; lets the harness flag classification drift
  "known_divergence": null                  // or {"reason":"blank-as-zero","backlog":"BL-xxx"}: still run and still reported
}
```

Rules:
- `expected.type` is one of the canonical types: `INT | DOUBLE | DECIMAL | BOOL | STRING | DATE | DATETIME | NULL | BLANK | ERROR`. Excel serials become `DATE`/`DATETIME` at extraction, so the harness never compares raw serials.
- A case has exactly one oracle of record. Cross-checks are evidence only, and any disagreement among them puts the case in `quarantine/`.
- A **cases manifest** per source records the licence, the extraction script and its hash, and the counts. The extractor is committed; the downloaded originals are not.

## 2. Loading inputs into the warehouse

Each run uses one scratch schema (`FORMULA_FIDELITY_<run>`) and two generic tables, so the number of cluster objects stays constant however many cases there are:

| Table | Columns | Used by |
|---|---|---|
| `SCALAR_CASES` | `CASE_ID`, typed slots `N1..N6` (DOUBLE), `I1..I4` (NUMBER), `S1..S4` (VARCHAR), `D1..D4` (DATE), `T1..T2` (TIMESTAMP_NTZ), `B1..B2` (BOOLEAN) | scalar cases. Each cell reference maps to a slot |
| `RANGE_ROWS` | `CASE_ID`, `RANGE_ID`, `ROW_IDX`, `N`, `S`, `D`, `B` | aggregate cases (`SUM(K2:K6)` → `SUM(N) WHERE CASE_ID=… AND RANGE_ID=…`) |

- Load them with `ts load snowflake --source <manifest> --if-exists replace`, which is what the `ts-load-source-data` skill drives, against an existing profile (the memory note names the scratch schema `AGENT_SKILLS.PUBLIC` on se-thoughtspot; use a dedicated schema).
- An Excel **blank** is loaded as SQL NULL and flagged in the case (`inputs.*.blank=true`), so the comparison rules in §5 know about it.
- Registering in ThoughtSpot: `ts tables create` over the two tables, then one scratch Model per run (`ZZ_FIDELITY_<run>_DELETE_ME`) joining nothing: both tables, no joins, `CASE_ID` as an attribute.

## 3. Expected values (oracle step, offline)

The order of preference is gold, then silver, then bronze (`oracles.md`).
- **SQL dialects:** run the source expression in the warehouse over the same rows (`ts snowflake exec -q "SELECT CASE_ID, <expr> FROM SCALAR_CASES"`). This produces a gold value at the same moment the inputs are loaded.
- **Excel:** use the case's own silver/gold value, cross-checked by `formulas`, or by LibreOffice once installed. The cross-check runs on a generated workbook that contains *only our input cells* (no cached values).

This step needs no ThoughtSpot cluster, so it is the **per-PR, offline tier**. It can also act as an oracle-agreement gate: "the corpus still agrees with itself".

## 4. Translate, then run in ThoughtSpot

1. `ts formula translate '<formula>' --from <dialect> --columns @slotmap.json --name c_<case>` gives the ThoughtSpot expression, its `classification` and its `agentql_wrapper`.
   - For map-backed dialects (Excel, Sheets, Omni, Sigma) until the Excel translator lands: use the composition from the map via `--from thoughtspot`, labelled `hand-composed` in the report.
   - `NEEDS_REVIEW` / `unmappable` → verdict `UNAVAILABLE`. These cases count in the denominator, never as passes.
2. Batch up to ~50 translated formulas into the run's scratch Model with **one** `ts tml import --create-new`. If the batch import fails, bisect so one bad formula cannot take down the batch, and record that formula's import error as its `ERROR` verdict.
3. Per case, run one AgentQL query (`ts agentql fetch-data --model <guid>`):
   - scalar: `SELECT "CASE_ID", "c_<case>" FROM … WHERE "CASE_ID" = '<id>'`
   - aggregate: `SELECT AGG("c_<case>") FROM … WHERE "CASE_ID" = '<id>' AND "RANGE_ID" = '…'`

   **Known AgentQL traps** (from `docs/reviews/2026-10-06-formula-semantics-probes.md`):
   - Select an aggregate formula as `AGG("name")`. A semi-additive formula uses the `agentql_wrapper` the translator reports.
   - **Query one aggregate formula at a time.** Mixing a plain `SUM(col)` with several formula measures pushes the formulas into GROUP BY (`[ca_3] is not a valid group by expression`).
   - Columns come back by **ordinal**, not name, so position-map the SELECT.
   - A rejected query returns a non-`SUCCESS` status with exit code 0, so read `status`, not the exit code.
4. Also store `ts agentql generate-sql` output per case. When a case fails, the compiled SQL is the evidence for attribution: translator, ThoughtSpot compilation or warehouse.
5. **Teardown:**
   - `ts metadata delete` the Model and both Tables, then confirm each is absent with `ts metadata search` (the probe-record rule).
   - A GUID that cannot be confirmed deleted makes the run exit non-zero and lists the GUIDs.
   - Drop the scratch schema last.

   Add a startup sweep that finds orphans named `ZZ_FIDELITY_*_DELETE_ME` older than 24 hours and reports them.

## 5. Comparison rules

The verdicts reuse the SV study's vocabulary, plus two new ones:

| Verdict | Meaning |
|---|---|
| `EXACT` | equal under the canonical-type rules below |
| `NUMERIC_DIFF` | ran, numeric value outside tolerance. **Silent wrong** |
| `VALUE_DIFF` | ran, non-numeric value differs (string, date, bool). **Silent wrong** |
| `ERROR_EQUIV` | source gives an error value (`#DIV/0!`, `#NUM!`, SQL error) and ThoughtSpot gives NULL or a query error. Reported separately, never as `EXACT`; it is a semantic difference users can see |
| `NULL_VS_BLANK` | the case involves an Excel blank and the results differ only by blank-as-0 / blank-as-"" vs NULL propagation. Separate bucket, because it is a known class (Excel treats blanks as 0 in arithmetic, ThoughtSpot/SQL propagates NULL) and the fix is a translator `ifnull` decision, not noise |
| `ERROR` | import or query rejected by ThoughtSpot (loud) |
| `UNAVAILABLE` | translator declined (`NEEDS_REVIEW` / `unmappable`) |

Canonical comparison:
- **Numbers:** compare as `Decimal` with relative tolerance 1e-12 by default. A case may *declare* a looser bound at authoring time with a reason (e.g. statistical functions where Excel's documented precision is 15 significant digits). A failure is never fixed by widening the bound; that is the SV study's standing rule.
- **INT vs DOUBLE:** `3` equals `3.0`. ThoughtSpot's `round` returns INT64 for an integer increment, which is fine.
- **Booleans:** ThoughtSpot `true`/`false` vs Excel TRUE/FALSE. A numeric 1/0 is equal to a boolean only if the case says the source returns a number.
- **Dates:** compare as ISO dates. DATETIME is compared in UTC with an explicit session TZ. Excel serials are already converted.
- **Strings:** exact and case-sensitive. ThoughtSpot comparison *operators* are case-insensitive (BL-333), but returned values are not changed.
- **NULL:** `NULL == NULL` only when the expected value is `NULL`. An expected `""` vs an actual NULL is `NULL_VS_BLANK` if blanks are involved, otherwise `VALUE_DIFF`.
- **Grouped results:** sort both sides before comparing; row-count differences are `SHAPE_DIFF`.

## 6. Reverse direction (ThoughtSpot → source)

The same case store, run the other way:
- **Seed cases** are ThoughtSpot formulas: the live-verified rows of `agents/shared/schemas/thoughtspot-formula-patterns.md`, plus every *forward* translation that scored `EXACT`.
- **Oracle:** ThoughtSpot itself (`fetch-data` on the scratch Model), which is gold for this direction.
- **Translate:** use the to-direction emitters (`build-sv` formulas, the Databricks MV translator, and future `--to` paths).
  - SQL targets: execute the emitted SQL in the warehouse on the same tables. That is gold and cheap.
  - Excel/Sheets target: write the translated formula into a generated workbook over the same inputs and evaluate it with the bronze oracle. Label it bronze.
- **Round trip:** A (source) → B (ThoughtSpot) → C (source again), with the SV study's three-stage attribution. A≠B blames the from-translator, B≠C the to-translator, and A≠C is the headline.

## 7. Reporting

- Per run, `runs/<date>-<dialect>.json` holds per-case verdicts, compiled SQL, the translator version and the case-file hash. A markdown summary goes to `docs/reviews/<date>-formula-fidelity-<dialect>.md`.
- The summary leads with **silent-wrong** (`NUMERIC_DIFF` + `VALUE_DIFF`), then loud (`ERROR`), `ERROR_EQUIV`, `NULL_VS_BLANK`, `UNAVAILABLE`, and only then `EXACT`. This is the SV study's lesson: a single EXACT ratio hides the silent class. Each silent-wrong case names the function-map row it falsifies.
- Group results by function-map row, so a map row's "live-verified" claim can cite the case IDs.
- **Two-bucket exit** (`.claude/rules/repo-audit.md`): a recurring wrong class becomes a translator unit test (offline golden) and/or a validator. A one-off becomes a dated BL item.

## 8. Fit with angle 15

- Angle 15 today is operator-run and full-sweep only, with the Snowflake SV corpus as its only fixture. This harness adds a **formula-level fixture** that is cheaper and better oracled (every case carries an expected value), and it closes the study's qualification (1), "half the corpus cannot vouch for itself", for the formula slice.
- **Tiers:**
  - (a) per PR, offline: corpus integrity, extractor reproducibility, oracle agreement, and translator golden outputs, all with no cluster.
  - (b) on demand / full sweep: the live ThoughtSpot run.
  - (c) the SV/MV round trip stays the model-level fixture.
- `repo-audit.js` still has no angle-15 finder (finding 18.1), so this stays operator-run until one is added. The runbook should be a skill-like README, not prose in a review.

## 9. Cost

| Item | Per run |
|---|---|
| Warehouse objects | 1 schema + 2 tables (constant), XS warehouse for under a minute of loading and oracle queries |
| ThoughtSpot objects | 2 Tables + 1 Model per run, plus 1 Model per bisection when a batch import fails. All deleted and confirmed |
| AgentQL calls | 1 `fetch-data` + 1 `generate-sql` per case |

**Runtime per 100 cases: estimated 8–12 minutes.** This is extrapolated from the probe sessions, not measured. It assumes:
- ~2 batch imports at 10–20 s each
- 200 AgentQL calls at 2–3 s each, sequential, so ≈7–10 min
- teardown under 1 min

Running a few queries in parallel (if the cluster tolerates it; unverified) would cut this to roughly 3–4 minutes. 1,000 cases is roughly 1.5 hours sequential: fine for a full sweep, far too slow per PR.
