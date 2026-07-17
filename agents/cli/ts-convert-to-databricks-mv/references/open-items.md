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

Status: OPEN — known, structurally unavoidable limitation of the `offset:`
primitive; not a bug in the emitter, but must stay visible until Task 18
records a live multi-period fidelity check.

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

Status: OPEN — verification gate, resolved by Task 18's live fidelity matrix
(flips to VERIFIED there, with the matrix's date and finding).

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
caveat) in `docs/audit/2026-07-17-dbx-to-fidelity-matrix.md`.

**Action on completion:** flip this item to VERIFIED with the matrix's date and
a one-line summary of the result; fold any DIVERGENCE findings into
`coverage-matrix.md` as new Notes/Limitations rows rather than leaving them
only in the audit doc.

Status: OPEN — this is the merge gate for the `wip/to-databricks-mv-codify`
branch (per `.claude/rules/branching.md` merge criteria: "all
`references/open-items.md` items in changed skills are VERIFIED... before
opening a PR"). Flips to VERIFIED in Task 18.
