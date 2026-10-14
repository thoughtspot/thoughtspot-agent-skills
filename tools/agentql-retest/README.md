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

## Three suites

| Suite | Backs | Runs on | Needs |
|---|---|---|---|
| `limitations` | `limitations.md` | the Dunder Mifflin demo Models (SE demo cluster) | `--model-single`, `--model-multi` |
| `guards` | [`limitations.md`](../../agents/cli/ts-object-model-agentql-query/references/limitations.md) § Read-only by design: statements that must **always** be refused | `(Sample) Retail - Apparel` | nothing (found by name). Calls `generate-sql` only, never `fetch-data` |
| `lessons` | [`learning-path.md`](../../agents/cli/ts-object-model-agentql-query/references/learning-path.md), the Learn AgentQL course | `(Sample) Retail - Apparel`, which ships on every cluster | nothing: found by exact name and author `system` (or pass `--model-apparel`) |

`--suite all` (the default) runs all three. A cluster without the Dunder Mifflin Models can
still run the two that need no GUID: `--suite lessons guards` (one or more suite names).

## Run it

```bash
python3 tools/agentql-retest/run.py --profile <ts-profile> \
    --model-single <guid of "DunderMifflin Sales"> \
    --model-multi  <guid of "Dunder Mifflin"> \
    [--only <case id> ...] [--out <file>.json]

python3 tools/agentql-retest/run.py --profile <ts-profile> --suite lessons guards
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
| `BREACH` | a `guards` case compiled to something other than one read-only `SELECT` (a write, DDL, a second statement or a comment got through) | **raise it as a security issue at once**. Do not edit the case to make it pass |

Exit code `0` means everything is as documented, `1` means something changed, `2` means
something errored, and `3` means a breach. Higher outranks lower, so a partial run never
reads as clean and a breach is never hidden behind a change.

**Tracking improvements as they ship.** Each ❌ row has a case that expects it to fail. When
an improvement lands, that case reports `CHANGED` ("now compiles"), which is the signal to
move the row to ✅. A guard is the opposite: it must never change. That is why its verdict
is `BREACH`, not `CHANGED`.

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
| `agentql_retest/cases.py` | The `limitations` cases. Each names the `limitations.md` row it backs |
| `agentql_retest/guards.py` | The `guards` cases: writes, DDL, admin, multi-statement and comment injection. The read-only check is `classify.read_only_problem` |
| `agentql_retest/lessons.py` | The `lessons` cases. Each names the lesson it backs, and each lesson's **Guarded by** line names its cases (a unit test keeps the two in step) |
| `agentql_retest/classify.py` | The `Case` model, the verdict rules and the case-list validator. Pure |
| `tests/` | Verdict-rule tests, including the shipped bespoke checks against real rows. No live calls |

## Adding a case

Add a `Case` to `cases.py`, with `row=` naming the `limitations.md` row it backs, and run
it with `--only <id>` until it reports `AS_DOCUMENTED`. If the construct's failure mode is a
wrong number, give it a control (`same_as` / `differs_from`) or a `check`. A case that only
asserts `SUCCESS` cannot detect the bug it is there for.
