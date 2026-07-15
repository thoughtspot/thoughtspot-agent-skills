# ts-object-model-aggregates — Open Items

Format per [.claude/rules/api-research.md](../../../../.claude/rules/api-research.md).

**Status (updated 2026-07-14):** the core behaviours have been VERIFIED live on the
aggregate-aware cluster: **#0, #1, #2, #6, #7, #8, #10** verified, and the
DDL-from-SpotQL path (#14) proven end-to-end (a generated aggregate matched the detail
total exactly). **#11, #12, #14, #15** are IMPLEMENTED + unit-tested with a live re-check
pending; **#13** is DEFERRED (explicit non-v1). The remaining OPEN items — **#3** (model
visibility), **#4** (non-additive routing, guarded by the `lattice.covers` NONADDITIVE
rule), **#5** (cross-connection), **#9** (WEEK boundary drift) — are lower-priority
edge-case behaviours, each with a runnable live-test script, and are gated behind the
skill's mandatory Step-7 routing verification (every recommendation is provisional until
that check passes). **#17** (RLS propagation) is WIRED end-to-end, its known import bugs
are FIXED, and its identical-rule dedup + pass-2 fail-closed hardening (Task 26) are DONE
— only the live leak-test and the flat-shape confirmation remain OPEN. Per
[.claude/rules/branching.md](../../../../.claude/rules/branching.md), these satisfy the
"explicitly deferred to a follow-up open item" merge clause.

Status legend: **VERIFIED** (tested live) | **CONFIRMED** (direction known via MCP/docs,
needs live verification) | **OPEN** (unknown) | **IMPLEMENTED** (coded + unit-tested, live
check pending) | **DEFERRED** (explicit non-v1 decision, tracked as a follow-up)

---

## #0 — Does routing fire + trigger condition — VERIFIED 2026-07-13 (aggregate-aware cluster)

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

## #1 — Date re-aggregation — VERIFIED 2026-07-13 (aggregate-aware cluster)

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

## #6 — Multi-aggregate precedence — VERIFIED 2026-07-13 (aggregate-aware cluster)

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

## #10 — Filter-precision-vs-bucket — VERIFIED SAFE 2026-07-14 (aggregate-aware cluster)

**RESULT: the engine self-protects — no wrong/empty results.** A MONTHLY-grain
query filtered at DAY precision (`[Transaction Date] = '01/15/2024'`) against a
primary with only a MONTHLY aggregate fell back to the DETAIL fact (scanned
`LINE_TOTAL`), not the month-grain aggregate. So `lattice.covers` not checking
filter precision is at most a mild **coverage over-estimate** (we might count a
day-filtered query as "covered" when the engine will actually serve it from
detail) — it never causes wrong or empty results, because ThoughtSpot's router
declines to serve a finer-than-grain filter from the aggregate. Low risk; the
Step-8 caveat about coverage estimates remains appropriate.

### #10 (historical OPEN text)

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

---

## #14 — DDL path now wraps ThoughtSpot-generated SQL (Task 18/19/24) — Task 19 + Task 24 fixes VERIFIED live 2026-07-14, full round-trip checklist still pending

**Why (Task 18):** live testing on an aggregate-aware cluster proved `sqlgen.build_select`'s
hand-rolled join walker produces **semantically wrong SQL on role-playing / ambiguous-
path dimensions** — a concrete case grouped revenue by the *inventory-balance* month
instead of the *order* month, because the walker's own join-path resolution (BFS over
`model_tables[].joins[]`) doesn't disambiguate which role-played path a query intends
the way ThoughtSpot's full semantic-model query generation does. This is a silent
wrong-aggregate bug, not a routing or import failure — Step 7's SQL-presence check
would not have caught it.

