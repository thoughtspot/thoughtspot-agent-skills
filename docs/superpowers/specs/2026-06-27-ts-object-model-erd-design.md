# ts-object-model-erd — Design

**Status:** Approved (design) · **Date:** 2026-06-27 · **Author:** damian.waldron

Render an existing ThoughtSpot Model into an interactive, self-contained HTML ERD —
structure, joins, columns, audit findings, and row-level security — that opens in any
browser and can be shared without a ThoughtSpot login. The renderer is packaged as a
shared module so other skills (notably `ts-audit`) can reuse it.

A working proof-of-concept exercising every interaction in §7 was validated before this
design (vanilla-SVG render of a real Model TML).

---

## 1. Purpose & scope

**In scope (v1):**

- Parse an existing ThoughtSpot Model (Model TML + its referenced Table TMLs) into a
  normalized graph, and render it as a single self-contained HTML ERD.
- Two input sources: local TML files, or a live ThoughtSpot instance.
- Multiple models in one shareable file with an index and a model switcher.
- The renderer published as a shared module (`agents/shared/erd/`) for reuse.

**Out of scope (noted, future — not specced here):**

- **ts-audit integration** — injecting audit findings and embedding per-model ERDs into
  `audit_report.html`. The shared renderer is designed to make this a small follow-up.
- **Image → TML ingestion** — a separate skill (opposite direction: authoring a new model
  from a diagram image), which would reuse this renderer and data model behind a
  human-review loop.
- Editing or writing TML back; sidecar layout files.

**Direction:** ThoughtSpot Model → ERD visualization. Read-only. The skill never modifies
the source model.

---

## 2. Architecture (approach C: Python owns parsing/assembly, renderer is a static asset)

```
agents/shared/erd/                  ← shared module (this skill + future ts-audit)
  renderer.css                      ← static styles (from the validated mockup)
  renderer.js                       ← static vanilla-SVG renderer (no external libs)
  render.py                         ← inlines assets + injects model JSON → self-contained HTML
agents/cli/ts-object-model-erd/
  SKILL.md                          ← orchestration (source selection, export, render, share)
  parser.py                         ← TML → ModelGraph (stitches Model + Table TMLs)
  erd_data.py                       ← normalize ModelGraph → renderer MODEL schema
  tests/
    test_parser.py
    test_render.py
    fixtures/                       ← sample Model + Table TMLs
```

- **Python is standard-library only** (`xml`/`yaml` via the repo's existing TML helpers,
  `json`, `pathlib`) — no pip installs, no JS build toolchain. Consistent with
  `ts-audit/report.py`.
- **Why approach C:** the fidelity risk lives entirely in the parser (RLS in table TMLs,
  cardinality/origin, formula table-binding). Keeping the renderer as a deterministic
  static asset puts the test boundary where bugs occur, keeps the renderer editable and
  lintable (not buried in a Python string), and lets `ts-audit` import the same
  `render.py` later.
- **Module boundary:** `render.py` depends only on the MODEL schema (§3), not on TML. The
  parser depends only on TML and produces the MODEL schema. Either side can change
  internally without breaking the other.
- For v1 the **parser lives in the skill**; it is promoted to `agents/shared/erd/` when
  ts-audit integration is built (ts-audit needs the same model+table stitching).

---

## 3. Data model — the parser ↔ renderer contract

The single interface both sides depend on. `render.py` consumes exactly this; `parser.py`
+ `erd_data.py` produce exactly this.

```jsonc
{
  "model":   { "name": str, "guid": str, "description": str },
  "tables": [{
    "id":   str,                       // table name as referenced in the model
    "kind": "fact" | "dim" | "bridge", // best-effort classification (visual only)
    "cols": [{
      "name":   str,                   // model column display name (or raw col in keys mode)
      "src":    str,                   // underlying column / formula marker
      "role":   "MEASURE" | "ATTR" | "FORMULA",
      "agg":    str | null,            // SUM/AVG/… for measures
      "key":    bool,                  // join key
      "hidden": bool,                  // FK helper col not surfaced as a model column
      "flag":   "crit" | "warn" | "info" | null   // set by findings (ts-audit)
    }],
    "rls": [{ "name": str, "expr": str, "scope": str }]   // from the TABLE TML
  }],
  "joins": [{
    "from":   str, "to": str, "name": str,
    "card":   "MANY_TO_ONE" | "ONE_TO_MANY" | "ONE_TO_ONE" | "MANY_TO_MANY",
    "origin": "table" | "model",       // where the join is defined (governance signal)
    "type":   "INNER" | "LEFT_OUTER" | "RIGHT_OUTER" | "FULL_OUTER"
  }],
  "formulas": { "<name>": "<expr>" },
  "findings": [{                        // OPTIONAL — empty unless populated by ts-audit
    "id": str, "sev": "crit"|"warn"|"info", "check": str,
    "target": str, "title": str, "where": str, "detail": str, "rec": str
  }]
}
```

Multiple models are carried as an array of these objects plus a small index summary
(§6).

---

## 4. Parser & fidelity (the hard part)

**Sources and what each provides:**

| Source | Provides |
|---|---|
| **Model TML** | `model_tables` (with `referencing_join` names), `columns` (`TABLE::COL` ids), `formulas`, `properties` (`join_progressive`, `is_bypass_rls`, `spotter_config`) |
| **Table TMLs** | join `type` + `cardinality` + FK columns, `db_column_properties`, **`rls_rules`** |

**Key rules:**

- **Stitching is mandatory for full fidelity.** RLS rules, cardinality, join type, and
  join origin are *not* in the Model TML — they live in the Table TMLs. The parser must
  resolve each `referencing_join` to its definition.
