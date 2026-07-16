# Stage 2 — Dashboards → Liveboards (ts-convert-from-tableau)

**This file is loaded on demand.** The main `SKILL.md` covers Stage 1 (parse → tables →
model → validate → import → confirm, Steps 1–7.5) and the wrap-up (Steps 11.5–12). This
file holds the heavier Stage 2 detail — parsing Tableau dashboard layout, generating the
Liveboard TML, styling, and import (Steps 9–11) — so a **model-only run never loads it**.

**When to read this:** only after Step 8 in `SKILL.md`, when the user answers **Y** to
"migrate dashboards". Prerequisites: Steps 1–7.5 are complete — the model is imported and
the user has confirmed it. Steps 8 (the migrate/skip + separate-vs-tabbed decision) stays
in `SKILL.md`.

**When you finish Step 11 here, return to `SKILL.md` Step 11.5** (Formula Coverage Answers),
then Step 12 (Migration Report). Those steps run for model-only and dashboard runs alike,
which is why they stay in the main file.

## References (Stage 2)

| File | Purpose |
|---|---|
| [../../../shared/schemas/thoughtspot-liveboard-tml.md](../../../shared/schemas/thoughtspot-liveboard-tml.md) | Liveboard TML structure reference |
| [../../../shared/schemas/thoughtspot-answer-tml.md](../../../shared/schemas/thoughtspot-answer-tml.md) | Answer/visualization TML structure |
| [liveboard-style-themes.md](liveboard-style-themes.md) | Step 10.5 curated themes — brand tokens + per-chart `viz_style` color palettes |

---

## Step 9 — Parse Dashboard Layout and Map to Grid

### 9a. Zone extraction

For each `<dashboard>` element in the TWB, walk `<zones>` → `<zone>` elements
recursively. For each leaf zone, extract:

| Field | Source |
|---|---|
| `zone_id` | `id` attribute |
| `zone_type` | `type` attribute (`text`, `title`, `viz`, `bitmap`, `web`, `extension`, `metric`) |
| `worksheet_name` | `name` attribute (for `viz` zones) |
| `x`, `y`, `w`, `h` | `x`, `y`, `w`, `h` attributes (Tableau uses 0–100,000 coordinate space) |
| `text_content` | `<formatted-text>` child text (for `text` / `title` zones) |

Classify each zone:
- **Chart zones**: a worksheet viz — a leaf zone carrying a `name` (worksheet name) and no
  more specific sub-type. These become visualization tiles.
- **Text/title zones**: `type="text"` or `type="title"` → becomes a note tile (Step 10c).
- **Skip**: `type="bitmap"` (images), `type="web"`, `type="extension"`, `type="metric"`,
  `type="filter"` (quick filters — handled via liveboard `filters[]`, not as tiles),
  `type="paramctrl"` (parameter controls — the migrated model `parameters[]` cover these),
  `type="color"`/`type="legend"` (legend zones — ThoughtSpot draws its own),
  `type="flipboard"`/`type="flipboard-nav"` (Tableau Story-style flipboards — no ThoughtSpot
  liveboard equivalent). **Before skipping a flipboard/story dashboard, salvage its content:**
  a flipboard usually re-presents worksheets already migrated from another dashboard (check —
  it may reference **no unique worksheets**), but it often carries **narrative captions**
  (analyst commentary). Migrate any unique worksheets as vizzes and preserve the narrative
  text as **note tiles** rather than losing it; only the flip *interaction* itself is dropped.
  A single
  worksheet often emits several zones (the viz plus its color/filter companions); keep the
  viz zone, drop the companions, and de-duplicate by worksheet name.

### 9b. Worksheet shelf data

For each chart zone's `worksheet_name`, find the corresponding `<worksheet>` element
in the TWB. Extract:
- Columns shelf (`<datasource-dependencies>` → `<column>` with shelf `column`)
- Rows shelf → shelf `row`
- Mark type: `<mark class="{type}">` (bar, line, circle/scatter, square, text, pie)
- Color encoding: column on `color` shelf
- Size encoding: column on `size` shelf
- Aggregation: from column `caption` prefix (`SUM(...)`, `AVG(...)`, etc.)

