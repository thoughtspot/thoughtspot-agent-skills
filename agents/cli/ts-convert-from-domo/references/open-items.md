# Open items — ts-convert-from-domo

Assumptions, quirks and follow-ups. Status vocabulary: `TO VERIFY | VERIFIED | KNOWN |
DEFERRED | WONT-FIX`. Each must reach VERIFIED, or be explicitly KNOWN/DEFERRED with a
reason, before shipping.

## #1 — Offline chain: model + liveboard import cleanly — VERIFIED

The full offline chain (`parse` → `build-model` → `ts tml lint` → `ts tml import` →
`build-liveboard` → import) was run against a live cluster and the emitted Table, Model,
Answer and Liveboard TML import without errors. Two fixes came out of that run and are in
the converter:

- **Join side + cardinality.** The shared model emitter writes each join on *both* tables
  (bidirectional), which the model schema rejects. `_apply_join_fixes` keeps the join on
  the source (FK/MANY) side only and sets an explicit `cardinality`.
- **Display-name collisions.** A column name shared across joined tables (typically the
  join key) must stay physically present on both tables or the join stops resolving, but a
  Model cannot expose two columns with the same display name. Colliding columns are kept
  and their *display* name disambiguated; `db_column_name` stays the physical name.

## #2 — Fixture-derived shapes match the documented Domo payloads — VERIFIED

Verified against `tests/fixtures/domo/`:
- Dataset schema shape (`schema.columns[{type,name}]`, types STRING/DATETIME/DOUBLE/LONG).
- Beast Mode get-all shape (`results[{id,name,formula,dataSourceId,global,links[]}]`).
- Card shapes: `kpi` uses `summaryNumber`; `bar`/`table` use `chartBody`; both carry
  `calculatedFields[]` and `quickFilters[]`; KPI carries `conditionalFormats[]`.
- Page shape (`cardIds[]`, `collectionIds[]`, `children[]`).
- ID cross-refs: `page.cardIds` ↔ `card.urn`; `card.dataSetId` / `beastmode.dataSourceId`
  ↔ `dataset.id`.

These fixtures model the **documented** shape, not a live capture — see #3.

## #3 — A card's analyzer query is not reachable from any Domo API — KNOWN (structural)

Probed against a real instance with an `X-DOMO-Developer-Token`:

- **Reachable:** datasets (`/api/data/v3/datasources`), pages (`/api/content/v1/pages`,
  `/pages/{id}/cards`, `/api/content/v3/stacks/{id}/cards`), card **metadata incl.
  chartType** (`/api/content/v1/cards?urns=…&parts=metadata,…`), Beast Modes
  (`POST /api/query/v1/functions/search`). `ts_cli/domo/client.py` wraps these.
- **Not reachable:** the card's **analyzer query** — which measure/dimension/aggregation/
  filter it plots. Every candidate endpoint (`…/analyzer`, `…/definition`, `…/render`,
  `parts=problem,columns,dataset`, `v3/cards`) returned 404/405 or metadata only. The
  internal dataset *column list* endpoint was also not found (the schema endpoint returns
  `columnCount` but not columns; the public Developer API `GET /v1/datasets/{id}` does
  return `schema.columns`).

**Consequence, and why the skill is offline-only:** faithful card → Answer conversion needs
the analyzer query, and no token can reach it. The skill therefore converts from an offline
bundle and asks for the **dashboard PDF** to read chart/axes; without it, cards degrade to
title + chart-type placeholders and are flagged. This is a Domo platform limitation, not a
gap in the converter — hence KNOWN rather than DEFERRED.

## #4 — Live (`domo-cloud`) mode is not wired into `parse_app` — DEFERRED

