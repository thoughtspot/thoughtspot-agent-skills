# Amuzing chart samples

The worked example: 50 custom chart tiles in 7 tabs on **(Sample) Retail - Apparel**,
the sample model most clusters ship. The guids differ per cluster, so the committed spec carries placeholders:
run `LIVEBOARD_GUID=... MODEL_GUID=... python3 make-spec.py` to point it at your own Liveboard and model. That
spec is written to `~/.cache/ts-charts/liveboards/amuzing-chart-samples/` (`<W>` below), never over this folder.

## The story

Follow the money: sales stepped up 119% in Jun 2023 and down 33% in Jun 2024 while price per unit fell
about 25%, a volume-for-price trade; year to date is flat (-0.5%). The tabs ask, in order:

| Tab | Question | Tiles |
|---|---|---|
| 01 About | Why this Liveboard, and how to read it | 2 (ignore filters) |
| 02 Pulse | How are we doing? | 12 (banner, eight KPI styles, monthly line, region bridge, pace lines) |
| 03 Where | Where does it sell? | 6 |
| 04 What | What sells? | 10 |
| 05 When | When does it sell? | 7 |
| 06 Who | Which stores and products lead? | 7 |
| 07 Next | What should we do? | 6 |

Filters: date, region, item type. Colour: five editorial product families own the hues (a grouping of
the 15 item types, not a model column); region is slate.

## The data (verified through the ThoughtSpot MCP)

- Measures: `sales`, `quantity purchased`. Attributes: `date`, `region` (5: East, Midwest, South, Southwest, West),
  `state` (19), `city`, `county`, `zip code`, `store` (30, name looks like "California (94702)"), `item type` (15), `product` (345), `SKU`, `latitude`, `longitude`.
- Dates: Jun 2021 to Sep 2026, 64 months. **2021 is a partial year (Jun to Dec).** Searches return dates as epoch **seconds** through MCP `searchdata`, but tiles receive epoch **milliseconds**. `AZ.ms()` handles both.
- All 30 stores trade every month. Sales are ~$10.5M/month until May 2023, jump to ~$24M in Jun 2023, drop to ~$16M in Jun 2024, then hold ~$13M to $17.6M with a seasonal shape. Units move the same way; average selling price fell from ~$60 to ~$52 to ~$41-49. It is uniform across all 15 item types. This is the Liveboard's central story: a volume-for-price trade.
- Item types (15) by sales: Jackets 188.9M, Pants 142.4M, Shorts 73.2M, Sweatshirts 71.1M, Dresses 69.7M, Vests 68.9M, Shirts 68.0M, Bags 64.0M, Jeans 55.4M, Skirts 40.7M, Sweaters 34.3M, Swimwear 30.8M, Headwear 29.8M, Underwear 22.6M, Socks 10.7M.
- **Store latitude/longitude are unreliable**: e.g. "Nevada (89052)" plots in Texas, "Maryland (21045)" in South Carolina, "Delaware (19702)" in New Jersey, "Minnesota (55420)" in Indiana. Never place a store by lat/long. Place by **state** (state centroid) and say so.
- Column names arrive renamed: measures as `Total sales`, `Total quantity purchased`; dates as `Month(date)`, `Year(date)`, `Quarter(date)`, `Day(date)`; attributes keep their names (`region`, `item type`, `store`, `state`, `product`). Resolve columns with `AZ.col(schema, /regex/)`, never by position.
- **Quarterly and yearly grain have part periods.** The first quarter (Q2 2021) holds only June, and `Year(date)` 2021 is Jun to Dec; 2026 ends at Sep. Detect a part period from the rows (a total far below its neighbours) and label it, never assume a full one.
- **Year to date is flat.** Jan to May 2026 equals Jan to May 2025 exactly and the whole-company YTD is -0.5%. Item types run -1.1% to +0.1%, stores -2.9% to +4.5% (only Massachusetts 02215 stands out at +4.5%). Check the spread before designing a growth or "movers" chart; if there is none, say so and show what does differ (price per unit, share, seasonality, concentration).
- The Liveboard has filters on date, region and item type. **Every chart must survive filtered data**: one region, one item type, a short date range, a single month. Never throw on small data; paint a plain message with `AZ.paint(el, '<div class="az-empty">...</div>')` and still let `boot` emit render-complete.

## Files

- `make-spec.py` writes `liveboard.spec.json` (the tile table, filters, style). Edit the table, run it.
- `narratives/<slug>.cfg.js`: one per narrative tile (About hero, guide, seven banners), rendered by
  `<L>/narratives/render.js` by `scripts/build-narratives.mjs` into the user's library
  (`~/.cache/ts-charts/library/<slug>/`; `--into-skill` refreshes the shipped copies in `<C>/library/`).
- The charts are in `<C>/library/`; `<C>/references/library.md` lists them by tab.

## Rebuild

```bash
node <L>/scripts/build-narratives.mjs
node <L>/scripts/liveboard-pack.mjs --liveboard <W> --commit --all --backup <export of the Liveboard> > p.js   # paste each block in order
node <L>/scripts/liveboard-pack.mjs --liveboard <W> --check > check.js         # then expect stale: [] and missing: []
```
On a Liveboard built before owner markers (the live *Amuzing chart samples* was), the first commit lists its
tiles under `problems` as tiles to adopt: build it once more with `--adopt` to take them over and mark them.
See `SKILL.md` Step 6.