**Change (Task 18):** `ts aggregate generate`/`profile` build a SpotQL statement for the
candidate's grain (`ts_cli/aggregate/spotql_aggregate.py::build_spotql`) and ask
ThoughtSpot to compile it against the primary Model via the existing `ts spotql
generate-sql` client path (`ts_cli/commands/spotql.py`'s `_run`) — reusing, not
reimplementing, that HTTP call. The returned join-correct `executable_sql` is
wrapped as aggregate-table DDL (`wrap_as_ddl`, reusing `sqlgen.build_ddl` for the
per-dialect materialization shape and the Snowflake mview-can't-join guard) or, for
`profile`, as `SELECT COUNT(*) FROM (<ts_sql_no_limit>) _agg`. `sqlgen.build_select`
remains as an explicit fallback (`--no-spotql`, or automatically when SpotQL generation
is unavailable/errors) — a stderr note flags that a fallback's result may be wrong on
role-playing/ambiguous-path dimensions, i.e. the exact bug this pivot fixes.

**Task 18's own SpotQL was itself invalid — found and fixed live (Task 19),
2026-07-14, aggregate-aware cluster.** Two of Task 18's construction choices were
confirmed wrong by actually running them:
- `SUM("t1"."TABLE::COL")` (a real aggregate function over a physical column
  reference) → `QUERY_GEN_ERROR`. SpotQL is a semantic-layer language over **display
  names** — a measure/formula already carries its own aggregation in the model, so a
  real aggregate function wrapped around any reference to it is invalid syntax (and
  would double-aggregate even if it weren't).
- `start_of_month("t1"."Order Date")` → `QUERY_GEN_ERROR`. SpotQL has **no
  date-truncation/bucketing function at all** — not merely "forbids `DATE_TRUNC`", as
  Task 18's residual-risk note #1 below speculated; there is no bucket UDF to reach for.
- **What DOES work, confirmed live:** selecting a measure **by its own display name**
  bare (`"t1"."Sales" AS "sales_sum"`, no wrapping function) yields the correctly
  pre-aggregated value; selecting a **raw date column by display name** (no bucket
  function) also succeeds.
- **Proven end-to-end:** raw-date SpotQL (measure-by-name) → ThoughtSpot compiled a
  join-correct detail SQL → wrapped as `CREATE TABLE AS SELECT dims, DATE_TRUNC('MONTH',
  ca_date), SUM(ca_measure) FROM (spotql_sql) src GROUP BY dims, DATE_TRUNC(...)` → a
  **192-row monthly aggregate whose total equalled the ungrouped detail total exactly
  (594,188,083.19)**.

**Task 19 fix:** `build_spotql` now (a) references each decomposable measure by the
*primary measure's own display name* (`plan["name"]`), never a real aggregate function
over a physical column/component; (b) selects date grains as the *raw* column by
display name, emitting no bucket function at all; (c) returns a structured
column-descriptor list — `{"alias", "kind": "dim"|"date"|"measure", "bucket", "reagg"}`,
in SELECT order — instead of a plain alias-string list, so `wrap_as_ddl` knows each
output column's role. Scoped to measures whose rewrite plan stores exactly **one**
component (direct SUM/MIN/MAX/COUNT) — selecting the measure by name has only one
unambiguous meaning for these. **AVG/RATIO plans store two components** (numerator +
denominator) with no SpotQL syntax to select either separately (selecting the whole
formula by name yields the ratio, not the parts) — `_measure_rows` raises
`spotql_aggregate.UnsupportedMeasureError` for these instead of guessing at invalid
SpotQL; the existing best-effort try/except in `commands/aggregate.py`
(`_spotql_ddl_or_none`/`_spotql_profile_sql_or_none`) already catches it like any other
SpotQL failure and falls back to `sqlgen.build_select` with the standard stderr note.
This is an accepted scope boundary, not a defect — AVG/RATIO SpotQL-component
expressibility remains an open follow-up (see below), and every AVG/RATIO candidate
still gets correct DDL via the fallback today.

`wrap_as_ddl` now branches on whether any descriptor carries a `bucket`:
- **No bucketed date** (dateless, or every grain raw): pass-through —
  positional rename, no outer GROUP BY. `build_spotql`'s own GROUP BY
  (dims + raw dates) already lands on the final target grain.
- **A bucketed date is present:** emits the live-proven outer AGGREGATING select —
  `DATE_TRUNC(bucket, ...) AS "date_alias"` for a bucketed date grain (also a GROUP BY
  term), `reagg(...) AS "measure_alias"` for each measure (never a GROUP BY term), and
  a bare positional rename (still a GROUP BY term) for dims and any
  unbucketed grain in a multi-date candidate. Per-dialect DATE_TRUNC is `sqlgen._date_trunc`
  reused directly (not re-derived) — same Snowflake/Databricks `DATE_TRUNC('MONTH', x)`
  vs. BigQuery `DATE_TRUNC(x, MONTH)` mapping `sqlgen.build_select` already uses.
  `build_spotql`'s GROUP BY is only ever at the *raw* date grain (SpotQL can't bucket),
  so this second aggregation pass is what actually reaches the candidate's target grain.

**Task 24 fix — `wrap_as_ddl` no longer assumes ThoughtSpot's own `ca_N` naming
(VERIFIED live 2026-07-14, aggregate-aware cluster).** Task 18/19's `wrap_as_ddl`
referenced ThoughtSpot's compiled output columns by an ASSUMED name — `"ca_1"`,
`"ca_2"`, ..., `"ca_N"`, 1-based and contiguous, one per descriptor in order. **This
assumption is false in general.** For a measure whose rewrite plan compiles through a
CTE — a count-over-join like "# Employees" — ThoughtSpot's own final SELECT aliases its
columns starting from a HIGHER number (observed live: `ca_7`, `ca_8`, `ca_9`), not
`ca_1`. The outer wrapper SELECT then referenced a `"ca_1"` that never existed in that
compiled SQL, and Snowflake raised `invalid identifier '"ca_1"'` — `CREATE TABLE`
failed outright. The Task 19 test suite's own SUM fixture happened to compile to
`ca_1..ca_3` (no CTE) and did not exercise this path — a coverage gap, not a
contradiction of the Task 19 finding.

**Fix:** `wrap_as_ddl` (via new helper `_positional_alias`) renames the derived table's
output columns using a DERIVED-TABLE COLUMN-ALIAS LIST — `FROM (<inner>)
"src"("g1", "g2", ..., "gN")`, one `gN` entry per descriptor, in order — and the outer
SELECT references `g1..gN` instead of guessing at ThoughtSpot's own column names.
Snowflake, Databricks, and BigQuery all support `FROM (subquery) alias(col1, col2,
...)`, which renames the subquery's exposed columns by POSITION only, independent of
whatever ThoughtSpot called them internally. **Verified live** against the actual
"# Employees" CTE query that reproduced the bug: the old `ca_N` form failed with the
invalid-identifier error above; the `g1..gN` column-alias-list form succeeded, on both
the bucketed-aggregating wrapper and the dateless pass-through. The profile `COUNT(*)`
wrapper (`_spotql_profile_sql_or_none` in `commands/aggregate.py`) was checked and
confirmed unaffected — it wraps `SELECT COUNT(*) AS agg_rows FROM (...) _agg` and never
references any inner column by name.

Covered by unit tests in `tools/ts-cli/tests/test_agg_spotql.py` (measure-by-display-name
assertions for SUM/MIN/MAX/COUNT with no wrapping aggregate function; raw-date,
no-bucket-function assertions; `UnsupportedMeasureError` for AVG and RATIO; descriptor
list shape/order for single- and multi-date candidates; component dedupe cross-check
against `generate.build_aggregate_table_spec` — Task 18's invariant, kept; `wrap_as_ddl`
LIMIT-strip, positional column-alias-list mapping (Task 24), the bucketed-outer-aggregate
shape incl. a mixed bucketed/raw multi-date case, per-dialect DATE_TRUNC argument order,
the mview guard under both no-bucket and bucketed inputs, and a canned-SQL regression
fixture whose final projection uses non-1-based `ca_7`/`ca_8`/`ca_9` aliases — asserting
the wrapper never references `ca_N` and instead emits/uses the `g1..gN` alias list) and
`tools/ts-cli/tests/test_agg_command.py` (SpotQL-success and both fallback paths for
`generate`/`profile`, stubbed via a monkeypatched `ts_cli.commands.spotql._run` — no live
connection in these tests; these fixtures are all dateless/no-bucket, so they exercise
the pass-through branch, now updated to assert the `g1..gN` alias-list form).

**Residual, explicitly out of this task's scope:**
1. **AVG/RATIO SpotQL-component expressibility — OPEN follow-up.** No live-proven way
   to get SpotQL to select a formula's separate numerator/denominator components by
   name. Candidate future approaches (unexplored): decompose the AVG/RATIO formula into
   two intermediate single-component *helper measures* on the primary Model before
   SpotQL generation (each nameable and selectable individually, per the Task 19
   finding), or accept the `sqlgen.build_select` fallback permanently for this measure
   class. Every AVG/RATIO candidate today correctly falls back to `sqlgen.build_select`
   (not blocked, just not on the join-correct SpotQL path).
2. **Measure-component double-aggregation via `measures.py`'s classification
   guarantee.** Unchanged from Task 18: this only matters if a future measure
   decomposition ever pointed a component's `source_column`/primary-measure name at
   something that isn't a plain semantic measure — out of `measures.py`'s documented
   contract, out of this task's scope to change.

**Live round-trip checklist (why this stays short of full VERIFIED status):** the
Task 19 fix above (measure-by-name, raw-date, outer-aggregate wrapper shape) **is**
live-verified — see the 192-row/594,188,083.19 proof above. Still to confirm on a
role-playing-dimension candidate specifically:
- (a) The compiled `executable_sql` for a **role-playing/ambiguous-path** candidate
  (not just the proven single-fact-table case) resolves the correct join path.
- (b) A measure whose plan decomposes through a non-trivial formula chain resolves
  without double-aggregating (residual #2 above).
- (c) A **multi-date** candidate with one bucketed + one raw grain round-trips
  correctly against a live cluster (unit-tested per the mixed-grain wrapper shape;
  not yet live-executed).

Until then, treat a role-playing-dimension or multi-date SpotQL-path DDL as provisional
in the same way Step 7's routing verification already treats every recommendation —
this item doesn't change that standing caveat for those cases; the core measure-by-name
/ raw-date / outer-aggregate mechanism itself is no longer provisional.

## #15 — Aggregate name contained a raw space for multi-word dimensions — FIXED 2026-07-14

**Found:** live testing (aggregate-aware cluster) showed `ts aggregate generate` emitting
an aggregate table/model name with a literal space —
`DM_CATEGORY_AGG_MONTHLY_PRODUCT CATEGORY` — for a candidate over the "Product Category"
dimension. `_aggregate_name` (`ts_cli/commands/aggregate.py`) built the name by joining
the root table, bucket, and raw dimension *display* names, then only `.upper()`'d the
result — a multi-word display name's space survives uppercasing. An unquoted SQL
identifier containing a space breaks `CREATE TABLE`/`CREATE DYNAMIC TABLE`, so this
blocked DDL execution for any candidate grouped by a multi-word dimension.

**Fix:** `_aggregate_name` now runs the fully-assembled name (and any `--agg-name`
override) through `sanitise_name` (`ts_cli/commands/load.py` — already used for `ts
load`'s warehouse identifier derivation, reused here rather than duplicated): uppercase,
any run of non-`[A-Z0-9]` characters collapsed to a single underscore, leading/trailing
underscores stripped. `"Product Category"` → `PRODUCT_CATEGORY`, giving
`DM_CATEGORY_AGG_MONTHLY_PRODUCT_CATEGORY`. Still deterministic (same candidate → same
name, required for the Task 16 idempotence/dedup path) and length-capped at 120. Flows
into the DDL target, the Table TML `db_table`/`name`, and the aggregate Model name alike,
since all three are derived from the same `name` value in `commands/aggregate.py`'s
`generate()`.

Covered by `test_aggregate_name_sanitizes_multiword_dimension_to_valid_identifier` in
`tools/ts-cli/tests/test_agg_command.py` (asserts no space and `[A-Z0-9_]`-only output
for a "Product Category" dimension). Not yet re-run against the live cluster that
surfaced the bug — unit-verified only; flag as a follow-up smoke check next time the
skill runs end-to-end against that cluster.

---

## #16 — `_candidate_key` collided single-date vs multi-date candidates — FIXED 2026-07-14

**Found:** final whole-branch review. `_candidate_key` (`ts_cli/commands/aggregate.py`,
used by `_merge_prior_agg_rows` to carry a prior `profile` run's `agg_rows` forward
across `recommend` re-runs) keyed on `c["dimensions"]` + the single-date
`date_column`/`bucket` COMPAT SHIM fields — which only ever hold a candidate's FIRST
date grain (Task 14's `date_grains` list). Two distinct candidates sharing the same
dimensions and the same first grain — one single-date, one multi-date — therefore
produced an identical key, so `_merge_prior_agg_rows` could assign one candidate's
profiled `agg_rows` to the other on the next `recommend` run. On a multi-date model
this skews cost-mode ranking and (via `cand["agg_rows"]` → `projected_rows`) the
`patch_association` ordering item #6 verified is load-bearing for first-match routing.
Does not corrupt generated DDL — DDL generation reads the full candidate dict, never
this key.

**Fix:** `_candidate_key` now keys on the full `date_grains` list (reusing
`lattice._cand_date_grains`'s single-date-shim fallback, so pre-Task-14 candidate
dicts that only carry `date_column`/`bucket` still key correctly), with grains sorted
by column so the key doesn't depend on list order. Covered by
`test_candidate_key_distinguishes_single_vs_multi_date_grains`,
`test_candidate_key_stable_regardless_of_date_grains_order`, and
`test_merge_prior_agg_rows_does_not_cross_assign_single_vs_multi_date` in
`tools/ts-cli/tests/test_agg_command.py`.

**Related, documented but explicitly NOT fixed here (out of scope):**
`history._signature_matches`/`match_history` (`ts_cli/aggregate/history.py`) only reads
a signature's `date_column`, never its `date_grains` list — multi-date history-based
signature weighting is degraded best-effort (an extra date column beyond the first is
invisible to matching), not a correctness bug, since weights only bias `recommend`'s
greedy ranking, never `covers()`'s coverage correctness. Noted inline on
`_signature_matches` as well.

---

## #17 — RLS propagation (Task 22/23/25/26) — WIRED; import bugs FIXED, identical-rule dedup + pass-2 fail-closed DONE, single-rule propagation VERIFIED live; leak-test + flat-shape confirmation OPEN

**Context:** live review surfaced that the skill previously only GATED on base-table
row-level security — it refused to import until the user manually replicated the RLS
elsewhere, and never checked whether a candidate's grain even contained the RLS filter
column at all. Decisions (user): (a) auto-propagate the base tables' `rls_rules` onto
the aggregate table (remapped to its own columns), plus verify routing enforces them
(no leak) — this second half is **Task 23**; (b) on a candidate whose grain omits an
RLS filter column, offer the user exclude-vs-force-add per candidate.

**What's IMPLEMENTED (this task, pure engine only):** a new pure module,
[`ts_cli/aggregate/rls.py`](../../../../tools/ts-cli/ts_cli/aggregate/rls.py), with
five functions, all unit-tested in
[`tools/ts-cli/tests/test_agg_rls.py`](../../../../tools/ts-cli/tests/test_agg_rls.py)
(26 tests):

1. `extract_rls(base_table_tmls)` — normalizes a base Table TML's `rls_rules` into
   `[{table, name, expr, columns, path_ids}]`, handling both the dict-nested shape
   (`rls_rules: {rules:[...], table_paths:[...]}`, the verified live shape — see
   `test_report_matched_columns.py::_TABLE_TML_WITH_RLS`) and a flat rule-list shape
   (no `table_paths` at all). Note: `agents/shared/erd/parser.py::_rls_rule_list`
   normalizes the two *nesting shapes* but does NOT resolve bracket refs to columns —
   that resolution is this module's own logic. **UNVERIFIED (no in-repo flat-shape
   TML example):** the flat shape resolves a bracket ref's identifier against the
   owning table's own name via a seeded `{own_table: (own_table, [])}` fallback entry
   in the path map — a reasonable inference, flagged for re-check by Task 23 / live
   testing if a real flat-shape export ever surfaces.
2. `rls_filter_columns(rules)` — the `(base table, physical column)` pairs the RLS
   exprs filter on, parsed from each rule's own `path_ids` map (supports cross-table
   RLS refs, not just a rule's owning table). **Fail-closed:** a ref whose path_id is
   neither declared nor the owning table name surfaces as `(<raw ref_id>, col)` rather
   than being dropped — see the security fix below.
3. `candidate_rls_conflict(candidate, plans, model_tml, rules)` — maps each RLS filter
   to the model's display column (via `column_id` match) and checks grain membership;
   returns `{required, present, missing}`. An RLS column the model doesn't expose at
   all (or one that resolved to a fail-closed pseudo-table) still surfaces (falls back
   to the raw `<table>::<column>` string, never a grain name) — a candidate is never
   reported securable while an unresolvable/un-modeled ref exists.
4. `add_rls_columns_to_candidate(candidate, missing_display_cols)` — the force-add
   mechanic: returns a copy with the missing columns folded into `dimensions`.
5. `propagate_rls(base_rules, agg_table_name, filter_to_aggcol)` — builds the
   aggregate table's `rls_rules` block: **as of Task 25** (see below — the original
   Task 22 version of this function omitted `tables` and failed live import; this
   description reflects the fixed version) one `tables` entry (`[{"name":
   agg_table_name}]`) plus one merged `table_paths` entry (id `"<agg_table_name>_1"`,
   following the `"<name>_1"` self-path convention in `thoughtspot-sets-tml.md`) plus
   rewritten rule exprs (`ts_*` system-var portions copied verbatim, since they're
   never bracket-wrapped so the rewrite regex never touches them). `filter_to_aggcol`
   is keyed by the **`(base table, physical column)` tuple** (the same pair
   `rls_filter_columns` emits / `candidate_rls_conflict` resolves), NOT the bare
   column name — Task 23 must build the dict with tuple keys. Raises `ValueError`
   naming every unmapped filter `(table, col)` if `filter_to_aggcol` is incomplete —
   a programming-error / fail-closed guard, since Task 23's caller is expected to
   guarantee coverage via #3/#4 above. A round-trip test confirms the emitted block
   survives `tml_common.dump_tml_yaml` + `tml_lint.lint_tml` clean when attached to a
   Table TML.

**Security fixes applied post-review (2026-07-14, before Task 23 wiring):**
- **Same-name cross-table columns (was a silent mis-securing / leak):** `propagate_rls`
  originally keyed its column mapping by the BARE physical column name inside `[id::COL]`,
  discarding the table qualifier. Two base tables each RLS-filtering on a same-named
  physical column (e.g. both a fact and a dim have `REGION`, mapping to DISTINCT aggregate
  grain columns) both remapped to the SAME aggregate column → a valid, lint-clean rule
  enforcing the WRONG row restriction (potential row-visibility leak). Fixed by keying the
  mapping (and the missing-mapping guard) on the `(table, col)` tuple `rls_filter_columns`
  already emits. Regression test: two RLS'd base tables sharing physical col `REGION` →
  the two propagated rules reference distinct aggregate columns.
- **Fail-open → fail-closed on unresolvable refs:** `rls_filter_columns` /
  `candidate_rls_conflict` previously silently dropped an RLS ref whose path_id was
  undeclared in `table_paths` and wasn't the owning table name (e.g. `[T_9::SECRET]` when
  only `T_1` is declared → `missing:[]` "securable" while an unsecurable ref existed). For
  a security control this now fails CLOSED: an unresolved ref surfaces (via `_resolve_ref`,
  using the raw ref_id as a pseudo-table) as a required-but-unresolvable column, so it
  always lands in `required`/`missing` and `propagate_rls` raises on it — never reported
  "securable as-is". Tests added for both.

**Task 23 (this task) WIRED the above into the command layer and the skill:**
- `ts aggregate recommend` extracts RLS from the tables-dir Table TMLs (`--tables-dir`,
  default `<dir>/tables`) and attaches `rls: {required, missing}` + `rls_conflict`
  (bool) to every candidate in `candidates.json`, plus an `rls_conflicts` (candidate
  ids) summary field on stdout — a no-op when no base table carries RLS
  (`_attach_rls_conflicts` in `commands/aggregate.py`).
- `ts aggregate generate` recomputes `candidate_rls_conflict` on the (possibly
  force-added) candidate and **FAILS CLOSED** (`typer.Exit(1)`, before writing any of
  the five output files) if the grain still omits a required RLS column; otherwise it
  resolves `filter_to_aggcol` — `(base_table, physical_col) -> aggregate stored column
  name` — via the model's `column_id` map (the same display name
  `build_aggregate_table_spec` stores the grain column under) and calls `propagate_rls`,
  attaching the result to the aggregate Table TML's `table.rls_rules` (both
  `table.tml.yaml` and `table_spec.json`) before either is written
  (`_propagate_rls_or_fail_closed`/`_build_filter_to_aggcol` in `commands/aggregate.py`;
  `_build_table_tml` in `commands/tables.py` now passes an optional `rls_rules` spec key
  straight through). No new CLI flag — the skill applies `add_rls_columns_to_candidate`
  directly to `candidates.json` before calling `generate`, so `generate` just reads the
  already-widened candidate ("pick the simpler" option from the task-23 brief).
