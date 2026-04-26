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

## #6 — Finding Alerts that reference affected Answers/Liveboards (Step 4) — VERIFIED 2026-04-26

**Alerts ARE returned as `monitor_alert` TML when exporting a Liveboard with
`--associated`.** Verified against TEST_DEPENDENCY_LIVEBOARD (`2fa59781-...`) on
champ-staging — `--associated --fqn --parse` returns 11 docs including a
`monitor_alert` document with both alerts attached to the liveboard's KPI viz.

The previously-recorded conclusion (Option C, manual review only) was **wrong** — earlier
probing missed the CLI's `--associated` flag because the v2 endpoint's flag is named
`export_associated` (not `export_associated_objects`). The CLI passes `export_associated:true`
which DOES include monitor_alert docs in the response.

### Verified TML structure

```yaml
# info.filename: "Alerts.tml"
# info.type:     "monitor_alerts"
# tml root key:  monitor_alert  (a list — multiple alerts on one liveboard come back together)
monitor_alert:
  - guid: 05e270a6-fec6-46e4-b725-ba81c66c3fa3
    name: "Alert on Total Amount by Daily Balance Date"
    frequency_spec:
      cron:
        second: "0"
        minute: "0"
        hour: "9"
        day_of_month: "*"
        month: "*"
        day_of_week: "1,2,3,4,5"
      time_zone: "UTC"
      start_time: 1777136381
      end_time: 0
      frequency_granularity: "DAILY"
    creator:
      username: damian.waldron@thoughtspot.com
      user_email: damian.waldron@thoughtspot.com
    condition:
      percentage_change_condition:
        comparator: "PERCENTAGE_CHANGE_COMPARATOR_CHANGES_BY"
        threshold: { value: 5.0 }
    metric_id:
      pinboard_viz_id:
        pinboard_id: 2fa59781-ef39-4755-906c-310968709094  # ← liveboard GUID
        viz_id:      b5e803c6-75f7-4c03-b824-55ef574f87f4  # ← visualization id
      personalised_view_id: 4ed497ac-...
    subscribed_user:
      - { username: ..., user_email: ... }
    customMessage: ""
    personalised_view_info:                                # ← COLUMN REFERENCES LIVE HERE
      tables:
        - id: TEST_DEPENDENCY_MANAGEMENT
          name: TEST_DEPENDENCY_MANAGEMENT
          fqn: e5c84be6-ebbc-4ef0-9522-e124f0d29827
      filters:
        - column: ["TEST_DEPENDENCY_MANAGEMENT::Customer Zipcode"]   # ← TABLE::COL_NAME
          is_mandatory: false
          is_single_value: false
          display_name: ""
        - column: ["TEST_DEPENDENCY_MANAGEMENT::Customer Name"]
          oper: "in"
          values: ["Ainyx"]
          is_mandatory: false
          is_single_value: false
          display_name: ""
    alert_type: "Threshold"   # also "Anomaly"
```

### Key column-reference locations

When a column on a Model used by an alerted Answer/Liveboard is renamed or removed:

1. **`personalised_view_info.filters[].column[]`** — strings of form `"TABLE_NAME::COLUMN_NAME"`.
   Multiple alerts can each have multiple filters. Each filter's `column` is a list (usually
   length 1, but can be longer for multi-column filters).
2. The alert is anchored to a specific viz via `metric_id.pinboard_viz_id.viz_id` (or
   `metric_id.answer_id` for standalone Answers). If the viz itself is deleted as part of
   a `REMOVE_CHART` decision in Step 6, the alert is orphaned and must also be deleted.

