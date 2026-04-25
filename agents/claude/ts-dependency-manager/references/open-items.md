# Open Items — ts-dependency-manager

Items that need verification against a live ThoughtSpot instance before the skill
is considered fully verified. Update each item with findings after testing.

Status legend: **CONFIRMED** (direction known, needs live verification) | **VERIFIED** (tested) | **OPEN** (unknown)

---

## #1 — Dependency API endpoint (Step 4) — VERIFIED on Cloud (v2)

**2026-04-25 test against se-thoughtspot (Cloud):** The v2 metadata search endpoint
**does** support dependents lookup via flags. This is the correct approach for Cloud
and replaces TML scanning.

### Verified endpoint (Cloud) — `POST /api/rest/2.0/metadata/search`

**Request:**

```http
POST /api/rest/2.0/metadata/search
Authorization: Bearer <token>
X-Requested-By: ThoughtSpot
Content-Type: application/json

{
  "metadata": [{"identifier": "<source_guid>", "type": "LOGICAL_TABLE"}],
  "include_dependent_objects": true,
  "dependent_object_version": "V2"
}
```

`type` may be `LOGICAL_TABLE` (works at table-level) or `LOGICAL_COLUMN` (works at
column-level — verified to return identical `dependents` structure for a column GUID).

**Response shape (verified):**

```json
[
  {
    "metadata_id":   "<source_guid>",
    "metadata_name": "DM_CUSTOMER",
    "metadata_type": "LOGICAL_TABLE",
    "dependent_objects": {
      "areInaccessibleDependentsReturned": false,
      "hasInaccessibleDependents":         false,
      "dependents": {
        "<source_guid>": {
          "QUESTION_ANSWER_BOOK": [ { "id": "...", "name": "...", "author": "...", ... } ],
          "PINBOARD_ANSWER_BOOK": [ ... ],
          "LOGICAL_TABLE":        [ ... ]
        }
      }
    }
  }
]
```

When the source has no dependents, `dependents.<source_guid>` is `{}` (empty object,
not missing). Response timing on se-thoughtspot: ~2 seconds per call vs. TML batch
scan which timed out after 5+ minutes on the same instance.

**Validation (2026-04-25):**

| Source GUID | Object | Dependents returned | Notes |
|---|---|---|---|
| `19b5d112-...` | DM_CUSTOMER (APJ_BIRD, new) | `{}` | Confirmed empty — table created 2026-03-17, nothing built on it yet |
| `5cd8e1bb-...` | DM_CUSTOMER (Power, older) | `LOGICAL_TABLE: 1, PINBOARD_ANSWER_BOOK: 1` | Returned "Dunder Mifflin - Decode" model and "Damian - Runtime Parameter" liveboard — confirms API correctly populates non-empty result |
| `8d625c60-...` | ZIPCODE column (LOGICAL_COLUMN) | `{}` | Column-level lookup also works |

### v1 endpoint — only on Software (on-prem)

`POST /tspublic/v1/dependency/listdependents` — returns 404 on Cloud (verified
2026-04-24 against se-thoughtspot) and nginx 500 on champagne-master staging
(2026-04-24). Keep documented as the on-prem fallback only.

Request format: `application/x-www-form-urlencoded` (NOT JSON)

```
type=LOGICAL_TABLE
id=["guid1","guid2"]
batchsize=-1
```

Supported `type` values: `LOGICAL_TABLE`, `LOGICAL_COLUMN`, `LOGICAL_RELATIONSHIP`,
`PHYSICAL_COLUMN`, `PHYSICAL_TABLE`. Required header: `X-Requested-By: ThoughtSpot`.
Response keyed by source GUID with the same `QUESTION_ANSWER_BOOK` /
`PINBOARD_ANSWER_BOOK` / `LOGICAL_TABLE` buckets as v2.

GET variants: `/tspublic/v1/dependency/logicaltable?id=["guid"]` and `/logicalcolumn`.

### Test script (verified working on Cloud)

```python
import requests, json
import urllib3; urllib3.disable_warnings()

resp = requests.post(
    f"{base_url}/api/rest/2.0/metadata/search",
    headers={
        "X-Requested-By": "ThoughtSpot",
        "Accept":         "application/json",
        "Authorization":  f"Bearer {token}",
        "Content-Type":   "application/json",
    },
    json={
        "metadata":                  [{"identifier": source_guid, "type": "LOGICAL_TABLE"}],
        "include_dependent_objects": True,
        "dependent_object_version":  "V2",
    },
    timeout=60, verify=False,
)
item     = resp.json()[0]
buckets  = ((item.get("dependent_objects") or {}).get("dependents") or {}).get(source_guid) or {}
# buckets: {"QUESTION_ANSWER_BOOK": [...], "PINBOARD_ANSWER_BOOK": [...], "LOGICAL_TABLE": [...]}
```

