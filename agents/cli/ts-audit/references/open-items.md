# Open Items — ts-audit

Verification items to test against a live ThoughtSpot instance before each phase ships.

---

## Phase 1 — A/D/H/P/S angles

### #1 — Bulk metadata search performance — VERIFIED

Tested on champ-staging (2026-06-18). `ts metadata search --subtype WORKSHEET --all`
returned **1855 models in 3 minutes 5 seconds**. No throttling, no partial results —
full result set returned. Auto-pagination works correctly.

**Implication:** For a large instance the enumeration step takes ~3 minutes. The audit
should show a progress indicator and warn the user before starting. Caching the
metadata response (keyed by profile + date) could avoid re-enumerating on subsequent
runs the same day.

---

### #2 — Bulk TML export timing — VERIFIED (sequential only)

Tested on champ-staging (2026-06-18). Sequential export of 8 models:
- Average: 2.9s per model
- Range: 1.8s – 4.6s
- No failures, no throttling at sequential pace

**Projected at 4-way parallel:** 1855 models × 3s / 4 workers ≈ 23 minutes.
The caching layer (Step 4) is essential — subsequent runs only re-export changed
objects. 4-way concurrent throttling NOT yet tested (needs a parallel harness).

**Closed 2026-11-18:** the 4-way parallel test is obsolete. The audit sends its exports
one request at a time, up to 50 objects each (`context._export_items`). It starts no
thread or process: a grep for thread pools, `threading`, `asyncio` and
`multiprocessing` under `ts_cli/audit` finds none. So concurrent exports never happen.

---

### #3 — Dependent counts for orphan detection — VERIFIED

Tested on champ-staging (2026-06-18) against GTM model
(`54beb173-d755-42e0-8f73-4d4ec768114f`).

Response is a list of typed dependent objects:
```
LIVEBOARD: 36, ANSWER: 14, FEEDBACK: 8, LOGICAL_TABLE: 1
```

Empty list = orphan. One call per object (no batch endpoint). The `type` field
distinguishes dependent types for H4 (model orphans) and H5 (set orphans).
Sets appear as type `COHORT` in the dependents of their parent model.

---

### #4 — is_bypass_rls in exported TML — VERIFIED

Tested on champ-staging (2026-06-18). `is_bypass_rls` IS present in exported TML
at `model.properties.is_bypass_rls` (boolean). GTM model value: `false`.

Also confirmed `spotter_config` is nested inside `properties`:
```yaml
properties:
  is_bypass_rls: false
  join_progressive: true
  spotter_config:
    is_spotter_enabled: true
```

S4, S10, D4, and P11 can all read from `model.properties` directly.
### #1 — Bulk metadata search performance — RESOLVED (a duplicate: the VERIFIED #1 above answers it; kept as the original question)

Large instances may have 1000+ models and 2000+ answers. The `ts metadata search --all`
command auto-paginates, but we need to verify:
- Latency ceiling for a full scan
- Whether the API throttles or returns partial results on very large instances
- Memory footprint of holding all metadata in memory

**Test:** Run `ts metadata search --subtype WORKSHEET --all` on an instance with 100+ models
and measure elapsed time and response completeness.

---

### #2 — Bulk TML export throttling — RESOLVED (obsolete: the audit does not export concurrently; kept as the original question)

**Obsolete (2026-11-18).** The question assumed exports at 4-way concurrency. The audit
sends them one request at a time (`context._export_items`) and starts no thread or
process, so concurrent-export throttling cannot arise. The VERIFIED #2 above measured
sequential export only, so it did not answer this question either.

Step 4 exports TML at 4-way parallel concurrency. Need to verify:
- Does the ThoughtSpot API throttle or 429 on concurrent TML exports?
- What is the latency per export on a typical model (10-50 columns)?
- Does `--associated` significantly increase export time?

**Test:** Export 50+ model TMLs at 4-way concurrency and check for failures or slowdowns.

---

### #3 — Dependent counts for orphan detection — RESOLVED (a duplicate: the VERIFIED #3 above answers it; kept as the original question)

Step 5 uses `ts metadata dependents` to detect orphan models (H4) and sets (H5).
Need to verify:
- Does the dependents API return empty results (not errors) for objects with no dependents?
- Can we batch this, or must it be one call per object?
- What is the response shape when there are zero dependents?

**Test:** Call `ts metadata dependents` on a model known to have zero downstream objects.

---

### #4 — is_bypass_rls in exported TML — RESOLVED (a duplicate: the VERIFIED #4 above answers it; kept as the original question)

S4 and S10 need `is_bypass_rls` from the model TML. Need to verify:
- Does `is_bypass_rls` appear in `ts tml export` output?
- Or is it only available in the `ts metadata search --include-details` response?
- If not in TML, we need an alternative approach.

