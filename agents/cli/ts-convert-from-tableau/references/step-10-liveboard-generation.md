# Step 9 — Dashboard Layout Parsing Detail

Reference detail for **Step 9 — Parse Dashboard Layout**: the zone-extraction field table and
the container-tree grid-mapping algorithm. Step 10 (liveboard generation) builds via
SpotterViz from natural-language instructions, not from this grid output directly — but the
relative layout this file computes (which zones group together, their reading order) is what
turns a flat tile list into a clear description of the source dashboard's actual structure;
see [`../../../shared/schemas/spotterviz-liveboard-build.md`](../../../shared/schemas/spotterviz-liveboard-build.md)
for how Step 10 uses it. The step's own spine (decision points, gotchas) stays in `SKILL.md`
— this file is what it links out to for the full algorithm detail.

---

## Zone extraction field reference (Step 9a)

For each leaf zone found by walking `<dashboard>` → `<zones>` → `<zone>` recursively,
extract:

| Field | Source |
|---|---|
| `zone_id` | `id` attribute |
| `zone_type` | `type` attribute (`text`, `title`, `viz`, `bitmap`, `web`, `extension`, `metric`) |
| `worksheet_name` | `name` attribute (for `viz` zones) |
| `x`, `y`, `w`, `h` | `x`, `y`, `w`, `h` attributes (Tableau uses 0–100,000 coordinate space) |
| `text_content` | `<formatted-text>` child text (for `text` / `title` zones) |
| `parent_zone` + `param` | the enclosing `<zone>`'s `id` and its `param` (`vert` = vertical container / stacks children top-to-bottom; `horz` = horizontal container / places children left-to-right). **Keep the nesting** — don't flatten to a coordinate list; the container tree is the layout's real structure (9c). |
| `floating` | `floating="true"` on the zone — a free-positioned overlay, not part of a container. Handle separately in 9c. |

## Container-tree grid mapping algorithm (Step 9c)

Map the **container tree**, not raw coordinates — a flat y-band scan misgroups zones
whenever two containers share a y range.

1. **Walk the `<zones>` tree** from 9a. A **`vert`** container stacks its children into
   successive **rows**; a **`horz`** container lays its children **side-by-side within one
   row**. Recurse: a `horz` inside a `vert` is one row split into columns; a `vert` inside a
   `horz` is a column split into stacked rows.
2. **Columns within a horizontal container** — split 12 columns **proportionally to each
   child's `w` relative to its siblings' total `w`** (not the whole dashboard). Normalize with
   **largest-remainder** so `col_span`s sum to **exactly 12** with no slivers: floor each
   share, then hand the leftover columns to the zones with the largest fractional remainders.
   Enforce a **minimum `col_span` of 2** (merge or bump anything smaller) so no tile is an
   unreadable sliver.
3. **Rows / height** — give each row a `row_span` from the zone's **aspect ratio**, so charts
   keep roughly their source shape: `row_span ≈ round(col_span × (h/w) × 0.5)`, clamped to a
   per-type floor — **KPI/number ≥ 3, note/text ≥ 2, chart ≥ 6, table ≥ 8**. Stack rows top to
   bottom, each starting at the previous row's bottom (`y += prev row_span`).
4. **Fallback to the band method** only when the tree is unavailable (rare — e.g. a
   hand-edited TWB with flat zones): group zones within ~2,000 y-units into a band, sort bands
   top-to-bottom and zones left-to-right within a band, then apply the same proportional
   column split + aspect-ratio height as above.

**Floating zones** (`floating="true"`) overlap the tiled layout and have no grid equivalent.
Don't try to reproduce the overlap: place each floating zone as its **own full-or-partial-width
tile** in reading order (by y then x) after the tiled zones, and **note in the Migration
Summary** that it was a floating overlay flattened into the flow.
