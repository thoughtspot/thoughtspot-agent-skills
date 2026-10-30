# Formula dependency tree (roadmap PR 3.2)

**Status:** built to the roadmap's PR 3.2 row (`2026-10-23-audit-v2-roadmap.md`, wave 3),
with the product owner's choices (2026-10-31): roots open one level by default, and the
view is reached from the sidebar and from each Model's scorecard. The first view built on
the 3.1 registry.

## What it shows

One tree per Model. The roots are the formulas nothing else uses, typically the measures
people search on; under each, the formulas it uses, then theirs, down to the table
columns (`TABLE::COL`). Each formula shows:

- its kind, MEASURE or ATTRIBUTE, from the `columns[]` entry that surfaces it;
- **hidden helper** when that column is hidden, or no column surfaces it (it exists to
  feed other formulas);
- **used by N**, how many formulas use it.

Roots open one level; any formula opens on click (or Enter/Space). Expand all opens the
rest, stopping at 2,000 rows with a note; Collapse all closes them. A formula already on
the path from its root shows as "circular reference to X" rather than being walked.

## Where the data comes from

`ts_cli/audit/formula_tree.py` builds the tree from the Model TML the audit already
fetches: nothing new is fetched, and no finding changes. A reference resolves to a
formula by its id (`[formula_<name>]`) or display name through
`engine/tml.formula_ref_index`, the one reading P17's reference graph also uses; any other
bracket reference is a column. A cycle reachable from no root is rooted at its first
formula, so no formula is lost. `build_corpus` adds it per Model; `report.py` compacts it
as `ft` (+1.2% page size on the 148-Model SE demo sample).

## Choices

- **Lazy children.** A node's children are built when it is first opened. A formula used
  by many others would otherwise be drawn once per path, and Expand all on a heavily
  shared Model could grow without bound; hence also the 2,000-row cap.
- **Display-name references count.** Exported TML references formulas by id, but a
  hand-built Model may use the display name; both resolve, as they do for P17.
- **No findings in the tree.** Marking problems on nodes is wave 4's (the severity rubric
  and new rules); the tree is the place they can land later.

## Tests

`tests/test_audit_formula_tree.py`: kinds, hidden helpers, uses by id, display name and
column, used-by counts, roots, self-references, a cycle rooted once, malformed entries;
in headless Chrome, roots open one level with deeper levels unbuilt, Expand all reaches
the columns and the circular reference, and the picker, scorecard link and sidebar link
all reach the tree. `tests/test_audit_report_views.py` covers the view's registration and
its render from JSON written before 3.2 (no tree: the picker says so).
