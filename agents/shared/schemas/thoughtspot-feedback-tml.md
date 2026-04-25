# ThoughtSpot Feedback (Coaching) TML — Structure Reference

How ThoughtSpot NLS Feedback (also called "Coaching") is represented in TML.
Feedback annotations teach ThoughtSpot's NLP search how to interpret specific phrases
and map them to columns, formulas, or query patterns within a Model.

The `nls_feedback` TML is unusual: the `guid` at the document root is the GUID of the
**parent Model** (not the feedback object itself). There is one `nls_feedback` TML
export per Model that has coaching defined.

**Dependency tracking implications:**
- Coaching is attached to a specific Model. If a column or formula referenced in a
  feedback entry is removed or renamed, the coaching entry becomes stale (it references
  a non-existent column/formula).
- The skill includes feedback in the impact report as a LOW-risk informational item
  when the parent Model is being changed. Stale coaching entries do not break the
  Model but may produce incorrect NLP search suggestions.
- Feedback TML can be exported and imported via the standard TML API.

**Metadata search identifiers:** Not available via `ts metadata search` (feedback is
attached to a Model, not a separately searchable object). Export via the Model GUID
using `--associated` flag.

---

## Full Feedback TML Structure

```yaml
guid: "<model_guid>"          # GUID of the PARENT MODEL — not a feedback object GUID
nls_feedback:
  feedback:
  - id: "1"
    type: BUSINESS_TERM        # BUSINESS_TERM | REFERENCE_QUESTION
    access: GLOBAL             # GLOBAL | USER
    feedback_phrase: "average revenue"
    parent_question: "show average revenue over last 3 years"
    search_tokens: "[average formula]"
    formula_info:
    - name:       "average formula"
      expression: "group_average ( Revenue , Color )"
    rating:       UPVOTE        # UPVOTE | DOWNVOTE
    display_mode: UNDEFINED
    chart_type:   KPI
    axis_config:
    - "y":
      - "average formula"

  - id: "2"
    type: REFERENCE_QUESTION
    access: GLOBAL
    feedback_phrase: "top customers"
    parent_question: "who are the top 10 customers by revenue"
    search_tokens: "[Customer Name] [Revenue] top 10"
    rating: UPVOTE
    display_mode: TABLE_MODE
    chart_type: TABLE
```

---

## Field Reference

| Field | Purpose | Notes |
|---|---|---|
| `guid` | Parent Model GUID (document root) | This is the Model's GUID, not a feedback GUID |
| `nls_feedback.feedback[].id` | Entry identifier | String; unique within the feedback block |
| `feedback[].type` | Feedback category | `BUSINESS_TERM` (column/formula synonym) or `REFERENCE_QUESTION` (full query pattern) |
| `feedback[].access` | Visibility scope | `GLOBAL` (all users) or `USER` (creator only) |
| `feedback[].feedback_phrase` | The phrase being taught | Short phrase the user typed |
| `feedback[].parent_question` | Full original question context | The complete query that produced this feedback |
| `feedback[].search_tokens` | Column/formula references | Uses `[...]` bracket syntax — references Model columns and formula IDs |
| `feedback[].formula_info[].name` | Referenced formula name | Must match a `formulas[].name` in the parent Model |
| `feedback[].formula_info[].expression` | Formula expression | ThoughtSpot formula syntax |
| `feedback[].rating` | Feedback polarity | `UPVOTE` (correct mapping) or `DOWNVOTE` (incorrect mapping) |
| `feedback[].display_mode` | Chart/table context | `TABLE_MODE`, `CHART_MODE`, or `UNDEFINED` |
| `feedback[].chart_type` | Chart type context | `KPI`, `TABLE`, `COLUMN`, `BAR`, etc. |
| `feedback[].axis_config` | Axis assignments | Maps column/formula names to chart axes |

---

## Dependency Management Notes

**When removing a column from a Model:**
- Scan `nls_feedback.feedback[].search_tokens` for the column name in `[...]` brackets.
- Scan `nls_feedback.feedback[].formula_info[].expression` for column references.
- Entries with stale references should be removed from the feedback block.
- Action: remove the stale feedback entry from the list — importing a feedback TML with
  a reference to a non-existent column is likely to fail or produce silent errors.

**When renaming a column in a Model:**
- Update `search_tokens` — replace `[old_name]` with `[new_name]`.
- Update `formula_info[].expression` — replace bare column references.

**Exporting feedback TML:**
Feedback TML is exported as part of the Model's `--associated` export, not as a
standalone export. It will appear as a separate item in the `--parse` output with
`type: "nls_feedback"`.

**Example export command:**
```bash
ts tml export {model_guid} --profile "{profile_name}" --fqn --associated --parse
```

The feedback item will appear alongside the model and table items in the response.
Filter by `item["type"] == "nls_feedback"` to extract it.

**Finding feedback for a Model:**
```python
export_result = json.loads(subprocess.run(...).stdout)
feedback_items = [item for item in export_result if item["type"] == "nls_feedback"]
```
