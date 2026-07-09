# PR1 Databricks Docs Findings — retrieved 2026-07-08

## Sources
- https://docs.databricks.com/aws/en/business-semantics/metric-views/create-edit — retrieved 2026-07-08
- https://docs.databricks.com/aws/en/business-semantics/metric-views/yaml-reference — retrieved 2026-07-08
- https://docs.databricks.com/aws/en/business-semantics/metric-views/advanced-techniques#window-measures — retrieved 2026-07-08 (directly linked from `create-edit`'s window-measures section — fetched per Step 1 to get the full `window:` grammar the `yaml-reference` page states only partially inline)

## materialization: block
- Top-level key: **yes** — sibling of `source:`, `fields:`/`dimensions:`, `measures:`, `joins:`, and `filter:`.
- Fields:
  - `schedule` (string, optional) — "Refresh schedule. Uses the same syntax as the schedule clause on materialized views." Example seen: `every 6 hours`.
  - `mode` (string, required) — must be `relaxed` (the yaml-reference page documents no other value today).
  - `materialized_views` (array, required) — list of materialization definitions, each with:
    - `name` (string, required)
    - `type` (string, required) — `aggregated` or `unaggregated`
    - `dimensions` (array, conditional) — field names to materialize
    - `measures` (array, conditional) — measure names to materialize
  - Verbatim example from `yaml-reference`:
    ```yaml
    materialization:
      schedule: every 6 hours
      mode: relaxed
      materialized_views:
        - name: baseline
          type: unaggregated
        - name: daily_status_metrics
          type: aggregated
          dimensions:
            - order_date
            - order_status
          measures:
            - total_revenue
            - order_count
    ```
- Default when absent: no `materialization:` block means no automatic query acceleration / materialized views are created for the metric view — the field is purely additive/optional (the page frames it as configuring "automatic query acceleration," not a behavior that changes query semantics when absent).
- Status: **Public Preview** — quote: "Public Preview / This feature is in [Public Preview](/aws/en/release-notes/release-types). / The `materialization` field configures automatic query acceleration using materialized views." (from `yaml-reference`). The `create-edit` page does not mention `materialization:` at all — it is documented only on the `yaml-reference` page.

**Repo cross-check:** `databricks-metric-view.md` does not document `materialization:` anywhere today (it is only referenced as a forward-looking note at line 99, "Newer GA constructs (top-level `materialization:`, ...) are tracked in BL-032"). This confirms BL-032/BL-064 finding #13 ("materialization: block not documented") is still accurate as of this retrieval — the findings above are new content for Task 6 to add, not a correction of an existing repo claim. The `ts-databricks-properties.md:1` currency anchor's characterization of materialization as "Public Preview" is **confirmed correct**.

