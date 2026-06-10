# Liveboard Style Themes

Reference for **Step 10.5 — Liveboard Style**. Each theme is three coordinated layers; apply
all three for a finished look. Brand tokens (`LBC_/GBC_/TBC_/TKS_`) and `style_properties`
scopes are defined in
[../../../shared/schemas/thoughtspot-liveboard-tml.md](../../../shared/schemas/thoughtspot-liveboard-tml.md)
("Liveboard styling").

The three layers:

1. **`liveboard.style.style_properties`** — board-level: `lb_brand_color`, `lb_border_type`,
   `kpi_hero_font_size`, group/tile hide flags.
2. **`liveboard.style.overrides[]`** — per-object (`object_id` = `Group_N` or `Viz_N`):
   `group_brand_color`, `tile_brand_color` (dark `TBC_I`–`TBC_P` are KPI-only).
3. **`chart.viz_style`** (per viz) — the actual **chart colors**. A JSON **string**:

```jsonc
{
  "overrides": {
    // per-series color — bar / line / KPI (one entry per measure series)
    "column_properties": [
      { "column_id": "Total Total Revenue", "properties": { "color": "#64748B" } },
      { "column_id": "Total Total Profit",  "properties": { "color": "#94A3B8" } }
    ],
    // categorical palette — pie and any color-by-dimension chart
    "legend_properties": { "color_palette": { "colors": ["#b8c1d0", "#9daab8", "#64748B"] } }
  }
}
```

Apply `column_properties` colors to single/multi-series charts (LINE, BAR, KPI) and a
`legend_properties.color_palette` to categorical charts (PIE, color-by-dimension). Keep a
viz's palette consistent with the chosen theme. `viz_style` is optional — omit it and the
chart uses ThoughtSpot's default palette; supply it to match the theme.

**KPI emphasis pattern.** Several themes make the KPI tiles stand out by overriding them
(in `style.overrides[]`, per KPI viz) with a dark tile background (`tile_brand_color` in the
`TBC_I`–`TBC_P` KPI-only range), a light hero-number color (`tile_kpi_color: TKS_*`), and
`is_highlighted: 'true'`. Non-KPI tiles get a light `TBC_*`. Each theme below states its own
KPI treatment — there is no single rule. **Border type also varies per theme** (some `SHARP`,
some `CURVED`); always follow the recorded recipe, not an assumption.

> Source of truth: these recipes are distilled from verified, working liveboard exports.
> When recording a new theme, paste the `style` block and the per-chart `viz_style` palette
> from a known-good liveboard.

---

## 1. Clean & Minimal — light gray, sharp borders (data-first)

**`style_properties`:** `lb_brand_color: LBC_A`, `lb_border_type: SHARP`,
`kpi_hero_font_size: M`, `hide_group_description: 'true'`.

**`overrides`:** every group → `group_brand_color: GBC_A`; KPI tiles → `tile_brand_color: TBC_A`
(this theme stays light — it does **not** use the dark KPI tiles).

**Chart palette — slate grayscale:**
- Series colors: primary `#64748B`, secondary `#94A3B8` (e.g. Revenue vs Profit on a line).
- Categorical palette (pie / color-by-dimension): a slate-gray ramp, e.g.
  `#b8c1d0, #9daab8, #64748B, #505d6f, #3c4653, #c5ccd6, #aab5c3, #94A3B8, …`.

```yaml
chart:
  # ... type / chart_columns / axis_configs ...
  viz_style: "{\"overrides\": {\"column_properties\": [{\"column_id\": \"Total Total Revenue\", \"properties\": {\"color\": \"#64748B\"}}, {\"column_id\": \"Total Total Profit\", \"properties\": {\"color\": \"#94A3B8\"}}]}}"
```

---

## 2. Cool Professional — blue, corporate/executive

**`style_properties`:** `lb_brand_color: LBC_C`, `lb_border_type: SHARP`,
`kpi_hero_font_size: M`, `hide_group_description: 'true'`.

**`overrides`:**
- Groups → `group_brand_color: GBC_C`.
- **Chart/note tiles** (line, pies, bar, geo) → `tile_brand_color: TBC_C` (light blue).
- **KPI tiles** → emphasized: `tile_brand_color: TBC_K` (dark), `tile_kpi_color: TKS_A`
  (light hero number), `is_highlighted: 'true'`. This is the theme's signature — the KPIs
  pop on dark blue while everything else stays light.

**Chart palette — neutral slate** (same as Clean & Minimal; the blue identity comes from
the brand tokens, not the series colors): series `#64748B` / `#94A3B8`; categorical pies use
a slate-blue ramp (`#b8c1d0, #9daab8, #64748B, #505d6f, …`).

```yaml
# KPI tile emphasis (per KPI viz) under style.overrides[]:
- object_id: Viz_7
  style_properties:
  - { name: tile_brand_color, value: TBC_K }
  - { name: tile_kpi_color,   value: TKS_A }
  - { name: is_highlighted,   value: 'true' }
```

## 3. Fresh & Modern — mint/teal, contemporary

**`style_properties`:** `lb_brand_color: LBC_D`, `lb_border_type: CURVED`,
`kpi_hero_font_size: M`, `hide_group_description: 'true'`.

**`overrides`:**
- Groups → `group_brand_color: GBC_D`.
- Chart/note tiles → `tile_brand_color: TBC_D` (light cyan).
- KPI tiles → emphasized: `tile_brand_color: TBC_L` (dark), `tile_kpi_color: TKS_A`,
  `is_highlighted: 'true'`.

