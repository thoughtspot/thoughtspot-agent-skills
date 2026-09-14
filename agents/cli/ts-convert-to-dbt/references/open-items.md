# Open Items — ts-convert-to-dbt

Unverified API/product behaviour and known gaps. Per `.claude/rules/api-research.md`,
each item records whether it was resolved via docs research, a live test, or is
still open.

Item **numbers are permanent** — SKILL.md and coverage-matrix.md cite them by
number, so a resolved item keeps its heading rather than being deleted or
renumbered. Resolved items are condensed to their verdict and the finding worth
keeping; the full investigation narratives were compressed 2026-09-09.

## Status at a glance

| # | Item | Status |
|---|---|---|
| 1 | `ts_*` metadata tags in schema.yml | VERIFIED live 2026-08-27 |
| 2 | Legacy MetricFlow spec (semantic_models.yml) | **OPEN** — now opt-in; importer still untested |
| 3 | Formula/calculated column translation | VERIFIED live 2026-09-09 |
| 4 | Case B — update an existing project in place | VERIFIED live 2026-09-09 |
| 5 | Composite-key joins | DEFERRED (low) |
| 6 | Entity naming collision across Models | **OPEN** |
| 7 | Scope: generate a project, not the round trip | RESOLVED (decision) |
| 8 | Never verified against dbt-core | VERIFIED 2026-09-10 + breakage FIXED |
| 9 | Full documented tag coverage | RESOLVED 2026-09-09 |
| 10 | `diff` assumed a flat project layout | FIXED 2026-09-01 |
| 11 | Multi-fact Models split into several | RESOLVED 2026-09-02 |
| 12 | `ts_index_type` case-sensitivity | VERIFIED live 2026-09-10 |
| 13 | Column Security Rules not in Table TML | **OPEN** — needs a design decision |
| 14 | `sync --update-metadata` end-to-end | VERIFIED live 2026-09-09 |
| 15 | Three tags are ts-cli extensions | RESOLVED 2026-09-09 |
| 16 | `ts_column_exclude` is read but never written | NOTED — by design |
| 17 | `sync --update-metadata` deleted hand-authored tags | FIXED (never shipped) |
| 18 | Case A renamed tables and joins on the round trip | FIXED + VERIFIED live 2026-09-09 |

**Three genuinely open: #2, #6, #13.** #8 closed 2026-09-10: the primary
artifact is verified against dbt-core 1.12.4, and the dbt-core breakage it
exposed in the secondary artifact is fixed (that file is now opt-in). #2 still
needs an instance with ThoughtSpot's MetricFlow importer enabled — but it is no
longer harmful while unanswered, since nothing emits the file by default. #6
needs a real multi-Model dbt project; #13 is a design decision that could be
made today.

---

## #1 — `ts_*` metadata tags (schema.yml) — VERIFIED live 2026-08-27

The primary artifact emits ThoughtSpot's own `ts_*` tags under `meta:`. Tag list
and nesting verified against docs.thoughtspot.com/cloud/26.9.0.cl/
dbt-integration-metadata-tags; TML property→tag mapping against
`agents/shared/schemas/thoughtspot-model-tml.md`. See #9 for the full set.

**The durable finding — nesting is not optional.** Column tags must sit under
`config: {meta: {...}}`, and a relationships test needs `data_tests:` +
`arguments: {to, field}` + `config: {meta: {...}}`. The bare `meta:`/`tests:`/
`to:`/`field:` shape that ThoughtSpot's own docs example shows produced hard
parse **errors** under dbt-fusion 2.0.0-preview.212 — even a plain column-level
`meta:` with no test involved. Verified past parse too: the compiled
`target/manifest.json` carries every `ts_*` tag intact, which is the artifact
`dbtGenerateTml` actually reads. Cross-confirmed against a real
dbt-cloud-managed project using the same nested shape independently.

`tests:` vs `data_tests:` is a still-accepted alias either way; the exporter
emits `data_tests:` as dbt's current canonical name. What breaks is the bare
shape inside each entry, not the list-key name.

Verified against dbt-fusion and dbt Cloud only — see #8.

---

## #2 — Legacy MetricFlow spec (semantic_models.yml) — OPEN

