<!-- currency: qlik — 2026-07 (ts qlik IR v0.1) -->

# Qlik App IR — the extract↔transform contract

The **intermediate representation (IR)** is the single contract between the
Qlik-extraction side and the ThoughtSpot-transform side of the `ts qlik` converter. Extractors
(offline, engine, engine-artifacts, qlik-cloud) populate these structures;
`ts qlik build-model` / `build-liveboard` consume them. The IR is plain JSON — dump it, inspect it,
hand-edit it, and re-run later stages without touching Qlik again.

Source of truth: `tools/ts-cli/ts_cli/qlik/ir.py`. Every field is optional-friendly —
a best-effort offline extraction fills what it can and leaves the rest empty
rather than failing.

## Root: `QlikApp`

| Field | Type | Notes |
|---|---|---|
| `app_name` | str | App display name (defaults to `"Untitled"`) |
| `source_file` | str? | Path to the source `.qvf`, if known |
| `extraction_mode` | str | `offline` \| `engine` (records how faithful the extract is) |
| `connections` | `Connection[]` | Qlik data connections (`lib://…`) |
| `tables` | `Table[]` | Tables loaded into the Qlik data model |
| `dimensions` | `MasterDimension[]` | Master dimensions |
| `measures` | `MasterMeasure[]` | Master measures |
| `variables` | `Variable[]` | Qlik variables |
| `sheets` | `Sheet[]` | Sheets (→ Liveboard tabs), each holding charts |
| `load_script` | str? | Recovered load-script text |
| `notes` | `ExtractionNote[]` | Everything the extractor could not fully recover |

Serialization: `to_json()`, `save(path)`, static `load(path)`, static
`from_dict(d)`. `from_dict` tolerates unknown/missing keys so hand-edited IR and
future fields never hard-fail.

## Nested structures

**`Connection`** — `name`, `qlik_type` (`Snowflake`/`ODBC`/`Folder`/…),
`properties{}`. Secrets are never present in a `.qvf`; credentials are supplied
at load time.

**`Table`** — `name`, `columns[Column]`, `db_name?`, `schema_name?`,
`source_connection?`, `load_script?`.
**`Column`** — `name`, `data_type` (Qlik-side, mapped later), `src_table?`.

**`MasterDimension`** — `id`, `label`, `fields[]`, `expression?` (set for
calculated dimensions). → ThoughtSpot worksheet column or formula.

**`MasterMeasure`** — `id`, `label`, `expression` (e.g. `Sum(Sales)`),
`number_format?`. → ThoughtSpot worksheet formula.

**`Variable`** — `name`, `definition`. → ThoughtSpot formula / parameter.

**`Sheet`** — `id`, `title`, `charts[Chart]`. → Liveboard tab.
**`Chart`** — `id`, `title`, `viz_type` (Qlik object type: `barchart`, `kpi`,
`table`…), `dimensions[]`, `measures[]`, `raw{}` (anything uninterpreted, kept
verbatim for the report).

**`ExtractionNote`** — `severity` (`info`/`warning`/`manual`), `area`
(`connection`/`chart`/`script`/…), `message`. These become rows in the migration
report — nothing is silently dropped.

## Object mapping (Qlik → ThoughtSpot)

| Qlik Sense | ThoughtSpot | IR carrier |
|---|---|---|
| Data connection (`lib://`) | Connection (`connection/create`) | `Connection` |
| Loaded table | Table (TML `table`) | `Table` + `Column` |
| Master dimension | Model/worksheet column | `MasterDimension` |
| Master measure | Model/worksheet formula | `MasterMeasure` |
| Variable | Formula / parameter | `Variable` |
| Sheet | Liveboard tab | `Sheet` |
| Chart / visualization | Answer (viz) on the Liveboard | `Chart` |
| Load-script ETL | **Manual** — flagged in the report | `load_script` + `ExtractionNote` |