- **Join origin:** a referenced join whose definition is found in a Table TML →
  `origin: "table"` (reusable across models; changing it can ripple). A join defined
  inline in the model → `origin: "model"` (scoped to this model).
- **fact / dim / bridge** classification heuristic: a table with measure columns or
  outgoing FK joins → `fact`; a pure join target with no measures → `dim`; a table that
  is both joined-from and joined-to without measures → `bridge`. Documented as
  best-effort and visual only — never affects correctness.
- **Column → table** mapping via the `TABLE::COL` prefix on `column_id`. **Formula
  binding:** parse `[TABLE::COL]` references in `expr` to attribute a formula to its
  primary table for display.
- **Graceful degradation:** if Table TMLs are unavailable, render structure from the
  Model TML alone — omit RLS, cardinality, join type, and origin — and **log exactly
  what is degraded**. No silent gaps (consistent with the repo's "no silent caps" rule).

---

## 5. Inputs / CLI flow

**Two sources:**

1. **Local TML files** — a path to a folder or an explicit list. Auto-discover
   `*.model.tml` and `*.table.tml`, stitch each model to its tables by GUID/name.
2. **Live ThoughtSpot** — reuse `ts-profile-thoughtspot` + the `ts` CLI. Enumerate
   models, let the user select one or more, export their TML (model + dependent tables),
   cached — the same mechanism as `ts-audit` Step 4.

**SKILL.md step flow:**

```
Step 0  Overview / plan                              (confirm)
Step 1  Choose source: files | live TS               (you choose)
Step 2  [live] Authenticate + enumerate + select     (confirm before export)
Step 3  Read / export TML (model + tables, cached)    auto
Step 4  Parse + stitch → ModelGraph → MODEL schema    auto
Step 5  Render self-contained HTML                     auto
Step 6  Open / share                                   you
```

**Options:** `--redact-rls` (hide RLS expressions but keep the shield badge + propagation
tinting, for external sharing), `--out <path>`, `--max-models <n>`.

---

## 6. Multi-model output

A **single self-contained HTML file** containing:

- all selected models as a JSON array (each conforming to §3),
- an **index landing page** — one card per model with table / join / finding / RLS
  counts — which doubles as the future ts-audit environment map,
- an in-page **model switcher** dropdown.

For very large environments, embedded models are **capped** (default 25, `--max-models`),
and any dropped models are **logged** by name — never silently truncated.

---

## 7. Interactions (locked by the validated mockup)

- **Layouts:** Organic (force), Star (fact-centric radial), Layered → and ↓ (Sugiyama),
  with animated transitions (respecting `prefers-reduced-motion`).
- **Orthogonal routing** toggle (layered views only) with lane separation.
- **Focus / ghosting:** click a table to isolate it + its neighbours; shift/⌘-click to
  compare multiple tables and trace the shortest join path between them.
- **Table finder** (autocomplete) to jump to a table.
- **Column modes:** collapsed / join keys / flagged only / all columns.
- **Findings overlay** (toggle) — borders + column dots by severity; only active when
  `findings[]` is present.
- **RLS overlay** + **secured-subgraph isolate** — shields on secured tables, purple tint
  on tables that inherit the filter through joins, isolate mode ghosts everything else.
- **Notation:** Arrow (TS-native) ⟷ Crow's-foot (cardinality).
- **Join-origin badges:** `T` (table-level) / `M` (model-local).
- **Reactive inspector:** table → columns/formulas/joins/RLS; join → cardinality, type,
  origin, blast radius; finding → detail + fix.

---

## 8. Persistence

- **localStorage auto-save** — dragging a table persists its position per model and per
  layout view; restored on reload.
- **Bake-on-export** — a "Save a copy" control re-emits the HTML with current positions
  embedded, so recipients open it already arranged.
- **No sidecar files** — persistence is entirely client-side; the skill does not manage
  layout state on disk.

Caveat: programmatic downloads may be restricted when the file is embedded in a sandboxed
host; this works normally for the standalone file.

---

## 9. Testing (the approach-C boundary)

- **Parser (pytest)** — the primary suite. Fixtures: the real Dunder Mifflin Model TML
  plus a synthetic multi-table fixture that includes RLS rules and a model-local join.
  Assert the resulting MODEL schema: join cardinality/type/origin, RLS extraction and
  propagation inputs, fact/dim/bridge classification, formula→table binding, and
  **degraded mode** (table TMLs absent → structure-only + log).
- **render.py** — assert the output is genuinely self-contained (no external `http`,
  `src`, `href`, or `@import` references), the model JSON is embedded, and the embedded
  count matches the input (including the cap/log path).
- **renderer.js** — `node --check` syntax validation in CI. Not DOM-unit-tested: it is
  deterministic given the MODEL schema and was proven by the mockup.

---

## 10. Open questions / future work

- **ts-audit integration:** promote `parser.py` to `agents/shared/erd/`, have ts-audit's
  `analyzer.py` populate `findings[]`, and embed the ERD as a tab in `audit_report.html`.
- **Image → TML ingestion:** a separate skill (`ts-convert-from-image` or
  `ts-object-model-from-sketch`). Vision extraction → MODEL schema → review in this
  renderer → emit draft TML. Lossy (no data types, no warehouse binding, cardinality only
  if the source diagram uses crow's-foot), so it always routes through a human-review
  step and hands off to `ts-load-source-data` + `ts-object-model-coach`.
- Whether crow's-foot or arrow should be the default notation (currently arrow).
