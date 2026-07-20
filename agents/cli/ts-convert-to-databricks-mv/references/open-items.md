# Open Items — ts-convert-to-databricks-mv

Tracks unverified behaviour, deferred work, and known gaps in the codified
`ts databricks build-mv` emit path (`tools/ts-cli/ts_cli/databricks/mv_emit*.py`,
`mv_build_view.py`). For a full construct-by-construct mapping, see
[coverage-matrix.md](coverage-matrix.md).

Status: OPEN | VERIFIED | DEFERRED | WONT-FIX

---

## #1 — Worksheet input is not supported — OPEN (known limitation)

`ts databricks build-mv` reads Model TML (`model_tables[]`, `columns[]`) only — it
has no understanding of a Worksheet's `worksheet_columns[]` shape. SKILL.md's
Step 3 "Model-only gate" stops before Step 5 and directs the user to convert or
promote the Worksheet to a Model first.

**Scope-decision needed:** the skill's frontmatter description still reads
"Convert or export a ThoughtSpot Worksheet or Model into a Databricks Metric
View" — a mismatch with the Model-only reality of the codified path. Task 20
(version-bump pass) should decide whether to narrow the description to "Model"
only, or add an explicit "(Worksheets: convert to a Model first)" caveat.

Status: OPEN — scope decision deferred to Task 20; the functional gap itself is
a permanent design boundary (the emitter's input parsing simply does not cover
Worksheet TML), not a bug to fix.

---

## #2 — `sql_view`-backed tables have no `build-mv` path — OPEN (known limitation)

`ts databricks build-mv` reads raw Table TML in `--tables` only. A `sql_view`
object (parsed YAML top-level key `sql_view`) passed through crashes with a
`KeyError`-shaped failure rather than a clean skip — there is no `sql_view`
handling in `mv_emit.build_column_index`/`build_joins`.

**Handling today:** SKILL.md's Step 4 sql_view classification (Simple/Complex →
Create/Map/Skip) already exists for the from-scratch agentic flow, but the
deterministic `build-mv` path only supports the **Skip (S)** outcome — Create
(C) and Map (M) produce a Databricks view that cannot be fed back into
`build-mv`'s `--tables` argument. Step 4 now explicitly recommends **S** for
the deterministic path and logs Create/Map choices as a manual follow-up
outside the skill.

Status: OPEN — no automated fallback exists; this is a structural gap in the
emitter's input shape, tracked here so it isn't rediscovered as a surprise
crash.

---

## #3 — Period-offset `sum_if(diff_months(...) = N, [m])` mapping is a lossy approximation — OPEN (known limitation)

**Finding (Task 9, carried forward; reference currency anchor 2026-07-09):**
`mv_emit_window._emit_period_offset_window` maps a `*_if(diff_months/diff_quarters([d],
today()) = N, [m])` condition-first formula to a Databricks MV `window: [{range:
current, offset: N month}]` measure. Databricks' `offset:` is **row-relative**
(a LAG-style shift by N rows in the `order:` dimension), evaluated per output
row's own period — it is **not** anchored to wall-clock `today()` the way the
ThoughtSpot source formula reads.

**Consequence:** the mapping is numerically exact only for a query returning a
single current-period snapshot row. It silently diverges on any query spanning
more than one period in the `order:` dimension — e.g. a "prior month revenue"
column queried across a 12-month trend does not return "revenue from the
calendar month before `today()`" at every row; it returns "revenue from the
row-relative prior period," which is actually the *more useful* reading for a
MoM/YoY growth-% column but is **not** what the ThoughtSpot source formula
literally encodes.

`agents/shared/mappings/ts-databricks/ts-databricks-formula-translation.md`'s
"Period Filter (flow/additive metrics)" section documents this in detail and
flags its own previous mapping as superseded by this row-relative "moving_sum
LAG idiom" (matrix C6/C6a, live-verified 2026-07-09 at month grain N=1 only;
quarter/year grains and N=12 are extrapolated, not separately live-tested —
matrix C8, deferred).

**Action:** Task 18's live numeric-fidelity gate (see #8 below) must include at
least one multi-period query against this construct to confirm the divergence
is understood and acceptable, not just theoretically documented.

