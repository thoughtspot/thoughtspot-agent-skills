# ossie-roundtrip

Round-trips **real** ThoughtSpot Models through the Apache Ossie converter and reports
what survived.

## Why this lives here and not upstream

The converter is in [apache/ossie](https://github.com/apache/ossie), where CI has no
ThoughtSpot cluster and never will. This is the check that cannot live there.

It has earned its keep. Four defects were found this way that a 940-test suite, Apache's
own validator and five rounds of code review all missed — because every one of them is
invisible to document-level validation:

| Defect | Why nothing else saw it |
|---|---|
| `with` omitted from a referencing join | Passes the Ossie schema and Apache's validator; ThoughtSpot rejects the import |
| A bare `group_aggregate` lost its column `aggregation` | Valid document, changed answer |
| Formulas no `columns[]` entry surfaces were dropped | 32 of 41 formulas in one real model |
| A field's portable expression named a warehouse column, not a field | 211 of 612 references; valid SQL, so the validator passes it |

The last one is the clearest case for this tool: **both the broken and the fixed converter
pass Apache's validator 31/31.** Only the round trip tells them apart.

## Use

```bash
# once, with a cluster: build a corpus
python3 roundtrip.py export --profile se-thoughtspot --corpus ./corpus --limit 30

# thereafter, offline, against any converter revision
python3 roundtrip.py check --corpus ./corpus \
    --converter ~/src/ossie/converters/thoughtspot
```

`check` needs no cluster, so it is the rerunnable half — point it at a converter working
tree before opening a PR upstream.

### As a regression gate

```bash
python3 roundtrip.py check --corpus ./corpus --converter <path> --work ./before
# ... change the converter ...
python3 roundtrip.py check --corpus ./corpus --converter <path> --work ./after \
    --baseline ./before/summary.json
```

Exit codes: `0` clean, `1` a model lost structure / failed / regressed against the
baseline / **had a check skipped**, `2` misconfigured.

Improvements are reported but never fail the run — only regressions do.

## What it measures

**Structural survival** — tables, columns, formulas and joins, in versus out.

**Apache's validator** — every converted document, via the real `validation/validate.py`.

**Column names**, not just counts — a Model column that comes back renamed is reported and
fails the run. Counts cannot see it: tables, columns, formulas and joins were all unchanged
on 5 of 31 real models whose columns were renamed, one of them carrying saved questions
that still name the old column (apache/ossie#468).

**Cross-vendor portability**, which the validator cannot see:

- *qualified references naming no declared field* — a portable expression that resolves
  against nothing. Valid SQL, so validation passes it (apache/ossie#459). Scanned over
  **fields and metrics**, with quoted identifiers counted.
- *metrics carrying a portable dialect* — a metric with only a `THOUGHTSPOT` expression is
  **dropped outright** by every vendor converter, so this is the number that decides
  whether a converted model means anything outside ThoughtSpot.

**Issue-code tally** — the converter's own warnings and errors, aggregated, so noise
regressions show up.

## Two traps it already handles

**A converter's `.venv` is not relocatable.** It records an absolute path to the source
tree it was created from, so a copied checkout silently keeps importing the *original* —
the run reports on code you are not testing, and reports it as a pass. This tool pins
`PYTHONPATH` to the converter you pointed it at. (`tests/conftest.py` prepends the local
`src/`, so pytest is immune; only the CLI path is exposed, which is the path used here.)

**A missing validator is not a failing validator.** An earlier revision recorded
"validator FAILED" for all 31 models when `validate.py` was simply absent. It now refuses
to start and tells you to pass `--validator`.

**Measuring half the document reads as measuring all of it.** An earlier revision scanned
only a dataset's `fields` for unresolvable references and reported `0/0` on output where
**348 of 348 metric references** named a column no field declares — a defect of exactly the
kind this harness exists to catch, in output it had just called clean. It was found by an
independent adversarial review, not by this tool. It now scans both, and its count agrees
with that review's (348/348).

**A skipped check is not a passing check.** Apache's validator degrades silently when
`sqlglot` is absent — it prints a warning, then prints `Validation PASSED`, and exits
zero. An earlier revision looked only for that second line, so every run against a
converter venv without sqlglot reported a clean 31/31 with no SQL expression parsed at
all. With sqlglot present the real figure at the time was 29 passed and 2 failed, on
output already reported as valid. The verdict is now three-state — `PASSED`, `FAILED`,
`SKIPPED` — and a skipped check **fails** the run rather than warning, because a quiet
"some checks did not run" is the exact shape of defect this harness exists to catch.

## Requirements

`export` needs the `ts` CLI and a ThoughtSpot profile. `check` needs a converter working
tree with its venv built (`cd converters/thoughtspot && uv sync`) and PyYAML available to
the interpreter running this script.

The converter's venv is also the interpreter Apache's validator runs under, so it needs
the validator's own optional dependencies — **`sqlglot`, `pyyaml`, `jsonschema`**. Without
`sqlglot` the SQL half of validation does not run, and the harness fails the run rather
than reporting a pass.
