"""Model and Table TML helpers the rules share — joins, table keys and roles, RLS
column references, indexing, string types — and the constants they grade by.

Moved here from `ts_cli/audit/rules.py` when the legacy check functions were deleted
(the rule catalog change): every name left is read by a derived field (fields.py,
fields_data.py), a scope (scopes.py) or a code rule (code_rules.py). The helpers only
the deleted checks used (`is_wide_and_not_progressive`, `FUNC_IN_EXPR`,
`MIN_TABLES_FOR_JOIN_PROGRESSIVE`) went with them: D4/P4 and P14/S9 now carry that
logic as catalog data, and `test_checks_registry.py` holds each such pair together.

Why one module (BL-304, 2026-09-22 audit): the data and performance check sets were
split by **copying**, and six rules existed twice — join_progressive on a wide model
(D4/P4), a function call in an RLS expression (S9/P14), a string column in an RLS rule
(S8/P15), join-graph depth (D1/P7), fact-table detection (D11/P5) and the 75-column
ceiling (D1/P8). A threshold tuned in one angle silently left the other on the old
value, and D2/P6 shipped the *same* two defects and had to be fixed twice in PR #528.

**Findings are still emitted per angle.** A wide un-progressive model genuinely is
both a modelling and a performance concern; what is shared is the rule, not the
reporting — each rule keeps its id, severity and wording.

Kept importable on Python 3.9 with no third-party imports: the catalog gate loads the
engine modules that import it.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from ts_cli.formula_translate.refs import split_literals
from ts_cli.tml_join_graph import node_id

#: Warehouse types ThoughtSpot treats as strings. A string join or RLS key is
#: markedly slower than an integer one and is what several checks look for.
STRING_TYPES = ("VARCHAR", "CHAR", "STRING", "TEXT")

#: A bracketed column reference inside a TML expression: ``[TABLE::COL]``.
BRACKET_REF = re.compile(r"\[([^\]]+)\]")

#: Keys the Model and Table TML schemas define as mappings, never lists
#: (thoughtspot-model-tml.md, thoughtspot-table-tml.md). A list or scalar under one is
#: malformed. The Model holding it (or using a Table that holds it) is not judged at all:
#: `unreadable_documents` names it and `engine/run.py` leaves it out of every rule, and
#: the report lists it under "Could not be read" (BL-406 item 10, product owner's ruling
#: 2026-10-30). A field path still reads such a value as None (fields._step) and Python
#: reads go through `mapping`, as a backstop: neither maps over it nor crashes on it.
MAPPING_KEYS = frozenset({"properties", "spotter_config", "db_column_properties"})

#: Where the Model, Table and Answer TML schemas hold a list of mappings (`[{...}]`) or a
#: mapping (`{...}`) the audit reads, by path from the document body; a nested shape is
#: what each mapping holds in turn. Any other shape there is malformed, and is treated
#: as a malformed MAPPING_KEYS value is (BL-501): the object is not judged, and is listed.
#: Only what is read unguarded belongs here: a shape no rule reads (`parameters`, whose
#: readers check, or `rls_rules.table_paths`) is left alone, as main left it, rather
#: than costing its Model a judgement. `rls_rules` is a mapping only. The flat list of
#: rules the ERD parser also accepts is in no schema doc and in none of the census's
#: Tables with RLS, and reading it as absent would call a protected Table unprotected;
#: listed, it is judged neither way.
SHAPES = {
    "model": {"columns": [{}], "formulas": [{}], "filters": [{}],
              "model_tables": [{"joins": [{}]}], "model_instructions": {}},
    "table": {"columns": [{}], "joins_with": [{}], "rls_rules": {"rules": [{}]}},
    "answer": {"tables": [{}], "formulas": [{}]},
}


def expr_refs(expr: Any) -> list:
    """The `[...]` references of a formula, RLS rule or join `on`, in order: outside
    quoted literals (`split_literals` keeps a bracketed reference whole even when its name
    holds a quote, BL-369), stripped, empty ones dropped. The one reading every audit
    reader shares — the formula tree, P17 and P2's reference graph, H3, the RLS column
    reads and the join key reads (BL-504). [] for a non-string."""
    if not isinstance(expr, str):
        return []
    code = " ".join(seg for lit, seg in split_literals(expr) if not lit)
    return [r.strip() for r in BRACKET_REF.findall(code) if r.strip()]


def formula_reference_index(formulas: list, columns: Any = ()) -> Dict[Any, Any]:
    """How a formula is referred to -> its NAME: `formula_ref_index` (its id, or its
    name), plus the display name of the column that surfaces it where that names no
    formula of its own (a hand-built Model may refer to a formula that way). Shared by
    the report's formula tree and P17 / P2's reference graph (BL-504)."""
    by_ref = formula_ref_index(formulas)
    surfacing: Dict[Any, Any] = {}
    for c in columns or []:
        fid = c.get("formula_id") if isinstance(c, dict) else None
        if isinstance(fid, str) and fid and fid not in surfacing:
            surfacing[fid] = c.get("name")
    for f in formulas:
        if not isinstance(f, dict) or not isinstance(f.get("name"), str) or not f["name"]:
            continue
        cname = surfacing.get(f.get("id")) if isinstance(f.get("id"), str) else None
        if isinstance(cname, str) and cname and cname not in by_ref:
            by_ref[cname] = f["name"]
    return by_ref


def formula_ref_index(formulas: list) -> Dict[Any, Any]:
    """How a formula is referred to in an expression -> its NAME. A cross-reference is
    written as the formula's id (`[formula_<name>]`), or, in a hand-built model, its
    display name; both resolve to the name (BL-300). The one reading shared by P17's
    reference graph and the report's formula tree. A non-string name or id is skipped,
    not a TypeError that ends the run (BL-501's class)."""
    by_ref: Dict[Any, Any] = {}
    for f in formulas:
        fname = f.get("name", "") if isinstance(f, dict) else ""
        if not isinstance(fname, str) or not fname:
            continue
        by_ref[fname] = fname
        fid = f.get("id", "")
        if isinstance(fid, str) and fid:
            by_ref[fid] = fname
    return by_ref


def mapping(obj: Any, key: str) -> dict:
    """`obj[key]` when it is a mapping, else {}: the one reader for a MAPPING_KEYS key,
    so a malformed (list or scalar) value reads as absent rather than raising."""
    value = obj.get(key) if isinstance(obj, dict) else None
    return value if isinstance(value, dict) else {}


def _body(doc: Any, kind: str) -> Tuple[dict, list]:
    """A document's `kind` body (a mapping, else {}) and why its shape is malformed:
    a body that is not a mapping (null included: readers take a present body as a
    mapping), a MAPPING_KEYS value that is not one, or a departure from SHAPES[kind].
    A document with no body at all reads as empty, as the pinned `*_lists_none` and
    `sec_owning_table_edges` inputs judge it."""
    if not isinstance(doc, dict) or kind not in doc:
        return {}, []
    body = doc[kind]
    if not isinstance(body, dict):
        return {}, [f"'{kind}' is not a mapping"]
    reasons = [f"'{p}' is not a mapping" for p in malformed_mappings(body)]
    return body, reasons + misshapen(body, SHAPES[kind])


def _name(body: dict) -> str:
    name = body.get("name")
    return name if isinstance(name, str) else ""


def _malformed_tables(tables: dict) -> Dict[Any, Tuple[str, list]]:
    """{Table key: (its name, why it is malformed)} for each malformed Table."""
    out: Dict[Any, Tuple[str, list]] = {}
    for key, doc in (tables or {}).items():
        body, reasons = _body(doc, "table")
        if reasons:
            out[key] = (_name(body), reasons)
    return out


def _model_reasons(body: dict, own: list, bad_tables: dict) -> list:
    """Why a Model is unreadable: its own malformed shapes (`own`), then each malformed
    Table it uses (by `model_tables[].fqn`, the key `ctx.tables` holds Tables under)."""
    reasons = list(own)
    for mt in _list(body.get("model_tables")):
        fqn = mt.get("fqn") if isinstance(mt, dict) else None
        if isinstance(fqn, str) and fqn in bad_tables:
            reasons.append(f"uses Table '{mt.get('name')}', whose TML is malformed")
    return list(dict.fromkeys(reasons))  # a Table used twice (aliases) is one reason


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _answer_reasons(body: dict, own: list, excluded: Dict[Any, str]) -> list:
    """Why an Answer is not judged: its own malformed shapes (`own`), then each excluded
    Model or Table it is built on (`tables[].fqn`) — its formulas and table references
    are judged against that object, which no rule can now see (H7, H8, H9)."""
    reasons = list(own)
    for ref in _list(body.get("tables")):
        key = ref.get("fqn") if isinstance(ref, dict) else None
        if isinstance(key, str) and key in excluded:
            reasons.append(f"built on {excluded[key]}, which is not judged")
    return list(dict.fromkeys(reasons))


def _message(kind: str, name: Any, key: Any, reasons: list) -> str:
    return f"{kind} '{name or ''}' ({key or 'no guid'}): {'; '.join(reasons)}; not judged"


def unreadable_documents(ctx: Any) -> Tuple[set, set, set, list]:
    """What no rule may judge, because its TML, or TML it depends on, holds the wrong
    shape where the audit reads one (`_body`: MAPPING_KEYS, SHAPES): (Model guids, Table keys, Answer guids, one message
    per object, its reasons joined).

    A Table is unreadable when its own TML has such a path; a Model when its own TML does
    or it uses such a Table; an Answer when its own TML does or it is built on such a
    Model or Table. The unit is the whole Model: skipping only the bad column left
    counts, sibling checks and the readiness score reading it anyway (PR #693 review,
    round 4), and keeping its Answers judged them against a Model no rule could see
    (round 5)."""
    bad_tables = _malformed_tables(ctx.tables)
    excluded = {key: f"Table '{name}'" for key, (name, _) in bad_tables.items()}
    models, messages = set(), []
    for doc in ctx.models:
        body, own = _body(doc, "model")
        reasons = _model_reasons(body, own, bad_tables)
        if reasons:
            guid = doc.get("guid")
            models.add(guid)
            if isinstance(guid, str):
                excluded[guid] = f"Model '{_name(body)}'"
            messages.append(_message("Model", _name(body), guid, reasons))
    for key, (name, reasons) in bad_tables.items():
        messages.append(_message("Table", name, key, reasons))
    answers, answer_messages = _unreadable_answers(ctx.answers, excluded)
    return models, set(bad_tables), answers, messages + answer_messages


def _unreadable_answers(answers: list, excluded: Dict[Any, str]) -> Tuple[set, list]:
    guids, messages = set(), []
    for doc in answers or []:
        body, own = _body(doc, "answer")
        reasons = _answer_reasons(body, own, excluded)
        if reasons:
            guids.add(doc.get("guid"))
            messages.append(_message("Answer", _name(body), doc.get("guid"), reasons))
    return guids, messages


def misshapen(doc: dict, shape: dict, path: str = "") -> list:
    """Why `doc` departs from `shape` (a SHAPES entry), in shape order: a key that holds
    something other than its list of mappings or mapping, or a list entry that is not a
    mapping. Absent, null and any other falsy value (`0`, `""`) are excepted: every
    reader takes those as empty (`or []`), so they never ended a run, and the pinned
    `*_lists_none` inputs judge them as empty. Paths name a list entry as
    `malformed_mappings` does: by its `name` when it has one, else by its index."""
    out: list = []
    for key, sub in shape.items():
        value = doc.get(key)
        if not value:
            continue
        here = f"{path}.{key}" if path else key
        if isinstance(sub, list):
            out += _misshapen_list(value, sub[0], here)
        elif not isinstance(value, dict):
            out.append(f"'{here}' is not a mapping")
        else:
            out += misshapen(value, sub, here)
    return out


def _misshapen_list(value: Any, entry_shape: dict, here: str) -> list:
    if not isinstance(value, list):
        return [f"'{here}' is not a list"]
    out: list = []
    for i, entry in enumerate(value):
        name = entry.get("name") if isinstance(entry, dict) else None
        at = f"{here}[{name}]" if isinstance(name, str) and name else f"{here}.{i}"
        if isinstance(entry, dict):
            out += misshapen(entry, entry_shape, at)
        else:
            out.append(f"'{at}' is not a mapping")
    return out


def malformed_mappings(doc: Any, path: str = "") -> list:
    """Dotted paths in `doc` where a MAPPING_KEYS key holds something other than a
    mapping (absent and null excepted), in document order. A list entry is named by its
    `name` when it has one (`columns[Amount].properties`), else by its index."""
    out: list = []
    if isinstance(doc, dict):
        for key, value in doc.items():
            here = f"{path}.{key}" if path else str(key)
            if key in MAPPING_KEYS and value is not None and not isinstance(value, dict):
                out.append(here)
            else:
                out += malformed_mappings(value, here)
    elif isinstance(doc, list):
        for i, value in enumerate(doc):
            name = value.get("name") if isinstance(value, dict) else None
            out += malformed_mappings(value, f"{path}[{name}]" if name else f"{path}.{i}")
    return out


def join_count(model_tables: list) -> int:
    """Joins declared across the model's tables (each lives under its ``model_tables[]``
    entry; Model TML has no Model-level ``joins``)."""
    return sum(len(t.get("joins") or []) for t in model_tables or [])


def join_depth(model_tables: list) -> int:
    """Longest join chain reachable from any table in the model.

    A DFS per start node, counting hops. Cycles terminate on the visited set. Each
    table is a node by its key (alias, else name) and a join's ``with`` resolves to the
    table it names (``join_target_key``); until 2026-10 nodes were keyed by ``name`` while
    ``with`` carries aliases, so a chain of aliased tables read as depth 1.
    """
    tables = model_tables or []
    graph: dict = {}
    for t in tables:
        tn = table_key(t)
        for j in (t.get("joins") or []):
            graph.setdefault(tn, []).append(join_target_key(tables, j.get("with", "")))
    if not graph:
        return 0
    max_d = 0
    for start in graph:
        visited: set = set()
        stack = [(start, 0)]
        while stack:
            node, depth = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            max_d = max(max_d, depth)
            for nb in graph.get(node, []):
                stack.append((nb, depth + 1))
    return max_d


def table_key(model_table: dict) -> str:
    """The prefix this model table's ``column_id`` values carry.

    The model schema: ``column_id`` is ``TABLE_NAME::col``, where TABLE_NAME is
    *"the `name:` (or `alias:`) from model_tables"*. Several checks keyed on
    ``name`` alone, so a role-playing dimension — the whole reason an alias
    exists — resolved to no columns: D10 called a fully-populated table a
    zero-column leaf, D6 and D11 silently saw "unknown" (BL-305).
    """
    return model_table.get("alias") or model_table.get("name") or ""


def join_target(model_tables: list, ref: Any) -> Optional[dict]:
    """The model_tables entry a join's ``with`` names: the entry whose node identity
    (``tml_join_graph.node_id``) it is — exactly, else ignoring case, as
    ``tml_join_graph.JoinGraph.resolve`` resolves it — else, for a ``with`` written as a
    physical name, the entry with that ``name``. None when nothing matches."""
    if not isinstance(ref, str) or not ref:
        return None
    entries = [t for t in (model_tables or []) if isinstance(t, dict)]
    for key in (node_id, lambda t: t.get("name")):
        for fold in (lambda s: s, str.lower):
            want = fold(ref)
            for t in entries:
                k = key(t)
                if isinstance(k, str) and k and fold(k) == want:
                    return t
    return None


def joined_keys(model_tables: list) -> set:
    """Every table on either side of a join, by key (alias, else name): each table that
    declares a join, and each table a join's ``with`` names (``join_target_key``). The
    one definition D5, D10 and H3 share (H3 kept its own copy until 2026-10, and drifted)."""
    tables = model_tables or []
    joined: set = set()
    for t in tables:
        for j in (t.get("joins") or []):
            joined.add(table_key(t))
            joined.add(join_target_key(tables, j.get("with", "")))
    return joined


def join_target_key(model_tables: list, ref: Any) -> Any:
    """The column-prefix key (``table_key``) of the table a join's ``with`` names, or
    ``ref`` itself when it names no model table."""
    target = join_target(model_tables, ref)
    return table_key(target) if target is not None else ref


def join_column_types(join: dict, model: dict, col_types: dict) -> dict:
    """`col_types` (`AuditContext.column_types`: `KEY::COL` -> warehouse type, keyed by
    each model table's alias, else name) as this join reads it: its two ends' columns
    also answer under their physical Table `name`. A referencing join's `on` lives in
    the Table TML and names Tables (`[DATE::KEY]`), so an aliased end read as unknown and
    P6 and D16 never saw it (BL-507). Only this join's own ends are added, so one alias of
    a role-playing Table never lends its types to another's join."""
    ends = [join.get("model_table"),
            join_target(model.get("model_tables") or [], join.get("with"))]
    out = dict(col_types)
    for mt in ends:
        if not isinstance(mt, dict):
            continue
        key, phys = table_key(mt), mt.get("name")
        if not key or not isinstance(phys, str) or not phys or phys == key:
            continue
        prefix = f"{key}::"
        for k, v in col_types.items():
            if k.startswith(prefix):
                out[f"{phys}::{k[len(prefix):]}"] = v
    return out


def model_joins(model: dict, tables: dict):
    """Yield every join of a model, inline or referencing, in one shape.

    A ``model_tables[].joins[]`` entry comes in two forms::

        inline       {with, on, type, cardinality}     condition in the model
        referencing  {with, referencing_join[, type]}  condition in the TABLE

    For a referencing join the definition lives in the source Table TML's
    ``joins_with[]``, keyed by the name ``referencing_join`` holds, and carries
    ``{name, destination: {name, fqn}, on, type}``.

    D2/D3/D11/P6 read only ``joins[].on``, so a referencing join looked like a
    join with no keys and no type — and that is the dominant shape in practice.
    Live-verified 2026-09-23: **0 of 6** joins in a real "Retail Sales - RLS"
    model carried an inline ``on``, and one of them was a VARCHAR join key the
    audit reported as zero (BL-306).

    The model's own ``type`` wins where it sets one: observed live overriding a
    table that says ``INNER`` with ``LEFT_OUTER``.

    ``on`` comes back empty when the referenced table is not in scope. That is
    *unknown*, not *no keys*, and a caller must not read it as clean.
    """
    for mt in (model.get("model_tables") or []):
        by_name = _joins_with_index(mt, tables)
        for j in (mt.get("joins") or []):
            yield _resolve_join(mt, j, by_name)


def _joins_with_index(model_table: dict, tables: dict) -> dict:
    """``joins_with[]`` of this model table's source Table TML, keyed by name."""
    table = (tables or {}).get(model_table.get("fqn", "")) or {}
    return {j.get("name", ""): j
            for j in (table.get("table", {}).get("joins_with") or [])}


def _resolve_join(model_table: dict, join: dict, by_name: dict) -> dict:
    """One join in the common shape, inline or referencing."""
    ref = join.get("referencing_join", "")
    base = by_name.get(ref, {}) if ref else {}
    dest = base.get("destination") or {}
    return {
        "model_table": model_table,
        "name": join.get("name") or ref or join_label(model_table, join),
        "on": join.get("on") or base.get("on", ""),
        # The model overrides the table's type where it declares one.
        "type": join.get("type") or base.get("type", ""),
        "with": join.get("with") or dest.get("name", ""),
        # The model's own cardinality wins, as its type does; exported Table TML
        # rarely carries one (0 of 165 joins_with entries, 2026-07-30 census).
        "cardinality": join.get("cardinality") or base.get("cardinality", ""),
    }


def join_label(model_table: dict, join: dict) -> str:
    """A name for a join, which real TML does not give one.

    ``model_tables[].joins[]`` carries no ``name`` key — none of the 493 joins in
    the 2026-07-30 census has one — so every join finding was reported with an
    empty ``object_name`` and could not be identified in the report. Prefers a
    declared name if some future export grows one.
    """
    declared = join.get("name", "")
    if declared:
        return declared
    left = table_key(model_table)
    right = join.get("with", "")
    return f"{left} -> {right}" if left and right else (left or right)


def model_table_roles(model: dict, tables: dict) -> Dict[str, dict]:
    """Each model table's role, by key (alias, else name): the shared classifier
    (agents/shared/erd/roles.py, loaded through ts_cli.audit.erd), with a referencing
    join's cardinality read from its Table's `joins_with` as `model_joins` reads it.
    `{key: {role, outrigger, attribute_heavy, unjoined, measures, attributes}}`; role is
    fact, factless, dimension or dimension_with_measures."""
    from ts_cli.audit.erd import load_table_roles  # erd imports nothing from engine

    def cardinality(model_table: dict, join: dict) -> Any:
        return _resolve_join(model_table, join,
                             _joins_with_index(model_table, tables))["cardinality"] or None
    return load_table_roles()(model, cardinality)


def rls_column_refs(table: dict):
    """Yield ``(rule, column_name, data_type, value_casing)`` per RLS column ref.

    The column's type and casing come from the **Table** TML's own ``columns[]``,
    which is where ``db_column_properties`` lives. An unresolvable reference
    yields ``""`` for both, and a caller must not read that as "not a string" —
    it means unknown. Shared by S8 and P15, which differ only in whether they
    require ``value_casing`` to be absent.
    """
    t = table.get("table", {})
    props = {}
    for c in (t.get("columns") or []):
        props[c.get("name", "")] = (
            mapping(c, "db_column_properties").get("data_type", ""),
            mapping(c, "properties").get("value_casing", ""),
        )
    for rule in ((t.get("rls_rules") or {}).get("rules") or []):
        for ref in expr_refs(rule.get("expr", "")):
            col = ref.split("::")[-1] if "::" in ref else ref
            dt, vc = props.get(col, ("", ""))
            yield rule, col, dt, vc


#: `index_type` suppresses indexing; every other documented value selects a
#: strategy, and omitting the key means full indexing.
NOT_INDEXED = "DONT_INDEX"


def is_indexed(column: dict) -> bool:
    """Whether a model column is text-search indexed.

    The schema is explicit: *"`DONT_INDEX` suppresses text-search indexing …
    Omit for full indexing (default)"*, with `DEFAULT`, `PREFIX_ONLY`,
    `PREFIX_AND_SUBSTRING` and `PREFIX_AND_WORD_SUBSTRING` all selecting a
    strategy rather than disabling one.

    S2, P9 and P11 each tested *presence* of the key instead (BL-299), which
    inverts both halves: a column indexed by default — the commonest shape in
    exported TML, and the risk those checks exist to report — was invisible,
    while a column deliberately tuned to `DONT_INDEX` was reported as indexed.
    `DONT_INDEX` is also the only value this repo ever writes, so every
    converter-produced model turned S2 into a pure false-positive generator.
    """
    idx = mapping(column, "properties").get("index_type", "")
    return (idx or "").upper() != NOT_INDEXED


def is_string_type(data_type: str) -> bool:
    """True for a warehouse string type. Empty (unknown) is not a string."""
    return (data_type or "").upper() in STRING_TYPES
