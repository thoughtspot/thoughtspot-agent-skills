# Candidate sources of formula test cases with expected values

Research date 2026-10-06. Counts marked **measured** come from downloading and parsing the files (scripts in `docs/research/formula-test-cases/scripts/`, downloads in `dl-*/`). Counts marked **estimated** were not parsed. Licence text is quoted from the source where I could reach it. **None of this is legal advice.** Each "may we copy" verdict is an engineering reading for an Apache-2.0-licensed repo and should get a legal check before anything is vendored.

## Summary table

| # | Source | Licence | Copy into Apache-2.0 repo? | Dialect | Cases (measured/est.) | With expected values | Extraction effort |
|---|---|---|---|---|---|---|---|
| 1 | LibreOffice `sc/qa/unit/data/functions/*/fods` | MPL-2.0 | **Yes, with conditions** (keep as MPL files) | Excel / OpenFormula | **9,563 measured** in 452 files | **8,605 literal** (rest computed in-sheet) | Medium |
| 2 | Apache POI `test-data/spreadsheet` | Apache-2.0 | **Yes** (keep NOTICE) | Excel (values cached by real Excel) | **~1,936 measured** (1,295 + 641) | ~1,810 | Low–medium |
| 3 | Apache Spark function examples + `sql-tests` golden files | Apache-2.0 | **Yes** (keep NOTICE) | Spark SQL ≈ Databricks SQL | est. 1,000–1,500 examples (370 measured in 3 files) + 221 golden `.sql.out` files | all (CI-verified) | Low |
| 4 | formula.js / @formulajs tests | MIT | **Yes** (keep copyright notice) | Excel (function-call form) | **2,444 `expect()` measured** in 8 files | all (hand-written) | Medium |
| 5 | Python `formulas` test workbooks | EUPL-1.1 | **No** (copyleft, incompatible) — use as a tool only | Excel | ~5,480 formula cells measured in `test.xlsx` | ~5,480 cached | n/a |
| 6 | pycel test fixtures | GPL-3.0 | **No** | Excel | not counted | — | n/a |
| 7 | HyperFormula | GPL-3.0 or proprietary | **No**, and the suite is private | Excel | — | — | n/a |
| 8 | xlcalculator `tests/resources` | MIT (tokenizer parts under other licences) | Probably yes, check per file | Excel | 67 workbooks, not counted | not checked | Medium |
| 9 | Microsoft Excel support "Example" tables | Microsoft Terms of Use | **No** | Excel | est. ~1,500 (≈3 per function × ~500) | nearly all | Medium (scrape) |
| 10 | Google Sheets help pages | © Google, ToS | **No** | Sheets | few: "Sample usage" has no results | ~0 | — |
| 11 | Microsoft Learn DAX reference | historically CC-BY-4.0, now **unverifiable** | **Not now**: treat as all rights reserved | DAX | est. a few hundred EVALUATE examples with result tables | most | Medium |
| 12 | dax.guide (SQLBI) | "© SQLBI, all rights reserved" | **No** | DAX | est. hundreds | many | — |
| 13 | Tableau function reference | © Salesforce | **No** | Tableau | est. ~100 inline `= result` examples | ~100 | Low |
| 14 | Qlik help | "© QlikTech… All rights reserved" | **No** | Qlik | est. hundreds; results are in prose or result tables | many | Medium |
| 15 | Snowflake / Databricks SQL docs | "© Snowflake, Inc. All Rights Reserved"; Databricks similar | **No** | SQL | est. thousands, with output tables | most | Medium |
| 16 | TPC-H / TPC-DS answer sets | TPC EULA | **No.** Run the queries in the warehouse instead | SQL | 22 / 99 queries | answer sets at SF1 | Low (already in Snowflake sample data) |
| 17 | Superstore (Tableau sample) | no open licence found | **No.** Use our own load | Tableau | — | known totals vary by version | — |
| 18 | OASIS OpenFormula (ODF 1.2 Part 2) | OASIS notice (permissive) | Yes, but there is nothing to copy | OpenFormula | **0**: the final spec has no test tables | — | — |

## Details