The metric being monitored is the visualization's primary measure — the alert doesn't
encode it as a column reference (it's whatever the viz computes). If the column underlying
the metric is removed without a `REMOVE_CHART` decision on the viz, the alert continues
to exist but its filter set is broken.

### Detection logic for Step 4

```python
def find_alert_column_uses(monitor_alert_tml, target_columns, source_model_name=None):
    """
    Returns list of {alert_guid, alert_name, viz_id, filter_index, column} for every
    filter in any alert that references a column in target_columns.

    target_columns is the set of model-level column names being removed/renamed
    (e.g. {"Customer Zipcode"}).
    """
    hits = []
    for i, alert in enumerate(monitor_alert_tml.get("monitor_alert", [])):
        viz_id = (alert.get("metric_id", {})
                       .get("pinboard_viz_id", {})
                       .get("viz_id", ""))
        for j, filt in enumerate(alert.get("personalised_view_info", {}).get("filters", [])):
            for col_ref in filt.get("column", []):
                # col_ref looks like "TABLE_NAME::COLUMN_NAME"
                parts = col_ref.rsplit("::", 1)
                if len(parts) != 2:
                    continue
                tbl, col = parts
                if col in target_columns:
                    if source_model_name and tbl != source_model_name:
                        continue   # filter is on a different table; skip
                    hits.append({
                        "alert_guid": alert.get("guid"),
                        "alert_name": alert.get("name"),
                        "viz_id":     viz_id,
                        "filter_index": j,
                        "column":     col,
                        "table":      tbl,
                    })
    return hits
```

### Update logic for Step 9 (RENAME)

```python
def rename_alert_columns(monitor_alert_tml, table_name, old_col, new_col):
    """Update column refs in alert filters for a column rename."""
    old_ref = f"{table_name}::{old_col}"
    new_ref = f"{table_name}::{new_col}"
    for alert in monitor_alert_tml.get("monitor_alert", []):
        for filt in alert.get("personalised_view_info", {}).get("filters", []):
            filt["column"] = [new_ref if c == old_ref else c for c in filt.get("column", [])]
    return monitor_alert_tml
```

### Update logic for Step 9 (REMOVE)

For REMOVE, drop filters whose column lists become empty after column removal. If an
alert ends up with zero filters AND its viz was marked for removal in Step 6, prompt
the user to delete the alert too (it has nothing left to filter on).

```python
def remove_alert_columns(monitor_alert_tml, table_name, removed_cols):
    """Strip filters whose column refs target a removed column."""
    removed_refs = {f"{table_name}::{c}" for c in removed_cols}
    for alert in monitor_alert_tml.get("monitor_alert", []):
        new_filters = []
        for filt in alert.get("personalised_view_info", {}).get("filters", []):
            kept = [c for c in filt.get("column", []) if c not in removed_refs]
            if kept:
                filt["column"] = kept
                new_filters.append(filt)
        alert["personalised_view_info"]["filters"] = new_filters
    return monitor_alert_tml
```

### Action

- [x] Verify alert TML structure on champ-staging
- [ ] Add alert scan to Step 4 — for each Liveboard/Answer dependent, also export with
      `--associated` and check for `monitor_alert` docs
- [ ] Add alert section to Step 5 impact report (separate from manual-review caveat —
      we can now actually find them)
- [ ] Add update logic to Step 9 RENAME and REMOVE flows
- [ ] Add re-import path for the modified `monitor_alert` TML — note: it has no GUID at
      the document root; the import endpoint handles list-of-alerts updates
- [ ] Confirm via test: does TS reject a re-import of monitor_alert TML where a filter
      references a column that no longer exists on the underlying model? (probably yes —
      same family as the search_query and join validation)
- [ ] Create `~/.claude/shared/schemas/thoughtspot-alert-tml.md` (currently missing)
      documenting the structure above

### Test fixture

TEST_DEPENDENCY_LIVEBOARD on champ-staging (`2fa59781-ef39-4755-906c-310968709094`) has
2 alerts referencing "Customer Zipcode" via `TEST_DEPENDENCY_MANAGEMENT::Customer Zipcode`.
Use this for end-to-end testing of the alert detection + update path.

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

## #7 — RLS (Row Level Security) column usage detection (Step 4) — VERIFIED 2026-04-26

**RLS rules ARE in the table TML** — no separate API needed. Verified against
`DM_CUSTOMER_BIRD` (32c062cb-...) on champ-staging via
`ts tml export <table_guid> --fqn --parse`. The rule structure is fully self-describing
and easy to scan: `table_paths[].column[]` lists the referenced columns explicitly, and
`rules[].expr` references them via `[path_id::COL_NAME]` syntax.

### Verified TML structure

```yaml
table:
  name: DM_CUSTOMER_BIRD
  columns: [...]
  rls_rules:
    tables:                          # (Always references self for single-table rules)
      - name: DM_CUSTOMER_BIRD
        fqn:  32c062cb-...
    table_paths:                     # Each path is a reusable identifier within the rule
      - id:     DM_CUSTOMER_BIRD_1
        table:  DM_CUSTOMER_BIRD
        column: [ZIPCODE]            # ← EXPLICIT column list — primary detection target
    rules:
      - name: testRLS
        expr: "[DM_CUSTOMER_BIRD_1::ZIPCODE] = ts_groups_int "  # ← path_id::COL_NAME
```

### Detection logic for Step 4

```python
def find_rls_column_uses(table_tml, target_columns):
    """
    Returns a list of {rule_name, path_id, column, expr} for every RLS rule that
    references any column in target_columns.
    """
    rls = table_tml.get("table", {}).get("rls_rules", {})
    paths = {p["id"]: p for p in rls.get("table_paths", [])}
    hits = []
    for rule in rls.get("rules", []):
        expr = rule.get("expr", "")
        for path_id, p in paths.items():
            for col in p.get("column", []):
                if col not in target_columns:
                    continue
                # Confirm the column actually appears in the rule expression
                if f"{path_id}::{col}" in expr or f"[{col}]" in expr:
                    hits.append({
                        "rule_name": rule["name"],
                        "path_id":   path_id,
                        "column":    col,
                        "expr":      expr,
                    })
    return hits
```

### Update logic for Step 9 (RENAME)

```python
def rename_rls_column(table_tml, old_name, new_name):
    """Update column references in table.rls_rules for a column rename."""
    rls = table_tml.get("table", {}).get("rls_rules", {})
    # Update path column lists
    for p in rls.get("table_paths", []):
        p["column"] = [new_name if c == old_name else c for c in p.get("column", [])]
    # Update rule expressions: [path_id::OLD_NAME] -> [path_id::NEW_NAME]
    for rule in rls.get("rules", []):
        expr = rule.get("expr", "")
        rule["expr"] = re.sub(
            r'(::)' + re.escape(old_name) + r'(\])',
            lambda m: m.group(1) + new_name + m.group(2),
            expr,
        )
    return table_tml
```

### Behavior on REMOVE

A removed column referenced by an RLS rule is a **STOP condition** — silently breaks
access control. The skill must:

1. **Detect** at Step 4 — scan the source table's `table.rls_rules` (and any join-target
   tables in the model) for the column
