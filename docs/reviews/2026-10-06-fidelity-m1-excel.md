# Formula fidelity M1: 250 Excel cases, literal oracle, 2026-10-06

**7 silent wrong answers** in 230 scored cases (250 selected, 20 oracle-disputed and not scored).
180 matched. 36 were rejected at import, 2 were warned wrong answers, 3 were documented
divergences and 2 were error-equivalent. Every silent wrong answer and every import-failure root
cause has a BL item (BL-346 to BL-355); the translator is not changed in this PR.

A *silent* wrong answer is a case the translator marked TRANSLATED (or APPROXIMATED with no trap),
that imported, ran, and returned a value other than the corpus value. The translator under test is
`ts formula translate --from excel` (`ts_cli/excel/`, ts-cli 0.158.0), live on se-thoughtspot,
connection `APJ_TAB`.

## Where the cases come from (and what is not in this repo)

**No third-party formula or value is committed.** The corpus lives outside the repo in
`~/Dev/ts/formula-fidelity-data/`, with a `PROVENANCE.md` that records URL, pinned commit, licence
and sha256 per file:

| Source | Commit | Licence | Oracle tier | Selected |
|---|---|---|---|--:|
| LibreOffice `sc/qa/unit/data/functions` (`date_time`, `text`, `mathematical`, `logical`), the `Expected` column | `6804c10b` | MPL-2.0 | silver (certified LibreOffice result) | 200 |
| Apache POI `FormulaEvalTestData_Copy.xlsx`, sheet `EverythingTests`, values cached by Excel | `ae62bb51` | Apache-2.0 | gold (Excel computed it) | 50 |

The repo holds the manifest (`tools/formula-fidelity/cases/excel/m1-manifest.jsonl`: id, file,
sha256, sheet and row or cell), aggregate selection counts (`m1-selection.json`), and the redacted
results (`tools/formula-fidelity/runs/2026-10-06-excel-m1.json`: per case id, status, class, cause).
The repros below describe each construct in our own words. A test fails if any of these files
carries formula-shaped text.

**Selection.** Every formula cell in the four LibreOffice categories (3,008) and the POI sheet
(1,189) was extracted. A cell was refused, with the reason counted in `m1-selection.json`, if it
is not an Excel scalar case:
- ranges or other-sheet references, named expressions, inline arrays
- volatile or positional functions, LibreOffice-only functions, LibreOffice-only error codes
- an expected value computed in-sheet rather than stored
- time-of-day values, and dates before 1900-03-01
- **OpenFormula's own `CEILING` / `FLOOR`**: LibreOffice stores Excel's versions as
  `COM.MICROSOFT.CEILING` / `.FLOOR`, and the bare names follow ODF sign rules, so 91 such cases
  would have scored false wrong answers against an Excel translator

That left 2,463 eligible cases. Of those, the translator handled 754 (TRANSLATED or APPROXIMATED),
and the 250 were drawn from them deterministically (hash order, at most 6 per leading function, at
most 12 error-valued and 10 blank-input cases). POI's old-Excel range quirks (implicit
intersection) are excluded by the no-range rule.

**Inputs.** 123 cases are formulas over constants, run as constant formulas. The others read input
cells. Each distinct source cell became a typed column (`FLOAT`, `VARCHAR`, `DATE`, `BOOLEAN`) of
one single-row warehouse table, `AGENT_SKILLS.PUBLIC.ZZ_FIDELITY_M1_<stamp>`, which M0's loader
created and dropped. A blank cell is a NULL column.

## Translator coverage

**1,709 of 2,463 eligible cases (69%) are NEEDS_REVIEW**: LibreOffice 1,375 of 1,723, POI 334 of
740. These count as coverage, not as fidelity failures, and are not in the 250.
- 1,505 have no translator rule for a function the Excel map rows. There are 105 distinct
  functions: CHAR, CODE, ASC, the inverse trig and hyperbolic functions, DEGREES, GCD, LCM,
  UNICHAR, WORKDAY.INTL, FLOOR.MATH, the `*B` byte functions, REPLACE, TEXT, the
  CEILING/FLOOR.PRECISE family, LOG, FACT, **DATE**, and others. DATE is a `direct` row in the map,
  but the translator has no rule for it.
- 118 have a non-literal argument the rule needs as a literal. Most are a DATEDIF unit read from a
  cell.
- 50 have an argument count outside the rule (for example three-argument CEILING / FLOOR).
- 36 are other refusals.

## Oracle disputes

