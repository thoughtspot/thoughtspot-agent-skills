# Open Items: ts-convert-from-tableau

---

## #1 — VALIDATE_ONLY policy in ts CLI — VERIFIED 2026-07-03

The skill uses `ts tml import --policy VALIDATE_ONLY` for the Step 6 fix loop. `ts tml
import` (`commands/tml.py`) passes `--policy` straight through as `import_policy` to
`POST /api/rest/2.0/metadata/tml/import` with no client-side enum restriction, so
`VALIDATE_ONLY` is accepted and returns structured per-object status JSON like any other
policy value.

Corroborating evidence: `ts tml lint` (added ts-cli v1.14.2) exists specifically because
live use of `--policy VALIDATE_ONLY` showed it does **not** catch every model invariant
(I1/I2/I4/I5/I8) — ThoughtSpot accepts the TML and reports success, and the invariant
violation only surfaces later, on export or search. Knowing what VALIDATE_ONLY does and
does not catch could only be learned by running it live, and that finding is what drove
the `tml_lint.py` pre-import gate documented in SKILL.md Step 6.

Status: VERIFIED 2026-07-03 — Step 6 fix loop + the `ts tml lint` docstring are built on
live VALIDATE_ONLY behaviour

---

## #3 — COLLECTION datasources — DEFERRED

Tableau COLLECTION datasources (multiple primary data sources combined) should generate
one model per underlying table. This edge case is not handled.

Status: DEFERRED — still open as of 2026-07-11; no committed target version or BL-NNN
filed as of 2026-07-03, and no COLLECTION-datasource workbook has been encountered since;
revisit if/when one is encountered

---

## #5 — Answer TML inline vs. separate import — VERIFIED 2026-07-03

The skill generates answer content inline within the liveboard's `visualizations` section.

Status: VERIFIED 2026-07-03 — confirmed by every shipped liveboard migration since
SKILL.md v1.3.0 (incl. the v1.5.40 three-workbook demo — Amazon/FDI/HR) plus the verified
`thoughtspot-liveboard-tml.md` schema (`visualizations[].answer` — full embedded Answer
TML). `answer:` blocks nested inside `visualizations[]` are accepted by `ts tml import`.

---

## #6 — Liveboard layout coordinate system — VERIFIED 2026-07-03

Step 9c maps Tableau 0–100,000 coords to a ThoughtSpot 12-column grid.

Status: VERIFIED 2026-07-03 — confirmed by every shipped liveboard migration since
SKILL.md v1.3.0 (incl. the v1.5.40 three-workbook demo) plus the verified
`thoughtspot-liveboard-tml.md` schema: `layout.tiles[]` entries use `x`/`y`/`height`/
`width` grid units (or a predefined `size` enum — `EXTRA_SMALL` … `EXTRA_LARGE`), and
`layout.tabs[]` groups tiles into pages using the same tile shape.

---

## #7 — NOTE_TILE structure — VERIFIED 2026-07-03

The skill generates note tiles using `note_tile.html_parsed_string` — not `viz_type:
NOTE_TILE` / `note_tile.content`, which was the original guess this item was opened
against. SKILL.md v1.3.0 (2026-06-09) rewrote liveboard generation "from verified
behaviour" and switched to `html_parsed_string`.

Status: VERIFIED 2026-07-03 — confirmed against the verified `thoughtspot-liveboard-tml.md`
schema ("Note tiles (text tiles)" section): note tiles use `note_tile.html_parsed_string`,
have no `answer` block, and support HTML content.

---

## #9 — Tab support (multiple dashboards → tabs) — VERIFIED 2026-07-03

When a Tableau workbook has multiple dashboard sheets, the skill's Step 8 offers a choice
between one liveboard per dashboard (**S**) and a single liveboard with one tab per
dashboard plus the Migration Summary tab (**T**), using `layout.tabs[]` (Step 8 prompt
added v1.5.24; Migration Summary tab added v1.5.22).

Status: VERIFIED 2026-07-03 — implemented in v1.5.x, live-verified via the shipped
liveboard migrations and the verified `thoughtspot-liveboard-tml.md` schema
(`layout.tabs[]`: `name`, `description`, `tiles[]`)

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
