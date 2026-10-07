# formula-fidelity

Does a translated formula return the **right value**? `ts formula translate --validate execute`
proves a formula imports and returns *some* rows. This harness runs each source formula and its
ThoughtSpot translation over the same rows and compares the answers key by key.

Design: [`docs/research/formula-test-cases/harness-design.md`](../../docs/research/formula-test-cases/harness-design.md).
First run (M0, 50 Snowflake SQL cases): [`docs/reviews/2026-10-06-fidelity-m0-snowflake.md`](../../docs/reviews/2026-10-06-fidelity-m0-snowflake.md).
M1 (250 Excel cases, literal oracle): [`docs/reviews/2026-10-06-fidelity-m1-excel.md`](../../docs/reviews/2026-10-06-fidelity-m1-excel.md) — see [M1](#m1-excel-cases-from-a-corpus-outside-the-repo) below.
M2 (98 Databricks SQL cases, Databricks as the oracle): [`docs/reviews/2026-10-07-fidelity-m2-databricks.md`](../../docs/reviews/2026-10-07-fidelity-m2-databricks.md) — see [M2](#m2-databricks-sql) below. Its findings were fixed in ts-cli 0.163.0; the report's "After fixes" section has the re-run (129 cases, 0 silent wrong answers).
It is the formula-level fixture for repo-audit angle 15 (`.claude/rules/repo-audit.md`). It is
operator-run, not workflow-run.

## Layout

| Path | What |
|---|---|
| `run.py` | Entry point: live run, `--translate-only` (offline), `--rebuild` (re-classify a stored run) |
| `fidelity/cases.py` | Case (JSONL) and fixture (JSON) loader. Strict: a malformed case fails the run rather than shrinking the denominator |
| `fidelity/builders.py` | Pure builders for everything a run sends: warehouse SQL, Table/Model TML, AgentQL |
| `fidelity/compare.py` | Canonical values, comparison rules, and the case verdicts |
| `fidelity/report.py` | Markdown report. Leads with silent wrong answers |
| `fidelity/live.py` | The only I/O: Snowflake and Databricks oracle sessions, ThoughtSpot import/query/teardown |
| `run_literal.py` | M1 entry point: `candidates`, `select`, `run`, `rebuild` over a corpus in a data dir outside the repo |
| `crosscheck_formulas.py` | M1 bronze cross-check with the `formulas` library (run in a throwaway uv env) |
| `fidelity/sources.py` | Stdlib readers for LibreOffice `.fods` and Excel `.xlsx`: one formula cell → a scalar case, or a named refusal |
| `fidelity/literal.py` | Data dir, manifest, materialising cases and the input fixture in memory, the `literal` oracle |
| `fidelity/redact.py` | What M1 may commit (redacted results, generated report tables) and the leak scanner |
| `cases/excel/` | `m1-manifest.jsonl` (ids + file + sha256 + locator, no formulas or values) and `m1-selection.json` (counts); `m1-coverage-manifest.jsonl` / `m1-coverage-selection.json`, the 2026-10-07 coverage pass's fresh selection (the cases it newly translates, at most 15 per leading function) |
| `cases/snowflake/` | `m0.jsonl` (114 cases: 50 original, 21 BL-340..343 / #572 guards, 26 `sf-fix-*` — 24 for the M2 fixes and their review, 2 round-trip cases for the to-direction `safe_divide` form (BL-366) — and 17 `sf-trig-*` / `sf-quote-*` / `sf-prec-*` for BL-364 / BL-365) and `fixture-m0.json` (10 edge rows; `S3` holds apostrophes, `I2` large integers) |
| `cases/databricks/` | `m2.jsonl` (141 cases, `ANSI_MODE=true`; 33 `dbx-fix-*` — 31 added with the BL-357..362 fixes, 2 round-trip cases for the to-direction `safe_divide` form (BL-366) — 17 `dbx-trig-*` / `dbx-quote-*` / `dbx-prec-*` for BL-364 / BL-365), `m2-nonansi.jsonl` (7 cases, `ANSI_MODE=false`), and their fixtures: M0's rows as Databricks types |
| `run_raw.py` + `cases/probes/` | A RAW ThoughtSpot formula against a SQL oracle (the translator bypassed through `run.py`'s `Deps.translate` seam), for probing how ThoughtSpot reads a formula — probe record §7 "Quotes and grouping" |
| `runs/` | Run JSON evidence (raw oracle and ThoughtSpot values, compiled SQL, verdicts) |
| `tests/` | Pure-function tests. No live calls |

## Run it

The command needs a ThoughtSpot profile (`ts profiles`) and a **python-method** Snowflake profile
(`/ts-profile-snowflake`). Credentials only ever come from those profiles.

```bash
PYTHONPATH= uv run --no-project --python 3.12 --with pyyaml --with typer --with requests \
    --with keyring --with snowflake-connector-python \
  python -I tools/formula-fidelity/run.py \
    --cases tools/formula-fidelity/cases/snowflake/m0.jsonl \
    --profile se-thoughtspot --sf-profile "ThoughtSpot Partner (AP)" --connection APJ_TAB \
    --out tools/formula-fidelity/runs/<date>-snowflake-m0.json \
    --report docs/reviews/<date>-fidelity-m0-snowflake.md
```

- **`--fill-expected`** writes the oracle's values into the case file's `expected` blocks, so
  later runs report oracle drift (`run.oracle_drift`). See the rules below.
- **`--translate-only`** needs no cluster and no warehouse. It prints each case's translation.
- **`--rebuild runs/<file>.json`** re-classifies a stored run against the current case file, for
  example after a new `known_divergence` tag. It does not re-query anything, and it records the
  rebuild date and the case file's hash beside the live run's hash, so the report shows both.
- **`--fill-expected`** writes only after a run that did not abort, and only for cases whose oracle
  returned values. Drift is computed against the case file as it was before the write.

Exit codes:
- `0`: the run completed and cleaned up, whatever the verdicts
- `1`: the run completed, but a scratch object could not be confirmed deleted (it is logged and
  recorded by name and GUID)
- `2`: bad arguments or case files (including a `--database` / `--schema` that is not a plain
  `^[A-Z_][A-Z0-9_$]*$` identifier)
- `3`: the run aborted, even when cleanup succeeded. A `SystemExit` (the ThoughtSpot client raises
  one on auth failure) or Ctrl-C is re-raised instead, after teardown and after the run JSON and
  report are written

Runtime for M0 (50 cases, 10 rows) was 99 s, 212 s and 88 s on three runs. About 70% of that is AgentQL:
two calls per case, sequential.

## What a run does

1. **Load.** It creates `AGENT_SKILLS.PUBLIC.ZZ_FIDELITY_<FIXTURE>_<stamp>` with plain
   `CREATE TABLE`, never `OR REPLACE`, and inserts the fixture rows. The fixture's `session`
   parameters (`WEEK_START`, `TIMEZONE`, …) are set on the oracle session first.
2. **Oracle.** It runs each source formula as a Snowflake `SELECT`:
   - per row (keyed by the fixture key), or per `group_by` group
   - a query error falls back to one query per key, so a single erroring row records an `error`
     value instead of losing the case
3. **Translate.** It calls the `ts formula translate` engine in-process with a level-1
   `--columns` context: the fixture columns on the run's Table, with the key column flagged so
   `COUNT(*)` counts it.
4. **Import.** It registers the Table on the connection, then VALIDATE_ONLY-imports a Model with
   every translated formula. If that fails, it **bisects** (VALIDATE_ONLY creates nothing), so
   only the bad formulas are recorded as IMPORT_FAILED. It then imports one scratch Model with
   the rest.
5. **Query.** It sends one AgentQL statement per formula: the key column plus that one formula
   (`AGG("f")` for a measure), and nothing else. It also stores `generate-sql` output as the
   attribution evidence.
6. **Teardown** (in `finally`, ThoughtSpot and warehouse in **separate** guarded blocks, so a
   failure or an interrupt in one never skips the other; the run JSON and report are then written
   whatever happened):
   - deletes the Model, then the Table, and confirms each is gone
   - **ownership check:** a GUID the import returned is deleted. A GUID found only by name is
     deleted only when no GUID was recorded for that name *and* it was created at or after the run
     started; any other name match is reported, never deleted. Run names also carry a random
     suffix (`ZZ_FIDELITY_M0_<UTC stamp>_<6 hex>`)
   - drops the warehouse table and confirms it with `SHOW TABLES`

   Startup sweeps report, but never touch, earlier `ZZ_FIDELITY_%_DELETE_ME` ThoughtSpot objects
   and `ZZ_FIDELITY_%` warehouse tables.

**Warehouse principal.** The oracle runs each case's `source_formula` verbatim as SQL. A case file
is executable input, and the principal running it is the only thing bounding it.
- **Snowflake (M0, M1):** it runs under the Snowflake profile's role.
- **Databricks (M2):** it runs under the `Production` profile's service principal, which is also
  the principal the `DBX_DAMIAN` ThoughtSpot connection uses. Its reach, read-only on 2026-10-07
  (`DESCRIBE CATALOG` / `DESCRIBE SCHEMA` and `system.information_schema.schema_privileges`), is
  far wider than the scratch schema:
  - it **owns the catalog** `agent_skills`
  - it owns the schemas `audit_probe`, `default`, `dunder_mifflin` and `business_forecast`
  - it has `SELECT` / `USE SCHEMA` on `analytics`, `ossie` and `plan`

  An owner can grant itself anything in the catalog, and catalogs outside `agent_skills` were not
  checked.

M0, M1 and M2's cases are all authored in-repo, so this was acceptable for them. **Before any
third-party SQL corpus runs on either warehouse**, the oracle must run as a principal confined to
the scratch schema: usage on it, create-table in it, and nothing else. For Databricks this is
**BL-363**.

## Case format

One JSON object per line:

```json
{"id": "sf-date-010", "dialect": "snowflake", "source_formula": "MONTHS_BETWEEN(D2, D1)",
 "role": "row", "fixture": "fixture-m0.json", "group_by": null,
 "expected": {"key_column": "ROW_ID", "values": {"1": {"t": "num", "v": "0.032258"}, "…": {}}},
 "tolerance": {"rel": 1e-12, "abs": 1e-12},
 "provenance": {"source": "authored in-repo, under the repository licence",
                "licence": "LicenseRef-ThoughtSpot-EULA (repo LICENSE)", "date": "2026-10-06"},
 "known_divergence": {"tag": "months-between-fractional", "kind": "translator-bug",
                      "backlog": "BL-342", "reason": "…", "keys": ["1", "2", "3", "4", "7"]},
 "note": "fractional months between two dates (BL-336)"}
```

- **`role`**: `row` (one value per fixture row) or `aggregate` (one value per `group_by` group).
- **`tolerance`**: declared when the case is written. **Never widen it after a failure.**
- **`known_divergence`**: optional, and it never hides anything. The case still runs, a wrong
  value is still MISMATCH, and the report attributes it. **`keys`** lists the keys expected to
  diverge. Derive them from the fixture and the documented behaviour, not by copying a run's
  output. A tag explains only those keys: any other wrong key is reported *unexplained*, and a
  listed key that comes back equal (or a tag on a MATCH) is reported as a **stale** tag.
  `keys: ["*"]` is a case-level tag, e.g. for an import failure, and explains no per-key value.
  - `kind: platform-semantics`: a documented ThoughtSpot behaviour the translator warns about, e.g. BL-333 case-insensitive `=`.
  - `kind: translator-bug`: an open BL item. The BL id is required.
- **Values** use canonical types: `null`, `num` (decimal string), `str`, `bool`, `date`,
  `datetime`, `error`.

## Verdicts and comparison rules

| Verdict | Meaning |
|---|---|
| `MISMATCH` | It imported, ran, and returned a different value. With a TRANSLATED status (or APPROXIMATED with no trap) it is a **silent wrong answer**; with APPROXIMATED and a named trap it is a **warned** wrong answer |
| `RUN_FAILED` | It imported, but the query failed where the source returned a value, returned SUCCESS with 0 rows, or was never reached because the run aborted |
| `IMPORT_FAILED` | ThoughtSpot rejected the translated formula (VALIDATE_ONLY) |
| `TRANSLATE_FAILED` | The translator declined (NEEDS_REVIEW). The case still counts in the denominator |
| `ERROR_EQUIV` | The source errored, and ThoughtSpot returned NULL or an error |
| `ORACLE_FAILED` | The source formula failed on every key, which is an authoring error |
| `MATCH` | Every key is equal |

Rules, all in `compare.py` and pinned by tests:
- **Numbers** compare as `Decimal` within the declared tolerance, so `3 == 3.0`. Cross-type
  equality applies only when the oracle is numeric: a numeric string from ThoughtSpot may equal
  it, but nothing is stripped (`' 7'` is not 7), and a string oracle must match exactly
  (`'007'` ≠ 7).
- **NULL** equals only NULL. NULL against a value is a mismatch.
- **Booleans** never equal numbers.
- **Strings** are exact and case-sensitive.
- **Dates and datetimes:** an integer is read as epoch seconds (UTC) only when its AgentQL
  column is typed INT64 and the oracle's value is a date, because AgentQL returns DATE formula
  results that way. A value that cannot be an epoch (fractional, out of range) is VALUE_DIFF.
- **Keys:** a key missing on either side is a mismatch.

## M1: Excel cases from a corpus outside the repo

**Third-party test data is never committed** (the user's rule, 2026-10-06). The LibreOffice
`.fods` and Apache POI `.xls`/`.xlsx` files, and everything extracted from them, live in a data
dir outside the repo, by convention `~/Dev/ts/formula-fidelity-data/`, with a `PROVENANCE.md`
(URL, pinned commit, licence, sha256 per file). Pass it as `--data-dir` or
`$FORMULA_FIDELITY_DATA`. The harness refuses a data dir inside the repo, and `.gitignore`
makes a misplaced copy un-addable.

| Committed | Not committed (data dir) |
|---|---|
| `run_literal.py`, `crosscheck_formulas.py`, `fidelity/{sources,literal,redact}.py` | the corpus files |
| `cases/excel/m1-manifest.jsonl`: id, source, path relative to the data dir, sha256, locator (sheet + row or cell), function names, cross-check status, flags. **No formula, no value** | `extracted/candidates.jsonl` (formulas, inputs, values), `extracted/crosscheck.json` |
| `cases/excel/m1-selection.json`: aggregate candidate and skip counts | `runs/<date>-excel-m1-full.json` (the full run evidence) |
| `runs/<date>-excel-m1.json`: per case id, status, verdict class, cause. **Redacted** | |
| the review: generated tables plus hand-written repros **in our own words** | |

Three leak guards, weakest first:
- **CI, no data dir:** `tests/test_fidelity_literal.py` scans every committed M1 file for
  formula-shaped text and forbidden keys (`formula`, `expected`, `values`, …). It is a heuristic:
  the 2026-10-06 review measured that about 19% of corpus formulas (short all-numeric calls such
  as a two-argument power) would pass it.
- **With the data dir:** the same test file's exact scan (it runs when `$FORMULA_FIDELITY_DATA`
  is set, and is skipped otherwise) matches every corpus formula, string value and string input,
  as raw text, against **every tracked text file in the repo** (`git ls-files`; widened from the
  M1 files and four prose files by the review of #574, 2026-10-07, which found short corpus
  formulas in tests, docstrings and map rows). Independent matches — a generic constant the repo
  had before the corpus — are listed, each with a reason, in `INDEPENDENT_MATCHES`.
  **Run it before pushing any change.**
- **At write time:** `run_literal.py` refuses to write redacted results or a report (the
  hand-written head included) that contain corpus text.

```bash
D=~/Dev/ts/formula-fidelity-data
UV="PYTHONPATH= uv run -q --no-project --python 3.12 --with pyyaml --with typer --with requests --with keyring"
# 1. every formula cell -> eligible or skipped (reason counted), translated offline
$UV python -I tools/formula-fidelity/run_literal.py --data-dir $D candidates
# 2. bronze cross-check with the `formulas` library (EUPL: a tool in a throwaway env, never imported)
PYTHONPATH= uv run --no-project --python 3.12 --with formulas --with openpyxl \
  python -I tools/formula-fidelity/crosscheck_formulas.py --data-dir $D
# 3. deterministic selection -> manifest
$UV python -I tools/formula-fidelity/run_literal.py --data-dir $D select \
  --manifest tools/formula-fidelity/cases/excel/m1-manifest.jsonl \
  --selection tools/formula-fidelity/cases/excel/m1-selection.json
# 4. live run (adds --with snowflake-connector-python)
$UV --with snowflake-connector-python python -I tools/formula-fidelity/run_literal.py --data-dir $D run \
  --manifest tools/formula-fidelity/cases/excel/m1-manifest.jsonl \
  --results tools/formula-fidelity/runs/<date>-excel-m1.json \
  --report docs/reviews/<date>-fidelity-m1-excel.md \
  --profile se-thoughtspot --sf-profile "ThoughtSpot Partner (AP)" --connection APJ_TAB
# re-classify a stored run without querying: `rebuild --full-run $D/runs/<date>-excel-m1-full.json`
```

**What differs from M0.**
- **Oracle `literal`.** The expected value is the one stored in the corpus: LibreOffice's
  certified `Expected` column (silver) or the value Excel itself cached in a POI workbook (gold).
  `Deps(oracle=…)` in `run.py` is the seam; its default is still M0's warehouse oracle.
- **Cross-check.** Every case is re-evaluated by `formulas` (bronze) on a workbook holding only
  its inputs. A disagreement makes the case **oracle-disputed**: listed, not run, not scored.
- **Inputs.** A formula over constants runs as a constant formula. A formula over cells gets its
  cells renamed to row 1 (`K2`, `K3` → `A1`, `B1`), and each distinct source cell becomes a typed
  column (`X<n>`) of one single-row fixture table, loaded by M0's run-stamped loader. A blank cell
  is `X_BLANK` (NULL).
- **Extraction refuses, and counts, what is not an Excel scalar case:** ranges, other sheets,
  named expressions, inline arrays, volatile or positional functions, LibreOffice-only functions,
  **OpenFormula's own `CEILING`/`FLOOR`** (LibreOffice stores Excel's as `COM.MICROSOFT.*`; the
  bare names have ODF sign rules), LibreOffice-only error codes (`Err:511`), time-of-day values,
  and dates before 1900-03-01 (Excel's fictitious 29 Feb 1900).
- **Classes.** `SILENT_WRONG`, `WARNED_WRONG`, `DIVERGENCE_BLANK` (Excel blank vs NULL),
  `DIVERGENCE_ERROR` (Excel errors, ThoughtSpot returns a value), then M0's loud verdicts,
  `ERROR_EQUIV`, `MATCH`, and `ORACLE_DISPUTED`. Divergences and error-equivalents are never
  counted as matches.

## M2: Databricks SQL

The same pipeline with Databricks as the oracle. A fixture with `"warehouse": "databricks"` names
its column types as `wh_type` (`BIGINT`, `DOUBLE`, `STRING`, `DATE`, `TIMESTAMP_NTZ`, `TIMESTAMP`),
and `run.py` then needs `--dbx-profile` instead of `--sf-profile`:

```bash
PYTHONPATH= uv run --no-project --python 3.12 --with pyyaml --with typer --with requests \
    --with keyring --with databricks-sql-connector --with databricks-sdk \
  python -I tools/formula-fidelity/run.py \
    --cases tools/formula-fidelity/cases/databricks/m2.jsonl \
    --profile se-thoughtspot --dbx-profile Production --connection DBX_DAMIAN \
    --database AGENT_SKILLS --schema AUDIT_PROBE \
    --out tools/formula-fidelity/runs/<date>-databricks-m2.json --report <path>.md
```

- **Topology.** The Table is registered on a ThoughtSpot connection to the **same** Databricks
  workspace and SQL warehouse, so both sides read one Delta table and `sql_*_op` pass-throughs run
  their Databricks SQL. If no such connection exists, M2 cannot score pass-throughs; do not create a
  connection for it without the user's approval.
- **`DatabricksWarehouse`** (`live.py`) connects with `databricks-sql-connector` to the profile's
  `sql_warehouse_http_path`. By default it follows the repo's credential model
  (`.claude/rules/security.md`, `/ts-profile-databricks`). It **does read the secret**: from the
  profile's `secret_env` environment variable, else the OS credential store (service
  `databricks-<slug>`, account = the client id for OAuth M2M, `token` for a PAT). It hands the
  secret in memory to `databricks-sdk`'s `Config(host=…, client_id=…, client_secret=…)`, and never
  logs, prints or writes it. `~/.databrickscfg` is used only when you pass
  `--dbx-cli-profile <name>`, an explicit opt-in: that file holds the secret in plaintext, which
  the profile skill advises against. The run header records which source was used
  (`warehouse_auth`).
- **Session.** The fixture's `session` takes `TIMEZONE` (sent as `SET TIME ZONE '…'`: a SQL
  warehouse rejects `SET timezone = …`), `ANSI_MODE` (boolean) and `LEGACY_TIME_PARSER_POLICY`, and
  nothing else. The run header records each value as **read back** from the session.
- **Names.** Unity Catalog stores names in lower case. Warehouse SQL uses the upper-case run names
  unquoted, and the Table TML spells `db` / `schema` / `db_table` in lower case.
- **Teardown** is M0's: the warehouse table is confirmed gone with
  `SHOW TABLES IN <catalog>.<schema> LIKE '<name>'`, and the startup sweep reports earlier
  `zz_fidelity_*` tables without touching them.
- **ANSI.** ThoughtSpot's own queries over the Databricks connection behaved as **non-ANSI** in
  M2 (BL-358, documented as accepted platform semantics; `ts formula translate` traps it). So an ANSI oracle and ThoughtSpot can disagree on overflow and bad casts, and
  `m2-nonansi.jsonl` measures the legacy semantics separately.

### What M1 does not exercise: DOUBLE grid values

Half the M1 cases are formulas over constants, which the warehouse computes as exact NUMBER
decimals, and the input cells it does read seldom sit exactly on a rounding step. So binary
representation error at a step (`3.0 * 10`, `0.15 * 100`) was never scored, and the 0.161.0
precision snap shipped with a step-jump on exactly those values (found by review,
2026-10-07). The grid is now pinned by a live probe (probe record §7, 13 DOUBLE values × 13
rounding forms) and by `tools/ts-cli/tests/test_scaled_ceil_floor.py`. A future case set
should add a typed fixture of DOUBLE grid values (3.0, 0.15, 0.29, 2.5, 1.1, -200, 0.57,
40.955 and near-steps) for every directed-rounding function, with Excel's 15-digit result as
the oracle.

## Extending

- **A new SQL dialect** needs a warehouse oracle class beside `Warehouse` and
  `DatabricksWarehouse` in `live.py` (`execute`, `keyed`, `table_exists`, optional `orphans` and
  `error_text`), a `warehouse` value in `builders.WAREHOUSES` with its literal and session syntax,
  and its case directory. Everything else is dialect-independent.
- **Third-party cases** follow M1: a manifest in the repo, the corpus in the data dir (the
  design's §1 "one LICENSE file per source directory" was superseded by the user's 2026-10-06
  rule). M0's cases are all authored in-repo, under the repository licence (the ThoughtSpot EULA
  in `LICENSE`, recorded as `LicenseRef-ThoughtSpot-EULA (repo LICENSE)`), not under Apache-2.0.
