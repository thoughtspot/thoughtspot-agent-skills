# ts-object-model-aggregates — Open Items

Format per [.claude/rules/api-research.md](../../../../.claude/rules/api-research.md).
All items below are **OPEN** — none have been tested against a live ThoughtSpot
instance yet (Task 11, blocked on user availability for `se-thoughtspot`). All must
be **VERIFIED** before this skill merges to `main` (see
[.claude/rules/branching.md](../../../../.claude/rules/branching.md) merge criteria).

Status legend: **VERIFIED** (tested live) | **CONFIRMED** (direction known via MCP/docs,
needs live verification) | **OPEN** (unknown) | **IMPLEMENTED** (coded + unit-tested, live
check pending) | **DEFERRED** (explicit non-v1 decision, tracked as a follow-up)

---

## #0 — Does routing fire + trigger condition — VERIFIED 2026-07-13 (aggregate-aware cluster 172.32.87.7)

**RESULT: routing works, and fires ONLY for FORMULA measures — not plain
measure columns.** A `[Agg Test Sales] [Product Category]` query (where
`Agg Test Sales` = a formula `sum([DM_ORDER_DETAIL::LINE_TOTAL])`) routed to the
aggregate table `DM_AGG_CAT_MONTHLY` (192 rows, single table, no joins) instead
of the 1.2M-row detail fact — confirmed via real-time
`DUNDERMIFFLIN.INFORMATION_SCHEMA.QUERY_HISTORY`. Three prior tests that queried
the plain `Amount` **measure column** did NOT route. Product limitation (per
product owner, now confirmed): default-aggregation switching on measure columns
is not yet coded, so only formula measures trigger the switch. Fires via the
**Search Data API** (no UI needed). Re-aggregation also demonstrated (a dateless
query re-summed the month-grain aggregate).

**Tooling consequences (must implement — see [[routing-formula-measure-consequences]]):**
1. `generate.build_aggregate_model_tml` must expose EVERY measure as a formula
   `sum(component)` (even direct SUM), never a plain measure column — else the
   aggregate won't route. Matches the real `DM_AGGR_PRODUCT_MONTHLY` pattern.
2. The skill must target formula measures (plain measure columns can't benefit),
   and/or recommend promoting measure columns to formulas.
3. `patch_association` id should be the aggregate model GUID (name is ambiguous
   against the equally-named backing table → `DUPLICATE_OBJECT_FOUND`).

**Update 2026-07-14 (Task 17): consequences 1 and 3 are now IMPLEMENTED.**

1. `measures.classify_measure` now sets `model_expr` for the direct-additive
   classes (SUM/MIN/MAX) — e.g. SUM → `"sum ( [alias] )"` — so every
   decomposable plan has a non-None `model_expr` (COUNT/AVG/RATIO already did).
   `generate.build_aggregate_model_tml` no longer has a "plain column" branch:
   every decomposable measure emits a hidden stored component (carrying its
   `reagg`) plus a formula named exactly as the primary measure, over that
   component. No aggregate model exposes a plain MEASURE column under a
   primary measure's own display name any more. Guarded by a round-trip test
   (`test_sum_min_max_formula_survives_dump_and_lint_clean` in
   `tools/ts-cli/tests/test_agg_generate.py`) confirming the emitted formula
   survives `tml_common.dump_tml_yaml` + `tml_lint.lint_tml` clean and the
   `expr` stays exactly `sum ( [alias] )` — `formula_common.fix_double_aggregation`
   only rewrites `sum([formula_X])` references (formula cross-refs), and a
   stored component's alias is never a formula name, so it's never touched.
2. `ts aggregate generate` gained `--agg-model-guid`, threaded into the new
   `aggregated_models` entry's `id` in `commands/aggregate.py`'s
   `_patch_and_write_primary` (falls back to the aggregate Model's display
   name with a stderr warning when omitted — e.g. the first, pre-import
   `generate` pass, before the GUID exists). SKILL.md Step 6 now reorders:
   6b generates provisionally (no GUID yet, warned) → 6f imports the
   aggregate Model and captures its GUID → **new 6f.1** re-runs `generate`
   with `--agg-model-guid <guid>` to regenerate `primary_patched.tml.yaml`
   keyed correctly → 6g imports that (GUID-keyed) file. Task 16's
   single-aggregate/idempotence behavior (dedup-by-id, last-wins) is
   untouched — `patch_association` doesn't care whether `id` is a name or a
   GUID.

Item #1 (which candidate class this consequence narrows down to — item 2
above, "target formula measures") remains open at the recommendation-scoring
level; only the TML-emission and association-id mechanics are closed here.

