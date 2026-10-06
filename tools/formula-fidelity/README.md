# formula-fidelity

Does a translated formula return the **right value**? `ts formula translate --validate execute`
proves a formula imports and returns *some* rows. This harness runs each source formula and its
ThoughtSpot translation over the same rows and compares the answers key by key.

Design: [`docs/research/formula-test-cases/harness-design.md`](../../docs/research/formula-test-cases/harness-design.md).
First run (M0, 50 Snowflake SQL cases): [`docs/reviews/2026-10-06-fidelity-m0-snowflake.md`](../../docs/reviews/2026-10-06-fidelity-m0-snowflake.md).
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
| `fidelity/live.py` | The only I/O: Snowflake oracle session, ThoughtSpot import/query/teardown |
| `cases/snowflake/` | `m0.jsonl` (50 cases) and `fixture-m0.json` (10 edge rows) |
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
  later runs report oracle drift (`run.oracle_drift`).
- **`--translate-only`** needs no cluster and no warehouse. It prints each case's translation.
- **`--rebuild runs/<file>.json`** re-classifies a stored run against the current case file, for
  example after a new `known_divergence` tag. It does not re-query anything.

Exit codes:
- `0`: the run completed, whatever the verdicts
- `1`: a scratch object could not be confirmed deleted (the GUIDs are logged)
- `2`: bad arguments or case files

Runtime for M0 (50 cases, 10 rows) was 99 s and 212 s on two runs. About 70% of that is AgentQL:
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
6. **Teardown** (in `finally`):
   - deletes the Model, then the Table, and confirms both are absent by GUID **and** by name
   - drops the warehouse table and confirms it with `SHOW TABLES`

   A startup sweep reports, but never touches, any earlier `ZZ_FIDELITY_%_DELETE_ME` objects.

## Case format

One JSON object per line:

```json
{"id": "sf-date-010", "dialect": "snowflake", "source_formula": "MONTHS_BETWEEN(D2, D1)",
 "role": "row", "fixture": "fixture-m0.json", "group_by": null,
 "expected": {"key_column": "ROW_ID", "values": {"1": {"t": "num", "v": "0.032258"}, "…": {}}},
 "tolerance": {"rel": 1e-12, "abs": 1e-12},
 "provenance": {"source": "authored in-repo", "licence": "Apache-2.0", "date": "2026-10-06"},
 "known_divergence": {"tag": "months-between-fractional", "kind": "translator-bug",
                      "backlog": "BL-342", "reason": "…"},
 "note": "fractional months between two dates (BL-336)"}
```

- **`role`**: `row` (one value per fixture row) or `aggregate` (one value per `group_by` group).
- **`tolerance`**: declared when the case is written. **Never widen it after a failure.**
- **`known_divergence`**: optional, and it never hides anything. The case still runs, a wrong
  value is still MISMATCH, and the report attributes it.
  - `kind: platform-semantics`: a documented ThoughtSpot behaviour the translator warns about, e.g. BL-333 case-insensitive `=`.
  - `kind: translator-bug`: an open BL item. The BL id is required.
- **Values** use canonical types: `null`, `num` (decimal string), `str`, `bool`, `date`,
  `datetime`, `error`.

## Verdicts and comparison rules

| Verdict | Meaning |
|---|---|
| `MISMATCH` | It imported, ran, and returned a different value. Combined with a TRANSLATED or APPROXIMATED status, this is a **silent wrong answer** |
| `RUN_FAILED` | It imported, but the query failed where the source returned a value |
| `IMPORT_FAILED` | ThoughtSpot rejected the translated formula (VALIDATE_ONLY) |
| `TRANSLATE_FAILED` | The translator declined (NEEDS_REVIEW). The case still counts in the denominator |
| `ERROR_EQUIV` | The source errored, and ThoughtSpot returned NULL or an error |
| `ORACLE_FAILED` | The source formula failed on every key, which is an authoring error |
| `MATCH` | Every key is equal |

Rules, all in `compare.py` and pinned by tests:
- **Numbers** compare as `Decimal` within the declared tolerance, so `3 == 3.0`.
- **NULL** equals only NULL. NULL against a value is a mismatch.
- **Booleans** never equal numbers.
- **Strings** are exact and case-sensitive.
- **Dates and datetimes:** an integer where a date is expected is read as epoch seconds (UTC),
  because AgentQL returns DATE formula results as INT64 epoch seconds.
- **Keys:** a key missing on either side is a mismatch.

## Extending (M1 and later)

- **A new SQL dialect** (Databricks) needs a warehouse oracle class beside `Warehouse` in
  `live.py`, plus its case directory. Everything else is dialect-independent.
- **Excel / Sheets (M1)** cases cannot use the warehouse as their oracle. They will carry
  `expected` from their corpus (LibreOffice, POI), and `run.py` needs a stored-oracle path that
  skips step 2. The fixture, translate, import, query, compare and report steps are reused
  unchanged.
- **Third-party cases** need a licence file in their case directory (design §1). M0's cases are
  all authored in-repo.