### 1. LibreOffice Calc function tests (best by volume)
- **URL / owner:** https://github.com/LibreOffice/core/tree/master/sc/qa/unit/data/functions — The Document Foundation / LibreOffice contributors.
- **Licence:** MPL-2.0 (`COPYING.MPL` at the repo root; the README says "LibreOffice is an integrated office suite based on copyleft licenses"; GitHub reports GPL-3.0 because of a top-level COPYING file, so the per-file situation should be confirmed). MPL §3.3: *"You may create and distribute a Larger Work under terms of Your choice, provided that You also comply with the requirements of this License for the Covered Software."*
- **Verdict:** **Yes, with conditions.** MPL-2.0 is file-level copyleft. Extracted fixture files are derived from Covered Software, so they stay under MPL-2.0: put them in their own directory with an MPL-2.0 LICENSE and a provenance header, and publish any modifications to them as MPL. The rest of the repo stays Apache-2.0. Never contribute these files to an ASF project such as apache/ossie: ASF policy lists MPL as Category B (binary only).
- **Format:** flat ODS XML (`.fods`). Sheet2 has the columns `Function | Expected | Correct | FunctionString | Comment`, and input data sits in the same sheet, usually columns K onward. The LibreOffice CppUnit test (`sc/qa/unit/functions_test.cxx`) recalculates every file and asserts `Sheet1.B3 == 1`, which is the AND of all the `Correct` cells.
- **Counts (measured):** 452 files across 10 categories: statistical 3,554, spreadsheet 1,449, mathematical 1,405, financial 1,093, text 972, date_time 492, information 156, logical 139, database 100, array 203. That is **9,563 cases, 8,605 with a literal expected value** and ~427 distinct leading functions. Against the repo's Excel map: **~3,100 cases use only `direct` functions**, ~700 involve a `passthrough` function, ~980 a `structural` one, and ~3,660 use a function the map does not row.
- **Extraction:** parse the XML with the stdlib (see `docs/research/formula-test-cases/scripts/count_fods.py`). Convert OpenFormula to Excel syntax (`of:=` prefix, `[.K2]` → `K2`, `;` → `,`) or use the `FunctionString` column, which already holds the Excel-style text. Then resolve the referenced input cells into typed input rows.
- **Caveats:** "Expected" means *what LibreOffice is certified to return*. It was authored to match Excel and mostly does, but where the two differ it is LibreOffice-truth. LibreOffice-only functions (EASTERSUNDAY, DAYS360 variants, `ORG.OPENOFFICE.*`) must be filtered out. Many cases test errors and odd arguments, which are low value for ThoughtSpot. Range arguments become aggregate tests, which is useful but needs a range-to-rows loader.

### 2. Apache POI formula-evaluation spreadsheets (the only Excel-computed values)
- **URL / owner:** https://github.com/apache/poi/tree/trunk/test-data/spreadsheet — Apache Software Foundation.
- **Licence:** Apache-2.0 (`legal/LICENSE`). **Verdict: yes.** Same licence; keep attribution and NOTICE.
- **Format / counts (measured):**
  - `FormulaEvalTestData_Copy.xlsx` (and the `.xls` original): **1,295 formula cells** (`docProps/app.xml` says `Microsoft Excel`), of which 1,170 carry Excel-cached values. Sheets: EverythingTests, FinanceLibTests, StatsLibTests, misc. 128 distinct functions.
  - 23 `*TestCaseData.xls` files: **641 rows** with `Formula` (column B, cached by Excel) and `Expected Result` (column C, entered by hand), plus Data columns. Read by `BaseTestFunctionsFromSpreadsheet.java`. Lookup and INDEX dominate (≈350 rows), and those are `structural` in ThoughtSpot.
- **Extraction:** openpyxl for xlsx (formula plus `data_only` cached value). `.xls` (BIFF) needs xlrd for values; for formula text, use POI or a LibreOffice conversion.
- **Caveats:** saved by legacy Excel before dynamic arrays, so a range in scalar context uses implicit intersection (`=G7:J7/B8` → `#VALUE!`). That is irrelevant for ThoughtSpot and should be filtered. Many cases test error propagation. The cases cover breadth, not realistic data.

### 3. Apache Spark SQL (for Databricks SQL)
- **URL / owner:** https://github.com/apache/spark: `ExpressionDescription(examples = """ > SELECT …; result""")` in `sql/catalyst/.../expressions/*.scala`, and `sql/core/src/test/resources/sql-tests/{inputs,results}`. Owner: ASF.
- **Licence:** Apache-2.0 (GitHub API). **Verdict: yes.**
- **Expected values are CI-verified:** `ExpressionInfoSuite."check outputs of expression examples"` runs every example and compares the output. The 221 golden `*.sql.out` files hold query, schema and output (`string-functions.sql.out` alone has 300 queries).
- **Caveats:** Databricks SQL warehouses default to ANSI mode and Photon, so some results (overflow, casts, invalid dates) differ from OSS Spark's non-ANSI defaults. Always re-run in the Databricks SQL warehouse, which is the oracle, and keep Spark's value as provenance only.

### 4. formula.js (@formulajs/formulajs)
- **URL:** https://github.com/formulajs/formulajs/tree/master/test. **Licence:** MIT, "Copyright (c) 2014 Sutoiku, Inc." **Verdict: yes**, keeping the notice.
- **Format:** mocha/chai, e.g. `expect(dateTime.DATE(10, 1, 1).getFullYear()).to.equal(1910)`. **2,444 `expect()` measured**: math-trig 604, statistical 477, lookup 423, financial 363, text 265, date-time 181, logical 74, information 57.
- **Caveats:** the expectations were written by hand for formula.js and are not certified against Excel; some encode formula.js's JS-Date behaviour. The cases are function calls with literal arguments, so they must be rewritten as Excel formulas. Use them as corroboration, never as the sole oracle.