Residual: SpotQL-vs-SearchData routing (does `ts spotql generate-sql` reflect the
switch?) still unconfirmed — secondary, affects only Step 7's verification method.

## #0 (historical) — original OPEN text

**Context (2026-07-12):** champ-staging (26.9.0.cl-31) does not route — a
grain+name+bucket-matched Search Data query against a primary with an associated
aggregate scanned the DETAIL tables (verified via real-time
`DUNDERMIFFLIN.INFORMATION_SCHEMA.QUERY_HISTORY()`; `ACCOUNT_USAGE` has ~45-min
latency and is unusable for this). Likely champ-staging isn't a working
routing environment right now (a dedicated aggregate cluster is being set up).

**Verification method (ready to run on a working cluster):** POST
`/api/rest/2.0/searchdata` with `{query_string, logical_table_identifier}` →
read `<DB>.INFORMATION_SCHEMA.QUERY_HISTORY()` in real time → confirm the
scanned physical table is the aggregate, not the detail fact.

**Two things to establish on the working cluster, in order:**
1. Does routing fire for a **Search Data API** query? (Expected yes per product
   owner.) This unblocks #1/#4/#6/#10 verification.
2. Does **`ts spotql generate-sql`** reflect routing, or only the Search Data /
   Spotter execution path? (Earlier assumption that SpotQL ignores routing is
   UNPROVEN — on champ-staging nothing routed, so the two paths were
   indistinguishable. May be an open item for the SpotQL team.) This decides
   how the skill's **Step 7 routing-verification** must observe routing —
   currently Step 7 inspects SpotQL SQL, which may not surface routing.

## #1 — Date re-aggregation — VERIFIED 2026-07-13 (aggregate-aware cluster 172.32.87.7)