**20 cases are oracle-disputed** (18 LibreOffice, 2 POI). For each, the Python `formulas` library
(bronze, run in a throwaway uv env, never imported) disagreed with the corpus value, so the case was
not run and is not scored. Of the 754 translatable candidates, 696 agreed, 57 were disputed and 1
could not be evaluated. The disputes in the 250 are:
- LibreOffice-vs-Excel serial semantics below 1900-03-01: YEAR / MONTH of small serials near zero
  (LibreOffice's epoch gives 1899)
- Excel's 15-significant-digit snapping: sums of decimal literals that cancel to zero, and
  round-down of a difference just below a step
- MROUND on non-representable multiples and with mixed signs
- a SWITCH matching a boolean against 1 (LibreOffice treats TRUE as 1, Excel does not)
- `0^0`, NETWORKDAYS.INTL with an empty weekend argument, VALUE of currency text, and one
  CEILING.MATH case where `formulas` itself is wrong
- POI (2): searching for a number's text inside a small decimal's text, and a power whose
  exponent cell holds empty text (Excel `#VALUE!`; `formulas` reads it as 0)

None is resolved by picking a side (oracles.md).

## Silent wrong answers (7)

| Case | Construct, in our own words | Corpus vs ThoughtSpot | Likely root cause | BL |
|---|---|---|---|---|
| `lo-mathematical-ceiling.math-sheet2-r6` | CEILING.MATH of a negative half-step number with a negative significance, over literals | Excel rounds toward zero; ThoughtSpot returned the next multiple away from zero | `functions.py` `HANDLERS`: CEILING.MATH reuses CEILING's `_ceiling_floor` (ceil variant), which divides by the signed significance | BL-346 |
| `lo-mathematical-ceiling.math-sheet2-r19` | the same, over two input columns (negative fractional number, negative significance) | one step too far from zero | same | BL-346 |
| `lo-mathematical-ceiling.xcl-sheet2-r10` | CEILING of a positive fractional number with a zero significance, over columns | Excel 0; ThoughtSpot NULL | `_ceiling_floor`: `x / s` compiles to `NULLIF(s, 0)` | BL-347 |
| `lo-mathematical-roundup-sheet2-r17` | ROUNDUP of a many-decimal literal to more than 6 digits | ThoughtSpot's result has only 6 decimals | `_scaled`: `ceil(x * F) / F` divides two integers, and Snowflake keeps scale 6 | BL-348 |
| `lo-text-upper-sheet2-r6` | UPPER over a date input cell | Excel gives the date serial as text; ThoughtSpot the ISO date | `functions_text.py` `_string_op` passes a DATE straight into `sql_string_op`; the `&` path traps this, the text functions do not | BL-350 |
| `poi-…-everythingtests-f27` | text joined with a comparison result | Excel `TRUE`; ThoughtSpot `true` | `forward.py` `as_text`: a boolean becomes `to_string` (lower case); the difference is a note, not a trap | BL-349 |
| `poi-…-everythingtests-f23` | sum of a negative four-digit integer and a one-decimal literal | Excel's double result differs from the exact decimal in the 13th significant digit | not in `ts_cli/excel`: Snowflake evaluates decimal literals in fixed point. Scored silent under the declared 1e-12 tolerance, which is not widened | BL-351 |

Six of the seven are `ts_cli/excel` rules. BL-351 is platform arithmetic and is filed so the
divergence is either documented or engineered away.

## Loud failures: 36 rejected at import, all reported TRANSLATED

Each of these is TRANSLATED by the translator and rejected by ThoughtSpot's VALIDATE_ONLY, so the
user would at least see an error.

| Root cause | Cases | BL |
|---|--:|---|
| an Excel date text literal (an ISO date in quotes) passed straight to a date function | 12 | BL-352 |
| Excel's implicit coercion not inserted: a number into a text function, numeric text into arithmetic, a serial number into a date function, a boolean compared with text | 19 | BL-353 |
| a DOUBLE column in an integer slot (`substr` start and length, `right` count) | 4 | BL-355 |
| IFERROR whose fallback type differs from the expression's | 1 | BL-354 |

## Warned, divergent and error-equivalent (not silent, not matches)

- **Warned (2):** a two-argument IF with a FALSE condition. Excel returns FALSE; the translation
  returns NULL. The translator says APPROXIMATED and names the trap.
- **Blank input (1):** EXP of a blank cell. Excel reads it as 0 and returns 1; the NULL column
  propagates. This is a documented divergence (`excel-blank-vs-null`).
- **Excel error, ThoughtSpot value (2):**
  - FLOOR with a positive number and a negative significance: Excel errors, ThoughtSpot returns a
    number.
  - LN of zero: Excel `#NUM!`. ThoughtSpot compiles `ln` to a conditional that yields the text 'inf' for
    zero, and returns the *string* `Infinity`.
- **Error-equivalent (2):**
  - LN of a negative literal: the warehouse query fails.
  - FLOOR with a zero significance: Excel `#DIV/0!`, ThoughtSpot NULL.

## Reading the numbers

- **The silent count is a floor.** The 250 were drawn only from cases the translator already
  handles, at most 6 per function, and 36 more never ran because they failed at import. BL-352 and
  BL-353 cover 31 of those, and fixing them will turn loud failures into scored cases. Some of
  those scored cases may then be silent wrong answers (the SV study's lesson).
- **The corpus is breadth, not realism.** LibreOffice's cases probe edge arguments, and its truth
  is LibreOffice's where it differs from Excel. The `formulas` cross-check catches what it can.
  POI is the only Excel-computed anchor, and both POI silent cases are real Excel behaviour.
- **Two harness rules mattered:**
  - Error-valued corpus cases were first scored ORACLE_FAILED by M0's rule (an all-error oracle
    means an authoring error in a SQL case). M1 classifies them against the error instead:
    `literal.classify_error_expected`.
  - The Excel-vs-ODF CEILING/FLOOR split, described under Selection.

## Run

One live run (2026-10-06, 230 cases, 374 s: 109 s import with VALIDATE_ONLY bisection, 257 s AgentQL). After the error-expected
fix the results were re-classified from the stored run with `run_literal.py rebuild`, with no new
queries. Teardown deleted the Model and the Table and confirmed both absent, and dropped the
warehouse table and confirmed it with `SHOW TABLES`. The startup sweep found one earlier
`ZZ_FIDELITY_*` warehouse table and only reported it; this run did not create it.

## After fixes (2026-10-07)

The fixes for BL-346..350 and BL-352..355 (ts-cli 0.161.0; the run used the fix commits before
the version string was bumped, so its header reads 0.160.0) were re-run live on the same 250
cases, the same manifest and the same cluster. Redacted results:
`tools/formula-fidelity/runs/2026-10-07-excel-m1.json`; full evidence in the data dir
(`runs/2026-10-07-excel-m1-full.json`). The findings above are the 2026-10-06 run and are kept
as they were; the generated tables below are that run's too.

**What changed in the translator.** A type checker over the emitted formula
(`ts_cli/excel/typecheck.py`) now turns any provable type error into NEEDS_REVIEW, so a
translation ThoughtSpot would reject at import can no longer come back TRANSLATED. Excel's
implicit coercions are written out (`ts_cli/excel/coerce.py`): a text date becomes `to_date`, a
serial number becomes its date, a number, boolean or date in a text function becomes Excel's
text, numeric text in arithmetic becomes a number, a DOUBLE count or position becomes
`floor ( … )`, and `IF` / `IFERROR` branches share one type. Then the silent rules were fixed:
`CEILING.MATH` sign and mode, a zero `CEILING` significance, `ROUNDUP` / `ROUNDDOWN` precision,
and booleans in text.

| Class | 2026-10-06 | 2026-10-07 |
|---|--:|--:|
| SILENT_WRONG | 7 | **2** |
| WARNED_WRONG | 2 | 2 |
| DIVERGENCE_BLANK | 1 | 3 |
| DIVERGENCE_ERROR | 2 | 2 |
| IMPORT_FAILED | 36 | **0** |
| TRANSLATE_FAILED (NEEDS_REVIEW) | 0 | 3 |
| ERROR_EQUIV | 2 | 3 |
| MATCH | 180 | **215** |
| ORACLE_DISPUTED (not run) | 20 | 20 |

**0 import failures among TRANSLATED or APPROXIMATED results.** Of the 36 former import
failures, 30 now match, 2 are blank-input divergences (a blank cell read as 0 by Excel), 1 is
error-equivalent (absolute value of non-numeric text: Excel `#VALUE!`, ThoughtSpot NULL) and 3
are NEEDS_REVIEW:
- `lo-date_time-day-sheet2-r5`: a date-time text before 1900. Excel does not read text before
  1900 as a date and returns `#VALUE!`; the corpus value is LibreOffice's, which does. Refused
  rather than translated to LibreOffice's answer.
- `lo-date_time-eomonth-sheet2-r7`: text that is not a date in a date function (Excel
  `#VALUE!`, which is also the corpus value). NEEDS_REVIEW is the honest answer.
- `poi-…-f940`: a month taken from serial number 0, which is Excel's fictitious "1900-01-00";
  no real date carries it.

**Five of the seven silent wrong answers now match**: both `CEILING.MATH` cases, the zero
`CEILING` significance, the date in `UPPER` and the boolean joined into text. Two remain:
- `poi-…-f23` (BL-351): constant decimal arithmetic. The warehouse computes literals as exact
  decimals, Excel as doubles. This is a platform divergence, documented in the Excel map and the
  skill; the translation now carries a trap naming it, and the status stays TRANSLATED, so the
  harness still scores it silent. The tolerance is not widened.
- `lo-mathematical-roundup-sheet2-r17` (BL-348, now an oracle question, BL-356): the
  round-up to more than 6 digits is no longer cut to 6. ThoughtSpot now returns the value that
  Microsoft's documented rule gives (round away from zero at the 11th decimal), and that the
  bronze `formulas` cross-check gives too. The LibreOffice silver value is one unit lower in the
  last place, a relative difference of about 1.2e-12, just above the case's declared 1e-12
  tolerance. The cross-check uses a 1e-9 bound, so it reported "agree" and the case was not
  quarantined. Following oracles.md, it is not resolved by picking a side: BL-356 makes the
  cross-check compare at the case's own tolerance.

**No regression.** No case that matched on 2026-10-06 changed class. Every MATCH case was also
re-translated offline: none moved to NEEDS_REVIEW, and the only changed formulas are the
`ROUNDUP` / `ROUNDDOWN` increment form and the new coercions.

**M0 (Snowflake, unchanged translator) re-run the same day:** 64 of 71 MATCH, 0 silent, 4 warned
(BL-333), 2 NEEDS_REVIEW, 1 error-equivalent, the same as its after-fixes run
(`tools/formula-fidelity/runs/2026-10-07-snowflake-m0-regression.json`). **60-case Excel
regression set:** 58 match their reviewed answers and 2 differ by documented rule, unchanged.

**Run.** 2026-10-06T20:34Z (2026-10-07 local), profile `se-thoughtspot`, connection `APJ_TAB`,
227 cases imported (3 NEEDS_REVIEW were not sent), 674 s (650 s AgentQL; the cluster timed out one
fetch, which was retried). Teardown deleted the Model and the Table and confirmed both absent,
and dropped the warehouse table and confirmed it with `SHOW TABLES`. The startup sweep found no
earlier `ZZ_FIDELITY_*` objects. After both runs, `ts metadata search` finds no `ZZ_FIDELITY_%`
or `ZZ_PROBE_M1FIX%` objects and `SHOW TABLES LIKE 'ZZ_%'` in `AGENT_SKILLS.PUBLIC` is empty.
The three scratch probe Models behind the new probe-record rows (§7) were deleted and confirmed
absent.

### Review round (2026-10-07, second live run)

An independent review of PR #574 found more defects, and they are fixed in the same PR:
- **DOUBLE representation error in the rounding compositions.** `1.1 * 100` is
  `110.00000000000001`, so `ceil` gave 1.11. A DOUBLE is now snapped with `round ( … , 1e-9 )`
  first, and more than 15 digits is NEEDS_REVIEW.
- **Cross-type comparison folds and DOUBLE-to-text are now APPROXIMATED**, with traps that
  name the assumption.
- **Number literals are written as text in Excel's General format.**
- **`to_double` of non-numeric text fails the whole query** (probed live; it does not return
  NULL). `IFERROR(VALUE(…))` and `ISNUMBER(VALUE(…))` therefore use `TRY_TO_DOUBLE`.
- **A slashed day/month date is APPROXIMATED**, with a locale trap.
- **The `COERCION_EMITS` validator exemption is limited to the nodes the coercions add.**
- **The exact leak scan now covers every tracked file.**

The second live run, at commit `323d282` (recorded in the run header, which now carries the
commit), replaced `tools/formula-fidelity/runs/2026-10-07-excel-m1.json`. Results:
- **0 import failures and 2 silent wrong answers**, the two named above. Both now carry their
  cause in the results: BL-351 (platform) and BL-356 (oracle dispute).
- **215 MATCH**, 2 warned, 3 blank divergences, 2 error divergences, 3 error-equivalent and 3
  NEEDS_REVIEW, the same classes as the first after-fixes run.
- 17 results are now APPROXIMATED, up from the first run because of the review's downgrading
  traps. None of them changed class.
- No case that matched on 2026-10-06 changed class.

M0 re-run at the same commit: 64 of 71, 0 silent, 4 warned. Cleanup was confirmed on both
sides (the run's own teardown, then `ts metadata search` and `SHOW TABLES LIKE 'ZZ_%'`, both
empty).

*Everything below is generated from the redacted results; regenerate with `run_literal.py rebuild`.*

<!-- generated by tools/formula-fidelity/run_literal.py: edit above this line -->

## Counts by class

| Class | LibreOffice | POI | Total | Meaning |
|---|--:|--:|--:|---|
| SILENT_WRONG | 5 | 2 | 7 | imported, ran, returned a different value, and the translator said TRANSLATED (or APPROXIMATED with no trap) |
| WARNED_WRONG | 2 | 0 | 2 | a different value, but the translator said APPROXIMATED and named a trap |
| DIVERGENCE_BLANK | 1 | 0 | 1 | an input cell is blank: Excel reads 0 / '', the warehouse column is NULL (documented divergence, not scored as a match) |
| DIVERGENCE_ERROR | 2 | 0 | 2 | Excel returns an error value; ThoughtSpot returns a value (documented divergence, not scored as a match) |
| RUN_FAILED | 0 | 0 | 0 | imported, but the AgentQL query failed or returned no rows |
| IMPORT_FAILED | 27 | 9 | 36 | ThoughtSpot rejected the translated formula (VALIDATE_ONLY) |
| TRANSLATE_FAILED | 0 | 0 | 0 | the translator declined (NEEDS_REVIEW) |
| ERROR_EQUIV | 1 | 1 | 2 | Excel returns an error; ThoughtSpot returns NULL or an error |
| ORACLE_FAILED | 0 | 0 | 0 | the corpus has no usable expected value |
| MATCH | 144 | 36 | 180 | equal under the comparison rules |
| ORACLE_DISPUTED | 18 | 2 | 20 | the `formulas` cross-check disagrees with the corpus value: quarantined, not run, not scored |
| **Total** | 200 | 50 | **250** | |

## By function

| Function | Cases | Match | Silent wrong | Warned | Divergence | Loud | Error-equiv | Disputed |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| (operators) | 12 | 5 | 2 | 0 | 0 | 2 | 0 | 3 |
| ABS | 7 | 6 | 0 | 0 | 0 | 1 | 0 | 0 |
| AND | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| CEILING | 7 | 5 | 1 | 0 | 0 | 1 | 0 | 0 |
| CEILING.MATH | 6 | 3 | 2 | 0 | 0 | 0 | 0 | 1 |
| CONCAT | 5 | 5 | 0 | 0 | 0 | 0 | 0 | 0 |
| CONCATENATE | 6 | 6 | 0 | 0 | 0 | 0 | 0 | 0 |
| DAY | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 0 |
| DAYS | 2 | 1 | 0 | 0 | 0 | 1 | 0 | 0 |
| EDATE | 3 | 0 | 0 | 0 | 0 | 3 | 0 | 0 |
| EOMONTH | 6 | 3 | 0 | 0 | 0 | 3 | 0 | 0 |
| EXACT | 3 | 3 | 0 | 0 | 0 | 0 | 0 | 0 |
| EXP | 3 | 2 | 0 | 0 | 1 | 0 | 0 | 0 |
| FALSE | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| FIND | 6 | 6 | 0 | 0 | 0 | 0 | 0 | 0 |
| FLOOR | 8 | 6 | 0 | 0 | 1 | 0 | 1 | 0 |
| IF | 7 | 5 | 0 | 2 | 0 | 0 | 0 | 0 |
| IFERROR | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 0 |
| IFS | 6 | 6 | 0 | 0 | 0 | 0 | 0 | 0 |
| INT | 5 | 5 | 0 | 0 | 0 | 0 | 0 | 0 |
| ISBLANK | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| ISNUMBER | 3 | 3 | 0 | 0 | 0 | 0 | 0 | 0 |
| LEFT | 6 | 6 | 0 | 0 | 0 | 0 | 0 | 0 |
| LEN | 5 | 4 | 0 | 0 | 0 | 1 | 0 | 0 |
| LN | 5 | 3 | 0 | 0 | 1 | 0 | 1 | 0 |
| LOG10 | 5 | 5 | 0 | 0 | 0 | 0 | 0 | 0 |
| LOWER | 4 | 4 | 0 | 0 | 0 | 0 | 0 | 0 |
| MID | 8 | 4 | 0 | 0 | 0 | 4 | 0 | 0 |
| MOD | 8 | 7 | 0 | 0 | 0 | 1 | 0 | 0 |
| MONTH | 4 | 0 | 0 | 0 | 0 | 2 | 0 | 2 |
| MROUND | 6 | 3 | 0 | 0 | 0 | 0 | 0 | 3 |
| NETWORKDAYS | 3 | 3 | 0 | 0 | 0 | 0 | 0 | 0 |
| NETWORKDAYS.INTL | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 2 |
| NOT | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| OR | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| POWER | 9 | 6 | 0 | 0 | 0 | 1 | 0 | 2 |
| RIGHT | 7 | 6 | 0 | 0 | 0 | 1 | 0 | 0 |
| ROUND | 6 | 6 | 0 | 0 | 0 | 0 | 0 | 0 |
| ROUNDDOWN | 7 | 6 | 0 | 0 | 0 | 0 | 0 | 1 |
| ROUNDUP | 9 | 7 | 1 | 0 | 0 | 1 | 0 | 0 |
| SEARCH | 8 | 6 | 0 | 0 | 0 | 1 | 0 | 1 |
| SIGN | 4 | 4 | 0 | 0 | 0 | 0 | 0 | 0 |
| SQRT | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| SUBSTITUTE | 3 | 3 | 0 | 0 | 0 | 0 | 0 | 0 |
| SUM | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| SWITCH | 6 | 5 | 0 | 0 | 0 | 0 | 0 | 1 |
| TEXTJOIN | 3 | 3 | 0 | 0 | 0 | 0 | 0 | 0 |
| TRIM | 6 | 6 | 0 | 0 | 0 | 0 | 0 | 0 |
| UPPER | 7 | 6 | 1 | 0 | 0 | 0 | 0 | 0 |
| VALUE | 4 | 0 | 0 | 0 | 0 | 3 | 0 | 1 |
| WEEKDAY | 6 | 0 | 0 | 0 | 0 | 6 | 0 | 0 |
| YEAR | 5 | 0 | 0 | 0 | 0 | 2 | 0 | 3 |

## Per-case results

Case ids name the source file and its row or cell; the formula and values are in the corpus (data dir), not here.

| Case | Functions | Translator | Class | Mismatch | Cause / detail |
|---|---|---|---|---|---|
| lo-mathematical-ceiling.math-sheet2-r19 | CEILING.MATH | TRANSLATED | SILENT_WRONG | NUMERIC_DIFF |  |
| lo-mathematical-ceiling.math-sheet2-r6 | CEILING.MATH | TRANSLATED | SILENT_WRONG | NUMERIC_DIFF |  |
| lo-mathematical-ceiling.xcl-sheet2-r10 | CEILING | TRANSLATED | SILENT_WRONG | NULL_DIFF |  |
| lo-mathematical-roundup-sheet2-r17 | ROUNDUP | TRANSLATED | SILENT_WRONG | NUMERIC_DIFF |  |
| lo-text-upper-sheet2-r6 | UPPER | TRANSLATED | SILENT_WRONG | VALUE_DIFF |  |
| poi-formulaevaltestdata_copy-everythingtests-f23 | (operators) | TRANSLATED | SILENT_WRONG | NUMERIC_DIFF |  |
| poi-formulaevaltestdata_copy-everythingtests-f27 | (operators) | TRANSLATED | SILENT_WRONG | VALUE_DIFF |  |
| lo-logical-if-sheet2-r12 | IF, TRUE | APPROXIMATED | WARNED_WRONG | NULL_DIFF |  |
| lo-logical-if-sheet2-r8 | IF | APPROXIMATED | WARNED_WRONG | NULL_DIFF |  |
| lo-mathematical-exp-sheet2-r3 | EXP | TRANSLATED | DIVERGENCE_BLANK | NULL_DIFF | excel-blank-vs-null |
| lo-mathematical-floor.xcl-sheet2-r19 | FLOOR | TRANSLATED | DIVERGENCE_ERROR | ERROR_VS_VALUE |  |
| lo-mathematical-ln-sheet2-r6 | LN | TRANSLATED | DIVERGENCE_ERROR | ERROR_VS_VALUE |  |
| lo-date_time-day-sheet2-r5 | DAY | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Search did not find … in your data or metadata. Expecting one of the valid keywords, s [code 14516] |
| lo-date_time-days-sheet2-r2 | DAYS | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Search did not find … in your data or metadata. Expecting one of the valid keywords, s [code 14516] |
| lo-date_time-edate-sheet2-r3 | EDATE | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Search did not find … in your data or metadata. Expecting one of the valid keywords, s [code 14516] |
| lo-date_time-edate-sheet2-r4 | EDATE | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Search did not find … in your data or metadata. Expecting one of the valid keywords, s [code 14516] |
| lo-date_time-edate-sheet2-r5 | EDATE | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Search did not find … in your data or metadata. Expecting one of the valid keywords, s [code 14516] |
| lo-date_time-eomonth-sheet2-r2 | EOMONTH | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Search did not find … in your data or metadata. Expecting one of the valid keywords, s [code 14516] |
| lo-date_time-eomonth-sheet2-r6 | EOMONTH | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Function start_o… expects 1st argument to be Date or DateTime or Time. … [code 14516] |
| lo-date_time-eomonth-sheet2-r7 | EOMONTH | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Function start_o… expects 1st argument to be Date or DateTime or Time. … [code 14516] |
| lo-date_time-month-sheet2-r3 | MONTH | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Search did not find … in your data or metadata. Expecting one of the valid keywords, s [code 14516] |
| lo-date_time-weekday-sheet2-r14 | WEEKDAY | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Search did not find … in your data or metadata. Expecting one of the valid keywords, s [code 14516] |
| lo-date_time-weekday-sheet2-r15 | WEEKDAY | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Search did not find … in your data or metadata. Expecting one of the valid keywords, s [code 14516] |
| lo-date_time-weekday-sheet2-r16 | WEEKDAY | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Search did not find … in your data or metadata. Expecting one of the valid keywords, s [code 14516] |
| lo-date_time-weekday-sheet2-r18 | WEEKDAY | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Search did not find … in your data or metadata. Expecting one of the valid keywords, s [code 14516] |
| lo-date_time-weekday-sheet2-r2 | WEEKDAY | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Search did not find … in your data or metadata. Expecting one of the valid keywords, s [code 14516] |
| lo-date_time-weekday-sheet2-r6 | WEEKDAY | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Search did not find … in your data or metadata. Expecting one of the valid keywords, s [code 14516] |
| lo-date_time-year-sheet2-r3 | YEAR | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Function year expects 1st argument to be Date or DateTime or Time. … [code 14516] |
| lo-date_time-year-sheet2-r4 | YEAR | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Search did not find … in your data or metadata. Expecting one of the valid keywords, s [code 14516] |
| lo-logical-iferror-sheet2-r14 | IFERROR | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Expecting a Text token. … [code 14516] |
| lo-mathematical-abs-sheet2-r8 | ABS | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Function abs expects 1st argument to be Numeric. … [code 14516] |
| lo-text-mid-sheet2-r10 | MID | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Function substr expects 2nd argument to be Numeric. … [code 14516] |
| lo-text-mid-sheet2-r11 | MID | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Search did not find … in your data or metadata. Expecting one of the valid keywords, s [code 14516] |
| lo-text-mid-sheet2-r5 | MID | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Search did not find … in your data or metadata. Expecting one of the valid keywords, s [code 14516] |
| lo-text-mid-sheet2-r9 | MID | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Function substr expects 2nd argument to be Numeric. … [code 14516] |
| lo-text-search-sheet2-r2 | SEARCH | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Function strpos expects 1st argument to be Text. … [code 14516] |
| lo-text-value-sheet2-r12 | VALUE | TRANSLATED | IMPORT_FAILED |  | excel-blank-vs-null |
| lo-text-value-sheet2-r4 | VALUE | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Function to_double expects 1st argument to be Boolean or Numeric or Text. … [code 14516] |
| lo-text-value-sheet2-r5 | VALUE | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Function to_double expects 1st argument to be Boolean or Numeric or Text. … [code 14516] |
| poi-formulaevaltestdata_copy-everythingtests-d832 | LEN | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Function strlen expects 1st argument to be Text. … [code 14516] |
| poi-formulaevaltestdata_copy-everythingtests-e63 | (operators) | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Expecting a List token. … [code 14516] |
| poi-formulaevaltestdata_copy-everythingtests-f940 | MONTH | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Function month_number expects 1st argument to be Date or DateTime or Time. … [code 14516] |
| poi-formulaevaltestdata_copy-everythingtests-g1168 | RIGHT | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Function right expects 2nd argument to be Numeric. … [code 14516] |
| poi-formulaevaltestdata_copy-everythingtests-i212 | CEILING | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Function ceil expects 1st argument to be Numeric. … [code 14516] |
| poi-formulaevaltestdata_copy-everythingtests-j932 | MOD | TRANSLATED | IMPORT_FAILED |  | excel-blank-vs-null |
| poi-formulaevaltestdata_copy-everythingtests-k1188 | ROUNDUP | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Expecting a Text token. … [code 14516] |
| poi-formulaevaltestdata_copy-everythingtests-l1068 | POWER | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Function pow expects 1st argument to be Numeric. … [code 14516] |
| poi-formulaevaltestdata_copy-everythingtests-m31 | (operators) | TRANSLATED | IMPORT_FAILED |  | Formula addition failed. … Error: Search did not find … in your data or metadata. Expecting one of the valid keywords, s [code 14516] |
| lo-mathematical-ln-sheet2-r8 | LN | TRANSLATED | ERROR_EQUIV |  |  |
| poi-formulaevaltestdata_copy-everythingtests-j544 | FLOOR | TRANSLATED | ERROR_EQUIV |  |  |
| lo-date_time-days-sheet2-r5 | DAYS | TRANSLATED | MATCH |  |  |
| lo-date_time-eomonth-sheet2-r12 | EOMONTH | TRANSLATED | MATCH |  |  |
| lo-date_time-eomonth-sheet2-r14 | EOMONTH | TRANSLATED | MATCH |  |  |
| lo-date_time-eomonth-sheet2-r15 | EOMONTH | TRANSLATED | MATCH |  |  |
| lo-date_time-networkdays-sheet2-r5 | NETWORKDAYS | TRANSLATED | MATCH |  |  |
| lo-date_time-networkdays_excel2003-sheet2-r5 | NETWORKDAYS | TRANSLATED | MATCH |  |  |
| lo-date_time-networkdays_excel2003-sheet2-r6 | NETWORKDAYS | TRANSLATED | MATCH |  |  |
| lo-logical-if-sheet2-r11 | IF, TRUE | APPROXIMATED | MATCH |  |  |
| lo-logical-if-sheet2-r18 | IF | TRANSLATED | MATCH |  |  |
| lo-logical-if-sheet2-r19 | IF | TRANSLATED | MATCH |  |  |
| lo-logical-if-sheet2-r4 | EXACT, IF | TRANSLATED | MATCH |  |  |
| lo-logical-if-sheet2-r6 | IF | TRANSLATED | MATCH |  |  |
| lo-logical-ifs-sheet2-r11 | IFS | TRANSLATED | MATCH |  |  |
| lo-logical-ifs-sheet2-r12 | IFS | TRANSLATED | MATCH |  |  |
| lo-logical-ifs-sheet2-r2 | IFS | TRANSLATED | MATCH |  |  |
| lo-logical-ifs-sheet2-r4 | IFS | TRANSLATED | MATCH |  |  |
| lo-logical-ifs-sheet2-r5 | IFS | TRANSLATED | MATCH |  |  |
| lo-logical-ifs-sheet2-r9 | IFS | TRANSLATED | MATCH |  |  |
| lo-logical-switch-sheet2-r10 | SWITCH | TRANSLATED | MATCH |  |  |
| lo-logical-switch-sheet2-r2 | SWITCH, WEEKDAY | TRANSLATED | MATCH |  |  |
| lo-logical-switch-sheet2-r3 | SWITCH, WEEKDAY | TRANSLATED | MATCH |  |  |
| lo-logical-switch-sheet2-r4 | SWITCH, WEEKDAY | TRANSLATED | MATCH |  |  |
| lo-logical-switch-sheet2-r7 | SWITCH | TRANSLATED | MATCH |  |  |
| lo-mathematical-abs-sheet2-r2 | ABS | TRANSLATED | MATCH |  |  |
| lo-mathematical-abs-sheet2-r4 | ABS | TRANSLATED | MATCH |  |  |
| lo-mathematical-abs-sheet2-r6 | ABS | TRANSLATED | MATCH |  |  |
| lo-mathematical-abs-sheet2-r7 | ABS | TRANSLATED | MATCH |  |  |
| lo-mathematical-add-sheet2-r4 | (operators) | TRANSLATED | MATCH |  |  |
| lo-mathematical-add-sheet2-r7 | (operators) | TRANSLATED | MATCH |  |  |
| lo-mathematical-ceiling.math-sheet2-r30 | CEILING.MATH | TRANSLATED | MATCH |  |  |
| lo-mathematical-ceiling.math-sheet2-r31 | CEILING.MATH | TRANSLATED | MATCH |  |  |
| lo-mathematical-ceiling.math-sheet2-r8 | CEILING.MATH | TRANSLATED | MATCH |  |  |
| lo-mathematical-ceiling.xcl-sheet2-r18 | CEILING | TRANSLATED | MATCH |  |  |
| lo-mathematical-ceiling.xcl-sheet2-r22 | CEILING | TRANSLATED | MATCH |  |  |
| lo-mathematical-ceiling.xcl-sheet2-r27 | CEILING | TRANSLATED | MATCH |  |  |
| lo-mathematical-ceiling.xcl-sheet2-r5 | CEILING | TRANSLATED | MATCH |  |  |
| lo-mathematical-ceiling.xcl-sheet2-r7 | CEILING | TRANSLATED | MATCH |  |  |
| lo-mathematical-exp-sheet2-r2 | EXP | TRANSLATED | MATCH |  |  |
| lo-mathematical-floor.xcl-sheet2-r22 | FLOOR | TRANSLATED | MATCH |  |  |
| lo-mathematical-floor.xcl-sheet2-r27 | FLOOR | TRANSLATED | MATCH |  |  |
| lo-mathematical-floor.xcl-sheet2-r28 | FLOOR | TRANSLATED | MATCH |  |  |
| lo-mathematical-floor.xcl-sheet2-r4 | FLOOR | TRANSLATED | MATCH |  |  |
| lo-mathematical-floor.xcl-sheet2-r7 | FLOOR | TRANSLATED | MATCH |  |  |
| lo-mathematical-int-sheet2-r2 | INT | TRANSLATED | MATCH |  |  |
| lo-mathematical-int-sheet2-r4 | INT | TRANSLATED | MATCH |  |  |
| lo-mathematical-int-sheet2-r5 | INT | TRANSLATED | MATCH |  |  |
| lo-mathematical-ln-sheet2-r2 | LN | TRANSLATED | MATCH |  |  |
| lo-mathematical-ln-sheet2-r3 | LN | TRANSLATED | MATCH |  |  |
| lo-mathematical-ln-sheet2-r4 | EXP, LN | TRANSLATED | MATCH |  |  |
| lo-mathematical-ln-sheet2-r5 | LN | TRANSLATED | MATCH |  |  |
| lo-mathematical-log10-sheet2-r2 | LOG10 | TRANSLATED | MATCH |  |  |
| lo-mathematical-log10-sheet2-r3 | LOG10 | TRANSLATED | MATCH |  |  |
| lo-mathematical-log10-sheet2-r4 | LOG10 | TRANSLATED | MATCH |  |  |
| lo-mathematical-log10-sheet2-r5 | LOG10 | TRANSLATED | MATCH |  |  |
| lo-mathematical-log10-sheet2-r7 | LOG10 | TRANSLATED | MATCH |  |  |
| lo-mathematical-mod-sheet2-r2 | MOD | TRANSLATED | MATCH |  |  |
| lo-mathematical-mod-sheet2-r31 | MOD | TRANSLATED | MATCH |  |  |
| lo-mathematical-mod-sheet2-r33 | MOD | TRANSLATED | MATCH |  |  |
| lo-mathematical-mod-sheet2-r35 | MOD | TRANSLATED | MATCH |  |  |
| lo-mathematical-mod-sheet2-r4 | MOD | TRANSLATED | MATCH |  |  |
| lo-mathematical-mod-sheet2-r6 | MOD | TRANSLATED | MATCH |  |  |
| lo-mathematical-mround-sheet2-r2 | MROUND | TRANSLATED | MATCH |  |  |
| lo-mathematical-mround-sheet2-r3 | MROUND | TRANSLATED | MATCH |  |  |
| lo-mathematical-mround-sheet2-r5 | MROUND | TRANSLATED | MATCH |  |  |
| lo-mathematical-power-sheet2-r5 | POWER | TRANSLATED | MATCH |  |  |
| lo-mathematical-power-sheet2-r6 | POWER | TRANSLATED | MATCH |  |  |
| lo-mathematical-power-sheet2-r7 | POWER | TRANSLATED | MATCH |  |  |
| lo-mathematical-power-sheet2-r8 | POWER | TRANSLATED | MATCH |  |  |
| lo-mathematical-power-sheet2-r9 | POWER | TRANSLATED | MATCH |  |  |
| lo-mathematical-round-sheet2-r12 | ROUND | TRANSLATED | MATCH |  |  |
| lo-mathematical-round-sheet2-r16 | ROUND | TRANSLATED | MATCH |  |  |
| lo-mathematical-round-sheet2-r2 | ROUND | TRANSLATED | MATCH |  |  |
| lo-mathematical-round-sheet2-r6 | ROUND | TRANSLATED | MATCH |  |  |
| lo-mathematical-round-sheet2-r7 | ROUND | TRANSLATED | MATCH |  |  |
| lo-mathematical-round-sheet2-r8 | ROUND | TRANSLATED | MATCH |  |  |
| lo-mathematical-rounddown-sheet2-r11 | ROUNDDOWN | TRANSLATED | MATCH |  |  |
| lo-mathematical-rounddown-sheet2-r16 | ROUNDDOWN | TRANSLATED | MATCH |  |  |
| lo-mathematical-rounddown-sheet2-r3 | ROUNDDOWN | TRANSLATED | MATCH |  |  |
| lo-mathematical-rounddown-sheet2-r7 | ROUNDDOWN | TRANSLATED | MATCH |  |  |
| lo-mathematical-rounddown-sheet2-r8 | ROUNDDOWN | TRANSLATED | MATCH |  |  |
| lo-mathematical-roundup-sheet2-r11 | ROUNDUP | TRANSLATED | MATCH |  |  |
| lo-mathematical-roundup-sheet2-r13 | ROUNDUP | TRANSLATED | MATCH |  |  |
| lo-mathematical-roundup-sheet2-r5 | ROUNDUP | TRANSLATED | MATCH |  |  |
| lo-mathematical-roundup-sheet2-r8 | ROUNDUP | TRANSLATED | MATCH |  |  |
| lo-mathematical-roundup-sheet2-r9 | ROUNDUP | TRANSLATED | MATCH |  |  |
| lo-mathematical-sign-sheet2-r2 | SIGN | TRANSLATED | MATCH |  |  |
| lo-mathematical-sign-sheet2-r5 | SIGN | TRANSLATED | MATCH |  |  |
| lo-mathematical-sign-sheet2-r6 | SIGN | TRANSLATED | MATCH |  |  |
| lo-mathematical-sign-sheet2-r7 | SIGN | TRANSLATED | MATCH |  |  |
| lo-mathematical-sub-sheet2-r4 | (operators) | TRANSLATED | MATCH |  |  |
| lo-mathematical-sum-sheet2-r3 | SUM | TRANSLATED | MATCH |  |  |
| lo-text-concat-sheet2-r2 | CONCAT | TRANSLATED | MATCH |  |  |
| lo-text-concat-sheet2-r3 | CONCAT | TRANSLATED | MATCH |  |  |
| lo-text-concat-sheet2-r4 | CONCAT | TRANSLATED | MATCH |  |  |
| lo-text-concat-sheet2-r5 | CONCAT | TRANSLATED | MATCH |  |  |
| lo-text-concat-sheet2-r6 | CONCAT | TRANSLATED | MATCH |  |  |
| lo-text-concatenate-sheet2-r2 | CONCATENATE | TRANSLATED | MATCH |  |  |
| lo-text-concatenate-sheet2-r3 | CONCATENATE | TRANSLATED | MATCH |  |  |
| lo-text-concatenate-sheet2-r4 | CONCATENATE | TRANSLATED | MATCH |  |  |
| lo-text-concatenate-sheet2-r5 | CONCATENATE | TRANSLATED | MATCH |  |  |
| lo-text-concatenate-sheet2-r6 | CONCATENATE | TRANSLATED | MATCH |  |  |
| lo-text-find-sheet2-r17 | FIND | TRANSLATED | MATCH |  |  |
| lo-text-find-sheet2-r19 | FIND | TRANSLATED | MATCH |  |  |
| lo-text-find-sheet2-r2 | FIND | TRANSLATED | MATCH |  |  |
| lo-text-find-sheet2-r21 | FIND | TRANSLATED | MATCH |  |  |
| lo-text-find-sheet2-r4 | FIND | TRANSLATED | MATCH |  |  |
| lo-text-left-sheet2-r11 | LEFT | TRANSLATED | MATCH |  |  |
| lo-text-left-sheet2-r12 | LEFT | TRANSLATED | MATCH |  |  |
| lo-text-left-sheet2-r13 | LEFT | TRANSLATED | MATCH |  |  |
| lo-text-left-sheet2-r14 | LEFT | TRANSLATED | MATCH |  |  |
| lo-text-left-sheet2-r5 | LEFT | TRANSLATED | MATCH |  |  |
| lo-text-left-sheet2-r7 | LEFT | TRANSLATED | MATCH |  |  |
| lo-text-len-sheet2-r10 | LEN | TRANSLATED | MATCH |  |  |
| lo-text-len-sheet2-r12 | LEN | TRANSLATED | MATCH |  |  |
| lo-text-len-sheet2-r13 | LEN | TRANSLATED | MATCH |  |  |
| lo-text-len-sheet2-r2 | LEN | TRANSLATED | MATCH |  |  |
| lo-text-lower-sheet2-r10 | EXACT, LOWER | TRANSLATED | MATCH |  |  |
| lo-text-lower-sheet2-r2 | LOWER | TRANSLATED | MATCH |  |  |
| lo-text-lower-sheet2-r4 | LOWER | TRANSLATED | MATCH |  |  |
| lo-text-mid-sheet2-r3 | MID | TRANSLATED | MATCH |  |  |
| lo-text-mid-sheet2-r4 | MID | TRANSLATED | MATCH |  |  |
| lo-text-right-sheet2-r11 | RIGHT | TRANSLATED | MATCH |  |  |
| lo-text-right-sheet2-r13 | RIGHT | TRANSLATED | MATCH |  |  |
| lo-text-right-sheet2-r14 | RIGHT | TRANSLATED | MATCH |  |  |
| lo-text-right-sheet2-r15 | RIGHT | TRANSLATED | MATCH |  |  |
| lo-text-right-sheet2-r2 | RIGHT | TRANSLATED | MATCH |  |  |
| lo-text-right-sheet2-r3 | RIGHT | TRANSLATED | MATCH |  |  |
| lo-text-search-sheet2-r10 | SEARCH | TRANSLATED | MATCH |  |  |
| lo-text-search-sheet2-r23 | SEARCH | TRANSLATED | MATCH |  |  |
| lo-text-search-sheet2-r25 | SEARCH | TRANSLATED | MATCH |  |  |
| lo-text-search-sheet2-r26 | SEARCH | TRANSLATED | MATCH |  |  |
| lo-text-search-sheet2-r6 | SEARCH | TRANSLATED | MATCH |  |  |
| lo-text-substitute-sheet2-r2 | SUBSTITUTE | TRANSLATED | MATCH |  |  |
| lo-text-substitute-sheet2-r4 | SUBSTITUTE | TRANSLATED | MATCH |  |  |
| lo-text-textjoin-sheet2-r2 | TEXTJOIN | TRANSLATED | MATCH |  |  |
| lo-text-textjoin-sheet2-r8 | TEXTJOIN | TRANSLATED | MATCH |  |  |
| lo-text-textjoin-sheet2-r9 | TEXTJOIN | TRANSLATED | MATCH |  |  |
| lo-text-trim-sheet2-r2 | TRIM | TRANSLATED | MATCH |  |  |
| lo-text-trim-sheet2-r3 | TRIM | TRANSLATED | MATCH |  |  |
| lo-text-trim-sheet2-r4 | TRIM | TRANSLATED | MATCH |  |  |
| lo-text-upper-sheet2-r2 | UPPER | TRANSLATED | MATCH |  |  |
| lo-text-upper-sheet2-r3 | UPPER | TRANSLATED | MATCH |  |  |
| lo-text-upper-sheet2-r4 | UPPER | TRANSLATED | MATCH |  |  |
| lo-text-upper-sheet2-r5 | UPPER | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-d1280 | SQRT | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-d1312 | SUBSTITUTE | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-d1408 | TRIM | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-d504 | FALSE | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-d796 | ISNUMBER | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-d932 | MOD | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-e1188 | ROUNDUP | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-e136 | AND | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-e1436 | UPPER | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-e476 | EXACT | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-e732 | IF | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-e772 | ISBLANK | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-e876 | LOWER | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-e900 | MID | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-f1216 | SEARCH | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-f7 | (operators) | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-f796 | ISNUMBER | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-f900 | MID | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-f96 | ABS | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-g1068 | POWER | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-g1184 | ROUNDDOWN | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-g264 | CONCATENATE | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-g520 | FIND | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-g876 | LOWER | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-g980 | NOT | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-h1020 | OR | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-h544 | FLOOR | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-h796 | ISNUMBER | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-i1188 | ROUNDUP | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-i1436 | UPPER | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-i51 | (operators) | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-i756 | INT | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-l1408 | TRIM | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-l756 | INT | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-p1408 | TRIM | TRANSLATED | MATCH |  |  |
| poi-formulaevaltestdata_copy-everythingtests-r96 | ABS | TRANSLATED | MATCH |  |  |
| lo-date_time-month-sheet2-r5 | MONTH | — | ORACLE_DISPUTED |  |  |
| lo-date_time-month-sheet2-r6 | MONTH | — | ORACLE_DISPUTED |  |  |
| lo-date_time-networkdays.intl-sheet2-r5 | NETWORKDAYS.INTL | — | ORACLE_DISPUTED |  |  |
| lo-date_time-networkdays.intl-sheet2-r6 | NETWORKDAYS.INTL | — | ORACLE_DISPUTED |  |  |
| lo-date_time-year-sheet2-r2 | YEAR | — | ORACLE_DISPUTED |  |  |
| lo-date_time-year-sheet2-r6 | YEAR | — | ORACLE_DISPUTED |  |  |
| lo-date_time-year-sheet2-r8 | YEAR | — | ORACLE_DISPUTED |  |  |
| lo-logical-switch-sheet2-r9 | SWITCH | — | ORACLE_DISPUTED |  |  |
| lo-mathematical-add-sheet2-r2 | (operators) | — | ORACLE_DISPUTED |  |  |
| lo-mathematical-add-sheet2-r3 | (operators) | — | ORACLE_DISPUTED |  |  |
| lo-mathematical-ceiling.math-sheet2-r17 | CEILING.MATH | — | ORACLE_DISPUTED |  |  |
| lo-mathematical-mround-sheet2-r22 | MROUND | — | ORACLE_DISPUTED |  |  |
| lo-mathematical-mround-sheet2-r6 | MROUND | — | ORACLE_DISPUTED |  |  |
| lo-mathematical-mround-sheet2-r7 | MROUND | — | ORACLE_DISPUTED |  |  |
| lo-mathematical-power-sheet2-r3 | POWER | — | ORACLE_DISPUTED |  |  |
| lo-mathematical-rounddown-sheet2-r14 | ROUNDDOWN | — | ORACLE_DISPUTED |  |  |
| lo-mathematical-sub-sheet2-r3 | (operators) | — | ORACLE_DISPUTED |  |  |
| lo-text-value-sheet2-r10 | VALUE | — | ORACLE_DISPUTED |  |  |
| poi-formulaevaltestdata_copy-everythingtests-h1216 | SEARCH | — | ORACLE_DISPUTED |  |  |
| poi-formulaevaltestdata_copy-everythingtests-j1068 | POWER | — | ORACLE_DISPUTED |  |  |

## Run

- date 2026-10-06T09:03:14+00:00, profile `se-thoughtspot`, connection `APJ_TAB`, ts-cli 0.158.0
- scratch objects: warehouse `AGENT_SKILLS.PUBLIC.ZZ_FIDELITY_M1_20261006T090314_69C17D`, Table `ZZ_FIDELITY_M1_20261006T090314_69C17D_TABLE_DELETE_ME`, Model `ZZ_FIDELITY_M1_20261006T090314_69C17D_DELETE_ME`
- cleanup: ThoughtSpot confirmed absent **True**, warehouse confirmed absent **True**, remaining 0, not owned 0
- startup sweep: 0 ThoughtSpot and 1 warehouse `ZZ_FIDELITY_*` objects from earlier runs (reported, not touched)
- runtime 374.1 s; phases {"load": 0.9, "oracle": 0.0, "translate": 0.1, "ts_import": 109.0, "agentql": 257.3, "teardown": 3.2}
