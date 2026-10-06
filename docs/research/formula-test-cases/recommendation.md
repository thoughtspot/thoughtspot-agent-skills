# Recommendation: where to start

The sources are ranked by expected-value coverage × licence safety × extraction effort. The figures come from `sources.md`, and these licence verdicts are an engineering reading that still needs legal sign-off before anything is vendored.

| Rank | Source | Why | Licence verdict | Effort |
|---|---|---|---|---|
| 1 | **LibreOffice Calc function tests** (`sc/qa/unit/data/functions`) | 8,605 cases with literal expected values (measured). About 3,100 use only functions the Excel map classifies `direct`, which is exactly what the Excel translator emits | MPL-2.0: **copyable as separate MPL-licensed fixture files** (file-level copyleft). Keep them out of anything bound for apache/ossie | Medium: fods XML, OpenFormula→Excel syntax, input cells → rows |
| 2 | **Apache POI test spreadsheets** | The only corpus whose values were **computed by real Excel** (gold): 1,170 cached cells plus 641 hand-checked rows (measured) | Apache-2.0: **copy freely** with NOTICE | Low (xlsx); legacy implicit-intersection cases need filtering |
| 3 | **Snowflake / Databricks as their own oracle**, plus **Apache Spark function examples and golden files** | Gold values at no licence risk: we author the case and the warehouse computes the answer. Spark contributes about 1,000–1,500 CI-verified examples as Databricks seeds | Spark: Apache-2.0, **copy**. Self-authored cases: ours | Low: `ts snowflake exec` already exists |
| 4 | **formula.js tests** | 2,444 hand-written expectations (measured); a second opinion for Excel | MIT: **copy** with notice | Medium: rewrite function calls as formulas |
| 5 | **TPC-H/TPC-DS via Snowflake sample data** | Aggregate- and join-level oracle; complements the SV study | TPC EULA: **do not vendor**; run the queries in place | Low, once the share is confirmed |

**Do not copy:**
- Microsoft support Excel examples, which are restricted to non-commercial use under the Terms of Use.
- Google, Tableau, Qlik, Snowflake and Databricks documentation, and dax.guide, which are all rights reserved.
- The Microsoft Learn DAX pages. Their public CC-BY repo now returns 404, so the licence cannot be confirmed.
- `formulas` (EUPL), pycel (GPL) and HyperFormula (GPL/commercial; its test suite is private).

Use these only to decide *what* to test, then author the inputs and let an oracle compute the expected value. The clean-room practice itself also needs a legal OK.

**Oracle feasibility, tested on this machine:**
- `formulas` 1.3.4 runs in a throwaway uv environment.
  - On my 28-formula workbook it matched 26. The two misses: `0.1+0.2=0.3` returns FALSE where Excel returns TRUE, and YEARFRAC basis 1 is wrong.
  - Against POI's Excel-cached workbook it agrees on 1,033 of 1,273 cells. Most disagreements are legacy implicit intersection or `#NAME?` for unimplemented functions.
  - That makes it usable as a bronze cross-check, never as the oracle of record.
- pycel cannot evaluate 9 of the 28 formulas and breaks on Python 3.14. Not recommended.
- LibreOffice is **not installed** and was not tried. Installing it, or running it in a CI container, is a user decision. When it is set up, force recalculation on load.

## First milestone

**M1: 250 Excel cases with expected values, run end to end on se-thoughtspot.**
- **Cases:**
  - 200 from LibreOffice `date_time`, `text`, `mathematical` and `logical`. Restrict them to functions the Excel map marks `direct`, use scalar shape only, and exclude error-argument cases.
  - 50 from POI's Excel-cached `FormulaEvalTestData` (scalar, no ranges). These are the gold anchor, so if LibreOffice and Excel disagree we see it.
- **Cross-check:** run every case through `formulas` and quarantine any disagreement.
- **Translation:**
  - Use the Excel translator if it has landed.
  - Otherwise use the map compositions validated with `--from thoughtspot`, labelled hand-composed.
- **Scale:** one scratch Model, deleted and confirmed. About 25 minutes of AgentQL.
- **Success means** a report that leads with the silent-wrong count. Each wrong case should name the Excel-map row it falsifies.

**M0 (prerequisite, about one day):** the same harness on **50 self-authored Snowflake SQL cases** with Snowflake as the gold oracle. This proves the plumbing (load, translate, batch import, AgentQL, teardown, compare) on a dialect that already has a translator, before any third-party corpus is involved.

**M2:** extend to LibreOffice `statistical`, using aggregate-shaped cases and the `RANGE_ROWS` loader, plus Spark→Databricks seeds. Then add the reverse direction for the SQL dialects.
