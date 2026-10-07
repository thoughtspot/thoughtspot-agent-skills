---
name: ts-link-semantic-layer
description: Link a semantic-layer object (Snowflake Semantic View, Databricks Metric View, Honeydew, Cube, Kyvos) into ThoughtSpot for direct query, WITHOUT converting it. Creates one Table over the semantic object and a thin Model that references only that Table (no joins, no formulas), carrying column roles, measure aggregation, descriptions, synonyms, ai_context and Spotter instructions, so the platform generates the SQL from its own definitions. Use when someone wants ThoughtSpot or Spotter to query a semantic view / metric view / semantic model as-is, "Semantic SQL", "link", "register", or "query the semantic layer directly". Not for translating the semantics into ThoughtSpot joins and formulas; that is the ts-convert-from-* skills.
---

# ThoughtSpot: Link a Semantic Layer

The `ts-convert-from-*` skills **translate** a semantic object into ThoughtSpot joins and
formulas. This skill does the opposite: it leaves the semantics where they are. ThoughtSpot
gets a Table pointing at the semantic object itself and a Model over that one Table. When a
user searches, ThoughtSpot sends the platform a query against the semantic object, and the
platform's own metric definitions produce the SQL.

That means constructs a converter cannot translate — window measures, subqueries,
semi-additive snapshots, platform-specific functions — work unchanged, because nothing is
translated. Verified 2026-09-28 on a Databricks Metric View: a prior-year window measure the
converter rejects returned correct values.

What the skill creates:

| Object | Contents |
|---|---|
| Table | `connection` / `db` / `schema` / `db_table` = the semantic object; one column per dimension and measure |
| Model | References only that Table; no joins, no formulas; Spotter enabled |

Metadata carried: column descriptions, synonyms, `ai_context` (where the source has it),
the object description, and Spotter instructions (via the API — TML does not persist them).

**Creates new objects only.** Re-linking an object that is already registered, and keeping
or discarding edits made in ThoughtSpot, is not supported yet (BL-318).

---

## Prerequisites

- A ThoughtSpot profile — [ts-profile-thoughtspot](../ts-profile-thoughtspot/SKILL.md).
- A ThoughtSpot **connection** to the platform, in the target Org, whose user can see the
  semantic object.
- Read access to the semantic object's metadata on the platform (a warehouse profile —
  [ts-profile-snowflake](../../claude/ts-profile-snowflake/SKILL.md),
  [ts-profile-databricks](../ts-profile-databricks/SKILL.md) — or an export the user provides).
- `CAN_USE_SPOTTER` plus edit access on the Model to write Spotter instructions. Without it
  the objects are still created; the summary reports the instructions as not set.

---

## Step 1: Identify the object, connection and Org

Ask for (skip any the user already gave):

1. The semantic object's fully qualified name (`catalog.schema.object`).
2. The ThoughtSpot profile, and the **Org** to create it in. Orgs are selected with the
   `TS_ORG` environment variable (Org id or name):
   `ts orgs search --profile {profile}` lists them.
3. The ThoughtSpot connection name:
   `TS_ORG={org} ts connections list --profile {profile}`.
4. The Model name. Suggest `Semantic SQL - {Object Name}`.

---

## Step 2: Check it is not already linked

ThoughtSpot matches a Table on `connection` + `db` + `schema` + `db_table`, **not** on its
name, and refuses to create a second one (live-verified 2026-09-28). Check first:

```bash
TS_ORG={org} ts metadata search --subtype ONE_TO_ONE_LOGICAL --name "%{object_name}%" --profile {profile}
```

Also look for a Table whose `db_table` is the object name under a different ThoughtSpot name
(an earlier link made with `--table-name`): export any candidate and compare `db`, `schema` and
`db_table`. If a Table over the same object exists, stop and tell the user: this skill does not
update an existing link yet (BL-318). They can delete the old Table and Model first, or use a
different Org. A match the search misses is still caught at import — the command stops before
creating anything and returns `existing_table_guid`.

---

## Step 3: Choose the aggregation mode

One switch, not per-platform logic. Ask the user which way the platform expects measures
to be queried, recommending the default for their platform:

| Mode | Every measure gets | Use for |
|---|---|---|
| `aggregate` | `aggregation: AGGREGATE` — ThoughtSpot wraps the column in the platform's measure function (`MEASURE(col)` on Databricks) | Snowflake Semantic View, Databricks Metric View |
| `standard` | Its logical aggregation — `SUM`, `COUNT_DISTINCT`, `AVERAGE`, `MIN`, `MAX`, … | Honeydew, and any platform that expects a standard aggregate over the metric |

