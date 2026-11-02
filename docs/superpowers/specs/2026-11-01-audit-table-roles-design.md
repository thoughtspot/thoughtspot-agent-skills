# Table roles from join direction (roadmap PR 4.1)

**Status:** design, 2026-11-01. Roadmap row 4.1 (`2026-10-23-audit-v2-roadmap.md`, wave 4).
Scope agreed with the product owner (2026-11-01): the shared classifier, the rules that
use a table's role moved onto it, and the role shown in the ERD. The fan-trap rule is the
next PR, built on this one.

## Why

The audit decides that a table is a fact when it has more than three MEASURE columns
(`engine/tml.py table_role`, `FACT_MEASURE_THRESHOLD`). The ERD decides separately: a
fact is any table with a visible measure (`agents/shared/erd/parser.py _table_kind`).
Neither looks at what actually makes a fact: its place in the joins. On the 148-Model
SE demo sample the two disagree (the audit calls 197 tables facts, the ERD 350), and
both mislabel the cases that matter:

- a fact with one to three measures is called a dimension by the audit (60 tables);
- a dimension holding a few numeric columns typed MEASURE (list price, weight) is called
  a fact (16 tables by the audit, more by the ERD);
- an order header, which the order lines join to and which itself joins out to customer
  and date, is a dimension of the lines that also carries measures (freight, order-level
  discount). Summed naively through the lines, those repeat once per line: the fan
  trap. (Review note, 2026-11-01: ThoughtSpot's engine resolves fan traps when the
  joins' cardinality is declared correctly — ts-object-model-agentql-query
  `references/architecture.md` — so the risk is a wrong or missing cardinality, and
  the ERD's note says that rather than claiming the measures repeat.)
  Neither classifier can name that shape.

The product owner's view, which this design adopts: **a fact sits at the root of the
joins, on the many side; a dimension is joined to, on the one side.** The measures a
table holds refine the role, they never decide it. Some tables hold both roles: a fact
with dimensional attributes, and a dimension with factual attributes (the header case).

## Goals

1. One classifier, shared by the audit, the ERD and the future remodel tool (wave 5),
   that labels every table of a Model from its joins, refined by its measures.
2. The audit rules that read a table's role read it from the classifier.
3. The ERD shows each table's role.
4. Every change in findings is shown on the SE demo sample, explained, before any pin
   moves.

## Non-goals

- **The fan-trap rule.** Next PR (roadmap G6). This PR gives it the roles it needs.
- **Telling a snowflaked hierarchy from an outrigger.** Both are a dimension joined
  from another dimension; join direction cannot tell intent apart (see "Roles").
- **Usage data.** Roles come from TML alone.
- **New findings.** No rule is added; only how existing rules read a role changes.

## Anti-goals (a failure even if it works)

- A role that contradicts the join evidence because a table has many or few measures.
- Finding changes that cannot be explained table by table on the sample.
- The ERD's layout or filters breaking because the role vocabulary grew.
- A second classifier left in place in the audit or the ERD (the measure count surviving
  in a helper). The converters' own fact detectors (`ts_cli/databricks/mv_emit.py
  detect_fact_tables`, which already uses "join root with a measure" but counts formula
  measures; `sv_build_model._detect_fact_tables`, over Snowflake relationships) are out
  of scope; converging them is a backlog item filed by this PR.

## Roles

Every table of a Model (keyed by its `model_tables` alias, else name, as `tml.table_key`
does) gets one **role** and two facts about itself:

| Role | Shape | Measures |
|---|---|---|
| `fact` | On the one side of no join (a root), or the only table in the Model | at least one |
| `factless` | A root with no measures that joins out to other tables: a bridge or a factless fact (event, coverage, status history) | none |
| `dimension` | On the one side of at least one join | none |
| `dimension_with_measures` | On the one side of at least one join | at least one: the header case, or numeric attributes typed MEASURE |

Plus, per table:

- `outrigger: true` when every table that joins to it is itself joined to (it hangs off
  another dimension, never off a root). This covers snowflaked hierarchies and true
  outriggers alike; the documentation says so.
- `attribute_heavy: true` on a `fact` with more descriptive columns than measures: the
  product owner's "fact with dimensional attributes" (46 of 232 facts on the sample).
- `unjoined: true` on a table that takes part in no directed join in a Model of two or
  more tables (it keeps `fact` or `dimension` by its measures). One on the sample.

**Measures** are the table's MEASURE columns in the Model's `columns[]` (matched by the
`column_id` prefix against the table's key), hidden ones included: a hidden measure
still sums. Formula measures are not on any table and are not counted, as today.

### Direction

A join is read many-side → one-side:

- The cardinality is the Model join's own, else (for a `referencing_join`) the
  cardinality of the Table-level join it names, else none. The classifier takes that
  Table-level lookup as an optional argument (`table_roles(model, join_cardinality=None)`,
  a function or mapping from a referencing join's name to its cardinality), so the audit
  and the ERD resolve it the way they already do (`tml.model_joins`,
  `parser._stitch_table_joins`) and the classifier reads the same cardinality D11 does.
- `MANY_TO_ONE`, or no cardinality found: the declaring table (the `model_tables` entry
  whose `joins[]` holds it) is the many side. Joins are declared on the foreign-key side
  (`thoughtspot-model-tml.md`). On the sample no Table-level `joins_with` entry carries a
  cardinality, so 150 of 729 joins rely on this default (the schema's census records 4
  hybrid joins carrying a cardinality on the Model join itself; those use it).
- `ONE_TO_MANY`: reversed, the `with` table is the many side.
- `ONE_TO_ONE`: no direction. It neither makes a table a root nor joins it to.
- `MANY_TO_MANY` (never seen in the census): no direction, as one-to-one.
- A join whose `with` names no table of the Model is ignored.

A table is a **root** when no directed join has it on the one side. A cycle of directed
joins (A→B→A) leaves its members non-roots; they are dimensions by the table above.

### On the sample (148 Models, 796 tables; aggregate counts only)

| Role | Tables |
|---|---|
| fact | 232 (46 attribute-heavy) |
| dimension | 400 + 21 outriggers |
| dimension_with_measures | 103 + 16 outriggers |
| factless | 24 |

Against today's audit rule: 609 tables keep their label; 60 become facts; 16 facts
become dimensions with measures or plain dimensions; 119 tables get the new
dimension-with-measures label. The builder re-derives these from the real code; the
figures here came from a throwaway probe and are a sanity bound, not a test oracle.

A table with no columns in the Model gets its role from its joins with zero measures
(old `table_role` returned "unknown"; only retired D6 read that).

## Where it lives

`agents/shared/erd/roles.py`: a pure function over one Model TML body
(`table_roles(model) -> {table_key: {"role", "outrigger", "attribute_heavy",
"unjoined", "measures", "attributes"}}`), no I/O, no imports beyond the standard
library. The ERD imports it directly; the audit loads it the way
`ts_cli/audit/erd.py` already loads the shared parser (by path, `_ERD_DIR`), so no
second copy exists. The constants it uses (the attribute-heavy comparison) live in it,
named. Malformed shapes (non-dict entries, non-string names or ids) are skipped, never
raised, matching the audit's `_str` convention and BL-501.

**If the audit cannot load it, the audit fails** with a message naming the path. The ERD
embed degrades quietly when the shared parser is missing (`erd.py`), which is fine for a
picture; a rule silently judging without roles is not, and a fallback classifier would be
the second copy this design forbids. ts-cli is installed editable from the repo (root
`CLAUDE.md`), so this only bites an install outside it, where it should be loud.

## Consumers

### Audit

- `engine/tml.py table_role` and `fact_tables` are replaced by calls into the shared
  classifier (cached per Model, as `cached("fact_table_names", ...)` does today), and
  `FACT_MEASURE_THRESHOLD` goes. No other helper counts measures to decide a role.
- `@table_role` returns the new vocabulary. `@fact_tables` and `@fact_table_count`
  return the `fact` tables by key (alias else name; today they key by name).
  `@fact_table_set` returns the `fact` tables' identities **as today** (`fqn`, else name),
  because D7 intersects it with `@table_set`, which uses that identity.
- **D7** (model overlap, active, pinned; `code_rules.model_overlap`) grades a partial
  overlap MEDIUM only when a table the two Models share is a fact in either. "Fact" there
  becomes the `fact` role only: a shared header (`dimension_with_measures`) is a shared
  dimension, which D7 deliberately does not treat as duplication. On the sample its 2
  MEDIUM findings stay and 1 pair becomes MEDIUM; its 9 HIGH findings do not depend on
  roles. Its catalog description ("more than 3 MEASURE columns") is rewritten. Re-pin
  with `repin_findings.py --rule D7` after the change is shown.
- `@is_fact_to_fact_join` becomes **"both ends hold measures"**: each end is `fact` or
  `dimension_with_measures`. This keeps the field's intent (two tables of measures
  joined, so one side's measures repeat) under roles where a root, by definition, is
  never joined to. D11 is the only active rule that reads it: on the sample 4 of its 8
  joins move from INFO to MEDIUM, 4 stay INFO. Its MEDIUM message changes from
  "fact-to-fact join" to wording that names both tables' roles, and its catalog
  description is rewritten likewise. Re-pin D11 with `repin_findings.py --rule D11` only
  after the four are shown in the PR (by count and shape, no names).
- D6 and P5 are retired and do not run; their catalog entries keep reading
  `@table_role` / `@fact_table_count`, so those fields must still evaluate.
- `check-catalog.md` is regenerated from the rewritten D7 and D11 descriptions
  (`python -m ts_cli.audit.generate`). `rule-authoring.md` quotes D11's MEDIUM message
  (line ~115); update the quote.
- The corpus (`corpus.models[]`) gains each table's role, so the report can show it.
  The report shows it in the Model scorecard's table list if that is a one-line change;
  otherwise it waits for the ERD.

### ERD

- `parse_model`'s per-table `kind` stays coarse. The renderer's layout, filter chips,
  overview fill and side-panel pill know only `fact` and `dim` (`renderer.js`; `bridge`
  appears nowhere in it, so today's 15 parser `bridge` tables fall under neither filter
  chip and are drawn as dimensions). So `kind` becomes two-valued: `fact` and `factless`
  → `fact` (a factless table is a root, and the layout centres roots); both dimension
  roles → `dim`. The parser's `bridge` kind goes, which closes that blind spot.
- A new per-table `role` (and the three flags) is added to the bundle. The table's side
  panel pill shows the role in words ("Fact", "Fact with descriptive attributes",
  "Factless / bridge", "Dimension", "Dimension holding measures", each with
  "(outrigger)" where set), with a one-line tooltip saying what it means and that
  "outrigger" also covers a snowflaked hierarchy.
- The ERD's tables change where its old rule ("any visible measure") and the new roles
  disagree; the PR shows how many on the sample.

## Tests

- The classifier: each role and flag on small synthetic Models, every direction case
  (no cardinality, each of the four cardinalities, a `with` outside the Model), a
  directed cycle, a single-table Model with and without measures, aliases, hidden
  measures counted, formula measures not counted, malformed entries.
- The order header / order detail case, end to end: detail is `fact`, header is
  `dimension_with_measures`, customer is `dimension`, and D11 on a one-to-many
  header→detail join (both ends holding measures) is MEDIUM.
- Audit fields: each changed field on fixtures. D11: the existing fixture
  (`data_fanout_fact_to_fact`) still fires MEDIUM; a one-to-many join whose ends each hold
  one to three measures is now MEDIUM (was INFO); a one-to-many join with one end holding
  no measures stays INFO. D7: a shared `fact` gives MEDIUM, a shared
  `dimension_with_measures` does not, and `@fact_table_set` still matches `@table_set`
  identities.
- ERD: the bundle's `kind` for each role, the new `role` field, and the pill text.
- Replay of the SE demo sample: findings differ from main only in D11's four severity
  changes and D7's one new MEDIUM; the report renders with no JS errors.
- Loading: the audit fails with a clear message when the shared classifier is missing.

## Left to the builder

- Function and field names beyond those fixed above; how the cache is keyed.
- The exact tooltip and pill wording, within the meanings above.
- Whether the scorecard shows roles in this PR (only if it is a small change).
- Version bumps: ts-cli minor (new field values, changed severity), ts-audit minor,
  ts-object-model-erd minor (new bundle field, new pill text).

## Calls made without the product owner (check these)

- `factless` is one role for both bridges and factless facts; telling them apart needs
  more than direction.
- One-to-one joins carry no direction.
- A missing cardinality means the declaring table is the many side.
- Hidden measures count; formula measures do not.
- "Attribute-heavy" means more descriptive columns than measures.
- D11's MEDIUM condition becomes "both ends hold measures".
- D7's "shared fact" means the `fact` role only.
- The audit fails if it cannot load the shared classifier.
- A factless table is drawn as a fact in the ERD (its pill says "Factless / bridge").
- The converters' fact detectors are left alone (backlog item).
