# ts-object-model-aggregates — Open Items

Format per [.claude/rules/api-research.md](../../../../.claude/rules/api-research.md).
All items below are **OPEN** — none have been tested against a live ThoughtSpot
instance yet (Task 11, blocked on user availability for `se-thoughtspot`). All must
be **VERIFIED** before this skill merges to `main` (see
[.claude/rules/branching.md](../../../../.claude/rules/branching.md) merge criteria).

Status legend: **VERIFIED** (tested live) | **CONFIRMED** (direction known via MCP/docs,
needs live verification) | **OPEN** (unknown)

---

## #1 — Date re-aggregation — OPEN

**Question:** Can a DAILY aggregate serve a MONTHLY query, or is aggregate routing
exact-bucket-only? ThoughtSpot's docs imply "token-satisfiable = routable" (a coarser
query's tokens are a subset of what the finer aggregate can answer), which is what
[`lattice.bucket_covers`](../../../../tools/ts-cli/ts_cli/aggregate/lattice.py) assumes
(`BUCKETS.index(grain_bucket) <= BUCKETS.index(sig_bucket)` — finer-or-equal serves
coarser).

**Why it matters:** if routing is actually exact-bucket, `bucket_covers` over-claims
coverage — a DAILY aggregate would be recommended for MONTHLY queries it can't
actually serve, and Step 7's routing verification would catch it, but only after the
DDL/TML/association work has already been done.

