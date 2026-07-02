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
  4.  Render ERD .......................................... auto
  5.  Open / share ........................................ done

### Options

| Flag | Default | Effect |
|---|---|---|
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
- **Live path:** for each selected model, export with associated tables into a temp directory:
  ```bash
  ts tml export "{model_guid}" --fqn --associated --profile "{profile}"
  ```
  `--associated` pulls the Table TMLs needed for join cardinality, join origin, RLS rules, and join keys.

---

## Step 4 — Render

Run:

```bash
python3 agents/cli/ts-object-model-erd/build_erd.py <src-dir-or-files> --out model_erd.html
```

Add `--redact-rls` if the user wants to hide RLS expressions for external sharing.
Add `--max-models N` to change the model cap.

Report any degraded-fidelity or model-cap log lines to the user. Degraded fidelity means
Table TMLs were missing for some joins — the ERD still renders structure, but cardinality,
join type, join origin, RLS, and join keys are omitted for those joins.

---

## Step 5 — Open / share

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
| 1.1.1 | 2026-07-02 | Classifier: a table is a fact only when it has real (visible) measures — an outgoing join alone no longer makes a dimension a fact (e.g. a user/lookup table that joins onward); measureless pass-through tables are bridges. ERD viewer: clicking a flagged fan-out join no longer errors when no fan-out finding is attached (shows a generic fan-out explanation) |
| 1.1.0 | 2026-07-02 | Layered layout clusters joined tables (Sugiyama median crossing-reduction); fix dimension/fact classifier (hidden and non-measure formula columns no longer promote a dimension to a fact); ERD parser + assembler moved to the shared `erd` library so the skill and the ts-audit ERD embed share one definition |
| 1.0.0 | 2026-07-01 | Initial release |
