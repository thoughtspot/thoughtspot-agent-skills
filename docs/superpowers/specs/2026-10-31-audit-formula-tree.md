# Formula dependency tree (roadmap PR 3.2)

**Status:** built to the roadmap's PR 3.2 row (`2026-10-23-audit-v2-roadmap.md`, wave 3),
with the product owner's choices (2026-10-31): roots open one level by default, and the
view is reached from the sidebar and from each Model's scorecard. The first view built on
the 3.1 registry.

## What it shows

One tree per Model. The roots are the formulas nothing else uses, typically the measures
people search on; under each, the formulas it uses, then theirs, down to the table
columns (`TABLE::COL`) and parameters. Each formula is shown by the name people search it
by, its surfacing column's name (hover shows the `formulas[].name` when that differs),
and carries:

- its kind, MEASURE or ATTRIBUTE, from the `columns[]` entry that surfaces it;
- **hidden helper** when that column is hidden, or no column surfaces it, and other
  formulas use it: it exists to feed them;
- **hidden, unused** when it is hidden and no formula uses it: nothing can reach it, a
  cleanup candidate;
- **used by N formula(s)**.

Roots open one level; any formula opens on click (or Enter/Space). Expand all opens the
rest, building at most 2,000 more rows per press (formulas, columns, parameters and
circular references all count); when it stops early a note says to press it again or
open the rest by hand. Collapse all closes every node. A formula already on the path from
its root shows as "circular reference to X" rather than being walked. Printing shows only
the subtrees that have been opened, since the rest are not built.

## Where the data comes from

`ts_cli/audit/formula_tree.py` builds the tree from the Model TML the audit already
fetches: nothing new is fetched, and no finding changes. Quoted literals are removed
before scanning, so bracket text inside a string (`concat ( '[' , ... )`, a regex class in
a `sql_*_op`) is not a reference. A bracket reference then resolves, in order, to:

1. a formula, by its id (`[formula_<name>]`) or `formulas[].name` through
   `engine/tml.formula_ref_index` (the one reading P17's reference graph also uses), or
   by the display name of the column that surfaces it;
2. a parameter (`parameters[].name`);
3. otherwise a column.

Each formula or column a formula uses is listed once, in first-use order; a formula's
reference to itself is not a use. Two formulas sharing a name are one node (the first);
when a column name collides with a formula's display name, the tree reads it as the
formula (not verified against how ThoughtSpot resolves such a collision).

Roots are the formulas nothing uses. What no root reaches can only be a cycle and what it
uses; each such cycle is rooted at the first formula, in formula order, that nothing
outside the cycle uses, so the cycle opens from its entry point rather than from a formula
beneath it, and no formula is lost.

`build_corpus` adds the tree per Model as `corpus.models[].formula_tree` in the audit
JSON; `report.py` compacts it as `ft` (+1.2% page size on the 148-Model SE demo sample). A
report rendered from JSON written before this change has formula counts but no trees, and
says to re-run the audit.

## Choices

- **Lazy children.** A node's children are built when it is first opened. A formula used
  by many others would otherwise be drawn once per path, and Expand all on a heavily
  shared Model could grow without bound; hence also the per-press cap.
- **Display-name references count.** Exported TML references formulas by id, but a
  hand-built Model may use the display name; both resolve, as they do for P17.
- **No findings in the tree.** Marking problems on nodes is wave 4's (the severity rubric
  and new rules); the tree is the place they can land later.

## Tests

`tests/test_audit_formula_tree.py`: kinds, hidden flags, labels, uses by id, name,
display name, parameter and column, quoted literals ignored, uses de-duplicated, used-by
counts, roots, self-references, cycle rooting (including its order), malformed entries,
and the compacted form. In headless Chrome, checking the text actually shown (not merely
built): roots open one level with collapsed children hidden and deeper levels unbuilt;
Expand all reaches the columns and the circular reference; Collapse all hides them again;
the cap stops each press at 2,000 rows, counting column leaves, and a second press
continues; Enter opens a node; names with markup and quotes are escaped, in text and in
attributes; parameters, labels and hidden-unused formulas show; the picker, the sidebar
link and the scorecard link (present only for a Model with a tree, with the right href)
reach the tree; a report from older JSON and an unknown Model each say why there is no
tree. `tests/test_audit_report_views.py` covers the view's registration.