2. **Block** at Step 5 — show in STOP CONDITIONS section with the rule name and expr
3. **Require explicit user resolution** — either remove the rule first via UI, or
   acknowledge that the column will be dropped and the rule will fail (TS may also
   reject the table TML import; not yet tested)

**Note on join-target tables:** When the source is a Model that joins to multiple base
tables, RLS rules can live on any of the joined tables. Step 4's RLS scan must walk every
table in `model.model_tables[].fqn` (resolve to its TML and check `rls_rules`), not just
the source table.

### Action

- [x] Verified RLS structure on champ-staging
- [ ] Add `find_rls_column_uses()` to Step 4 of SKILL.md
- [ ] Add RLS section to Step 5 STOP CONDITIONS
- [ ] Add `rename_rls_column()` to Step 9 RENAME path
- [ ] Add RLS scan across all `model_tables[]` (not just source table)
- [ ] Confirm via test: does TS reject a table TML import that has RLS rule referencing
      a removed column? (probably yes — same pattern as #4 join conditions and #12 filters)

---

## #8 — Column-level sharing / access control detection (Step 4) — VERIFIED 2026-04-26 (no skill action needed)

**Verified findings on champ-staging (2026-04-26):** Column-level ACLs exist as ORM
records, NOT as TML. They are accessible via the v2 endpoint
`POST /api/rest/2.0/security/metadata/fetch-permissions` with
`type: LOGICAL_COLUMN` and the column GUID. Response shape mirrors the table-level
permissions response: principal-by-principal grants of `MODIFY` / `VIEW` / `NO_ACCESS`.

**Critical observation: ACLs are keyed by column GUID, not by name.** Implications for
the skill:

- **RENAME** — column GUID is stable across a name change, so column ACLs follow the
  rename automatically. **No skill action required.**
- **REMOVE** — when a column is deleted, its ACL records become orphaned. They are
  inert (no column to grant access to) and cause no security exposure. **No skill
  action required.**
- **REPOINT** — column GUIDs change because the dependent objects now reference
  columns from a different table. ACLs on the OLD column are unaffected; the user's
  visibility into the new repointed object is determined by the target table's ACLs.
  **No skill action required** — this is the existing behavior of repoint operations.

### What the skill could optionally do

Show column ACL counts in the impact report as informational metadata (e.g.,
"3 principals have explicit access to this column"). This is purely advisory; it
doesn't change the operation's safety. Probably not worth the API call latency in
typical use.

### Probes ruled out

`MASKING_POLICY`, `DATA_MASK`, `COLUMN_SECURITY`, `RLS_POLICY`, `DATA_POLICY_RULE`,
`COLUMN_PROPERTY` — all rejected by v2 metadata search enum. There is no separate
"column security TML" object on this build. The user-facing concept of column-level
security is implemented entirely as ACL records on the column GUID, which the skill
does not need to inspect or update.

**Status:** VERIFIED. No skill changes required. The original open item asked the wrong
question ("how do we find column security TML?"); the actual answer is that there is no
such TML and no action is needed because GUIDs are stable.

---

## #9 — Column security rule TML structure (Step 9) — STRUCTURE KNOWN; RETRIEVAL UNVERIFIED 2026-04-26

ThoughtSpot has a per-table `column_security_rules` TML type (filename pattern
`<TABLE_NAME>_CSR.column_security_rules`). It controls which user groups can see which
columns of the table — distinct from #8 (which is column ACLs keyed by GUID).

The TML structure is documented and detection/update logic is mechanical. The
**retrieval mechanism** is the open question: on champ-staging, the v2
`/api/rest/2.0/metadata/tml/export` endpoint with `export_associated:true`
**does not return** these TML files for any model tested (TEST_DEPENDENCY_MANAGEMENT,
canonical Dunder Mifflin Sales, Aliasing Testing model). The CSR file appears only when
exporting via the ThoughtSpot UI's Download TML zip path or via the `vcs/git/branches/commit`
workflow that pushes a full bundle to a configured git repo.

### Verified TML structure (per user-provided example, 2026-04-26)

```yaml
# Filename pattern: <TABLE_NAME>_CSR.column_security_rules
# Lives at table scope; references columns by name.
column_security_rules:
  table:
    name: DM_CUSTOMER_BIRD
    obj_id: DM_CUSTOMER-32c062cb     # ← <table>-<short_id>; not a raw GUID
  rules:
    - column_name: CUSTOMER_CODE     # ← references base TABLE column name (not model alias)
      accessible_groups:
        group_name:
          - "123"
          - all_users
    - column_name: STATE
      accessible_groups:
        group_name:
          - all_users
    - column_name: ZIPCODE           # ← target column for our skill's REMOVE/RENAME ops
      accessible_groups:
        group_name:
          - admaxi
          - "123"
          - all_users
```

**Important properties:**
- One CSR file per table that has any column-level rules. A table with no rules has no CSR file.
- `column_name` references the **base table column name** (e.g. `ZIPCODE`), NOT a model-level
  alias (e.g. `Customer Zipcode`). This matters: removing `Customer Zipcode` at the model layer
  does not affect CSR; renaming the underlying `ZIPCODE` column at the table layer does.
- `accessible_groups.group_name` is a list of group names (strings).
- A column referenced in CSR but missing from the table → access falls through to default
  table-level sharing (column becomes visible/invisible based on table ACL, not CSR rules).

### Detection logic for Step 4 (when CSR file is available)

```python
def find_csr_column_uses(csr_tml, target_columns):
    """
    target_columns is the set of base-table column names being removed/renamed.
    Returns list of {table, column, accessible_groups} for each rule that references
    a column in target_columns.
    """
    csr = csr_tml.get("column_security_rules", {})
    table_name = csr.get("table", {}).get("name", "")
    hits = []
    for rule in csr.get("rules", []):
        col = rule.get("column_name")
        if col in target_columns:
            hits.append({
                "table":             table_name,
                "column":            col,
                "accessible_groups": rule.get("accessible_groups", {}).get("group_name", []),
            })
    return hits
```

### Update logic for Step 9

**RENAME** — update `column_name` in matching rules:

```python
def rename_csr_column(csr_tml, old_name, new_name):
    for rule in csr_tml.get("column_security_rules", {}).get("rules", []):
        if rule.get("column_name") == old_name:
            rule["column_name"] = new_name
    return csr_tml
```

**REMOVE** — drop rules referencing the removed column. **STOP CONDITION**: if any
rule is about to be deleted, surface in the impact report as a security-impact warning,
since dropping the rule changes who can see related data on the table:

```python
def remove_csr_column(csr_tml, removed_cols):
    rules = csr_tml.get("column_security_rules", {}).get("rules", [])
    csr_tml["column_security_rules"]["rules"] = [
        r for r in rules if r.get("column_name") not in removed_cols
    ]
    return csr_tml
```

### Retrieval mechanism — UNVERIFIED on champ-staging via v2 API

**What was tried and failed:**
- v2 `metadata/tml/export` with `export_associated:true` — returns model + tables only;
  no CSR docs even on tables (DM_CUSTOMER_BIRD) or models known to use them
- 17 additional flag combinations on the same endpoint (`export_dependent`,
  `export_full`, `export_metadata_associations`, `export_locale`,
  `export_column_security_rules`, `include_internal_metadata`, etc.) — all return
  exactly the same 9 docs as the baseline call
- v2 `metadata/tml/export-zip` and similar paths — 500 (not routed)
- v1 `callosum/v1/metadata/tml/export` with `export_associated=true` — 500
- v2 `metadata/search` enum — `COLUMN_SECURITY_RULES`, `COLUMN_SECURITY`, `RLS_POLICY`,
  `DATA_POLICY_RULE`, etc. all rejected with 400
- The cs_tools repo (https://github.com/thoughtspot/cs_tools), which is the canonical
  community tooling for TS, has zero references to `column_security_rules`,
  `column_alias`, or `monitor_alert` TML types in any code path

**Likely retrieval paths to investigate:**
- TS UI "Download TML" button → produces a multi-file zip including CSR; this is
  the path the user was almost certainly using when generating their example
- `/api/rest/2.0/vcs/git/branches/commit` → pushes a full TML bundle to git, which
  would include CSR if the source table has rules. This requires a configured git remote
  (which we don't have on champ-staging in this skill's context)
- A v2 build on a newer Cloud version (26.4.0+) that adds CSR to the standard
  `--associated` export — testing on champ-staging gave consistent results suggesting
  this build doesn't enable it

### Action

- [x] Document TML structure (this entry)
- [x] Document detection/update logic (above)
- [ ] Confirm retrieval mechanism — ask user to share the exact UI action or REST call
      that produced their example CSR file
- [ ] If UI-only: skill must rely on user pre-export. Document a "bring your own CSR
      bundle" mode where the user points the skill at a directory of TML files
- [ ] If git-commit-only: skill could trigger a vcs commit, fetch the resulting bundle,
      detect/update CSR, then re-import. Heavy lift; only worth doing if there's no
      direct API path
- [ ] Re-test on a Cloud cluster running 26.4.0+ to see if `--associated` returns CSR
      there (champ-staging build version unknown; may be older)

---

## #10 — Column alias TML (Step 4 / Step 9) — STRUCTURE KNOWN; RETRIEVAL UNVERIFIED 2026-04-26

ThoughtSpot has TWO distinct alias mechanisms — both are real and both need to be
handled by the skill:

1. **Inline aliases** (already implementable) — Model `columns[].name` vs `column_id`,
   Table `columns[].name` vs `db_column_name`, View `view_columns[].name` vs
   `search_output_column`. These come back in standard `--associated` exports and can
   be detected/updated using TML field rewrites.
2. **Per-locale alias TML** — a separate `column_alias` TML file at model scope, holding
   per-locale, per-org, per-group display names for each model column. **Retrieval via
   v2 API not verified** — same status as #9 (CSR).

### Mechanism 1: Inline aliases (verified)

**Layer A — Table TML**: `columns[].name` (TS-side label) vs `db_column_name` (DB column).
**Layer B — Model TML**: `columns[].name` (model-level alias) vs `column_id`
(`TABLE::DB_COL_NAME`).
**Layer C — View TML**: `view_columns[].name` vs `search_output_column`.
**Layer D (NOT a layer)** — Answer/Liveboard `answer_columns[].name` and
`chart.chart_columns[].column_id` reference the **model alias** directly. No second-level
aliasing inside Answers.

Verified on TEST_DEPENDENCY_MANAGEMENT: 28 model columns with `name != column_id-suffix`
(e.g. `"Customer Zipcode"` → `"DM_CUSTOMER_BIRD::ZIPCODE"`). The skill's existing
`rename_column_in_set()` already handles the `column_id.endswith("::OLD")` → `"::NEW"`
rewrite. View handling needs an extension (`search_output_column` is currently missed).

### Mechanism 2: Per-locale alias TML (structure documented; retrieval unverified)

This is a separate file at model scope. Filename pattern unknown but likely
`<MODEL_NAME>.column_alias` or similar (per user's example file). Holds per-locale,
per-org, per-group display name overrides for every aliased model column.

```yaml
# Filename pattern: <MODEL_NAME>.column_alias  (best guess)
# Lives at model scope; references columns by the model-level ALIAS (Mechanism 1 layer B).
column_alias:
  model:
    name: "Dunder Mifflin Sales"
    obj_id: DunderMifflinSales-0e4406c7   # ← <model>-<short_id>; not a raw GUID
  columns:
    - name: "Order ID"                     # ← references model.columns[].name (the alias)
      locales:
        - name: de-DE
          orgs:
            - name: Primary
              groups:
                - name: TS_WILDCARD_ALL    # ← all users in the org by default
                  entries:
                    - alias: "Bestellungs-ID"   # ← localized display name
                      description: ""
        - name: sv-SE
          orgs:
            - name: Primary
              groups:
                - name: TS_WILDCARD_ALL
                  entries:
                    - alias: "OrderId"
                      description: ""
        - name: en-AU
          orgs:
            - name: Primary
              groups:
                - name: TS_WILDCARD_ALL
                  entries:
                    - alias: "Order ID"        # ← matches the model-level name
                      description: ""
        - name: fr-FR
          orgs:
            - name: Primary
              groups:
                - name: TS_WILDCARD_ALL
                  entries:
                    - alias: "ID Commande"
                      description: ""
    - name: "zipcode"     # ← target column for our skill (case-sensitive vs model alias?)
      locales: ...
    # ...one entry per aliased column on the model
```

**Important properties:**
- The `columns[].name` references the **model alias** (e.g. `"Order ID"`), NOT the
  underlying table column (`ORDER_ID`) and NOT the model column_id (`DM_ORDER::ORDER_ID`).
- Each column has a `locales[]` list, with one entry per supported locale (de-DE, sv-SE,
  en-AU, fr-FR in the example).
- Each locale has `orgs[]` for multi-org tenants, then `groups[]` for per-group overrides.
  `TS_WILDCARD_ALL` is the default applies-to-everyone group.
- Each `entries[]` element has `alias` (the localized display string) and `description`.
- The `locales[].name` should match the user's `preferred_locale` (the user's auth payload
  from `/auth/session/user` exposes this — e.g. `en-AU` for the test user).
- A column not present in `column_alias.columns[]` falls through to its model-level `name`
  (Mechanism 1).

### Detection logic for Step 4 (when alias TML is available)

```python
def find_alias_column_uses(alias_tml, target_columns):
    """
    target_columns is the set of MODEL-LEVEL alias names being removed/renamed
    (e.g. {"Customer Zipcode"}).
    """
    cols = alias_tml.get("column_alias", {}).get("columns", [])
    return [c for c in cols if c.get("name") in target_columns]
```

### Update logic for Step 9

**RENAME (model alias)** — update the matching `columns[].name`:

```python
def rename_alias_column(alias_tml, old_name, new_name):
    for c in alias_tml.get("column_alias", {}).get("columns", []):
        if c.get("name") == old_name:
            c["name"] = new_name
        # The localized strings inside locales[].entries[].alias may also
        # need updating IF the user wants the localized aliases to track the
        # base name. By default the localized strings are independent of the
        # base name (e.g. "Order ID" → "Bestellungs-ID" doesn't change just
        # because the base name changes). Don't auto-rewrite localized aliases.
    return alias_tml
```

**REMOVE** — drop the entire `columns[]` entry for the removed column. The localized
aliases die with it; that's correct (the column doesn't exist anymore):

```python
def remove_alias_columns(alias_tml, removed_cols):
    cols = alias_tml.get("column_alias", {}).get("columns", [])
    alias_tml["column_alias"]["columns"] = [
        c for c in cols if c.get("name") not in removed_cols
    ]
    return alias_tml
```

### Retrieval mechanism — UNVERIFIED on champ-staging via v2 API

**Same probes as #9 — the v2 `--associated` flag does not return `column_alias` TML
files for any model tested.** Tested:
- `0e4406c7-d978-4be7-abd7-c34e8f7da835` (canonical Dunder Mifflin Sales — the model
  matching the user's example obj_id)
- `565032d4-f5d9-42c9-a6a4-91d5abef93f7` ("Aliasing Testing - Dunder Mifflin Sales & Inventory")
- `e5c84be6-ebbc-4ef0-9522-e124f0d29827` (TEST_DEPENDENCY_MANAGEMENT)

All three returned only model + base tables (8-9 docs). cs_tools has no references
to `column_alias`. Same retrieval-path candidates as #9: UI download, VCS commit
bundle, or a Cloud build version that enables this in `--associated`.

### Implications for the skill's RENAME logic

The current SKILL.md Step 3-N treats "rename a column" as a single concept. With both
inline aliases (Mechanism 1) AND localized alias TML (Mechanism 2) in play, RENAME has
multiple meanings:

| Source object the user picked | What "rename" means | Files to update |
|---|---|---|
| TABLE | rename `db_column_name` (or both `name` and `db_column_name` if they were equal) | table TML; every Model's `column_id` suffix |
| MODEL alias | rename `columns[].name` only | model TML; every Answer/Liveboard `answer_columns[].name`, `chart_columns[].column_id`, model formulas; **column_alias TML if present** |
| VIEW alias | rename `view_columns[].name` and `search_output_column` | view TML; consumers of the view |

Step 3-N currently picks "rename" without distinguishing. For a TABLE source, it's
unambiguous (DB column rename). For a MODEL source, the user should be asked whether
they want to also propagate through the column_alias TML (if one exists).

### Action

- [x] Document Mechanism 1 (inline) — already mostly implementable
- [x] Document Mechanism 2 (column_alias TML) per user-provided example
- [x] Document detection/update logic for Mechanism 2
- [ ] Confirm retrieval mechanism for Mechanism 2 — pending the same answer as #9
- [ ] Update SKILL.md Step 3-N to explicitly distinguish DB-column rename vs. alias rename
      when the source is a TABLE with `name != db_column_name`
- [ ] Update `rename_column_in_view()` to handle `search_output_column` in addition to
      `name` (currently only handles `name`)
- [ ] If the column_alias TML becomes retrievable: add detection to Step 4 and update
      logic to Step 9 RENAME path (REMOVE is automatic — drop the column entry)
- [ ] Decide: when localized aliases exist, should RENAME of the base name auto-rewrite
      the localized strings? Default to "no — they're independent" but make this a Step 6
      user choice when localizations exist for the renamed column

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
