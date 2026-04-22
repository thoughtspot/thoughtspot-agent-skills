# Open Items — ts-object-answer-promote

Unverified or partially verified API behaviors. Each item includes a status, test
procedure, and findings recorded against `champ-staging` (champagne-master-aws.thoughtspotstaging.cloud).

---

## Item 1 — Answer TML structure

**Skill steps affected:** Step 3, Step 4, Step 5

**Status:** VERIFIED ✓ — tested against champ-staging

**Finding:**

Top-level YAML key is `answer:`, with `guid:` at the document root (same as Model TML).

Full structure confirmed:

```yaml
guid: "{answer_guid}"
answer:
  name: "..."
  description: "..."
  dynamic_name: "..."        # present when name was auto-assigned
  display_mode: "TABLE_MODE | CHART_MODE"
  tables:
  - id: "Model Display Name"
    name: "Model Display Name"
    fqn: "{model_guid}"       # ← data source GUID is here
  search_query: "..."
  answer_columns:
  - name: "Column Name"       # display names only; no column_type or aggregation
    format:                   # optional display formatting (PERCENTAGE etc.)
  formulas:
  - id: "formula_Name"        # "formula_" + name, spaces preserved
    name: "Name"
    expr: "[col_ref] / [other_col]"   # bare display names, NO TABLE::col format
    was_auto_generated: false          # true = AI-created; false = user-created
  parameters:
  - id: "uuid"
    name: "Param Name"
    data_type: INT64
    default_value: "10"
    description: ""
  cohorts:                    # sets — see Item 5
  - name: "Set Name"
    # ... (additional set fields)
  table:                    # table visualization config
  chart:                    # chart visualization config
```

**Key findings for the skill:**

1. Data source GUID is at `answer.tables[0]["fqn"]` — use directly in Step 5.
2. **No `column_type` or `aggregation` in formula entries.** Must infer from the formula
   expression (aggregate functions → MEASURE; conditional/string → ATTRIBUTE) or ask the user.
3. `was_auto_generated: true` means ThoughtSpot auto-derived the formula. Flag these to
   the user — they are often wrapper formulas not meaningful on their own (e.g. `( [Revenue] )`).
4. Formula expressions use **bare `[display_name]`** references, not `[TABLE::col]`.
   Formula inter-references use the formula `id`: `[formula_Vivun Deliverables Count(all)]`.
5. Parameter references in formulas look identical to column references: `[Param Name]`.
   Distinguish them by checking against `parameters[].name`.

---

## Item 2 — Edit permissions in metadata search response

**Skill steps affected:** Step 6 (access check)

**Status:** PARTIALLY VERIFIED — tested against champ-staging

**Finding:**

The `ts metadata search` (REST API v2 `POST /api/rest/2.0/metadata/search`) response
**does not include an explicit permissions field** in the returned metadata objects.

The full response structure is:
```json
{
  "metadata_id": "...",
  "metadata_name": "...",
  "metadata_type": "LOGICAL_TABLE",
  "metadata_obj_id": "...",
  "metadata_detail": null,
  "metadata_header": {
    "id": "...",
    "name": "...",
    "type": "WORKSHEET",
    "author": "...",
    "authorName": "...",
    ...
    "csrProtected": true
  },
  "stats": null
}
```

No `sharing_access`, `access_level`, `permissions`, or similar field was found.

`POST /api/rest/2.0/security/metadata/fetch` returned HTTP 500 on champ-staging —
endpoint may not be available on this instance version.

**Current recommendation for Step 6:**

Proceed without a pre-flight permission check. Rely on the import response for
access errors:
- If import returns HTTP 403 or `UNAUTHORIZED` status → report the permission error
  to the user and stop.
- If the `metadata_header.author` matches the current user's ID (from `ts auth whoami`),
  the user is the owner and almost certainly has edit access — skip the warning.

**Still to test:**
- [ ] Whether a shared Model with READ_ONLY access can be found by a non-owner and what
  the import returns (403 vs a ThoughtSpot-level error message)
- [ ] Whether `POST /api/rest/2.0/security/metadata/fetch` works on newer instance versions

---

## Item 3 — Bare display-name column references in Model formulas

**Skill steps affected:** Step 9 (column reference mapping)

**Status:** PARTIALLY VERIFIED — `TABLE::COLUMN_ID` translation confirmed working; bare names untested

