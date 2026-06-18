# Open Items — ts-dependency-audit

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

S4, P10, D4, and P11 can all read from `model.properties` directly.

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