- SKILL.md Step 5e prompts exclude (X) vs force-add (F) per conflicting candidate (and
  says to re-profile after a force-add); Step 6e's manual "apply RLS in the UI" hard
  gate is replaced by a show-and-confirm of the auto-propagated `rls_rules` (a hard stop
  remains only for a fail-closed `generate` error — CLS stays its own unchanged manual
  gate); Step 7 adds the RLS leak-test described below as the live gate; Step 5d's
  candidate table now also shows measures carried (`measure_columns`) and the proposed
  aggregate name (`_aggregate_name`, computed the same deterministic way `generate` will
  name the real table/Model) before the user picks the cut-off.
- Command-level tests (CliRunner + offline fixtures, no live instance): `recommend`
  surfacing (conflict/no-conflict/no-RLS no-op) and `generate` (fail-closed with zero
  files written; successful propagation onto both TML artifacts; no-op absent RLS) — see
  `tools/ts-cli/tests/test_agg_command.py`'s "Task 23" section. `rls.py`'s own pure
  functions are unchanged (Task 22, only called here).

**Task 25 (this task) — LIVE testing surfaced two real import bugs, both FIXED:**

- **Bug A — `propagate_rls` omitted the `tables` sub-block.** A known-good ThoughtSpot
  `rls_rules` block (a live UI-created rule that re-imports cleanly) has THREE
  sub-blocks — `tables`, `table_paths`, `rules` — not two. `propagate_rls` only ever
  emitted `table_paths` + `rules`; on live import this failed `OBJECT_NOT_FOUND ...
  LOGICAL_TABLE`, because `table_paths`' self-reference to the aggregate table can't
  resolve without a `tables` entry naming that table. Fixed: `propagate_rls` now
  returns `{"tables": [{"name": agg_table_name}], "table_paths": [...], "rules":
  [...]}` (one `tables` entry — the aggregate is always a single table), sub-blocks in
  that order. Verified: adding `tables` made the live import succeed and the rule
  attach to the aggregate. Tests: `tools/ts-cli/tests/test_agg_rls.py` (`tables`
  presence/content on single-rule, multi-rule-same-table, and multi-BASE-TABLE
  propagation; key order; round-trip through `dump_tml_yaml` + `lint_tml` stays
  clean) and `tools/ts-cli/tests/test_agg_command.py`'s Task 23 section (`generate`'s
  emitted `table.tml.yaml`/`table_spec.json` both carry `tables`).
