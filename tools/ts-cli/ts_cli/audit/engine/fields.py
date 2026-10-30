"""Field paths and the derived-field registry.

A rule reads an item through a *field path* (`field:` in an expression, `measure:`,
group `key:`/`value:`/`member:`, pairwise `set:`, composite components, a severity
mapping's `field:`, an `{each}` message placeholder):

    properties.column_type   walk the item's `obj` mapping key by key
    model_tables.fqn         a non-numeric step on a list maps over it -> [fqn, ...]
    properties.synonyms.0    a numeric step on a list indexes it
    parent.name              `parent.` (repeatable) reads the enclosing item instead
    @is_indexed              a derived field: a registered function of (item, ctx)

A missing key, an index out of range or a step into a scalar yields None, never an
error — absence is data, and the operators define what None means. A key the TML schema
defines as a mapping (`tml.MAPPING_KEYS`: `properties`, `spotter_config`,
`db_column_properties`) holding a list or a scalar reads as None too, never mapped over.
Such an item is not judged at all (BL-406 item 10, product owner's ruling 2026-10-30):
the engine skips a column or formula with one (scopes.iterate), a rule reading a Model's
own `properties` that would fire on an absent value excludes the Model with
`@properties_unreadable`, and the report lists every such item as "Could not be read".

Derived fields are small pure functions, written once, for what a path cannot express
(a default the schema implies, a join graph, a lookup into another document). Register
one with `@register("name", uses=...)` — the conditional data it reads; the catalog
validator learns the name from `FIELDS` and the data from `FIELD_USES`.

Kept importable on Python 3.9 with no third-party imports (the catalog gate imports
this module to learn the registered names): import anything heavier inside the
function that needs it.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Optional, Tuple

from ts_cli.audit.engine import tml
from ts_cli.audit.catalog_expr import CONDITIONAL_DATA
from ts_cli.audit.engine.memo import cached
from ts_cli.spotql_ops import AGGREGATE_FUNCS

DerivedField = Callable[[dict, Any], Any]
FIELDS: Dict[str, DerivedField] = {}
FIELD_USES: Dict[str, FrozenSet[str]] = {}   # name -> conditional data it reads
# name -> every value the field can return, for the fields that declare them: what a
# severity `map:` keyed on the field is checked against (a key no value equals never
# maps — a typo, or YAML `"true"` for a boolean field).
FIELD_VALUES: Dict[str, Tuple[Any, ...]] = {}
# name -> how the field reads to an audit reader; generated text (the report, the check
# catalog) writes this, never `@name`.
FIELD_LABELS: Dict[str, str] = {}

_PARENT = "parent."


def register(name: str, *, uses: Any = None, values: Optional[Iterable[Any]] = None,
             label: Optional[str] = None) -> Callable[[DerivedField], DerivedField]:
    """Decorator: make `fn(item, ctx)` available to rules as `@name`.

    `uses` is the conditional data (catalog_expr.CONDITIONAL_DATA) the function reads
    from `ctx`, directly or through another field — `()` for none; Model and Table TML
    and metadata are always fetched and never declared. Required (omitting it raises
    ValueError, so no field is registered undeclared): the catalog gate
    fails a rule naming `@name` whose `requires`/`uses` do not cover it
    (catalog_uses.py), so a rule cannot be starved of data by a category move.

    `values`, optional, is every value the field can return — required of a field a
    severity `map:` is keyed on (the catalog gate fails one that declares none).

    `label` is how the field reads to an audit reader, in place of `@name`: a clause for
    a true/false field ("the join links two fact tables"), else a noun phrase ("the join
    type"). Required, like `uses` — generated text never shows an engine identifier."""
    declared = _declared_uses(f"derived field '@{name}'", uses)
    text = human_label(f"derived field '@{name}'", label)
    vocabulary = None if values is None else tuple(values)

    def deco(fn: DerivedField) -> DerivedField:
        if name in FIELDS:
            raise ValueError(f"derived field '@{name}' is already registered")
        FIELDS[name] = fn
        FIELD_USES[name] = declared
        FIELD_LABELS[name] = text
        if vocabulary is not None:
            FIELD_VALUES[name] = vocabulary
        return fn
    return deco


def human_label(what: str, label: Any) -> str:
    """`label`, checked: a non-blank string with no engine identifier in it (shared with
    code_rules)."""
    if not isinstance(label, str) or not label.strip():
        raise ValueError(f"{what}: label is required — how it reads to an audit reader "
                         "(generated text shows it in place of the engine's name)")
    if re.search(r"@\w|\bcode:\w", label):
        raise ValueError(f"{what}: label must read as words, not engine identifiers: "
                         f"{label!r}")
    return label.strip()


def _declared_uses(what: str, uses: Optional[Iterable[str]]) -> FrozenSet[str]:
    """`uses`, checked: a collection of CONDITIONAL_DATA names (shared with code_rules).
    None — the argument omitted — is an error: `()` declares "reads none"."""
    if uses is None:
        raise ValueError(f"{what}: uses is required — the conditional data it reads "
                         f"({', '.join(CONDITIONAL_DATA)}), or () for none")
    if isinstance(uses, str) or not all(u in CONDITIONAL_DATA for u in uses):
        raise ValueError(f"{what}: uses must be a collection of conditional data "
                         f"({', '.join(CONDITIONAL_DATA)}), got {uses!r}")
    return frozenset(uses)


def get(item: dict | None, path: str, ctx: Any) -> Any:
    """The value at `path` for `item` (see the module docstring); None when absent."""
    while path.startswith(_PARENT):
        item = item.get("parent") if item else None
        path = path[len(_PARENT):]
    if item is None:
        return None
    if path.startswith("@"):
        fn = FIELDS.get(path[1:])
        if fn is None:
            raise KeyError(f"unknown derived field '{path}'")
        return fn(item, ctx)
    return walk(item.get("obj"), path)


def walk(value: Any, path: str) -> Any:
    """Follow a dotted path through mappings and lists (lists map or index).

    A derived `@name` is only ever a whole path (handled by `get`); as a step inside
    one it would silently read None, so it raises.
    """
    for step in path.split(".") if path else []:
        if step.startswith("@"):
            raise KeyError(f"derived field '{step}' must be the whole path, "
                           f"not a step in '{path}'")
        value = _step(value, step)
        if value is None:
            return None
    return value


def _step(value: Any, step: str) -> Any:
    if isinstance(value, dict):
        found = value.get(step)
        # A schema mapping holding a list or scalar is malformed: absent, not mapped over.
        if step in tml.MAPPING_KEYS and not isinstance(found, dict):
            return None
        return found
    if isinstance(value, list):
        if step.lstrip("-").isdigit():
            i = int(step)
            return value[i] if -len(value) <= i < len(value) else None
        return [_step(v, step) for v in value]
    return None


# ── derived fields ──────────────────────────────────────────────────────────

@register("properties_unreadable", uses=(), values=(False, True),
          label="its properties are malformed and cannot be read")
def _properties_unreadable(item: dict, ctx: Any) -> bool:
    """Model (or any item): a mapping key it holds is present but not a mapping
    (tml.unreadable). The engine already skips such a column or formula for every rule;
    a Model is not skipped (its joins, names and tables are still readable), so a rule
    that reads the Model's own `properties` and would fire on an absent value excludes it
    with this field: P4 reads an unset `join_progressive` as off, which is the platform's
    behaviour (live-verified 2026-08-10), but not a guess about an unreadable one."""
    return tml.unreadable(item.get("obj"))


@register("is_indexed", uses=(), values=(False, True),
          label="the column is indexed for search")
def _is_indexed(item: dict, ctx: Any) -> bool:
    """Column: text-search indexed (absent `index_type` means indexed by default)."""
    return tml.is_indexed(item.get("obj") or {})


@register("has_synonyms", uses=(),
          label="the column has synonyms")
def _has_synonyms(item: dict, ctx: Any) -> bool:
    """Column: carries synonyms under `properties:` (exported TML) or at the root."""
    col = item.get("obj") or {}
    return bool(tml.mapping(col, "properties").get("synonyms") or col.get("synonyms"))


@register("join_depth", uses=(),
          label="the join depth")
def _join_depth(item: dict, ctx: Any) -> int:
    """Model: longest join chain across `model_tables` (tml.join_depth)."""
    return tml.join_depth((item.get("obj") or {}).get("model_tables") or [])


@register("is_coached", uses={"ai_instructions"},
          label="the Model has Spotter coaching")
def _is_coached(item: dict, ctx: Any) -> bool:
    """Model: coached — its ai/instructions response carries an instruction, or its TML
    has `model_instructions.data_model_instructions`. A model whose lookup failed (no
    entry in `ctx.ai_instructions`) reads as uncoached here; a rule that must skip it
    instead declares `requires: [ai_instructions]` (A3 does; the report's Spotter readiness
    score, A5 until 2026-10, does not)."""
    from ts_cli.audit.context import nl_instructions  # not gate-safe: import on use
    model = item.get("obj") or {}
    return bool(
        nl_instructions(ctx.ai_instructions.get(item.get("guid")))
        or ((model.get("model_instructions") or {}).get("data_model_instructions")
            or "").strip())


# ── set keys (the group and pairwise modes, D7's code rule) ─────────────────

def as_key(v: Any) -> Any:
    """A grouping / set key comparing as Python does — 1, 1.0 and True are one key, as
    they are in the legacy checks' sets and dicts (D7, D8) — with lists, tuples and
    mappings (where legacy would raise) wrapped so they can be keys at all."""
    if isinstance(v, (list, tuple)):
        return ("seq", tuple(as_key(x) for x in v))
    if isinstance(v, dict):
        return ("map", repr(v))
    try:
        hash(v)
    except TypeError:
        return ("unhashable", repr(v))
    return v


def as_set(value: Any) -> set:
    """The collection at a pairwise `set` path (or a code rule's, D7), as a set of keys. None is an element like any other
    (legacy D7 counts an explicit `fqn: None`); a path mapped over a list reads an
    absent key as None too, so a rule that needs a default supplies it in a derived
    field (D7's @table_set does)."""
    if not isinstance(value, (list, tuple, set)):
        return set()
    return {as_key(v) for v in value}


def _model_of(item: dict) -> dict:
    """The Model body a child item (column, formula, join) belongs to."""
    return ((item.get("parent") or {}).get("obj")) or {}


@register("is_row_level_formula", uses=(),
          label="the formula computes row by row")
def _is_row_level_formula(item: dict, ctx: Any) -> bool:
    """Formula: its `expr` calls no aggregate function (spotql_ops.AGGREGATE_FUNCS or a
    `sql_*_aggregate_op`, outside any `[...]` reference or quoted literal) and references no formula that is
    aggregate, directly or through a chain (_reference_graph). How a surfacing column's
    `aggregation` key reads plays no part: the model schema says it is a no-op on an
    aggregate expr and applies on a row-level one, so it never told the two apart."""
    obj = item.get("obj") or {}
    if not obj.get("name"):
        return not _calls_aggregate(obj)
    model = _model_of(item)
    aggregate = cached("aggregate_formula_names", model, _aggregate_formula_names, model)
    return obj["name"] not in aggregate


#: SQL pass-through aggregation: its SQL sits in a quoted literal, which _NOT_CODE strips.
_SQL_AGGREGATE_OP = re.compile(r"\bsql_[a-z_]+_aggregate_op\s*\(", re.IGNORECASE)


def _calls_aggregate(formula: dict) -> bool:
    code = _NOT_CODE.sub(" ", str(formula.get("expr") or ""))
    return bool(AGGREGATE_FUNCS.search(code) or _SQL_AGGREGATE_OP.search(code))


def _aggregate_formula_names(model: dict) -> set:
    formulas = [f for f in (model.get("formulas") or []) if isinstance(f, dict)]
    direct = {f.get("name") for f in formulas if f.get("name") and _calls_aggregate(f)}
    graph, _ = _reference_graph(formulas)
    found = set(direct)
    changed = True
    while changed:
        changed = False
        for name, refs in graph.items():
            if name not in found and any(r in found for r in refs):
                found.add(name)
                changed = True
    return found


@register("formula_expr", uses=(),
          label="the expression of the formula the column surfaces")
def _formula_expr(item: dict, ctx: Any) -> Any:
    """Model column: the `expr` of the formula it surfaces (its `formula_id`), or None
    for a column on a table, or a `formula_id` matching no formula."""
    fid = (item.get("obj") or {}).get("formula_id")
    if not fid:
        return None
    model = _model_of(item)
    return cached("formula_exprs", model, _formula_exprs, model).get(fid)


def _formula_exprs(model: dict) -> dict:
    return {f.get("id"): f.get("expr") for f in (model.get("formulas") or [])
            if isinstance(f, dict) and f.get("id")}


#: The distinct-count functions a formula can call (thoughtspot-formula-patterns.md).
_DISTINCT_FORMULA = re.compile(
    r"\bunique\s+count\b|\bunique_count_if\b|\bgroup_unique_count\b", re.IGNORECASE)
#: What a function name inside does not count: a `[...]` reference, a quoted literal.
_NOT_CODE = re.compile(r"\[[^\]]*\]|'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")
DISTINCT_COUNT_KINDS = ("COUNT_DISTINCT aggregation", "distinct-count formula")


@register("distinct_count_kind", uses=(), values=(None,) + DISTINCT_COUNT_KINDS,
          label="how the column counts distinct values")
def _distinct_count_kind(item: dict, ctx: Any) -> Optional[str]:
    """Model column: "COUNT_DISTINCT aggregation" when it is aggregated so (the form
    invariant I5 forbids on a physical column), else "distinct-count formula" when it
    surfaces a formula calling `unique count`, `unique_count_if` or
    `group_unique_count` — outside any `[...]` reference or quoted literal — else None."""
    props = (item.get("obj") or {}).get("properties")
    if isinstance(props, dict) and props.get("aggregation") == "COUNT_DISTINCT":
        return DISTINCT_COUNT_KINDS[0]
    expr = _formula_expr(item, ctx)
    if isinstance(expr, str) and _DISTINCT_FORMULA.search(_NOT_CODE.sub(" ", expr)):
        return DISTINCT_COUNT_KINDS[1]
    return None


@register("has_date_constraint", uses=(),
          label="the Model has a date constraint")
def _has_date_constraint(item: dict, ctx: Any) -> bool:
    """Model: a `date_range_condition` anywhere in its `constraints` (a mapping in
    exported TML, a list in hand-built fixtures — searched as text, BL-303)."""
    return "date_range_condition" in str((item.get("obj") or {}).get("constraints") or {})


def _fact_table_names(item: dict) -> set:
    model = item.get("obj") or {}
    return cached("fact_table_names", model, tml.fact_tables,
                  model.get("columns") or [], model.get("model_tables") or [])


@register("fact_tables", uses=(),
          label="the fact tables")
def _fact_tables(item: dict, ctx: Any) -> List[str]:
    """Model: the distinct `model_tables[].name`s that read as fact tables
    (tml.fact_tables — keyed by name, not alias), sorted; a name list in messages."""
    from ts_cli.audit.engine.messages import NameList  # messages imports this module
    return NameList(sorted(_fact_table_names(item)))


@register("fact_table_count", uses=(),
          label="the number of fact tables")
def _fact_table_count(item: dict, ctx: Any) -> int:
    """Model: how many distinct table names read as fact tables (see @fact_tables)."""
    return len(_fact_table_names(item))


@register("varchar_join_keys", uses=(),
          label="the string-typed join keys")
def _varchar_join_keys(item: dict, ctx: Any) -> List[str]:
    """Join: the column ids in its `on` clause whose warehouse type, read off the Table
    TMLs (AuditContext.column_types), is a string type. A key whose table is not in
    the context has no type and is not listed — unknown is not "a string"."""
    from ts_cli.audit.context import join_key_ids  # not gate-safe: import on use
    from ts_cli.audit.engine.messages import NameList
    col_types = cached("column_types", item["doc"], ctx.column_types, item["doc"])
    return NameList(k for k in join_key_ids((item.get("obj") or {}).get("on"))
                    if col_types.get(k, "").upper() in tml.STRING_TYPES)


@register("is_string_type", uses=(),
          label="the column is string-typed")
def _is_string_type(item: dict, ctx: Any) -> bool:
    """RLS column reference: its warehouse `data_type` is a string type
    (tml.is_string_type — `.upper()` against VARCHAR/CHAR/STRING/TEXT, exactly; an
    unknown "" type is not a string)."""
    return tml.is_string_type((item.get("obj") or {}).get("data_type"))


@register("varchar_join_key_count", uses=(),
          label="the number of string-typed join keys")
def _varchar_join_key_count(item: dict, ctx: Any) -> int:
    """Join: how many of its keys are string-typed (see @varchar_join_keys)."""
    return len(_varchar_join_keys(item, ctx))


_IF_CALL = re.compile(r"\bif\s*\(", re.IGNORECASE)


@register("if_call_count", uses=(),
          label="the number of IF calls")
def _if_call_count(item: dict, ctx: Any) -> int:
    """Formula: how many `if (` calls its `expr` makes."""
    return len(_IF_CALL.findall(str((item.get("obj") or {}).get("expr") or "")))


def _reference_graph(formulas: list) -> Tuple[Dict[Any, list], Dict[Any, int]]:
    """A Model's formula reference graph, keyed by formula NAME.

    A cross-reference is written as the formula's id (`[formula_<name>]`), or — in a
    hand-built model — its display name; both resolve back to the name (BL-300). A
    formula's edges are the other formulas its `expr` references. Formulas sharing a
    name share a node, holding the references of the LAST of them that has any;
    `owner` maps each node to the position of the FIRST of them that has any, so a rule
    reports a node once — even when one formula mapping is listed twice — and in the
    order legacy P17 did (it walked its name-keyed dict, where a name keeps the place
    of its first insertion).
    """
    by_ref: Dict[Any, Any] = {}
    for f in formulas:
        fname = f.get("name", "")
        if not fname:
            continue
        by_ref[fname] = fname
        fid = f.get("id", "")
        if fid:
            by_ref[fid] = fname
    graph: Dict[Any, list] = {}
    owner: Dict[Any, int] = {}
    for i, f in enumerate(formulas):
        fname = f.get("name", "")
        refs = tml.BRACKET_REF.findall(str(f.get("expr") or ""))
        cross = [by_ref[r] for r in refs if r in by_ref and by_ref[r] != fname]
        if cross:
            graph[fname] = cross
            owner.setdefault(fname, i)
    return graph, owner


def _bfs_depth(graph: Dict[Any, list], start: Any) -> int:
    """Hops to the farthest node reachable from `start` (breadth first)."""
    visited: set = set()
    queue = [(start, 0)]
    max_d = 0
    while queue:
        node, d = queue.pop(0)
        if node in visited:
            continue
        visited.add(node)
        max_d = max(max_d, d)
        for nb in graph.get(node, []):
            queue.append((nb, d + 1))
    return max_d


@register("reference_chain_depth", uses=(),
          label="the depth of the formula's reference chain")
def _reference_chain_depth(item: dict, ctx: Any):
    """Formula: the longest chain of formula references starting at its node of the
    Model's reference graph (see _reference_graph). None — no value, so no finding —
    for a formula that references no other formula, or whose name another formula's
    references represent."""
    model = _model_of(item)
    graph, owner = cached("reference_graph", model, _reference_graph,
                          model.get("formulas") or [])
    name = (item.get("obj") or {}).get("name", "")
    if name not in owner or owner[name] != item.get("index"):
        return None
    return _bfs_depth(graph, name)


# ── S: PII, credentials, masking and owning-table RLS ───────────────────────
# The name heuristics, copied verbatim from the legacy checks_security.py; since the rule catalog
# replaced that module this is their single source (the smoke test's own list is BL-112).
# The legacy answers pinned in tests/audit_rule_fixtures/legacy_findings.json.gz hold
# the rules that read them to the legacy findings.

#: (pattern, category, confidence) — a column's FIRST matching pattern names it.
#: A separator between the words of a multi-word term: none, `-`, `_` or a space, so the
#: snake_case warehouse name and the display name a Model column usually has both match
#: ("first_name", "First Name", "FirstName"). Before 2026-10 a space did not.
_SEP = r"[-_ ]?"
#: Where a word starts: not after a letter, or at a camelCase hump ("customerEmail").
_START = r"(?:(?<![A-Za-z])|(?<=[a-z])(?=[A-Z]))"
#: Where a word ends: not before a letter, at a camelCase hump ("telNumber"), or where an
#: acronym meets a capitalised word ("SSNLast4", "IBANNumber").
_END = r"(?:(?![A-Za-z])|(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z]))"


def _word(token: str) -> str:
    """`token` (any case) as a whole word — for the short tokens that otherwise match
    inside ordinary words: "tel" in "hotel", "sin" in "cousin", "dob" in "adobe". Known
    misses: a token run into another word with no separator or case change ("TELNO",
    "EMPSSN"), which no pattern can tell from "HOTEL"."""
    return f"{_START}(?i:{token}){_END}"


def _starts_word(term: str) -> str:
    """`term` (any case) starting a word, for a term whose first letters also end other
    words: "e-mail" in "Voice Mail", "card number" in "Scorecard Numerator"."""
    return f"{_START}(?i:{term})"


#: The column-name patterns S1 reads as personal data (first match names the category).
#: Compiled case-sensitively: `(?i:...)` makes every term any case, while the word
#: boundaries need the case of the letters around them.
PII_PATTERNS = [
    (re.compile(_starts_word(r"e[-_]?mail")), "email", "HIGH"),
    (re.compile(rf"(?i:phone|cell{_SEP}phone|telephone|telef[oó]n|(?<!auto)mobile)"
                rf"|{_word('fax')}|{_word('tel')}"),
     "phone", "HIGH"),
    (re.compile(rf"{_word('ssn')}|(?i:social{_SEP}sec|national{_SEP}id|tax{_SEP}id)"
                rf"|{_word('nin')}|{_word('sin')}"),
     "national_id", "HIGH"),
    (re.compile(rf"{_word('dob')}|(?i:birth{_SEP}date|date{_SEP}of{_SEP}birth|birthday)"),
     "dob", "HIGH"),
    (re.compile(rf"(?i:credit{_SEP}card|account{_SEP}num|routing{_SEP}num)"
                rf"|{_starts_word(f'card{_SEP}num')}|{_word('iban')}"),
     "financial", "HIGH"),
    (re.compile(rf"(?i:first{_SEP}name|last{_SEP}name|surname|full{_SEP}name|given{_SEP}name)"),
     "person_name", "MEDIUM"),
    (re.compile(rf"(?i:street{_SEP}addr|postal{_SEP}code|zip{_SEP}code)"), "address", "MEDIUM"),
]

CREDENTIAL_PATTERN = re.compile(
    r"\bpassword\b|\bpasswd\b|\bsecret[-_ ]?key\b|\bapi[-_ ]?key\b|\btoken\b",
    re.IGNORECASE,
)
#: Every term CREDENTIAL_PATTERN can match, lower-cased — @credential_term's values. The
#: spaced forms (a display name, "API Key") were added 2026-10.
CREDENTIAL_TERMS = ("password", "passwd", "secretkey", "secret-key", "secret_key",
                    "secret key", "apikey", "api-key", "api_key", "api key", "token")


def _column_name(item: dict) -> Any:
    """A column's name as the S checks read it: `.get("name", "")`."""
    return (item.get("obj") or {}).get("name", "")


def _pii_match(item: dict):
    """`(category, confidence)` of the column name's first matching PII pattern, or
    None. A non-string name matches nothing (the legacy regex would raise on it)."""
    name = _column_name(item)
    if not isinstance(name, str):
        return None
    for pattern, category, confidence in PII_PATTERNS:
        if pattern.search(name):
            return category, confidence
    return None


@register("pii_category", uses=(),
          label="the kind of personal data the name suggests")
def _pii_category(item: dict, ctx: Any):
    """Column: the PII category its name reads as (email, phone, national_id, dob,
    financial, person_name, address — the first pattern that matches), or None."""
    match = _pii_match(item)
    return match[0] if match else None


@register("pii_confidence", uses=(),
          label="how confidently the name suggests personal data")
def _pii_confidence(item: dict, ctx: Any):
    """Column: the confidence (HIGH / MEDIUM) of that PII pattern, or None."""
    match = _pii_match(item)
    return match[1] if match else None


@register("credential_term", uses=(), values=(None,) + CREDENTIAL_TERMS,
          label="the credential word in the column name")
def _credential_term(item: dict, ctx: Any):
    """Column: the credential word its name contains (password, passwd, secret key, api
    key — joined, hyphenated, underscored or spaced — or token; whole words, any case),
    lower-cased as matched; None when none."""
    name = _column_name(item)
    match = CREDENTIAL_PATTERN.search(name) if isinstance(name, str) else None
    return match.group().lower() if match else None


@register("owning_table_has_rls", uses=(), values=(False, True),
          label="the column's table has row-level security")
def _owning_table_has_rls(item: dict, ctx: Any) -> bool:
    """Model column: the Table its `column_id` prefix names (through the model's
    `model_tables`, alias first) has RLS rules on its Table TML. False when that
    Table TML is not in the context.

    legacy S2's lookup, step for step: the model's tables keyed by the prefix
    their columns' `column_id` carries (alias, else name — BL-305), each True when its
    Table TML (in the context) declares RLS rules; a later model table with the same
    key overrides an earlier one, and one whose Table TML is absent writes nothing.
    The column's key is its `column_id` prefix ("" without `::`)."""
    model = _model_of(item)
    has_rls = cached("rls_by_table_key", model, _rls_by_table_key, model, ctx)
    cid = (item.get("obj") or {}).get("column_id", "")
    table_name = cid.split("::")[0] if "::" in cid else ""
    return has_rls.get(table_name, False)


def _rls_by_table_key(model: dict, ctx: Any) -> Dict[Any, bool]:
    has_rls = {}
    for mt in model.get("model_tables") or []:
        table = ctx.tables.get(mt.get("fqn", ""))
        if not table:
            continue
        rls = table.get("table", {}).get("rls_rules") or {}
        has_rls[tml.table_key(mt)] = bool(rls.get("rules"))
    return has_rls


@register("named_in_masking_formula", uses=(),
          label="a masking formula names the column")
def _named_in_masking_formula(item: dict, ctx: Any) -> bool:
    """Model column: legacy S3's masking heuristic — some formula of the model calls
    `is_group_member` AND the column's name appears (case-insensitively) anywhere in
    the model's formula expressions joined by spaces. Not a per-formula test: a mask
    on one column and a raw projection of another silence both (a known defect,
    kept). A non-string name names nothing (False), as for @pii_category — S3 asks
    only about PII columns, whose names are strings."""
    name = _column_name(item)
    if not isinstance(name, str):
        return False
    model = _model_of(item)
    lowered = cached("lowered_formula_text", model, _lowered_formula_text, model)
    return "is_group_member" in lowered and name.lower() in lowered


def _lowered_formula_text(model: dict) -> str:
    return " ".join(str(f.get("expr") or "") for f in (model.get("formulas") or [])).lower()


# The D (Data Modeling) and H (Human Readiness) fields live in their own modules;
# importing them here registers them wherever FIELDS is read (the engine, and the
# catalog gate's known names).
from ts_cli.audit.engine import fields_data  # noqa: E402,F401
from ts_cli.audit.engine import fields_human  # noqa: E402,F401