### 9c. Map coordinates to ThoughtSpot 12-column grid

ThoughtSpot liveboards use a **12-column responsive grid**. Tableau dashboards use
absolute pixel coordinates (0–100,000 range).

Use a band-based approach:

1. **Group zones by y-band** — zones within 2,000 units of each other vertically are
   in the same row band.
2. **Sort bands** from smallest y to largest y (top to bottom).
3. **Within each band**, sort zones by x (left to right).
4. **Assign columns**: divide 12 columns proportionally by each zone's `w` relative to
   the total dashboard width. Round to nearest integer; ensure columns sum to 12.
5. **Assign height**: convert Tableau `h` to ThoughtSpot height units (1 unit ≈ 1/20th
   of the dashboard height; minimum 4 units).
6. **Assign y position**: start from 0; each new row band starts at the bottom of the
   previous band.

Save the grid layout as a list of tiles with `zone_id`, `zone_type`, `worksheet_name`,
`col`, `col_span`, `row_span`, `y`.

### 9d. Orphan worksheets — surface and prompt to include

A workbook often contains worksheets that aren't placed on **any** dashboard being migrated.
By default they produce no tile — but the author built them for a reason, and the model fully
supports them, so the user should **decide**, not have them silently dropped (surface →
recommend → resolve).

1. **Detect.** Compute the set of worksheets referenced by the dashboard(s) being migrated
   (the `name` on each chart zone). Any `<worksheet>` in the TWB not in that set is an orphan.
2. **Describe each.** Read the orphan's shelves (as in 9b) and state, in one line, **what it
   shows** and its **ThoughtSpot equivalent** — not just the name. E.g.
   *"`Attrition Yes/No Count` — pie of headcount split by Attrition (Yes/No) → PIE
   `[Attrition] [Total Employee Count]`."* A bare name leaves the user unable to choose.
3. **Recommend.** Say whether each looks worth adding (a meaningful, distinct view) or is
   likely a draft/superseded by a tile already on the dashboard.
4. **Prompt** (per the references — ask, don't assume). Offer: add **all**, add a **subset**
   (name which), or **none**. For any the user picks, build them as additional tiles in Step 10
   (same chart-type resolution, theming, and grid placement as dashboarded vizzes) and append
   them after the dashboard's own tiles.
5. **Record the outcome** in the Migration Summary (Step 10g): which orphans existed, which
   were added, which were left off (and that the model still supports them via Spotter).

Don't skip this prompt just because the dashboard already looks complete — orphans frequently
include an overall-rate or breakdown view the author drafted but forgot to place.

---

## Step 10 — Generate Liveboard TML

### 10a. Resolve chart types

| Tableau mark class / zone | ThoughtSpot `chart.type` |
|---|---|
| `bar` | `BAR` |
| `line` | `LINE` |
| `circle` / `point` | `SCATTER` |
| `square` | `BAR` |
| `pie` | `PIE` |
| `area` | `AREA` |
| `text` (crosstab) | `TABLE` (display_mode `TABLE_MODE`) |
| Map (lat/long generated + geo role) | `GEO_BUBBLE` (or `GEO_AREA` for a filled/choropleth map) |
| "Measure Names / Measure Values" KPI block | `KPI` — **one tile per measure** (see KPI rule below) |

**KPI rule.** A Tableau scorecard/KPI worksheet (Measure Names + Measure Values, no
dimension) maps poorly to a single tile. Emit **one KPI viz per measure** — that's the
idiomatic ThoughtSpot KPI (headline + sparkline + period-over-period). **ALWAYS include a date
when the model has one** — this applies to *every* KPI tile (not just measure blocks), and is
easy to forget. Date selection: **0 date fields → static KPI (measure only); exactly 1 →
include it automatically; 2+ → ask the user which.** Use the data's grain (`[Date].yearly`
for annual data, `[Date].monthly` otherwise) — the default is monthly, so set `.yearly`
explicitly for annual sources. So a "count of sectors" KPI in a workbook with a `Fiscal Year`
column is `[Total Sectors] [Fiscal Year].yearly`, **not** a bare `[Total Sectors]`.