**RESULT: finer-serves-coarser confirmed — `bucket_covers` is correct as written.**
Against a MONTHLY aggregate (`DM_AGG_CAT_MONTHLY`): a **monthly** query routed to
it (exact bucket); a **yearly** query routed to it and re-aggregated
(`EXTRACT(YEAR FROM TXN_MONTH)`, months→years); a **daily** query correctly fell
back to the detail fact (the monthly aggregate can't produce daily grain). This
matches `lattice.bucket_covers` (`BUCKETS.index(grain) <= BUCKETS.index(sig)`)
exactly — **no equality-only fallback needed.** (Tested with a formula measure so
routing was in play — see #0.)

### #1 (historical OPEN text)

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

## #2 — `aggregated_models` TML syntax on a live 26.6+ cluster — VERIFIED 2026-07-11 (champ-staging, 26.9.0.cl-31)

**Finding:** A live production model on champ-staging ("Dunder Mifflin Sales &
Inventory", `4da3a07f`) carries a real, ThoughtSpot-accepted block:
`aggregated_models: [{id: "DM_AGGR_PRODUCT_MONTHLY", date_aggregation_info:
[{column_id: "Transaction Date", bucket: "MONTHLY"}]}]`. This matches
`patch_association`'s emitted shape exactly:
- `date_aggregation_info` is a **list** (confirms the Task 6 dict→list fix).
- `bucket` uses the **`-LY` form** (`MONTHLY`), matching `lattice.BUCKETS` — the
  schema doc's `MONTH` enum list is wrong; **no translation table needed**.
- `id` is a string identifier (the aggregate model's name); `column_id` is the
  date column's **display name**, matching what `patch_association` uses.
Structure of the associated aggregate model (`DM_AGGR_PRODUCT_MONTHLY`,
`b07f3aaf`) also validates `generate.build_aggregate_model_tml`: single logical
table, `properties.spotter_config.is_spotter_enabled: true` (confirms the Task 6
nested-path deviation), grain columns named to match the primary, SUM measures
exposed under the primary's display names via `sum()` formulas over the stored
column. **Residual (minor):** we matched an exported live block and validated
structure; still worth one direct import of a `patch_association`-emitted block
to confirm write-acceptance, but the shape risk is resolved.

**Update 2026-07-12 (real multi-date TML evidence):** a fuller live block
(exported "Dunder Mifflin Sales & Inventory") shows shapes our code does NOT
yet produce — track as follow-ups:
```yaml
aggregated_models:
  - id: CM_AGGR_SHIPPED_ORDER_DATES_COMPANY
    date_aggregation_info:
    - {column_id: Transaction Date, bucket: DAILY}
    - {column_id: Shipped Date,     bucket: NO_BUCKET}   # <-- multiple date cols + NO_BUCKET
  - id: DM_AGGR_PRODUCT                                   # <-- no date_aggregation_info (dimensional only)
  - id: DM_AGGR_PRODUCT_MONTHLY
    date_aggregation_info: [{column_id: Transaction Date, bucket: MONTHLY}]
  - id: DM_AGGR_CUSTOMER_MONTHLY
    date_aggregation_info: [{column_id: Transaction Date, bucket: MONTHLY}]
```
Gaps this surfaces:
1. **Multi-date aggregates** — `date_aggregation_info` is a list of *N* date
   columns, each with its own bucket. Our `lattice` candidate carries a single
   `date_column`+`bucket`, and `patch_association` emits a single-element list.
   v1 = single-date only (document as a limitation); multi-date is a follow-up
   (both candidate generation and `patch_association` would extend).
2. **`NO_BUCKET`** is a valid bucket value (date carried at full grain) not in
   `lattice.BUCKETS`; maps to our raw-date (`date_bucket=None`) concept — add
   `NO_BUCKET` emission when a date column is present but ungrouped.
3. Confirms multi-aggregate-per-primary is common (≥4 here) → `#6` precedence
   matters in practice; and confirms `date_aggregation_info` is optional
   (dateless aggregate `DM_AGGR_PRODUCT`), which our code already handles.

**Update 2026-07-12 (Task 15 — emission side): gaps 1 and 2 above are now
SUPPORTED.** `sqlgen.build_select` iterates every grain in
`candidate["date_grains"]`, emitting `DATE_TRUNC(...)` for a bucketed grain
and the plain column (no truncation) for a raw grain (`bucket=None`), all
joined into the same GROUP BY. `generate._grain_columns` (shared by
`build_aggregate_table_spec` and `build_aggregate_model_tml`) emits an
ATTRIBUTE column for every date grain, not just the first. `patch_association`
emits one `date_aggregation_info` entry per grain, mapping internal
`bucket=None` to the string `"NO_BUCKET"` at the emission boundary only —
`lattice.BUCKETS` is untouched. Single-date candidates (1 grain) are
byte-identical to pre-Task-15 output (verified by test + full suite green).
**Update 2026-07-12 (Task 16 — CLI wiring + re-patch idempotence): residual
above is CLOSED.** `commands/aggregate.py`'s `_patch_and_write_primary` now
threads the just-generated aggregate's full `cand["date_grains"]` (falling
back to the single-date `date_column`/`bucket` shim only when absent) into
its `patch_association` entry, so a multi-date candidate's association is no
longer collapsed to one date column. A latent bug surfaced alongside this:
the primary's EXISTING `aggregated_models` entries carry `date_aggregation_info`
(the real live-TML shape), not `date_grains`/`date_column` — re-feeding them
through `patch_association` unconverted read no grains at all and silently
stripped every existing entry's date association on re-patch (harmless with
one aggregate, real with two+). Fixed via a new pure helper,
`date_aggregation_info_to_grains` (`ts_cli/aggregate/generate.py`), the exact
inverse of `patch_association`'s emission mapping (`"NO_BUCKET"` <-> internal
`bucket=None`); `_patch_and_write_primary` uses it to reconstruct each
existing entry's `date_grains` before re-patching. Covered by an emit∘parse /
parse∘emit round-trip test (incl. a NO_BUCKET grain) and a command-level
idempotence test: a primary with an existing single-date aggregate (A) plus a
newly generated multi-date aggregate (B, incl. NO_BUCKET) — re-patch keeps
A's `date_aggregation_info` byte-for-byte and emits B's full list, ordered
most-aggregated-first; running `generate` again against the same starting
primary produces byte-identical output. CLI now threads multi-date end-to-end
and re-patch is idempotent — no further residual here.

## #2 (historical) — original OPEN text retained below for reference

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

## #6 — Multi-aggregate precedence — VERIFIED 2026-07-13 (aggregate-aware cluster 172.32.87.7)

**RESULT: first-match by `aggregated_models` definition order — NOT auto-smallest.**
With two aggregates both able to serve a category query (`DM_AGG_CAT`, 8 rows, and
`DM_AGG_CAT_MONTHLY`, 192 rows): listing `DM_AGG_CAT` first → it won; reversing so
`DM_AGG_CAT_MONTHLY` was first → it won. So routing takes the **first** satisfying
entry in list order. This confirms `patch_association`'s most-aggregated-first
ordering (ascending `projected_rows`, None last) is **load-bearing and correct** —
emitting smallest-first is exactly what makes the cheapest satisfying aggregate win.
Refinement (tracked): existing entries reconstructed from a primary's TML carry no
`projected_rows` (sort last); persist/re-derive row counts so a genuinely-smaller
existing aggregate isn't ordered after a larger new one under first-match.

### #6 (historical OPEN text)

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

## #7 — Dependent type-filter values — VERIFIED 2026-07-11 (champ-staging, 26.9.0.cl-31)

**Finding:** `ts aggregate signatures --model 0e4406c7 --profile champ-staging`
returned **50 dependents** and **188 signatures** (63 full / 125 partial), 0
export failures. The type-string filter matches what the v2 dependents walk emits
on 26.9 — dependents are found, not silently zero-filtered. (Double-counting
sub-check still worth a spot audit on a Liveboard-with-embedded-answers, but the
1:1 mechanism held — no obvious doubling in the 188 vs 50 relationship given
multi-viz Liveboards.)

## #7 (historical OPEN text below)

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

## #8 — Real TML `search_query` token casing — VERIFIED 2026-07-11 (champ-staging, 26.9.0.cl-31)

**Finding:** Real exported `search_query` strings preserve the model's
display-name casing exactly — e.g. `growth of [Amount] by [order date]
[order date].monthly [Company] [Product]`, `[Amount] [Country]`, `sum [Amount]
[Product]`. Tokens like `[Amount]`/`[Company]`/`[Product]` match the model's
column display names case-for-case; the lowercase `[order date]` matches because
that column's display name is *literally* lowercase, not because tokens are
lowercased. The case-sensitive lookup in `column_kinds_from_model` /
`extract_signatures` is correct against live exports — **no case-insensitive
fallback needed**. (Separately observed: the ~67% partial rate on this model is
expected — driven by parameter tokens, `growth of…` headline constructs, and
columns outside the kinds map — the conservative "exclude from coverage, count
it" design, not a casing failure.)

## #8 (historical OPEN text below)

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

## #11 — Join-pruning fidelity — OPEN (rule now IMPLEMENTED; live check pending)

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

**Update (final whole-branch review fixes):** the deterministic
"always-include-mandatory-INNER-joins" rule this item called for is now
**IMPLEMENTED** in `sqlgen.py` — `_mandatory_inner_tables` walks the join BFS
spanning tree and force-retains any table whose direct join edge is an
unconditional `INNER` (regardless of whether its columns are in the selected
grain), on the reasoning that an INNER join can only ever reduce the row set, so
retaining one unreferenced is always safe (at worst an unnecessary join, never
wrong numbers). `LEFT_OUTER`/`RIGHT_OUTER`/`OUTER` joins to unreferenced tables are
still pruned (they don't change the root row set). Covered by
`test_inner_joined_unreferenced_table_is_retained` and
`test_left_outer_joined_unreferenced_table_is_pruned` in
`tools/ts-cli/tests/test_agg_sqlgen.py`. The pre-existing star-schema pruning test
(`test_star_join_pruned_to_needed_tables`) asserted an INNER-joined, unreferenced
DIM2 got pruned — under the new rule that assertion is no longer correct (an
unreferenced INNER-joined DIM2 must now be retained), so that test's DIM2 join type
was changed to `LEFT_OUTER` to preserve its original intent (pruning a genuinely
optional/unreferenced dimension) rather than deleting the coverage.

**Remaining live-test script (why this item stays OPEN):** pick (or construct) a
Model with a nullable FK on an INNER-joined dimension; generate a candidate whose
grain doesn't select any column from that dimension; compare `ts aggregate
profile`'s `agg_rows`-adjacent measure totals (e.g. `SUM(Revenue)`) against the same
grain queried through the full primary Model (not just row counts — a measure total
is the more sensitive check) to confirm the aggregate's counts now match the base
model for covered queries on a live instance. The rule is implemented and unit-
tested; only this live-instance confirmation is outstanding.

---

## #12 — `referencing_join` resolution (Task 12) — IMPLEMENTED 2026-07-12

**Update:** `sqlgen.build_select` previously raised `UnsupportedModelError` on any
`referencing_join` in `model.model_tables[].joins[]` — but real ThoughtSpot models
express joins predominantly this way (system-inferred), not via inline `on:`, so
this made connected-mode DDL generation fall back to manual SQL for most real
models. `_collect_edges` / `_resolve_referencing_join` in
[`sqlgen.py`](../../../../tools/ts-cli/ts_cli/aggregate/sqlgen.py) now resolve
`referencing_join` pointers against the source table's own `table.joins_with[]`
entry (matched by `name`), reusing the existing `_JOIN_COND` rewrite and join-type
map exactly as the inline `on:` path does. The open-item #11 mandatory-INNER-
retention rule composes correctly through resolution — it reads the resolved
`type`, so a resolved INNER `referencing_join` to an unreferenced table is still
retained. Graceful degradation is preserved: a missing source table TML, a source
table with no `joins_with`, or a `referencing_join` name with no matching
`joins_with` entry all raise `UnsupportedModelError` (never a silent dropped join).
Verified against real 26.9 champ-staging shapes (Dunder Mifflin Sales —
`DM_ORDER_DETAIL` → `DM_ORDER` → `DM_CUSTOMER` referencing_join chain, plus mixed
inline+referencing_join models). Covered by 8 new tests in
`tools/ts-cli/tests/test_agg_sqlgen.py` (single-hop resolve, multi-hop chain,
missing-joins_with, missing-table-TML, name-not-found, mixed inline+referencing,
INNER-retained, LEFT_OUTER-pruned). **Connected-mode DDL generation is no longer
limited to models using only inline `on:` joins.**

---

## #13 — Snowflake 2-step flat materialized view — DEFERRED (future enhancement, non-blocking)

**Context:** live-tested on Snowflake `AGGR_AWARENESS` (Task 13): a materialized view
whose definition **joins more than one table** is rejected with error `002212`
("Invalid materialized view definition. More than one table referenced in the view
definition."); a materialized view with `GROUP BY` on a **single table** is fine. Since
every non-trivial aggregate candidate this skill generates joins the star's fact table
to at least one dimension, Snowflake materialized views are not usable directly for
aggregate DDL — [`sqlgen.build_ddl`](../../../../tools/ts-cli/ts_cli/aggregate/sqlgen.py)
now raises `UnsupportedModelError` for `dialect="snowflake"` + `materialization="mview"`,
and [SKILL.md Step 6a.1](../SKILL.md#6a1--choose-the-materialization) only offers
Snowflake users a **dynamic table** (joins natively, auto-refresh, needs a warehouse) or
a **plain table** (CTAS, manual refresh) — never a materialized view.

**Deferred option — the 2-step flat MV:** Snowflake materialized views *can* still serve
an aggregate if the join is done first: (1) create a flat, single-table view or table
that pre-joins the star (fact + dimensions) with no aggregation, then (2) create the
actual materialized view as a `GROUP BY` over *that* flat object (single-table
reference, so `002212` doesn't apply). This gets Snowflake auto-refresh semantics
without a dynamic table's warehouse dependency, at the cost of a second object to
maintain (the flat view/table) and, if the flat layer is itself a plain view rather
than a materialized one, the join re-executes on every MV refresh anyway — the
performance case for it over a dynamic table needs to be established, not assumed.

**Why it's not built in v1:** the dynamic table already covers the "I want
auto-refresh" case for Snowflake with a single object and no extra maintenance surface;
the 2-step flat MV only helps if a warehouse genuinely isn't available for scheduled
dynamic-table refreshes but a Snowflake-native auto-refresh is still wanted. That's a
narrower case than v1's two-option (dynamic/plain) split covers, and building it means
generating and gating a *second* DDL artifact per candidate (the flat layer) — real
scope, not a one-line addition to `build_ddl`.

**Candidate future enhancement:** if requested, this would need (a) a new
`materialization` value (e.g. `"flat_mview"`) in `sqlgen.py` that emits both the flat
object DDL and the MV-over-flat DDL, (b) a Step 6 gate for the extra artifact/import,
and (c) a live-test to confirm Snowflake's automatic-refresh behavior on an MV built
over a flat *view* (vs. a flat *table*) actually refreshes downstream when the
underlying star tables change — not otherwise assumed here. Not scheduled; recorded so
the `002212` guard's rationale and the considered alternative aren't lost.