### Caveats

- **Sets/Cohorts are NOT included** in the v2 dependents response. The Step 4 cohort
  scan (using `search_all("COHORT", ...)` — see open-item #11) is still required.
- **Alerts/Monitors are NOT included.** See open-item #6.
- **RLS rules and column security TMLs are NOT included.** See open-items #7–#9.
- **Authorization filters apply** — `hasInaccessibleDependents` and
  `areInaccessibleDependentsReturned` flags indicate when the calling user lacks
  visibility into some dependents. Surface this in the impact report.

### Action

- [ ] Replace the TML batch-scan block in SKILL.md Step 4 with the v2 search call above
- [ ] Add `ts metadata dependents <guid> [<guid>...]` command to ts-cli wrapping the v2 call;
      v1 endpoint as Software/on-prem fallback path (auto-detect via 404 on v2)
- [ ] Update the SKILL.md Step 4 narrative — change "(~30 s in large environments)" to
      "(~2 s, single API call)"
- [ ] Keep the cohort scan (item #11), alert scan (#6), RLS/security/alias scans (#7–#10)
      as separate steps — v2 dependents does not cover them

**Availability:** v2 metadata search verified on ThoughtSpot Cloud (se-thoughtspot,
2026-04-25). v1 endpoint: ThoughtSpot Cloud ts7.aug.cl onwards; Software 7.1.1 onwards.

---

## #2 — Column reference format in chart configs (Step 9b) — OPEN

**Question:** Do `chart_columns[].column_id`, `table.ordered_column_ids`, and
`table.table_columns[].column_id` in Answer/Liveboard TML use:
  - (A) Display name (e.g. `"Revenue"`) — expected based on schema reference
  - (B) `TABLE::COLUMN_NAME` composite key
  - (C) Opaque internal ID

**Why it matters:** The `remove_columns_from_answer()` and `rename_column_in_answer()`
helpers compare by display name. If format (B) or (C) is used for some chart types,
those helpers silently miss chart config entries.

**Test script:**

```bash
source ~/.zshenv && ts tml export {answer_guid} --profile '{profile_name}' --fqn --parse \
  | python3 -c "
import json, sys
data = json.load(sys.stdin)
answer = data[0]['tml']['answer']
print('answer_columns:', json.dumps(answer.get('answer_columns', [])[:3], indent=2))
print('chart.chart_columns:', json.dumps(answer.get('chart', {}).get('chart_columns', [])[:3], indent=2))
print('table.ordered_column_ids:', answer.get('table', {}).get('ordered_column_ids', [])[:5])
print('table.table_columns:', json.dumps(answer.get('table', {}).get('table_columns', [])[:3], indent=2))
"
```

Test with: a table-view Answer, a chart Answer, and an Answer that uses formula columns.
Check whether column_id values match the display name exactly.

**Finding:** _(not yet tested)_

---

## #3 — search_query must be sanitized — CONFIRMED (user-verified)

**Confirmed behavior:** ThoughtSpot will **not** save an object (Answer, View) where
`search_query` references a column that no longer exists. The import fails with a
validation error. The `search_query` MUST be updated before import.

**Resolution:** The `remove_columns_from_answer()` and `remove_columns_from_view()`
helpers in SKILL.md Step 9b include `search_query` sanitization:

```python
import re

def sanitize_search_query(query_str, columns_to_remove):
    """Strip [col_name] tokens from a ThoughtSpot search_query string."""
    for col in columns_to_remove:
        query_str = re.sub(r'\s*\[' + re.escape(col) + r'\]\s*', ' ', query_str)
    return query_str.strip()

def rename_in_search_query(query_str, old_name, new_name):
    """Rename a [col_name] token in a ThoughtSpot search_query string."""
    return re.sub(
        r'\[' + re.escape(old_name) + r'\]',
        f'[{new_name}]',
        query_str,
    )
```

**Status:** Implementation added to SKILL.md. Mark VERIFIED once tested end-to-end.

---

## #4 — Join conditions with removed columns must be updated — CONFIRMED (user-verified)

**Confirmed behavior:** A Model TML cannot be saved if `joins_with[].on` (or equivalent
join expression in `model_tables[]`) references a column that no longer exists in
`columns[]`. The import fails. The join must be removed or the `on` expression corrected.

**Resolution (implemented in SKILL.md Step 9a):** Before removing a column from a
Model, scan all join expressions for references to the column. If found:
1. Show in the impact report (Step 5) as a separate "Join Conditions Affected" section
2. At the confirmation step (Step 8): list each join that will be removed
3. In Step 9a: remove the affected join from `model_tables[].joins_with[]`

```python
def remove_column_from_model_joins(section, columns_to_remove):
    """
    Remove join conditions that reference any of columns_to_remove.
    Returns (updated_section, list of removed joins for the change report).
    """
    removed_joins = []
    for tbl in section.get("model_tables", []):
        safe   = []
        for join in tbl.get("joins_with", []):
            on_expr = join.get("on", "")
            if any(col in on_expr for col in columns_to_remove):
                removed_joins.append({
                    "table":   tbl.get("name", "?"),
                    "join":    join.get("name", "unnamed"),
                    "on":      on_expr,
                })
            else:
                safe.append(join)
        tbl["joins_with"] = safe
    return section, removed_joins
```

**Impact on dependent Models:** If a dependent Model joins to the source Model using
the removed column, the same logic applies to that Model's `joins_with[]`.

**Status:** Implementation added to SKILL.md. Mark VERIFIED once tested end-to-end.

---

## #5 — `ts metadata dependents` CLI command (pending #1 verification)

**Status:** Not yet implemented. Blocked on #1 verified against a live instance.

**Proposed command interface:**

```bash
ts metadata dependents <guid> [<guid> ...] \
  [--type LOGICAL_TABLE|LOGICAL_COLUMN|PHYSICAL_TABLE|PHYSICAL_COLUMN] \
  [--profile <name>]
```

**Output:** JSON array normalizing the response into a flat list:

```json
[
  {"guid": "...", "name": "...", "type": "ANSWER",    "author": "...", "authorDisplayName": "..."},
  {"guid": "...", "name": "...", "type": "LIVEBOARD", "author": "...", "authorDisplayName": "..."},
  {"guid": "...", "name": "...", "type": "MODEL",     "author": "...", "authorDisplayName": "..."}
]
```

Map response keys: `QUESTION_ANSWER_BOOK` → `ANSWER`, `PINBOARD_ANSWER_BOOK` → `LIVEBOARD`,
`LOGICAL_TABLE` → type based on subtype metadata.

Add to `tools/ts-cli/commands/metadata.py` following the pattern of the `search` command.
Requires the `requests` form-encoded POST (not JSON) and the `X-Requested-By: ThoughtSpot` header.
Bump ts-cli version in both `__init__.py` and `pyproject.toml`.

---

## #6 — Finding Alerts that reference affected Answers/Liveboards (Step 4) — VERIFIED (Option C confirmed)

**2026-04-26 test against champ-staging — verified findings:**

- **v2 `SearchMetadataType` enum** does NOT contain any alert-like type. Tested:
  `ALERT`, `MONITOR`, `MONITOR_ALERT`, `MONITOR_RULE`, `KPI_ALERT`, `ANSWER_ALERT`,
  `LIVEBOARD_ALERT`, `SCHEDULED_ALERT`, `NOTIFICATION`, `WATCH`, `ANOMALY`,
  `METRIC`, `KPI`, `SUBSCRIPTION`, `SCHEDULE`, `SCHEDULED`, `RULE`. All rejected as
  invalid enum values (HTTP 400).

- **v2 alert/monitor REST endpoints** return 500 on champ-staging:
  `/api/rest/2.0/alerts`, `/api/rest/2.0/alerts/search`,
  `/api/rest/2.0/monitor/alert/search`, `/api/rest/2.0/monitor/search`,
  `/api/rest/2.0/notifications/search`. Only `/api/rest/2.0/schedules/search` works,
  but schedules are scheduled-report deliveries, not value-threshold alerts.

- **v2 dependents response** does NOT surface alerts in any bucket. Tested with
  TEST_DEPENDENCY_LIVEBOARD — buckets returned were empty (`has_inacc: False`).

**Conclusion: Option C — alerts cannot be programmatically discovered on this build.**
The skill MUST fall back to a manual-review caveat in the impact report.

**Action (already implemented):**
- Step 5 impact report has an "Alerts (manual review required)" section listing the
  affected Answers/Liveboards that the user should manually inspect for alerts

**Question:** How should the skill find Monitor Alerts that reference an Answer or
Liveboard being modified?

**Option A — metadata search:** Does `ts metadata search --type MONITOR_ALERT` work?
The current `metadata.py` `_OBJECT_TYPES` list does not include `MONITOR_ALERT`. Test
whether adding it to the search call returns results.

**Option B — TML batch scan:** Export all monitor_alert objects (if discoverable) and
check `monitor_alert[].metric_id.answer_id` == affected answer GUID.

**Option C — Not supported:** If Alerts cannot be found via metadata search or the
TML API, note this in the impact report as a caveat ("Alerts referencing affected
objects cannot be automatically detected — check manually").

**Status:** VERIFIED — Option C is the only viable path on the champ-staging build.
Re-verify on a different ThoughtSpot Cloud build if a future test environment is added,
in case alerts become queryable in a later release.

---

## #7 — RLS (Row Level Security) column usage detection (Step 4) — OPEN

**Question:** If a column being removed is referenced in an RLS rule, removing it from
the model will silently break access control. How can the skill detect this before proceeding?

**Why it matters:** RLS rules are applied at query time. If the column used in an RLS
condition is removed, the rule may evaluate incorrectly or fail silently, potentially
exposing data to unauthorized users. This is a **STOP condition** (Rule 7) — the skill
must detect RLS usage and prevent the removal until the RLS rule is updated.

**Options to investigate:**

Option A — TML export of the model: Does the model TML include RLS rule definitions
directly, or are they stored separately?

Option B — Dedicated RLS API: Is there a v1 or v2 endpoint for listing RLS rules by
table or column?

Option C — metadata search for RLS object type: Try `ts metadata search --type ROW_SECURITY_RULE`
(or equivalent) to discover RLS objects referencing the source model.

**Test script:**

```bash
# Check if ROW_SECURITY_RULE is a valid metadata type
source ~/.zshenv && ts auth token --profile '{profile_name}' | read TOKEN && \
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Requested-By: ThoughtSpot" \
  -H "Content-Type: application/json" \
  "{base_url}/api/rest/2.0/metadata/search" \
  -d '{"metadata":[{"type":"ROW_SECURITY_RULE"}],"record_size":10}' \
  | python3 -m json.tool | head -50
```

Also check the model TML export with `--associated` flag — look for any `rls_rules`
or `row_security` keys in the output:

```bash
source ~/.zshenv && ts tml export {model_guid} \
  --profile '{profile_name}' --fqn --associated --parse \
  | python3 -c "
import json, sys
docs = json.load(sys.stdin)
for d in docs:
    if 'rls' in str(d).lower() or 'row_security' in str(d).lower() or 'row_level' in str(d).lower():
        print(d['type'], json.dumps(d, indent=2)[:500])
"
```

**Finding:** _(not yet tested)_

**Action when VERIFIED:**
- If RLS rules are discoverable: add RLS scan to Step 4; add RLS column usage as a
  STOP condition in the impact report and require user to update the RLS rule first
- If not detectable: add a mandatory warning in the impact report that RLS rules
  cannot be automatically detected and must be manually reviewed

---

## #8 — Column-level sharing / access control detection (Step 4) — OPEN

**Question:** ThoughtSpot supports column-level access control (restricting which users
can see specific columns). If a column is being renamed, references in column-level
sharing rules may become stale. How are these rules stored and can they be detected
via TML or API?

**Why it matters:** Renaming a column that appears in a column-level sharing rule may
silently remove that column from the rule, potentially exposing restricted data.

**Options to investigate:**

Option A — Column-level security in model TML: Are column access restrictions stored
inline in the model TML (e.g., `columns[].access_type` or similar)?

Option B — Separate security TML type: Is there a distinct TML object type for
column-level security policies?

Option C — v2 REST API: Is there a `/api/rest/2.0/` endpoint for column-level security?

**Test script:**

```bash
# Export model TML and look for access / permission / security keys
source ~/.zshenv && ts tml export {model_guid} \
  --profile '{profile_name}' --fqn --parse \
  | python3 -c "
import json, sys
data = json.load(sys.stdin)
model = data[0]['tml']
# Look for access-related fields
tml_str = json.dumps(model)
for keyword in ['access', 'permission', 'security', 'sharing', 'visibility']:
    if keyword in tml_str.lower():
        print(f'Found keyword: {keyword}')
"
```

**Finding:** _(not yet tested)_

**Action when VERIFIED:**
- Document the column-level sharing TML structure
- Add detection to Step 4 impact report
- Add update logic to Step 9 for RENAME operations

---

## #9 — Column security rule TML structure (Step 9) — OPEN

**Question:** ThoughtSpot has a concept of column-level security rules stored as separate
TML objects. What is the TML type name, structure, and how does it reference columns
from a parent model?

**Why it matters:** When removing or renaming a column, any column security rule TML
that references that column must also be updated. The skill currently has no mechanism
to find or update these objects (Rule 9).

**Options to investigate:**

Option A — `--associated` export: Does exporting a model with `--associated` include
any security rule TML documents? Check the `type` field of all returned documents.

Option B — metadata search: Try variations of the type string (`COLUMN_SECURITY_RULE`,
`DATA_POLICY`, `SECURITY_RULE`) against the metadata search endpoint.

**Test script:**

```bash
# Export model with --associated and list all returned TML types
source ~/.zshenv && ts tml export {model_guid} \
  --profile '{profile_name}' --fqn --associated --parse \
  | python3 -c "
import json, sys
docs = json.load(sys.stdin)
for d in docs:
    print(d.get('type'), list(d.get('tml', {}).keys())[:5])
"
```

**Finding:** _(not yet tested)_

**Action when VERIFIED:**
- Document the column security rule TML structure in `agents/shared/schemas/`
- Add scan to Step 4 to find security rule documents referencing the affected column
- Add update logic to Step 9: for REMOVE, remove the column from the rule; for RENAME,
  update the column reference

---

## #10 — Column aliasing in TML (Step 4 / Step 9) — OPEN

**Question:** ThoughtSpot allows columns to be aliased (displayed under a different name
than the underlying column ID). When a column is renamed or removed, are alias references
updated automatically, or do they need to be found and updated explicitly?

**Why it matters:** If aliases are stored as separate references (e.g., in answer TML as
a `custom_name` field or in a separate alias mapping), the skill's current rename logic
may miss them, leaving stale display names after a column rename.

**Options to investigate:**

Option A — Inline in answer_columns: Do `answer_columns[]` entries have a `custom_name`
or `alias` field separate from `name` that stores an alias?

Option B — In chart config: Are aliases stored in `chart.chart_columns[].name` vs.
`chart.chart_columns[].column_id` (i.e., is `name` the alias and `column_id` the actual reference)?

Option C — In model TML: Does the model TML store column aliases in a `display_name`
field separate from `name`?

**Test script:**

```bash
# Export an answer that uses a column known to have a custom alias
# and inspect the full answer_columns and chart structure
source ~/.zshenv && ts tml export {answer_guid} \
  --profile '{profile_name}' --fqn --parse \
  | python3 -c "
import json, sys
data = json.load(sys.stdin)
answer = data[0]['tml']['answer']
print('answer_columns:', json.dumps(answer.get('answer_columns', [])[:5], indent=2))
print('chart_columns:', json.dumps(answer.get('chart', {}).get('chart_columns', [])[:5], indent=2))
"
```

**Finding:** _(not yet tested)_

**Action when VERIFIED:**
- Document where aliases are stored in the TML structure
- Update `rename_column_in_answer()` and `rename_column_in_view()` to handle alias fields
- Update the impact report to show aliased column names alongside internal names

---

## #11 — Reusable Set (cohort) metadata type and delete command (Step 4 / Step 9c) — CONFIRMED (type), OPEN (delete)

**Finding (user-confirmed):** The internal name for Sets is `cohort`. The metadata API
type name is `COHORT`. The `search_all("COHORT", profile_name)` call in Step 4 is correct.

**Remaining open question — Delete command:** Does `ts metadata delete {guid}` work for
cohort/Set objects, or is a different command or API endpoint needed?

**Why it still matters:** The Step 9c delete loop uses `ts metadata delete` — if that
command does not support cohort objects, set deletions will silently fail.

**Test script:**

```bash
# Part A: find the correct type name
source ~/.zshenv && ts auth token --profile '{profile_name}' | read TOKEN && \

# Try COHORT
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Requested-By: ThoughtSpot" \
  -H "Content-Type: application/json" \
  "{base_url}/api/rest/2.0/metadata/search" \
  -d '{"metadata":[{"type":"COHORT"}],"record_size":5}' \
  | python3 -m json.tool | head -20

# If COHORT returns empty or errors, also try:
# "type":"USER_DEFINED_GROUPING" or "type":"SET"

# Part B: delete a test set and confirm it's gone
# (only after creating a throwaway set specifically for this test)
source ~/.zshenv && ts metadata delete {test_set_guid} --profile '{profile_name}'
```

Also export a known Set via TML export to confirm its type label:

```bash
source ~/.zshenv && ts tml export {known_set_guid} --profile '{profile_name}' --parse \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d[0].get('type'))"
```

**Finding:** _(not yet tested)_

**Action when VERIFIED:**
- Replace `"COHORT"` in the Step 4 `search_all()` call with the confirmed type name
- Add a `ts metadata delete` test to the smoke test suite for set cleanup
- If `ts metadata delete` does not support Sets, add a workaround using the REST API
  (`DELETE /api/rest/2.0/metadata/delete` with the set GUID) and document it here

**Update 2026-04-26 (champ-staging test):** Confirmed multiple findings:
- `COHORT` is **not** a valid `SearchMetadataType` enum value — the v2 API returns 400.
  Sets must be queried as `LOGICAL_COLUMN`. The skill's `search_all("COHORT", ...)` call
  needs to be replaced.
- Sets appear in v2 dependents responses under their own **`COHORT` bucket** alongside
  `LOGICAL_TABLE` etc. (when querying the source table that contains the set's anchor column).
- The `ts metadata delete` CLI command is **broken** — see open-item #17.

---

## #12 — Model-level filters block column removal (Step 9c) — VERIFIED 2026-04-26

**Confirmed behavior:** ThoughtSpot will not save a Model TML if `model.filters[].column`
references a column that no longer exists in `model.columns[]`. The import fails with
`error_code: 14518` and message `"Invalid filter column: {col_name}"`. The error message
is misleadingly surfaced upstream as `"Invalid YAML/JSON syntax in file."` if the caller
parses by message text instead of error_code.

**Resolution:** Step 9c's `fix_model()` helper must strip model-level filters whose
`column` array references a removed column.

```python
def fix_model(m, cols_to_remove):
    """Existing logic: strip columns + joins. Add: strip top-level filters."""
    # ... existing logic ...
    m["filters"] = [
        f for f in m.get("filters", [])
        if not any(c in cols_to_remove for c in f.get("column", []))
    ]
    return m
```

**Test fixture verified:** `TEST_DEPENDENCY_MANAGEMENT` and other Models on champ-staging
had `filters: [{column: ["Customer Zipcode"], oper: ">", values: ["1000"]}]` blocks that
caused the failure. After stripping, the import succeeds.

**Status:** Implementation specified above; code update pending in SKILL.md Step 9c.

---

## #13 — Chart `client_state_v2` JSON contains stale column references — OPEN

**Issue:** Liveboard visualizations and Answers store chart-styling config inside a
`chart.client_state_v2` field — a JSON-encoded string. After stripping the column from
all the structural locations (chart_columns, axis_configs, table_columns, etc.), the
import still fails with `Invalid custom chart config columns. These column ids do not
exist. [Customer Zipcode]` if the column name appears inside `client_state_v2`'s
`columnProperties[]` or `systemSeriesColors[]`.

**Witnessed structures:**

```json
{
  "columnProperties": [
    {"columnId": "Customer Zipcode", "columnProperty": {"kpiColumnProperties": {...}}}
  ],
  "systemSeriesColors": [
    {"serieName": "Customer Zipcode", "color": "#48d1e0"}
  ]
}
```

Plus chart-binding-style entries in `viz.viz_style` or `viz.chart_properties`:

```json
{
  "key": "split-by-color",
  "columns": ["Customer Zipcode"],
  "mode": "COLUMN_DRIVEN"
}
```

**Resolution:** `fix_answer` and `fix_liveboard` must:
1. Parse `chart.client_state_v2` as JSON
2. Strip removed-column entries from `columnProperties[]`, `systemSeriesColors[]`, and any
   other column-id-keyed sub-arrays
3. Re-serialize to JSON before saving back to TML
4. Walk `viz.chart_properties[]` (or whichever key holds the bindings) and strip column
   refs from any `columns[]` array inside

This is closely related to open-item #2 (column ID format in chart configs). Both must be
resolved together to make Liveboard/Answer fixes reliable.

**Status:** Tested and confirmed on champ-staging Liveboard `2fa59781-...` (Viz_6).

---

## #14 — Cohort `pass_thru_filter` lost on TML re-import (round-trip) — OPEN

**Issue:** When a cohort TML is exported and re-imported unchanged, the
`config.pass_thru_filter` field is silently dropped. Original cohort had:

```yaml
config:
  pass_thru_filter:
    accept_all: false
```

After export → re-import, querying the cohort returns `pass_thru_filter: None`. This is
a fidelity issue with the TML export/import pipeline (potentially v2 server-side, not
ts-cli).

**Why it matters:** Step 11 rollback re-imports the original cohort TML to restore. If
fields are silently dropped, the rollback isn't a true restore.

**Test script:** Export any cohort with a non-default `pass_thru_filter`, re-import,
re-export, diff. Find which fields don't round-trip.

**Status:** Witnessed on champ-staging during 2026-04-26 test. Not yet root-caused.

---

## #15 — TS error message text is misleading; use error_code for branching — OPEN

**Issue:** When TML import fails for non-syntax reasons (missing column, invalid filter,
chart binding mismatch, etc.), the API often returns
`"error_message": "Invalid YAML/JSON syntax in file."` regardless of the actual cause.
The actual cause is reflected in `error_code` (14518 = invalid filter column,
14544 = column has dependents, 14516 = duplicate cohort name, etc.).

**Implication for the skill:** the Step 9 import loop must NOT match on error message
text. It must read `error_code` to classify failures and surface the right remediation.

**Resolution:**
1. Build a mapping table of TS error codes → cause/remediation
2. Update `import_status()` helper in Step 9b to extract `error_code` and pair it with
   the message
3. Surface error_code in the Change Report (Step 10) so users can look up the cause

**Witnessed error codes (partial):**

| Code  | Meaning |
|-------|---------|
| 14516 | Duplicate cohort name |
| 14518 | Invalid filter column (column referenced by filter doesn't exist) |
| 14544 | Deleted columns have dependents (cascade block) |

**Status:** Catalog the codes by triggering known failures; document per-code remediation.

---

## #16 — Cohort + dependent answer import ordering / TS metadata caching — OPEN

**Issue:** When restoring objects in dependency order during Step 11 rollback, importing
a Set's TML appears to succeed but a follow-up import of an answer that consumes the
Set fails with `Column: address set not found`. Re-importing the cohort and waiting
~2 seconds before the answer import resolves the issue.

**Root cause hypothesis:** ThoughtSpot has internal metadata caching that doesn't
immediately reflect a cohort import. Subsequent imports referencing the cohort by name
race against the cache update.

**Resolution options:**
1. **Sleep**: add a 2-3s sleep between cohort imports and consumer imports (cheap, fragile)
2. **Verify-and-retry**: after each cohort import, query the cohort by GUID and confirm
   it's discoverable from the parent Model before importing consumers
3. **Batch import**: bundle the cohort + its consumers into a single multi-object import
   payload — let TS resolve them together

Option 2 is the most robust. Add to Step 9c's helper.

**Status:** Witnessed during 2026-04-26 rollback test. Not yet root-caused; verify-then-
retry workaround applied successfully.

---

## #17 — `ts metadata delete` CLI command is broken — VERIFIED 2026-04-26

**Issue:** `ts metadata delete <guid> --profile <name>` returns exit 0 with response
`{"deleted": [<guid>]}` but **the object is not actually deleted**. Querying the object
afterward returns it with `isDeleted: False`.

**Root cause:** The CLI sends a v2 `POST /api/rest/2.0/metadata/delete` request without
the required `type` field in the body. The API silently accepts the malformed request
and returns 200 OK with a fake "deleted" payload, but does nothing.

**Workaround (verified):** Call the v2 endpoint directly with `{type, identifier}`:

```python
import requests
r = requests.post(
    f"{base_url}/api/rest/2.0/metadata/delete",
    headers={"Authorization": f"Bearer {token}", "X-Requested-By": "ThoughtSpot",
             "Content-Type": "application/json", "Accept": "application/json"},
    json={"metadata": [{"identifier": guid, "type": v2_type}]},
    timeout=60, verify=verify_ssl,
)
# 204 No Content = success
```

The v2 type values: `ANSWER`, `LIVEBOARD`, `LOGICAL_TABLE` (for Models/Views/Tables),
`LOGICAL_COLUMN` (for Sets/Cohorts).

**Resolution:**
1. **Skill (already applied)**: Step 9a uses the direct v2 call, not `ts metadata delete`
2. **ts-cli fix needed**: `tools/ts-cli/ts_cli/commands/metadata.py` `delete` command must
   include `type` in the request body. Resolve the type either via a required CLI flag
   (`--type ANSWER`) or by looking it up via `metadata/search` first.
3. **Add a verification step in the CLI**: after calling delete, re-query and confirm
   the object is gone. If not, error with the actual cause.

**Status:** SKILL.md updated to bypass the CLI. Separate ts-cli bug ticket needed.

---

## #18 — TML export/import cycle for FEEDBACK objects fails — OPEN

**Issue:** Spotter feedback objects (returned by v2 dependents under the `FEEDBACK` bucket
when querying a Model) cannot be exported via `ts tml export <guid>`. The API returns:

```
error_code: 10002
error_message: "Invalid parameter values: {\"metadata_identifiers\": ...}"
```

This is true with `--type FEEDBACK`, with no type, and with several variants. The standard
TML export endpoint does not accept FEEDBACK-typed identifiers.

**Implication:** Step 9c's feedback handling cannot use TML export/import for fix or
rollback. A different mechanism is needed. Candidate endpoints:
- `/api/rest/2.0/spotter/feedback/...` — returns 500 on champ-staging (build-specific?)
- `/api/rest/2.0/feedback/...` — returns 500
- `/api/rest/2.0/sage/feedback/...` — returns 500

None of these have been verified working on champ-staging.

**Resolution:** Pending discovery of the correct endpoint for fetching/updating/deleting
FEEDBACK objects. Until then:
- Step 4 should still surface FEEDBACK in the impact report (information only)
- Step 9 should NOT attempt to update or delete FEEDBACK objects automatically
- Step 10 Change Report should mention "Spotter feedback referencing the column was not
  modified — review and update manually after the change"

**Status:** Open; needs documentation of the right endpoint.

---

## #19 — Audit scope 3: Whole-object section-per-column report (Step 5) — DEFERRED

**Goal:** When the user picks audit scope 3 (whole object), generate a separate report
section per column on the source — each with its own markdown tables, dependency tree,
mermaid DAG, and summary counts.

**Why deferred:** Step 3-A (Commit A) and Step 4 (existing) already work for scope 1 and
2. Whole-object mode requires two new pieces:
1. Iterating Step 4 once per column with the per-column filter, AND
2. Restructuring Step 5 output to render N sections instead of 1, plus a top-level summary
   table that lists every column with its dep count

**Implementation outline:**

```python
if audit_scope == "WHOLE":
    all_columns = [c.get("name") for c in source_columns]
    per_column_results = {}
    for col in all_columns:
        # Run Step 4 with audit_columns = [col]
        per_column_results[col] = run_step4_scan(source_guid, [col])

    # Step 5 rendering: emit
    #   summary.csv with one row per column (col, dep_count, risk_summary)
    #   impact_plan_<col>.json per column
    #   dependency_tree_<col>.txt per column
    #   dependency_<col>.mmd per column
    # Plus a top-level overview: rank columns by dep count
```

**Output files in `{report_dir}/`:**
- `summary.csv` — one row per column: name, dep_count, by-type counts, recommended action
- `per_column/{col}/impact_plan.json` etc.

**Status:** Deferred — implement in Commit B.

---

## #20 — Audit scope 4: Repoint pre-flight column-gap analysis (Step 5) — DEFERRED

**Goal:** When the user picks audit scope 4, generate a "would this repoint work?" report:
- Source object's columns
- Target object's columns
- **Column gap** — source columns absent in target
- For each gap column, list the dependents that would lose data after the repoint
- Per-dependent simulation: which would auto-resolve, which would break, which need manual
  fix-up

**Why deferred:** Reuses Step 4 dep walk on the source, but adds:
1. Target object lookup + column listing
2. Gap computation
3. Per-dependent column-impact simulation (would the dep still render? lose what columns?)

**Implementation outline:**

```python
if audit_scope == "REPOINT_PREFLIGHT":
    target_guid = ask_for_target_object()  # Step 3-P-style search
    source_cols = export_columns(source_guid)
    target_cols = export_columns(target_guid)
    gap = source_cols - target_cols  # source columns missing in target

    deps_per_col = {}
    for col in gap:
        deps_per_col[col] = run_step4_scan(source_guid, [col])

    # Render: gap table, per-gap-column dep list, simulation summary
```

**Output files:**
- `repoint_preflight.json` — full simulation result
- `column_gap.csv` — one row per gap column with dep counts
- `dependency_<col>.txt/.mmd` per gap column

**Status:** Deferred — implement in Commit B (alongside #19).

---

## #21 — Recommendation engine after audit (Step 5.5) — DEFERRED

**Goal:** After any audit, surface concrete next-action recommendations per column based
on the dep graph. The user can pick a recommendation and the skill jumps directly into
the matching R/N/P flow with source + columns pre-filled.

**Recommendation rules (initial):**

| Pattern | Recommended action |
|---|---|
| 0 deps                            | REMOVE (safe) |
| Only formula deps, no charts      | REMOVE (auto-cleanup) |
| Charts on axis                    | REMOVE w/ auto-fix to TABLE_MODE |
| RLS rule + dependents             | REMOVE — coordinate with security review first |
| Display-name issue (user request) | RENAME |
| Switching backing source          | REPOINT |
| Set as anchor + consumers         | REMOVE the Set; consumers need attention |

**Output:**

```
Recommended actions:

  ZIPCODE (9 dependents)
    Recommended:  REMOVE  (with auto-fix mode for charts on axes)
    Risk:         HIGH — 1 RLS rule + 3 Liveboard vizzes on axis + 2 feedback items
    Take action?  /ts-dependency-manager → R → DM_CUSTOMER_BIRD → ZIPCODE

  STATE (0 dependents)
    Recommended:  REMOVE  (safe)
    Take action?  /ts-dependency-manager → R → DM_CUSTOMER_BIRD → STATE

Enter the number(s) to apply, or N to exit and replan later.
```

If the user picks one, the skill **jumps directly into the matching apply flow** with
source + columns pre-filled (skip Step 2 and Step 3 search; resume at Step 4 with the
recommendation's parameters).

**Why deferred:** Requires the rule-engine + jumping logic. Best to ship after #19/#20
so the input data (per-column dep counts and patterns) is already populated.

**Status:** Deferred — implement in Commit C.