- **Bug B — single-pass import of a self-referencing `rls_rules` block fails.** A
  `create_new` import of the aggregate table TML that already carries `rls_rules`
  fails live — the same self-reference above can't resolve to a `LOGICAL_TABLE` that
  doesn't exist yet in the SAME call that creates it (independent of Bug A; still
  fails even with `tables` present). The working sequence, live-verified, is two
  passes: (1) create the table WITHOUT `rls_rules`; (2) re-import the SAME table WITH
  `rls_rules` + the created table's `guid` at the document root + `--no-create-new`,
  which attaches the rules to the now-existing table. Fixed in `ts tables create`
  (`tools/ts-cli/ts_cli/commands/tables.py`) — `create_tables` now does this
  automatically whenever a spec carries `rls_rules`; the caller (this skill) doesn't
  orchestrate it by hand. `_build_table_tml` gained an optional `guid` param (places
  `guid:` at the document root, per the TML invariant) and a new `_strip_rls_rules`
  pure helper produces the RLS-less pass-1 variant; the retry loop was extracted into
  `_import_one`, shared by both passes. A spec with no `rls_rules` is byte-for-byte
  unaffected (still one pass). SKILL.md Step 6d documents the two-pass behavior and
  why; Step 6e was reworked from "show and confirm the propagated shape" to "confirm
  it actually attached live" (a live `ts tml export` + compare, since pass 2 can fail
  independently of pass 1 — a non-null GUID is no longer proof RLS is in effect) before
  the show-and-confirm prompt. Tests: `tools/ts-cli/tests/test_tables_command.py` (new
  — two import calls for an RLS spec, pass 1 has no `rls_rules`/`guid`, pass 2 has
  `create_new: false` + `guid` + `rls_rules`, a pass-2-failure case still reports the
  GUID with a loud stderr error, a no-RLS spec makes exactly one call) and
  `tools/ts-cli/tests/test_build_table_tml.py` (new — the `guid` param and
  `_strip_rls_rules` in isolation).
