"""Derived fields for the D (Data Modeling) rules.

Registered into the same registry as engine/fields.py (which imports this module at its
end, so `fields.FIELDS` — and the catalog gate's list of known names — always includes
them). Each reproduces what a legacy check in checks_data.py (deleted when the rule catalog replaced them) read,
step for step, including the readings that are known to be wrong (the legacy answers
pinned in tests/audit_rule_fixtures/legacy_findings.json.gz hold them to it; fixing
them is the follow-up work the spec lists):

- D10 and D11 looked a model table up by its `name`, where its columns' `column_id`s
  carry the `alias` when it has one (BL-305). Since 2026-10 (roadmap PR 2.3) they key a
  table by alias, else name (tml.table_key), and resolve a join's `with` to the table
  it names (tml.join_target), as the join graph does.

Same import constraint as fields.py: Python 3.9, no third-party imports at module level.
"""
from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple

from ts_cli.audit.engine import tml
from ts_cli.audit.engine.fields import _model_of, model_roles, register
from ts_cli.audit.engine.memo import cached
from ts_cli.formula_translate.refs import split_literals
from ts_cli.tml_join_graph import on_clause_key_pairs


def _upper(value: Any) -> Optional[str]:
    """`(value or "").upper()` as the legacy checks read a join's type and cardinality;
    None for a non-string (where the legacy `.upper()` would raise)."""
    value = value or ""
    return value.upper() if isinstance(value, str) else None


# ── joins (D3, D11) ─────────────────────────────────────────────────────────

@register("join_type", uses=(),
          values=("", "INNER", "LEFT_OUTER", "RIGHT_OUTER", "OUTER", None),
          label="the join type")
def _join_type(item: dict, ctx: Any) -> Optional[str]:
    """Join: its type upper-cased ("" when unset) — INNER, LEFT_OUTER, RIGHT_OUTER or
    OUTER (ThoughtSpot's full outer join). A referencing join's type comes from the
    Table's `joins_with` unless the model overrides it (tml.model_joins)."""
    return _upper((item.get("obj") or {}).get("type"))


@register("join_cardinality", uses=(),
          label="the join cardinality")
def _join_cardinality(item: dict, ctx: Any) -> Optional[str]:
    """Join: its cardinality upper-cased ("" when unset): the model's own, else a
    referencing join's Table `joins_with` entry, which exported Table TML rarely
    carries (tml.model_joins)."""
    return _upper((item.get("obj") or {}).get("cardinality"))


def _join_from_table(item: dict) -> dict:
    return (item.get("obj") or {}).get("model_table") or {}


@register("join_from_name", uses=(),
          label="the table the join starts from")
def _join_from_name(item: dict, ctx: Any) -> Any:
    """Join: the key (alias, else name) of the model table it is declared on ("" when
    absent). The physical `name` until 2026-10 (BL-305)."""
    return tml.table_key(_join_from_table(item))


@register("is_fact_to_fact_join", uses=(), values=(False, True),
          label="the join links two tables that both hold measures")
def _is_fact_to_fact_join(item: dict, ctx: Any) -> bool:
    """Join: both ends hold measures — each end's role (model_roles) is `fact` or
    `dimension_with_measures` — each end by its key (alias, else name): the declaring
    table's, and the table the join's `with` names (tml.join_target_key). Under roles
    from join direction a root is never joined to, so "two facts" would never hold; two
    tables of measures joined, one side's repeating, is what the field always meant.
    Until 2026-11 an end was a fact when it had more than 3 MEASURE columns."""
    model = _model_of(item)
    roles = model_roles(model, ctx)
    to_table = tml.join_target_key(model.get("model_tables") or [],
                                   (item.get("obj") or {}).get("with", ""))
    held = ("fact", "dimension_with_measures")
    return all((roles.get(k) or {}).get("role") in held
               for k in (_join_from_name(item, ctx), to_table))


# ── model tables (D5, D6, D10) ──────────────────────────────────────────────

