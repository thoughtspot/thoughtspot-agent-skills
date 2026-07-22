<!-- currency: sisense — 2026-07 (Sisense L2024.x JAQL) -->
# Worked example — Sisense numeric-range dashboard filter → Liveboard filter chip

A Sisense dashboard filter bar carries interactive filters that apply across every widget.
ThoughtSpot's equivalent is a **Liveboard filter chip** (a `generic_filter` on a column that
scopes all vizzes). `ts sisense build-liveboard` extracts these from `dashboard.filters[]` and
injects them into the emitted liveboard after `build_from_spec` returns. The hard case is a
**numeric range**, because the flattened `values` list cannot express the bound semantics —
the extractor reconstructs the operator from the raw Sisense filter subdict.

## The mapping (from `answers.py._range_generic_filter`)

A Sisense range filter's `raw` keys map to a ThoughtSpot `generic_filter {oper, values}`:

| Sisense raw keys | ThoughtSpot `oper` | Meaning |
|---|---|---|
| `equals` | `EQ` | exact match |
| `from` **and** `to` | `BW_INC` | between, inclusive |
| `fromNotEqual` **and** `toNotEqual` | `BW` | between, exclusive |
| `from` only | `GE` | ≥ inclusive lower bound |
| `fromNotEqual` only | `GT` | > exclusive lower bound |
| `to` only | `LE` | ≤ inclusive upper bound |
| `toNotEqual` only | `LT` | < exclusive upper bound |

Precedence matters: `equals` wins first; a two-sided inclusive range (`from`+`to`) becomes
`BW_INC` before any single-bound rule fires.

## Example

Sisense dashboard filter on `[Orders.Revenue]`, "greater than or equal to 1000, less than 5000":
```json
{
  "jaql": {
    "dim": "[Orders.Revenue]",
    "filter": { "from": 1000, "toNotEqual": 5000 }
  }
}
```
`from` is inclusive and `toNotEqual` is exclusive, so this is **not** a clean `BW_INC`/`BW`
pair (mixed inclusivity). The single-bound fallback fires in order and picks the inclusive
lower bound first → `GE 1000`. (A pure two-sided range would use `from`+`to` → `BW_INC`.)

Emitted Liveboard filter chip:
```yaml
- column: [Revenue]
  is_mandatory: false
  is_single_value: false
  display_name: ""
  generic_filter:
    oper: GE
    values: [1000]
```

A clean inclusive range `{ "from": 1000, "to": 5000 }` instead yields:
```yaml
  generic_filter:
    oper: BW_INC
    values: [1000, 5000]
```

## Gotchas (from the code)

- **Column must be exposed on the model.** When `build-liveboard` knows the model columns, a
  filter whose column is not on the model is dropped (a measure-range filter on a formula not
  materialised as a column disappears). It retries on the date-hierarchy base name
  (`Date (Calendar)` → `Date`) before dropping.
- **member / exclude are separate kinds.** `members` → `IN`, `exclude.members` → `NOT_IN` — not
  range operators.
- **Unrecognised presets still produce a bare chip.** An `all` / relative-date / unknown preset
  yields a column-only interactive chip (no `generic_filter`) so nothing is silently dropped.
- **A per-attribute top-N is NOT a chip.** `top`/`bottom` filters are per-widget (baked into the
  widget answer as `top N`), so the liveboard-chip extractor skips them.
