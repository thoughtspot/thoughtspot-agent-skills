# TPC-DS conversion-fidelity cross-validation vs apache/ossie fixtures

**Date:** 2026-07-29 · **Branch:** `feat/ossie-tpcds-fidelity` · **Plan:** `docs/superpowers/plans/2026-07-29-ossie-tpcds-fidelity.md`

**Upstream source:** apache/ossie @ `c26b61cafa41699106110a62620062f49a7c5482` (2026-07-29), read-only clone at `/Users/damianwaldron/Dev/ossie`, working tree clean.

| Fixture | Path | git blob SHA |
|---|---|---|
| Databricks Metric View (vendor source) | `converters/databricks/tests/fixtures/tpcds_metric_view.yaml` | `b22fc698017aa2a8add1723dc76faf80c7af9293` |
| OSI hub form (semantic referee) | `converters/databricks/tests/fixtures/tpcds_ossie.yaml` | `e055eab1e9a913d3ca49bdbf6ccf4f07b19cec0d` |

**Our converter under test:** `ts` CLI v0.124.2 (repo `tools/ts-cli/pyproject.toml` and installed `thoughtspot-cli` agree), driven per `agents/cli/ts-convert-from-databricks-mv/SKILL.md` v1.10.2 and `agents/cli/ts-convert-to-databricks-mv/SKILL.md` v1.3.1.

**Method summary.** Round-trip apache/ossie's community-reviewed TPC-DS fixtures through our converters in both directions and compare per construct against the vendor source, with the OSI hub form as the semantic referee. Databricks first (Section 2) — the upstream fixture is a real Metric View, so the format match is direct and the whole exercise runs offline. Conversions use the skills' documented deterministic `ts` CLI pipelines, never hand-translation or ad-hoc scripting (`.claude/rules/ts-cli.md`). No ThoughtSpot import and no Databricks execution: validation is `ts tml lint` plus `tools/validate/check_tml.py`. Generated artifacts live in the gitignored SDD workspace (`.superpowers/sdd/2026-07-29-ossie-tpcds-fidelity/dbx/`), not the repo tree.

