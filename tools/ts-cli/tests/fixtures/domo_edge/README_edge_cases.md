# Domo edge-case fixture bundle

Deliberately awkward inputs that the happy-path bundle in `../domo/` does not exercise.
Kept separate so `../domo/` stays a readable worked example (and so the committed
`migration-report.example.md` stays the clean case) while these paths still have
regression coverage.

Each file exists because a real defect shipped through the gap it covers — see the
PR #440 review:

| File | Covers |
|---|---|
| `domo_table_orders.json` / `domo_table_refunds.json` | two datasets sharing a Beast Mode name, and an id-like join key alongside incidental shared columns (`Region`, `Date`) |
| `domo_model_beastmodes.json` | string functions with no ThoughtSpot equivalent (`UPPER`, `TRIM`, `REPLACE`), a simple-form `CASE expr WHEN`, a duplicate `Net Revenue` name across both datasets, a Beast Mode **referencing a sibling Beast Mode** whose name exists on both datasets, Beast Modes **named after a column** (on the other dataset and on its own), and one Domo marks `INVALID` |
| `domo_card_500001_table_min_price.json` | a card with a non-SUM (`MIN`) per-column aggregation |
| `domo_liveboard_page_edge.json` | the page wiring for the card above |
| `domo_card_500002_bar_refunds_by_region.json` | a card on the **second** dataset, whose `Region`/`Revenue` are display-renamed in the Model — emitting raw Domo names would silently bind it to `Orders` |
| `domo_card_500003_table_second_page.json` + `domo_liveboard_page_edge2.json` | a **second page**, so cards on pages 2..n are exercised — they must be reported `Skipped`, not vanish |

Page 1 deliberately carries **both** real cards (one per dataset) so the cross-dataset
binding invariant in `tests/test_domo_binding.py` actually has something to check.
