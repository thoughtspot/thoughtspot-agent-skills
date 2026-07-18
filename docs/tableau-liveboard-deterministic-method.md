# Tableau → ThoughtSpot: the deterministic dashboard method (and the gap)

Reverse-engineered from the FedEx Ground VEDR KI Dashboard migration (session
`local_54c74f74`, board `f6d7f50b` — 22 tiles, model `fedex_vedr_sample_model`), whose
harness lives (un-versioned) at `~/projects/tableau-published-ds-repro/`
(`build_fedex_model.py`, `build_fedex_liveboard_v4.py`, `enrich_driver_events.py`,
`verify_lb.py`, `resolve_published.py`).

## The root-cause finding (why quality swings between sessions)

**The Tableau *liveboard* step is not codified.** PowerBI (`generate_tml.py`) and Sisense
(`sisense2ts`) converters are fully Python-driven — they emit the liveboard AND a per-run
coverage report deterministically. The Tableau converter codifies parse → formula translation
→ **model** TML, but the **dashboard/liveboard reconstruction is agent-driven** — done by
hand-written, per-workbook scripts (`build_fedex_liveboard_v4.py`) each time.

That is the whole story behind the "magnanimous dip": a good result depends on the agent
re-deriving the tile set, KPI-per-measure rules, sections, and data-formula alignment from
scratch every session. Miss any of it (or skip reusing the harness) and the board regresses
from 22 faithful tiles to 3 generic ones. **Determinism has to move into the skill.**

## The method that produced the good board (make this the spec)

### 1. Resolve the source schema (published / custom SQL)
`resolve_published.py` / `download_datasource.py` / `probe_customsql.py` — get the real
physical columns behind the sqlproxy / Custom SQL Queries. This is the input the model needs.

### 2. Build a reconciled multi-table model (`build_fedex_model.py`)
- **Two SQL views** for the two Custom SQL Queries: `fedex_driver_events_sv` (driver-grain
  events) + `fedex_ki_breakdown_sv` (KI breakdown per fleet), joined on `fleet_account_id`.
  This is how the multi-query custom SQL is reconciled (skill Step 5b).
- Base columns (with aggregation): Fleet Account Name, Driver Name, Behavior, Total Days
  Active (SUM), Normalised Days (AVG), Total Events (SUM), per-KI value cols (AVERAGE).
- **KI grade formulas** (ATTRIBUTE): `if ( [ki_breakdown_sv::<ki_col>] > <threshold> ) then
  'FAIL' else 'PASS'`.
- **Final Grade** (ATTRIBUTE): `if ( <all ki_col <= threshold> ) then 'PASS' else 'FAIL'`.
- **Event count formulas** (MEASURE): `sum_if ( [events_sv::behavior] = '<Behavior String>'
  [and driver_name != 'UNIDENTIFIED'] , [events_sv::eventscounts] )`.
- The behavior strings and thresholds are read from the TWB calcs — NOT invented.

### 3. Provision + align sample data (`enrich_driver_events.py`)
When the source is unreachable, provision synthetic data — **but the categorical values must
match what the formulas reference** (e.g. `behavior = 'seat_belt_violation'`, not
`'seat_belt'`), or every KI/event tile reads zero. This data↔formula alignment is a required,
non-obvious step. (`ts load databricks/snowflake` provisions; enrichment aligns categories.)

### 4. Emit the liveboard faithfully (`build_fedex_liveboard_v4.py`)
The 22 tiles, grouped into sections:
- **Scorecard KPIs:** Final Grade, Normalised Days, Total Days Active — **one KPI per
  measure** (a multi-measure KPI collapses to a single number).
- **Per-KI KPIs:** 6 grade KPIs (`[<KI> Grade]`) + 6 value KPIs (`[<KI> KI Value]`).
- **Six Top-5 driver bars:** `search_query: "[Driver Name] [<KI> Events] top 5"`.
- **Middle "Behaviours and Events":** native dim+measure **COLUMN** `[Behavior] [Total
  Events]` — a wide multi-measure chart hangs the renderer / auto-picks a donut; a single
  dim+measure renders vertical columns like the source.
- Sections via `layout` groups; theme `LBC_A` / `CURVED`. Rebuild in place by GUID.

### 5. Verify (`verify_lb.py`)
Export the liveboard to PDF (`POST /api/rest/2.0/report/liveboard`) and confirm it renders
(non-trivial byte size, tiles present). Numeric check via SpotQL against the model, compared to
the warehouse.

### Hard-won rules baked in (regression guards)
- One KPI per measure (multi-measure KPI collapses).
- Middle chart = single dim+measure COLUMN (wide measures hang the renderer).
- Data categorical values must match the event-formula string literals.
- On re-import, flip `display_mode` by `answer.name`, not viz id (ids renumber on export).

## Codification target (close the gap)

Move steps 2 and 4 into the skill so they are deterministic, driven by `ts tableau parse`:
1. **Parser role/dashboard extraction (open item #20) — DONE (ts-cli v0.59.0).**
   `ts tableau parse` now emits `dashboards` (`ts_cli/tableau/dashboards.py`: zones → visuals
   with mark + shelf/role/measure-tagged fields, calc-id→caption resolution, date buckets,
   grid tiles), and `ts tableau build-liveboard --input <parse.json> --model-name <m>` consumes
   it — **parse→build-liveboard now runs with no hand-assembled spec** (FedEx: 18 auto-tiles,
   lint-clean). This was the highest-leverage fix; the liveboard step is no longer agent-driven.
2. **Model KI-formula generation** — the grade/value/event formula patterns above are
   mechanical from the TWB calcs; generate them in `ts tableau build-model` rather than a
   bespoke `build_fedex_model.py`.
3. **Liveboard assembly** — KPI-per-measure, sectioning, the middle-chart rule, and theming
   belong in `ts tableau build-liveboard` (the emission engine exists; the spec assembly is
   the missing half).
4. **Coverage report + PDF verify** — emit a per-run coverage report (like PowerBI/Sisense)
   and optionally the PDF verify, so quality is measured, not assumed.

Until 1–3 land, the Tableau liveboard is agent-driven and quality will vary session to session.
The `build_fedex_*` harness is the reference implementation to port from.