**Test:** Export a model TML where `is_bypass_rls` is set and check if the field appears.

---

### #5 — Data Model Instructions in TML — VERIFIED

Confirmed at `model.model_instructions.data_model_instructions` in exported TML.
A3 check can use this field directly.

---

### #6 — constant_folding TML property — UNVERIFIABLE

User reported `constant_folding` as a TML property for column-picker formulas
(IF parameter patterns like `if([pColumn] = 'amount') then [amount] else [quantity]`).
Searched MCP docs and live TML exports — **property does not exist**.

If no TML property exists, column-picker formula detection cannot verify whether
constant folding is enabled. The pattern CAN still be detected (IF + parameter +
column references), but the optimisation flag cannot be checked via TML.

**Status:** Parked — revisit if a TML or API surface for this setting is discovered.

---

### #7 — Column Level Security in TML export — SPEC-VERIFIED via MCP 2026-07-22

MCP `exportMetadataTML` spec confirms `export_column_security_rules` exists as a boolean
in `export_options` (Beta, requires 10.12.0.cl+, must be used with `export_associated: true`).
Additionally, dedicated endpoints exist: `fetchColumnSecurityRules`
(`POST /api/rest/2.0/security/column/rules/fetch`) and `updateColumnSecurityRules`, both
Beta 10.12.0.cl+. The fetch endpoint returns per-column rules with group IDs and source
table details.

**Remaining:** Live-verify the TML shape returned when the flag is set, and wire the
`--export-column-security-rules` flag into `ts tml export`.

---

### #8 — NL Instructions API — VERIFIED

Tested on champ-staging (2026-06-18). `POST /api/rest/2.0/ai/instructions/get` works.

**Correct parameter name:** `data_source_identifier` (NOT `metadata_identifier` — the
MCP listing was wrong / out of date).

Response shape:
```json
{
  "nl_instructions_info": [
    {
      "instructions": [
        "\"ACV\" = Opportunity ACV (not Opportunity Software ACV).",
        "Default date range: current quarter using Opportunity Close Date...",
        "Sort results by the measure column descending unless specified otherwise."
      ],
      "scope": "GLOBAL"
    }
  ]
}
```

A3 can now check both TML path (`data_model_instructions`) and API path
(`ai/instructions/get`) for full NL instruction coverage. Instructions set via the
UI appear in the API response. `scope: GLOBAL` applies to all searches on this model.
### #8 — NL Instructions API — RESOLVED (a duplicate: the VERIFIED #8 above answers it; kept as the original question)

A3 partially depends on detecting NL Instructions set via the REST API
(`POST /api/rest/2.0/ai/instructions/get`). Confirmed via MCP as Beta since
10.15.0.cl. Requires `CAN_USE_SPOTTER` + `SPOTTER_COACHING_PRIVILEGE`.

**Test:** Call `ai/instructions/get` for a model with Spotter instructions configured.
Verify response shape and whether it returns instructions set via the UI.