def _joined_keys(model: dict) -> set:
    """Every table on either side of a join, by key (tml.joined_keys; D5, D10, and H3
    through fields_human). Once per Model per run (engine/memo.py)."""
    return cached("joined_keys", model, tml.joined_keys, model.get("model_tables") or [])


@register("is_joined", uses=(),
          label="the table takes part in a join")
def _is_joined(item: dict, ctx: Any) -> bool:
    """Model table: its key (alias, else name) is on either side of some join."""
    return item.get("name") in _joined_keys(_model_of(item))


@register("zero_column_role", uses=(), values=(None, "bridge", "leaf"),
          label="the table's place in the joins")
def _zero_column_role(item: dict, ctx: Any) -> Optional[str]:
    """Model table (D10): None when its key (alias, else name) prefixes some model
    column's `column_id`; otherwise "bridge" when it is on either side of a join,
    "leaf" when not. Keyed by `name` until 2026-10, so an aliased table always read
    zero-column (BL-305)."""
    model = _model_of(item)
    with_columns = set()
    for c in model.get("columns") or []:
        cid = c.get("column_id", "")
        if isinstance(cid, str) and "::" in cid:
            with_columns.add(cid.split("::")[0])
    key = tml.table_key(item.get("obj") or {})
    if key in with_columns:
        return None
    return "bridge" if key in _joined_keys(model) else "leaf"


def _table_columns(item: dict) -> Tuple[list, list]:
    """(the model's columns, those whose `column_id` prefix is this table's key)."""
    cols = _model_of(item).get("columns") or []
    key = item.get("name")
    return cols, [c for c in cols if (c.get("column_id") or "").split("::")[0] == key]


def _attribute_count(table_cols: List[dict]) -> int:
    return sum(1 for c in table_cols
               if tml.mapping(c, "properties").get("column_type") == "ATTRIBUTE")


@register("table_role", uses=(),
          label="the table's role (fact, factless, dimension or dimension with measures)")
def _table_role(item: dict, ctx: Any) -> str:
    """Model table: its role from join direction (model_roles), by its key — alias,
    else name: fact, factless, dimension or dimension_with_measures ("" for a table
    the classifier skipped as malformed)."""
    return (model_roles(_model_of(item), ctx).get(item.get("name")) or {}).get("role", "")


@register("table_column_count", uses=(),
          label="the number of the table's columns")
def _table_column_count(item: dict, ctx: Any) -> int:
    """Model table: how many model columns its key prefixes."""
    return len(_table_columns(item)[1])


@register("attribute_count", uses=(),
          label="the number of ATTRIBUTE columns")
def _attribute_count_field(item: dict, ctx: Any) -> int:
    """Model table: how many of its model columns are ATTRIBUTEs."""
    return _attribute_count(_table_columns(item)[1])


@register("attribute_share", uses=(),
          label="the share of ATTRIBUTE columns")
def _attribute_share(item: dict, ctx: Any) -> Optional[float]:
    """Model table: the fraction of its model columns that are ATTRIBUTEs (None
    without columns) — what legacy D6 compares (`> 0.4`). Its metric, the rounded
    percentage (@attribute_pct), is not: 40.04% rounds to 40.0 yet is over the line."""
    _, table_cols = _table_columns(item)
    return _attribute_count(table_cols) / len(table_cols) if table_cols else None


@register("attribute_pct", uses=(),
          label="the percentage of ATTRIBUTE columns")
def _attribute_pct(item: dict, ctx: Any) -> Optional[float]:
    """Model table: that share as a percentage, rounded to 1 place (D6's metric)."""
    _, table_cols = _table_columns(item)
    if not table_cols:
        return None
    return round(_attribute_count(table_cols) / len(table_cols) * 100, 1)


# ── models (D7) and metadata (D8) ───────────────────────────────────────────

@register("table_set", uses=(),
          label="the Model's tables")
