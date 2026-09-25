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
baseline, `2` misconfigured.

Improvements are reported but never fail the run — only regressions do.

## What it measures

**Structural survival** — tables, columns, formulas and joins, in versus out.

**Apache's validator** — every converted document, via the real `validation/validate.py`.

**Cross-vendor portability**, which the validator cannot see:

- *qualified references naming no declared field* — a portable expression that resolves
  against nothing. Valid SQL, so validation passes it (apache/ossie#459).
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

## Requirements

`export` needs the `ts` CLI and a ThoughtSpot profile. `check` needs a converter working
tree with its venv built (`cd converters/thoughtspot && uv sync`) and PyYAML available to
the interpreter running this script.