- **Multi-rule / multi-base-table propagation — CONFIRMED, no code change needed.**
  Two base tables, each with its own RLS rule on its own column, propagate through
  `extract_rls` -> `propagate_rls` into a SINGLE aggregate `rls_rules` block: one
  `tables` entry, one merged `table_paths` entry carrying both remapped columns, both
  rules present, referencing distinct aggregate columns (the Task-22 collision fix
  already handled this — see `test_two_base_tables_each_with_a_rule_merge_into_one_
  aggregate_block` in `test_agg_rls.py`, added this task to make the confirmation
  explicit).

**Task 26 (this task) — two RLS hardening fixes, from live testing + the product owner's
clarification:**

1. **Identical-rule dedup (non-strict RLS).** Product-owner clarification: STRICT RLS is
   usually a single rule; NON-STRICT RLS repeats the SAME rule across MANY base tables —
   a cluster-wide setting that is **undetectable from our TML data** (we can't tell from
   a Table TML export whether a cluster is running strict or non-strict RLS). The
   dedup-identical-rules approach fixed here is correct either way: a genuinely strict
   single rule is never affected (nothing to dedup), while a non-strict cluster's
   repeated-rule-per-table pattern collapses to one rule instead of propagating N
   byte-identical copies. Previously `propagate_rls` emitted one output rule per base
   rule with no dedup — confirmed (live-review scenario): two base tables carrying the
   same rule, both remapping to the same aggregate column, produced 2 identical rules on
   the aggregate. Fixed: `propagate_rls` (`ts_cli/aggregate/rls.py`) now dedupes rules
   whose REMAPPED expr is identical (whitespace-normalized) down to ONE, keeping the
   FIRST occurrence's name deterministically. Multiple DIFFERENT rules still all apply
   to the aggregate; the Task 22 collision-fix case (two rules on same-named physical
   columns that remap to DIFFERENT aggregate columns) is untouched — those remapped
   exprs genuinely differ, so they never collide on the dedup key. `table_paths`' merged
   column list was already deduped (pre-existing `if agg_col not in agg_cols` guard), so
   no separate fix was needed there — verified by a new test asserting a single-column
   `table_paths` entry survives the same repeated-rule scenario.
   Tests (`tools/ts-cli/tests/test_agg_rls.py`,
   `TestPropagateRlsIdenticalRuleDedup`): same rule repeated across N base tables →
   exactly one output rule; first-occurrence name wins when names differ but the
   remapped expr matches; whitespace-only expr differences still dedup; genuinely
   different rules both kept; the Task 22 same-physical-column/distinct-aggregate-column
   case still keeps both; the deduped block round-trips through `dump_tml_yaml` +
   `lint_tml` clean.