def _table_set(item: dict, ctx: Any) -> list:
    """Model: each model table's identity as legacy D7 reads it — its `fqn`, or its
    `name` ("" when absent) when it has no `fqn` key at all (an explicit `fqn: None`
    stays None)."""
    return [t.get("fqn", t.get("name", ""))
            for t in (item.get("obj") or {}).get("model_tables") or []]


@register("fact_table_set", uses=(),
          label="the Model's fact tables")
def _fact_table_set(item: dict, ctx: Any) -> list:
    """Model: the identity (as @table_set reads it: `fqn`, else `name`) of each model
    table whose role (model_roles, by key: alias else name) is `fact`."""
    model = item.get("obj") or {}
    roles = model_roles(model, ctx)
    return [t.get("fqn", t.get("name", "")) for t in model.get("model_tables") or []
            if (roles.get(tml.table_key(t)) or {}).get("role") == "fact"]


@register("physical_table_key", uses=(),
          label="the physical table (connection, database, schema, name)")
def _physical_table_key(item: dict, ctx: Any) -> Any:
    """Metadata header: (connection, database, schema, table name) — each "" when
    absent — the physical table legacy D8 groups Table objects by. Renders
    dot-joined in a message."""
    from ts_cli.audit.engine.messages import Key  # messages imports fields
    header = item.get("obj") or {}
    return Key((header.get("dataSourceName", ""), header.get("databaseStripe", ""),
                header.get("schemaStripe", ""), header.get("name", "")))


# ── S12: an RLS table on the optional side of an outer join ─────────────────

#: An RLS rule keeping a table's unmatched (null) rows: a null test on a column — the RLS
#: docs' `is_null ( … )` (security-rls, "Respect join definitions"), the formula
#: language's `isnull ( … )` (thoughtspot-formula-patterns.md), or `= null`.
_ISNULL_CALL = re.compile(r"(?i)\bis_?null\s*\(|=\s*null\b")


def _optional_tables(join: dict, model_tables: list) -> List[dict]:
    """The model tables an outer join may find no row in — the side that can be null:
    the table its `with` names (tml.join_target, as the join graph resolves it) for
    LEFT_OUTER, the declaring table for RIGHT_OUTER, both for OUTER (ThoughtSpot's full
    outer join); none otherwise, and none it cannot resolve."""
    kind = _upper(join.get("type"))
    declaring = join.get("model_table")
    target = tml.join_target(model_tables, join.get("with"))
    sides = {"LEFT_OUTER": [target], "RIGHT_OUTER": [declaring],
             "OUTER": [declaring, target]}.get(kind, [])
    return [t for t in sides if isinstance(t, dict)]


def _key(model_table: dict) -> str:
    """A model table's key (alias, else name) when it is a string, else ""."""
    for k in ("alias", "name"):
        if isinstance(model_table.get(k), str) and model_table[k]:
            return model_table[k]
    return ""


def _unguarded_rls(table_doc: Any) -> bool:
    """A Table TML with RLS rules, none of which has a null branch (_ISNULL_CALL)."""
    t = table_doc.get("table") if isinstance(table_doc, dict) else None
    rls = t.get("rls_rules") if isinstance(t, dict) else None
    rules = rls.get("rules") if isinstance(rls, dict) else None
    rules = [r for r in rules if isinstance(r, dict)] if isinstance(rules, list) else []
    return bool(rules) and not any(_ISNULL_CALL.search(str(r.get("expr") or ""))
                                   for r in rules)


@register("outer_join_unguarded_rls", uses=(),
          label="the outer join's optional-side tables with RLS and no null branch")
def _outer_join_unguarded_rls(item: dict, ctx: Any) -> list:
    """Join: the keys, sorted, of the tables on its optional side (_optional_tables) whose
    Table TML carries RLS rules none of which has a null branch (`is_null` / `isnull`).
    Without one the outer join can act as an inner one for users under the rule
    (security-rls, "Respect join definitions"). A table with no Table TML in scope is
    unknown and not listed; a name list in messages."""
    from ts_cli.audit.engine.messages import NameList  # messages imports fields
    model_tables = _model_of(item).get("model_tables")
    sides = _optional_tables(item.get("obj") or {},
                             model_tables if isinstance(model_tables, list) else [])
    return NameList(sorted({_key(t) for t in sides
                            if isinstance(t.get("fqn"), str)
                            and _unguarded_rls(ctx.tables.get(t["fqn"]))} - {""}))