### 5–7. `formulas`, pycel, HyperFormula
- `formulas` (vinci1it2000): EUPL-1.1. `test/test_files/test.xlsx` has 5,480 formula cells with cached values (CORE 1,115; EXTRA 4,137; OPERATORS 228). EUPL is copyleft and not Apache-compatible, so **do not copy** the test files. The library is evaluated as an oracle in `oracles.md`.
- pycel: GPL-3.0. **Do not copy.**
- HyperFormula: dual GPL-3.0 / proprietary ("The specific license under which you use the software is determined by the license key you apply"). Its `test/README.md` says *"The full test suite is available on request"*, and the suite is a private `hyperformula-tests` repo. **Not available, and not copyable.**

### 9. Microsoft Excel function reference (support.microsoft.com)
- **Example:** the NETWORKDAYS page has a data table plus `=NETWORKDAYS(A2,A3)` → 110, `…,A4)` → 109, `…,A4:A6)` → 107. These are excellent cases. The footer is "© Microsoft 2026".
- **Licence:** the Microsoft Terms of Use: *"use of such Documents from the Services is for informational and non-commercial or personal use only and will not be copied or posted on any network computer"*. **Verdict: do not copy.** You can read a page to choose *which* behaviour to test, then author our own inputs and compute the expected value with an oracle. That is clean-room in spirit; get legal sign-off on the practice.

### 10. Google Sheets help
- The NETWORKDAYS page (answer/3092979) has "Sample usage" with no results, and its "Examples" is one prose line. "©2026 Google". **No usable expected values, and do not copy.** For Sheets, Excel cases plus the Sheets delta map are the route; for the ~46 Sheets-only functions, an oracle would have to be Google Sheets itself through the Sheets API (`values.get` with `valueRenderOption=UNFORMATTED_VALUE`). That needs a Google account and was not tested.

### 11–12. DAX
- learn.microsoft.com DAX pages have `EVALUATE` examples with result tables (e.g. DATEDIFF: Year 2, Quarter 9, Month 29, Week 130, Day 914). The page metadata now points to `MicrosoftDocs/query-docs-pr` (private). The public `MicrosoftDocs/query-docs`, which carried a CC-BY-4.0 LICENSE, **returns 404 (confirmed with `gh api`)**. **Verdict: not until the licence is re-confirmed.** If a CC-BY-4.0 statement is found for the live pages, attribution-only reuse is fine. Many examples also need the Adventure Works DW 2020 sample model, so expected values depend on data we would have to load.
- dax.guide: "© SQLBI, all rights reserved" (the terms page returned 404). **No.**
- **Oracle path instead:** the Power BI REST `datasets/{id}/executeQueries` (DAX) against a Fabric/Power BI workspace, if one is available. This was not tested.

### 13–15. Tableau, Qlik, Snowflake, Databricks docs
- Tableau: inline results such as `DATEDIFF('day', #3/25/1986#, #2/20/2021#) = 12,751`, `DATETRUNC('iso-week', #9/22/2018#) = #9/17/2018#`. © Salesforce. **No copy.** Oracle path: publish a tiny workbook to Tableau Cloud/Server through the repo's `ts-profile-tableau` and read `GET /views/{id}/data` (CSV). Not tested.
- Qlik: NETWORKDAYS example (08/10/2022–08/26/2022 → 13; one holiday → 12; four → 11). "Copyright © 1993-2026 QlikTech International AB. All rights reserved." **No copy.**
- Snowflake: examples carry output tables (`DATEDIFF(year, '2020-04-09 14:39:20', '2023-05-08 23:39:20')` → 3). "© 2026 Snowflake, Inc. All Rights Reserved." **No copy**, and none is needed: Snowflake itself is the oracle. Author the case, run it and record the output.

### 16. TPC-H / TPC-DS
- Answer sets ship in the TPC kits under the TPC EULA (search results; the EULA URL 404'd, so I could not quote it). **Do not vendor** queries, answers or generated data. Snowflake already exposes `SNOWFLAKE_SAMPLE_DATA.TPCH_SF1` / `TPCDS_SF10TCL` (assuming the share is mounted on the test account: unverified). The repo's TPC-DS use so far is structural (`docs/reviews/2026-07-29-ossie-tpcds-fidelity.md`), with no executed numbers. Value here: **aggregate-level** oracles (revenue by year, ratios, windowed ranks) computed by Snowflake and reproduced through a ThoughtSpot Model. That is the same shape as the angle-15 SV study, and it tests joins and aggregation rather than single functions.

### 17. Superstore
- No open licence was found, and the published "known totals" differ by Superstore version. **Low value.** If wanted, load it ourselves and use Snowflake as the oracle, which makes it the same as #16 with a weaker provenance story.

### 18. OASIS OpenFormula
- **Measured:** the final ODF 1.2 Part 2 HTML (1.28 MB) has 408 "Semantics:" blocks and **no** test-case tables. The ROUND section is prose only. Test cases existed in pre-OASIS drafts (D. Wheeler, 2005–2007); those were not retrieved. The licence notice is permissive (*"derivative works that comment on or otherwise explain it or assist in its implementation may be prepared, copied, published, and distributed, in whole or in part, without restriction of any kind, provided that the above copyright notice and this section are included"*), but there are no expected values to take. Useful only as the semantic spec when sources disagree (e.g. ROUND "shall round away from zero").