**Task 18 (2026-07-18) recorded the live multi-period check** — see
`docs/audit/2026-07-18-dbx-to-fidelity-matrix.md` Finding 2. A two-month fixture
(Electronics spanning June/July, Furniture July-only) confirmed live: ThoughtSpot
computes `Monthly Amount`/`Prior Month Amount` as wall-clock-scoped scalars
(current = 1000/550, prior = 500/0, invariant of how many periods exist);
Databricks computes the same-named measures as row-relative, per-period-bucket
values (`GROUP BY category, month_txn_date` returns one row per existing
period, `prior_month_amount` a `LAG(1)` over that category's own sequence).
The numbers happened to coincide at the current-period row in this fixture (a
coincidence of having only two adjacent periods), but the shape (full per-month
trend table vs. one wall-clock snapshot per category) and edge-case
representation (`NULL` vs `0` for "no such period") both diverge. Confirmed
understood and acceptable, not a translation-fidelity blocker.

Status: OPEN — known, structurally unavoidable limitation of the `offset:`
primitive; not a bug in the emitter. The Task 18 live multi-period check this
item was waiting on is now recorded above; remains OPEN as a documented,
accepted approximation with no code fix scheduled.

---

## #4 — `filter:` string not scanned by the dangling-reference cascade — OPEN (known limitation)

**Finding (Task 10, carried forward):** `mv_emit._cascade_skip_dangling_refs`
removes any emitted `dimensions[]`/`measures[]` entry whose `expr` references a
`MEASURE()`/`ANY_VALUE()` machine name that isn't itself among the successfully
emitted columns (running to a fixed point for transitive chains). It does
**not** scan the MV's combined top-level `filter:` string — a filter formula
that references a since-cascade-skipped measure/LOD dimension by name could
leave a dangling reference in `filter:` undetected.

**Why this is low-severity in practice:** an MV `filter:` is a row-level
`WHERE` clause. `MEASURE()`/`ANY_VALUE()` (both aggregate/window-scoped
constructs) are not valid inside a `WHERE` clause in the first place — a
ThoughtSpot boolean filter formula that references a cross-measure or LOD
dimension by name would already be a modeling error upstream of this emitter,
independent of this gap.

**Action:** if a live fidelity check (or a user report) ever surfaces a real
dangling-`filter:` case, extend `_cascade_skip_dangling_refs` to also scan
`filter_exprs` before `_combine_filters` runs.

Status: OPEN — known limitation, not scheduled for a fix (no known real-world
trigger case; see rationale above).

---

## #5 — Measure-attribution DFS mis-attributes condition-first formula measures — OPEN (known limitation)

**Finding (Task 13, carried forward):** `mv_emit._measure_column_table` resolves
a formula-backed `MEASURE` column's owning table via a depth-first walk for the
formula's *first* physical `[TABLE::COL]` reference (`_first_col_ref_table`).
For a condition-first formula such as `sum_if(diff_months([DIM::order_date],
today()) = 0, [FACT::revenue])`, the DFS visits the condition argument first
and can attribute the measure to `DIM`, not `FACT`.

`detect_fact_tables`'s join-root filter (a real fact table is never itself the
target of another table's join) masks this for detection in the common case —
a mis-attributed measure lands on some *other* table's excluded join-target
dimension, and the walk still finds the true fact via its other (properly
attributed) measures.

**Consequence:** a model whose fact table's *only* `MEASURE` columns are
condition-first formulas (no plain physical measure at all) is under-detected —
`detect_fact_tables` can return zero facts, or exclude the true fact.

**Workaround:** `build-mv` fails loud in this case (`no fact table detected`)
and the CLI's error message directs the user to pass `--source-table`
explicitly (`ts_cli/commands/databricks.py:build_mv_cmd`).

Status: OPEN — known limitation with a documented, fail-loud workaround; not
scheduled for a fix because the failure mode is already safe (explicit error,
no silently-wrong output).

---

## #6 — `source.`-prefix in a single-source MV's `filter:`/exprs needs live verification — OPEN (Task 18 verification gate)

**Finding (Task 8, carried forward):** `mv_emit.make_col_resolver` always
prefixes a physical column reference from the source (fact) table with
`source.` — e.g. `SUM(source.AMOUNT)`, `source.REGION = 'West'` — regardless of
whether the MV has any `joins:` block at all. This is consistent for every
emitted expression (dimensions, measures, LOD, window `order:` dims, and the
`filter:` string), but it has only been unit-tested, never confirmed against a
live Databricks warehouse for a **single-source MV with no joins**.

`agents/shared/schemas/databricks-metric-view.md`'s own summary table (line
~711: "Column references | Direct column name | Direct (single-source) or
`alias.column` dot-path (multi-source)") documents bare column names for
single-source MVs and reserves `source.`/alias dot-paths for the multi-table
(joined) case — a documentation/implementation tension that has not yet been
resolved by a live test.

**Action:** Task 18's live numeric-fidelity gate must include at least one
single-source (no-join) MV in its query battery and confirm `source.COL`
parses and returns the correct value on a real warehouse. If it fails, the fix
is either (a) `make_col_resolver` should omit the `source.` prefix when
`dot_path_by_table` has no join entries, or (b) the schema doc's "Direct
column name" row should be corrected to `source.column` for single-source too.

**VERIFIED 2026-07-18** — `docs/audit/2026-07-18-dbx-to-fidelity-matrix.md`.
The entire fidelity-gate model was single-source, no-`joins:` (one physical
table, `SALES_FIXTURE`/`sales_fixture`, zero joins in `model_tables[]`), and
the emitted MV used `source.`-prefixed column references throughout
(`source.category`, `source.amount`, `source.txn_date`, etc. — 14 such
references across 6 dimensions and 8 measures). The DDL created successfully
on a live Databricks warehouse (statement 5) and every query in the battery
(statements 6–10) returned correct values. `make_col_resolver`'s
always-`source.`-prefix behavior is correct for single-source MVs; no emitter
change needed. The schema doc's "Direct column name" row for single-source MVs
should be corrected to reflect `source.column`, not a bare column name (Task 20
version-bump pass, or opportunistic fix on next touch of that file).

Status: VERIFIED 2026-07-18 — resolved by Task 18's live fidelity matrix.

---

## #7 — 2-argument `{0}`-template SQL pass-through form is not implemented — OPEN (known limitation)

`mv_emit_sql._emit_passthrough` accepts exactly one argument — a single string
literal that is unwrapped and emitted as raw SQL
(`sql_string_op("LOWER(some_col)")` → `LOWER(some_col)`). The 2-argument
`{0}`-template form documented in
`ts-databricks-formula-translation.md` ("SQL Pass-Through Functions" —
`sql_string_op("get_json_object({0}, '$.path')", [T::COL])`, the JSON-path
pattern) is **not** implemented in the codified emitter: passing 2 arguments
raises `UntranslatableError` ("pass-through expects exactly one argument").

**Workaround:** rewrite the source formula as the single-argument form,
inlining the column reference directly into the SQL string (e.g.
`sql_string_op("get_json_object(some_col, '$.path')")`), before running
`build-mv`.

Status: OPEN — known limitation; the single-arg form covers the common case
(the pass-through's own "already-complete SQL string" contract), and 2-arg
template support is not yet scheduled.

---

## #8 — Live numeric fidelity of the codified emit path — OPEN (Task 18 merge gate)

Every mapping in `coverage-matrix.md` reflects unit-tested emitter behavior
(pure dict-in/dict-out transforms, verified via `tools/ts-cli/tests/`) plus, for
several window/LOD/filter constructs, live-verified numeric fidelity from the
**reverse** (Databricks → ThoughtSpot) direction's audit matrices
(`docs/audit/2026-07-08-dbx-window-claim-matrix.md`,
`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`). Neither of those matrices
exercises this skill's own **forward** (ThoughtSpot → Databricks) emit path
end-to-end against a live Databricks warehouse and a live ThoughtSpot instance.

**Gate:** Task 18 seeds fixtures on Databricks, builds/points a ThoughtSpot
Model at them, runs `ts databricks build-mv` to produce the DDL, creates the
Metric View on Databricks, and runs a query battery (≥1 per construct family —
plain aggregate, filtered aggregate, LOD partition, moving_sum, cumulative,
semi-additive, cross-measure, plus the single-source `source.`-prefix case
from #6 and a multi-period query against the period-offset lossy mapping from
#3) against both the ThoughtSpot Model and the Databricks MV side-by-side,
recording actual numbers and marking each row CONFIRMED or DIVERGENCE (with
caveat) in `docs/audit/2026-07-18-dbx-to-fidelity-matrix.md`.

**Action on completion:** flip this item to VERIFIED with the matrix's date and
a one-line summary of the result; fold any DIVERGENCE findings into
`coverage-matrix.md` as new Notes/Limitations rows rather than leaving them
only in the audit doc.

**VERIFIED 2026-07-18** — `docs/audit/2026-07-18-dbx-to-fidelity-matrix.md`.
Ran the full forward gate: seeded a 20-row single-source fixture on Databricks,
built a ThoughtSpot Model over it (8 formulas covering plain SUM, COUNT
DISTINCT, filtered/conditional aggregate, an LOD partition, a cumulative
window, a trailing-3-day window, period-offset current/prior month, and a
cross-measure ratio), ran the worktree's `ts databricks build-mv`, created the
emitted MV on Databricks, and ran a query battery of 8 constructs against both
platforms. **Result: 7/8 CONFIRMED, 2 expected DIVERGENCEs** (gapped
trailing-window row-positional-vs-date-interval, mirroring the reverse-
direction E1 finding; period-offset row-relative-vs-wall-clock, resolving #3
above), **and 1 live emitter bug found** — see new item #9 below and
`coverage-matrix.md` L10. Also resolved #6 above (VERIFIED). Full teardown
confirmed (Databricks schema dropped, ThoughtSpot model+table deleted, both
independently verified empty).

Status: VERIFIED 2026-07-18 — this was the merge gate for the
`wip/to-databricks-mv-codify` branch (per `.claude/rules/branching.md` merge
criteria). All other open items in this file are VERIFIED or documented,
known, accepted limitations — see #9 below for the one new item this gate
surfaced.

---

## #9 — Formula-backed "raw measure" ratios emit without their aggregation wrapper — RESOLVED/VERIFIED 2026-07-18

**Finding (Task 18, live-verified 2026-07-18):** a MEASURE-type ThoughtSpot
formula built from a scalar function (`safe_divide`, but the gap is general —
see below) over two **plain physical** MEASURE columns — e.g.
`safe_divide([Amount], [Qty])`, both `Amount`/`Qty` plain `aggregation: SUM`
columns, no LOD/formula operand on either side — is emitted by
`mv_emit.emit_measure`'s formula-backed branch **without** wrapping the result
in the column's declared `aggregation` property. The physical-column branch of
the same function does this correctly (`_physical_measure_expr(dot_path,
props.get("aggregation"))`); the formula-backed branch calls `_formula_sql` →
`emit_sql` directly and assigns the raw result as `expr`, with no equivalent
wrapping step.

**Live reproduction:**
- `ts spotql classify-columns --model <guid>` classifies this exact formula as
  `"kind": "raw_measure"`, `"aggregation": "SUM"`, `"wrapper": "SUM"` —
  ThoughtSpot's own query engine treats it as an unaggregated per-row
  expression and applies `SUM(...)` at query time. Confirmed via `searchdata`:
  the live TS number is `Σ(amount_i / qty_i)` (sum-of-ratios: 1300 / 100 on the
  Task 18 fixture), not `Σamount / Σqty` (ratio-of-sums: 115.38 / 10.0).
- The emitted Databricks DDL for the same formula:
  `expr: COALESCE(source.amount / NULLIF(source.qty, 0), 0)` — no `SUM(...)`,
  no `window:` block, not an aggregate expression at all.
- Creating the MV with this measure included fails on a live Databricks
  warehouse: `[MISSING_AGGREGATION] The non-aggregating expression "..." is
  based on columns which are not participating in the GROUP BY clause. ...
  SQLSTATE: 42803`. This is a **hard failure for the entire `CREATE OR REPLACE
  VIEW` statement** — every dimension/measure in the same MV, not just the one
  bad formula.

Full write-up: `docs/audit/2026-07-18-dbx-to-fidelity-matrix.md` Finding 1;
tracked in `coverage-matrix.md` as L10 (row 58 cross-referenced).

**Scope:** not specific to `safe_divide` — any formula-backed MEASURE column
whose top-level parsed AST is not itself an aggregate call (arithmetic over
two or more physical measures: `[Amount] - [Qty]`, `[Amount] * 1.1`, etc.)
would hit the same gap.

**Recommended fix (not applied — this task reports bugs, it does not patch the
emitter):** in `mv_emit.emit_measure`'s formula-backed branch, when the parsed
formula's outermost node is not already an aggregate call, wrap the translated
SQL in `{aggregation}(...)` from `col["properties"]["aggregation"]` (default
`SUM`, matching the physical-column branch's own default). `spotql_ops.py`'s
existing `is_aggregate_expr`/`classify_expr` may be directly reusable rather
than re-deriving an equivalent check inside the Databricks emitter.

**Workaround (pre-fix):** rewrite the source formula so the aggregation is
explicit and self-contained before running `build-mv`, e.g.
`safe_divide(sum([Amount]), sum([Qty]))` rather than referencing two
already-aggregated measure columns by name — the `sum(...)` wrapping does get
correctly emitted as `SUM(source.amount)` since it's a recognized top-level
aggregate call, not a bare column/ref. No longer required now that the fix
below ships, but harmless to keep doing.

**Fix applied (2026-07-18):** `mv_emit.emit_measure`'s formula-backed branch
now calls `mv_emit_sql.wrap_measure_if_needed(expr, aggregation)` on the
translated SQL before assigning it to `expr`. That combinator checks
`is_aggregate_present(expr)` — true if `SUM(`/`COUNT(`/`AVG(`/`MIN(`/`MAX(`/
`STDDEV(`/`VARIANCE(`/`MEDIAN(`/`MEASURE(`/`ANY_VALUE(` or a window `OVER`
appears ANYWHERE in the emitted SQL string (presence-based, not "outermost
AST node is a call") — and only wraps in `{aggregation}(...)` (via
`wrap_in_aggregation`, same `AGG_MAP`-derived keyword set the physical-column
branch's `_PROP_AGG_TO_DBX` uses, default `SUM`) when no aggregate is present.
This is exactly why `safe_divide([Amount],[Qty])` over two RAW physical-column
refs gets wrapped (`COALESCE(source.amount / NULLIF(source.qty, 0), 0)` has no
aggregate anywhere → `SUM(COALESCE(...))`) while the cross-measure form
`safe_divide([Quantity],[Category Quantity])` — whose operands resolve via
`ref_resolver` into `MEASURE(quantity)`/`ANY_VALUE(category_quantity)` — is
left unwrapped, matching the Dunder golden test's `Category Contribution
Ratio` assertion (`COALESCE(MEASURE(quantity) / NULLIF(ANY_VALUE(category_quantity), 0), 0)`,
no outer `SUM`). The wrap matches ThoughtSpot's own live-confirmed
`raw_measure` + SUM-at-query-time semantics (this open item's original
finding). Unit-tested in `tools/ts-cli/tests/test_databricks_emit.py`
(`TestEmitMeasureRawMeasureWrap`, `TestIsAggregatePresent`); the Dunder golden
test (`test_databricks_to_golden.py`) re-run clean, confirming the
cross-measure case is still not double-wrapped. Not re-verified live against
Databricks post-fix — the mechanism (ThoughtSpot's `raw_measure`+SUM wrapper)
was already live-confirmed during the Task 18 gate; this fix only makes the
emitter match that already-confirmed semantics, offline unit-tested.

Status: RESOLVED/VERIFIED 2026-07-18 — see
`mv_emit_sql.is_aggregate_present`/`wrap_in_aggregation`/`wrap_measure_if_needed`
and `mv_emit.emit_measure`.