2. **Pass-2 RLS attach failure now fails CLOSED.** `ts tables create`'s two-pass RLS
   registration (Task 25) printed a loud stderr error when pass 2 (the `--no-create-new`
   attach import) failed, but still exited 0 and reported the table's GUID as if the
   create had fully succeeded — the one fail-OPEN link in an otherwise fail-closed
   pipeline: a scripted caller (the skill itself, or any other automation) had no
   non-zero-exit signal that the table it just "successfully" created is actually
   UNSECURED. Fixed in `commands/tables.py`'s `create_tables`: a pass-2 failure is now
   collected per table and, after the JSON name→guid map is still printed to stdout (the
   manual-attach recovery — "set `guid: <guid>` ... `--no-create-new`" — depends on that
   guid), the command raises `typer.Exit(1)`. The happy paths (no-RLS single create;
   successful two-pass RLS) are unaffected — still exit 0. Tests
   (`tools/ts-cli/tests/test_tables_command.py`, `TestPassTwoFailureFailsClosed`): pass-2
   failure exits non-zero; the guid is still present in stdout; the stderr error names
   the affected table and retains the "do not re-run `ts tables create`" recovery
   guidance; a multi-spec invocation where one table's RLS attach fails and another
   table (no RLS) succeeds still reports BOTH guids while exiting non-zero overall; both
   happy paths still exit 0.

