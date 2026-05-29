# Open Items: ts-liveboard-from-tableau

---

## #1 — Answer TML inline vs. separate import — NEEDS VERIFICATION

The skill currently generates standalone `.answer.tml` files and packages them with the liveboard TML in a zip for `ts tml import`. Verify that:
- Standalone answer TMLs can be imported independently of liveboards
- OR answers must be embedded inline in the liveboard's `visualizations` section

If answers must be embedded (not standalone), remove the separate answer TML files and inline the full answer structure in each `visualizations` entry.

Status: NEEDS VERIFICATION against live cluster

---

## #2 — Liveboard layout coordinate system — NEEDS VERIFICATION

Step 4 maps Tableau 0–100,000 coords to a ThoughtSpot 12-column grid. Verify:
- The exact column width unit ThoughtSpot uses in TML (is it 1/12 of the liveboard width?)
- The height unit (pixels? rows? a relative unit?)
- The minimum and maximum tile height values

Reference: `thoughtspot-liveboard-tml.md` schema doc for exact field semantics.

Status: NEEDS VERIFICATION

---

## #3 — NOTE_TILE structure — NEEDS VERIFICATION

The skill generates `viz_type: NOTE_TILE` with `note_tile.content`. Verify the exact TML structure for note tiles against the liveboard TML schema, especially:
- Is `viz_type` the correct field name?
- What is the supported `background_color` format?
- Can note tiles contain HTML or markdown?

Status: NEEDS VERIFICATION

---

## #4 — Multi-datasource worksheets — NOT IMPLEMENTED

Tableau worksheets can blend data from multiple datasources. v1.0.0 assumes each worksheet uses a single datasource. Blended worksheets will produce an incomplete Answer TML.

Status: DEFERRED to v1.1.0

---

## #5 — Tab support (multiple dashboards → tabs) — NOT IMPLEMENTED

When a Tableau workbook has multiple dashboard sheets, v1.0.0 creates one liveboard per dashboard. ThoughtSpot supports liveboard tabs — grouping all dashboards into a single multi-tab liveboard is a better migration output but requires the liveboard tabs TML structure.

Status: DEFERRED to v1.1.0
