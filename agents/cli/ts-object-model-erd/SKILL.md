---
name: ts-object-model-erd
description: Render an existing ThoughtSpot Model (Model TML + its Table TMLs) into an interactive, self-contained HTML ERD — tables, joins, columns, findings and row-level security — that opens in any browser and is shareable without a ThoughtSpot login. Use when someone wants to chart, visualise, diagram, or review the structure of a Model. Not for editing models or generating TML.
---

# ThoughtSpot: Model ERD

Render a Model into a single self-contained HTML ERD. Read-only — never modifies the source model.

**When to use this skill:**

- You want to visualise or diagram the structure of a ThoughtSpot Model
- You need to review joins, cardinality, column layout, or RLS before making changes
- You want to share a Model's structure with someone who doesn't have ThoughtSpot access
- You need a visual reference while coaching or auditing a Model

**Relationship to other skills:**

| Need | Skill |
|---|---|
| Coach the model for Spotter readiness | `/ts-object-model-coach` |
| Audit the full environment | `/ts-audit` |
| Remove or repoint dependencies | `/ts-dependency-manager` |

Ask one question at a time. Wait for each answer before proceeding.

---

## References

| File | Purpose |
|---|---|
| [../../shared/schemas/thoughtspot-model-tml.md](../../shared/schemas/thoughtspot-model-tml.md) | Model TML structure |
| [../../shared/schemas/thoughtspot-table-tml.md](../../shared/schemas/thoughtspot-table-tml.md) | Table TML structure — joins_with, rls_rules |
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth, profile config |

---

## Prerequisites

- Python 3.9+ with `pyyaml` (`pip install pyyaml`)
- For live export: a ThoughtSpot profile (`/ts-profile-thoughtspot`) + the `ts` CLI

---

## Step 0 — Overview (confirm before starting)

On skill invocation, display this plan before doing any work:

---
**ts-object-model-erd** — render a Model into a self-contained HTML ERD.
Read-only — never modifies the source model.

### Steps

  1.  Choose source ....................................... ask
  2.  (Live) Authenticate + select models ................ ask/auto
  3.  Read or export TML .................................. auto
  4.  Synthesize AI-analysis corpus ...................... auto
  5.  Render ERD .......................................... auto
  6.  Open / share ........................................ done

### Options

| Flag | Default | Effect |
|---|---|---|
| `--ai-analysis` | off | Inject a synthesized business-context corpus (domain, objectives, audience, questions, AI instructions) into the ERD |
| `--redact-rls` | off | Replace RLS expressions with `(redacted)` for external sharing |
| `--max-models` | 25 | Cap on models per ERD file |
| `--out` | `model_erd.html` | Output path |

---

Confirm the user wants to proceed before starting Step 1.

---

## Step 1 — Choose source

Ask: **(A) Local TML files or folder**, or **(B) Live ThoughtSpot instance**?

- **A — Files:** ask for the path(s) to the TML files or directory. Skip to Step 3.
- **B — Live:** proceed to Step 2.

---

## Step 2 — (Live only) Authenticate, enumerate, select

1. Read `~/.claude/thoughtspot-profiles.json`. If missing or empty, run `/ts-profile-thoughtspot`.
2. List Models:
   ```bash
   ts metadata search --subtype ONE_TO_ONE_LOGICAL --all --profile "{profile}"
   ```
3. Show the user the list. Let them pick one or more models. Confirm selection before export.

---

## Step 3 — Read or export TML

- **Files path:** note the folder/paths provided in Step 1.
- **Live path:** for each selected model, export it **with its associated tables** and
  redirect the JSON straight to a file:
  ```bash
  ts tml export "{model_guid}" --fqn --associated --profile "{profile}" > export.json
  ```
  `--associated` pulls the Table TMLs needed for join cardinality, join origin, RLS rules,
  and join keys.

  `ts tml export` writes a **single JSON array** to stdout (one `{edoc}` object per exported
  object). Feed that file directly to the builder in Step 5 — **do not** hand-split it into
  per-object `.tml` files. `build_erd.py` ingests the export JSON as-is and routes each object
  to model/table by its TML content. Multiple models: pass several GUIDs to one `ts tml export`
  call, or pass several `export*.json` files to the builder.