# ── S14 / S15 (BL-512): RLS judgement checks ───────────────────────────────

#: A session variable an RLS rule scopes users by: ts_groups (any variant), ts_username,
#: ts_org (any variant), ts_email_domain, or a custom `ts_var ( name )`.
_SESSION_VARIABLE = re.compile(
    r"(?i)\b(ts_groups\w*|ts_username|ts_org|ts_email_domain"
    r"|ts_var\s*\(\s*(\w+)\s*\))(?!\w)")
_BRACKETED = re.compile(r"\[[^\]]*\]")
#: A null test on one bracketed column: `is_null ( [X] )`, `isnull ( [X] )`, `[X] = null`.
_NULL_TEST = re.compile(r"(?i)\bis_?null\s*\(\s*\[([^\]]+)\]\s*\)|\[([^\]]+)\]\s*=\s*null\b")


def _code(expr: Any) -> str:
    """`expr` with its quoted literals removed (formula_translate.refs.split_literals)."""
    if not isinstance(expr, str):
        return ""
    return " ".join(seg for lit, seg in split_literals(expr) if not lit)


def _variable(match: Any) -> str:
    whole = match.group(1).lower()
    if match.group(2):
        return f"ts_var({match.group(2).lower()})"
    return "ts_groups" if whole.startswith("ts_groups") else whole


def _rule_variables(expr: Any) -> set:
    """The session-variable families an RLS rule names, outside quoted literals and
    outside `[...]` references (a column called TS_ORG_ID is not ts_org)."""
    code = _BRACKETED.sub(" ", _code(expr))
    return {_variable(m) for m in _SESSION_VARIABLE.finditer(code)}


def _rls_rules_of(table_doc: Any) -> list:
    t = table_doc.get("table") if isinstance(table_doc, dict) else None
    rls = t.get("rls_rules") if isinstance(t, dict) else None
    rules = rls.get("rules") if isinstance(rls, dict) else None
    return [r for r in rules if isinstance(r, dict)] if isinstance(rules, list) else []


@register("rls_session_variables", uses=(),
          label="the session variables the Model's RLS rules scope users by")
def _rls_session_variables(item: dict, ctx: Any) -> list:
    """Model: when two or more of its Tables (Table TML by `model_tables[].fqn`, each
    once) scope users through RLS and do so by DIFFERENT sets of session variables, all
    of those variables, sorted; else none. One family per variable (`_rule_variables`):
    every ts_groups variant is `ts_groups`, a custom variable `ts_var(name)`. Two
    variables on one Table — an owner-or-group override — is not a difference between
    Tables (S14, BL-512; review of PR 5); a name list in messages."""
    from ts_cli.audit.engine.messages import NameList  # messages imports fields
    model = item.get("obj") or {}
    mts = model.get("model_tables")
    per_table = {}
    for mt in mts if isinstance(mts, list) else []:
        fqn = mt.get("fqn") if isinstance(mt, dict) else None
        if not isinstance(fqn, str) or fqn in per_table:
            continue
        found = set()
        for rule in _rls_rules_of(ctx.tables.get(fqn)):
            found |= _rule_variables(rule.get("expr"))
        if found:
            per_table[fqn] = frozenset(found)
    if len(per_table) < 2 or len(set(per_table.values())) < 2:
        return NameList()
    return NameList(sorted(set().union(*per_table.values())))


_CLAUSE_SPLIT = re.compile(r"(?i)\b(?:and|or)\b")