**Finding:**

Exported Model formulas from champ-staging use `[TABLE::col]` format (e.g.
`[DM_ORDER_DETAIL::LINE_TOTAL]`). Answer formula expressions use bare `[display_name]`
format (e.g. `[Amount]`).

**Live test result (champ-staging, Answer `03dc7ccb-74d6-4fbf-9449-e58e135d3964`, Model `3b0de9da`):**

Translating bare Answer formula refs to `[TABLE::COLUMN_ID]` using the Model's `col_by_name`
→ `column_id` map **works**. The two promoted formulas imported and resolved correctly:

- `sum ( [Amount] ) / sum ( [Quantity]  )` → `sum ( [DM_ORDER_DETAIL::LINE_TOTAL] ) / sum ( [DM_ORDER_DETAIL::QUANTITY] )`
- `sum ( [Amount] ) - [Answer Paramerer]` → `sum ( [DM_ORDER_DETAIL::LINE_TOTAL] ) - [Answer Paramerer]` (parameter ref left as-is)

**Current skill approach (updated in Step 9):** Translate bare display-name refs to
`[TABLE::COLUMN_ID]` using the `col_by_name` → `column_id` lookup. Parameter references
(tokens matching `parameters[].name`) are left unchanged.

**Still to test:**
- [ ] Whether bare display-name refs (untranslated) also work in Model formula import — the safe approach is translation, so this is low priority

---

## Item 4 — Answers embedded in Liveboards (not standalone objects)

**Skill steps affected:** Step 2 (Find the Answer)

**Status:** UNTESTED

**Why it matters:** `ts metadata search --type ANSWER` returns only standalone saved
Answers. Answers created directly inside a Liveboard are not independent metadata
objects — they live inside the Liveboard TML and will not appear in Answer search results.

If the user's formula lives in a Liveboard-embedded Answer, Step 2 returns no results
and the user will be confused about why their Answer can't be found.

**Test procedure:**

1. Identify a Liveboard that contains at least one visualization with a custom formula.

2. Check whether that visualization appears in a standalone Answer search:
   ```bash
   source ~/.zshenv && ts metadata search \
     --type ANSWER \
     --name "%{viz_name}%" \
     --profile "{profile_name}"
   ```

3. Export the Liveboard TML and inspect structure:
   ```bash
   source ~/.zshenv && ts metadata search \
     --type LIVEBOARD \
     --name "%{liveboard_name}%" \
     --profile "{profile_name}"

   source ~/.zshenv && ts tml export {liveboard_guid} \
     --profile "{profile_name}" \
     --fqn
   ```

4. Inspect: where are individual visualizations in the Liveboard TML? Do they each
   have a `formulas[]` section? Is it the same structure as standalone Answer TML?

**What to record:**
- [ ] Does `ts metadata search --type ANSWER` return Liveboard-embedded Answers?
- [ ] What is the top-level section in Liveboard TML that represents embedded Answers?
- [ ] Do embedded Answer formulas use the same `formulas[]` / `expr` structure?
- [ ] Is there a way to search Liveboards by the name of an embedded visualization?

**Proposed skill change if confirmed:**

Add a fallback branch to Step 2:

```
No standalone Answers matched "{search_term}".

  The formula may live inside a Liveboard visualization. Liveboard-embedded Answers
  are separate from standalone saved Answers.

  Options:
    L  Search for a Liveboard instead
    R  Try a different search term
    G  Enter a GUID directly

  Enter L / R / G:
```

If L: export the Liveboard TML, find the embedded visualization's `formulas[]`, and
continue from Step 4 with those formulas.

**Finding:**

```
[Record results here after testing]
```

---

## Item 5 — Sets (cohorts) in Answer TML — promotion path

**Skill steps affected:** Step 3, Step 4

**Status:** VERIFIED (structure) / UNTESTED (promotion path)

**Finding — structure:**

Sets appear in Answer TML as `cohorts[]`, not in `formulas[]`. They also appear in
`answer_columns[]` by name. Two types confirmed:

- **Column Set (BIN_BASED):** Uses `config.cohort_type: SIMPLE`, `config.cohort_grouping_type: BIN_BASED`, with `config.bins`
- **Query Set (COLUMN_BASED):** Uses `config.cohort_type: ADVANCED`, `config.cohort_grouping_type: COLUMN_BASED`, with an embedded `answer:` section and `config.return_column_id`