---

## Step 4 — Synthesize the AI-analysis corpus (optional but recommended)

Models rarely define a business-context corpus (domain, objectives, audience, business
questions). Synthesize one by **reasoning over the model definition** — table and column
names, per-column `properties.ai_context`, `properties.synonyms`, measure aggregations,
formula expressions, joins, and RLS. This is a judgment task for you (the agent); do not
try to derive it with a heuristic script.

Write the result to a sidecar JSON keyed by model **guid** (or name):

```json
{
  "<model-guid>": {
    "ai_analysis": {
      "domain": "one-paragraph description of the business domain the model serves",
      "objectives": ["what analysis it's built for", "..."],
      "personas": ["who uses it", "..."],
      "questions": ["representative business questions it answers", "..."]
    },
    "ai_instructions": ["semantic rules grounded in the model, e.g. 'Amount is the primary revenue measure'", "..."]
  }
}
```

Ground every entry in the actual model: cite real measures, note semi-additive or averaged
aggregations, and lift genuine guidance out of `ai_context` (e.g. day-grain date handling).
This step is **read-only** — the corpus enriches the ERD only and is never written back to
the source model.

---

## Step 5 — Render

Run — pass the Step 3 `export.json` (or a directory / individual `.tml` files) directly:

```bash
python3 agents/cli/ts-object-model-erd/build_erd.py export.json --out model_erd.html
```

`src` accepts, in any mix: a `ts tml export` JSON dump, individual `.tml`/`.yaml` files, or a
directory of them. Model vs. table is decided by TML content, so no naming convention or split
step is required.

Add `--ai-analysis <corpus.json>` to inject the Step 4 corpus into the ERD's Model domain /
Key objectives / Audience / Business questions / AI instructions sections.
Add `--redact-rls` if the user wants to hide RLS expressions for external sharing.
Add `--max-models N` to change the model cap.

If the source contains **no model** (e.g. only table TMLs), the builder exits non-zero with a
clear message rather than writing an empty diagram — re-export with `--associated` and confirm
the model GUID.

Report any degraded-fidelity or model-cap log lines to the user. Degraded fidelity means
Table TMLs were missing for some joins — the ERD still renders structure, but cardinality,
join type, join origin, RLS, and join keys are omitted for those joins.

---

## Step 6 — Open / share

Open `model_erd.html` in a browser. The file is fully self-contained — share the single
HTML file; no ThoughtSpot login required to view.

**ERD features:**
- Four layouts: Organic, Star, Layered →, Layered ↓
- Two notations: Arrow (ThoughtSpot-style), Crow's foot (cardinality)
- Column modes: Collapsed, Join keys, Flagged only, All columns
- Focus mode: click a table to highlight its neighbourhood; shift-click to compare two tables
- RLS overlay: toggle to see secured subgraph
- Findings overlay: toggle to see structural findings
- Drag to reposition tables; positions auto-save in localStorage
- Multi-model switcher (when multiple models rendered)
- Navigation: drag or scroll to pan; pinch / ⌘-scroll (Ctrl-scroll on Windows) to zoom;
  arrow keys pan, `+`/`-` zoom, `0` fits (to the focused neighbourhood if a table is
  focused, otherwise the whole model) — built for large models (verified on a 79-table
  export) where the default fit would otherwise be microscopic
- Minimap: always-on overview in the bottom-right corner with a viewport rectangle;
  click or drag it to jump anywhere in the model; collapsible, and the collapsed/expanded
  state persists across reloads
- Search zooms to a readable level (never leaves you at a microscopic fit scale)

---

## Notes

- RLS rules, join cardinality, join type, and join origin come from the **Table** TMLs.
  Without them the ERD still renders structure, and the run logs what was omitted.