def _rule_key_columns(expr: Any) -> List[str]:
    """The columns an RLS rule scopes users through: the `[path::COLUMN]` references in
    those of its `and` / `or` clauses that name a session variable, outside quoted
    literals and null tests; the part after `::`, stripped. A column the rule compares
    with a literal (a status flag) or guards with `!= null` sits in a clause naming no
    variable and is not read (review of the S16 PR). References are masked while the
    rule is split, so an `and` inside a column name does not split it."""
    refs: List[str] = []

    def mask(m: Any) -> str:
        refs.append(m.group(0))
        return f" \x00{len(refs) - 1}\x00 "

    masked = _BRACKETED.sub(mask, _NULL_TEST.sub(" ", _code(expr)))
    out = []
    for clause in _CLAUSE_SPLIT.split(masked):
        if _rule_variables(clause):
            out += [refs[int(i)][1:-1].rpartition("::")[2].strip()
                    for i in re.findall(r"\x00(\d+)\x00", clause)]
    return out


@register("rls_key_columns", uses=(),
          label="the columns the Model's RLS rules scope users through")
def _rls_key_columns(item: dict, ctx: Any) -> list:
    """Model: when two or more of its Tables (Table TML by `model_tables[].fqn`, each
    once) scope users through RLS and do so through DIFFERENTLY NAMED sets of columns
    (`_rule_key_columns`; names compared without case), all of those columns, sorted,
    each name once; else none. Any difference counts, as the product owner specified
    for G5e's keys half (S16, BL-521, 2026-11-05); a name list in messages."""
    from ts_cli.audit.engine.messages import NameList  # messages imports fields
    mts = (item.get("obj") or {}).get("model_tables")
    per_table, names = {}, {}
    for mt in mts if isinstance(mts, list) else []:
        fqn = mt.get("fqn") if isinstance(mt, dict) else None
        if not isinstance(fqn, str) or fqn in per_table:
            continue
        found = set()
        for rule in _rls_rules_of(ctx.tables.get(fqn)):
            for col in _rule_key_columns(rule.get("expr")):
                if col:
                    found.add(col.casefold())
                    names.setdefault(col.casefold(), col)
        if found:
            per_table[fqn] = frozenset(found)
    if len(per_table) < 2 or len(set(per_table.values())) < 2:
        return NameList()
    return NameList(sorted((names[k] for k in set().union(*per_table.values())),
                           key=str.casefold))


def _own_table_and_paths(doc: Any) -> Tuple[Any, dict]:
    """A Table TML's name and its RLS `table_paths` as {id: Table name}."""
    t = doc.get("table") if isinstance(doc, dict) else None
    rls = t.get("rls_rules") if isinstance(t, dict) else None
    paths = rls.get("table_paths") if isinstance(rls, dict) else None
    by_id = {p["id"]: p.get("table") for p in paths
             if isinstance(p, dict) and isinstance(p.get("id"), str)} \
        if isinstance(paths, list) else {}
    return (t.get("name") if isinstance(t, dict) else None), by_id


@register("own_column_null_tests", uses=(),
          label="the rule's null tests on its own Table's columns")
def _own_column_null_tests(item: dict, ctx: Any) -> list:
    """RLS rule: the columns, in order, of its own Table that it tests for null
    (`is_null` / `isnull ( [X] )`, `[X] = null`; outside quoted literals) AND scopes
    users by — the same column also appears outside the null test in a rule that names
    a session variable (G5f's shape: the owner key). A reference's prefix is a
    `table_paths` id resolved to its Table, else a Table name. Such a test keeps the
    Table's ownerless rows for every user under the rule; a null test on a key that is
    never null (the join key) keeps an outer join's unmatched rows without that, and is
    not listed (S15, BL-512; review of PR 5); a name list in messages."""
    from ts_cli.audit.engine.messages import NameList  # messages imports fields
    own, by_id = _own_table_and_paths(item.get("doc"))
    code = _code((item.get("obj") or {}).get("expr"))
    out = NameList()
    if not _rule_variables(code):
        return out
    scoped = _BRACKETED.findall(_NULL_TEST.sub(" ", code))
    for m in _NULL_TEST.finditer(code):
        prefix, sep, column = (m.group(1) or m.group(2)).strip().partition("::")
        prefix, column = prefix.strip(), column.strip()
        if sep and isinstance(own, str) and by_id.get(prefix, prefix) == own \
                and column not in out and _scopes(scoped, by_id, own, column):
            out.append(column)
    return out