`client.py` is a working foundation (see #3 for what it reaches) but `parse_app` only reads
a directory of JSON, and `ts domo` now **refuses** any `--mode` other than `offline`
rather than recording one it did not use. Because #3
caps live mode at *partial* fidelity anyway, wiring it is deferred rather than blocking.
`ts domo signin` exercises the client so the credential path stays honest and testable.

**Workaround:** capture the bundle (by hand, or with the client's endpoints) and run the
offline chain.

## #5 — Domo auth: developer token, not OAuth2 client credentials — VERIFIED

An earlier draft assumed OAuth2 client-credentials with a `data`/`dashboard` scope. The
endpoints the converter actually needs (#3) are Domo's internal ones, which authenticate
with an `X-DOMO-Developer-Token`, not a scoped OAuth2 bearer token. `ts-profile-domo` and
`ts profiles add --platform domo --auth-type developer-token` reflect that; the public
Datasets scope question is moot for this path.

## #6 — Join inference is a heuristic — KNOWN

Domo carries no relationship metadata. Without a Magic ETL export, joins are inferred by
shared column name. With `--etl`, they come from the dataflow's `MergeJoin` graph (keys +
type) — much better, but the join *side* is resolved by following each `MergeJoin.step1`
down to its primary `LoadFromVault` (star-to-fact), so a dim→dim join (e.g. Products →
Category Translation on `product_category_name`) attaches to the fact instead of Products.
Correct lineage needs the dataset schemas.

**Every** join from either path is therefore emitted `NEEDS REVIEW`, and the report warns on
a chasm trap when facts share a join key. Prefer `--etl`, and confirm cardinality by hand.

## #7 — Only `chartVersion` 2.0 is parsed — DEFERRED

Fixtures are `"2.0"`. Older card versions may nest the query differently; other versions are
flagged rather than guessed. Revisit when a pre-2.0 capture is available.

## #8 — Relative-date operands and fiscal semantics — DEFERRED

The operand → ThoughtSpot preset table in the coverage matrix (`LAST_N_DAYS`, `THIS_MONTH`,
`YTD`, …) is best-effort, and `chartBody.fiscal` semantics have not been reconciled against
ThoughtSpot's fiscal presets. Mapped rows are marked Approximated; anything unrecognised is
flagged. Cards carrying `dateRangeFilter` are deferred entirely.

## #9 — Column format → ThoughtSpot number format — DEFERRED

Domo `format` (CURRENCY / NUMBER / percent / precision) → TS number-format string needs a
fidelity pass. Mapped as Approximated today.

## #10 — Multi-tab pages are untried against a populated payload — DEFERRED

There is **no tab code at all** — `answers.py` emits `layout.tiles` and never a `tabs`
node, so `collectionIds` / `children` are parsed and dropped. An earlier version of this
entry described tab grouping as "exercised only on the single-tab path", which implied an
implementation that does not exist. Card drill paths and card-to-card links are likewise
out of scope (see the coverage matrix).

## #11 — Card sort / filters / formats are parsed but not emitted — KNOWN

`parsing.py` reads `orderBy`, `filters` (incl. relative-date operands), `quickFilters`,
`conditionalFormats` and per-column `format` into the IR, but `answers.py` emits none of
them. An Answer therefore lands **unsorted and unfiltered — showing all-time data** even
when the source card was scoped to, say, `LAST_90_DAYS`.

Found by auditing the emitted TML against the fixtures rather than trusting the coverage
matrix: the fixture card `Revenue by Region` carries a `DESCENDING` sort, a `LAST_90_DAYS`
filter and a `Product Category` quick filter, and the emitted Liveboard TML contained no
sort, filter or format node at all.

The dangerous part was not the gap but the **silence**: those cards were reported
`Migrated` with an empty note, and the report claimed 89% automation. `_dropped_constructs`
now detects each dropped construct per card, downgrades the card to `Approximated`, names
the constructs in the note, and surfaces them in the report's Manual review section — the
same fixture bundle now honestly reports 56% automation.

Emitting them for real is deferred: card filters need an operand→ThoughtSpot-preset
mapping that is still unverified (#8), and Liveboard filter chips need the `quickFilters`
→ filter-chip binding designed. Tracked here rather than silently carried.

## #12 — Six string functions had no ThoughtSpot equivalent — VERIFIED (fixed)

`UPPER`/`LOWER`/`TRIM`/`LTRIM`/`RTRIM`/`REPLACE` were mapped to same-named ThoughtSpot
functions. None of those exist (BL-170/BL-171, live-disproved on se-thoughtspot
2026-06-13 and 2026-07-29/30) — a bare call is rejected at import with `error_code
14516` — and because the translator considered them mapped, the affected formulas were
reported `Migrated`.

They now go through the shared `formula_common.wrap_passthrough_calls` into a
`sql_string_op` pass-through, the same mechanism `ts qlik` and `ts powerbi` use.
`SUBSTRING` was separately mapped to `substring`, which is also not a ThoughtSpot
function; it now maps to `substr`.

Two gates were blind to this and both are closed:
- `check_formula_catalog.py` only scans markdown **table rows**, and the Domo function
  map was written as prose bullets, so ~40 names were never checked. The map is now a
  set of tables in call form (`| \`ABS(x)\` | \`abs(x)\` | |`) — the shape the validator's
  regex actually matches. Injecting `upper` into any row now fails the validator.
- No fixture exercised a string function. `tests/fixtures/domo_edge/` now does, and
  `tests/test_domo_functions.py::TestMapIntegrity` cross-checks every emitted name
  against the catalog directly, so a future edit cannot reintroduce the class of bug.

Eight emitted names (`exp`, `hour`, `log`, `minute`, `quarter`, `sign`, `to_date`,
`week`) are not *in* the catalog — unverified rather than disproved. All eight are
emitted by the tableau/qlik/sisense maps too, so this converter is no more exposed than
the rest of the family; the validator warns rather than errors on them.

## #13 — Duplicate Beast Mode names produced a dangling formula reference — VERIFIED (fixed)

`build_model_tml` derives a formula's id from its name, so two datasets each carrying a
"Net Revenue" Beast Mode — ordinary in Domo — produced two formulas with the same id.
Downstream dedup then stripped **both**, leaving model columns pointing at a
`formula_id` that no longer existed (import fails), while the mapping still reported
both as `Migrated`. Colliding names are now disambiguated by dataset and the rename is
reported. The converter also now adopts `formula_common.resolve_name_collisions` for
column↔formula name clashes, which it previously did not handle at all.

## #14 — Join inference was unsound — VERIFIED (fixed)

Three separate problems, all now addressed:
- One join was emitted **per shared column per dataset pair**, so a pair sharing
  `id`, `Region` and `Date` produced three joins to the same table.
- Pairs whose only shared columns were incidental (`Region`, `Date`, `Status`, …) were
  joined anyway, which fans measures out across the star. Such a pair is now left
  unjoined and reported instead.
- The join **side** was decided by dataset iteration order — i.e. bundle filename sort
  — so the same two datasets could emit `MANY_TO_ONE` or `ONE_TO_MANY` depending on
  file names. Row counts now decide, and the join is placed on the many (fact) side.

## #15 — `--etl` joins were counted but silently dropped — VERIFIED (fixed)

Magic ETL carries dataflow **action** names, which need not match dataset names. Joins
whose tables did not resolve were counted in `counts.joins` and listed in
`mapping.json`, then filtered out of the TML — so the report claimed "Relationships: 7"
(and emitted a chasm-trap warning) over a model with no joins at all. Names are now
reconciled against the bundle's datasets; unmatched joins are dropped with a named
warning, surfaced in the report's Manual review section and counted separately as
`counts.joins_dropped`. `counts` now describes what was emitted, not what was seen.

## #16 — Column renames never crossed the stage boundary — VERIFIED (fixed)

The root cause behind two separate wrong-numbers bugs, and the reason they were worth
fixing together rather than individually.

`_build_tables_and_columns` disambiguates a colliding display name (`Revenue` on the
second dataset becomes `Revenue (Refunds)`), but nothing rewrote:

- **formula bodies** — a Beast Mode defined on Refunds translated to `sum([Revenue])`,
  which the Model resolves to `Orders::Revenue`. Reported `Migrated`, note empty.
- **Answer columns / `search_query`** — a card on Refunds grouped by `Region` emitted
  `[Region]`, silently grouping by `Orders.Region`. For a *renamed Beast Mode* the
  reference dangled instead.

Both produce a **clean import with wrong numbers**, which is the failure mode this
converter's discipline exists to prevent — worse than a failed import, because nothing
tells the user.

`build-model` and `build-liveboard` are separate CLI invocations that each re-parse the
bundle, so `mapping.json` is structurally unreachable from the Answer path. The fix is
therefore not to pass a rename map between them but to make the mapping a **pure
function of the parsed IR**: `ts_cli/domo/naming.py` owns the collision rule for both
columns and Beast Mode names, and every consumer resolves through it. Two independent
invocations over the same bundle produce identical names because dataset order and the
first-wins rule are deterministic. Nothing recomputes the rule.

A reference that resolves to nothing the Model exposes is now flagged rather than
shipped.

**The regression test that matters** is `tests/test_domo_binding.py`: a property check
that every `[Column]` in an emitted formula or `answer_column` resolves to a column the
Model exposes **on the owning table**. Asserting "the rename happened" (the previous
test) caught neither bug. Verified to bite: neutering either fix fails 5 of the 13.

## #17 — A flagged formula made the whole model unimportable — VERIFIED (fixed)

A NEEDS REVIEW formula is emitted verbatim, so it carried Domo backticks (and bare
`CASE … END`) straight into `model.formulas[].expr`. That is not merely one unusable
measure: the model TML fails to import, so the user loses every *other* measure too.
Flagged expressions are now wrapped in a `/* TODO review: … */` marker — the convention
`ts_cli/qlik/build_model.py` already uses — so the rest of the model imports and the
original survives for the human.

## #18 — Cards on Domo pages 2..n vanished — VERIFIED (fixed)

Only the first page becomes a Liveboard (a scope decision the coverage matrix declares).
The problem was silence: later pages produced no mapping row at all, so the report read
`n_pages` from the mapping and asserted "the 1 Domo page(s) map to 1 Liveboard(s)". Each
later page, and every card on it, is now reported `Skipped` with the page named, and
`counts` carries `pages_skipped` / `cards_skipped`.

## #19 — Parsed join cardinality was ignored in favour of a guess — VERIFIED (fixed)

`magic_etl.parse_etl` reads `relationshipType`; nothing consumed it. All seven joins in
the olist fixture declare `MTM` (many-to-many) and every one was emitted `MANY_TO_ONE` —
the report then told the user to verify fan-out on a cardinality the converter invented.

`relationshipType` is now honoured where ThoughtSpot can express it (`MTO`/`OTM`/`OTO`),
and it is read **before** orientation — reading it after the row-count flip inverted a
declared `OTM` into `ONE_TO_MANY` on the fact, which is valid, importable and backwards.

A Domo **many-to-many cannot be expressed as a ThoughtSpot join at all**. To be exact
about what happens: it **is** emitted `MANY_TO_ONE` so the Model still builds, **and** it
carries an explicit warning that measures will fan out until a bridge table exists. An
earlier version of this entry said "warned rather than flattened"; it is both, and the
report says so on the join's own row.

## #20 — `Approximated` never reached the summary layer — VERIFIED (fixed)

`_dropped_constructs` (#11) downgrades a card, but `_risk_level`, `_section_checklist`
and `_section_scorecard` all keyed off the NEEDS-REVIEW tally alone. A conversion where
every card lost its filters and sort still reported:

    - **Risk score:** Low — clean conversion — no structural gaps.
    | Liveboards | 90/100 | 1 page(s) → 1 Liveboard(s). |

with no "rebuild each flagged card" line — the summary re-asserting exactly what the
per-card flagging was added to stop. Risk, checklist and scorecard now all account for
Approximated. The shipped fixture reports Medium / 66-100 instead of Low / 90-100.

## #21 — Smaller correctness fixes from the same review — VERIFIED (fixed)

- **`_UNSUPPORTED_RE` matched column names.** The structural check ran *before*
  backtick→bracket conversion, so `SUM(\`Case Volume\`)` matched `\bcase\b` and was
  flagged — and per #17 that broke the whole model import. "Case …" is ubiquitous in
  CRM/support data. The check now runs after conversion, with bracketed identifiers and
  string literals masked out.
- **`_looks_like_key` used `endswith("id")`**, matching `Paid`, `Void`, `Valid`, `Rapid`,
  `Overpaid` — two tables could join on a boolean flag with no warning, because a single
  candidate was treated as the confident case. It now matches a trailing id-like *token*
  (camelCase-aware, so `customerId` still matches), and a single candidate alongside
  other shared columns reports which ones were not used.
- **`DATEDIFF` was renamed without an arity check.** `DATEDIFF('month', a, b)` became
  `diff_days('month', [End], [Start])` — a 3-arg call to a 2-arg function, graded
  `Approximated`. Arity is now checked — on **every** `diff_days` call in the expression,
  not just the first, which a single `find()` missed when a valid call came first. The
  coverage matrix now says the grain argument is **kept** and the 3-arg form is NEEDS
  REVIEW; an earlier version of this entry claimed that row was corrected before it was.
- **`counts["joins_dropped"]` conflated drops with advisory notes**, so a join that was
  emitted but whose direction was uncertain reported `joins: 1, joins_dropped: 1`. Drops
  and notes are now counted separately.
- **`_APPROXIMATE_MARKERS` was dead**, with `_formula_status` re-inlining the same three
  substrings. The constant now carries marker → caveat and is the single source.

## #22 — Self-review after the second round — VERIFIED (fixed)

Found by auditing my own round-2 changes the same way, rather than waiting for a third
review pass:

- **The naming rule had been reintroduced in two places.** `naming._index_formulas` and
  `build_model._dedupe_beast_modes` each derived the Beast Mode set and dedup rule
  independently — precisely the divergence that caused #16. `naming.deduped_beast_modes`
  is now the single definition and `build_model` consumes it.
  `tests/test_domo_binding.py::TestOneSourceOfTruth` asserts the two stages agree on the
  exact name set, so the collapse cannot silently come back.
- **`BeastMode.status` was parsed and ignored.** Domo marks a broken Beast Mode with
  `status != VALID`; it was translated as though it worked. Now emitted `NEEDS REVIEW`
  with the Domo status quoted — the same "parsed but never consumed" pattern as the
  `relationshipType` finding (#19), found by diffing IR fields the parser populates
  against fields any consumer reads.
- **`QueryColumn.alias` is unmapped and now says so.** An Answer's `answer_columns` must
  name Model columns, so a card-local display label cannot be carried without
  model-level aliasing. Documented in the coverage matrix along with `description` and
  the Beast Mode `global` flag. Domo's `orderBy` references the **alias**, not the
  column, so the dropped-sort note now marks it as such — otherwise the reader hunts for
  a column that does not exist.
- The committed `migration-report.example.md` had gone stale against that note. Docs that
  are generated are now regenerated as part of the change, not after it.

## #23 — The namespace is now owned end-to-end — VERIFIED (fixed)

Round 3 claimed `naming.Index` owned the whole flat Model namespace. It did not, and
three more paths into the same wrong-numbers class survived. All reproduced:

- **`formula_*` was never reserved.** `model_builder` mints ids as
  `formula_<display name>`, so a physical Domo column named `formula_Net` aliased the id
  of a Beast Mode named `Net`. A formula authored as 0.9 × money shipped as 0.9 ×
  quantity — `Migrated`, empty note, `ts tml lint` clean. The prefix is now reserved and
  such a column is renamed (the prefix **stripped**, not suffixed: an early attempt
  produced `formula_Net (column)`, which still aliased).
- **A fourth naming authority.** `build_model` still called
  `formula_common.resolve_name_collisions`, which resolves a column/formula clash by
  **dropping the column** — poisoning every other formula that referenced it. It is no
  longer used as a mutation; see #24.
- **The table pass was decorative.** `taken` was dead after the table loop, so a dataset
  and a column could share a name unrenamed and unreported. Tables, columns and formulas
  now share ONE reserved set.
- **The join graph keyed on raw dataset names**, so two same-named datasets produced
  `[Sales::Order ID] = [Sales::Order ID]` — a self-join — plus a disconnected second
  table, both `Migrated`. `_infer_joins`, the `directed` map and `rows_by_table` all key
  on the resolved name now, and filenames have their own namespace (`Sales-Data` and
  `Sales Data` both slug to `Sales_Data` and one Table TML was silently discarded).
- NFC/NFD names are compared normalised, so two visually identical columns cannot both
  ship; a duplicate raw column name on one dataset is reported instead of overwritten.

**Both property-test exemptions are gone** and the invariant now asserts *object*
identity, not display-name membership — the previous version could not distinguish a
physical column `formula_Net` from a reference to the formula whose id is `formula_Net`,
which is exactly the conflation that hid the first path.

## #24 — `resolve_name_collisions` as an assertion, not a mutation — VERIFIED

`check_converter_parity` requires every formula-emitting converter to use this helper.
Using it as a mutation is what caused the column-dropping above. It is now called as an
**assertion**: `Index` guarantees a collision-free namespace, so the helper must find
nothing, and if it ever does the build fails loudly with the offending names rather than
shipping a quietly-different model. Verified to fire — neutering the index's formula
reservation raises with `would drop ['Region', 'Revenue']`.

The gate passes on the merits rather than by exemption.

## #25 — Determinism is no longer an assumption — VERIFIED (fixed)

`naming.py` claimed the index was safe to derive twice because "same bundle, same
dataset order, same names". Dataset order was **filename sort order**
(`sorted(glob(...))` in `parse_app`), so renaming a fixture file rewrote the namespace,
and nothing bound the two CLI invocations together.

- `ordered_datasets()` sorts by dataset id (tie-broken by name) — a property of the data.
- `build-model` writes the resolved index to `mapping.json`; `build-liveboard` **loads**
  it rather than re-deriving. Re-derivation still works but announces itself.
- A `bundle_digest` is written and checked: `build-liveboard` refuses a `mapping.json`
  built from a different bundle, because binding Answers to a stale Model produces wrong
  numbers rather than an error.
- `app.notes` are printed by every build command. Corrupting one dataset file previously
  gave exit 0, no warning, and cards silently bound to the other table's columns —
  round 1's original bug, reachable with no code change.

## #26 — Host validation closed the class, not four spellings — VERIFIED (fixed)

`_reject_internal_host` classified only canonical IP literals, so `localhost`,
`2130706433`, `127.1`, `0177.1` and `0x7f.1` all reached loopback and the token was
delivered. And Python's IDNA codec treats U+3002/U+FF0E/U+FF61 as label separators, so
`acme.domo.com。evil.example` connected to `acme.domo.com.evil.example` while every UI
string rendered the original — the same threat the userinfo `@` check exists to prevent.

Now: those separators are refused; non-ASCII hosts are IDNA-encoded so what is validated
is what urllib sends; numeric IPv4 shorthands are canonicalised via `inet_aton` before
classification; `localhost`/`.local`/`.internal` forms are refused by name; and the host
is resolved with every returned address classified. 16 hostile inputs refused, legitimate
tenants unaffected.

**Stated as a limitation rather than a guarantee**, in both the module docstring and the
SKILL.md bullet: resolution is a validation-time check, DNS can change afterwards
(rebinding), and an unresolvable host is allowed through so the CLI works offline. The
previous SKILL.md sentence claimed "refuses loopback/link-local/private hosts" while
classifying only canonical literals — a false guardrail reintroduced inside the fix for
one, which is worse than none because it tells the next reader not to look.

Also: server-controlled text is stripped of control bytes before it can reach a terminal
(a transcript-forgery primitive), an undecodable body is an error rather than a
traceback, and `test_no_bypass_flag_exists` asserts positive properties — no TLS context
is constructed, no env var relaxes validation, exactly one request path — instead of
grepping for five literals, of which it caught one.

## #27 — The report no longer contradicts its own mapping — VERIFIED (fixed)

`_risk_level` had been generalised for `Approximated` only, so a bundle that dropped 7
joins still headlined "Automation 100% · Risk Low — clean conversion". Dropped joins and
findings are now inputs, dropped joins are in the automation denominator, and the risk
text names them. A clean bundle still reports Low / 100% / 90.

`n_pages or 1` invented a page, so running `report` after `build-model` alone produced
"Pages → Liveboards | 0 |" in the table and "the 1 Domo page(s) map to 1 Liveboard(s)"
in the prose of the same document. Removed.

Aggregation switches (`SUM` → `AVERAGE` from the shared emitter's name heuristic) were
filed under `invariant_findings` and mislabelled "TML invariant" — it is a semantics
change. They now have their own class, appear on the affected measure's own row as
`Approximated`, and are scoped with `formula_common.expr_is_aggregated` so an
already-aggregating formula (where the property is metadata and applies to nothing) is
not reported.

## #28 — `_looks_like_key` had no test at all — VERIFIED (fixed)

Round 3 claimed "20 cases pinned, both classes". `grep -rn '_looks_like_key' tests/`
returned zero matches: the pinning happened in a session and was never committed. That
is the fourth occurrence of the record running ahead of the change, and the most
`grep`-able one.

`tests/test_domo_naming.py` pins 35 cases across both directions, and writing them
immediately found two live bugs the claim had covered for: `urn` matched as a *glued*
suffix so `Churn`, `Return`, `Turn` and `Saturn` were all treated as join keys, and
singular/plural disagreed (`bid` False, `bids` True). `urn` now matches only as a
separated token, and a glued suffix requires two characters of stem — which is also what
makes the plural consistent.

## #29 — Final self-audit before merge — VERIFIED (fixed)

Swept the repo rather than the diff, and found four more things. Recording them because
three are the same *shape* as findings the reviewer raised, which is the useful signal.

- **Four CI validators had never been run locally.** My sweep script was a hand-kept
  parallel list, so `check_ci_gate_coverage`, `check_harness_routing`,
  `check_audit_workflow_permissions` and `check_mapping_code_sync` were invisible to it —
  and so was the `suggest_dependency_types --base` PR gate. The sweep now *extracts* the
  command lines from `.github/workflows/validate.yml`, so a gate added upstream cannot
  be missed again. All 38 pass, plus all four PR-scoped gates.
- **Five mapping keys were stored and never shown** — `table_renames`,
  `formula_renames`, `name_ambiguities`, `parse_notes`, `join_advisories`. Exactly the
  "recorded in the mapping, contradicted by the report" pattern from #27, one layer
  further out. Renames now have their own report section, and unread sources plus
  ambiguous names lead Manual review.
- **An unread source file still reported "Risk: Low — clean conversion".** A parse note
  means data is *missing*, which outranks every other class, so it now dominates the
  risk score and the headline says the conversion is incomplete.
- **`Index.derived` was read only by a test**, duplicating a local that recorded the same
  fact. The field is now the single source and the local is gone.

`tests/test_domo_pipeline.py` was added because every earlier test drove the two build
stages in-process, which cannot catch a cross-stage drift — the thing that actually went
wrong four times. It runs the real CLI and asserts that every column an Answer names
exists in the Model written beside it on the right table, that the index was loaded
rather than re-derived, that both stages agree on the bundle digest, that a second run
is byte-identical, and that `ts tml lint` passes on the output.

