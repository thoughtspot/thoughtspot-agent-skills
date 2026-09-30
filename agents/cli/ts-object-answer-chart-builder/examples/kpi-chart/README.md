# Opportunity Rate — KPI Card

A single-number KPI card: headline rate, red/green change-vs-last-year indicator,
and a comparison sentence with dynamic counts. Rendered as plain DOM — no Muze
canvas (a KPI card has no plot).

## ThoughtSpot setup

Search query needs these measures (rename the constants at the top of
`result/script.js` if your columns are named differently):

| Measure | Required | Meaning |
| --- | --- | --- |
| `Opportunity Count` | yes | opportunities created this period |
| `Prior Opportunity Count` | yes | same period last year |
| `Opportunity Rate` | optional | headline rate (fraction `0.1` or percent `10` both work) |
| `Prior Opportunity Rate` | optional | same period last year — drives the ↓/↑ indicator |

Typical formulas: `Prior Opportunity Count` = `sum(if(<last-year period>) then 1 else 0)`
or a vs-period formula; `Opportunity Rate` = `opportunity count / lead count`.

Behavior:
- With all four measures: headline = `Opportunity Rate`, indicator = rate change
  in percentage points (red ↓ when falling, green ↑ when rising).
- Without the rate measures: headline falls back to the percent change in counts
  and the indicator is hidden.
- The `0` / `3` in the sentence are always the two count measures, bolded.

## Paste into Muze Studio

Paste `result/script.js` as-is — the local preview shim lives in `index.html`
and is not part of the pasted code. Card text, measure names, and colors are
the constants at the top of the script. Typography scales with the tile size.

## Local preview

Serve `result/` over HTTP (ES modules don't load from `file://`) and open
`index.html` — sample data (0 vs 3, 0% vs 10%) renders automatically.