The secondary artifact targets the **legacy** top-level `semantic_models:`/
`metrics:` spec, not dbt's current nested one, because ThoughtSpot documents
MetricFlow support only through "dbt 1.7 and earlier" — which predates the
nested spec (dbt Core 1.12+).

**Verified:** `dbt-fusion parse` accepts it with a deprecation *warning*, not an
error — valid, still-supported syntax.

**Open:** whether ThoughtSpot's MetricFlow importer actually reads it. Never
tested against a live instance with that feature enabled. This artifact carries
no join cardinality/type/name at all (MetricFlow entities are pure identity), so
that fidelity lives only in `schema.yml`.

Related: `ts-convert-from-dbt` #14 (L11) records that ThoughtSpot's server-side
MetricFlow importer produced **nothing** on the tested instance across three
connection shapes — which is evidence against this artifact being read at all,
though not against this file's validity.

**2026-09-10 — the cost/benefit shifted, and this now needs deciding.** #8 found
that this file makes a generated project **fail `dbt parse` under real dbt-core
1.12.4** whenever it carries a time dimension (no `metricflow_time_spine` model
is emitted alongside it). So the artifact is not merely unproven — it actively
breaks the project for dbt-core users, while the only evidence about its
consumer says nothing reads it. Removing the file makes the same project parse
clean.

**Resolved by #8's fix:** the file is now written only with `--semantic-models`,
so an unanswered #2 no longer costs anyone a broken project. The question of
whether ThoughtSpot reads it stays open, and the flag is how to test it.

---

## #3 — Formula/calculated column translation — VERIFIED live 2026-09-09

Formula columns are emitted as `ts_formula` in `config.meta`, placed under the
dbt model matching the first `[TABLE::COL]` reference in the expression
(`_first_table_ref`). The expression is preserved **verbatim** rather than
translated to SQL, and restored verbatim on the return leg by
`build_model_tml_from_schema_yml`.

That choice is the point: translating ThoughtSpot formula syntax into a dbt
`expression:` would need a translation reference and would break on unsupported
functions. Round-tripping the text needs neither.

A formula whose expression contains no `[TABLE::COL]` reference has no model to
attach to and is reported in `skipped_formulas`.

**Live 2026-09-09 — the class that triggers this is now known.** A round trip of
`BARBERSHOP_OPERATIONS` (14 formulas) skipped exactly 2: `Tip Rate` and
`Net Revenue`. Both are **MetricFlow metrics of type `ratio` / `derived`**,
which `ts dbt build-model` translates into formulas that reference *other
metrics* rather than table columns — so `_first_table_ref` correctly finds
nothing. The 6 `simple` metrics round-tripped fine.

This is a structural limit, not a bug: a derived metric has no single owning
table, so there is no dbt model it could be attached to. It is reported at
build time, and the re-import is lossless for everything else (74 → 72 columns,
7/7 tables, the 2 lost being exactly the 2 reported). The remedy if the
formulas matter is `ts dbt build-model` (dbt Cloud), which regenerates them
from the manifest's `metrics:` — verified live the same day by restoring the
Model to 14 formulas after the lossy return leg.