**Still OPEN — the only two pieces left:**
1. **Live leak-test.** Task 25 verified single-rule propagation's IMPORT/ATTACH path
   live (the rule now imports and attaches to the aggregate table, per Bugs A/B above)
   — that is a DIFFERENT question from this one. Does an RLS-restricted query against
   the primary Model, once routed to the propagated aggregate, actually still enforce
   the rule (a user in group A never sees group B's rows), or does routing to the
   aggregate silently bypass the base table's RLS? This is the question that decides
   whether auto-propagation is safe to ship — until it's verified live, treat a
   propagated-and-attached RLS rule as unverified for ENFORCEMENT in the same
   provisional sense the routing-verification caveat already applies to every other
   recommendation in this skill. SKILL.md Step 7 now documents the procedure:
   re-run the same aggregate-hit `ts spotql generate-sql` check authenticated as a
   restricted user (swap `--profile`) and confirm the returned rows actually respect the
   rule. This item stays OPEN until someone actually runs it against a live
   aggregate-aware cluster with a real RLS rule.
2. **Flat-shape `rls_rules` confirmation.** `extract_rls`'s flat-list handling (no
   `table_paths`, resolved via the own-table-name fallback) is still unverified against
   a real flat-shape TML export — see `rls.py`'s module docstring. Re-check the first
   time a live table export actually shows this shape.