For the trend/sparkline to actually render, the date must be in **both** `chart_columns`
and on axis **`x`**, with the measure on `y` — a KPI with only `y:[measure]` shows a flat
number, no trend:

```yaml
chart:
  type: KPI
  chart_columns:
  - column_id: Month(Order Date)
  - column_id: Total Total Revenue
  axis_configs:
  - x: [Month(Order Date)]
    y: [Total Total Revenue]
```

### 10b. Build search queries

`search_query` is a ThoughtSpot search string of **bracketed column display names**, not
a "sum sales" phrase. Build it from the worksheet shelves:

- Reference each measure by its model column name: `[Total Revenue]` — the column's own
  default aggregation applies; do **not** prepend `sum`.
- Reference each dimension/attribute by name: `[Sales Channel]`.
- Date on a shelf → **dotted** bucket from the TWB `datetrunc`/`datepart`:
  `[Ship Date].yearly`, `[Order Date].monthly`. A bare `monthly` token is rejected.
- Top-N (Tableau Top filter) → append `top N`, e.g. `[Item Type] [Total Revenue] top 5`.
- **Percentage format for ratio measures.** A contribution / percent-of-total / growth-rate
  measure should display as a percent, not `0.07`. Set `format` on its `answer_columns[]` entry
  (`category: PERCENTAGE`, `percentageFormatConfig.decimals`) — see
  `../../shared/schemas/thoughtspot-answer-tml.md` "answer_columns[] fields". Detect from the
  formula (`/ TOTAL(...)`, `/ {FIXED ...}`, `growth of`) or the Tableau column's own % format.
- **Cumulative / moving measures** → reference the **measure column** by name with the
  worksheet's shelf attribute as the trailing sort arg: `cumulative_sum ( [Sales] , [Month] )`,
  `moving_average ( [Sales] , 2 , 0 , [Order Date] )` — these are **answer-level** formulas (not
  model columns). See `tableau-formula-translation.md` Running/Moving sections.
