# ThoughtSpot Alert TML — Structure Reference

How a ThoughtSpot Monitor Alert (scheduled or threshold-based notification) is
represented in TML.

Alerts reference Answers or Liveboard visualizations by GUID. They do not reference
Models, Tables, or columns directly — their dependency chain is:
`Alert → Answer/Liveboard viz → Model → Table`.

**Dependency tracking implications:**
- Removing a column from an Answer does not break an Alert's GUID reference, but the
  Alert's metric may produce different results or errors at runtime.
- Alerts are included in the impact report as informational HIGH-risk items when the
  Answer or Liveboard they reference is being modified — they cannot be fixed by TML
  modification (the GUID reference stays valid).
- If a referenced Answer is deleted (not just modified), the Alert breaks. The skill
  does not delete Answers; this case is out of scope.

**Metadata search identifiers:**
- `type`: Not yet confirmed for `ts metadata search` — see open-items.md for test script.
  The TML container is `monitor_alert`.

**Note on TML structure:** The Alert TML uses a list as the root value under
`monitor_alert:`, unlike other TML types that use a mapping. The `guid` appears
inside each list item, not at the document root.

---

## Full Alert TML Structure

```yaml
monitor_alert:
- guid: "<alert_guid>"
  name: "Revenue Drop Alert"

  frequency_spec:
    cron:
      second:       0
      minute:       0
      hour:         8
      day_of_month: "*"
      month:        "*"
      day_of_week:  1       # 0 = Sunday … 6 = Saturday
    time_zone:           "America/Los_Angeles"
    start_time:          1700000000    # Unix epoch
    end_time:            1800000000    # Unix epoch (omit for no end)
    frequency_granularity: DAILY       # HOURLY | DAILY | WEEKLY | MONTHLY

  creator:
    username:   "admin@company.com"
    user_email: "admin@company.com"

  condition:
    # Simple threshold condition (omit entire condition: block for scheduled-only alerts)
    simple_condition:
      comparator: COMPARATOR_LT        # GT | LT | GEQ | LEQ | EQ | NEQ
      threshold:
        value: 10000

    # OR: percentage-change condition (requires time-series column in metric)
    # percentage_change_condition:
    #   comparator: PERCENTAGE_CHANGE_COMPARATOR_DECREASES_BY
    #   threshold:
    #     value: 15

  metric_id:
    # Exactly ONE of the three options below:

    # Option A — Alert on a saved Answer
    answer_id: "<answer_guid>"

    # Option B — Alert on a specific Liveboard visualization
    # pinboard_viz_id:
    #   pinboard_id: "<liveboard_guid>"
    #   viz_id:      "<visualization_guid>"

    # Option C — Alert on a personalized view (filtered view of an Answer/Liveboard)
    # personalised_view_id: "<view_guid>"

  subscribed_user:
  - username:   "analyst@company.com"
    user_email: "analyst@company.com"
  - username:   "manager@company.com"
    user_email: "manager@company.com"

  # personalised_view_info — only present when metric_id.personalised_view_id is set
  personalised_view_info:
    tables:
    - id:   "Sales_Model"
      name: "Sales_Model"
      fqn:  "<model_guid>"
    filters:
    - column:
      - "Sales_Model::Region"
      oper: in
      values:
      - "North America"
      is_mandatory:   false
      is_single_value: false
      display_name:   ""
    - column:
      - "Sales_Model::Sale_Date"
      date_filter:
        type: EXACT_DATE_RANGE
        oper: between
        date_range:
          start_date: "2024-01-01"
          end_date:   "2024-12-31"
      display_name: ""
```

---

## Field Reference

| Field | Purpose | Notes |
|---|---|---|
| `monitor_alert[].guid` | Alert GUID | Inside list item, NOT at document root |
| `monitor_alert[].name` | Alert display name | |
| `frequency_spec.cron.*` | Cron schedule | second 0–59, minute 0–59, hour 0–23, dom 1–31, month 1–12, dow 0–6 |
| `frequency_spec.time_zone` | Delivery timezone | Full name format required: `"America/Los_Angeles"`, not `"PST"` |
| `frequency_spec.frequency_granularity` | Delivery cadence | HOURLY \| DAILY \| WEEKLY \| MONTHLY |
| `creator.username` / `.user_email` | Alert owner | Immutable after creation; admin-only field |
| `condition.simple_condition.comparator` | Comparison operator | COMPARATOR_GT \| LT \| GEQ \| LEQ \| EQ \| NEQ |
| `condition.simple_condition.threshold.value` | Numeric threshold | Omit `condition:` entirely for scheduled-only alerts |
| `condition.percentage_change_condition` | % change threshold | Requires a time-series keyword in the metric |
| `metric_id.answer_id` | Source Answer GUID | Mutually exclusive with `pinboard_viz_id` and `personalised_view_id` |
| `metric_id.pinboard_viz_id.pinboard_id` | Source Liveboard GUID | Must be paired with `viz_id` |
| `metric_id.pinboard_viz_id.viz_id` | Visualization GUID | The specific viz within the Liveboard |
| `metric_id.personalised_view_id` | Personalized View GUID | LOGICAL_TABLE subtype reference |
| `subscribed_user[].username` / `.user_email` | Alert recipients | Must be valid ThoughtSpot users |
| `personalised_view_info.tables[].fqn` | Data source GUID | GUID of the underlying Model/Table |
| `personalised_view_info.filters[].column[]` | Filter column | Format: `<table_name>::<column_name>` |

---

## Dependency Management Notes

Alerts are **read-only** from the dependency manager's perspective — the skill includes
them in the impact report but does not modify their TML:

**When removing a column from a Model/Table:**
- The Alert is not directly broken (it references an Answer GUID, not a column).
- If the affected Answer is in `objects_to_update`, note any Alerts referencing that
  Answer in the impact report under a "Downstream Alerts" section.
- Risk: MEDIUM if the metric column is the one being removed — the Alert may evaluate
  to null/error at runtime. Show the alert URL and advise the user to verify.

**When repointing an Answer to a new Model:**
- Same as above — the Alert GUID reference remains valid.
- The metric may produce different values if the Answer now queries different data.

**Finding Alerts that reference an Answer:**
There is no direct metadata search for `monitor_alert` type via the current `ts` CLI.
See [open-items.md](../../../agents/claude/ts-dependency-manager/references/open-items.md) #6
for the test script to find Alerts via TML scan or API.

**`personalised_view_info.filters[].column` format:** `<table_name>::<column_name>` —
the same `TABLE::COLUMN` format used in View TML column IDs. For a RENAME operation, if
a personalized view filter references the renamed column, the Alert TML must be updated.
