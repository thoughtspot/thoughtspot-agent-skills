# agentql-retest

Has a documented AgentQL limitation been fixed, or a fixed one regressed? This suite holds a case
for every row of
[`limitations.md`](../../agents/cli/ts-object-model-agentql-query/references/limitations.md)
for the `ts-object-model-agentql-query` skill that its two demo Models can exercise. It
runs each case live and reports **only the
rows whose behaviour moved**. It is the executable form of that skill's
[use case #6](../../agents/cli/ts-object-model-agentql-query/references/use-cases.md) and of
the refresh procedure in its `open-items.md`.

It is operator-run, not CI-run, because it needs a live cluster. Only its verdict rules are
unit-tested in CI.

## Run it

```bash
python3 tools/agentql-retest/run.py --profile <ts-profile> \
    --model-single <guid of "DunderMifflin Sales"> \
    --model-multi  <guid of "Dunder Mifflin"> \
    [--only <case id> ...] [--out <file>.json]
```

On the SE demo cluster (profile `se-thoughtspot`) the two Models are
`001af1e7-ce2e-4e46-a521-3ee149d92c66` (single table, has a date column) and
`829a3344-657c-4d34-918d-84a7438afb59` (multi-table, `group_aggregate` formulas). The cases
use those Models' column names, so another cluster needs the same Dunder Mifflin demo data.

**Not covered**, because these Models cannot exercise them: Semantic View / Metric View
backed Models, semi-additive and `moving_sum` measures, `join_progressive`, VARIANT/JSON
columns, and a `count_distinct` aggregate-formula measure (SCAL-330560). Those rows stay
hand-probed. Their `limitations.md` dates say when they were last checked.

A full run makes about 150 `ts agentql` calls and takes a few minutes. Use `--only` to re-run a
few cases; the control cases are always added, because the value checks read them. `--out`
keeps the raw results: generated SQL, rows and errors for every case. Write it outside the repo.

## Reading the output

| Verdict | Meaning | Action |
|---|---|---|
| `AS_DOCUMENTED` | the row's documented behaviour reproduced | none (not printed) |
| `CHANGED` | the behaviour moved, in either direction | probe it, then update the row in `limitations.md` (and any rule in `agentql-rules.md` / `udf-reference.md` / `patterns.md` that the row feeds) and the case in `cases.py` |
| `ERROR` | the run could not tell (CLI or auth failure, or a broken control) | fix the run, not the docs |

Exit code `0` means everything is as documented, `1` means something changed, and `2` means
something errored. An error outranks a change, so a partial run never reads as clean.

## Why values, not statuses

The dangerous rows return `SUCCESS` with the wrong number. Here, `QUALIFY` is dropped and
returns 60 rows, `FILTER (WHERE …)` is ignored, and a date-literal `SUM(CASE …)` comes back
empty. A status check would score those as working. So every silent-wrong case carries a
**control** (the same question written in a form that works) and asserts it *differs*. When
it starts to match, the case reports CHANGED with "looks fixed". The ✅ cases check values the
same way: against a control, or hand-computed from one (`STDDEV`, `LAG`, `OFFSET`, `ROUND`).
Literal values appear only for constant expressions (`EXP(1)`, `CHR(65)`), so a data reload
does not read as a behaviour change.

## Layout

| Path | What |
|---|---|
| `run.py` | Entry point: the only I/O (`ts agentql generate-sql` / `fetch-data`) |
| `agentql_retest/cases.py` | The cases. Each names the `limitations.md` row it backs |
| `agentql_retest/classify.py` | The `Case` model, the verdict rules and the case-list validator. Pure |
| `tests/` | Verdict-rule tests, including the shipped bespoke checks against real rows. No live calls |

## Adding a case

Add a `Case` to `cases.py`, with `row=` naming the `limitations.md` row it backs, and run
it with `--only <id>` until it reports `AS_DOCUMENTED`. If the construct's failure mode is a
wrong number, give it a control (`same_as` / `differs_from`) or a `check`. A case that only
asserts `SUCCESS` cannot detect the bug it is there for.
