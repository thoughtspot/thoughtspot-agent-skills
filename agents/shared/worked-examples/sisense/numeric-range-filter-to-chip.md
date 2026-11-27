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
| one inclusive and one exclusive bound | `BW_INC` | between; both bounds kept, the exclusive end read as inclusive (a known boundary gap, ts-convert-from-sisense open-item #5) |
| `from` only | `GE` | ≥ inclusive lower bound |
| `fromNotEqual` only | `GT` | > exclusive lower bound |
| `to` only | `LE` | ≤ inclusive upper bound |
| `toNotEqual` only | `LT` | < exclusive upper bound |

Precedence matters: `equals` wins first; any two-sided range becomes `BW_INC` (or `BW` when
both bounds are exclusive) before a single-bound rule fires, so neither bound is ever dropped.

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
`from` is inclusive and `toNotEqual` is exclusive (mixed inclusivity). Both bounds are kept,
so the chip is `BW_INC` over `[1000, 5000]`; the exclusive upper end is read as inclusive,
which is the boundary gap ts-convert-from-sisense open-item #5 tracks.

Emitted Liveboard filter chip:
```yaml
- column: [Revenue]
  is_mandatory: false
  is_single_value: false
  display_name: ""
  generic_filter:
    oper: BW_INC
    values: [1000, 5000]
```

A one-sided `{ "from": 1000 }` instead yields:
```yaml
  generic_filter:
    oper: GE
    values: [1000]
```

## Gotchas (from the code)

- **Column must be exposed on the model.** When `build-liveboard` knows the model columns, a
  filter whose column is not on the model is dropped (a measure-range filter on a formula not
  materialised as a column disappears). It retries on the date-hierarchy base name
  (`Date (Calendar)` → `Date`) before dropping.
- **member / exclude are separate kinds, in the exported-Liveboard shape.** `members` → a
  top-level `oper: in` with `values`, `exclude.members` → `oper: not in` (live-verified to filter
  every tile, ts-convert-from-sisense open-item #5); no `generic_filter`, and not range operators.
- **What carries no condition.** An `all` preset is no condition, so its chip is column-only,
  faithfully. A relative-date or unknown preset also yields a column-only chip on the default
  path, which leaves the chip **unfiltered**. With `--target-model` that chip is reported
  NEEDS REVIEW in `migration-report.json`, and so is every range chip (this generic_filter form
  is still TO VERIFY on a live Liveboard, ts-convert-from-sisense open-item #5) and any filter on
  a date value.
- **A per-attribute top-N is NOT a chip.** `top`/`bottom` filters are per-widget (baked into the
  widget answer as `top N`), so the liveboard-chip extractor skips them.
