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

_(filled by Task 2)_

---

## 4. Findings and routing

_(filled by Task 3)_