## window: block — confirmation vs. repo's existing claims
- `range` values: `current`, `cumulative`, `trailing <n> <unit> [inclusive|exclusive]`, `leading <n> <unit> [inclusive|exclusive]`, `all` — **matches** databricks-metric-view.md:441-447 (all 5 values present, same names). Definitions confirmed verbatim from `advanced-techniques`:
  - `current`: "Rows where the window ordering value equals the anchor row's value." (repo's "Current period only" — consistent paraphrase)
  - `cumulative`: "All rows where the window ordering value is less than or equal to the anchor row's value." (repo's "Running total from start to current period" — consistent paraphrase)
  - `trailing <n> <unit>`: "Rows from the anchor row going backward by the specified time units, for example `trailing 7 day`." (repo's "Rolling look-back window... ending at the anchor row" — consistent)
  - `leading <n> <unit>`: "Rows from the anchor row going forward by the specified time units, for example `leading 3 month`." (repo's "Rolling look-ahead window... starting at the anchor row" — consistent; repo had flagged this as "verified 2026-07 — spec only," which this fetch reconfirms as spec-documented)
  - `all`: "All rows regardless of the window ordering value." (repo's "entire partition, unbounded in both directions" — consistent; also spec-only per repo, reconfirmed)
  - **New detail not previously in the repo table:** the `inclusive|exclusive` modifier is documented as applying only to `trailing` and `leading` — `all`, `current`, and `cumulative` do **not** accept it (the yaml-reference page's syntax pattern shows the modifier only in the `trailing`/`leading` grammar). The repo's prose at line 449 already says "`trailing` and `leading` ranges accept an optional `inclusive|exclusive` modifier," which is consistent, but doesn't explicitly say the other three ranges reject it — worth tightening in Task 6's new section.
- `offset` syntax: **confirmed**, with one addition. Repo (line 457) says `<-N period>` where period is "month, year, day, etc." The yaml-reference page gives the closed unit list: `day`, `days`, `month`, `months`, `year`, `years` — no `week` or `quarter`. This is an addition/tightening (repo's "etc." was open-ended; the real vocabulary is closed and only has 3 unit families, singular+plural) rather than a contradiction. Offset behavior also newly confirmed: "If the shifted frame falls outside the available data, the measure evaluates to NULL."
- `semiadditive`: **confirmed** — "Possible values: `first` and `last`," matching databricks-metric-view.md:510 exactly.
- `inclusive|exclusive` default: **confirmed as `exclusive`** — quote: "The default is `exclusive`." (yaml-reference); `advanced-techniques` independently states "`exclusive` (default)" for the same behavior (anchor row not included). This matches databricks-metric-view.md:452's existing claim ("Default: `exclusive`") word for word — the repo's citation trail (Runtime 18.1 + YAML 1.1; DBSQL 2026.10 preview, release note 2026-03-26) was not independently re-verified in this pass (Step 2's release-note backup search was not needed since both canonical pages resolved and gave a direct quote), but the value itself is now doc-confirmed rather than release-note-only.
- `window:` status label: **Experimental** — quote: "Experimental / This feature is [Experimental](/aws/en/release-notes/release-types). / The `window` field defines windowed, cumulative, or semiadditive aggregations for measures." (yaml-reference). The `advanced-techniques` page's window-measures section independently shows the same "Experimental" badge. This confirms `ts-databricks-properties.md:1`'s anchor claim ("window Experimental status") is still accurate.

## Open questions for the live experiment (Tasks 3-5)
- Whether `mode:` under `materialization:` genuinely accepts only `relaxed` today, or whether other modes exist but are undocumented/gated by runtime version — the docs show no alternative value and no runtime-version gate note (contrast with `offset`, which explicitly documents its Runtime 18.1+ gate). A live `CREATE VIEW ... WITH METRICS` attempt with a non-`relaxed` mode would confirm whether the API 400s or silently accepts it.
- Whether `dimensions`/`measures` are truly optional on a `type: unaggregated` entry (the `baseline` example omits both) but required/enforced on `type: aggregated` entries, or whether omitting them on `aggregated` just materializes nothing — the docs mark them "Conditional" without stating the exact conditionality rule.
- Whether specifying `inclusive`/`exclusive` on a `current`, `cumulative`, or `all` range is a hard parse error (`PARSE_SYNTAX_ERROR`) or silently ignored — the docs only show the modifier in the `trailing`/`leading` grammar and don't state what happens if it's misapplied elsewhere.
- Whether `offset` composes with `range: trailing`/`leading`/`all` (all worked examples on both fetched pages pair `offset` only with `range: current`) — needed before the parser can safely allow/reject that combination.
- Whether an existing live-instance Metric View can be round-tripped through `DESCRIBE TABLE EXTENDED` with a `materialization:` block intact (confirms the CLI/API surfaces the block back in `View Text` / `metric_view.raw_yml` the same way other fields do) — none of the repo's existing verified worked examples (`ts-to-databricks.md`, `ts-from-databricks*.md`) include a `materialization:` block, so this is fully unverified against a live instance.
- The actual query-engine behavior of `leading`/`all` ranges (row-count semantics at partition boundaries, NULL-padding behavior analogous to `offset`'s documented NULL-on-out-of-range) — the docs give syntax and one-line semantics but not edge-case behavior; this is exactly the class of thing BL-032 already flags as "ThoughtSpot translation pending live verification."