Note: A3 works without this — `data_model_instructions` in TML (verified in #5)
covers the TML path. This API would add coverage for instructions set only via the UI.

---

## Phase 2 — Usage Analysis (future)

### #9 — searchdata against BI Server — DEFERRED to BL-081 (usage stats)

Need to verify `POST /api/rest/2.0/searchdata` works with the BI Server system model:
- Does it accept the BI Server model GUID as `logical_table_identifier`?
- What is the maximum `record_size`? Does pagination work?

### #10 — BI Server Spotter coverage — DEFERRED to BL-081 (usage stats)

Does the TS: BI Server system model capture Spotter/AI search interactions,
or only classic Search interactions?

### #11 — User Action enum — DEFERRED to BL-081 (usage stats)

Full `User Action` values in BI Server? Need the enum to filter appropriately.

### #12 — Query Text column parsability — DEFERRED to BL-081 (usage stats)

Does `[Query Text]` contain `[column_name]` tokens parseable for column-level
usage analysis?

---

### #14 — Large cluster timeout on full metadata scan — VERIFIED 2026-07-01

On champ-staging (91 GTM models, ~1855+ total objects), the original `build_context`
metadata scan (`metadata/search` with `{"type": "LOGICAL_TABLE"}` and no identifier
filter) timed out at 60s. The scan was paginating through ALL logical tables in the
cluster — unnecessary when auditing a scoped set of models.

**Fix applied:** Scoped the metadata search to only the model GUIDs + their associated
table GUIDs (extracted from the TML export). Batched in groups of 50. Also bumped
timeout to 300s on TML export and dependents calls for large model counts.

**SKILL.md review needed:** The skill doesn't mention performance considerations for
large clusters. Should document:
- Expected timing for 50+ model audits
- The scoped vs full-cluster metadata scan tradeoff (D8 duplicate detection is
  limited to tables referenced by audited models, not cluster-wide)
- Timeout behaviour and how to handle staging clusters with thousands of objects

---

### #15 — Bulk dependents fetch truncation — FIXED 2026-07-01

The `build_context` dependents fetch sent all model+table GUIDs (282 for champ-staging)
in a single `metadata/search` request with `include_dependent_objects: True`. At scale,
the API response appears to truncate dependent objects for some items silently — GTM
Partners (confirmed to have 2 LIVEBOARD dependents via individual
`ts metadata dependents` call) returned zero dependents in the bulk response.

**Fix applied:** Batched dependents queries in groups of 25 GUIDs instead of one bulk
request. This matches the pattern used by the scoped metadata scan (batched at 50) and
reduces the chance of response truncation.

**Impact:** H4 (orphan model detection) produced false positives when the bulk response
omitted dependent objects. Needs re-verification on next audit run.

---

### #16 — Custom calendar search pages, and `record_size: -1` returns none — VERIFIED 2026-11-18

Live-probed, read-only, on the SE demo cluster on 2026-11-18, for P22, which reads the
custom calendars registered on each connection. `POST /api/rest/2.0/calendars/search`:

| Request body | Answer |
|---|---|
| `{}` | The first 10 calendars only (the default page size is 10) |
| `{"record_size": 100}` | 57 calendars on 22 connections: all of them |
| `{"record_size": -1}` | **None at all.** -1 is not "all" here, as it is on `metadata/search` |
| `{"record_offset": 10, "record_size": 10}` | The next 10 |
| Pages of 25 from offset 0 until a short page | All 57 |
| `{"connection_identifier": <connection id>}` | That connection's calendars only |

Each item is `{calendar_id, calendar_name, connection_id, connection_name,
data_warehouse_type, author_name, modification_time_in_millis}`, all strings.

**What changed (ts-cli 0.219.0, ts-audit 3.23.0).** `ts calendar search` sent no
`record_size`, so it listed at most 10 calendars. It now pages 100 at a time until a
page comes back short. The audit's `calendars` fetch (for P22 and the Data Cache view)
shares that paging (`ts_cli/custom_calendar/search.py`), once per audit, and keeps only
the four ids and names it reads. It matches a calendar to a Model's Tables by
connection name, any case, and by connection id where a Table's metadata header
carries `dataSourceId`.

**Checked 2026-11-18, the SE demo cluster:** none of 93 Table metadata headers in a 20-Model
snapshot carries `dataSourceId` (73 carry `dataSourceName`), so the name match is what
carries the rule; the id match stays for a build that adds the key. **Not verified:** what
that key would hold. And the paging guard against a server that ignores
`record_offset` (a repeated full page is an error) has met no such server.

---

### #17 — Connection search details, and how P23 and P24 read a connection — VERIFIED 2026-11-18

Live-probed, read-only, on the SE demo cluster on 2026-11-18, for P23 and P24.

`POST /api/rest/2.0/connection/search` with `{"record_size": 200, "record_offset": 0,
"include_details": true}` answered 200 connections, so the audit pages it as it pages
the calendar search (until a short page, 100 at a time). Each item is `{id, name,
data_warehouse_type, details: {type, configuration, ...}}`:

- `details.configuration` is a **JSON string** of the connection's settings,
  credentials included. They were masked (`******`) in what the probe saw; the audit
  does not rely on that. It parses the string in the fetch, keeps
  `{id, name, type, oauth, oauth_m2m, privatelink, parameterized}` and drops the rest, so no
  configuration value is stored, logged, snapshotted or reported
  (`audit/connection_facts.py`; a test checks the context, the snapshot, the audit
  JSON, the report and the logs).
- **There is no auth-type field.** OAuth shows only in setting names: `OAuth2ClientId`
  and `OAuth2Secret` (Snowflake OAuth), `oauth_pvt_key`, and `client_id` with
  `client_secret` on a Databricks connection (an OAuth M2M service principal). So P24
  is evidence `heuristic`.
- **No setting names PrivateLink.** P24 reads it from the `host` or `accountName`
  value: a Snowflake PrivateLink URL carries `.privatelink.`. The value is read to
  derive the flag and not kept.
- A template variable is a setting whose whole value is a `${var}` token. **Checked
  2026-11-18, read-only: the search does not show one.** None of the 1,815 connections
  it returned held a token. One connection's metadata header carries
  `parameterizedConnection: true`, and its connection TML holds a `${var}` token in each
  of its six properties, but the search returned none of them as a token. So P24
  cannot see a parameterized connection this way; the header flag is the signal
  (BL-595). Only key names and counts were read; no value was printed or kept.

The Table metadata headers carry `dataSourceType`: `RDBMS_SNOWFLAKE` on 73 of 92 headers
in the sample (Model headers carry none). P23 reads the connection's
`data_warehouse_type` first, and the header's type when the connection gives none.

**Checked 2026-11-18, read-only, with `ts metadata search` on the SE demo cluster.**
Both points this item first left open now hold:

- **`RDBMS_DATABRICKS` is Databricks' `dataSourceType`.** Of 13,162 Table headers, 149
  carry it: every Table on the cluster's 14 Databricks connections. One of them, fetched
  by id in the request shape the audit's header fetch uses, carries it too. The other
  values seen were `RDBMS_SNOWFLAKE` (12,549), `RDBMS_MODE` (394), `RDBMS_GCP_BIGQUERY`
  (24), `RDBMS_POSTGRES` (18), `DEFAULT` (13), `RDBMS_REDSHIFT` (11),
  `RDBMS_GCP_POSTGRESQL` (3) and `RDBMS_SQLSERVER` (1). P23 reads each of those as a
  source Data Cache does not serve.
- **A SQL View's header `type` is `SQL_VIEW`.** Five SQL Views sampled, and one fetched
  by id in the audit's request shape, all carry it. The audit keeps no SQL View TML
  (only `table` documents), and until 3.23.0 it fetched no header for a SQL View either,
  so P1 and D8 could not see one a Model used. P27 reads the header, and falls back to
  the row's `metadata_subtype`, as `migrate/discover.py` does.

What P28 counts as a function in an RLS rule, a null test included, is #18's point 3:
the product owner confirmed it.

---

### #18 — Data Cache: what the product team is to confirm — DEFERRED to BL-590

Until the team answers, P24 is graded as a heuristic and its findings say "to confirm" where they rest on point 1 or 2.
A Model whose only Data Cache reasons rest on those two reads To confirm, not Can't use.

The product owner raised points 1 to 3 on 2026-11-18 and asked for them to be flagged
for the team. Points 4 to 6 came from the review of the rules the same day, and point 7
from re-running the sample after it. Each is what P19, P21, P23, P24 or P28 reads today.
A P24 finding says "to confirm" where it rests on point 1 or 2.

1. **OAuth M2M.** P24 reads a connection as OAuth when a configuration key contains
   `oauth`, or, without one, when it has both `client_id` and `client_secret` (a
   Databricks OAuth M2M service principal). Does Data Cache treat that M2M connection as
   an OAuth connection? The finding names it "OAuth M2M, to confirm".
2. **PrivateLink.** No configuration key names PrivateLink, so P24 reads it from a
   `host` or `accountName` containing `privatelink`. Is that a sound signal on every
   source Data Cache supports? The finding names it "PrivateLink read from the host, to
   confirm".
3. **A null test in an RLS rule.** The product owner confirmed (2026-11-18) that any
   function in an RLS rule's formula stops Data Cache, `isnull` included. S12 advises a
   null test so an outer join keeps its unmatched rows, so the two rules meet: the team
   is to decide how customers should weigh keeping the rows against caching. Both S12's
   and P28's remediation now say so, and P28 names such a rule "a null test that keeps
   outer-join rows, see S12".
4. **The `= null` form of a null test.** S12 and S15 accept `[X] = null` as a null
   branch, as well as `isnull` and `is_null`. P28 reads only function calls, so a rule
   whose null test is `= null` does not fire it. Does that form stop Data Cache too? If
   so, P28 should read it the way S12 does. S12's remediation says it is to confirm.
5. **A custom calendar named in a formula.** A formula can pass a calendar to a date
   function, as in `start_of_week ( [d] , RetailCal )`. P19 reads only a column's
   `properties.calendar`, so it misses such a formula. Does a formula that names a custom
   calendar stop Data Cache? If so, P19 (or a new rule) should read formula arguments.
6. **Pre-aggregated measures beyond `AGGREGATE`.** P21 also fires on a Model column over
   a Table column with `aggregation: SUM` and `is_pre_aggregated_measure: true`. The
   product owner's rule named Models with `AGGREGATE` measures (semantic query Models).
   Is a Model with such a pre-aggregated SUM measure uncached too?
7. **A Model built on a View.** A Model source whose metadata header type is
   `AGGR_WORKSHEET` (a View) names no connection, so P23 cannot read a warehouse type
   for it, and the Model reads Not assessed. Two of the 19 Models in the 2026-11-18
   sample on the SE demo cluster do. Can Data Cache serve a Model built on a View?

## Phase 3 — Visualization Layer (future)

### #13 — Liveboard viz fingerprinting — DEFERRED to BL-591

Can two liveboards with the same visualizations be reliably detected by comparing
`search_query` strings in their viz definitions?