**Live-test script:** associate a DAILY-bucketed aggregate Model with a primary Model
(`ts aggregate generate` → import), run a MONTHLY-grouped query against the primary
(`ts spotql generate-sql "SELECT DATE_TRUNC('MONTH', ...) ..." --model <primary_guid>`
or a Search/Liveboard tile), inspect `executable_sql` (or the answer's generated SQL)
for the aggregate table's physical name.

**Fallback if refuted:** change `bucket_covers` to equality-only matching — a one-line
change, already called out in that function's docstring.

---

## #2 — `aggregated_models` TML syntax on a live 26.6+ cluster — OPEN

**Question:** Does the shape
[`generate.py::patch_association`](../../../../tools/ts-cli/ts_cli/aggregate/generate.py)
emits — `{id: <name-or-guid>, date_aggregation_info: [{column_id: <date-col>, bucket:
<BUCKET>}]}` appended to the primary Model's `aggregated_models:` list — match what
ThoughtSpot's TML importer actually accepts on a 26.6+ cluster?

**Why it matters:**
[`agents/shared/schemas/thoughtspot-model-tml.md`](../../../../agents/shared/schemas/thoughtspot-model-tml.md)
§ `aggregated_models` explicitly says: *"Do not construct `aggregated_models` from
scratch; aggregate model associations are managed in the ThoughtSpot UI."* Every other
TML block this skill (and its siblings) constructs programmatically has been
live-verified against a real import; this one, uniquely, has an authoritative doc
telling us NOT to do that. Programmatic construction here is a deliberate, flagged
exception to house practice and must be proven correct before shipping, not assumed
correct because the doc's example shape parses.

There is also a **bucket-enum inconsistency inside that same schema doc**: the worked
example shows `bucket: MONTHLY`, but the doc's own enum list for the field is
`DAY | WEEK | MONTH | QUARTER | YEAR` (singular/no `-LY` suffix). `lattice.BUCKETS`
uses `HOURLY|DAILY|WEEKLY|MONTHLY|QUARTERLY|YEARLY` (matching the worked example, not
the enum list) — confirm which form the importer actually accepts before this ships;
if it's the enum-list form, `patch_association` needs a bucket-name translation table.

**Live-test script:** manually associate an aggregate Model to a primary via the
ThoughtSpot UI (the doc's own recommended path), export the primary Model's TML
(`ts tml export {primary_guid} --fqn --parse`), and diff the resulting
`aggregated_models:` block against what `patch_association` would have emitted for
the same association. Also try importing a `patch_association`-emitted TML directly
and confirm ThoughtSpot doesn't reject or silently drop the block.

---

## #3 — Aggregate Model visibility — OPEN

**Question:** Should the aggregate Model be hidden from Search/Spotter browse (it
should never be a direct NL-search target — see the design doc's note that synonyms
are deliberately not copied onto it), and — separately — does a **hidden** Model
still participate in query routing from the primary?

**Why it matters:** if hiding a Model also disables its participation in
`aggregated_models` routing, the skill must NOT hide the aggregate Model (accepting
the UX cost of it being search-discoverable), or must find a different visibility
mechanism.

**Live-test script:** create two aggregate Models associated with the same primary —
one left visible, one hidden via the Model's visibility setting — and confirm a
routed query still resolves to the hidden one's aggregate table.

---

## #4 — Non-additive measure routing — OPEN

**Question:** Does the ThoughtSpot query engine actually refuse to route a
`unique count(x)` query to an aggregate that lacks column `x`, matching
[`lattice.covers`](../../../../tools/ts-cli/ts_cli/aggregate/lattice.py)'s NONADDITIVE
rule (a signature needing a non-decomposable measure is only "covered" when its
`requires_grain_column` is present in the candidate's dimensions)?

**Why it matters:** if the engine routes anyway (treating the aggregate's grain as
"good enough" without checking distinctness), a `unique count` query would silently
return a wrong (double-counted or under-counted) number from the aggregate instead of
falling back to the primary Model. This is the single worst failure mode this skill
could cause — a hard requirement to verify before recommending any aggregate whose
covered signatures include a NONADDITIVE measure.

**Live-test script:** build an aggregate whose grain omits the distinct-count column
of a `unique count(...)` measure that a dependent Answer/Liveboard uses, associate it,
run that query, and confirm (a) the generated SQL still hits the primary table, and
(b) the returned count matches what the primary alone would produce.

---

## #5 — Cross-connection aggregates — OPEN

**Question:** ThoughtSpot's docs say an aggregate Model may live on a different
connection than its primary Model. Is this actually supported end-to-end (DDL on
connection B, `aggregated_models` association still resolves from the primary on
connection A)?

**Why it matters:** this directly affects the connection prompt in Step 6 — if
cross-connection aggregates work, the prompt can legitimately default to "any
connection that can reach a warehouse capable of holding the aggregate table," not
just the primary's own connection. If they don't work, the skill must constrain (or
at least strongly warn on) picking a different connection.

**Live-test script:** register the aggregate table (via `ts tables create`) on a
connection distinct from the one(s) the primary Model's `model_tables` use, import
the aggregate Model against that connection, associate it with the primary, and run
a routed query to confirm it resolves.

---

## #6 — Multi-aggregate precedence — OPEN

**Question:** With two aggregates associated to the same primary Model that both
satisfy a query (e.g. `(Sales × Category)` nested inside
`(Sales × Customer × Category × State)`), does routing follow `aggregated_models`
**definition order** (first match wins), pick the **smallest** satisfying aggregate
regardless of order, or is it unspecified/implementation-defined?

**Why it matters:**
[`generate.py::patch_association`](../../../../tools/ts-cli/ts_cli/aggregate/generate.py)
emits entries **most-aggregated-first** (ascending `projected_rows`) specifically so
that a first-match walk lands on the cheapest satisfying aggregate — correct under
first-match semantics, and harmless (a no-op ordering) if ThoughtSpot instead
auto-picks the smallest candidate itself. If neither theory holds — e.g. routing
picks the *first-created* or *most-recently-associated* aggregate regardless of list
order — the emission order is not just harmless-but-irrelevant, it's actively
misleading documentation of intent and the skill needs a different signal (or to
warn the user that precedence among overlapping aggregates is not controllable).

**Live-test script:** associate both aggregates above to one primary in both
orderings (test A-then-B and B-then-A in the `aggregated_models` list), run a query
matching the narrower `(Sales × Category)` grain in both cases, and record which
aggregate table appears in the generated SQL each time.

---

## #7 — Dependent type-filter values — OPEN (narrow)

**Question:** `ts_cli.commands.aggregate._SIGNATURE_TYPES` filters the dependents walk
to `{"ANSWER", "LIVEBOARD", "PINBOARD_ANSWER_BOOK", "QUESTION_ANSWER_BOOK"}`. This
reuses `_collect_dependents` (the same v2 `metadata dependents` code path, alias-aware,
already live-verified for `ts-dependency-manager` v1.4.0) — the *walk mechanism* is
proven, only the **type-string values** need re-confirming on a current 26.6+ build.

**Why it matters:** if the live walk emits different casing or different literal type
strings on a newer build, every dependent gets silently filtered out and `signatures`
returns zero — an obviously-wrong-looking but silent failure (it looks like "the Model
has no dependents" rather than "the filter is stale").

**Secondary question (no double-counting):** confirm that a Liveboard-embedded Answer
(a `visualizations[].answer` tile) arrives into signature extraction via the
**Liveboard's own TML export** (`extract_signatures` walking `liveboard.visualizations[]`)
and is **not also** separately enumerated as a top-level `QUESTION_ANSWER_BOOK`
dependent — otherwise the same tile's `search_query` would be turned into two
signatures with double weight, skewing coverage/benefit scoring.

**Live-test script:** run `signatures` against a Model with a mix of standalone
Answers and Liveboards-with-embedded-viz-answers on a 26.6+ instance; confirm
`dependents` count and the emitted `signatures.jsonl` entries match 1:1 with the
Answers/Liveboard-tiles actually present (no missing, no doubled).

---

## #8 — Real TML `search_query` token casing — OPEN

**Question:** `ts_cli.aggregate.signatures.extract_signatures` matches `search_query`
tokens against the Model's display-name kinds map
(`column_kinds_from_model`) **case-sensitively**. Do real ThoughtSpot exports ever
lowercase tokens in `search_query` (e.g. `[revenue]` instead of `[Revenue]`)?

**Why it matters:** if real exports lowercase tokens, every signature from a live
Model would come back `partial` (unparseable) regardless of how simple the underlying
query actually is — a systemic under-coverage bug that would look like "most of this
Model's usage can't be analyzed" rather than a casing bug.

**Live-test script:** export a real Answer/Liveboard's TML from a 26.6+ instance,
inspect the raw `search_query` string's token casing against the Model's column
display names.

**Fallback if refuted:** add a case-insensitive fallback to the kinds lookup in
`column_kinds_from_model` / `extract_signatures` (build a lowercased alias map
alongside the exact-case one, prefer exact match, fall back to lowercased).

---

## #9 — WEEK bucket boundary drift — OPEN

**Question:** `DATE_TRUNC('WEEK', ...)` (used by
[`sqlgen._date_trunc`](../../../../tools/ts-cli/ts_cli/aggregate/sqlgen.py) for a
WEEKLY-bucketed aggregate) is **Monday-based** on Snowflake and Databricks,
**Sunday-based** on BigQuery, and ThoughtSpot's own week start is **configurable**
per org. Does a WEEKLY aggregate's `DATE_TRUNC`-computed week boundaries match
ThoughtSpot's own WEEKLY grouping for the same org's configured week start?

**Why it matters:** if they disagree, a WEEKLY aggregate silently reshuffles rows
across week boundaries relative to what a live WEEKLY Search query groups by — wrong
numbers, not a routing failure (so Step 7's SQL-presence check alone won't catch it;
it needs a row-count or value comparison, not just "does the aggregate table appear").

**Live-test script:** on an org with a non-default week-start setting, run the same
WEEKLY grouping through (a) a live Search/SpotQL query against the primary Model and
(b) the aggregate's DDL SELECT, and diff the resulting week-boundary buckets.

**Fallback if refuted:** thread an org week-start parameter into
`sqlgen.build_select`'s `_date_trunc` (Snowflake/Databricks: adjust via an offset;
BigQuery: already Sunday-based, so only Snowflake/Databricks need the adjustment when
the org's week start isn't Monday).

---

## #10 — Filter-precision-vs-bucket (known design limitation, verify impact) — OPEN

**Context:** a query signature carries `date_bucket` (the GROUP BY grain) but **not**
the filter's own date precision — this is a documented design limitation from the
Task 3 build (see `docs/superpowers/plans/2026-07-11-ts-object-model-aggregates.md`
progress notes), not a bug to silently patch.

**Concrete failure shape:** a query grouped MONTHLY but **filtered** on a specific day
(`Order Date = 2026-07-11`) is treated by
[`lattice.covers`](../../../../tools/ts-cli/ts_cli/aggregate/lattice.py) as covered by
a MONTHLY aggregate, because `covers()` only checks that the filter *column* is in the
grain (`filter_columns ⊆ dims | {date_column}`), not the filter's *precision* against
the aggregate's stored bucket. A MONTHLY aggregate has no day-level rows to filter on
— the query would return nothing, or ThoughtSpot's routing itself may refuse to route
it (which would actually be the *safe* outcome — see #1's finer-or-equal question,
which this item is a special case of at the filter level rather than the GROUP BY
level).

**Why it matters:** the advisor may **overstate** what an aggregate actually serves
if this refutes safely (routing rejects it) it's merely an over-generous coverage
estimate; if it does NOT refute safely (routing accepts and returns wrong/empty
results) it's a correctness bug on par with #1/#4.

**Action:** verify impact live (does ThoughtSpot's router notice the filter precision
mismatch, or does the aggregate simply return an empty/wrong result?). Regardless of
outcome, the skill's Step 8 summary must surface this as a standing caveat on every
recommendation report — signatures don't carry filter granularity, so a candidate's
"coverage" number can include queries that filter more precisely than the candidate's
bucket. Step 7's routing verification should include at least one day-filtered query
alongside the plain grouped one for any MONTHLY+ candidate.

---

## #11 — Join-pruning fidelity — OPEN

**Question:** `sqlgen.build_select`'s join-pruning
(`_join_clauses` / `_path_tables` in
[`sqlgen.py`](../../../../tools/ts-cli/ts_cli/aggregate/sqlgen.py)) keeps only the
tables needed by the candidate's selected dimensions/measures. Does this ever drop a
**mandatory INNER join** whose columns aren't referenced by the grain, but whose
presence in the primary Model's canonical query filters out fact rows with an
unmatched (nullable) FK?

**Concrete failure shape:** primary Model's canonical query is
`FACT INNER JOIN DIM ON FACT.dim_id = DIM.id` (drops `FACT` rows where `dim_id` is
NULL or orphaned). A candidate grain that doesn't select any `DIM` column prunes that
join entirely — the aggregate's `SELECT ... FROM FACT GROUP BY ...` (no join) now
includes the orphaned rows the primary's canonical query would have excluded. The
aggregate's row/measure counts would then not match the primary for a query the
advisor claims it "covers."

**Why it matters:** this is a data-correctness bug, not a routing bug — Step 7's
SQL-presence check wouldn't catch it (the aggregate table does get used); only a
row-count or aggregate-value comparison against the primary would.

**Live-test script:** pick (or construct) a Model with a nullable FK on an
INNER-joined dimension; generate a candidate whose grain doesn't select any column
from that dimension; compare `ts aggregate profile`'s `agg_rows`-adjacent measure
totals (e.g. `SUM(Revenue)`) against the same grain queried through the full primary
Model (not just row counts — a measure total is the more sensitive check). If they
diverge, `sqlgen.py` needs an "always include mandatory INNER joins even when
unreferenced by the grain" rule (a design note carried forward from the Task 5
build review).
