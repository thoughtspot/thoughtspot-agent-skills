# Computing expected values ourselves (oracles)

**Principle.** The best oracle is the source tool itself. A *second implementation* of the source tool (LibreOffice, `formulas`, pycel) is a proxy: wherever it disagrees with the real tool it manufactures confidence, the same failure as `wrangler dev` not enforcing a production limit. So every case records **which oracle produced its expected value**, and a proxy oracle's value is never presented as the source tool's.

Oracle tiers, used in the case format (`harness-design.md`):
- **gold:** the source tool computed it. Examples: Excel-cached values in POI workbooks, Snowflake/Databricks executing the SQL, Power BI `executeQueries`, Tableau view data.
- **silver:** an independent test suite certified it against its own engine and authored it to match the source (LibreOffice `Expected`, formula.js `expect`, Spark example outputs before re-running on Databricks).
- **bronze:** a proxy engine computed it (`formulas`, LibreOffice recalculation, pycel).

A bronze value that disagrees with a silver value quarantines the case. It is never resolved by picking one.

## What is on this machine (checked 2026-10-06)

| Tool | Status |
|---|---|
| `soffice` / `libreoffice` | **not installed** (`which` empty, Spotlight finds no LibreOffice bundle, no Homebrew casks) |
| Microsoft Excel | **not installed**. Only "Numbers Creator Studio" is present (it opens xlsx; its recalculation is Apple's engine, a fourth implementation, not tested) |
| `uv` | 0.12.8; system `python3` is 3.9.6. uv-managed 3.12/3.14 environments work |
| `formulas` | installed fine in a throwaway uv env (v1.3.4, Python 3.14) |
| `pycel` | installed fine (v1.0b30), but **fails on Python 3.14** (`module 'ast' has no attribute 'Num'` on every arithmetic formula); works on 3.12 |

LibreOffice could not be tried without a system-wide install (a cask or .dmg), so its feasibility below is from documentation and the LibreOffice test design, **not from a run here**.

## 1. LibreOffice headless recalculation

- **Invocation:** `soffice --headless --convert-to xlsx --outdir out/ in.xlsx`, or `--convert-to csv`.
- **Trap: it may not recalculate at all.** Calc's "Recalculation on File Load" for Excel 2007+ files defaults to *never recalculate* (it trusts cached values), so a plain `--convert-to` can return the cached values untouched. Two ways round it:
  - Force "always": set `org.openoffice.Office.Calc/Formula/Load/OOXMLRecalcMode = 0` in a throwaway profile, passed with `-env:UserInstallation=file:///tmp/lo-profile`.
  - Write formulas with **no cached values** (openpyxl writes none), which forces calculation. That is what we would generate anyway.
  - Verify with a sentinel such as `=NOW()` or a deliberately wrong cache.
- **Fidelity to Excel:**
  - Its own test corpus (`sources.md` #1) was authored to match Excel and is green in CI.
  - Dates: LibreOffice's epoch is 1899-12-30, so serials agree with Excel from 1900-03-01. Excel's fictitious 1900-02-29 is not reproduced, so keep test dates after 1900-03-01. 1904-date-system workbooks are honoured.
  - Rounding: IEEE double like Excel. Excel's 15-significant-digit compare and display rounding is emulated ("approxEqual"), but not identically in every function.
  - Empty cells: blank-as-0 in arithmetic and blank-as-"" in concatenation match Excel. The *string-to-number* conversion setting ("Generate #VALUE! error" vs "Treat as zero") is configurable and must be pinned in the profile.
  - Error values are the same codes, but which error appears can differ on odd arguments.
  - LibreOffice-only functions and its Excel-compatibility variants (`COM.MICROSOFT.*`) need filtering.
  - Dynamic arrays / `LET` / `LAMBDA` support is recent (the `dynamic_array` and `lambda` test dirs exist); avoid them in milestone 1.
- **Licence:** MPL-2.0. Running it as an external tool puts no obligation on our repo.
- **Verdict:** **the best bronze Excel oracle for breadth** (~500 functions), but it needs a LibreOffice install, through Homebrew cask or a Docker image in CI, which needs the user's decision.

## 2. Python `formulas` (vinci1it2000): tested here

**Test A: tiny workbook I wrote** (`oracle-test/tiny.xlsx`, `docs/research/formula-test-cases/scripts/make_wb.py`, `docs/research/formula-test-cases/scripts/eval_formulas.py`). It has 28 formulas with expected values from Microsoft's NETWORKDAYS example or Excel semantics. **26 of 28 matched.** Both deviations are real fidelity limits:

| Formula | Expected (Excel) | `formulas` | Note |
|---|---|---|---|
| `=0.1+0.2=0.3` | TRUE | **FALSE** | Excel compares at 15 significant digits; `formulas` compares raw doubles |
| `=YEARFRAC(2012-10-01, 2013-03-01, 1)` | 151/365 = 0.41370 (pycel agrees) | **0.41313** (151/365.5) | Wrong denominator branch for actual/actual spans under a year. Confidence medium: from Excel's documented algorithm, not checked in Excel |

All of these matched: NETWORKDAYS (110/109/107), ROUND half-away-from-zero (−2.5 → −3), WEEKDAY types 1 and 2, DATEDIF "m", COUNT/COUNTA, blank+1 = 1, blank&"x" = "x", IFERROR, `#DIV/0!`, `#VALUE!`, TEXT date format, MOD(−7,3) = 2, INT(−2.5) = −3, EOMONTH, SUMPRODUCT, ISBLANK and MEDIAN.

**Test B: against real Excel at scale** (`docs/research/formula-test-cases/scripts/formulas_vs_cached.py` on POI's Excel-saved `FormulaEvalTestData_Copy.xlsx`).
- One formula (`=1000%%`) was unparseable and made the whole workbook load fail; I replaced it with its cached value (`docs/research/formula-test-cases/scripts/clean_wb.py`).
- **1,033 of 1,273 comparable cells agree (81%).** The 240 disagreements:
  - 38 `#NAME?`: function not implemented (COMBIN, DOLLAR, …)
  - 71 cases where legacy Excel cached `#VALUE!` from implicit intersection of a range in scalar context
  - 131 other: mostly the same implicit-intersection class returning a value, plus error-code differences and floating-point differences (e.g. AVERAGE −4.09e-09 vs 2.32e-08 on a cancellation case)

  Implicit intersection is irrelevant to ThoughtSpot (row formulas never take ranges), so the agreement on *ThoughtSpot-relevant* scalar cases is higher than 81%, but that has not been separately measured.
- **Fidelity limits:**
  - floating-point equality (no 15-digit rule)
  - unimplemented functions return `#NAME?` (detectable; treat as "no oracle")
  - errors are a Python object (`XlError`), not a string
  - dates are Excel serials
  - blank cells follow Excel rules
  - Python 3.14 prints `SyntaxWarning`s but works
- **Licence:** EUPL-1.1, copyleft. Use it as an **external dev tool installed by uv, never vendored or imported into `ts_cli`**. Distributing a modified copy would trigger EUPL.
- **Verdict:** **usable bronze oracle today**, no system install. Pair it with silver values and quarantine on disagreement.

## 3. pycel: tested here, not recommended

- Same tiny workbook on Python 3.12, with **9 of 28 failing**:
  - `UnknownFunction`: NETWORKDAYS ×3, DATEDIF, COUNTA, MEDIAN, STDEV, NETWORKDAYS.INTL
  - `FormulaEvalError`: `WEEKDAY(d, 2)`
- On Python 3.14 nearly everything fails to compile.
- It did get YEARFRAC basis 1 right (0.41370).
- GPL-3.0, beta (1.0b30). Too narrow to be a primary oracle; at most a tie-breaker.

## 4. Warehouse SQL (Snowflake, Databricks) as the oracle for SQL dialects

- **Fidelity:** exact by definition. It is the source engine, i.e. **gold**. This is the cheapest gold oracle we have, and the repo already has the plumbing: `ts snowflake exec -q … --sf-profile`, `ts load snowflake/databricks`, profiles in `~/.claude/snowflake-profiles.json`.
- **Pin the session**, because the same SQL gives different answers under different settings:
  - Snowflake: `WEEK_START`, `WEEK_OF_YEAR_POLICY`, `TIMEZONE`, `TIMESTAMP_TYPE_MAPPING`, `DATE_INPUT_FORMAT`, `QUOTED_IDENTIFIERS_IGNORE_CASE`, and `ROUND` mode (`HALF_AWAY_FROM_ZERO` default; `HALF_TO_EVEN` is optional).
  - Databricks: `ansi_mode` (on by default for SQL warehouses), `timeZone`, `legacy_time_parser_policy`.
  
  Record the settings in each case's provenance.
- **Type traps:** NUMBER(38,s) vs FLOAT changes ROUND/division results. Integer division is `/` → decimal in Snowflake but differs across engines. NULL is NULL (no blank), and empty string is distinct from NULL.
- **Also the oracle for ThoughtSpot itself:** ThoughtSpot compiles formulas to Snowflake SQL (`generate-sql`), so differences between "Snowflake running the source SQL" and "ThoughtSpot's compiled SQL on the same warehouse" are pure translation effects. That gives clean attribution.
- **Licence:** none needed; we author the cases.
- **Cost:** XS-warehouse seconds per 100 cases.
- **Not run in this research:** the brief allowed only local feasibility tests, so no warehouse queries were issued.

## 5. Source-tool oracles for the BI dialects (not tested; listed for completeness)

| Dialect | Gold oracle | Needs |
|---|---|---|
| Excel | Excel itself (Windows/Mac desktop, or Microsoft Graph workbook API `…/workbook/functions/{name}` on OneDrive) | an M365 tenant. Not available here |
| Sheets | Sheets API recalculation | a Google account plus OAuth |
| DAX | Power BI REST `executeQueries` | a Fabric/Power BI workspace |
| Tableau | publish a workbook, then `GET /api/…/views/{id}/data` | Tableau Cloud/Server (the repo has `ts-profile-tableau`) |
| Qlik / Sisense | Engine API / JAQL REST | a tenant |

Until one of these is available, Tableau/DAX/Qlik/Sisense cases can only be **silver from docs (which we may not copy)** or **cross-dialect**. Cross-dialect means expressing the case's intent in SQL, computing it in Snowflake, and asserting that the source formula *should* mean the same. That is a weaker claim and must be labelled as such.
