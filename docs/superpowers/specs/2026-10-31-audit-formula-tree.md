# Formula dependency tree (roadmap PR 3.2)

**Status:** built to the roadmap's PR 3.2 row (`2026-10-23-audit-v2-roadmap.md`, wave 3),
with the product owner's choices (2026-10-31): roots open one level by default, and the
view is reached from the sidebar and from each Model's scorecard. The first view built on
the 3.1 registry.

## What it shows

One tree per Model. The roots are the formulas nothing else uses, typically the measures
people search on (and, for a circular chain nothing outside it uses, the formula where it is
entered); under each, the formulas it uses, then theirs, down to the table
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
rest, building about 2,000 more rows per press (formulas, columns, parameters and
circular references all count; the formula being opened when it reaches 2,000 is
finished, so a press can overshoot by that formula's uses); when it stops early a note says to press it again or
open the rest by hand. Collapse all closes every node. A formula already on the path from
its root shows as "circular reference to X" rather than being walked. Printing shows only
the subtrees that have been opened, since the rest are not built.

## Where the data comes from

`ts_cli/audit/formula_tree.py` builds the tree from the Model TML the audit already
fetches: nothing new is fetched, and no finding changes. Quoted literals are split off
with `formula_translate.refs.split_literals` before scanning, so bracket text inside a
string (`concat ( '[' , ... )`, a regex class in a `sql_*_op`) is not a reference, while a
quote inside a reference (`[ORDERS::Men's Sales]`) opens no literal (BL-369). A bracket reference then resolves, in order, to:

1. a formula, by its id (`[formula_<name>]`) or `formulas[].name` through
   `engine/tml.formula_ref_index` (the one reading P17's reference graph also uses), or
   by the display name of the column that surfaces it;
2. a parameter (`parameters[].name`);
3. otherwise a column.

Each formula or column a formula uses is listed once, in first-use order; a formula's
reference to itself is not a use. Two formulas sharing a name are one node (the first,
whose references alone are read: a hidden formula only the second uses shows as unused).
When a column name collides with a formula's display name the tree reads it as the
formula, and when a column and a parameter share a name, as the parameter; neither is
verified against how ThoughtSpot resolves the collision. A formula or column whose id is
not a string is ignored, so malformed TML cannot end a narrow run (BL-501).

The rules (P17, P2, H3) read references without skipping literals, so on unusual
expressions the tree and a finding can disagree about whether a formula is used; BL-504
moves them onto the tree's reading. On the SE demo sample they agree.

Roots are the formulas nothing uses. What no root reaches can only be cycles and what they
use; each such cycle is rooted at the first formula, in formula order, everything upstream
of which lies in its own cycle. So a cycle opens from its entry point, never from a
formula beneath it, nor as a second root when another cycle above it uses it, and no
formula is lost.

`build_corpus` adds the tree per Model as `corpus.models[].formula_tree` in the audit
JSON; `report.py` compacts it as `ft`. With the view's script and styles, the page grows
1.7% on the 148-Model SE demo sample. A report rendered from JSON written before this
change has formula counts but no trees, and says to re-run the audit; a Model whose tree
is empty (say, only unnamed formulas) says it has no formulas.

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
display name, parameter and column, quoted literals ignored, quotes inside references,
uses de-duplicated, used-by counts, roots, self-references, cycle rooting (its order, and
a cycle beneath a cycle), malformed entries and ids, and the compacted form. In headless Chrome, checking the text actually shown (not merely
built): roots open one level with collapsed children hidden and deeper levels unbuilt;
Expand all reaches the columns and the circular reference; Collapse all hides them again
and resets `aria-expanded`; the cap stops each press at about 2,000 rows, counting column
leaves, its note says to press again, and a second press continues; Enter and Space open a
node; names with markup and quotes are escaped, in text and in
attributes; parameters, labels and hidden-unused formulas show; the picker's links, the
tree header's scorecard link, the sidebar link and the scorecard's tree link (present only
for a Model with a tree) carry the right hrefs; a report from older JSON, a Model with an
empty tree and an unknown Model each say why there is no tree. Each fix from review was
checked by a deliberate mutation that a test now catches, except apostrophe escaping in
`esc()`, which no sink needs today (the report has no single-quoted attributes). `tests/test_audit_report_views.py` covers the view's registration.