def _scopes(refs: list, by_id: dict, own: str, column: str) -> bool:
    """One of `refs` (bracketed, outside the null tests) is `own`'s `column`."""
    for ref in refs:
        prefix, sep, col = ref[1:-1].strip().partition("::")
        if sep and col.strip() == column and by_id.get(prefix.strip(), prefix.strip()) == own:
            return True
    return False


# ── S17: an RLS Table planned as a second root ──────────────────────────────

#: The roles of a root of the Model's directed joins (agents/shared/erd/roles.py):
#: nothing joins to it, with or without measures.
_ROOT_ROLES = ("fact", "factless")


def _join_roots(model: dict, ctx: Any) -> frozenset:
    """Keys (alias, else name) of the roots of the Model's directed joins: role fact or
    factless (model_roles: direction from cardinality, ONE_TO_MANY reversed) and in at
    least one directed join — an unjoined table is D5's, not a root."""
    return frozenset(k for k, r in model_roles(model, ctx).items()
                     if r.get("role") in _ROOT_ROLES and not r.get("unjoined"))


def _dicts(value: Any) -> list:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _measure_formulas(body: dict) -> list:
    """The formulas the Model surfaces as MEASURE columns."""
    by_id = {f.get("id"): f for f in _dicts(body.get("formulas"))
             if isinstance(f.get("id"), str)}
    return [by_id[c["formula_id"]] for c in _dicts(body.get("columns"))
            if c.get("formula_id") in by_id
            and (c.get("properties") or {}).get("column_type") == "MEASURE"]


def _formula_measure_tables(model: dict) -> frozenset:
    """Table keys (the part before `::`) that a formula surfaced as a MEASURE column
    reads, following formula cross-references (formula_ref_index): such a table is
    counted as a fact even when none of its own columns is a MEASURE, which the shared
    role classifier does not see (it reads `column_id` columns only)."""
    body = model["model"] if isinstance(model.get("model"), dict) else model
    formulas = _dicts(body.get("formulas"))
    by_ref = tml.formula_ref_index(formulas)
    by_name = {f.get("name"): f for f in formulas if isinstance(f.get("name"), str)}
    todo, seen, tables = _measure_formulas(body), set(), set()
    while todo:
        f = todo.pop()
        if id(f) in seen:
            continue
        seen.add(id(f))
        for ref in tml.expr_refs(f.get("expr")):
            if "::" in ref:
                tables.add(ref.partition("::")[0].strip())
            elif by_ref.get(ref) in by_name:
                todo.append(by_name[by_ref[ref]])
    return frozenset(tables)


@register("rls_root_beside", uses=(),
          label="the other tables at the root of the Model's joins")
def _rls_root_beside(item: dict, ctx: Any) -> list:
    """Model table: when its Table TML (by `fqn`) carries RLS rules (_rls_rules_of, the
    S14/S15 reading), it holds no measures and is a root of the Model's directed joins
    (role `factless`, joined) while another table is a root too, the other roots' keys,
    sorted; else none. Query generation plans each root as its own fact and stitches
    them, so such a table — an access-control table joined many-to-one to a dimension is
    the measured case (S17, live-verified 2026-11-12) — doubles every query's SQL. A
    root holding measures (role `fact`), or one a formula measure reads
    (_formula_measure_tables), is a genuine fact of a multi-fact Model, not this shape,
    so it never fires; a name list in messages."""
    from ts_cli.audit.engine.messages import NameList  # messages imports fields
    obj = item.get("obj")
    fqn = obj.get("fqn") if isinstance(obj, dict) else None
    if not isinstance(fqn, str) or not _rls_rules_of(ctx.tables.get(fqn)):
        return NameList()
    me = item.get("name")
    if not isinstance(me, str) or not me:           # a non-string alias or name: no key
        return NameList()
    model = _model_of(item)
    roots = cached("join_roots", model, _join_roots, model, ctx)
    if me not in roots or model_roles(model, ctx).get(me, {}).get("role") != "factless":
        return NameList()
    if me in cached("formula_measure_tables", model, _formula_measure_tables, model):
        return NameList()
    return NameList(sorted(roots - {me}))