**Live:** 14 formulas exported, pushed through a dbt Cloud job, and rebuilt with
zero delta (see #14). Tests: `TestFormulaColumnsInSchemaYml`.

---

## #4 — Case B (update an existing dbt project in place) — VERIFIED live 2026-09-09

`diff`/`sync` mirror `ts snowflake diff`'s Mode C: diff two flattened column
maps and report a change-set, rather than merge YAML structurally. `diff` is
read-only; `sync` is additive-only unless `--update-metadata`.

**The three refusals that make `--update-metadata` safe to offer:**

- a `removed_column` is deleted only if `_is_ts_only_column` passes — no
  description, no non-`ts_*` meta key, no data test other than `relationships`
- `removed_relationship` is never auto-deleted
- a description **cleared** in ThoughtSpot is neither reported nor applied, so a
  resync cannot silently wipe hand-written dbt documentation

**Name adoption.** An existing project's own model names are adopted, not
overwritten with `stg_<table>`. Each Model table is paired with the on-disk
model that either selects from its warehouse location (`{{ source() }}` matched
on database/schema/table) or produces it (the Table's `db_table` equals a model
name — what `ts-convert-from-dbt` leaves behind). Reported as `adopted_names` /
`dbt_output_tables`; `removed_tables` is narrowed to those models' directories
(`scoped_to`). **An empty `adopted_names` against a project that demonstrably
holds these tables means matching failed** — stop rather than trust `new_tables`.

**Scoped to `models/schema.yml` only.** A change to `models/semantic_models.yml`
on an existing table is un-reported (not corrupted) — see #2.

**Disclosed limitation:** appends are a full `yaml.safe_load` → append →
`safe_dump` round-trip, so the whole file reformats and comments are lost. Run
only against a version-controlled project and review `git diff`.

Still unit-tested only: the column-**deletion** branch (no live run has removed
a column).

---

## #5 — Composite-key joins produce no entity or relationships test — DEFERRED (LOW)

A composite-key join (`[A::C1] = [B::C1] and [A::C2] = [B::C2]`) is reported in
`skipped_composite_joins` rather than mis-emitted. dbt's own `relationships:`
test is single-column too, so the limitation is shared by both artifacts, not
specific to this exporter. No Model in testing has used one.

---

## #6 — Entity naming collision across unrelated Models — OPEN

`semantic_models.yml` derives an entity `name:` as `to_snake(right_table_node_key)`.
Two different ThoughtSpot Models exported into the same dbt project, each joining
a differently-defined table sharing a node key (two unrelated `CUSTOMERS`), would
emit same-named entities in different semantic models — MetricFlow could then
treat them as joinable to each other.

Not a problem in single-Model testing. Needs a real multi-Model dbt project.

---

## #7 — Scope: generate a dbt project only, not the full round trip — RESOLVED (decision) 2026-08-27

This skill stops at a valid, compilable dbt project. It does not run `dbt`, zip
anything, call the dbt Cloud API, or invoke `ts dbt create`/`generate-tml`.
Driving the compile step would couple the skill to whichever dbt tooling,
connection type and warehouse credentials the user happens to have.

**The hand-off branches by connection type — it is not one universal "zip and
upload".** `ZIP_FILE`: run `dbt docs generate` yourself, then point
`ts dbt create --import-type ZIP_FILE --file <target dir>` at the result (the
CLI builds the archive — `ts-convert-from-dbt` #4). `DBT_CLOUD`: no artifact
changes hands locally at all — commit the files and let a dbt Cloud job run.

`dbt docs generate` needs the tables to exist and be queryable (it introspects
real schema), though not to be fully populated. ZIP_FILE path only.

---

## #8 — Not verified against dbt-core — VERIFIED 2026-09-10; the dbt-core breakage it exposed is FIXED

All parse/manifest verification used dbt-fusion 2.0.0-preview.212, plus a live
dbt Cloud job. The nested config syntax this exporter targets is comparatively
recent, and is **not verified against dbt-core** at any version — including the
1.7 line ThoughtSpot's own MetricFlow docs name as the supported ceiling.

If a real dbt-core project rejects it, the older bare shape (matching
ThoughtSpot's docs example verbatim) may be what works there, and the two may
need to be version-conditional rather than a single fixed choice.

**Settled 2026-09-10 against real dbt-core 1.12.4 + dbt-snowflake 1.12.0**
(isolated venv), parsing a project `ts dbt-export build` had just generated from
`BARBERSHOP_OPERATIONS`.

**The primary artifact passes — this is the headline.** `dbt parse` completed
clean, and dbt-core's own `target/manifest.json` carries everything the return
leg depends on:

- `alias: APPOINTMENTS` on `stg_appointments` — **the identity fix survives dbt-core**
- all 4 `ts_*` column tags in `columns[].meta`
  (`ts_column_type`, `ts_index_type`, `ts_ai_context`, `ts_display_name`)
- all **7** `ts_join_*` relationship tests with meta intact in `config.meta`

Feeding that dbt-core manifest back to `ts dbt list-models` returned the 7
aliased table names. So the nested `config:` / `meta:` / `data_tests:` syntax
this exporter targets is **not** fusion-only — the fallback to the older bare
shape this item worried about is not needed.

**The secondary artifact breaks dbt-core.** With `models/semantic_models.yml`
present, `dbt parse` fails outright:

```
Parsing Error
  The semantic layer requires a time spine model with granularity DAY or
  smaller in the project, but none was found.
```

Removing that one file makes the same project parse cleanly. `ts dbt-export
build` emits semantic models with time dimensions but never emits the
`metricflow_time_spine` model dbt-core requires alongside them, so **every
generated project containing a time dimension is unparseable by dbt-core as
shipped**. dbt-fusion did not enforce this, which is why it went unseen.

**FIXED the same day — the artifact is now opt-in.** `ts dbt-export build` no
longer writes `models/semantic_models.yml` unless `--semantic-models` is passed,
so a generated project parses under dbt-core out of the box (re-verified: the
same Model now yields 10 files and a clean `dbt parse`). stderr says the file was
withheld and how to get it, and passing the flag warns when the project would
need a time spine — the warning was checked against dbt-core and predicts the
exact error.

Emitting a time spine instead was rejected: it would materialise a date table
the user never asked for, in dialect-specific SQL, to support an artifact with
no known consumer (#2, and `ts-convert-from-dbt` #14).

`ts-convert-to-dbt` SKILL.md already carried a caution not to copy this file
into an existing project for precisely this reason — a rule the LLM had to
remember. Moving it into the command's default is `.claude/rules/repo-audit.md`
angle 11 ("agentic → deterministic") applied to a real failure.

Tests: `TestSemanticModelsAreOptIn`.

**Both engines, checked against the SAME generated project (2026-09-10):**

| | default output | with `--semantic-models` |
|---|---|---|
| dbt-core 1.12.4 | `parse` clean | **hard error** — needs a time spine |
| dbt-fusion 2.0.0-preview.212 | `parse` clean | parses, 1 deprecation warning |

The deprecation is `SemanticModelDeprecated (dbt1157)` — "defines semantic models
and metrics using the legacy YAML … migrate to the new YAML to use the semantic
layer with dbt Fusion". So the legacy spec this artifact targets (#2) is on
fusion's deprecation path as well as being a hard failure on core.

The two engines produce **equivalent manifests** for everything ThoughtSpot
reads: 7 models, `alias: APPOINTMENTS`, the same four `ts_*` column tags, and 7
`ts_join_*` tests. `ts dbt inspect` and `ts dbt list-models` return identical
results against either.

**`dbt run` also verified on both, against live Snowflake (`DL_TEST`, se
snowflake), 2026-09-10.** Not just `parse` — both engines built all 7 models:

| engine | result | target schema |
|---|---|---|
| dbt-core 1.12.4 | `PASS=7 WARN=0 ERROR=0` in 5.1s | `DBT_DLEE_PROD_ROUNDTRIP_CORE` |
| dbt-fusion 2.0.0-preview.212 | `7 total \| 7 success` in 4.2s | `DBT_DLEE_PROD_ROUNDTRIP_FUSION` |

Each run was pointed at its own scratch schema via a `+schema` config rather
than the profile's default — the profile targets `DBT_DLEE_PROD`, which is the
**source** schema, and an aliased model materialised there overwrites the very
relation it selects from. That is the hazard `--target-schema` refuses at build
time (#18); here it was avoided by redirecting the target. The source schema was
confirmed unchanged afterwards: 8 base tables + 27 views, no new objects.

---

## #9 — Full documented tag coverage — RESOLVED 2026-09-09

All 13 documented column tags are now emitted and read back. `is_hidden`,
`calendar`, `currency_type` and `geo_config` had previously been withheld.

**Why they were withheld, and why that was wrong.** The four had been lumped
together as "the ones we don't emit", but they had two different blockers and
neither survived re-reading the sources:

| Property | What the source actually says | Resolution |
|---|---|---|
| `is_hidden` | thoughtspot-model-tml.md:243 — "Do not set during conversion or model creation" | Scoped to *creating* a Model from another source. This returns a value the owner already set to the same Model — a round trip |
| `calendar` | :253 — "Do not emit when generating a model — pass through on round-trips only" | The carve-out is explicit. This IS the round-trip leg |
| `currency_type` | :246 — "Only `iso_code` is used when generating new models; accept all three when round-tripping" | No prohibition at all. The real blocker was the unknown tag shape |
| `geo_config` | :247 — one neutral line | Same: unknown shape, not a warning |

**The shapes are nested, with a `type` discriminator** — not the flat values
this reference had assumed, which is exactly why the mapping looked
unverifiable:

```yaml
ts_currency_type:
  type: from_isocode        # or from_column (+ column:), from_browser, none
  isocode: USD
ts_geo_config:
  type: sub_nation_region   # or latitude, longitude, country, none
  country: United States
  region_type: State
```

**Found while fixing it — four tags were write-only.** `ts_index_priority`,
`ts_attr_dim`, `ts_additive` and `ts_spotiq_pref` were emitted but consumed by
*neither* reader, so they reached dbt and were dropped coming back. Both readers
had inlined their own partial copy of the tag→property mapping and both were
missing the same four. Replaced with one shared `tml_properties_from_ts_meta`;
`test_manifest_reader_agrees_with_schema_yml_reader` pins that they cannot
diverge again. Formula columns now share `_build_column_meta` with physical
columns rather than taking a narrower path that lost real data.

`TestFullPropertyRoundTrip` asserts property-for-property equality across
TS → schema.yml → TS, including every geo role and currency form.

### Still genuinely unmappable

| Construct | Why |
|---|---|
| `geo_config` custom-map role (`custom_file_guid` + `geometryType`) | No `ts_geo_config` type covers it, and it is instance-local — "a portable document must not carry it" |
| `index_type` outside `DEFAULT` / `DONT_INDEX` | `ts_index_type` documents only two of TML's five values |
| `value_casing`, `custom_order`, `default_date_bucket`, `search_iq_preferred` | No `ts_*` tag exists at all. Now reported in `unmapped_properties`; closing them needs new tags from ThoughtSpot |

`synonym_type` needs no tag — it is derived on read-back (`USER_DEFINED`
whenever synonyms are present).

**Unverified:** the docs show `region_type: State` / `country: United States`
(title case) while the TML census shows `region_name: "state"` /
`country: "UNITED STATES"`. Values pass through verbatim both ways, so a
same-instance round trip is exact — but whether ThoughtSpot's importer is
case-sensitive here is untested. If a geo role fails to apply, check casing first.

---

## #10 — `diff` assumed the flat project layout `build` generates — FIXED 2026-09-01

Against a real project (`models/marts/core/*.sql`, `models/staging/jaffle_shop/*.sql`)
`diff` reported `new_tables: 2` instead of `changed_tables: 2`. Three hardcoded
assumptions held only for projects this skill had itself generated:
non-recursive `glob("*.sql")`, a hardcoded `models/schema.yml`, and a hardcoded
`models/staging/sources.yml`.

**Fixed:** `_load_project_state` uses `rglob("*.sql")` and merges every `*.yml`
under `models/` into one virtual schema doc and one virtual sources doc.
`_find_sources_file` `rglob`s for the file that actually declares `--source-name`
and writes back to that one, rather than hoisting other directories' sources into
it. Test: `TestDiffCmd::test_nested_layout_finds_sql_and_yaml`.

The naming mismatch this left behind was fixed separately — see #4's name adoption.

---

## #11 — Multi-fact Models don't round-trip as one Model via `generate-tml` — RESOLVED 2026-09-02

`generate-tml` created **3 separate Models** from a 7-table barbershop
`schema.yml` with correct `ts_join_*` tests. ThoughtSpot builds one Model per
connected component of the dbt FK graph, and BARBERSHOP_OPERATIONS is multi-fact:
APPOINTMENTS and PRODUCT_SALES are independent facts sharing BARBERS/CUSTOMERS.
No dbt construct says "these two facts belong in one ThoughtSpot Model."

Single-fact star schemas round-trip fine.

**Resolution — Path Y**: `ts dbt generate-tml --import-worksheets NONE` creates
Tables only, then `ts dbt-export build-model --schema-yml` assembles one unified
Model from the `ts_join_*` tests. Always one Model, however many facts.

**Remaining limitation:** `generate-sync-tml` has no `--import-worksheets`
equivalent, so a resync refreshes Tables only. If the join graph changed, re-run
`build-model` afterwards (`ts-convert-from-dbt` Step 10.4).

---

## #12 — `ts_index_type` case-sensitivity — VERIFIED live 2026-09-10

ThoughtSpot documents lowercase (`default`, `dont_index`); TML uses uppercase
(`DONT_INDEX`). The exporter carries `_TS_INDEX_TYPE_MAP` /
`_TS_INDEX_TYPE_REVERSE_MAP` plus `_apply_index_type` to convert both ways.

**To verify:** write `ts_index_type: DONT_INDEX` (uppercase) into a schema.yml,
run `ts dbt generate-tml`, and check whether the column carries
`index_type: DONT_INDEX` or is silently ignored.

**Settled live 2026-09-10 — the two forms really are different, and the map is
required.** Traced one column, `appointments.APPOINTMENT_DATETIME`, all the way
round against dbt Cloud project 130012 + the Prod org:

| Stage | Value |
|---|---|
| dbt manifest `config.meta.ts_index_type` | `dont_index` (lower) |
| ThoughtSpot Table TML after `generate-tml` | `properties.index_type: DONT_INDEX` (upper) |
| `ts dbt-export build` → `schema.yml` | `dont_index` (lower) |
| `ts dbt-export build-model` → Model TML | `DONT_INDEX` (upper) |

So ThoughtSpot's server-side importer reads the **documented lowercase** form and
stores the TML uppercase. `_TS_INDEX_TYPE_MAP` / `_TS_INDEX_TYPE_REVERSE_MAP` /
`_apply_index_type` are doing real work and must stay — storing the raw TML value
verbatim would write `DONT_INDEX` into `schema.yml`, which is not the form the
manifest uses. 8 columns round-tripped with the flag intact and none acquired or
lost it.

**Two caveats, deliberately not claimed as verified.** (1) Whether ThoughtSpot
*also* tolerates uppercase in the dbt meta tag is untested — the live project
uses lowercase throughout, and since the exporter now provably writes lowercase,
this is a robustness question, not a correctness one. (2) `index_type` sits at
`columns[].properties.index_type`, not on the column root; a reader that looks at
the root sees `None` on a column that does carry the flag.

---

## #13 — Column Security Rules (CSR) not in Table TML — OPEN

A table with a CSR applied exports no CSR data in its Table TML — `ts tml export`
returned only `rls_rules`. CSR lives behind a separate API
(`security/column/update`, read via `security/column/fetch`), which
`ts security column-rules` already wraps.

RLS by contrast round-trips fully via `ts_rls_rules`.

**To include CSR in the two-way sync:**
1. **Export** — call `ts security column-rules get --table {guid}` after the TML
   export; serialise as `ts_csr_rules` in the model's `config.meta` using group
   and column *names* (portable, unlike GUIDs).
2. **Import** — a `ts dbt-export apply-security --schema-yml`, or an extension of
   Path Y, that reads the tag and calls `ts security column-rules apply`.
3. **The hard part** — CSR identifies principals by group name, and group names
   are Org-scoped. A round trip into a different Org requires those groups to
   exist there; the importer must **warn on a missing group, never silently
   skip**.

Needs a design decision on the key shape and the import-side command. Not blocked
by anything else.

---

## #14 — `sync --update-metadata` end-to-end — VERIFIED live 2026-09-09

Run against the barbershop project and the `Embed-1-Prod` Model
(`208c4bfa-8e68-4064-9e97-5defde8a7d22`), job 1121584 → commit 08f871b → dbt
Cloud run 510481448:

1. Path Y built the Model — RLS on BARBERS, 5 `ts_ai_context`, 49 descriptions,
   14 `ts_formula` formulas verified on export.
2. Edited `Tip Amount` in ThoughtSpot: new description + synonym `gratuity`.
3. `diff` showed the synonym; **the description change was missing** — a real
   reporting gap, fixed the same day (`modified_description` in `dbt_diff.py`).
4. `sync --update-metadata` wrote both, and appended a catalog-only column
   `CHANNEL_ID`. The rest of the `git diff` was YAML reformatting.
5. Rebuild from the new manifest: **zero column / formula / join delta.**

**Side finding, fixed the same day:** `ts tml import` reported the update as
"did not import" (exit 1) on a per-item `status_code` of `WARNING`
("columns with misconfigured suggestion settings") — the re-export proved it had
landed. `WARNING` now counts as imported, with the notice on stderr. The REST
spec types the response only as `array of object`, so the live observation is the
only evidence.

**Pre-deletion gate.** Before committing any auto-deleted column, run
`ts columns impact --column "<display name>" --physical-col "<db col>"
--model {guid} --table {guid}`. A non-empty `objects` list means dependents
still exist. Not exercised live — no column was removed in this run.

---

## #15 — Three tags this exporter emits are ts-cli extensions — RESOLVED 2026-09-09

`ts_formula`, `ts_display_name` and `ts_ai_context` are **ts-cli extensions**,
not on ThoughtSpot's documented tag page. `ts_ai_context` was the uncertain one;
the skill author confirmed it is a gap filed with ThoughtSpot that has not
shipped natively (`ts-convert-from-dbt` #16).

**The consequence, which is the part that matters:** a project built here and
synced back through **Path N** (server-side Model generation) loses all three,
silently. Only **Path Y** (`ts dbt build-model`) is lossless. SKILL.md Step 9's
hand-off guidance now states this explicitly — it previously did not.

`ts_column_exclude` is a fourth extension; see #16.

---

## #16 — `ts_column_exclude` is read but never written — NOTED

`is_column_excluded` is consumed in three places — `build_model_tml_from_manifest`
(leaves the column out of the Model), `dbt_diff._parse_column_entry` (so an
excluded column never reads as removed/changed), and `_is_ts_only_column` (so
`sync --update-metadata` never deletes one). `build_dbt_export` never emits it,
because no ThoughtSpot property means "keep on the Table, omit from the Model."

The asymmetry is correct — the tag is hand-authored — but a round trip is stable
only because all three consumers agree to leave it alone. Recorded so a future
change to the diff or the deletion gate doesn't drop one and start silently
deleting hand-authored exclusions. No action needed.

---

## #17 — `sync --update-metadata` silently deleted hand-authored `ts_*` tags — FIXED 2026-09-09 (never shipped)

**The bug.** `_merge_ts_meta` rebuilt a column's `config.meta` as "every
non-`ts_*` key from disk, plus every `ts_*` key from the fresh generation" —
treating the whole `ts_*` namespace as generator-owned. It is not. Any tag a user
wrote that the generator does not itself emit was absent from every fresh
generation and therefore **deleted on the next sync**, with no error, no warning
and no change-set entry. `ts-convert-from-dbt` Step 5.5 actively tells users they
may author such tags, so this was reachable by following the documentation.

`dbt_diff._diff_column` had the same blind spot: it compared whole `meta` dicts,
so `diff` reported the hand-authored tag as a change and `sync` acted on it.

**The fix — an explicit ownership boundary declared next to the emitters.**
`GENERATED_COLUMN_META_KEYS` / `GENERATED_MODEL_META_KEYS` say what `build` can
produce; `_merge_ts_meta` clears only those. The fresh side still filters on the
`ts_` prefix, so a tag a future emitter adds is written even if the set hasn't
caught up — failing in the write-it-anyway direction is the safer drift.
`_owned_meta` restricts `diff` to the same set, so it reports exactly what `sync`
applies. Preserved tags are **reported** via `preserved_meta` and a stderr
summary: silence was half the bug.

**Drift protection.** `TestGeneratedMetaKeyBoundary` asserts the declared set and
the emitted set are *equal*, in both directions — a key emitted but undeclared
would never be cleared (a removed property lingers); a key declared but never
emitted means `sync` deletes a hand-authored tag of that name.

The four documented tags that originally triggered this (`ts_hidden`,
`ts_calendar_type`, `ts_currency_type`, `ts_geo_config`) are themselves generated
as of #9, so the boundary now serves forward-compatibility — an unknown tag from
a newer ThoughtSpot — rather than those four.

---

## #18 — Case A renamed tables and joins on the round trip — FIXED 2026-09-09 (never shipped)

**The bug.** Case A named each staging model `stg_<table>`, which with no alias
materialises as `STG_<TABLE>`. Syncing the project back therefore imported a
**second** ThoughtSpot Table beside the original: the Model silently repointed at
the copy, while the original kept every dependent it had. Valid output, wrong
result, no diagnostic. Separately, `ts_join_name` was emitted as a derived
`<left>_to_<right>` rather than the join's own name, renaming every join on each
trip.

**The fix.** Staging models carry `config.alias: <TABLE>`, so dbt materialises
under the name ThoughtSpot already knows. Both readers resolve through the alias
(`_table_name_of` in the schema.yml reader; `manifest_table_locations` already
did on the manifest side), including `ref()` → model → alias for join targets.
`ts_join_name` now carries the join's own name; the derived form is still
generated for platforms with identifier rules (Snowflake SV) and kept beside it
as `join_data["name"]`.

**Deliberately not aliased:** an **adopted** Case B name (#4). Those models
already materialise somewhere real, and forcing an alias would repoint live
warehouse relations.

**New consequence — `--target-schema`.** An aliased model materialised into its
own source's schema would overwrite that source. `ts dbt-export build
--target-schema DB.SCHEMA` refuses at build time when it would; omitted, the
command names on stderr which schemas dbt must avoid. It cannot detect this on
its own — the target schema lives in the user's `profiles.yml`, which this
offline command never reads.

Tests: `TestRoundTripPreservesIdentity`, `TestTargetSchemaCollision`, and the
`build → diff` no-op assertion in `tools/smoke-tests/smoke_ts_convert_to_dbt.py`.

**VERIFIED live 2026-09-09** — full round trip of `BARBERSHOP_OPERATIONS`
(7 tables, Prod org, connection `fe5ebaf8-…`):

- `build` emitted all 7 staging models with `config.alias:` set to the original
  Table name, and warned on stderr that dbt must target a schema other than
  `DL_TEST.DBT_DLEE_PROD`.
- `build --target-schema DBT_DLEE_PROD` **refused before any write** — the
  output directory was not even created.
- Feeding the generated project back through `build-model --schema-yml`
  returned `model_tables` = the 7 original names. Re-running the same command
  against a copy with `alias:` stripped returned `STG_APPOINTMENTS` … — the
  duplicate-Table defect, reproduced and then fixed, on real data.
- Re-importing with `--model-guid --import` gave `created_new: false` on the
  same GUID. Table count before and after: **7 → 7, zero `STG_*` objects**.
- All 7 joins came back carrying the author's own `ts_join_name`
  (`appointments_to_barbers`, …), not a derived form.

**Proven in the warehouse 2026-09-10.** `dbt run` on the generated project
(both dbt-core 1.12.4 and dbt-fusion) created the relations under their
**ThoughtSpot names** — `APPOINTMENTS`, `BARBERS`, `CUSTOMERS`, `PRODUCTS`,
`PRODUCT_SALES`, `SERVICES`, `TRANSACTIONS` — not `STG_*`. The alias is not just
a manifest field; it is what Snowflake ends up called.

**And the pre-fix damage is real, not hypothetical.** `DL_TEST` still holds
seven orphaned views in `DBT_DLEE_PROD`, all created **2026-09-04** (before the
fix): `STG_APPOINTMENTS`, `STG_BARBERS`, `STG_BS_CUSTOMERS`, `STG_PRODUCTS`,
`STG_PRODUCT_SALES`, `STG_SERVICES`, `STG_TRANSACTIONS`. None of the seven
exists as a model or alias in the live dbt project, and each selects from the
same `DL_TEST.BARBERSHOP_DEMO.*` base table as its un-prefixed twin — a
redundant parallel copy of the whole barbershop set, exactly the duplication
this item describes. They are inert leftovers; deleting them is safe but is a
warehouse change, so it has not been done here.

**Caveat on the `diff` no-op:** it does *not* exercise the alias. `diff` matches
models by their `source()` reference (`_existing_models_by_source_table`), which
is alias-independent — stripping every `alias:` still diffs clean. The no-op
proves writer/reader agreement; the return leg above is what proves identity.