- Layout positions auto-save in the browser's localStorage per model.
- The HTML file has no external dependencies — no CDN, no network requests.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.4.1 | 2026-07-02 | **Correct the unresolvable-join handling.** A join whose `with:` target isn't a table in the model cannot occur in a valid ThoughtSpot export (the model editor won't create one and TML import validates join targets), so the 1.4.0 approach of defensively skipping such joins in the viewer was guarding an impossible state. The parser now **drops** any join with a non-existent endpoint at the source (and logs it as malformed TML), so the viewer no longer needs — and no longer carries — the `adj`/`undir`/edge dangling-endpoint guards. This also makes the join count honest (a dropped join is no longer counted-but-undrawn). No change for valid models (verified 0 dropped on a 79-table model); only genuinely malformed TML is affected. |
| 1.4.0 | 2026-07-02 | **Large-model navigation.** Scroll/trackpad now pans the canvas (pinch or ⌘/Ctrl-scroll zooms, cursor-anchored) instead of always zooming; a pan-drag no longer wipes focus/selection on release. Arrow keys pan, `+`/`-` zoom, `0` fits. New always-on **minimap** (bottom-right, collapsible, state persisted to localStorage, Share-HTML safe) shows the whole model with a live viewport rectangle; click or drag it to jump anywhere. `fit()` now has a shared `MIN_K=0.12` zoom floor (was an unbounded 0.047× on a 79-table model) used consistently by fit, wheel-zoom and `#zoom-out`; `#zoom-fit`/`0` fit to the focused neighbourhood instead of clearing focus when something is focused; search now zooms to a readable level (≥0.9×) before centering. Fixed a latent crash: a join referencing a table with no Table TML and no `model_tables` entry (a "degraded fidelity" join) previously threw in the browser (`adj[...]`/`undir[...]` on an unknown id) instead of just being logged and skipped. |
| 1.3.0 | 2026-07-02 | **Ingest:** `build_erd.py` now ingests a `ts tml export` JSON dump directly (raw `{edoc}` list or `--parse` form) and routes each object to model/table by TML **content**, not filename — the SKILL.md Step 3 → 5 flow is now a clean pipe with no manual split (the previous flow silently rendered an empty diagram when export JSON was hand-split into wrongly-suffixed files). Builder now **exits non-zero with a clear message** when the source contains no model, instead of writing an empty HTML. Existing `.model.tml`/`.table.tml` files and directories still work unchanged. **RLS model corrected:** RLS is no longer modelled as propagating along join edges. A table is highlighted only when a rule is **defined on it** (secured, red) or when it is **referenced in another table's rule expression** (in RLS path, amber). Removed the incorrect "RLS inherited / constrained via joins" pills, tooltips, rule-card "propagates through joins" line, dashed-red "RLS edge", and the join-ancestor subgraph; rule cards now list the other tables a rule references. **Column inspector fix:** column groups (Join keys / Measures / Attributes / Formulas) are now flat headed sections instead of `<details>` nested inside the Columns `<details>` — nested disclosure left the column rows hidden in some browsers (the section header showed a count but expanding revealed nothing). |
| 1.2.0 | 2026-07-02 | New `--ai-analysis` flag injects an agent-synthesized business-context corpus (domain, objectives, audience, business questions, AI instructions) into the ERD (read-only; never written back). Column inspector now surfaces per-column AI context and synonyms. RLS legend parity: secured tables show the red border + 🔒 by default (no longer gated behind the RLS overlay) and the "In RLS path" fill matches the legend swatch. Focus: double-click (join subtree) and shift-click compare now hide out-of-scope tables instead of dimming them. Parser fix: handle the nested `rls_rules: {rules: […]}` TML shape (previously crashed) |
| 1.1.1 | 2026-07-02 | Classifier: a table is a fact only when it has real (visible) measures — an outgoing join alone no longer makes a dimension a fact (e.g. a user/lookup table that joins onward); measureless pass-through tables are bridges. ERD viewer: clicking a flagged fan-out join no longer errors when no fan-out finding is attached (shows a generic fan-out explanation) |
| 1.1.0 | 2026-07-02 | Layered layout clusters joined tables (Sugiyama median crossing-reduction); fix dimension/fact classifier (hidden and non-measure formula columns no longer promote a dimension to a fact); ERD parser + assembler moved to the shared `erd` library so the skill and the ts-audit ERD embed share one definition |
| 1.0.0 | 2026-07-01 | Initial release |