#: @rls_root_fix's values: which fix fits the table's RLS rules.
RLS_ROOT_FIXES = (
    "review its rules: they are not one `ts_username = [column]` rule, so check that "
    "after the RLS filter every user has at most one row per key (a user in two groups "
    "mapped to one key has two); if so, reverse the join so the dimension joins to it "
    "many-to-one, and if not, keep it, as the reversed join would double-count measures",
    "if it is an access-control table rather than a fact, reverse the join so the "
    "dimension joins to it many-to-one, once the conditions in the remediation hold",
)


#: The one rule shape the reversal is safe for: the user equals a column of the table.
_USER_EQUALS_KEY = re.compile(
    r"(?i)^\s*(?:ts_username\s*=\s*\[[^\]]+\]|\[[^\]]+\]\s*=\s*ts_username)\s*$")


def _keyed_on_user_alone(expr: Any) -> bool:
    """The rule is exactly `ts_username = [path::COLUMN]` (either side; quoted literals
    removed, so a literal comparison never matches): each user then sees only the rows
    whose key column holds their name, the condition the many-to-one reversal needs
    together with the (user, key) uniqueness the remediation asks to check. Anything
    else — ts_groups, a multi-value ts_var, `or`, `!=`, `in`, contains, a literal — can
    give a user several rows per key."""
    return isinstance(expr, str) and bool(_USER_EQUALS_KEY.match(_code(expr)))


@register("rls_root_fix", uses=(), values=RLS_ROOT_FIXES,
          label="the fix that fits the table's RLS rules")
def _rls_root_fix(item: dict, ctx: Any) -> str:
    """Model table: the second of RLS_ROOT_FIXES (reverse) only when its Table TML (by
    `fqn`) has exactly one RLS rule and it is keyed on the user alone
    (_keyed_on_user_alone); else the first (review: an access-control list should
    return one row per key per user after the filter, so the shape stays an
    anti-pattern, but the code cannot prove it here). A Table's rules combine with OR, so
    a second rule (owner or delegate) can give a user two rows per key, as can ts_groups,
    a multi-value ts_var or an `or`: the reversed many-to-one join would double-count
    measures, which the stitched plan's grouping does not."""
    obj = item.get("obj")
    fqn = obj.get("fqn") if isinstance(obj, dict) else None
    rules = _rls_rules_of(ctx.tables.get(fqn)) if isinstance(fqn, str) else []
    safe = len(rules) == 1 and _keyed_on_user_alone(rules[0].get("expr"))
    return RLS_ROOT_FIXES[1] if safe else RLS_ROOT_FIXES[0]


# ── D15: duplicate Table-level joins ────────────────────────────────────────

def _join_group_key(j: Any) -> Optional[tuple]:
    """(destination — `fqn`, else `name` —, `on` without whitespace) for a well-formed
    `joins_with` entry, else None."""
    dest = j.get("destination") if isinstance(j, dict) else None
    on = j.get("on") if isinstance(j, dict) else None
    if not isinstance(dest, dict) or not isinstance(on, str) or not on.strip():
        return None
    target = dest.get("fqn") or dest.get("name")
    return (target, "".join(on.split())) if isinstance(target, str) and target else None