In `standard` mode each measure's aggregation comes from the spec's `aggregation` field, or
is inferred from the outermost function of its `expr` (`SUM(x)` → SUM,
`COUNT(DISTINCT x)` → COUNT_DISTINCT, `SUM(x) FILTER (WHERE …)` → SUM). A compound
expression (`SUM(a) / SUM(b)`) has no single honest answer, so the build **fails and lists
those measures** rather than guess. Resolve them with the user: give each an explicit
`aggregation`, or pass `--default-aggregation`.

`COUNT_DISTINCT` on a physical column is documented to be coerced to ATTRIBUTE on import
([open item #4](references/open-items.md)); the build emits a warning for each one, and the
post-import `coerced` check reports it if it happens.

For Cube and Kyvos, ask the user — which mode they accept is not yet established
([open item #3](references/open-items.md)).

**Facts are outside the mode.** A Snowflake Semantic View `FACT` is a row-level expression
with no aggregation of its own (`GROSS_PROFIT AS gross - costs`). Snowflake rejects `AGG()` on
a fact (*Unsupported feature 'AGG'*) but runs any standard aggregate, so a `kind: fact`
column is **never** `AGGREGATE`: it gets its declared `aggregation` (the view's
`default_aggregation`), or `SUM`, in either mode. A non-numeric fact becomes an attribute.
Marking a fact `AGGREGATE` breaks every search that touches it — ThoughtSpot even rewrites an
explicit `SUM`/`AVG` to `AGG()` ([open item #6](references/open-items.md)).

---

## Step 4: Build the spec

The command takes one normalized JSON spec, whatever the platform. Assemble it from the
platform's metadata:

```json
{
  "connection": "TS-DBX",
  "db": "agent_skills", "schema": "business_forecast", "db_table": "business_reporting_mv",
  "description": "Object-level description",
  "instructions": "Spotter guidance, if the source has any",
  "columns": [
    {"name": "region", "data_type": "string", "kind": "attribute",
     "description": "…", "synonyms": ["area"]},
    {"name": "revenue", "data_type": "decimal(28,2)", "kind": "measure",
     "expr": "SUM(amount)", "description": "…", "ai_context": "…"},
    {"name": "gross_profit", "data_type": "NUMBER(11,2)", "kind": "fact",
     "aggregation": "avg"}
  ]
}
```

| Field | Required | Notes |
|---|---|---|
| `name` | yes | The column name **as the platform exposes it when queried** — becomes `db_column_name` |
| `data_type` | yes | Platform type (`decimal(28,2)`, `VARCHAR(16777216)`, `timestamp_ltz`) or a ThoughtSpot type |
| `kind` | yes | `measure`, `fact` or `attribute` (`dimension` is accepted as `attribute`). `fact` is a Snowflake Semantic View FACT — see Step 3 |
| `description` | no | Carried to the Table and Model column |
| `synonyms`, `ai_context` | no | Carried to the Model column (a string `synonyms` is one synonym) |
| `display_name` | no | Model column name; otherwise humanized (`revenue_gbp` → `Revenue GBP`) |
| `aggregation`, `expr` | standard mode | See Step 3 |
| `aggregation` | facts, when declared | The fact's `default_aggregation`; omit for `SUM`. `AGGREGATE` is refused |

Where the metadata lives:

| Platform | Source of the spec |
|---|---|
| **Databricks Metric View** | `DESCRIBE TABLE EXTENDED {fqn} AS JSON`: `columns[]` gives each column's type (append `(precision,scale)` for decimals); `view_text` is the YAML, whose `dimensions[]` / `measures[]` give `kind`, `expr`, `comment` → `description`, `synonyms`, `display_name`; top-level `comment` → `description`. Verified 2026-09-28 |
| **Snowflake Semantic View** | `DESCRIBE SEMANTIC VIEW {fqn}`: one row per property. `object_kind` DIMENSION → attribute, METRIC → measure, **FACT → fact**; `object_name` → `name`; properties `DATA_TYPE`, `EXPRESSION`, `COMMENT`, `SYNONYMS` (a JSON array string); the row with no `object_kind` and property `COMMENT` → object `description`. Verified 2026-09-28: output matched a hand-built Table on all 31 columns. **A fact's `default_aggregation` is not in `DESCRIBE`** — it lives only in the Cortex Analyst extension. Read it from `SELECT SYSTEM$READ_YAML_FROM_SEMANTIC_VIEW('{fqn}')` (`tables[].facts[].default_aggregation`) and put it in the fact's `aggregation`. Snowflake's SQL ignores it, but copying it keeps ThoughtSpot's default answer the same as Cortex Analyst's. Verified 2026-10-05 |
| **Honeydew, Cube, Kyvos** | Ask the user for the object's metric and attribute list (names as queried, types, descriptions, and each metric's aggregation). [Open item #2](references/open-items.md) |

Only include what the source actually has. Do not invent descriptions or synonyms. If the
object-level comment contains guidance for query behaviour (defaults, "use X for Y"),
confirm with the user and put that part in `instructions`.

Write the spec to a working directory, e.g. `./link/{object_name}/spec.json`.

---

## Step 5: Dry run and review

```bash
ts link build --spec spec.json --aggregation {mode} --model-name "{model_name}" \
  --output-dir ./link/{object_name} --dry-run
```

Show the user the summary: attribute, measure and fact counts, how aggregations were decided
(`aggregation_source`: `fact-default` = SUM because none was declared),
how many columns carry synonyms / descriptions / ai_context, and **every skipped column**.

**Non-numeric measures are skipped.** ThoughtSpot rejects a non-numeric MEASURE and silently
turns it into an ATTRIBUTE, which then queries the platform's measure without its measure
function, and the platform refuses the query (verified on Databricks: a `MAX(date)` measure
failed with `METRIC_VIEW_MISSING_MEASURE_FUNCTION` every way it was queried). If the user
needs such a value, the fix is at source: a numeric twin (e.g. a `yyyymmdd` integer).

Options: `--naming raw` keeps source names; `--table-name` sets the Table name (default: the
object name); `--no-spotter` disables Spotter.

---

## Step 6: Create

After the user confirms:

```bash
TS_ORG={org} ts link build --spec spec.json --aggregation {mode} --model-name "{model_name}" \
  --output-dir ./link/{object_name} --profile {profile}
```

The command imports the Table, points the Model at its GUID, imports the Model, writes the
Spotter instructions via `ai/instructions/set`, then re-exports the Model and compares each
column's role and aggregation with what it sent. JSON summary on stdout:

| Field | Meaning |
|---|---|
| `table_guid`, `model_guid` | The created objects |
| `instructions_result` | `{"set": true}`, or the HTTP status and error. A failure here does not undo the link |
| `coerced` | Columns whose `column_type` or `aggregation` ThoughtSpot changed on import. Should be `[]` — report any entry to the user |
| `existing_table_guid` | Present when the object was already linked (Step 2 missed it); nothing was created |
| `warnings` | Pre-import advisories (e.g. COUNT_DISTINCT measures) |
| `error` | Present on failure. If `table_guid` is also present, the Table was created and remains |

**Editing a linked Model later:** change a measure's aggregation on the **Table** too. AgentQL/SpotQL reads the Table's aggregation (UI search reads the Model's), so a Model-only change to `AGGREGATE` leaves every AgentQL query on it failing. `ts tml lint --file table.tml --file model.tml` flags it (I16; [open item #8](references/open-items.md)).

If the Model import fails, the Table has already been created: the summary still carries
`table_guid` alongside `error`. Fix the cause and delete the Table
(`TS_ORG={org} ts metadata delete {table_guid} --profile {profile}`) before retrying.

---

## Step 7: Verify with a query

Run one query through the new Model — a dimension and a measure:

```bash
TS_ORG={org} ts agentql fetch-data \
  'SELECT "{Dimension}", AGG("{Measure}") AS m FROM "{model_name}" AS "t1" GROUP BY "{Dimension}"' \
  -m {model_guid} --profile {profile}
```

**Do not mix `AGG()` with `SUM`/`AVG`/`COUNT` in one query** — on a linked model that query
shape is planned as two levels that group by the metric, and the platform rejects it
([open item #7](references/open-items.md)). Verify a fact separately, with `SUM("{Fact}")`.

`status: SUCCESS` with rows means the platform accepted ThoughtSpot's SQL. To check the
numbers, run the equivalent query on the platform directly and compare. See
[ts-object-model-agentql-query](../ts-object-model-agentql-query/SKILL.md) for more.

---

## Step 8: Report

Tell the user: the Table and Model names and GUIDs (with the Org), the counts, the skipped
columns and why, the instructions outcome, any `coerced` entries, and the query result.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.1.2 | 2026-10-07 | Notes that AgentQL/SpotQL reads a measure's aggregation from the **Table**, not the Model, so a hand-edit must change both; `ts tml lint` I16 flags the mismatch (ts-cli 0.168.0). Open item #8 |
| 1.1.1 | 2026-10-06 | Model column names from an all-upper-case source name (Snowflake's default) read `Gross Profit`, not `GROSS PROFIT`; mixed-case names keep their casing. ts-cli 0.155.0 |
| 1.1.0 | 2026-10-06 | Snowflake Semantic View **facts**: new spec `kind: fact`, never `AGGREGATE` (Snowflake rejects `AGG()` on a fact); takes the view's `default_aggregation` from the YAML export, else `SUM`; non-numeric facts become attributes. Documents the SpotQL mixed-aggregate planner bug (open item #7). Requires ts-cli 0.154.0 |
| 1.0.0 | 2026-09-28 | Initial release: `ts link build` creates a Table over a semantic object plus a thin, formula-free Model; one aggregation switch (`aggregate` / `standard`) instead of per-platform adapters; skips non-numeric measures; writes Spotter instructions via the API; re-exports to catch silent role coercion |
