# Open Items: ts-convert-from-tableau

---

## #1 — VALIDATE_ONLY policy in ts CLI — NEEDS VERIFICATION

The skill uses `ts tml import --policy VALIDATE_ONLY` for the fix loop. Verify that the
`ts` CLI supports this policy flag and returns structured error JSON (not just HTTP status).

Alternative: if VALIDATE_ONLY is unsupported, use `--policy PARTIAL` with a dry-run flag,
or call the REST v2 endpoint directly:
`POST /api/rest/2.0/metadata/tml/import` with `{"import_policy": "VALIDATE_ONLY", "dry_run": true}`

Status: NEEDS VERIFICATION against live cluster

---

## #3 — COLLECTION datasources — NOT IMPLEMENTED

Tableau COLLECTION datasources (multiple primary data sources combined) should generate
one model per underlying table. This edge case is not handled in v1.0.0.

Status: DEFERRED to v1.1.0

---

## #5 — Answer TML inline vs. separate import — NEEDS VERIFICATION

The skill generates answer content inline within the liveboard's `visualizations` section.
Verify that this structure imports correctly — specifically that `answer:` blocks nested
inside `visualizations[]` are accepted by `ts tml import`.

Status: NEEDS VERIFICATION against live cluster

---

## #6 — Liveboard layout coordinate system — NEEDS VERIFICATION

Step 9c maps Tableau 0–100,000 coords to a ThoughtSpot 12-column grid. Verify:
- The exact column width unit ThoughtSpot uses in TML (is it 1/12 of the liveboard width?)
- The height unit (pixels? rows? a relative unit?)
- The minimum and maximum tile height values

Reference: `thoughtspot-liveboard-tml.md` schema doc for exact field semantics.

Status: NEEDS VERIFICATION

---

## #7 — NOTE_TILE structure — NEEDS VERIFICATION

The skill generates `viz_type: NOTE_TILE` with `note_tile.content`. Verify the exact TML
structure for note tiles against the liveboard TML schema, especially:
- Is `viz_type` the correct field name?
- What is the supported `background_color` format?
- Can note tiles contain HTML or markdown?

Status: NEEDS VERIFICATION

---

## #9 — Tab support (multiple dashboards → tabs) — NOT IMPLEMENTED

When a Tableau workbook has multiple dashboard sheets, v1.0.0 creates one liveboard per
dashboard. ThoughtSpot supports liveboard tabs — grouping all dashboards into a single
multi-tab liveboard is a better migration output but requires the liveboard tabs TML
structure.

Status: DEFERRED to v1.1.0

---

## #13 — REGEXP family + FINDNTH — PASS-THROUGH ONLY

REGEXP_EXTRACT/MATCH/REPLACE, FINDNTH have no native TS equivalent — mapped to
sql_*_op pass-through (warehouse-dialect-specific) or omit+log.

Status: Pass-through implemented; not verified against live cluster

---

## #14 — Parameter TML: CHAR not VARCHAR, list_choice format — VERIFIED 2026-06-19

Verified against se-thoughtspot (Weighted Usage migration).

**Finding 1: `data_type: VARCHAR` fails for list parameters.** The model TML schema
lists `VARCHAR` as a valid `data_type`, but import rejects it for parameters with
`list_config`. Use `CHAR` instead. `VARCHAR` may work for free-form parameters (not tested).

**Finding 2: `list_choice` entries must be objects, not bare strings.** Each entry needs
at minimum a `value:` key; `display_name:` is recommended.

```yaml
# WRONG — fails on import
data_type: VARCHAR
list_config:
  list_choice:
  - USD
  - CAD

# CORRECT
data_type: CHAR
list_config:
  list_choice:
  - value: USD
    display_name: USD
  - value: CAD
    display_name: CAD
```

**Doc fix applied:** updated `tableau-tml-rules.md` parameter example and
`thoughtspot-model-tml.md` field descriptions (same commit).

Status: VERIFIED — doc fixes applied

---

## #15 — Formula cross-references fail during TML import — VERIFIED 2026-06-19

Verified against se-thoughtspot (Weighted Usage migration).

A model formula that references another formula column by bracket notation
(`[Other Formula Name]`) fails during import with "Search did not find 'other formula
name'". ThoughtSpot resolves formula references by display name, but the referenced
formula may not yet exist when the referencing formula is validated during import.

**Workaround 1 (preferred):** inline the referenced formula's expression directly into
the referencing formula.

**Workaround 2:** import base formulas first (no cross-refs), export the model to get
server-assigned IDs, then add dependent formulas via a second import using the exported
JSON format.

**Doc fix applied:** added "Formula cross-references during import" section to
`tableau-tml-rules.md` (same commit).

Status: VERIFIED — doc fixes applied

---

## #16 — Special characters in parameter list values — VERIFIED 2026-06-19

Verified against se-thoughtspot (Weighted Usage migration).

Parameter list values containing `$` and `%` characters caused import failures. Renamed
values to avoid special characters (e.g. "$ Difference" → "Dollar Difference",
"% Difference" → "Pct Difference").

Not yet determined whether this is a YAML escaping issue or a ThoughtSpot validation
restriction. If YAML escaping, quoting the values may work — not tested.

Status: VERIFIED — workaround is to avoid special characters in parameter values