**Chart palette — teal/mint (this theme DOES recolor the series):** primary
`#22636B` (deep teal), secondary `#4ECDC4` (mint). Bar single-series `#22636B`. Categorical
pies use a teal→mint ramp (`#7db0b5, #5a9aa0, #22636B, …, #4ECDC4, …`); the geo palette is an
all-teal ramp.

```yaml
chart:
  viz_style: "{\"overrides\": {\"column_properties\": [{\"column_id\": \"Total Total Revenue\", \"properties\": {\"color\": \"#22636B\"}}, {\"column_id\": \"Total Total Profit\", \"properties\": {\"color\": \"#4ECDC4\"}}]}}"
```

## 4. Soft Lavender — purple, elegant/calm

**`style_properties`:** `lb_brand_color: LBC_B`, `lb_border_type: CURVED`,
`kpi_hero_font_size: M`, `hide_group_description: 'true'`.

**`overrides`:**
- Groups → `group_brand_color: GBC_B`.
- Chart/note tiles → `tile_brand_color: TBC_B` (light purple).
- KPI tiles → emphasized: `tile_brand_color: TBC_J` (dark), `tile_kpi_color: TKS_A`,
  `is_highlighted: 'true'`.

**Chart palette — purple/lavender:** line series `#6B4E9C` (deep purple) / `#B8A3DC`
(lavender); bar single-series `#B07AA1`; pie/geo use purple ramps. This theme also colors
the **KPI sparklines** via each KPI viz's `viz_style` (`#9b59b6` / `#9370DB`) — earlier
themes leave KPI charts unstyled, this one themes them too.

```yaml
# line
chart: { viz_style: "{\"overrides\": {\"column_properties\": [{\"column_id\": \"Total Total Revenue\", \"properties\": {\"color\": \"#6B4E9C\"}}, {\"column_id\": \"Total Total Profit\", \"properties\": {\"color\": \"#B8A3DC\"}}]}}" }
# a KPI viz
chart: { viz_style: "{\"overrides\": {\"column_properties\": [{\"column_id\": \"Total Total Revenue\", \"properties\": {\"color\": \"#9b59b6\"}}]}}" }
```

## 5. Warm Tones — peach/orange, friendly/customer-facing

**`style_properties`:** `lb_brand_color: LBC_G`, `lb_border_type: CURVED`,
`kpi_hero_font_size: M`, `hide_group_description: 'true'`.

**`overrides`:**
- Groups → `group_brand_color: GBC_G`.
- Chart/note tiles → `tile_brand_color: TBC_G` (peach).
- KPI tiles → emphasized: `tile_brand_color: TBC_O` (dark), `tile_kpi_color: TKS_A`,
  `is_highlighted: 'true'`.

**Chart palette — peach/orange:** line series `#FF8C66` (orange) / `#FFB399` (peach); bar
single-series `#FF8C66`; pie/geo use orange→peach ramps. KPI sparklines should use the same
orange family (e.g. `#FF8C66`). *(Note: a sample export had the KPI sparklines purple
`#9b59b6`/`#9370DB`. Confirm with the user whether that's intended — purple-KPI-on-dark is a
deliberate accent in the High Contrast theme, so don't assume it's a mistake here; ask.)*

```yaml
chart:
  viz_style: "{\"overrides\": {\"column_properties\": [{\"column_id\": \"Total Total Revenue\", \"properties\": {\"color\": \"#FF8C66\"}}, {\"column_id\": \"Total Total Profit\", \"properties\": {\"color\": \"#FFB399\"}}]}}"
```

## 6. High Contrast KPIs — dark KPI tiles for maximum headline impact

The point of this theme is KPI prominence, not a color identity: keep everything neutral and
let the dark, oversized KPI tiles dominate.

**`style_properties`:** `lb_brand_color: LBC_A`, `lb_border_type: CURVED`,
**`kpi_hero_font_size: XL`** (largest hero number — note `XL` extends the `S`/`M`/`L` set),
`hide_group_description: 'true'`.

**`overrides`:**
- Groups → `group_brand_color: GBC_A`; chart/note tiles → `tile_brand_color: TBC_A` (neutral).
- KPI tiles → maximum emphasis: `tile_brand_color: TBC_I` (the darkest KPI background),
  `tile_kpi_color: TKS_A` (light hero number), `is_highlighted: 'true'`.

**Chart palette — vivid warm + purple KPIs (intentional, user-confirmed).** The contrast is
two-fold: vivid charts *and* dark KPI tiles, not neutral charts. Apply:
- Line series `#FF8C66` (orange) / `#FFB399` (peach); bar single-series `#FF8C66`.
- Pie + geo: warm orange categorical ramps (`#FFD4C2, #FFB399, #FF8C66, …`).
- **KPI sparklines purple** `#9b59b6` / `#9370DB` — a deliberate accent against the dark KPI
  tiles (this is the one theme where the KPI sparkline color intentionally differs from the
  chart series hue).

```yaml
# line
chart: { viz_style: "{\"overrides\": {\"column_properties\": [{\"column_id\": \"Total Total Revenue\", \"properties\": {\"color\": \"#FF8C66\"}}, {\"column_id\": \"Total Total Profit\", \"properties\": {\"color\": \"#FFB399\"}}]}}" }
# a KPI viz
chart: { viz_style: "{\"overrides\": {\"column_properties\": [{\"column_id\": \"Total Total Revenue\", \"properties\": {\"color\": \"#9b59b6\"}}]}}" }
```
