# Measure Decomposition Rules

Human-readable mirror of the classifier in
[`tools/ts-cli/ts_cli/aggregate/measures.py`](../../../../tools/ts-cli/ts_cli/aggregate/measures.py)
(`classify_measure` / `build_rewrite_plans`). Read this before overriding, extending,
or second-guessing a rewrite plan the CLI produced — the classifier is authoritative
(see the last section).

## Why decomposition exists

Aggregate-model routing is **exact-name-match**: the aggregate Model must expose a
formula (or column) with the *identical*, case-sensitive name as the primary Model's
measure. A `SUM` can just be re-summed at query time, but an `AVG` cannot — averaging
pre-averaged numbers produces the wrong answer. Every measure and formula on the
primary Model therefore gets a **rewrite plan**: what gets stored physically in the
aggregate table, and how the primary's measure name is re-expressed as a formula over
those stored components.

## The decomposition table

| Measure class | Stored in aggregate table | Aggregate-Model expression |
|---|---|---|
| `SUM(x)`, `MIN(x)`, `MAX(x)` | same aggregate function | same function (safe to re-aggregate) |
| `COUNT(*)` / `COUNT(x)` | `COUNT(..) AS x_cnt` | `SUM(x_cnt)` |
| `AVG(x)` | `SUM(x) AS x_sum`, `COUNT(x) AS x_cnt` | formula `x_sum / x_cnt` (components SUM-re-aggregated) |
| Ratio / derived formulas | decompose numerator and denominator if both additive | rebuilt formula over stored components |
| `unique count(x)` / COUNT DISTINCT | **not decomposable**; servable only if `x` is itself in the candidate grain | flagged NONADDITIVE; otherwise the signature stays on the detail Model |
| STDEV / VARIANCE | decomposable (sum, sum-of-squares, count) | deferred to v2 — not implemented |

Source: `docs/superpowers/specs/2026-07-11-ts-object-model-aggregates-design.md` §
Measure decomposition engine (copied verbatim).

## What the classifier actually recognizes

`classify_measure(name, aggregation=None, expr=None)` returns:

```json
{"name": str, "class": "SUM|MIN|MAX|COUNT|AVG|RATIO|NONADDITIVE|UNKNOWN",
 "decomposable": bool,
 "components": [{"alias": str, "source_column": str, "func": str, "reagg": str}],
 "model_expr": "str|None",
 "requires_grain_column": "str|None"}
```

Recognized shapes (case-insensitive on the function keyword):

- **Column aggregation** (no formula, just `properties.aggregation`): `SUM`, `MIN`,
  `MAX`, `COUNT`, `AVERAGE`/`AVG` (rewritten internally to `average ( [col] )` and
  handled by the formula path below), `COUNT_DISTINCT`/`UNIQUE_COUNT` → NONADDITIVE.
  Anything else → `UNKNOWN`.
- **Formula expressions** matched against three patterns:
  - `unique count ( [Col] )` → NONADDITIVE, `requires_grain_column = "Col"`
  - `sum|min|max|count|average|avg ( [Col] )` → SUM/MIN/MAX (direct), COUNT (stored
    as `x_cnt`, re-aggregated as `SUM`), AVG (stored as `x_sum`/`x_cnt`, re-expressed
    as `x_sum / x_cnt`)
  - `sum|count ( [ColA] ) / sum|count ( [ColB] )` → RATIO, numerator and denominator
    each stored and SUM-re-aggregated, re-expressed as `num / den`
  - Anything else (window functions, nested formulas, cross-measure references,
    CASE expressions, any expression ThoughtSpot's formula DSL supports that isn't
    one of the three shapes above) → `UNKNOWN`

`build_rewrite_plans(model_tml)` runs this over every `MEASURE` column and every
`formulas[]` entry on the Model, uniquifying component aliases across the whole
plan set so that two differently-named measures never collide on the same stored
alias (e.g. `"Avg Sale"` and `"Avg-Sale"` both slugging to `avg_sale`).

## TS formula gotchas that apply here

- `unique count(...)` is the correct ThoughtSpot syntax — `count_distinct(...)` is
  **invalid** and will not match the NONADDITIVE pattern (or anything else); a
  formula written with `count_distinct` will classify as `UNKNOWN`, not NONADDITIVE.
  If you see `UNKNOWN` on a measure that looks like a distinct count, check for this
  before assuming it needs manual review.
- `+` does not concatenate strings in ThoughtSpot formulas — use `concat()`. Not
  directly relevant to the numeric classes above, but applies if a hand-written
  rewrite (see below) also touches a string column.

## When the classifier returns UNKNOWN — never guess

**The classifier is authoritative.** Do not override its verdict based on how a
formula "looks" — re-aggregation mistakes are silent and confidently wrong (e.g.
re-summing an already-averaged column produces a plausible-looking but incorrect
number, with no error from ThoughtSpot).

When `class` is `UNKNOWN`:

1. Read the formula's `expr` manually against the shapes listed above. If it's a
   variant the regex-based classifier doesn't recognize (extra whitespace inside
   brackets is fine and matched; a different function name, a nested nested nested
   formula reference, a nested aggregate inside a non-aggregate wrapper is not),
   either:
   - Supply a hand-written component plan for that one measure (a
     `{"alias", "source_column", "func", "reagg"}` list plus a `model_expr`) and
     pass it through the same path `generate.py` consumes, or
   - **Exclude the measure** from the candidate grain. The aggregate table simply
     won't carry it — any signature whose measures include it will not be covered
     by that aggregate (no partial credit; see `lattice.covers`), and those queries
     stay on the primary Model.
2. Never guess additivity to force a measure through. If in doubt, exclude.

This mirrors the rule for [open-items.md](open-items.md) — unverified behaviour
gets a documented fallback, not a silent assumption.