**Verdict vocabulary** (used verbatim throughout): `matched` · `mis-inferred` (both definitions shown verbatim) · `missed` (present in source, absent in ours) · `extra` (ours adds something the source lacks) · `not-applicable` (construct outside the skill's documented scope — coverage-matrix row cited).

---

## 1. Method and inputs

### 1.1 Why this fixture

`tpcds_metric_view.yaml` is the strongest available baseline because **upstream's own round-trip on it is lossless**. `converters/databricks/tests/test_roundtrip.py:57-63` (`test_tpcds_mv_round_trips`) asserts MV → OSI → MV is structurally byte-faithful for this exact file, and `converters/databricks/tests/test_ossie_to_metric_view.py:33-38` (`test_tpcds_export_matches_expected`) asserts the OSI → MV direction reproduces it exactly. Any loss measured below is therefore **ours**, not inherited from the fixture pair.

### 1.2 Source inventory — the fidelity denominators

Parsed from `converters/databricks/tests/fixtures/tpcds_metric_view.yaml`.

**Top-level properties (4):**

| # | Property | Value | Line |
|---|---|---|---|
| T1 | `version` | `'1.1'` | :18 |
| T2 | `source` | `tpcds.public.store_sales` | :19 |
| T3 | `comment` | `Store sales enriched with date, item, and customer dimensions` | :20 |
| T4 | `filter` | `ss_net_profit > 0` | :21 |

**Joins (3 constructs, 12 properties):** each carries `name`, `source`, `on`, `rely.at_most_one_match: true`. No join declares `cardinality:`, and no join declares a join type (the MV schema has no `type:` field).

| # | `name` | `source` | `on` | `rely` | Lines |
|---|---|---|---|---|---|
| J1 | `date_dim` | `tpcds.public.date_dim` | `source.ss_sold_date_sk = date_dim.d_date_sk` | `at_most_one_match: true` | :23-27 |
| J2 | `item` | `tpcds.public.item` | `source.ss_item_sk = item.i_item_sk` | `at_most_one_match: true` | :28-32 |
| J3 | `customer` | `tpcds.public.customer` | `source.ss_customer_sk = customer.c_customer_sk` | `at_most_one_match: true` | :33-37 |

**Dimensions (6 constructs, 15 properties):**

| # | `name` | `expr` | `display_name` | `synonyms` | Lines |
|---|---|---|---|---|---|
| D1 | `ticket_number` | `ss_ticket_number` | — | — | :39-40 |
| D2 | `sold_year` | `date_dim.d_year` | `Year` | `[year, yr]` | :41-46 |
| D3 | `sold_date` | `date_dim.d_date` | — | — | :47-48 |
| D4 | `item_category` | `item.i_category` | — | `[category, product type]` | :49-53 |
| D5 | `item_brand` | `item.i_brand` | — | — | :54-55 |
| D6 | `birth_country` | `customer.c_birth_country` | — | — | :56-57 |

**Measures (2 constructs, 7 properties):**

| # | `name` | `expr` | `comment` | `format` | Lines |
|---|---|---|---|---|---|
| M1 | `total_sales` | `SUM(ss_ext_sales_price)` | `Total sales revenue` | `{type: currency, currency_code: USD}` | :59-64 |
| M2 | `total_quantity` | `SUM(ss_quantity)` | `Total units sold` | — | :65-67 |

**Denominators:** 15 constructs (4 top-level properties + 3 joins + 6 dimensions + 2 measures) / **38 source properties**.

**Not present in this fixture** (so *not* exercised by this task, and the results below must not be generalised to them): windows / semi-additive measures, LOD (`AGG() OVER (PARTITION BY ...)`), cross-measure `MEASURE()` / `ANY_VALUE()` refs, conditional aggregates, subquery or MV-on-MV `source:`, `parameters:`, `materialization:`, `using:` joins, nested joins, role-play aliases, and **any string function** — so the BL-171 emitter defect (`trim`/`ltrim`/`rtrim`/`replace`/`starts_with`/`ends_with` emitted as bare non-native names by `mv_sql.py`'s `_RENAME`) is **not triggered** by this fixture. See §2.7.

### 1.3 Cross-list against the OSI hub form (referee)

`converters/databricks/tests/fixtures/tpcds_ossie.yaml` shows what upstream's own MV → OSI conversion keeps, re-expresses, or stashes. **Upstream drops nothing semantically.**

| MV construct | OSI representation | Referee reading |
|---|---|---|
| `comment` (:20) | `semantic_model[0].description` (:21) | Mapped 1:1 |
| `source` (:19) | `datasets[].source` per table (:24, :30, :42, :53) | Mapped, normalised into per-dataset sources |
| `filter` (:21) | Model-level `custom_extensions` vendor JSON: `'{"_v": 1, "filter": "ss_net_profit > 0"}'` (:87-89) | **Stashed, not mapped** — OSI has no first-class global-filter concept |
| `rely.at_most_one_match: true` (:26-27, :31-32, :36-37) | `primary_key:` on the joined dataset (:31 `[d_date_sk]`, :43 `[i_item_sk]`, :54 `[c_customer_sk]`); `relationships[]` (:59-74) carry **no** cardinality field | **Re-expressed** — a PK on the "one" side implies at-most-one-match |
| join type (absent from MV) | `relationships[]` (:60-74) carry **no** join-type field | **Silent** — the referee neither confirms nor contradicts a join type |
| dimension `name` + `display_name` (:41-43) | `name: sold_year` (:33) **and** `label: Year` (:36) — both preserved | **Both kept.** The identifier/label distinction *is* preservable in a hub form |
| dimension `synonyms` (:44-46, :51-53) | `ai_context: {synonyms: [...]}` (:37, :48) | Mapped |
| measure `comment` (:61, :67) | `metrics[].description` (:79, :86) | Mapped |
| measure `format` (:62-64) | Metric-level `custom_extensions` vendor JSON: `'{"_v": 1, "format": {"type": "currency", "currency_code": "USD"}}'` (:80-82) | **Stashed, not mapped** — OSI has no first-class currency-format concept |
| `expr` alias prefixes (`date_dim.d_year`, :42) | Stripped to the bare physical column (`d_year`, :35) under the owning dataset | Equivalent — the dataset provides the qualification |

**Consequence for our verdicts.** Where the referee *preserves* a construct (dimension identifier vs label), a loss on our side is ours. Where the referee is *silent* (join type), we fall back to the vendor spec. Where the referee only *stashes* (filter, format), losing it is still ours if our own mapping docs claim it maps.

### 1.4 Pipeline actually executed, and every checkpoint skipped

**Forward (MV → ThoughtSpot Model TML)** — `agents/cli/ts-convert-from-databricks-mv/SKILL.md`, offline:

```bash
ts databricks parse-mv ./00-source-mv.yaml --output ./01-parsed.json
#   → "Parsed MV v1.1: 6 dimension(s), 2 measure(s), 3 top-level join(s)"  exit 0
ts databricks translate-formulas --input ./01-parsed.json --tables ./02-tables.json \
  --output ./03-translated.json
#   → "Translated 9/9 (0 skipped)"  exit 0
ts databricks build-model --parsed ./01-parsed.json --translated ./03-translated.json \
  --tables ./04-tables-v2.json --connection "DBX_TPCDS" \
  --model-name "Tpcds Store Sales" --mv-fqn "tpcds.public.tpcds_store_sales" \
  --output-dir ./tml_out --spotter-enabled
#   → exit 0; "invariant_findings": [], "lint_findings": [], "skipped": []
```

**Reverse (Model TML → MV)** — `agents/cli/ts-convert-to-databricks-mv/SKILL.md`, offline. Step 3's `ts tml export --parse` is unavailable without an instance, so the two JSON inputs `build-mv` documents (Step 5.1) were produced by loading the TML files we just generated — a format conversion of our own output, not a substitute for any conversion logic:

```bash
ts databricks build-mv --model ./05-model-export.json --tables ./06-tables-export.json \
  --catalog tpcds --schema public --output-dir ./mv_out
#   → exit 0; 1 metric view, 6 dimensions, 2 measures, filter_applied: true
#   → stderr WARNING: formula 'MV Filter' classified as a row filter (boolean) —
#      confirm this is intended as a global MV filter rather than a dimension
```

**Interactive checkpoints skipped, and what each would have asked:**

| Skill | Step | Would have asked | Substituted |
|---|---|---|---|
| from-mv | 0 | `Ready to start? [Y / N]` | assumed Y |
| from-mv | 3 | select a Metric View from the catalog list | fixture file given |
| from-mv | 5 | MV-on-MV live check — `parsed.json` set `needs_live_check: true` on `source` **and all 3 join sources**; the skill requires a `system.information_schema.tables` probe to prove each is not itself a metric view, and to **fail loud** if it is | **not run** — no workspace. Treated as physical tables (they are, in TPC-DS) |
| from-mv | 6.3 | review `skipped[]` / `annotations[]` | nothing to review — 0 skips, 0 annotations |
| from-mv | 7 | `Is this table already registered in ThoughtSpot? Y / N / ?` × 4 tables | answered **N** (create new) — no instance to search |
| from-mv | 8A | connection-scoped vs instance-wide search (`C / I`) | n/a on the N path |
| from-mv | 8B | connection picker (`N / F / L`) | placeholder connection name `DBX_TPCDS` |
| from-mv | 9 | confirm/override the model name | `Tpcds Store Sales` (matches the referee's `semantic_model[0].name: tpcds_store_sales`, :20) |
| from-mv | 9.5 | `Enable Spotter (AI search)? [Y / n]` | Y |
| from-mv | 10 | review TML then import / FILE | **FILE** |
| from-mv | 11 | — | import skipped (no instance) |
| to-mv | 1 / 1.5 | ThoughtSpot + Databricks profile selection | skipped |
| to-mv | 1.5 | warehouse selection **and the Runtime-floor confirmation** (`Y / N / ?`) — materially relevant here, see finding F5: the emitted DDL requires Runtime **18.1+**, not 17.3+ | skipped |
| to-mv | 2 | find/select the model (`G / S / B`) | TML already on disk |
| to-mv | 5.2 | confirm `--catalog` / `--schema` (also sets the `source:` FQN) | `tpcds` / `public` |
| to-mv | 10 | `YES / NO / EDIT / FILE` on the generated DDL | **FILE** |
| to-mv | 12 | — | DDL execution skipped (no workspace) |

**Table-column input caveat.** The file-only path (from-mv Steps 8A/8B) specifies `tables.json` entries with `create: true` carrying `db`/`schema`/`db_table` plus a `columns` list of `{name, dbx_type}` "from the `DESCRIBE TABLE` output". With no workspace, the column list was built from the **TPC-DS standard schema**, restricted to the 15 columns the MV actually references (7 in `store_sales` including the filter column `ss_net_profit`, 3 in `date_dim`, 3 in `item`, 2 in `customer`). This affects only Table TML `data_type` values, not any measure/dimension/join definition measured below — with one consequence worth its own finding (F7).

### 1.5 Validation results (verbatim)

`ts tml lint --dir ./tml_out` — exit 0:

```json
{"clean": true, "results": [{"index": 0, "type": "table", "name": "CUSTOMER", "findings": []}, {"index": 1, "type": "table", "name": "DATE_DIM", "findings": []}, {"index": 2, "type": "table", "name": "ITEM", "findings": []}, {"index": 3, "type": "table", "name": "STORE_SALES", "findings": []}, {"index": 4, "type": "model", "name": "Tpcds Store Sales", "findings": []}]}
```

`python3 tools/validate/check_tml.py --file <each>` — all exit 0:

```
PASS  Tpcds Store Sales.model.tml (model TML)
PASS  CUSTOMER.table.tml (table TML)
PASS  DATE_DIM.table.tml (table TML)
PASS  ITEM.table.tml (table TML)
PASS  STORE_SALES.table.tml (table TML)
```

**Both gates are clean, and both are blind to every finding in §2.** They check structural TML invariants, not semantic fidelity to a source. That is itself the headline observation about our current gate coverage.

### 1.6 Workspace artifacts

All under `.superpowers/sdd/2026-07-29-ossie-tpcds-fidelity/dbx/` (gitignored via `.superpowers/sdd/.gitignore`):

| File | Contents |
|---|---|
| `00-source-mv.yaml` | verbatim copy of the upstream fixture |
| `01-parsed.json` | `ts databricks parse-mv` output |
| `02-tables.json`, `04-tables-v2.json` | alias → ThoughtSpot table maps (v1 for translate, v2 with `create: true` for build) |
| `03-translated.json` | `ts databricks translate-formulas` output |
| `tml_out/` | `Tpcds Store Sales.model.tml` + 4 `*.table.tml` |
| `05-model-export.json`, `06-tables-export.json` | `build-mv` JSON inputs |
| `mv_out/tpcds_store_sales_store_sales_mv.sql` | regenerated Metric View DDL |
| `canon.py` | canonicaliser + differ (parsed YAML → sorted-key JSON) |
| `10-canon-original-mv.json` … `13-canon-our-model-tml.json` | canonical forms of all four documents |
| `14-diff-original-vs-regenerated.txt` | unified canonical diff (the evidence for §2.2) |
| `15-inventory-summary.json` | construct counts + name lists, both sides |

**Canonicalisation note.** The fixture writes `on:` unquoted (`tpcds_metric_view.yaml:25`, `:30`, `:35`), which YAML 1.1 parses as the boolean key `True`; `canon.py` normalises mapping keys to strings so `on` compares to `on`. Both `ts databricks parse-mv` and `ts databricks build-mv` already handle this correctly — `build-mv` re-emits the key quoted (`'on':`, `.sql:9`, `:15`, `:21`), which is the safer form.

---

## 2. Databricks round-trip

### 2.1 Fidelity table

**Verdict** = the worst deviation anywhere across the round trip (original MV → our Model TML → regenerated MV); the **Evidence** column names which leg it occurred on. **Extras** (things we add that the source lacks) are listed separately in the last column so an otherwise-clean construct is not silently downgraded — and so nothing is hidden.

**Top-level properties**

| # | Construct | Verdict | Evidence | Extras |
|---|---|---|---|---|
| T1 | `version` | `matched` | `'1.1'` in (`:18`) → `'1.1'` out (`.sql:3`) | — |
| T2 | `source` | `matched` | `tpcds.public.store_sales` (`:19`) → same (`.sql:5`); decomposed to `db: tpcds` / `schema: public` / `db_table: store_sales` in `STORE_SALES.table.tml` | — |
| T3 | `comment` | **`mis-inferred`** | forward leg — see §2.3 F4 | — |
| T4 | `filter` | `matched` | `ss_net_profit > 0` (`:21`) → `MV Filter` ATTRIBUTE formula `[STORE_SALES::ss_net_profit] > 0` (`model.tml:58-63`) + model-level `filters:` block with `oper: in` / `values: ['true']` (`model.tml:52-57`) → `filter: source.ss_net_profit > 0` (`.sql:59`). Alias-qualification only; `source.COL` is a documented valid dot-path (`agents/shared/schemas/databricks-metric-view.md:419`). `build-mv` correctly routed the boolean formula to `filter:` rather than emitting it as a 7th dimension, and warned while doing so | — |

**Joins**

| # | Construct | Verdict | Evidence | Extras |
|---|---|---|---|---|
| J1 | `date_dim` | **`mis-inferred`** | `name`/`source`/`on`/`rely` all round-trip verbatim (`:23-27` → `.sql:7-12`), but our Model TML asserts `type: INNER` (`model.tml:70`) for a join the vendor defines as LEFT OUTER — see §2.3 F1 | `cardinality: many_to_one` (`.sql:12`) — §2.3 F5 |
| J2 | `item` | **`mis-inferred`** | same; `type: INNER` at `model.tml:75`; `:28-32` → `.sql:13-18` | `cardinality: many_to_one` (`.sql:18`) |
| J3 | `customer` | **`mis-inferred`** | same; `type: INNER` at `model.tml:80`; `:33-37` → `.sql:19-24` | `cardinality: many_to_one` (`.sql:24`) |

**Dimensions**

| # | Construct | Verdict | Evidence | Extras |
|---|---|---|---|---|
| D1 | `ticket_number` | `matched` | `name` + `expr` survive (`:39-40` → `.sql:26-27`, alias-qualified) | `display_name: Ticket Number` (`.sql:28`) |
| D2 | `sold_year` | **`mis-inferred`** | identifier restated as `year` — see §2.3 F2. `expr`, `display_name`, `synonyms` all matched (`:42-46` → `.sql:30-34`) | — |
| D3 | `sold_date` | `matched` | `:47-48` → `.sql:35-36` | `display_name: Sold Date` (`.sql:37`) |
| D4 | `item_category` | `matched` | `name`, `expr`, both synonyms survive (`:49-53` → `.sql:38-43`) | `display_name: Item Category` (`.sql:40`) |
| D5 | `item_brand` | `matched` | `:54-55` → `.sql:44-45` | `display_name: Item Brand` (`.sql:46`) |
| D6 | `birth_country` | `matched` | `:56-57` → `.sql:47-48` | `display_name: Birth Country` (`.sql:49`) |

**Measures**

| # | Construct | Verdict | Evidence | Extras |
|---|---|---|---|---|
| M1 | `total_sales` | **`missed`** | `name`, `expr` (`SUM(...)` → `aggregation: SUM` on `STORE_SALES::ss_ext_sales_price` → `SUM(source.ss_ext_sales_price)`), and `comment` → `properties.description` → `comment` all matched (`:59-61` → `model.tml:35-40` → `.sql:51-54`). `format:` (`:62-64`) is absent from both our Model TML and the regenerated MV — see §2.3 F3 | `display_name: Total Sales` (`.sql:53`) |
| M2 | `total_quantity` | `matched` | `:65-67` → `model.tml:41-46` → `.sql:55-58` | `display_name: Total Quantity` (`.sql:57`) |

### 2.2 Summary counts

**Construct level** (15 constructs):

| Group | n | `matched` | `mis-inferred` | `missed` | `extra` | `not-applicable` | additive extras |
|---|---|---|---|---|---|---|---|
| **Measures** | 2 | **1** | **0** | **1** | **0** | **0** | 2 |
| **Dimensions** | 6 | **5** | **1** | **0** | **0** | **0** | 5 |
| **Joins** | 3 | **0** | **3** | **0** | **0** | **0** | 3 |
| Top-level properties | 4 | 3 | 1 | 0 | 0 | 0 | 0 |
| **Total** | **15** | **9** | **5** | **1** | **0** | **0** | **10** |

**Property level** (38 source properties): **35 matched · 2 mis-inferred · 1 missed · 0 extra · 0 not-applicable**, plus **10 properties we add** that the source lacks (3 × join `cardinality`, 7 × `display_name`).

The two figures diverge because the round trip's biggest defect — the `type: INNER` assertion (F1) — has **no source property to compare against**: the Metric View schema has no join-type field, so the MV → MV diff is silent on it and it is visible only at construct level, by reading our intermediate TML against the vendor spec. A property-level diff alone would have scored this round trip **35/38 = 92%** and missed the one finding that changes numbers. That asymmetry is the methodological point of the exercise.

**Canonical diff** (`14-diff-original-vs-regenerated.txt`) confirms these and only these MV-level deltas: 1 changed `comment`, 1 changed dimension `name`, 1 removed measure `format` block, 3 added join `cardinality` keys, 7 added `display_name` keys, and alias-qualification of 4 `expr`/`filter` strings. Construct counts and all three join names, both measure names, and 5 of 6 dimension names are identical on both sides (`15-inventory-summary.json`).

### 2.3 Non-matched constructs, both definitions verbatim

#### F1 — Join type: MV joins are LEFT OUTER, we assert INNER *(joins J1-J3, `mis-inferred`, wrong side: **ours**)*

**Source (`tpcds_metric_view.yaml:23-27`, representative):**

```yaml
- name: date_dim
  source: tpcds.public.date_dim
  on: source.ss_sold_date_sk = date_dim.d_date_sk
  rely:
    at_most_one_match: true
```

**Ours (`tml_out/Tpcds Store Sales.model.tml:66-71`):**

```yaml
  joins:
    - cardinality: MANY_TO_ONE
      name: fact_to_date_dim
      'on': "[STORE_SALES::ss_sold_date_sk] = [DATE_DIM::d_date_sk]"
      type: INNER
      with: DATE_DIM
```

The Metric View schema has no join-type field because the type is fixed by the platform. Databricks documents it explicitly:

> "In a star schema, the `source` is the fact table and joins with one or more dimension tables using a `LEFT OUTER JOIN`."
> — [Joins in metric views, Databricks docs](https://docs.databricks.com/aws/en/business-semantics/metric-views/joins)

Our forward converter hardcodes the opposite: `tools/ts-cli/ts_cli/databricks/mv_build_model.py:236` emits `"type": "INNER"` unconditionally for every join it builds, with no source-derived alternative. `LEFT_OUTER` is a valid ThoughtSpot Model TML join type (`agents/shared/schemas/thoughtspot-model-tml.md:123`), so nothing about the target format forces this.

**Impact — this changes numbers, silently.** Every fact row whose FK is NULL or matches no dimension row is retained by the Databricks MV and dropped by the ThoughtSpot Model, so `total_sales` and `total_quantity` read **lower** in ThoughtSpot than in Databricks on the same data. The TPC-DS standard schema declares `store_sales`'s surrogate-key columns nullable (they carry no NOT NULL constraint — only the primary key `(ss_item_sk, ss_ticket_number)` is mandatory), so the divergence is reachable on this fixture's own schema; the exact magnitude depends on how the data was generated and was **not measured here** (see §2.7). Nothing in the pipeline warns: the round-trip diff cannot see it (the MV has no `type:` to compare), `ts tml lint` cannot see it, and `check_tml.py` cannot see it.

**Referee:** silent — OSI `relationships[]` (`tpcds_ossie.yaml:60-74`) carry no join-type field either, so upstream's hub form does not contradict us. The vendor spec does. Our converter is wrong regardless of the referee's silence.

**Also undocumented:** the from-databricks coverage matrix has rows for `joins:` (#10), `joins[].on` (#11), `joins[].using` (#12) and `joins[].cardinality`/`rely` (#13) but **no row for the join type at all** — `agents/cli/ts-convert-from-databricks-mv/references/coverage-matrix.md:33-36`. Neither does the to-direction Concept Mapping.

#### F2 — Dimension identifier collapses into the display name *(D2 `sold_year` → `year`, `mis-inferred`, wrong side: **ours**, with a real ThoughtSpot constraint behind it)*

**Source (`tpcds_metric_view.yaml:41-46`):**

```yaml
- name: sold_year
  expr: date_dim.d_year
  display_name: Year
  synonyms:
  - year
  - yr
```

**Regenerated (`mv_out/tpcds_store_sales_store_sales_mv.sql:29-34`):**

```yaml
- name: year
  expr: date_dim.d_year
  display_name: Year
  synonyms:
  - year
  - yr
```

**Mechanism.** The forward leg computes the ThoughtSpot column name as `entry.get("display_name") or entry["name"].replace("_", " ").title()` (`tools/ts-cli/ts_cli/databricks/mv_build_model.py:19`) — so when `display_name` is present, the MV identifier is discarded outright (`model.tml:8` has `name: Year` and nothing else). The reverse leg regenerates the identifier from the display name via `to_snake(display)` (`tools/ts-cli/ts_cli/databricks/mv_emit_classify.py:240-241`), producing `year`. The 5 dimensions **without** a `display_name` round-trip cleanly precisely because the title-case ↔ snake-case pair is invertible; the moment a `display_name` exists, the identifier is unrecoverable.

**Impact.** `name:` is the queryable identifier of a Metric View dimension. Any Databricks consumer, saved query, or dashboard referencing `sold_year` breaks against the regenerated view. The side effect is visible in the output too: the regenerated dimension `year` now carries `year` as one of its own synonyms.

**Referee:** the OSI hub form keeps **both** — `name: sold_year` (`tpcds_ossie.yaml:33`) and `label: Year` (`tpcds_ossie.yaml:36`) — proving the distinction is preservable in an intermediate form (this is the same bridging upstream's own test docstring describes, `test_ossie_to_metric_view.py:33-37`). ThoughtSpot Model TML has only one identity field per column (`name`), so we cannot store both there without a convention (e.g. stashing the source identifier in `description` or AI context). The loss is ours; the constraint is real; the honest routing is a documented limitation plus, optionally, a stash convention.

**Also undocumented:** coverage-matrix row #6 covers `display_name` → column `name` (`coverage-matrix.md:24`) but there is **no row for the MV `name:` field** in either the Mapped or Unmapped sections — the collapse is undocumented behaviour, not a documented limitation.

#### F3 — Measure `format:` (currency) dropped on the forward leg only *(M1, `missed`, wrong side: **ours**, contradicts our own docs)*

**Source (`tpcds_metric_view.yaml:59-64`):**

```yaml
- name: total_sales
  expr: SUM(ss_ext_sales_price)
  comment: Total sales revenue
  format:
    type: currency
    currency_code: USD
```

**Ours (`tml_out/Tpcds Store Sales.model.tml:35-40`) — no `currency_type`:**

```yaml
  - column_id: "STORE_SALES::ss_ext_sales_price"
    name: Total Sales
    properties:
      aggregation: SUM
      column_type: MEASURE
      description: Total sales revenue
```

**Regenerated (`mv_out/tpcds_store_sales_store_sales_mv.sql:51-54`) — no `format:`:**

```yaml
- name: total_sales
  expr: SUM(source.ss_ext_sales_price)
  display_name: Total Sales
  comment: Total sales revenue
```

**This contradicts our own documented mapping.** `agents/shared/mappings/ts-databricks/ts-databricks-properties.md:109` lists the pair as mapped — `properties.currency_type` ↔ `format: { type: currency }` — and `:122` states "`currency_type` maps for measures". The **reverse** leg honours it: `mv_emit_classify.py:228-231` reads `properties.currency_type.iso_code` and emits `format: {type: currency, currency_code: <iso>}`. The **forward** leg does not: `mv_translate.py:98` faithfully carries `"format": meta.get("format")` into `translated.json` (confirmed present in `03-translated.json:118-121`), and then nothing in `mv_build_model.py` or `mv_tml.py` reads it — `grep -rn currency_type tools/ts-cli/ts_cli/` returns only the two reverse-direction lines. The target field exists and is documented (`agents/shared/schemas/thoughtspot-model-tml.md:175`, `properties.currency_type.iso_code`).

So this is a one-sided gap in an otherwise-implemented bidirectional mapping: the data survives parse and translate and is discarded at assembly. Small and obvious to fix.

**Referee:** upstream also does not map `format:` to a first-class OSI concept — it stashes it verbatim in `custom_extensions` (`tpcds_ossie.yaml:80-82`) and round-trips it from there. Our situation is different: we have a real target field, documented as mapped, that we do not write.

**Also undocumented:** the from-databricks coverage matrix has **no row for `format:`** in either its Mapped or Unmapped sections, so today the drop is neither implemented nor declared as a limitation.

#### F4 — Top-level `comment` polluted with provenance text, and accretive *(T3, `mis-inferred`, wrong side: **ours**)*

**Source (`tpcds_metric_view.yaml:20`):**

```yaml
comment: Store sales enriched with date, item, and customer dimensions
```

**Regenerated (`mv_out/tpcds_store_sales_store_sales_mv.sql:4`):**

```yaml
comment: Store sales enriched with date, item, and customer dimensions Converted from Databricks Metric View tpcds.public.tpcds_store_sales. MV Filter applied automatically via model filter.
```

The forward leg appends two provenance sentences to `model.description` (`tml_out/Tpcds Store Sales.model.tml:51`) and the reverse leg copies the whole string back into `comment:`. Two distinct defects:

1. **Missing separator.** The MV comment and the appended sentence are concatenated with a single space and no terminating punctuation on the first — `"...customer dimensions Converted from Databricks..."` is a run-on. This is user-visible in the ThoughtSpot model description regardless of any round trip.
2. **Accretion.** Because the reverse leg round-trips the polluted string, a second MV → TS → MV cycle appends the provenance again. The description grows without bound across repeated conversions.

The provenance itself is legitimate and useful; it just should not be written into the field that round-trips as the source's own comment.

#### F5 — Redundant `cardinality: many_to_one` raises the emitted DDL's Runtime floor *(joins J1-J3, `extra`, wrong side: **ours**)*

**Source (`tpcds_metric_view.yaml:26-27`)** — the `rely:` form only:

```yaml
  rely:
    at_most_one_match: true
```

**Regenerated (`mv_out/tpcds_store_sales_store_sales_mv.sql:10-12`)** — both forms:

```yaml
  rely:
    at_most_one_match: true
  cardinality: many_to_one
```

The two are equivalent and agree, so the emitted DDL is semantically correct — but the extra key is not free:

- `rely: { at_most_one_match: true }` works on **all** runtimes; `cardinality:` is **18.1+ only** (`agents/shared/schemas/databricks-metric-view.md:20`, `:430-431`).
- `many_to_one` is also the schema's **default** when neither is present (`agents/shared/schemas/databricks-metric-view.md:436-437`), so the key adds nothing even semantically.
- The to-direction skill's own prerequisites table states 18.1+ is "Required only if the model has an explicit `MANY_TO_ONE` join (emits `cardinality:`)" (`agents/cli/ts-convert-to-databricks-mv/SKILL.md:197`). The model *does* now have explicit `MANY_TO_ONE` joins — because the forward leg stamped them from a `rely:` hint that needed no such promotion. The round trip has silently moved this MV's Runtime requirement from 17.3+ to 18.1+.

Emission chain: `mv_build_model.py:237` writes `"cardinality": _CARDINALITY[node.get("cardinality") or "many_to_one"]` into the Model TML for every join, and the reverse leg emits both keys.

**Documentation mismatch (separate from the behaviour).** Coverage-matrix row #13 states `joins[].cardinality` / `joins[].rely` are "Parsed, precedence applied — **Informational — not written to TML**" (`agents/cli/ts-convert-from-databricks-mv/references/coverage-matrix.md:36`). They *are* written to TML: `cardinality: MANY_TO_ONE` appears on all three joins (`model.tml:67`, `:72`, `:77`). The row is stale.

#### F6 — `display_name` synthesized on all 7 constructs that lacked one *(`extra`, wrong side: **ambiguous / benign**)*

Five dimensions (D1, D3, D4, D5, D6) and both measures had no `display_name` in the source; all seven acquire one in the regenerated MV (`.sql:28`, `:37`, `:40`, `:46`, `:49`, `:53`, `:57`), e.g. `ticket_number` gains `display_name: Ticket Number`. This is structural, not a defect: ThoughtSpot has one name field, so the reverse leg must synthesize the identifier/label pair (`mv_emit_classify.py:240-241` sets `name: to_snake(display)`, `display_name: display`). The values are the correct title-cased forms and the identifiers are unchanged. Recorded for completeness; no action expected.

#### F7 — File-only Table TML classifies join keys and a declared dimension as summable measures *(quality, wrong side: **ours + a doc gap**; not a round-trip loss)*

`build_table_tml` defaults every numeric column to `MEASURE` with `aggregation: SUM` (`tools/ts-cli/ts_cli/databricks/mv_tml.py:69-73`). The generated Table TMLs therefore mark all four surrogate keys and `ss_ticket_number` as summable measures — including `ss_ticket_number`, which the MV **explicitly declares a dimension** (`tpcds_metric_view.yaml:39-40`):

```yaml
  - db_column_name: ss_ticket_number
    db_column_properties:
      data_type: INT64
    name: ss_ticket_number
    properties:
      aggregation: SUM
      column_type: MEASURE
```

The Model TML overrides it correctly (`column_type: ATTRIBUTE`, `model.tml:3-6`), so the round trip survives and the regenerated MV has `ticket_number` back as a dimension — this is not a fidelity loss. It is a quality defect in what a user actually receives: the underlying ThoughtSpot Tables offer "Sum of Ss Sold Date Sk" and a summable ticket number.

Notably, `build_table_tml` **does** accept per-column `column_type` and `aggregation` overrides (`mv_tml.py:69-73`) — but the SKILL's file-only instructions specify only `{"name", "dbx_type"}` (`agents/cli/ts-convert-from-databricks-mv/SKILL.md:552-556` and the identical block at `:607-611`), so no documented run ever passes them. The information needed to do better is available for free: the MV's own dimension list and every join's `on` clause identify exactly which numeric columns are keys or dimensions.

#### F8 — Default regenerated view name doubles the fact-table token *(cosmetic, wrong side: **ours**)*

`build-mv` named the regenerated view `tpcds_store_sales_store_sales_mv` (`.sql:1`) — `default_view_name(model_name, fact)` concatenates the model name (`Tpcds Store Sales`) with the fact table (`store_sales`), which duplicates the token whenever the model is named after its fact. Not a fidelity comparison (the fixture carries no view name — the MV name lives in the DDL, not the YAML) but a visible round-trip artifact. `--view-name` overrides it, and no skill step prompts for it.

### 2.4 Which side is wrong — summary

| Finding | Verdict | Wrong side | Judged against |
|---|---|---|---|
| F1 join type INNER vs LEFT OUTER | `mis-inferred` | **ours** | Databricks vendor docs (referee silent — OSI has no join-type field) |
| F2 `sold_year` → `year` | `mis-inferred` | **ours**, ThoughtSpot single-name-field constraint behind it | OSI referee preserves `name` + `label` (`tpcds_ossie.yaml:33`, `:36`) |
| F3 `format:` dropped | `missed` | **ours** — contradicts `ts-databricks-properties.md:109`/`:122`; reverse leg already implemented | our own mapping docs; referee only stashes |
| F4 `comment` polluted + accretive | `mis-inferred` | **ours** | source fixture `:20` |
| F5 redundant `cardinality:` | `extra` | **ours** | `databricks-metric-view.md:20`, `:430-437`; to-mv `SKILL.md:197` |
| F6 synthesized `display_name` | `extra` | **ambiguous / benign** | structural to ThoughtSpot's single name field |
| F7 keys as MEASURE/SUM in Table TML | quality (not a fidelity loss) | **ours + doc gap** | MV's own dimension declaration `:39-40`; `mv_tml.py:69-73` |
| F8 doubled default view name | cosmetic | **ours** | — |

### 2.5 Documentation gaps found alongside the behaviour

| Gap | Location | Nature |
|---|---|---|
| No coverage-matrix row for MV join **type** | `agents/cli/ts-convert-from-databricks-mv/references/coverage-matrix.md:33-36` (Joins section) | Missing row — the behaviour (F1) is both wrong and undeclared |
| No coverage-matrix row for the MV dimension/measure **`name:`** field | same file, Version and Metadata section (`:20-27`) — row #6 (`:24`) covers `display_name` only | Missing row — the collapse (F2) is undeclared |
| No coverage-matrix row for **`format:`** | same file, Mapped and Unmapped sections | Missing row — the drop (F3) is undeclared, while `ts-databricks-properties.md:109`/`:122` claims it maps |
| Row #13 says cardinality/rely is "Informational — not written to TML" | `coverage-matrix.md:36` | **Stale** — `cardinality: MANY_TO_ONE` *is* written (`model.tml:67`, `:72`, `:77`) |
| File-only `tables.json` spec omits the supported `column_type` / `aggregation` per-column keys | `agents/cli/ts-convert-from-databricks-mv/SKILL.md:552-556`, `:607-611` | Incomplete — causes F7 in every documented file-only run |

### 2.6 What the existing gates did and did not catch

| Gate | Result | Findings caught |
|---|---|---|
| `ts databricks parse-mv` | exit 0, `unsupported: []`, `warnings: []` | — (correctly: it parsed everything, including `format` and `rely`) |
| `ts databricks translate-formulas` | exit 0, 9/9, `skipped: []` | — (correctly: `format` survives into `translated.json`) |
| `ts databricks build-model` | exit 0, `invariant_findings: []`, `lint_findings: []`, `skipped: []` | **none of F1-F5** — this is where F1, F3, F4 and F5 are introduced |
| `ts tml lint --dir` | `"clean": true` | none |
| `tools/validate/check_tml.py` | PASS × 5 | none |
| `ts databricks build-mv` | exit 0, 1 warning (`MV Filter` boolean → `filter:`, correct and useful) | none of F1-F5 |

Every gate is green and every finding above survives. The gates verify structural TML validity, not semantic fidelity to a source definition — which is exactly the gap a fidelity harness like this one fills.

### 2.7 Scope limits on these results

- **BL-171 was not exercised.** The fixture contains no string functions, so `mv_sql.py`'s `_RENAME` never emitted `trim`/`ltrim`/`rtrim`/`replace`/`starts_with`, and `ENDSWITH`'s missing mapping was never hit. The only formula generated was the filter comparison `[STORE_SALES::ss_net_profit] > 0`. The known defect (`tools/ts-cli/ts_cli/databricks/mv_sql.py:251-252`, documented as coverage-matrix rows #75/#76 at `agents/cli/ts-convert-from-databricks-mv/references/coverage-matrix.md:100-101`) remains open and untested here.
- **No numeric verification.** F1's impact (dropped fact rows) is reasoned from the vendor's documented join semantics plus the TPC-DS schema's nullable surrogate keys — it is not measured, and no NULL-rate figure is claimed. Confirming the magnitude needs a live workspace and instance holding the same data on both sides — the parked conversion-fidelity angle (audit angle 15).
- **The 92% property-level match is not a general fidelity figure.** It is the figure for a plain 3-join star with 6 direct dimensions and 2 simple aggregates. The constructs most likely to be mis-inferred — windows, LOD, cross-measure refs, conditional aggregates, subquery sources — are all absent (see §1.2).

---

## 3. Snowflake semantic comparison

Section 3 derives its ThoughtSpot TML **independently** of §2 — nothing is reused from the
Databricks leg. The two sections share only the verdict vocabulary, the table format, and
the counting convention restated in §3.5.

### 3.1 What upstream's Snowflake converter produced, and from which OSI input

| Fixture | Path | git blob SHA |
|---|---|---|
| Cortex Analyst semantic-model YAML (upstream's output) | `converters/snowflake/tests/example_converted_tpcds_semantic_model.yaml` | `7817666842cfa79b2f8a750d46ae76bfb00d4ab6` |
| OSI source (semantic referee) | `examples/tpcds_semantic_model.yaml` | `a04b16835b5a5e3ec7a1e7af70d634c92408bb6b` |

**Which OSI input it came from — settled by reproduction, not inference.** The learnings
report established that the fixture is referenced by no test
(`docs/reviews/2026-07-29-ossie-converter-learnings.md` §3.5); re-confirmed here — a
repo-wide `grep -rn "example_converted_tpcds" .` at `c26b61c` returns **zero** matches, so
nothing generates or validates it and it is a checked-in illustrative sample, not a golden
file. That leaves the correspondence to be established directly, so it was: running the
shipped converter over the candidate OSI input reproduces the fixture **byte-for-byte**.

```
$ uv run ossie-snowflake -i ../../examples/tpcds_semantic_model.yaml -o 00-upstream-regenerated.yaml
$ diff <(grep -v '^#' 01-fixture-checked-in.yaml | sed '/^$/d') \
       <(grep -v '^#' 00-upstream-regenerated.yaml | sed '/^$/d')
IDENTICAL (modulo license header)
```

The only raw-diff delta is the 17-line Apache licence header, which the fixture carries and
the converter does not emit (370 lines vs 353). So the input is **`examples/tpcds_semantic_model.yaml`**,
and the fixture is current against `c26b61c`. The other candidate,
`converters/databricks/tests/fixtures/tpcds_ossie.yaml` (89 lines, 4 datasets, derived from
the Metric View used in §2), is a different and much smaller model — it shares neither the
model name (`tpcds_store_sales` vs `tpcds_retail_model`) nor the dataset set, and is ruled out.

Five warnings fired during that run, all information loss:

```
UserWarning: Dropped from relationship 'store_sales_to_date' (no Snowflake counterpart): ai_context
UserWarning: Dropped from relationship 'store_sales_to_customer' (no Snowflake counterpart): ai_context
UserWarning: Dropped from relationship 'store_sales_to_item' (no Snowflake counterpart): ai_context
UserWarning: Dropped from relationship 'store_sales_to_store' (no Snowflake counterpart): ai_context
UserWarning: Dropped from model (no Snowflake counterpart): ai_context, custom_extensions
```

**Upstream's own fidelity, therefore, is not lossless** — unlike §2's Databricks fixture pair,
whose round trip upstream asserts is byte-faithful (§1.1). Against the OSI referee, upstream drops:
model-level `ai_context.instructions` (a 200-word Spotter-style instruction block,
`examples/tpcds_semantic_model.yaml:29`), all four relationship `ai_context.synonyms` sets
(`:510-513`, `:520-523`, `:530-533`, `:540-543`), both `custom_extensions` vendor payloads
(`:613-631`), and `datatype: Decimal` on all five metrics (`:553`, `:566`, `:579`, `:593`, `:606`).
The first two are acknowledged in `converters/snowflake/README.md:64-69`; the `custom_extensions`
drop is not, and inverts that ecosystem's own guidance
(`converters/README.md:260`: "Ignore (do not discard) — preserve for round-tripping").

**These upstream drops are outside our denominators.** Our measurement starts at the Cortex
YAML, exactly as §2's starts at the Metric View. They are recorded because they bound how
much the referee can adjudicate: where upstream already dropped a construct, the referee
cannot tell us whether *our* handling of it is right.

**Inventory — the fidelity denominators.** Parsed from
`example_converted_tpcds_semantic_model.yaml`:

| Group | Constructs | Properties | Members |
|---|---|---|---|
| Top-level | 2 | 2 | `name` (:18), `description` (:19) |
| Tables | 5 | 30 | `store_sales` (:21), `date_dim` (:98), `customer` (:144), `item` (:194), `store` (:251) — each with `name`, `base_table`, `primary_key`, `unique_keys`, `description`, `synonyms` |
| Dimensions | 22 | 104 | 4 in `store_sales` (:40-68), 1 in `date_dim` (:114-118), 6 in `customer` (:160-193), 6 in `item` (:210-250), 5 in `store` (:267-299) |
| Time dimensions | 4 | 18 | `d_date`, `d_year`, `d_quarter_name`, `d_month_name` (:119-144) |
| Facts | 5 | 25 | 4 in `store_sales` (:69-97), 1 in `store` (`s_number_employees`, :300-307) |
| Relationships | 4 | 16 | :308-332 — all equi, single-column, `left_table`/`right_table`/`relationship_columns` |
| Metrics | 5 | 20 | `total_sales`, `total_profit`, `customer_lifetime_value`, `sales_by_brand`, `store_productivity` (:333-370) — all at document **root** |
| **Total** | **47** | **215** | |

**Cortex-Analyst-specific fields present:** `data_type` on dimensions/time_dimensions/facts
(29 of 31 carry one; the 2 without are `d_quarter_name` and `d_month_name`, and — deliberately —
no metric carries one, per `converters/snowflake/README.md:64-69`). No `verified_queries`,
no `custom_instructions`, no `filters`, no `access_modifier`, no `is_enum`, no `sample_values`,
no `cortex_search_service`, no `tags`, no `using_relationships`.

**Not present in this fixture** (so *not* exercised, and the results below must not be
generalised to them): semi-additive / `non additive by` metrics, window functions and
`PARTITION BY`, LOD, metric-on-metric double aggregation, subquery/SQL-query logical tables,
range and ASOF joins, composite-column relationships, `PRIVATE` visibility, filter labels,
and — as in §2 — **any string function other than `||`**, so the BL-171 string-function
family is again untouched. See §3.10.

### 3.2 Cortex YAML → Semantic View correspondence

The plan anticipated a wide format gap ("upstream emits Cortex Analyst semantic-model YAML,
ours speaks Semantic View DDL — comparison is semantic-level"). **In practice the gap is
much narrower than assumed, and that is a finding in itself:** upstream's output shape is
very nearly our own documented Semantic View **YAML** form. Compare
`agents/shared/schemas/snowflake-schema.md:39-173` (`tables[]` with `name`, `base_table`
triad, `primary_key.columns`, `unique_keys[].columns`, nested `dimensions`/`time_dimensions`/
`facts`/`metrics`, each with `name`/`synonyms`/`description`/`expr`/`data_type`) plus
`:165-173` (top-level `relationships[]` with `left_table`/`right_table`/`relationship_columns[].
{left_column,right_column}`) against the inventory above — the correspondence is essentially
the identity function for every construct class in this fixture. The two artifacts are two
serialisations of the same object, not two different semantic models.

The consequence for method: the only real conversion is **YAML → DDL**, because
`ts snowflake parse-sv` accepts DDL only (`ts snowflake parse-sv --help`: "Path to a Semantic
View DDL file"). That re-serialisation stands in for the skill's Step 3
(`GET_DDL('SEMANTIC_VIEW', ...)`), which needs a live instance.

| Cortex YAML construct | `CREATE SEMANTIC VIEW` clause our skill consumes | Coverage row | Verdict class |
|---|---|---|---|
| `name` (:18) | the view identifier after `create or replace semantic view` | — | direct |
| `description` (:19) | trailing `comment='...'` | #6 | direct |
| `tables[].base_table` triad (:22-25) | `DB.SCHEMA.TABLE` in `tables (...)`; default alias = last segment | #1 | direct |
| `tables[].primary_key.columns` (:26-29) | `primary key (col, ...)` on the table entry | #4 | direct |
| `tables[].unique_keys[].columns` (:30-33) | `unique (col, ...)` on the table entry | **L4** | `not-applicable` |
| `tables[].description` (:34) | `comment='...'` on the table entry | #5 | direct (via separate Table TML) |
| `tables[].synonyms` (:35-39) | `with synonyms=('...',...)` on the table entry | **L2** | `not-applicable` |
| `dimensions[]` (:40-68) | `dimensions ( ALIAS.NAME as <expr> ... )` | #12 | direct |
| `time_dimensions[]` (:119-143) | same `dimensions (...)` block — **the DDL has no `time_dimensions` clause**; the role survives only inside `with extension (CA='…')` (`ts-from-snowflake-rules.md:224-245`) | — | see F14 |
| `facts[]` (:69-97) | `facts ( ALIAS.NAME as <expr> ... )` | #16 | direct |
| `*.description` on any member | `comment='...'` | #15 | direct |
| `*.synonyms` on any member | `with synonyms=(...)` | #14 | see F10 |
| `*.data_type` (:47 etc.) | **no DDL representation** — a Semantic View derives column type from the physical column | — | `not-applicable` |
| `relationships[]` (:308-332) | `relationships ( NAME as FROM(FK) references TO(PK) )` | #7 | direct |
| root `metrics[]` (:333-370) | `metrics ( [ALIAS.]NAME as EXPR ... )` | #18/#20/#26 | see F21 |

Two Cortex-YAML-only constructs have no SV clause and are `not-applicable` with the
coverage-matrix row cited: `unique_keys` (**L4** — "No key declarations in ThoughtSpot models
… Not needed") and table-level `synonyms` (**L2** — "No ThoughtSpot table-level synonym
concept"). A third, `data_type`, is `not-applicable` to the *DDL* path but is not worthless:
it is exactly what a ThoughtSpot Table TML needs, and §3.3 uses it for that.

**One construction choice, recorded because it affects one verdict.** The DDL `metrics()`
grammar prefixes each metric name with an owning table alias, while upstream emits all five
metrics at the document root. `mk_ddl.py` scopes each to the table its aggregate reads from
first. This is an *addition* by the re-serialisation, so §3.4 scores metric table-scoping
against the Cortex source (root-level both sides) and not against the DDL — see F21.

### 3.3 Pipeline executed, checkpoints skipped, validation results

**Forward (SV DDL → ThoughtSpot Model TML)** — `agents/cli/ts-convert-from-snowflake-sv/SKILL.md`
v1.19.0, offline, using the documented deterministic commands (Steps 4, 9, 8, 10-FILE):

```bash
ts snowflake parse-sv 03-sv_ddl.sql --output 04-parsed.json
#   → "Parsed SV 'TPCDS_RETAIL_MODEL': 26 dimension(s), 5 metric(s), 5 fact(s),
#      4 relationship(s)"   exit 0;  warnings: []   unsupported: []
ts snowflake translate-formulas --input 04-parsed.json --output 05-translated.json
#   → "Translated 35/36 formulas (1 skipped)"   exit 0
#   → stderr: "Skipped: - customer_full_name (dimensions): operator '||' —
#      use CONCAT() instead (ts-snowflake-formula-translation.md)"
ts snowflake build-model --parsed 04-parsed.json --translated 05-translated.json \
  --tables 06-tables.json --model-name "Tpcds Retail Model" --output-dir ./tml_out \
  --sv-fqn "TPCDS.PUBLIC.TPCDS_RETAIL_MODEL" --spotter-enabled
#   → exit 0; "formula_count": 5, "lint_findings": [], "name_renames": {},
#      "skipped": [customer_full_name]
```

**Reverse (Model TML → SV DDL)** — `agents/cli/ts-convert-to-snowflake-sv/SKILL.md` v1.5.0,
offline (Steps 8, 9). Step 3's `ts tml export --parse --associated` is unavailable without an
instance, so `build-sv`'s two documented inputs were produced by loading the Model TML we
had just generated and synthesising one Table TML per table from the physical columns the SV
references — a format conversion of our own output plus the `data_type` values the Cortex YAML
already carries (mapped per `ts-from-snowflake-rules.md:758-766`). It substitutes for no
conversion logic.

```bash
ts snowflake build-sv --model 07-model-export.json --tables-dir ./08-tables-export \
  --sv-name TPCDS.PUBLIC.TPCDS_RETAIL_MODEL_RT --output 09-regenerated-sv.sql
#   → dimensions: 28, time_dimensions: 2, metrics: 0, relationship_count: 4,
#     skipped_formulas: 5, dropped_join_attrs: 4
```

**A second, corrected reverse run was also made, and why.** The forward leg emits five metric
formulas whose cross-references do not resolve (F9), which alone causes `build-sv` to drop all
five metrics. Scoring the rest of the reverse leg off that one cascade would have measured the
same bug five more times and taught nothing about the remaining pipeline. So a corrected
variant (`10-model-export-corrected.json`) repairs only the three dangling references to the
`[TABLE::col]` form the documented algorithm prescribes, with Step 8 formula translations
supplied per `ts-snowflake-formula-translation.md`:

```bash
ts snowflake build-sv --model 10-model-export-corrected.json --tables-dir ./08-tables-export \
  --sv-name TPCDS.PUBLIC.TPCDS_RETAIL_MODEL_RT2 --output 12-regenerated-sv-corrected.sql \
  --formulas 11-formulas.json
#   → dimensions: 28, time_dimensions: 2, metrics: 5, skipped_formulas: 0
```

**§3.4's verdicts are scored against the as-is run** (`09-regenerated-sv.sql`) — what a user
actually gets today. The corrected run is cited only where it isolates a *second, independent*
defect that the cascade would otherwise have masked (F12, F20, F21).

**Interactive checkpoints skipped, and what each would have asked:**

| Step | Would have asked | Substituted |
|---|---|---|
| from-sv 1 / 1.5 | ThoughtSpot profile + session mode (A/B/C) | Mode A assumed; no instance |
| from-sv 2 | select the semantic view from a searched list | fixture-derived DDL given |
| from-sv 3 | — | `GET_DDL` unavailable; DDL re-serialised from the Cortex YAML (§3.2) |
| from-sv 5 | `Are these tables already registered in ThoughtSpot?` | answered **N/A** — no instance; tables map hand-built (§3.3 note below) |
| from-sv 6A/6B | connection-scoped vs instance-wide search; `ts snowflake introspect` + connection picker + `ts tables create` | not run — `introspect` needs live Snowflake |
| from-sv 6D | apply SV table-level `comment=` to the Table TMLs | **not run** — this is F16 |
| from-sv 7 | join-discovery options 1-4 | n/a — the SV declares all 4 relationships |
| from-sv 9.5 | `Enable Spotter (AI search)? [Y / n]` | Y |
| from-sv 10 | review TML then import / FILE | **FILE** |
| from-sv 11 / 12.5 | import; NLS Feedback TML import | skipped (no instance; no verified queries in the fixture) |
| to-sv 1 / 1.5 | ThoughtSpot + Snowflake profile selection | skipped |
| to-sv 2 | find/select the model (`G / S / B`) | TML already on disk |
| to-sv 7 | multi-domain split confirmation | single domain — one fact table |
| to-sv 8 | classify + translate every formula (a judgment step, not a CLI command) | done per the mapping reference; see the corrected-run note above |
| to-sv 10/11/12 | `YES / NO / EDIT / FILE` on the DDL; validate; execute | **FILE**; `ts snowflake lint-ddl` run; no Snowflake execution |

**Tables-map caveat.** Step 8's `tables.json` maps each SV alias to a ThoughtSpot Table
object `{name, fqn}`; with no instance there are no GUIDs, so entries carry `name` only
(`06-tables.json`). This affects `column_id` resolution not at all — every alias matches its
physical table name — but it is worth noting that **the from-snowflake-sv file-only path emits
no Table TML at all** (Step 10-FILE: "The command writes `{model_name}.model.tml` to the output directory", `SKILL.md:753`), unlike
the from-databricks path in §1.4 which emits four. That asymmetry is the mechanism behind F16.

**Validation results (verbatim).** `ts tml lint --dir ./tml_out` — exit 0:

```json
{"clean": true, "results": [{"index": 0, "type": "model", "name": "Tpcds Retail Model", "findings": []}]}
```

`python3 tools/validate/check_tml.py --file "tml_out/Tpcds Retail Model.model.tml"` — exit 0:

```
PASS  Tpcds Retail Model.model.tml (model TML)
```

`ts snowflake lint-ddl` on both regenerated DDLs — exit 0:

```
  clean — no findings
[]
```

**All three gates are clean, and all three are blind to every finding in §3 — including F9,
which makes every measure in the model unresolvable.** As in §2, they check structural
validity, not semantic fidelity to a source; §3.9 breaks down which gate could plausibly have
caught what.

### 3.4 Fidelity table

**Counting convention** (identical to §2.1, restated here so the two sections' numbers are
directly comparable). **Verdict** = the *worst* deviation anywhere across the round trip
(Cortex YAML → SV DDL → our Model TML → regenerated SV DDL); the **Evidence** column names
which leg it occurred on. **Extras** — things we add that the source lacks — are listed
separately in the last column rather than downgrading an otherwise-clean row, so nothing is
hidden and no row is scored twice.

> **Reconciling footnote (applies to §2.2 and §3.5 alike).** Because the worst deviation wins
> the row and additive extras are carried in their own column, the `extra` **verdict** column
> is unreachable at construct level — it reads `0` in both sections' count tables even where
> extras exist and are individually reported (§2.3 F5/F6; F19/F20 and the extras column below).
> The two readings are not in conflict: the `extra` column counts *rows whose worst deviation
> was an addition*, which is by construction empty, while the **additive extras** column counts
> *properties we add*. Read the additive-extras column, never the `extra` column, for what we add.

**Top-level properties**

| # | Construct | Verdict | Evidence | Extras |
|---|---|---|---|---|
| S1 | `name` | `matched` | `tpcds_retail_model` (:18) → SV `TPCDS_RETAIL_MODEL` → model `Tpcds Retail Model` (`model.tml:325`); title-casing is invertible via `to_snake` | — |
| S2 | `description` | **`mis-inferred`** | provenance appended on both legs, accretively — see F19 | — |

**Tables** — all five lose their `comment`; `store_sales` also loses its composite PK

| # | Construct | Verdict | Evidence | Extras |
|---|---|---|---|---|
| ST1 | `store_sales` | **`missed`** | `base_table` round-trips (`:22-25` → `.sql:3`); `description` (:34) and `primary_key` (:26-29) both absent from the regenerated `tables()` — see F16, F17 | — |
| ST2 | `date_dim` | **`missed`** | `primary key (d_date_sk)` survives (`.sql:4`); `description` (:109) lost — F16 | — |
| ST3 | `customer` | **`missed`** | `primary key (c_customer_sk)` survives (`.sql:5`); `description` (:155) lost — F16 | — |
| ST4 | `item` | **`missed`** | `primary key (i_item_sk)` survives (`.sql:6`); `description` (:205) lost — F16 | — |
| ST5 | `store` | **`missed`** | `primary key (s_store_sk)` survives (`.sql:7`); `description` (:262) lost — F16. Its `unique_keys: [s_store_id]` (:259-261) deliberately differs from its PK; dropped as `not-applicable` (L4) | — |

**Dimensions** (22) — 6 identifiers survive, 15 are replaced by a synonym, 1 construct is dropped

| # | Construct | Verdict | Evidence | Extras |
|---|---|---|---|---|
| SD1 | `ss_sold_date_sk` | **`mis-inferred`** | identifier → `sale date` (F10); the rename then causes the surrogate key to be re-emitted as a **`time_dimension`** (F15) | name re-added to own synonyms |
| SD2-4 | `ss_item_sk`, `ss_customer_sk`, `ss_store_sk` | **`mis-inferred`** | identifiers → `product`, `customer`, `store` — F10 | name re-added to own synonyms |
| SD5 | `d_date_sk` | `matched` | no synonyms → `D Date Sk` → `d_date_sk` (`.sql:19`); invertible | — |
| SD6-8 | `c_customer_sk`, `c_first_name`, `c_last_name` | `matched` | no synonyms; invertible title-case round trip (`.sql:23`, `:25`, `:26`) | — |
| SD9-10 | `c_customer_id`, `c_email_address` | **`mis-inferred`** | → `customer ID`, `email` — F10 | name re-added to own synonyms |
| SD11 | `customer_full_name` | **`missed`** | `\|\|` rejected by the translator; whole construct dropped — see F11 | — |
| SD12 | `i_item_sk` | `matched` | no synonyms; invertible (`.sql:28`) | — |
| SD13-17 | `i_item_id`, `i_item_desc`, `i_brand`, `i_category`, `i_current_price` | **`mis-inferred`** | → `item ID`, `product description`, `brand`, `product category`, `price` — F10 | name re-added to own synonyms |
| SD18 | `s_store_sk` | `matched` | no synonyms; invertible (`.sql:34`) | — |
| SD19-22 | `s_store_id`, `s_store_name`, `s_city`, `s_state` | **`mis-inferred`** | → `store ID`, `store name`, `city`, `state` — F10 | name re-added to own synonyms |

**Time dimensions** (4) — all four renamed; three also lose their temporal role

| # | Construct | Verdict | Evidence | Extras |
|---|---|---|---|---|
| SX1 | `d_date` | **`mis-inferred`** | identifier → `date` (F10); temporal role survives (`DATE` type re-derives it, `.sql` CA JSON `time_dimensions:[{"name":"date"}]`) | name re-added to own synonyms |
| SX2 | `d_year` | **`mis-inferred`** | → `year` (F10) **and** demoted `time_dimension` → plain dimension (F14) | name re-added to own synonyms |
| SX3 | `d_quarter_name` | **`mis-inferred`** | → `quarter` (F10) and demoted (F14) | name re-added to own synonyms |
| SX4 | `d_month_name` | **`mis-inferred`** | → `month` (F10) and demoted (F14) | name re-added to own synonyms |

**Facts** (5) — all five renamed and all five re-emitted as dimensions

| # | Construct | Verdict | Evidence | Extras |
|---|---|---|---|---|
| SF1-4 | `ss_quantity`, `ss_sales_price`, `ss_ext_sales_price`, `ss_net_profit` | **`mis-inferred`** | identifiers → `units sold`, `unit price`, `total price`, `profit` (F10); all four leave the `facts()` block and return as `dimensions()` (F13). `expr` and `description` matched throughout | name re-added to own synonyms |
| SF5 | `s_number_employees` | **`mis-inferred`** | → `employee count` (F10); `facts()` → `dimensions()` (F13) | name re-added to own synonyms |

**Relationships** (4)

| # | Construct | Verdict | Evidence | Extras |
|---|---|---|---|---|
| SR1 | `store_sales_to_date` | **`mis-inferred`** | tables and columns round-trip exactly; the **name** is regenerated as `store_sales_to_date_dim` (`.sql:10`) rather than reused — see F18 | — |
| SR2-4 | `store_sales_to_customer`, `store_sales_to_item`, `store_sales_to_store` | `matched` | names, tables and columns all survive verbatim (`.sql:11-13`). Join `type: LEFT_OUTER` + `cardinality: MANY_TO_ONE` are correctly dropped — the SV format has no join-type field (`snowflake-schema.md:225-226`), so this is `not-applicable`, **not** §2's F1 | — |

**Metrics** (5) — every measure in the model is lost

| # | Construct | Verdict | Evidence | Extras |
|---|---|---|---|---|
| SM1 | `total_sales` | **`missed`** | forward leg emits `sum ( [formula_ss_ext_sales_price] )` against a formula id that is never declared; `build-sv` then reports `SKIPPED formula 'total revenue': not in translated_formulas` and the regenerated SV has **no `metrics()` block at all** — see F9. Identifier also → `total revenue` (F10) | `aggregation: SUM`, `index_type: DONT_INDEX` (both benign — see §3.4 note) |
| SM2 | `total_profit` | **`missed`** | same; `[formula_ss_net_profit]` dangling — F9 | as above |
| SM3 | `customer_lifetime_value` | **`missed`** | same; `[formula_ss_ext_sales_price]` dangling — F9. `COUNT(DISTINCT …)` → `unique count (…)` was correct (coverage #19/I5) | as above |
| SM4 | `sales_by_brand` | **`missed`** | same — F9 | as above |
| SM5 | `store_productivity` | **`missed`** | same — F9. Independently, the corrected run shows `NULLIF(…,0)` → `DIV0` changes NULL to 0 — see F12 | as above |

**Note on the two stamped measure properties.** `aggregation: SUM` and
`index_type: DONT_INDEX` are added to all five formula-backed MEASURE columns
(`sv_build_model.py:41-44`). Both are benign and neither is a double-aggregation bug:
`agents/shared/schemas/thoughtspot-model-tml.md:200-203` states that "`aggregation:` on formula
`columns[]` entries is **ignored at query time** — ThoughtSpot evaluates the formula `expr`
directly", and the same passage prescribes `SUM` as the convention for all MEASURE formula
columns — so stamping it on the `CLV` ratio neither re-aggregates the ratio nor departs from our
own guidance. Both are recorded in the extras column for completeness only.

### 3.5 Summary counts

**Construct level** (47 constructs). Convention as stated in §3.4 — worst deviation wins the
row, additive extras counted separately; see the reconciling footnote there for why the `extra`
verdict column reads 0.

| Group | n | `matched` | `mis-inferred` | `missed` | `extra` | `not-applicable` | additive extras |
|---|---|---|---|---|---|---|---|
| **Metrics** | 5 | **0** | **0** | **5** | **0** | **0** | 15 |
| **Facts** | 5 | **0** | **5** | **0** | **0** | **0** | 5 |
| **Dimensions** | 22 | **6** | **15** | **1** | **0** | **0** | 15 |
| **Time dimensions** | 4 | **0** | **4** | **0** | **0** | **0** | 4 |
| **Relationships** | 4 | **3** | **1** | **0** | **0** | **0** | 0 |
| Tables | 5 | 0 | 0 | 5 | 0 | 0 | 0 |
| Top-level properties | 2 | 1 | 1 | 0 | 0 | 0 | 0 |
| **Total** | **47** | **10** | **26** | **11** | **0** | **0** | **39** |

**Property level** (215 source properties): **96 matched · 50 mis-inferred · 31 missed ·
0 extra · 38 not-applicable**, plus **39 properties we add** that the source lacks (29 ×
re-added self-synonym on the reverse leg, 5 × `aggregation`, 5 × `index_type`). The 38
`not-applicable` properties are the ones with no Semantic View representation at all:
28 × `data_type`, 5 × `unique_keys`, 5 × table `synonyms` — each cited to its coverage row
in §3.2. (29 source entries carry a `data_type`; the 29th belongs to `customer_full_name`,
whose whole construct is `missed` under F11, so its properties are counted there instead.) Eight further **role changes** (5 facts → dimensions, 3 time_dimensions →
dimensions) are scored at construct level only, since the Cortex YAML encodes role by
*which list an entry sits in* and there is no property to compare.

**Headline: 21% of constructs survive unchanged (10/47), and 0 of 5 measures survive at all.**
Property level reads better (96/215 = 45% matched, or 96/177 = 54% excluding
`not-applicable`) precisely because the properties that *do* survive — `expr`, `description`,
join columns — are the mechanical ones, while the properties that carry identity and role are
the ones that break.

**The two figures diverge in the opposite direction from §2.** In §2 the property-level diff
*flattered* the round trip (92% property vs a join-type defect invisible at property level).
Here property level flatters it too, but for a different reason: F9 destroys five constructs
by breaking a *reference*, and a reference has no source property to diff against — the Cortex
YAML has no "formula id" field. Both sections therefore make the same methodological point
from opposite directions: **a property-wise diff cannot see a defect in a construct's
identity, role, or cross-reference**, and those are where both converters actually fail.

### 3.6 Non-matched constructs, both definitions verbatim

Findings continue §2.3's numbering (F1-F8 are Databricks).

#### F9 — Every metric's cross-reference dangles; all five measures are lost *(SM1-SM5, `missed`, wrong side: **ours**)* — HEADLINE

The forward leg emits five metric formulas that reference formula ids which are never
declared, so `build-sv` drops all five and the regenerated Semantic View contains **no
`metrics()` block at all**. Both TML gates pass clean.

**Source (`example_converted_tpcds_semantic_model.yaml:334-340`, representative):**

```yaml
- name: total_sales
  expr: SUM(store_sales.ss_ext_sales_price)
  description: Total sales revenue across all transactions
  synonyms:
  - total revenue
  - gross sales
  - sales amount
```

**Ours (`tml_out/Tpcds Retail Model.model.tml:277-292`) — the `formulas[]` block in full:**

```yaml
  formulas:
  - expr: "sum ( [formula_ss_ext_sales_price] )"
    id: formula_total revenue
    name: total revenue
  - expr: "sum ( [formula_ss_net_profit] )"
    id: formula_net profit
    name: net profit
  - expr: "sum ( [formula_ss_ext_sales_price] ) / unique count ( [CUSTOMER::c_customer_sk] )"
    id: formula_CLV
    name: CLV
  - expr: "sum ( [formula_ss_ext_sales_price] )"
    id: formula_brand sales
    name: brand sales
  - expr: "safe_divide ( sum ( [formula_ss_ext_sales_price] ) , sum ( [formula_s_number_employees] ) )"
    id: formula_sales per employee
    name: sales per employee
```

Declared ids are `formula_total revenue`, `formula_net profit`, `formula_CLV`,
`formula_brand sales`, `formula_sales per employee`. Referenced ids are
`formula_ss_ext_sales_price`, `formula_ss_net_profit`, `formula_s_number_employees` — **none
of which exists.** All three referents were emitted as plain `columns[]` entries instead
(`model.tml:196-219`, e.g. `column_id: "STORE_SALES::ss_ext_sales_price"`, `name: total price`).
Machine-checked: `5/5` formulas carry at least one dangling reference (`14-tally.txt`,
`compare.py` "MODEL TML FORMULA INTEGRITY").

**Consequence on the reverse leg (`09-regenerated-sv.sql`, stderr):**

```
  SKIPPED formula 'total revenue': not in translated_formulas
  SKIPPED formula 'net profit': not in translated_formulas
  SKIPPED formula 'CLV': not in translated_formulas
  SKIPPED formula 'brand sales': not in translated_formulas
  SKIPPED formula 'sales per employee': not in translated_formulas
```

`"metrics": 0`. The regenerated Semantic View is a five-table model with 28 dimensions and
**not one measure**.

**Two independent defects, both in the resolver.** `tools/ts-cli/ts_cli/sv_translate.py:125-137`:

```python
        if len(parts) == 2:
            alias, col = parts[0].lower(), parts[1]
            key = f"{alias}.{col.lower()}"
            if key in fact_idx:
                return f"[formula_{col}]"
            if key in metric_idx:
                return f"[formula_{col}]"
            table = alias_map.get(alias)
```

1. **The documented resolution order is inverted.** `agents/shared/mappings/ts-snowflake/ts-from-snowflake-rules.md:585-593`
   is explicit:

   > ```
   > 1. Is `name` a physical column on the table identified by `table_alias`?
   >    YES → emit [TABLE_ID::col_name]  (standard column reference)
   >    NO  → step 2
   >
   > 2. Is `name` a FACT_NAME in the facts map where the fact's table_alias matches?
   > ```

   Physical column is step 1; fact is step 2. The code checks `fact_idx`/`metric_idx` *first*
   and only falls through to `alias_map` afterwards. The function's own docstring
   (`sv_translate.py:103-110`) restates the correct order immediately above the code that
   inverts it. For a passthrough fact — one whose `expr` *is* a physical column, which is what
   upstream produces for every OSI field lacking a `dimension` block — step 1 would have
   emitted `[STORE_SALES::ss_ext_sales_price]` and resolved cleanly.

2. **The emitted id is not the id `build-model` mints.** Even where a fact legitimately becomes
   a formula, the resolver emits `[formula_<sql_token>]` while `build-model` derives the id from
   the *display* name. The same rules file forecloses this at step 2: "The reference uses the
   formula's `id` value (e.g. `formula_Tenure Months`), **NOT** the display name." A targeted
   probe with a computed fact carrying synonyms (`probe/computed_fact.sql`) shows both halves at
   once — declared `id: formula_Net Line Amount`, referenced `[formula_net_line]`, dangling.

**This is a regression against a live-verified baseline, and the regression is load-bearing.**
`agents/shared/worked-examples/snowflake/ts-from-snowflake-identifier-resolution.md` was
"Verified end-to-end against `se-thoughtspot` on 2026-06-13" (`:23`, with the resulting model
GUID recorded) and documents the correct output at `:233`:

```yaml
  - id: formula_Avg Tenure
    expr: "average ( [formula_Tenure Months] )"
```

Re-running **that worked example's own DDL** through today's pipeline produces instead:

```
    'formula_Avg Tenure' = average ( [formula_tenure_months] )
    'formula_Total Tenure' = sum ( [formula_tenure_months] )
    'formula_Avg Headcount Per Company' = average ( [formula_headcount] )
    'formula_Max Salary Budget' = max ( [formula_total_salary] )
DANGLING: ['formula_headcount', 'formula_tenure_months', 'formula_total_salary']
```

4 of 8 formulas broken on the repo's own showcase fixture. Per `agents/shared/CLAUDE.md`
("Worked examples are ground truth"), the worked example wins: the CLI is wrong. The likely
window is the Step 4/9/8 rewire onto deterministic commands — `SKILL.md` changelog v1.17.0,
2026-07-22, "Rewire onto deterministic CLI commands … Removes 8 inline Python code blocks",
which postdates the 2026-06-13 verification.

**Why it survived: the unit tests assert the defect.** `tools/ts-cli/tests/test_sv_translate.py:352-361`:

```python
    def test_fact_reference(self):
        parsed = _parsed_workforce()
        resolver = make_resolver(parsed, "employees")
        assert resolver("employees.tenure_months") == \
            "[formula_tenure_months]"
```

The resolver and `build-model` are each tested in isolation and the contract *between* them —
that every `[formula_X]` a metric emits matches an id `build-model` will declare — is asserted
nowhere. That is the gap to close, and it is a validator-shaped gap (§3.9).

**Referee:** the OSI form preserves all five metrics with their expressions intact
(`examples/tpcds_semantic_model.yaml:547-611`), and upstream's Cortex YAML carries them through
faithfully. Nothing on either of their sides is at fault; the loss is entirely ours.

**Impact.** A user converting any Semantic View whose metrics aggregate a declared fact — the
normal shape, and the shape upstream's converter always emits — receives a Model in which every
measure is unresolvable, with `ts tml lint` and `check_tml.py` both reporting clean. Live import
behaviour was **not verified** (no instance); per `CLAUDE.md`'s formula invariant a bracket
reference that matches no `formulas[].id` is parsed as search tokens rather than resolving, so
the expected outcome is import failure or a silently broken measure, but which of the two is
unconfirmed here.

#### F10 — The SV logical identifier is replaced by its first synonym *(29 of 36 constructs, `mis-inferred`, wrong side: **ours**)*

**Source (`example_converted_tpcds_semantic_model.yaml:41-47`, representative):**

```yaml
  - name: ss_sold_date_sk
    expr: ss_sold_date_sk
    description: Foreign key to date dimension
    synonyms:
    - sale date
    - transaction date
    data_type: NUMBER(38,0)
```

**Ours (`tml_out/Tpcds Retail Model.model.tml:3-10`):**

```yaml
  - column_id: "STORE_SALES::ss_sold_date_sk"
    name: sale date
    properties:
      column_type: ATTRIBUTE
      description: Foreign key to date dimension
      synonym_type: USER_DEFINED
      synonyms:
      - transaction date
```

**Regenerated (`09-regenerated-sv.sql:44`):**

```
    STORE_SALES.sale_date as store_sales.ss_sold_date_sk with synonyms=('sale date', 'transaction date') comment='Foreign key to date dimension'
```

The identifier `ss_sold_date_sk` is gone from the logical layer; `sale_date` has taken its
place, and the promoted synonym has been re-added to its own synonym list. **29 of the 36
named dimension/time_dimension/fact/metric constructs are renamed this way** — every construct
that carries a `synonyms` list (`13-comparison.txt`, "NAME FATE"). The 6 survivors
(`d_date_sk`, `c_customer_sk`, `c_first_name`, `c_last_name`, `i_item_sk`, `s_store_sk`) survive
only because they have no synonyms, so the title-case ↔ snake-case pair is invertible — exactly
the mechanism behind §2's F2.

**This is documented behaviour, and the documentation is the problem.** Coverage row 14 states
it plainly: "`with synonyms=('...',...)` on dimensions/metrics → `column.name` +
`properties.synonyms` | **First synonym → name**; rest → synonyms"
(`references/coverage-matrix.md:37`). The heuristic is defensible for Semantic Views our *own*
to-direction authored — `build-sv` emits the ThoughtSpot column name as the first synonym
(`09-regenerated-sv.sql` shows exactly that), so the pair round-trips cleanly. It is wrong for
a Semantic View authored anywhere else, where `with synonyms=(...)` means what Snowflake says
it means: alternate names for natural-language matching, not a display name.

**Referee: unambiguous, and it separates the two fields explicitly.** OSI keeps `name` and
synonyms in different places — `name: total_sales` (`examples/tpcds_semantic_model.yaml:547`)
versus `ai_context.synonyms: ["total revenue", "gross sales", "sales amount"]` (`:554-558`).
A converter that promotes `total revenue` over `total_sales` is discarding the identifier the
referee took care to keep. Upstream carried both through correctly.

**Worst on the metrics**, where the substitutions are not even display-name-shaped:
`total_sales` → `total revenue`, `customer_lifetime_value` → **`CLV`**,
`store_productivity` → `sales per employee`, `sales_by_brand` → `brand sales`. Any Cortex
Analyst verified query, saved question, or downstream SQL referencing `total_sales` breaks.

**It also compounds.** The rename is what triggers F15: `ss_sold_date_sk` does not match the
reverse leg's date-name heuristic, but `sale date` does.

#### F11 — `||` string concatenation is rejected, dropping the construct, though `CONCAT` is mapped *(SD11, `missed`, wrong side: **ours**)*

**Source (`example_converted_tpcds_semantic_model.yaml:180-186`):**

```yaml
  - name: customer_full_name
    expr: c_first_name || ' ' || c_last_name
    description: Customer full name (computed field)
    synonyms:
    - full name
    - customer name
    data_type: VARCHAR
```

**Ours — nothing.** The construct is absent from the Model TML and from both regenerated DDLs.
`ts snowflake translate-formulas` (stderr, verbatim):

```
Skipped:
  - customer_full_name (dimensions): operator '||' — use CONCAT() instead (ts-snowflake-formula-translation.md)
```

**The suggested replacement is already a documented, bidirectional mapping.**
`agents/shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md:197-198`:

```
| `concat ( [a] , [b] )` → `CONCAT(a, b)` | `CONCAT(a, b)` → `concat ( [a] , [b] )` |
| `concat ( [a] , ' ' , [b] )` → `CONCAT(a, ' ', b)` *(supports N args)* | `CONCAT(a, ' ', b)` → `concat ( [a] , ' ' , [b] )` |
```

The second row is a character-for-character match for the target shape needed here —
`concat ( [CUSTOMER::c_first_name] , ' ' , [CUSTOMER::c_last_name] )`. So the translator
declines a translation whose rule it cites in its own error message. The `||` → `concat`
rewrite is a mechanical N-ary fold with no judgment involved.

**Referee: `||` is not a Snowflake dialect quirk that could excuse skipping it.** The OSI
source declares the expression under `dialect: ANSI_SQL`
(`examples/tpcds_semantic_model.yaml:290-292`):

```yaml
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: c_first_name || ' ' || c_last_name
```

`||` is the ANSI SQL standard concatenation operator. A converter that consumes ANSI_SQL
expressions and cannot handle `||` will drop this construct from a large share of real
Semantic Views — and upstream's converter passes expressions through untouched
(`docs/reviews/2026-07-29-ossie-converter-learnings.md` §3.2: "The expression string itself is
never parsed or rewritten"), so *every* `||` in any OSI model reaches us intact.

**Not in the coverage matrix.** Neither the Mapped nor the Unmapped section of
`references/coverage-matrix.md` has a row for `||`, so today the drop is undeclared as well
as unimplemented.

#### F12 — `NULLIF(x, 0)` division guard becomes `safe_divide`/`DIV0`: NULL silently becomes 0 *(SM5, `mis-inferred` on the metric expression, wrong side: **ours**)*

Independent of F9 — visible on both legs, and isolated by the corrected reverse run.

**Source (`example_converted_tpcds_semantic_model.yaml:363-366`):**

```yaml
- name: store_productivity
  expr: SUM(store_sales.ss_ext_sales_price) / NULLIF(SUM(store.s_number_employees),
    0)
  description: Sales per employee across stores
```

**Ours, forward leg (`tml_out/Tpcds Retail Model.model.tml:290`):**

```yaml
  - expr: "safe_divide ( sum ( [formula_ss_ext_sales_price] ) , sum ( [formula_s_number_employees] ) )"
```

**Ours, regenerated (`12-regenerated-sv-corrected.sql:52`):**

```
    sales_per_employee as DIV0(SUM(store_sales.ss_ext_sales_price), SUM(store.s_number_employees)) with synonyms=('sales per employee', 'employee productivity', 'revenue per employee') comment='Sales per employee across stores'
```

`X / NULLIF(Y, 0)` yields **NULL** when `Y = 0`. `safe_divide` yields **0** — our own schema
reference states it outright at `agents/shared/schemas/thoughtspot-formula-patterns.md:171`:

> | `safe_divide` | `safe_divide ( [a] , [b] )` — returns 0 (not NULL) when `b` is 0 |

and the round trip completes the substitution by emitting Snowflake's `DIV0`, which the
ts-snowflake mapping pairs with `safe_divide` for exactly that reason (`:172`). So a store
with zero employees reports **0 sales per employee** in ThoughtSpot and in the regenerated
Semantic View, where the source reports "no value". The two are not interchangeable
downstream: 0 participates in `AVG`, `MIN`, and ranking; NULL does not.

**A NULL-preserving translation was available and is documented in the same table.**
`ts-snowflake-formula-translation.md:154` maps `NULLIF` in both directions:

```
| `nullif ( [a] , [b] )` → `NULLIF(a, b)` | `NULLIF(a, b)` → `nullif ( [a] , [b] )` |
```

so `sum ( [...] ) / nullif ( sum ( [...] ) , 0 )` was expressible throughout.

**Silent.** The translated entry carries `"annotations": []` — no flag, no note, nothing in
the `build-model` summary. Notably the **Tableau** mapping already warns about this exact
hazard (`agents/shared/mappings/tableau/tableau-formula-translation.md:319`: "Returns **0**,
not NULL, on zero divisor … flag if downstream logic distinguishes 0 from NULL"); the
ts-snowflake mapping carries no such warning, and the from-direction applies the substitution
without one. **The magnitude is not measured here** — it depends on how many stores have zero
employees, which needs live data on both sides (§3.10).

#### F13 — Facts are classified `ATTRIBUTE` unconditionally, so `facts()` returns as `dimensions()` *(SF1-SF5, `mis-inferred`, wrong side: **ours**)*

**Source (`example_converted_tpcds_semantic_model.yaml:69-76`, representative — a `facts:` member):**

```yaml
  facts:
  - name: ss_quantity
    expr: ss_quantity
    description: Quantity of items sold
    synonyms:
    - units sold
    - quantity
    data_type: NUMBER(38,0)
```

**Ours (`tml_out/Tpcds Retail Model.model.tml:180-187`):**

```yaml
  - column_id: "STORE_SALES::ss_quantity"
    name: units sold
    properties:
      column_type: ATTRIBUTE
      description: Quantity of items sold
      synonym_type: USER_DEFINED
      synonyms:
      - quantity
```

**Regenerated (`09-regenerated-sv.sql:39`) — now inside the `dimensions()` block:**

```
    STORE_SALES.units_sold as store_sales.ss_quantity with synonyms=('units sold', 'quantity') comment='Quantity of items sold'
```

All five facts make this trip; the regenerated Semantic View has no `facts()` block at all
(`13-comparison.txt`, "REGENERATED SV BLOCKS": `'facts': False`). Quantities, prices, profit
and employee counts are declared to Cortex Analyst as categorical dimensions.

**The choice the coverage matrix documents is never actually made.** Row 16 says facts →
"`formulas[]` entries (**MEASURE or ATTRIBUTE**)" (`references/coverage-matrix.md:44`), but
`tools/ts-cli/ts_cli/sv_translate.py:454-468` hardcodes the constant on both branches:

```python
def _translate_fact(
    fact: dict, parsed: dict, alias_map: dict[str, str],
) -> dict[str, Any]:
    """Translate one fact entry. Facts are intermediate computed columns —
    always formulas, classified as ATTRIBUTE (non-aggregated) or MEASURE."""
    if fact["expr"] is None:
        table = alias_map.get(fact["alias_table"].lower(), fact["source_table"])
        return _entry(
            fact["source_column"], "fact", "column", "ATTRIBUTE", fact,
            table=table, column=fact["alias_name"])
```

There is no `MEASURE` branch anywhere in the function — the docstring describes a decision the
code does not implement. This is structurally the same defect as §2's F1 (a hardcoded constant
where the source implies a choice), in a different converter.

**Referee: the OSI form marks these as facts by construction.** Every one of the five lacks a
`dimension:` block (`examples/tpcds_semantic_model.yaml:103-149`, `:491-501`), which is precisely
how OSI distinguishes a fact — upstream's `_classify_field` documents the rule as "A field with
no `dimension` block is a `fact` regardless of `datatype`". The 22 true dimensions all carry
`dimension: {is_time: false}` and are correctly `ATTRIBUTE` on our side. So the referee draws
the fact/dimension line cleanly, upstream transmits it cleanly, and we erase it.

#### F14 — `time_dimension` role lost for temporal dimensions that are not date-typed *(SX2-SX4, `mis-inferred`, wrong side: **ours**, with a real ThoughtSpot constraint behind it)*

**Source (`example_converted_tpcds_semantic_model.yaml:127-138`, two of three):**

```yaml
  - name: d_year
    expr: d_year
    description: Year
    synonyms:
    - year
    data_type: NUMBER(38,0)
  - name: d_quarter_name
    expr: d_quarter_name
    description: Quarter name (e.g., 2024Q1)
    synonyms:
    - quarter
    - fiscal quarter
```

— all three sit under `time_dimensions:` (`:119`).

**Regenerated (`09-regenerated-sv.sql:20-22`) — inside `dimensions()`, and absent from the
CA JSON's `time_dimensions`:**

```
    DATE_DIM.year as date_dim.d_year comment='Year',
    DATE_DIM.quarter as date_dim.d_quarter_name with synonyms=('quarter', 'fiscal quarter') comment='Quarter name (e.g., 2024Q1)',
    DATE_DIM.month as date_dim.d_month_name comment='Month name'
```

`d_date` survives as a time dimension because its `DATE` type re-derives the role; the three
whose temporal nature is semantic rather than typed (a `NUMBER` year, two `VARCHAR` names) do
not. The forward leg maps every time dimension to `ATTRIBUTE` — documented behaviour
(`ts-from-snowflake-rules.md:244`: "`time_dimensions` → `ATTRIBUTE` (ThoughtSpot infers date
type from the Snowflake column)") — and the reverse leg then has only the data type to work
from.

**Referee: explicit, and on the losing side.** OSI declares the temporal role independently of
the data type, and the fixture's comments call this out as deliberate
(`examples/tpcds_semantic_model.yaml:201-210`):

```yaml
          # Declares temporal role via is_time without a datatype annotation.
          # Both datatype and is_time are independently optional.
          - name: d_quarter_name
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: d_quarter_name
            description: Quarter name (e.g., 2024Q1)
            dimension:
              is_time: true
```

`d_year` carries `is_time: true` at `:195-196`, `d_month_name` at `:224-225`. So the referee
preserves the role and upstream transmits it into `time_dimensions:`. ThoughtSpot Model TML has
no independent temporal-role flag for a non-date-typed column, so the constraint on our side is
real — but the loss is still ours, and it is undeclared: the coverage matrix has **no row for
`time_dimensions`** in either section.

#### F15 — A surrogate key is re-emitted as a `time_dimension`, caused by F10's rename *(SD1, `mis-inferred`, wrong side: **ours**)*

**Source (`:41-47`):** `ss_sold_date_sk`, a `NUMBER(38,0)` foreign key, declared under
`dimensions:` — *not* `time_dimensions:`.

**Regenerated (`09-regenerated-sv.sql`, CA extension JSON):**

```json
{"name":"store_sales", ... ,"time_dimensions":[{"name":"sale_date"}]}
```

An integer surrogate key is declared to Cortex Analyst as the fact table's time dimension,
which invites date filtering and date truncation of a join key.

**Mechanism — a name-suffix fallback (`tools/ts-cli/ts_cli/sv_build_sv.py:94-105`):**

```python
_DATE_SUFFIXES = (
    "_date", "_at", "_time", "_ts", "_datetime",
    "date", "time", "timestamp",
)


def _is_date_column(col_name: str, data_type: str) -> bool:
    dt = data_type.upper().strip()
    if dt in _DATE_TYPES:
        return True
    lower = col_name.lower()
    return any(lower.endswith(s) for s in _DATE_SUFFIXES)
```

The column's declared type is `INT64`, so the type test correctly fails; the name test then
matches the bare suffix `"date"`.

**The two defects compound, and that is the point.** The original identifier
`ss_sold_date_sk` ends in `_sk` and matches **no** entry in `_DATE_SUFFIXES` — it would have
been classified a plain dimension. It only trips the heuristic because F10 renamed it to the
first synonym `sale date`. Neither defect alone produces this; the combination does. The
source `data_type: NUMBER(38,0)` was available and correct throughout and is not consulted
once the name heuristic fires.

#### F16 — Table-level `comment` is lost for all five tables in the file-only path *(ST1-ST5, `missed`, wrong side: **ours**)*

**Source (`example_converted_tpcds_semantic_model.yaml:34`, representative; all five tables carry one):**

```yaml
  description: Fact table containing all store sales transactions
```

**Regenerated (`09-regenerated-sv.sql:2-8`) — the `tables()` block in full, no `comment=` anywhere:**

```
  tables (
    TPCDS.PUBLIC.STORE_SALES,
    TPCDS.PUBLIC.DATE_DIM primary key (d_date_sk),
    TPCDS.PUBLIC.CUSTOMER primary key (c_customer_sk),
    TPCDS.PUBLIC.ITEM primary key (i_item_sk),
    TPCDS.PUBLIC.STORE primary key (s_store_sk)
  )
```

`ts snowflake parse-sv` captured all five correctly (`04-parsed.json`: `"comment": "Fact table
containing all store sales transactions"` on the `STORE_SALES` entry), so the information
reaches our pipeline and is discarded downstream.

**Why: the target lives in a file the file-only path never writes.** Coverage row 5 maps
table-level `comment=` → `table.description` with the note "**Separate Table TML update**"
(`references/coverage-matrix.md:18`), applied by Step 6D. But Step 10-FILE emits the Model TML
only — "The command writes `{model_name}.model.tml` to the output directory"
(`SKILL.md:753-754`) — and Step 6D depends on Table TMLs fetched from a live instance. So on
the documented offline path the mapping row is unreachable and five table descriptions are
silently dropped. Contrast §1.4, where the from-databricks file-only path emits four Table
TMLs alongside the model.

Table-level `synonyms` (4 + 3 + 3 + 3 + 3 = 16 values) are also absent, but that is
`not-applicable` by **L2** ("No ThoughtSpot table-level synonym concept"), correctly declared.

#### F17 — The fact table's composite primary key is dropped *(ST1, `missed`, wrong side: **ours**)*

**Source (`example_converted_tpcds_semantic_model.yaml:26-33`):**

```yaml
  primary_key:
    columns:
    - ss_item_sk
    - ss_ticket_number
  unique_keys:
  - columns:
    - ss_item_sk
    - ss_ticket_number
```

**Regenerated (`09-regenerated-sv.sql:3`):**

```
    TPCDS.PUBLIC.STORE_SALES,
```

No `primary key` clause. The four dimension tables keep theirs because each is the `right_table`
of a relationship; `store_sales` is on the `left_table` side of all four and never a join target,
so the reverse leg has no relationship from which to recover a PK. `ss_ticket_number` is
additionally the one PK column the SV references nowhere else, so it vanishes from the model
entirely.

Consequences are modest but real: `primary_key` is required on any table that later becomes a
relationship target (`snowflake-schema.md:244-245`), so a regenerated view extended with a new
relationship into `store_sales` would fail validation, and Snowflake loses the grain declaration
for the fact table. Our own coverage matrix says PK is "Not written to TML" by design (row 4,
`coverage-matrix.md:17`) — which is the mechanism, and is fine for the forward direction, but it
means the round trip cannot restore a PK that no join implies.

#### F18 — Relationship names are regenerated rather than reused *(SR1, `mis-inferred`, wrong side: **ours**)*

**Source (`example_converted_tpcds_semantic_model.yaml:309-314`):**

```yaml
- name: store_sales_to_date
  left_table: store_sales
  right_table: date_dim
  relationship_columns:
  - left_column: ss_sold_date_sk
    right_column: d_date_sk
```

**Regenerated (`09-regenerated-sv.sql:10`):**

```
    store_sales_to_date_dim as STORE_SALES(ss_sold_date_sk) references DATE_DIM(d_date_sk),
```

The forward leg preserved the name correctly — `name: store_sales_to_date` on the join
(`tml_out/Tpcds Retail Model.model.tml:297`) — and the reverse leg discarded it in favour of a
`{left}_to_{right}` name synthesised from table names. The other three names survive only
coincidentally: `store_sales_to_customer`, `store_sales_to_item` and `store_sales_to_store`
already match the generated pattern. `store_sales_to_date` does not, because upstream named it
after the *concept* rather than the table (`date_dim`).

Relationship names are referenceable in Snowflake — `using_relationships` on a metric names them
(`snowflake-schema.md:146-147`) — so a rename breaks any metric or verified query that cites one.
Low impact on this fixture (nothing references them) but it is a name-fidelity loss that costs
nothing to avoid, since the name is sitting in the Model TML.

#### F19 — Model description accretes one provenance sentence per leg *(S2, `mis-inferred`, wrong side: **ours** — same class as §2's F4)*

**Source (`example_converted_tpcds_semantic_model.yaml:19`):**

```yaml
description: TPC-DS retail semantic model for sales and customer analytics
```

**After the forward leg (`tml_out/Tpcds Retail Model.model.tml:276`):**

```yaml
  description: TPC-DS retail semantic model for sales and customer analytics Converted from Snowflake Semantic View TPCDS.PUBLIC.TPCDS_RETAIL_MODEL.
```

**After the reverse leg (`09-regenerated-sv.sql:47`):**

```
  comment='TPC-DS retail semantic model for sales and customer analytics Converted from Snowflake Semantic View TPCDS.PUBLIC.TPCDS_RETAIL_MODEL. | Migrated from ThoughtSpot: Tpcds Retail Model'
```

Both defects §2's F4 identified are present, and this confirms them as a **cross-converter
class rather than a Databricks quirk**:

1. **Missing separator** — `"…customer analytics Converted from Snowflake…"` is a run-on, the
   source description having no terminating punctuation. User-visible in the ThoughtSpot model
   description independent of any round trip.
2. **Accretion** — each leg appends and neither strips, so the string grows without bound
   across repeated conversions. Here *two* provenance strings have accumulated in a single
   round trip (the Snowflake pair appends on both legs, where §2's Databricks pair appended on
   one), so this direction accretes twice as fast.

The provenance is legitimate; writing it into the field that round-trips as the source's own
description is not.

#### F20 — Every formula-backed metric is grouped under a fabricated CA-extension table named `field` *(`extra`, wrong side: **ours**)*

Visible in the corrected reverse run (the as-is run has no metrics to group).

**Regenerated (`12-regenerated-sv-corrected.sql:55`, CA extension JSON, final table entry):**

```json
{"name":"field","metrics":[{"name":"total_revenue"},{"name":"net_profit"},{"name":"clv"},{"name":"brand_sales"},{"name":"sales_per_employee"}]}
```

There is no table named `field` in the view — `tables()` declares `STORE_SALES`, `DATE_DIM`,
`CUSTOMER`, `ITEM`, `STORE`. The Cortex Analyst context JSON therefore attributes all five
metrics to a non-existent table.

**Mechanism.** `_classify_formula_column` (`tools/ts-cli/ts_cli/sv_build_sv.py:531-538`) builds
the metric entry without a `"table"` key:

```python
    entry = {
        "alias": alias,
        "display_name": col_name,
        "expr": tf["expr"],
        "classification": classification,
        "synonyms": props.get("synonyms", []),
        "comment": props.get("description"),
    }
```

`_build_ca_tables` then groups by `to_snake(m.get("table", ""))` (`:610-613`), and `to_snake`
returns the placeholder `"field"` for an empty string (`:24-32`):

```python
def to_snake(name: str) -> str:
    """Convert a display name to a snake_case SV alias."""
    s = re.sub(r"[^a-z0-9]", "_", name.lower())
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        return "field"
```

The `if tname:` guard immediately above was clearly meant to skip untabled entries; `"field"`
is truthy, so it never fires. This is general — **any** Model with formula-backed measures
produces it, not just this fixture.

`ts snowflake lint-ddl` reports `clean — no findings` on this DDL despite its documented remit
including "undeclared table references" (`ts snowflake lint-ddl --help`) — it checks the DDL
clauses and not the CA JSON payload.

#### F21 — Root-level metrics carry no `using_relationships` *(SM1-SM5, both sides, referee silent — recorded, not charged to either converter)*

Also from the corrected run. **Regenerated (`12-regenerated-sv-corrected.sql:47-53`, abbreviated):**

```
  metrics (
    total_revenue as SUM(store_sales.ss_ext_sales_price) ...,
    clv as SUM(store_sales.ss_ext_sales_price) / COUNT(DISTINCT customer.c_customer_sk) ...,
    sales_per_employee as DIV0(SUM(store_sales.ss_ext_sales_price), SUM(store.s_number_employees)) ...
  )
```

Every metric name is unqualified, which in Semantic View terms is the **derived-metric** form —
reserved for expressions spanning multiple logical tables, and required to declare its path.
`agents/shared/schemas/snowflake-schema.md:275-276`:

```yaml
  using_relationships:
  - fact_sales_to_fact_cost
```

with Key Structural Rule #1 (`:233-239`) stating that "A metric scoped to a single table's own
columns still belongs in that table's `metrics:` list, not at the root."

Two observations, deliberately kept apart:

- **Table scoping is `matched`, not a loss.** Upstream emits all five metrics at the document
  root (`example_converted_tpcds_semantic_model.yaml:333`), and so does our reverse leg — the
  same form on both sides. Only §3.2's DDL re-serialisation added the `STORE_SALES.` prefixes,
  which is why §3.4 scores this against the Cortex source rather than the DDL. Charging it to
  either converter would be scoring an artifact of the test harness.
- **The missing `using_relationships` is genuine but unadjudicable.** Neither side emits it, so
  `clv` and `sales_per_employee` — which really do span `store_sales` × `customer` and
  `store_sales` × `store` — reach Snowflake as root-level metrics with no declared relationship
  path. The referee cannot settle it: OSI metrics are model-level by spec
  (`examples/tpcds_semantic_model.yaml:546`, "Semantic model-level metrics spanning multiple
  datasets"), so OSI has no per-table metric concept and upstream had no information with which
  to scope them. Whether Snowflake resolves such a metric by inference or rejects it is
  **unverified here** — it needs a live `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML` round trip
  (§3.10), and BL-031 already tracks the converter's non-emission of `using_relationships`.

### 3.7 Which side is wrong — summary

| Finding | Verdict | Wrong side | Judged against |
|---|---|---|---|
| F9 metric cross-references dangle; 5/5 measures lost | `missed` | **ours** | `ts-from-snowflake-rules.md:585-593` (documented order inverted) + live-verified worked example `ts-from-snowflake-identifier-resolution.md:23`,`:233`; referee preserves all 5 metrics |
| F10 identifier replaced by first synonym (29/36) | `mis-inferred` | **ours** (documented in coverage row 14, but wrong for foreign SVs) | OSI referee separates `name` (`:547`) from `ai_context.synonyms` (`:554-558`) |
| F11 `\|\|` rejected, construct dropped | `missed` | **ours** — the cited replacement is already mapped | `ts-snowflake-formula-translation.md:197-198`; OSI declares it `ANSI_SQL` (`:290-292`) |
| F12 `NULLIF(…,0)` → `safe_divide`/`DIV0`, NULL→0 | `mis-inferred` | **ours** | `thoughtspot-formula-patterns.md:171`; `nullif` available (`ts-snowflake-formula-translation.md:154`) |
| F13 facts → ATTRIBUTE → `dimensions()` | `mis-inferred` | **ours** — contradicts coverage row 16's "MEASURE or ATTRIBUTE" | OSI marks all 5 as facts by omitting `dimension:` (`:103-149`, `:491-501`) |
| F14 `time_dimension` role lost (3/4) | `mis-inferred` | **ours**, ThoughtSpot has no non-date temporal flag | OSI `is_time: true` explicit and commented as deliberate (`:195`, `:201-210`, `:224`) |
| F15 surrogate key → `time_dimension` | `mis-inferred` | **ours** — compounds with F10 | source `data_type: NUMBER(38,0)` (`:47`); `sv_build_sv.py:94-105` |
| F16 table `comment` lost (5/5) | `missed` | **ours** — coverage row 5 claims it maps; unreachable offline | source `:34`,`:109`,`:155`,`:205`,`:262`; `SKILL.md:747-748` |
| F17 fact table's composite PK dropped | `missed` | **ours** | source `:26-29`; `snowflake-schema.md:244-245` |
| F18 relationship name regenerated | `mis-inferred` | **ours** — name was preserved in the TML and then discarded | source `:309`; `model.tml:297` |
| F19 description provenance + accretion (×2) | `mis-inferred` | **ours** — same class as §2's F4 | source `:19` |
| F20 fabricated CA table `field` | `extra` | **ours** | `sv_build_sv.py:24-32`, `:531-538`, `:610-613` |
| F21 root metrics without `using_relationships` | — | **both / unadjudicable** | `snowflake-schema.md:233-239`, `:275-276`; referee has no per-table metric concept (`:546`) |
| *(upstream, out of denominators)* model `ai_context`, relationship synonyms ×4, `custom_extensions` ×2, metric `datatype` ×5 dropped | — | **upstream's** | OSI `:29`, `:510-543`, `:613-631`, `:553`+; `converters/README.md:260` |

### 3.8 Documentation gaps found alongside the behaviour

| Gap | Location | Nature |
|---|---|---|
| No coverage row for `\|\|` (or any string operator) | `references/coverage-matrix.md` — Mapped and Unmapped sections | Missing — the F11 drop is neither implemented nor declared, while `ts-snowflake-formula-translation.md:197-198` maps the equivalent |
| No coverage row for `time_dimensions` | same file, Dimensions section (`:31-38`) | Missing — F14's role loss is undeclared |
| No coverage row for `data_type` on dimensions/facts | same file | Missing — 26 source properties are `not-applicable` with nothing to cite |
| Row 16 says facts → "MEASURE **or** ATTRIBUTE" | `coverage-matrix.md:44` | **Stale/aspirational** — `sv_translate.py:454-468` has no MEASURE branch (F13) |
| Row 5 says table `comment=` → `table.description` via "Separate Table TML update" | `coverage-matrix.md:18` | **Unreachable on the documented file-only path** — Step 10-FILE emits no Table TML (F16) |
| Identifier Resolution Algorithm step 1 vs step 2 | `ts-from-snowflake-rules.md:585-593` vs `sv_translate.py:125-137` | **Code contradicts the rule** and its own docstring (F9) |
| Worked example no longer reproducible | `worked-examples/snowflake/ts-from-snowflake-identifier-resolution.md:233` | **Regressed** — the documented `[formula_Tenure Months]` is now emitted as `[formula_tenure_months]` (F9) |
| No warning that `safe_divide` ≠ `x / NULLIF(y,0)` | `ts-snowflake-formula-translation.md:172` | Missing — the Tableau mapping carries exactly this warning at `tableau-formula-translation.md:319` (F12) |

### 3.9 What the existing gates did and did not catch

| Gate | Result | Findings caught |
|---|---|---|
| `ts snowflake parse-sv` | exit 0, `warnings: []`, `unsupported: []` | — (correctly: it parsed all 47 constructs, including table comments and PKs) |
| `ts snowflake translate-formulas` | exit 0, 35/36, 1 skipped | **F11 only** — and it names the fix in the skip message without applying it. Emits F9's dangling references and F12's NULL→0 substitution with `annotations: []` |
| `ts snowflake build-model` | exit 0, `lint_findings: []`, `name_renames: {}` | **none of F9/F10/F13** — this is where F9, F10, F13 and F19 are introduced |
| `ts tml lint --dir` | `"clean": true` | **none** — notably blind to F9, a dangling `[formula_X]` reference in 5 of 5 formulas |
| `tools/validate/check_tml.py` | `PASS` | none |
| `ts snowflake build-sv` | exit 0; 5 × `SKIPPED formula`, 4 × `DROPPED join attrs` | **F9's symptom** — the 5 skip lines are the only signal a user gets that every measure is gone, and they appear on stderr beside 4 benign `DROPPED join attrs` lines. The `DROPPED join attrs` warnings are correct and expected (SV has no join type) |
| `ts snowflake lint-ddl` | `clean — no findings` on **both** DDLs | **none** — clean on a Semantic View with zero metrics, and clean on one whose CA JSON references a non-existent table `field` (F20), despite "undeclared table references" being in its documented remit |

Every gate is green and every finding survives. Two are validator-shaped and worth promoting
per the two-bucket rule (`.claude/rules/repo-audit.md`):

- **Dangling `[formula_X]` references** (F9, F20) — a purely structural check over a single TML
  document: every bracket reference matching `formula_*` must match a `formulas[].id`. No live
  instance needed, no judgment. It belongs in `ts tml lint`'s invariant set beside I5/I8, and it
  would have caught F9 at the moment it was introduced. The same check applied to the emitted
  CA JSON catches F20.
- **Worked-example reproducibility** (F9) — the worked examples are declared ground truth
  (`agents/shared/CLAUDE.md`) but nothing re-runs them, which is why a live-verified output could
  silently stop being reproducible. A smoke test that re-runs each snowflake worked example's DDL
  through `parse-sv → translate-formulas → build-model` and diffs the formulas block against the
  documented output would have failed on 2026-07-22.

### 3.10 Scope limits on these results

- **No live verification anywhere.** No ThoughtSpot import, no Snowflake execution — the plan's
  constraint. So F9's import behaviour (rejection vs silently-broken measure), F12's numeric
  magnitude, F15's effect on Cortex Analyst date handling, and F21's `using_relationships`
  resolution are all **reasoned from documented semantics, not measured**. Each is flagged in
  place above. Confirming them needs the parked conversion-fidelity angle (audit angle 15).
- **The DDL is a re-serialisation, not a `GET_DDL` capture.** §3.2 documents the one construction
  choice that affects a verdict (metric table-scoping, F21). A real `GET_DDL` from a deployed
  view could differ in whitespace, clause order, or CA-JSON content; the *constructs* would not.
- **BL-171 was not exercised, again.** The fixture's only string operation is `||`, which is a
  separate defect (F11). `trim`/`ltrim`/`rtrim`/`replace`/`starts_with`/`ends_with` are untouched
  by either §2 or §3, so BL-171 remains open and untested by this exercise. The `sv_sql.py:206-208`
  bare-name emission noted in the task brief was likewise not reached — no metric or dimension in
  this fixture routes through it.
- **Upstream's own losses are excluded from the denominators** (§3.1) and are not charged to our
  converter. Where upstream already dropped a construct — model `ai_context`, relationship
  synonyms, `custom_extensions`, metric `datatype` — the referee cannot adjudicate our handling
  of it, because it never reached us.
- **These figures describe a plain 5-table star.** 4 single-column equi-joins, 26 direct column
  dimensions, 1 computed dimension, 5 passthrough facts, 5 simple-to-moderate metrics. Every
  construct class most likely to be mis-inferred — semi-additive, window, LOD, metric-on-metric,
  range/ASOF joins, composite relationship columns, subquery logical tables, `PRIVATE`, filter
  labels, verified queries — is absent (§3.1). Do not read 10/47 as a general fidelity rate in
  either direction: the sample is easy, and it still lost every measure.

### 3.11 Workspace artifacts

All under `.superpowers/sdd/2026-07-29-ossie-tpcds-fidelity/sf/` (gitignored):

| File | Contents |
|---|---|
| `00-upstream-regenerated.yaml` | upstream converter re-run over the OSI example (proves fixture provenance, §3.1) |
| `01-fixture-checked-in.yaml`, `02-osi-source.yaml` | verbatim copies of the two upstream fixtures |
| `mk_ddl.py`, `03-sv_ddl.sql` | Cortex YAML → `CREATE SEMANTIC VIEW` DDL re-serialiser and its output (§3.2) |
| `04-parsed.json` | `ts snowflake parse-sv` output |
| `05-translated.json` | `ts snowflake translate-formulas` output (records the F11 skip) |
| `06-tables.json` | SV alias → ThoughtSpot table map (Step 8) |
| `tml_out/Tpcds Retail Model.model.tml` | our Model TML — the forward leg's output |
| `mk_reverse_inputs.py`, `07-model-export.json`, `08-tables-export/` | `build-sv`'s two documented inputs (stand-in for `ts tml export --parse`) |
| `09-regenerated-sv.sql` | regenerated SV DDL, **as-is** — the artifact §3.4 scores |
| `10-model-export-corrected.json`, `11-formulas.json`, `12-regenerated-sv-corrected.sql` | corrected variant isolating F12/F20/F21 from F9's cascade |
| `compare.py`, `13-comparison.txt` | construct inventory, name-fate tally, formula-integrity check |
| `tally.py`, `14-tally.txt` | property-level fate tally (the 215 denominators and every verdict) |
| `probe/computed_fact.sql`, `probe/out/` | minimal probe isolating F9's second defect half (computed fact + synonyms) |
| `probe/workforce.sql`, `probe/wout/` | the live-verified worked example's own DDL re-run through today's CLI — F9's regression evidence |

---

## 4. Findings and routing

_(filled by Task 3)_