def _duplicate_joins(table: dict) -> List[tuple]:
    """(label, conflicting) per group of two or more `joins_with` entries with the same
    destination and `on` (_join_group_key); conflicting when their type or cardinality
    differ. Malformed entries are skipped."""
    joins_with = table.get("joins_with")
    groups: dict = {}
    for j in joins_with if isinstance(joins_with, list) else []:
        key = _join_group_key(j)
        if key:
            groups.setdefault(key, []).append(j)
    out = []
    for (dest, _), joins in groups.items():
        if len(joins) > 1:
            shapes = {(_upper(j.get("type")), _upper(j.get("cardinality"))) for j in joins}
            name = joins[0]["destination"].get("name")
            name = name if isinstance(name, str) and name else dest
            out.append((f"{len(joins)} joins to {name} on {joins[0]['on']}", len(shapes) > 1))
    return out


@register("duplicate_joins", uses=(),
          label="the Table's duplicate joins")
def _duplicate_joins_field(item: dict, ctx: Any) -> list:
    """Table: one label per group of `joins_with` entries sharing a destination and an
    `on` (see _duplicate_joins); a name list in messages, empty when there are none."""
    from ts_cli.audit.engine.messages import NameList  # messages imports fields
    return NameList(label for label, _ in _duplicate_joins(item.get("obj") or {}))


@register("duplicate_joins_conflict", uses=(), values=(False, True),
          label="the Table's duplicate joins differ in type or cardinality")
def _duplicate_joins_conflict(item: dict, ctx: Any) -> bool:
    """Table: a group of duplicate joins whose type or cardinality differ, so a query's
    result depends on which one a Model takes."""
    return any(conflict for _, conflict in _duplicate_joins(item.get("obj") or {}))


# ── D16: join keys of different types ───────────────────────────────────────

#: Warehouse types by family: a join pairing two families compares unlike values.
_TYPE_FAMILIES = {
    "string": ("VARCHAR", "CHAR", "STRING", "TEXT"),
    "integer": ("INT32", "INT64", "INT", "INTEGER", "BIGINT", "SMALLINT", "TINYINT"),
    "decimal": ("DOUBLE", "FLOAT", "DECIMAL", "NUMBER", "NUMERIC", "REAL"),
    "datetime": ("DATE", "DATE_TIME", "DATETIME", "TIMESTAMP", "TIME"),
    "boolean": ("BOOL", "BOOLEAN"),
}
_FAMILY_OF = {t: fam for fam, types in _TYPE_FAMILIES.items() for t in types}


def key_type_mismatches(on: Any, col_types: dict) -> List[str]:
    """`"A::x (TYPE) = B::y (TYPE)"` for each key pair in `on` (the join graph's reader,
    tml_join_graph.on_clause_key_pairs: unescaped, whole conjuncts only) whose types are
    in different families (_TYPE_FAMILIES). A key with an unknown type, or a type
    outside the families, is not compared."""
    out = []
    for t1, c1, t2, c2 in on_clause_key_pairs(on if isinstance(on, str) else ""):
        left, right = f"{t1}::{c1}", f"{t2}::{c2}"
        lt, rt = (str(col_types.get(k, "")).upper() for k in (left, right))
        lf, rf = _FAMILY_OF.get(lt), _FAMILY_OF.get(rt)
        if lf and rf and lf != rf:
            out.append(f"{left} ({lt}) = {right} ({rt})")
    return out


@register("join_key_type_mismatches", uses=(),
          label="the join's key pairs of different types")
def _join_key_type_mismatches(item: dict, ctx: Any) -> list:
    """Join: each pair of keys in its `on` whose warehouse types, read off the Table TMLs
    (AuditContext.column_types, as @varchar_join_keys reads them), are of different
    families; a name list in messages. A key of a table with no Table TML in scope has
    no type and is not compared; one of an aliased table is read under the alias
    (tml.join_column_types, BL-507)."""
    from ts_cli.audit.engine.messages import NameList  # messages imports fields
    join = item.get("obj") or {}
    col_types = tml.join_column_types(join, _model_of(item), cached(
        "column_types", item["doc"], ctx.column_types, item["doc"]))
    return NameList(key_type_mismatches(join.get("on"), col_types))