Neither type is a `formulas[]` entry. The current skill scope (`formulas[]` only) correctly
excludes sets. The skill must:
1. Detect set column names (`cohort[].name`) and exclude them from the formula selection list
2. Explain to the user that sets require separate promotion (standalone cohort TML)

**Promotion path (untested):**

A reusable set has its own TML with a top-level `cohort:` key and a GUID. To promote an
answer-level set to a reusable set:
1. Extract the `cohorts[]` entry from the Answer TML
2. Wrap it in `cohort:` with a new GUID (or no GUID for first import)
3. Add `model:` / `models:` reference to the target Model
4. Import via `ts tml import`

**Test procedure for promotion:**
- [ ] Build a standalone cohort TML from an answer-level `cohorts[]` entry
- [ ] Import it: does ThoughtSpot accept it as a new reusable set?
- [ ] After import, can the set be used as a column in a new Answer on the same Model?

**Finding:**

```
[Record results here after testing]
```

---

## Item 7 — Parameter promotion to Model TML

**Skill steps affected:** Step 4, Step 8, Step 10

**Status:** VERIFIED ✓ — tested against 172.32.68.104:8443 (Snowflakeddpmodel)

**Why it matters:** Answer-level parameters are scoped to the Answer. When a formula
references a parameter (e.g. `[today]`), promoting just the formula without the
parameter leaves a dangling reference in the Model — the formula will fail at query time.

The fix (implemented): on choosing P in Step 4, the Answer parameter is copied into
`model.parameters[]` with the same `name`, `data_type`, `description`, and either
`default_value` or `dynamic_default_date`. The Answer-level UUID is omitted — ThoughtSpot
assigns a new one on import.

**Test procedure:**

1. Find an Answer with a formula that references a parameter (e.g. `[today]`).
2. Run the skill and choose **P** when prompted.
3. Verify the import succeeds and the parameter appears in the Model's Columns section.
4. Open a new Answer on the Model — confirm the parameter is available and the formula resolves.

**What to record:**
- [ ] Does ThoughtSpot accept `dynamic_default_date` in `model.parameters[]` on import?
- [ ] If not, does falling back to a static `default_value` work?
- [ ] Does the formula correctly resolve against the new Model-level parameter at query time?
- [ ] What happens if the parameter name in the Model already exists but with a different `data_type`?

**Finding:**

- `dynamic_default_date` is accepted in `model.parameters[]` on import ✓
- Formula resolves correctly against the promoted Model-level parameter ✓
- Import response: `status_code: OK`, `columns_added: 1`
- Tested with Answer parameter `today` (DATE, `dynamic_default_date.type: TODAY`) and formula `form today` expr `[today]`

Open items resolved:
- [x] `dynamic_default_date` accepted at model level on import
- [ ] Confirmed formula resolves at query time (visual verification pending — user to open Model URL)
- [ ] Behaviour when parameter already exists with different `data_type` still untested

---

## Item 6 — `--subtype MODEL` not valid on all instance versions

**Skill steps affected:** Step 5 (Find target Model)

**Status:** VERIFIED — tested against champ-staging

**Finding:**

`ts metadata search --subtype MODEL` returns HTTP 400 on champ-staging. The API rejects
`"subtypes": ["MODEL"]` for this instance version.

On champ-staging, Models appear with `metadata_header.type = "WORKSHEET"` and
`metadata_header.contentUpgradeId = "WORKSHEET_TO_MODEL_UPGRADE"`.

**Skill fix (already applied to Step 5 in SKILL.md):** Use `--subtype WORKSHEET` instead
of `--subtype MODEL`. This returns both legacy Worksheets and upgraded Models. If the
instance supports `MODEL` as a subtype, it is also a subset of what `WORKSHEET` returns.

To distinguish Models from Worksheets in the response:
- `metadata_header.contentUpgradeId = "WORKSHEET_TO_MODEL_UPGRADE"` → Model
- `metadata_header.worksheetVersion = "V2"` → Model (V1 = legacy Worksheet)
- `metadata_header.type = "WORKSHEET"` with either marker above → Model

The skill does not need to filter on this — listing both and letting the user pick is
sufficient. Label them as `[MODEL]` or `[WORKSHEET]` using the markers above.