- **Growth / decline.** Two cases — read the worksheet's actual filters/table-calc to choose:
  - **A trend of growth over time** (`pcdf` with no Top-N, every period shown) → the
    `growth of` keyword: supply the bare date *and* its bucket, `growth of [Measure] by [Date]
    [Date].yearly [dim]` (default is **monthly**, so set `.yearly` for annual; dotted-only
    `by [Date].yearly` fails to tokenize). Resolved columns: `Growth of Total {Measure}` +
    `{Bucket}(Date)` — bind chart columns to those (export-patch).
  - **"Top/bottom N by growth over a window"** (`pcdf` **plus a Top-N filter + a recent-N-years
    filter** — e.g. "highest growth in past 5 years") → a **period-comparison**, best built as
    **answer-level formulas** on that one viz (it's viz-specific):
    ```yaml
    formulas:
    - id: formula_Val Start   # FDI in the start year
      expr: "group_aggregate ( sum ( [Measure] ) , query_groups () , query_filters () + { year_name ( [Date] ) = '2012' } )"
    - id: formula_Val End     # FDI in the end year
      expr: "group_aggregate ( sum ( [Measure] ) , query_groups () , query_filters () + { year_name ( [Date] ) = '2016' } )"
    - id: formula_Growth
      expr: "( [formula_Val End] - [formula_Val Start] ) / [formula_Val Start]"
    # search_query: "[Sector] [formula_Growth] top 5 by [formula_Growth]"   (bottom 5 = decline)
    ```
    Anchor years: **dynamic vs the actual data range matters.** `max([Date])` is **not allowed
    inside a formula filter** (`"Search did not find max("`), so you can't compute the data's
    latest year in-formula. Options: (a) **dynamic** via `currentdate()` —
    `year ([Date]) = year ( currentdate () )` and `… - 5` — correct for **live/refreshing**
    data, but returns **nothing** if the data is historical (e.g. ends 2016 while "today" is
    2026); (b) **anchor to the data's real bounds** (latest year and latest−5) when the
    dataset is static — functional, matches the "past 5 years" intent. Choose by whether the
    source refreshes; if unsure, **ask the user**. Format `Growth` as a percentage. This is the
    faithful translation of the `pcdf` + Top-N + window pattern — not a raw `growth of` line.
- A formula used by only this one viz can be an **answer-level formula** (`answer.formulas[]`
  + an `answer_columns[]` entry) rather than a model formula — see Step 5b.
- Calculated fields: translate the Tableau caption to the ThoughtSpot formula name via
  `{formula_column_map}`.

### 10c. Build liveboard TML

Follow `../../shared/schemas/thoughtspot-liveboard-tml.md` exactly — the structure below
is what actually imports and renders (an earlier `fqn`-based, minimal-chart form did not).

```yaml
liveboard:
  name: Dashboard Name
  description: "Migrated from Tableau workbook"
  visualizations:
  - id: Viz_1
    answer:
      name: Worksheet Name
      tables:
      - id: "Model Name"
        name: "Model Name"
        obj_id: ModelNameNoSpaces-{guid8}   # NOT fqn — a viz-level fqn is dropped on import
      search_query: "[Sales Channel] [Total Revenue]"
      answer_columns:                         # RESOLVED names (see below)
      - name: Sales Channel
      - name: Total Total Revenue
      chart:                                  # complete block, or omit entirely
        type: PIE
        chart_columns:
        - column_id: Sales Channel
        - column_id: Total Total Revenue
        axis_configs:
        - x: [Sales Channel]
          y: [Total Total Revenue]
      display_mode: CHART_MODE
  - id: Note_1                                # Tableau text / title zone → note tile
    note_tile:
      html_parsed_string: |-
        <p><strong>Title text</strong></p>
        <p>Body text from the Tableau text zone.</p>
  layout:
    tiles:
    - visualization_id: Viz_1
      x: 0
      y: 0
      height: 6
      width: 8
    - visualization_id: Note_1
      x: 8
      y: 0
      height: 6
      width: 4
```

**Critical naming rule (this is what breaks vizzes).** `chart_columns`, `axis_configs`,
and `table.table_columns` must reference the **resolved** answer-column names, not raw
model names:
- aggregated measure → `Total {Measure}` (`SUM([Total Revenue])` → `Total Total Revenue`)
- bucketed date → `{Bucket}(col)` (`[Ship Date].yearly` → `Year(Ship Date)`)
- attribute → unchanged

ThoughtSpot re-resolves `answer_columns` from `search_query` on import but does **not** fix
`chart_columns`/`axis_configs`. Reliable loop: build with your best-guess resolved names,
import, **export the liveboard**, copy the exact resolved names back into
`chart_columns`/`axis_configs`, and re-import. Use `obj_id` (never bare `fqn`) for the
table ref, and don't hand-author `client_state_v2` — leave styling to defaults.

Note tiles use `note_tile.html_parsed_string` (HTML) and have **no `answer`** — not the
old `viz_type: NOTE_TILE`/`content` form.

### Self-check — liveboard TML (verify before proceeding to layout)

Re-read the generated liveboard TML and confirm ALL of these hold. Fix any violation
before moving to 10d.

- [ ] Every viz `answer.tables[]` uses `obj_id` (not bare `fqn`)
- [ ] `chart_columns` and `axis_configs` use **resolved** names (`Total {Measure}`, `{Bucket}(date)`) not raw model names
- [ ] Every KPI tile includes a date when the model has one (with correct grain: `.yearly` for annual)
- [ ] Date in KPI is in both `chart_columns` and axis `x` (not just `y`)
- [ ] Note tiles use `note_tile.html_parsed_string` with no `answer` block
- [ ] `search_query` uses bracketed column names — `[col]` not bare `col`
- [ ] Date buckets are dotted — `[Order Date].monthly` not `monthly [Order Date]`
- [ ] Percentage measures have `format.category: PERCENTAGE` in `answer_columns[]`
- [ ] `display_mode: TABLE_MODE` tiles have NO `chart` block (omit it entirely)
- [ ] Every chart tile that should be themed has both `tile_brand_color` override AND `viz_style`

### 10d. Beautify layout

Apply layout optimization to each liveboard TML:

1. **Sort tiles** by y, then x.
2. **Pack rows from y=0** — reset y values so tiles start at 0 with no gaps.
3. **Fill 12 columns per row** — if a row's tiles don't span all 12 columns, expand
   the rightmost tile's width to fill.
4. **Minimum tile height** — enforce minimum height of 4 units.
5. **Remove empty rows** — if a row has no tiles, remove it.

Rewrite the `layout.tiles` section with corrected coordinates.

### 10e. Group related tiles into sections, and label everything clearly

A flat grid of tiles reads as a dump; a grouped, well-labelled liveboard reads as a
designed product. Two cheap, high-value steps:

**Group related vizzes into sections** (`groups[]` + `layout.group_layouts[]` — see
`../../shared/schemas/thoughtspot-liveboard-tml.md` "Sections (groups)"). Infer groupings
from what the vizzes have in common rather than leaving everything loose:
- All the per-measure **KPI tiles** → one "Key Metrics" section.
- Vizzes that share a **breakdown dimension** (e.g. two charts both by *Sales Channel*) →
  a section named for that dimension ("Channel Performance").
- Vizzes that share a **subject** (e.g. top-products + a geographic map) → e.g.
  "Product & Geographic Analysis".
- Give each group a short `name` and a one-line `description`.
A Tableau dashboard has no native sections, so this is an inference — keep it light
(2–4 groups), and don't force a viz into a group it doesn't fit; ungrouped tiles are fine.

**Write meaningful names and descriptions on every viz.** Don't ship raw worksheet names
like `Sheet 1` or terse labels. Set `answer.name` to a clear title and add a one-line
`answer.description` stating what the tile shows (these surface as the tile title and its
info tooltip):

```yaml
answer:
  name: "Revenue by Country"
  description: "Total revenue distribution across countries; bubble size = revenue volume."
```

Prefer the Tableau worksheet caption when it's descriptive; otherwise synthesize a title
from the columns on the shelves (`{measure} by {dimension}`, `Monthly {measure} Trend`,
`Top {N} {dimension} by {measure}`). Keep descriptions to one factual sentence.

### 10f. Surface referenced parameters in the liveboard header

If any viz on the liveboard **references a model parameter** (directly, or via a formula/bin
it uses — e.g. an `Age (bin)` driven by an `Age Groups` parameter), the parameter can be
shown as a **header chip** so users can change it live. For each referenced parameter,
**ask the user — default yes:**

```
Add parameter "{name}" to the liveboard header so users can adjust it? [Y/n]  (default Y)
```

On **yes**, add it to the liveboard header via `ordered_chips[]` and `parameter_overrides[]`
(see `../../shared/schemas/thoughtspot-liveboard-tml.md`):

```yaml
liveboard:
  parameter_overrides:
  - key: "{parameter_uuid}"
    value:
      name: "{Model Name}::{Parameter Name}"
      id: "{parameter_uuid}"
      # override_value: "..."   # only to change the default
  ordered_chips:
  - name: "{Model Name}::{Parameter Name}"
    type: PARAMETER
```

The `{parameter_uuid}` is assigned when the model imports — resolve it by exporting the
model (`ts tml export {model_guid} --parse`) and reading its `parameters[].id`. Chip names
are scope-qualified: `Model Name::Parameter Name`.

### 10g. Add a "Migration Summary" tab

Add a final **"Migration Summary"** tab to each liveboard — a single note tile that records
what the migration did, so it's reviewable **in-product** (not just in a side file). The user
can edit or delete it. Use the **tabs** layout (`layout.tabs[]`): the migrated content is the
first tab, the summary is the last. The note tile's `html_parsed_string` has three sections:

```
1. Items migrated      — each viz/tile and how (chart type, search), formulas, cohorts, params
2. Decisions made      — non-obvious choices (unpivot via SQL view, bins=cohort vs formula,
                          count column, growth via `growth of`, theme, top/bottom approximations…)
3. Partial / placeholder — vizzes that couldn't be fully reproduced but were built as
                          placeholders (forecast → historical trend; cluster → underlying inputs);
                          flag each "needs review" + what's missing
4. Items NOT migrated  — only things with genuinely nothing to show, untranslatable formulas,
                          the flipboard interaction, orphan worksheets, data-fidelity gaps — reason each
```

Per the placeholder principle, **forecast/cluster vizzes are placeholders, not omissions** —
show the reproducible part (a forecast's historical trend; a cluster's input columns) and
flag for review; reserve "not migrated" for things with literally nothing to render.

This is the same content as `MIGRATION_LIMITATIONS.md` (Step 12) plus the positive items —
keep them consistent. If a workbook has multiple liveboards, give each its own summary
covering that liveboard, and note model-level decisions on the first.

**Record the orphan-worksheet outcome.** Orphans are surfaced and decided in **Step 9d** (not
here). In the Migration Summary, list which orphans existed, which were added as tiles, and
which were left off — noting that any calc fields/cohorts they introduced are still on the
model (usable via Spotter/search). (Example: the FDI `Groups` cohort exists on the model, but
its `Groups` worksheet wasn't dashboarded — so nothing referenced it until added deliberately.)

Write each liveboard to
`/tmp/ts_tableau_mig/output/{workbook_name}/{dashboard_name}.liveboard.tml`.

---

## Step 10.5 — Liveboard Style

A migrated liveboard looks intentional when it carries a coherent style rather than the
bare default. Offer the user a **curated theme** (one pick), then write it into the
liveboard. A complete theme is **three layers** — board/group/tile brand tokens
(`style.style_properties`), per-object assignments (`style.overrides[]`), **and** a matching
per-chart color palette (`chart.viz_style`). The full token reference is in
`../../shared/schemas/thoughtspot-liveboard-tml.md` ("Liveboard styling"); the
ready-to-apply per-theme recipes (tokens + `viz_style` palettes) are in
[liveboard-style-themes.md](liveboard-style-themes.md) — read it and
apply the chosen theme's three layers verbatim.

```
Pick a style for the liveboard(s):
  1  Clean & Minimal     — light gray, sharp borders (data-first, default)
  2  Cool Professional   — blue, corporate/executive
  3  Fresh & Modern      — mint/teal, contemporary
  4  Soft Lavender       — purple, elegant/calm
  5  Warm Tones          — peach/orange, friendly/customer-facing
  6  High Contrast KPIs  — dark KPI tiles for maximum headline impact
  0  None                — leave ThoughtSpot defaults

Enter 1–6 or 0:
```

**Apply the theme to EVERY chart tile — don't skip any.** When a theme defines a chart
palette (`viz_style`), set it on *all* chart vizzes uniformly, including formula-/growth-based
tiles and ones added late. A common miss is theming the straightforward bars/pies but leaving
a growth or computed tile on the default color — verify every chart tile got both its
`tile_brand_color` override **and** its `viz_style`.

**Confirm the theme on every workbook — never apply it silently.** In a multi-workbook run,
remember the previous pick and offer it as the **default** ("Style for this liveboard?
[default: High Contrast KPIs]"), so the user can press through to stay consistent or change
it per workbook. Always surface the choice; do not assume the last theme carries over without
showing it. Apply the theme by
writing `style.style_properties` and, where the theme colors groups/tiles, per-object
`style.overrides[]`:

```yaml
style:
  style_properties:
  - name: lb_brand_color
    value: LBC_C            # theme's liveboard color
  - name: lb_border_type
    value: CURVED           # SHARP for Clean & Minimal
  - name: kpi_hero_font_size
    value: M
  overrides:                # set each group/tile to the theme's GBC_/TBC_ token
  - object_id: Group_1
    style_properties:
    - name: group_brand_color
      value: GBC_C
```

Theme → token map:

The base brand colors per theme (quick glance — **the verified, complete recipe incl.
border type, per-tile colors, KPI emphasis, and `viz_style` palette is in
[liveboard-style-themes.md](liveboard-style-themes.md), which is
authoritative**):

| Theme | `lb_brand_color` | `group_brand_color` | non-KPI `tile_brand_color` |
|---|---|---|---|
| Clean & Minimal | `LBC_A` | `GBC_A` | `TBC_A` |
| Cool Professional | `LBC_C` | `GBC_C` | `TBC_C` |
| Fresh & Modern | `LBC_D` | `GBC_D` | `TBC_D` |
| Soft Lavender | `LBC_B` | `GBC_B` | `TBC_B` |
| Warm Tones | `LBC_G` | `GBC_G` | `TBC_G` |
| High Contrast KPIs | `LBC_A` | — | KPI tiles `TBC_I`–`TBC_P` (dark) |

Border type and KPI-tile treatment **vary per theme** — read the reference file, don't
assume. `TBC_I`–`TBC_P` are valid **only on KPI tiles** — never apply a dark tile color to
a chart/table tile.

---

## Step 11 — Import Liveboard

Display a summary:
```
Ready to import {N} liveboard(s) to {base_url}:
  - {dashboard_name_1}
  - {dashboard_name_2}
  ...
```

Ask: "Import now? (yes/no)"

On confirmation, build the JSON array of liveboard TML strings and import. Use
`--policy PARTIAL` so successfully imported liveboards are kept even if some fail, and
`--create-new` since these are new objects:

```bash
cd /tmp/ts_tableau_mig/output/{workbook_name}
python3 - > /tmp/ts_tableau_mig/{workbook_name}_lb_payload.json <<'PY'
import json, glob
print(json.dumps([open(f).read() for f in sorted(glob.glob("*.liveboard.tml"))]))
PY
cat /tmp/ts_tableau_mig/{workbook_name}_lb_payload.json \
  | ts tml import --policy PARTIAL --create-new --profile {profile_name}
```

Parse the response for import errors. Show any failures with detail.

**Re-importing a liveboard in place** (a styling/param-chip/coverage pass after the first
import): set `guid` **and** `obj_id` to the existing object's values and import with
`--no-create-new`. **The single thing that matters: `guid`/`obj_id` must be TOP-LEVEL keys of
the TML document — siblings of `liveboard:`, NOT nested inside it.**

```json
{ "guid": "<existing>", "obj_id": "<existing>", "liveboard": { "name": ..., "visualizations": ... } }
```

Nesting them as `liveboard.guid` (a natural mistake when you build the dict as `{"liveboard": {...}}`
and set `d["liveboard"]["guid"]`) means the import never matches the existing object and **forks a
duplicate with a new guid — every time, regardless of `--policy`**. (This is the same top-level
placement tables/models use, which is why those updated in place while liveboards kept forking.)
`--policy` is irrelevant to the match; either `ALL_OR_NONE` or `PARTIAL` works once the guid is
top-level. Read the existing `obj_id` from the search result (`metadata_obj_id`) or a prior
export, and **verify the returned `id_guid` is unchanged** afterward; if it changed, the guid was
mis-placed — fix it and delete the stale duplicate.

For each successfully imported liveboard, display the URL:

```
{base_url}/#/pinboard/{liveboard_guid}
```