## #18 — End-to-end build findings (2026-07-15, nebula-aggregate-aware) — OPEN, plan in references/remediation-plan.md

First full manual build of two aggregates (dimensional + monthly semi-additive) on
"Dunder Mifflin Sales & Inventory" surfaced 14 findings (F1–F17 in the run's
PROCESS_FINDINGS.md). Full design + phased plan: [remediation-plan.md](remediation-plan.md).
Summary of tracked items:

**Correctness bugs (Phase 0):**
- **F1 — part (a) FIXED.** `build_base_count_sql` counted `model_tables[0]` (a dim, no fact
  join) → `base_rows=8`. Now `sqlgen.base_table_name` anchors the count on the measure-owning
  fact (unit-tested). (b) DONE — `flag_suspect_base_rows` warns + sets `base_rows_suspect`
  when `base_rows` < max(agg_rows), both profile paths. Remaining (c): fix internal SpotQL
  so profiling stops falling back to the walker (needs live repro).
- **F6 — INVALIDATED (operator error, not a tool bug).** The reported crash on a
  `bucket=MONTHLY` candidate was caused by a malformed injected candidate
  (`date_grains: ['MONTHLY']` — list of strings — instead of the real
  `[{'column','bucket'}]` shape). Verified offline: correctly-shaped bucketed candidates and
  the `date_column`/`bucket` compat shim both work in `generate._grain_columns`. Residual
  (LOW): the tool raises a bare `TypeError`/`AttributeError` on a malformed candidate dict —
  add input-shape validation with a clear message. NOT a blocker for the monthly use case.
- **F8 — FIXED.** Component types were hardcoded (`INT64` for COUNT else `DOUBLE`), so
  `SUM(int)` emitted DOUBLE and `ts tables create` failed the CDW type check. Model TML lacks
  measure types, but the base Table TMLs carry them — `generate._measure_source_type()` now
  resolves each component's source column (via `column_id` or the formula's `[TABLE::col]`
  ref) and preserves its type (SUM/MIN/MAX), COUNT→INT64, DOUBLE fallback. `table_tmls`
  threaded through `_write_table_artifacts`. Unit-tested.
- **F2** — `ts aggregate profile` (via `commands/load._connect`) died with a bare
  "install snowflake-connector-python". **FIXED this PR:** added `[snowflake]` extra +
  a remedy message covering `pip install 'thoughtspot-cli[snowflake]'` and the uv-tool
  `uv tool install thoughtspot-cli --with snowflake-connector-python` form.

**Verification (Phase 1):**
- **F9 — ADDRESSED.** Routing fires ONLY for formula measures (open-item #0); the skill built
  aggregates over plain measure columns that can never route. `recommend` now emits
  `routing_ineligible_measures` (`commands/aggregate.routing_ineligible_measures` over
  `spotql_ops.classify_model_columns`) and SKILL.md Step 5a gates on it, offering the
  promotion (plain measure → `sum([physical])` formula, backup first). Unit-tested. Optional
  follow-up: codify the promotion as a `ts` command.
- **F10/F11/F13 — CORRECTED (earlier claim was wrong).** `ts spotql generate-sql` DOES
  reflect routing for ALL measure kinds incl. semi-additive; the earlier failures were
  query-construction errors. Step 7 must pick the wrapper via `ts spotql classify-columns`:
  raw→`SUM`, aggregate-formula→`AGG` (SUM nests → NESTED_AGGREGATE), semi-additive
  last_value→`SUM` (AGG → NON_CONVERTIBLE_FUNCTION). Re-verified live: `SUM("Inventory
  Balance")`→monthly agg, `AGG("Amount")`→dimensional agg. Step 7's hardcoded `SUM("Sales")`
  example is wrong for aggregate-formula measures and must be replaced.
- **F14** — RLS leak-test still owed (routed queries so far ran as bypass admin); see #17.

**Capability (Phase 2) — mostly wiring existing engine pieces:**
- **F3** multi-dimension candidates; **F5** wire `measures.py`/`classify-columns`
  (semi-additive + ratio) into `lattice` candidate generation (knowledge exists, not wired);
  **F12** role-playing/conformed date columns (key date aggregates on the column users query,
  or the shared conformed date); **F4** combine-vs-split analysis; **F15** emit formula-only
  aggregate models (formulas over physical component cols, no hidden component model columns —
  also unblocks in-place editing).

**UX (Phase 3) — DONE:** **F16** model name now aggregate-first `<aggregate> (<source>)`;
**F17** `generate` auto-writes a description (grain/measures/routing/RLS). Both unit-tested.

**Positive (keep):** **F7** RLS fail-closed guard + rule remap worked correctly end to end.
