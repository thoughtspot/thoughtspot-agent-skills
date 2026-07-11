# ts-object-model-aggregates — Aggregate Model Advisor (Design)

**Date:** 2026-07-11
**Status:** Approved design, pre-implementation
**Feature basis:** ThoughtSpot 26.6.0.cl aggregate-aware Model switching
(https://docs.thoughtspot.com/cloud/26.6.0.cl/model-aggregate-aware)

## Problem

ThoughtSpot 26.6 lets a primary Model declare associated **aggregate Models**
(via an `aggregated_models` TML block). Search/Spotter/Liveboard queries are
transparently routed to an aggregate when its token set fully satisfies the
query, cutting scanned rows by orders of magnitude. But deciding *which*
aggregates to create is manual today: analysts must work out which grains
cover real usage, whether measures survive pre-aggregation, and whether the
compression justifies another object to maintain.

This skill audits a Model's dependent Liveboards and Answers, recommends a
small set of aggregate grains with quantified benefit, and — gated by user
approval at every step — creates the warehouse aggregate tables, the aggregate
Model TML, and the association patch.

**Scope decision:** end-to-end but gated (audit → recommend → user shortlist →
generate DDL/TML/association with confirmation gates). Warehouses: Snowflake
and Databricks in v1.

## Architecture

Deterministic logic lives in `tools/ts-cli` as a new `ts aggregate` command
group (same codify direction as the Tableau parse/classify work, PR #180).
The skill (`agents/cli/ts-object-model-aggregates/`) is thin orchestration:
auth via the existing `ts-profile-*` skills, object picker (must show Owner
column), confirmation gates, and the judgment calls code cannot make
(aggregate naming, ambiguous-formula review, RLS parity sign-off).

### CLI subcommands

| Subcommand | Responsibility | Input → Output |
|---|---|---|
| `ts aggregate signatures` | Fetch the Model's dependents (Liveboards + Answers), export TML, parse every viz/answer into a normalized query signature | `--model <guid>` → `signatures.jsonl` |
| `ts aggregate history` | Mine Snowflake `QUERY_HISTORY` / Databricks `system.query.history` for ThoughtSpot-issued queries against the Model's tables; produce run-frequency weights per signature | warehouse profile → `weights.json` |
| `ts aggregate recommend` | Lattice generalization + greedy weighted set-cover → ranked candidates and marginal-gain curve | signatures + weights (+ profiling results on second pass) → `candidates.json` |
| `ts aggregate profile` | Profiling SQL for top-K candidates: base row count, `COUNT(*) GROUP BY <grain>` per candidate → compression ratios written back | candidates + warehouse profile → updated `candidates.json` |
| `ts aggregate generate` | Emit warehouse DDL, aggregate Model TML, and `aggregated_models` association patch for one approved candidate. Never auto-imports. | `--candidate <id>` → artifact files |

Dependent-walking reuses the `ts-dependency-manager` approach, **including
per-Model alias propagation** (base-name matching misses ~30% of dependents).
TML mining follows `ts-object-model-coach` patterns.

### Query signature (unit of analysis)

```json
{
  "source": {"guid": "...", "name": "...", "type": "liveboard_viz|answer"},
  "dimensions": ["Region", "Product Category"],
  "date_column": "Order Date",
  "date_bucket": "MONTHLY",
  "measures": [{"name": "Revenue", "class": "SUM", "rewrite": {...}}],
  "filter_columns": ["Region", "Order Date"],
  "formulas": ["Avg Order Value"],
  "parse_status": "full|partial"
}
```

`partial` signatures (unparseable tokens) are excluded from coverage but
counted in the report so coverage percentages are honest.

## Measure decomposition engine

A first-class component. Every measure/formula gets a **rewrite plan**: how
its components are stored physically in the aggregate table and how the
measure is re-expressed as a formula in the aggregate Model. Because routing
is exact-name-match, the aggregate Model must expose a formula with the
*identical* (case-sensitive) name as the primary's measure, rebuilt over the
stored components.

| Measure class | Stored in aggregate table | Aggregate-Model expression |
|---|---|---|
| `SUM(x)`, `MIN(x)`, `MAX(x)` | same aggregate | same function (safe to re-aggregate) |
| `COUNT(*)` / `COUNT(x)` | `COUNT(..) AS x_cnt` | `SUM(x_cnt)` |
| `AVG(x)` | `SUM(x) AS x_sum`, `COUNT(x) AS x_cnt` | formula `x_sum / x_cnt` (components SUM-re-aggregated) |
| Ratio / derived formulas | decompose numerator and denominator if both additive | rebuilt formula over stored components |
| `unique count(x)` / COUNT DISTINCT | **not decomposable**; servable only if `x` is itself in the candidate grain | flagged; otherwise the signature stays on the detail Model |
| STDEV / VARIANCE | decomposable (sum, sum-of-squares, count) | deferred to v2 |

Rules are implemented deterministically in the CLI and duplicated as
`references/measure-decomposition-rules.md` so the agent can review formulas
the classifier marks ambiguous. TS formula gotchas apply (`unique count`
not `count_distinct`; `concat()` not `+`).

A candidate that cannot rewrite a signature's measures **does not cover that
signature** — no partial credit.

## Coverage rule (mirrors the routing engine)

Candidate grain `G = (dims, date_col, bucket, stored measure components)`
covers signature `S` iff:

1. `S.dimensions ⊆ G.dims`
2. `S.filter_columns ⊆ G.dims` — filters need their columns present
3. `S.date_bucket` is coarser-or-equal to `G.bucket` on the same date column
   (vacuously true when `S` has no date column; a dated `S` is never covered
   by a dateless `G`)
4. every `S.measure` has a valid rewrite plan against `G`'s components

## Candidate generation & scoring

**Lattice generalization:** signatures are generalized up a lattice — the
date-bucket ladder (HOURLY < DAILY < WEEKLY < MONTHLY < QUARTERLY < YEARLY)
crossed with dimension supersets formed by unioning signature dimension sets
whose Jaccard similarity ≥ 0.5 (tunable). Candidates are lattice points
covering ≥ 2 signatures, pruned
by a width guard (grain > 8 columns is flagged; wide grains rarely compress).

**Two-pass scoring:**

1. Rank candidates by weighted coverage:
   `coverage(G) = Σ weight(S) for covered S`, where `weight` is the
   query-history run frequency (default 1 when history is unavailable —
   coverage-only mode with an explicit caveat).
2. Profile only the top-K (default 10): base row count and
   `COUNT(*) GROUP BY <grain>` per candidate. Then re-rank by
   `benefit(G) = Σ weight(S) × (base_rows − agg_rows)` (scan-rows saved).

**Greedy marginal-gain selection:** repeatedly pick the highest-benefit
candidate, remove its covered signatures, recompute. The report presents the
diminishing-returns curve, e.g.:

> #1 (Region × Product, MONTHLY): 58% of weighted queries, 240× compression
> +#2 (Store, DAILY): → 79% · +#3: → 85% · +#4: → 87%

The **user chooses the cut-off** — the maintenance-cost judgment stays human.
Soft flags, not hard rules: compression < 10×, grain > 8 columns, candidate
covering only stale/unviewed objects.

## Generation (per approved candidate, three gated artifacts)

Each artifact is shown to the user before anything executes or imports.

1. **Warehouse DDL** — Snowflake: dynamic table (configurable `TARGET_LAG`,
   default 1h), CTAS fallback. Databricks: materialized view, CTAS fallback.
   Naming `<BASE>_AGG_<grain summary>`, user confirms/edits. SELECT is built
   from the rewrite plans (stored components, not display measures).
2. **Aggregate Model TML** — single logical table over the aggregate table.
   Column and formula names copied exactly (case-sensitive) from the primary.
   Decomposed measures rebuilt as formulas. `is_spotter_enabled: true`
   (programmatic Models default false → Spotter error 10004). Synonyms are
   deliberately **not** copied — the aggregate should not win NL search
   directly (visibility handling is Open Item #3).
3. **Association patch** — `aggregated_models` block (with
   `date_aggregation_info` when the grain has a date bucket) added to the
   primary Model TML. The primary TML is **backed up first**
   (ts-dependency-manager pattern); rollback is a single import.

Import gotchas honoured: root `guid:` + `--no-create-new` to update in place;
Table TML `table.schema` validates against the connection.

## Safety rails

- **RLS/CLS parity is a hard gate.** If the primary Model has RLS rules or
  CLS, the skill displays what parity requires and refuses to import the
  aggregate Model until the user explicitly confirms replicated rules. A fast
  aggregate that leaks rows across tenants is worse than no aggregate.
- All steps idempotent — re-running against the same Model updates existing
  artifacts rather than duplicating.
- Connection selection at generation time follows the standing rule: prompt
  the user; never silently reuse an existing connection.

## Routing verification

After import, per candidate:

1. Fire a test query that *should* route to the aggregate; fetch its generated
   SQL (answer SQL endpoint) and confirm it references the aggregate table.
2. Fire a detail-grain query and confirm it still falls back to the primary.

Pass/fail lands in the final report. A failed verification offers rollback of
the association patch (restore backed-up primary TML).

## Error handling

| Failure | Behaviour |
|---|---|
| Dependent TML export fails | Skip object, count in report |
| Unparseable viz/search tokens | Signature marked `partial`, excluded from coverage, counted ("12 of 87 signatures unparseable") |
| No warehouse profile configured | Coverage-only scoring with explicit "compression unestimated" caveat |
| Profiling SQL timeout | Fall back to sampling / `APPROX_COUNT_DISTINCT` |
| Routing verification fails | Report + offer association rollback |

## Testing

- **Unit (pytest, `tools/ts-cli`):** signature parser, decomposition
  classifier, lattice generation, coverage rule, greedy scorer — fixture TMLs
  with dunder-mifflin as the golden model.
- **Live smoke:** `se-thoughtspot` profile (password auth; champ-staging
  tokens 401). The smoke run doubles as verification of the open items below.

## Open items (verify live before/during implementation)

1. **Date re-aggregation:** can a DAILY aggregate serve a MONTHLY query, or is
   routing exact-bucket? Docs imply token-satisfiable = routable. The
   lattice's coarser-or-equal rule depends on this; fall back to exact-bucket
   matching if wrong.
2. **`aggregated_models` TML syntax** on a live 26.6+ cluster (docs example
   only; id/`date_aggregation_info`/`column_id` shapes unverified).
3. **Aggregate Model visibility:** should aggregate Models be hidden from
   search/browse? Verify whether a hidden Model still participates in routing.
4. **Non-additive measure routing:** confirm the engine refuses to route
   `unique count` queries to an aggregate lacking the distinct column (i.e.
   our coverage rule matches actual routing behaviour).
5. **Cross-connection aggregates:** docs say the aggregate may live on a
   different connection — verify, since it affects the DDL/connection prompt.

## Out of scope (v1)

- STDEV/VAR decomposition; HLL sketches for approximate distinct counts.
- Automatic refresh-lag tuning of dynamic tables/materialized views.
- Monitoring drift (usage changes → aggregate set stale) — natural future
  `ts-audit` integration.
- Recommending aggregates from ad-hoc query history *shapes* alone (history is
  a weighting signal only in v1, not a candidate generator).
