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

**Remaining:** Test 4-way parallel to confirm no 429 or connection pooling issues.

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
### #1 — Bulk metadata search performance — UNVERIFIED

Large instances may have 1000+ models and 2000+ answers. The `ts metadata search --all`
command auto-paginates, but we need to verify:
- Latency ceiling for a full scan
- Whether the API throttles or returns partial results on very large instances
- Memory footprint of holding all metadata in memory

**Test:** Run `ts metadata search --subtype WORKSHEET --all` on an instance with 100+ models
and measure elapsed time and response completeness.

---

### #2 — Bulk TML export throttling — UNVERIFIED

Step 4 exports TML at 4-way parallel concurrency. Need to verify:
- Does the ThoughtSpot API throttle or 429 on concurrent TML exports?
- What is the latency per export on a typical model (10-50 columns)?
- Does `--associated` significantly increase export time?

**Test:** Export 50+ model TMLs at 4-way concurrency and check for failures or slowdowns.

---

### #3 — Dependent counts for orphan detection — UNVERIFIED

Step 5 uses `ts metadata dependents` to detect orphan models (H4) and sets (H5).
Need to verify:
- Does the dependents API return empty results (not errors) for objects with no dependents?
- Can we batch this, or must it be one call per object?
- What is the response shape when there are zero dependents?

**Test:** Call `ts metadata dependents` on a model known to have zero downstream objects.

---

### #4 — is_bypass_rls in exported TML — UNVERIFIED

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

### #7 — Column Level Security in TML export — UNVERIFIED

S3 depends on detecting Column Level Security rules. CLS is not in standard TML
export. A Beta flag `export_column_security_rules` reportedly exists.

**Test:** Export a model with CLS configured using `ts tml export --export-column-security-rules`
(or equivalent flag) and check if CLS rules appear. If the flag doesn't exist, S3 falls
back to the masking-formula heuristic.

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
### #8 — NL Instructions API — UNVERIFIED

A3 partially depends on detecting NL Instructions set via the REST API
(`POST /api/rest/2.0/ai/instructions/get`). Confirmed via MCP as Beta since
10.15.0.cl. Requires `CAN_USE_SPOTTER` + `SPOTTER_COACHING_PRIVILEGE`.

**Test:** Call `ai/instructions/get` for a model with Spotter instructions configured.
Verify response shape and whether it returns instructions set via the UI.

Note: A3 works without this — `data_model_instructions` in TML (verified in #5)
covers the TML path. This API would add coverage for instructions set only via the UI.

---

## Phase 2 — Usage Analysis (future)

### #9 — searchdata against BI Server — UNVERIFIED

Need to verify `POST /api/rest/2.0/searchdata` works with the BI Server system model:
- Does it accept the BI Server model GUID as `logical_table_identifier`?
- What is the maximum `record_size`? Does pagination work?

### #10 — BI Server Spotter coverage — UNVERIFIED

Does the TS: BI Server system model capture Spotter/AI search interactions,
or only classic Search interactions?

### #11 — User Action enum — UNVERIFIED

Full `User Action` values in BI Server? Need the enum to filter appropriately.

### #12 — Query Text column parsability — UNVERIFIED

Does `[Query Text]` contain `[column_name]` tokens parseable for column-level
usage analysis?

---

## Phase 3 — Visualization Layer (future)

### #13 — Liveboard viz fingerprinting — UNVERIFIED

Can two liveboards with the same visualizations be reliably detected by comparing
`search_query` strings in their viz definitions?
