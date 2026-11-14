"""Derived fields for the H (Human Readiness) rules.

Registered into the same registry as engine/fields.py (which imports this module at its
end, so `fields.FIELDS` — and the catalog gate's list of known names — always includes
them). Each reproduces what a legacy check in checks_human.py (deleted when the rule catalog replaced them)
read, step for step, including the readings that are known to be wrong (the legacy
answers pinned in tests/audit_rule_fixtures/legacy_findings.json.gz hold them to it;
fixing them is the follow-up work the spec lists):

- H3 decided which tables are "joined" by a model table's `name` (and a join's raw
  `with`), where its columns' `column_id`s carry the `alias` when it has one, and
  tested a formula-backed column by its formula's display name only, where real TML
  references a formula by id (`[formula_<name>]`). Both fixed 2026-10 (roadmap PR 2.3):
  a table is keyed by alias, else name, and an id reference counts.

Where the legacy check would raise on a malformed value (a non-string expression or
`column_id`, a non-mapping `properties`), these read it as absent instead: a raising
legacy check aborts the whole H category, so there is nothing to reproduce.

Same import constraint as fields.py: Python 3.9, no third-party imports at module level.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from ts_cli.audit.engine import tml
from ts_cli.audit.engine.fields import (AGGREGATE_FUNCS, _aggregate_formula_names,
                                        _model_of, register)
from ts_cli.audit.engine.memo import cached
from ts_cli.tml_join_graph import on_clause_refs

_WHITESPACE = re.compile(r"\s+")


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""


# ── H1: column names a person would not search for ──────────────────────────

#: col1, field_2, val, tmp_x, a leading digit (any case) — and SHOUTING_SNAKE warehouse
#: names. H1 and the report's Spotter readiness score both read them through
#: `is_poor_name`; each kept its own copy until 2026-10.
_NAME_ANTI = re.compile(r"^col\d+$|^field[-_]?\d+$|^val\d*$|^tmp[-_]|^\d", re.IGNORECASE)
_NAME_ANTI_UPPER = re.compile(r"^[A-Z][A-Z0-9]*_[A-Z0-9_]+$")


def is_poor_name(name: Any) -> bool:
    """A name matching either pattern; False for a non-string."""
    return isinstance(name, str) and bool(_NAME_ANTI.match(name) or
                                          _NAME_ANTI_UPPER.match(name))


@register("is_poor_name", uses=(),
          label="the column's name is generic or a warehouse name")
def _is_poor_name(item: dict, ctx: Any) -> bool:
    """Model column: its `name` is one a person would not search for (is_poor_name)."""
    return is_poor_name((item.get("obj") or {}).get("name"))


# ── H3: hidden columns no formula references ────────────────────────────────

def _joined_table_names(model: dict) -> set:
    """H3's joined tables, by key: the same set D5 and D10 read (tml.joined_keys). Once
    per Model per run (engine/memo.py)."""
    return cached("joined_keys", model, tml.joined_keys, model.get("model_tables") or [])


def _is_hidden(column: Any) -> bool:
    props = column.get("properties") if isinstance(column, dict) else None
    return bool(props.get("is_hidden")) if isinstance(props, dict) else False


@register("is_sole_join_carrier", uses=(),
          label="the column is the only visible one from its joined table")
def _is_sole_join_carrier(item: dict, ctx: Any) -> bool:
    """Model column: its `column_id` prefix ("" without `::`) names a joined table
    (by NAME — see the module docstring) and no OTHER visible column of the Model
    carries that prefix — so hiding it keeps the join alive, and H3 excuses it."""
    model = _model_of(item)
    column = item.get("obj") or {}
    cid = _str(column.get("column_id", ""))
    table = cid.split("::")[0] if "::" in cid else ""
    if table not in _joined_table_names(model):
        return False
    prefix = f"{table}::"
    return not any(_str(cc.get("column_id", "")).startswith(prefix)
                   for cc in model.get("columns") or []
                   if cc is not column and not _is_hidden(cc))


def _join_ons(doc: dict, ctx: Any) -> List[Any]:
    """The `on` of every join of a Model: its inline joins, and the `joins_with` of its
    Tables in scope (where a referencing join's `on` lives)."""
    model_tables = (doc.get("model") or {}).get("model_tables") or []
    joins = [j for mt in model_tables if isinstance(mt, dict) for j in mt.get("joins") or []]
    joins += [j for t in ctx.tables_for_model(doc)
              for j in (t.get("table") or {}).get("joins_with") or []]
    return [j.get("on") for j in joins if isinstance(j, dict)]


def _join_key_ids(doc: dict, ctx: Any) -> set:
    """Lower-cased `TABLE::COL` of every key named in the Model's joins (_join_ons), read
    with the join graph's `[TABLE::COL]` reader (unescaped)."""
    return {f"{t}::{c}".lower() for on in _join_ons(doc, ctx) if isinstance(on, str)
            for t, c in on_clause_refs(on)}


@register("is_join_key", uses=(),
          label="the column is a key of one of the Model's joins")
def _is_join_key(item: dict, ctx: Any) -> bool:
    """Model column: its `column_id` is named in an `on` of the Model's joins (inline,
    or a referencing join's Table-level `on`) — a key, which a Model rightly hides. A
    key of an aliased table is matched by the Table's name only, so may be missed."""
    doc = item.get("doc") or {}
    keys = cached("join_key_ids", doc, _join_key_ids, doc, ctx)
    return _str((item.get("obj") or {}).get("column_id", "")).lower() in keys


@register("referenced_by_formula", uses=(),
          label="a formula references the column")
def _referenced_by_formula(item: dict, ctx: Any) -> bool:
    """Model column: another of the Model's formulas references it — as `[<its name>]`
    or `[<its column_id>]` (`[TABLE::COL]`, the usual form) — or, when it surfaces a
    formula (`formula_id`), references that formula by `[<its id>]` (how TML writes it)
    or `[<its formula name>]`. References are read as the formula tree reads them:
    outside quoted literals, stripped (tml.expr_refs), and a formula's reference to
    itself does not count (BL-504)."""
    model = _model_of(item)
    refs = cached("h3_formula_refs", model, _formula_refs, model.get("formulas") or [])
    column = item.get("obj") or {}
    fid = column.get("formula_id")
    own = fid if isinstance(fid, str) and fid else None
    names = _reference_names(column, own, model.get("formulas") or [])
    return any((own is None or owner != own) and names & used for owner, used in refs)


def _reference_names(column: dict, own: Any, formulas: list) -> set:
    """What a reference to this column is written as: its name, its `column_id`, and,
    when it surfaces formula `own`, that formula's id and name."""
    names = {v for v in (column.get("name"), column.get("column_id"), own)
             if isinstance(v, str) and v}
    if own:
        names |= {fn["name"] for fn in formulas
                  if isinstance(fn, dict) and fn.get("id") == own
                  and isinstance(fn.get("name"), str) and fn["name"]}
    return names


def _formula_refs(formulas: list) -> list:
    """(formula id, the set of references its expr makes), per formula."""
    return [(f.get("id"), set(tml.expr_refs(f.get("expr"))))
            for f in formulas if isinstance(f, dict)]


# ── H4 / H5: dependents ─────────────────────────────────────────────────────

# Declares `sets` too: it reads `ctx.dependents`, which Set discovery writes SET rows
# into. It filters them out, but no static check can prove that (catalog_reads.py).
@register("dependent_count", uses={"dependents", "sets"},
          label="the number of dependent objects")
def _dependent_count(item: dict, ctx: Any) -> int:
    """Model: how many `ctx.dependents` rows under its guid are not Sets. A Set is a
    column on the Model, so whatever uses it is already a Model dependent: a SET row
    alone never makes a Model used. A Model never listed has none."""
    rows = ctx.dependents.get(item.get("guid"), []) or []
    return sum(1 for d in rows if d.get("type") != "SET")


@register("orphan_model", uses={"dependents", "sets"}, values=(False, True),
          label="the item is a Model nothing uses")
def _orphan_model(item: dict, ctx: Any) -> bool:
    """True for a Model with no dependents but Sets (H4's test, @dependent_count); False
    for any other item, a column included — H10 grades its findings on this."""
    return item.get("scope") == "model" and _dependent_count(item, ctx) == 0


@register("set_consumers", uses={"dependents", "sets"},
          label="the objects that use the Set")
def _set_consumers(item: dict, ctx: Any) -> Any:
    """Set: the consumers its lookup returned (`ctx.dependents[<set guid>]`); None when
    it was not looked up — which a rule declaring `requires: [sets]` never sees."""
    return ctx.dependents.get(item.get("guid"))


# ── H7: Answers built straight off a Table ──────────────────────────────────

def _known_table_guids(ctx: Any) -> set:
    """legacy H7's `table_guids`: every non-empty `model_tables[].fqn` of every Model,
    and every Table TML key in the context — those left out as malformed included (they
    are still Tables). Once per run (engine/memo.py)."""
    return cached("h7_known_table_guids", ctx, _build_known_table_guids, ctx)


def _build_known_table_guids(ctx: Any) -> set:
    guids: set = set()
    for body in _all_model_bodies(ctx):
        for mt in _mappings(body.get("model_tables")):
            fqn = mt.get("fqn", "")
            if fqn and isinstance(fqn, str):
                guids.add(fqn)
    return guids | set(ctx.tables) | set(getattr(ctx, "excluded_tables", {}) or {})


def _all_models(ctx: Any) -> list:
    """Every Model in the run: the judged ones and those left out as malformed (BL-406
    item 10). A rule asking whether something is on NO Model reads this, never
    `ctx.models` alone, or excluding a Model would make that answer false."""
    return list(ctx.models) + list(getattr(ctx, "excluded_models", []) or [])


def _all_model_bodies(ctx: Any) -> list:
    """The `model` mapping of every Model in `_all_models`. An excluded Model may be
    misshapen anywhere (that is why it was excluded), so its body and lists are read
    defensively here — `_mappings` — never assumed (review of PR 1, blocker 1)."""
    return [doc["model"] for doc in _all_models(ctx)
            if isinstance(doc, dict) and isinstance(doc.get("model"), dict)]


def _mappings(value: Any) -> list:
    """The mapping entries of `value` when it is a list, else []."""
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


@register("is_table_reference", uses=(),
          label="the Answer reads a Table directly")
def _is_table_reference(item: dict, ctx: Any) -> bool:
    """Answer table reference: its `fqn` is set and is a Table's guid (see
    _known_table_guids). An Answer built on a Model carries the Model's guid there; an
    fqn matching nothing known is unresolved, not a bypass (BL-301)."""
    fqn = (item.get("obj") or {}).get("fqn", "")
    return bool(fqn) and fqn in _known_table_guids(ctx)


# ── H8 / H9: Answer formulas against Model formulas ─────────────────────────

def _normalize(expr: Any) -> Optional[str]:
    """legacy `_normalize_expr`: stripped, lower-cased, whitespace runs collapsed to one
    space. None for a non-string."""
    if not isinstance(expr, str):
        return None
    return _WHITESPACE.sub(" ", expr.strip().lower())


def _model_formula_names(ctx: Any) -> Dict[str, Any]:
    """Normalised expression -> the `name` of the LAST Model formula (across every
    Model, in order) with that expression, as legacy H9 builds it; its keys are H8's
    set. An absent `expr` normalises to "" like any other. Once per run — it is read for
    every Answer formula (engine/memo.py)."""
    return cached("h8_model_formula_names", ctx, _build_model_formula_names, ctx)


def _build_model_formula_names(ctx: Any) -> Dict[str, Any]:
    names: Dict[str, Any] = {}
    for body in _all_model_bodies(ctx):
        for f in _mappings(body.get("formulas")):
            key = _normalize(f.get("expr", ""))
            if key is not None:
                names[key] = f.get("name", "")
    return names


@register("normalized_expr", uses=(),
          label="the formula expression, normalised")
def _normalized_expr(item: dict, ctx: Any) -> Optional[str]:
    """Answer formula: its `expr` normalised (see _normalize; absent reads as "")."""
    return _normalize((item.get("obj") or {}).get("expr", ""))


@register("matches_model_formula", uses=(),
          label="a Model formula has the same expression")
def _matches_model_formula(item: dict, ctx: Any) -> bool:
    """Answer formula: a Model formula has the same normalised expression — a blank one
    included (legacy H9 has no blank guard; H8 excludes blanks itself)."""
    expr = _normalized_expr(item, ctx)
    return expr is not None and expr in _model_formula_names(ctx)


@register("matched_model_formula_name", uses=(),
          label="the Model formula with the same expression")
def _matched_model_formula_name(item: dict, ctx: Any) -> Any:
    """Answer formula: the name of the Model formula it duplicates (the last one with
    that expression), or None."""
    return _model_formula_names(ctx).get(_normalized_expr(item, ctx))


@register("answer_name", uses=(),
          label="the Answer's name")
def _answer_name(item: dict, ctx: Any) -> Any:
    """Answer formula: the name of its Answer, as an Answer finding reports it ("" when
    the Answer has no `name`)."""
    return (item.get("parent") or {}).get("name")


# ── A8: one search term naming two columns ──────────────────────────────────

def _column_terms(col: dict) -> Tuple[str, set]:
    """(the column's name, trimmed and lower-cased; its synonyms, the same way) — read as
    @has_synonyms reads them: under `properties:`, else at the root."""
    def norm(t: Any) -> str:
        return t.strip().lower() if isinstance(t, str) else ""
    syns = tml.mapping(col, "properties").get("synonyms") or col.get("synonyms") or []
    syns = syns if isinstance(syns, list) else []
    return norm(col.get("name")), {norm(t) for t in syns} - {""}


def _shared_terms(model: dict) -> Dict[str, str]:
    """{term: "name" | "synonym"} for each term — a visible column's name or synonym —
    that names two or more visible columns; "name" when it is some column's name."""
    owners: Dict[str, set] = {}
    names = set()
    for i, col in enumerate(model.get("columns") or []):
        if not isinstance(col, dict) or tml.mapping(col, "properties").get("is_hidden"):
            continue
        name, syns = _column_terms(col)
        if name:
            names.add(name)
        for term in syns | ({name} - {""}):
            owners.setdefault(term, set()).add(i)
    return {t: ("name" if t in names else "synonym")
            for t, cols in owners.items() if len(cols) > 1}


def _shared(item: dict) -> Dict[str, str]:
    model = item.get("obj") or {}
    return cached("shared_terms", model, _shared_terms, model)


@register("shared_terms", uses=(),
          label="the search terms that name two or more columns")
def _shared_terms_field(item: dict, ctx: Any) -> List[str]:
    """Model: each term (trimmed, lower-cased) that is the name or a synonym of two or
    more visible columns — column names first, so a MEDIUM message's first five show
    what made it MEDIUM — then sorted; a name list in messages."""
    from ts_cli.audit.engine.messages import NameList  # messages imports fields
    shared = _shared(item)
    return NameList(sorted(shared, key=lambda t: (shared[t] != "name", t)))


@register("shared_term_count", uses=(),
          label="the number of search terms that name two or more columns")
def _shared_term_count(item: dict, ctx: Any) -> int:
    """Model: how many terms name two or more visible columns (see @shared_terms)."""
    return len(_shared(item))


@register("shared_term_kind", uses=(), values=("name", "synonym", None),
          label="the worst kind of shared search term")
def _shared_term_kind(item: dict, ctx: Any) -> Optional[str]:
    """Model: "name" when a shared term is some visible column's name (searching it may
    pick the other column), "synonym" when only synonyms are shared, None when none is."""
    kinds = set(_shared(item).values())
    return "name" if "name" in kinds else ("synonym" if kinds else None)



# ── H15: hidden formulas used by exactly one other formula ──────────────────

#: What wraps a helper's expression when it is pasted into the formula that uses it.
_INLINE_WRAP = len("(  )")


def _named_columns(model: dict) -> set:
    """The column names something else in the Model names: each `filters[].column`
    (a list, or a scalar) and each column's `properties.currency_type.column`."""
    out = set()
    for f in model.get("filters") or []:
        col = f.get("column") if isinstance(f, dict) else None
        out.update(str(c) for c in (col if isinstance(col, (list, tuple)) else [col])
                   if c is not None)
    for c in model.get("columns") or []:
        currency = tml.mapping(c, "properties").get("currency_type") if isinstance(c, dict) else None
        if isinstance(currency, dict) and currency.get("column") is not None:
            out.add(str(currency["column"]))
    return out


def _text(segments: Any) -> Optional[str]:
    """An expression rebuilt from its formula-tree segments, as written; None when the
    TML gave none, or none that is text."""
    if not isinstance(segments, list) or not segments:
        return None
    return "".join(s if isinstance(s, str) else str(s.get("ref") or "") for s in segments)


def _refs_to(segments: Any, name: str) -> int:
    return sum(1 for s in segments or [] if isinstance(s, dict) and s.get("formula") == name)


_CALL_OR_PAREN = re.compile(r"([A-Za-z_]\w*(?:\s+count)?)\s*\(|\(|\)")
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
_GROUP_CALL = re.compile(r"(?i)group_\w+\Z")


def _calls_around(user: dict, name: str) -> List[str]:
    """The calls (function names, lower-case) that enclose `user`'s first reference to
    formula `name`, outermost first: read off its segments, quoted literals left out,
    a bare bracket recorded as ""."""
    stack: List[str] = []
    for seg in user["expr"]:
        if isinstance(seg, dict):
            if seg.get("formula") == name:
                return stack
            continue
        for m in _CALL_OR_PAREN.finditer(_QUOTED.sub(" ", seg)):
            if m.group(0) == ")":
                if stack:
                    stack.pop()
            else:
                stack.append((m.group(1) or "").lower())
    return stack


def _paste_nests(user: dict, name: str, aggregates: bool) -> bool:
    """Pasting formula `name` into `user` would write a form ThoughtSpot rejects
    (thoughtspot-formula-patterns.md, "Group functions" rules 2 and 4): an aggregating
    helper inside an aggregate, group or window call, or any helper inside a group
    call, where only a column or a formula reference is shown working."""
    for call in _calls_around(user, name):
        if _GROUP_CALL.match(call):
            return True
        if aggregates and call and AGGREGATE_FUNCS.match(call + " ("):
            return True
    return False


def _inlined_length(user: dict, name: str, text: str) -> int:
    """The length of `user`'s expression with its reference to formula `name` replaced
    by `( <text> )`; every other reference counts as written."""
    total = 0
    for seg in user["expr"]:
        if isinstance(seg, str):
            total += len(seg)
        elif seg.get("formula") == name:
            total += len(text) + _INLINE_WRAP
        else:
            total += len(str(seg.get("ref") or ""))
    return total


def _helper_entry(name: str, node: dict, users: List[str], nodes: Dict[str, dict],
                  model: dict) -> dict:
    from ts_cli.audit.formula_tree import _reachable
    sole = users[0] if len(users) == 1 else None
    named, shared, aggregates = model["named"], model["shared"], model["aggregates"]
    entry = {"label": node["label"], "hidden": node["hidden"], "user_count": len(users),
             "sole_user": nodes[sole]["label"] if sole else None,
             "named": node["label"] in named or name in named,
             "cyclic": False, "user_refs": 0, "inlined_length": None,
             "blocked": name in shared}
    if sole is None:
        return entry
    user = nodes[sole]
    entry["user_refs"] = _refs_to(user["expr"], name)
    entry["cyclic"] = _refs_to(node["expr"], name) > 0 or sole in _reachable([name], nodes)
    entry["blocked"] = (entry["blocked"] or (user["hidden"] and user["used_by"] == 0)
                        or (isinstance(user["expr"], list)
                            and _paste_nests(user, name, name in aggregates)))
    text = _text(node["expr"])
    if text is not None and isinstance(nodes[sole]["expr"], list):
        entry["inlined_length"] = _inlined_length(nodes[sole], name, text)
    return entry


def _build_single_use(model: dict) -> Dict[str, dict]:
    """Per formula name, read off the report's formula tree (so the audit and the
    Formulas view read uses the same way): its label, whether it is hidden, how many
    formulas use it and the label of the one that does when only one does, whether a
    Model filter or currency setting names its column, whether it and that one user
    form a cycle (a reference to itself counts), how many times that user references
    it, that user's length with it pasted in, and whether pasting is blocked: its name
    is shared (the tree keeps one formula of a name, so "used only by" may be false),
    its user is itself hidden and unused (remove both instead), or the paste would nest
    an aggregate where ThoughtSpot rejects one (_paste_nests)."""
    from ts_cli.audit.formula_tree import formula_tree
    nodes = {n["name"]: n for n in formula_tree(model)["nodes"]}
    users: Dict[str, List[str]] = {n: [] for n in nodes}
    for user, node in nodes.items():
        for use in node["uses"]:
            if "formula" in use:
                users[use["formula"]].append(user)
    names = [f.get("name") for f in model.get("formulas") or [] if isinstance(f, dict)]
    facts = {"named": _named_columns(model),
             "shared": {n for n in names if isinstance(n, str) and names.count(n) > 1},
             "aggregates": _aggregate_formula_names(model)}
    return {name: _helper_entry(name, node, users[name], nodes, facts)
            for name, node in nodes.items()}


def _first_index(model: dict) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for i, f in enumerate(model.get("formulas") or []):
        name = f.get("name") if isinstance(f, dict) else None
        if isinstance(name, str) and name not in out:
            out[name] = i
    return out


def _single_use(item: dict) -> dict:
    """This formula's entry in _build_single_use; {} for a formula sharing an earlier
    formula's name (the tree keeps the first, so a name reports once) or whose name is
    not text (malformed TML, BL-501)."""
    model = _model_of(item)
    name = (item.get("obj") or {}).get("name")
    if not isinstance(name, str):
        return {}
    if cached("formula_first_index", model, _first_index, model).get(name) != item.get("index"):
        return {}
    return cached("single_use_helpers", model, _build_single_use, model).get(name, {})


@register("formula_label", uses=(),
          label="the name people search the formula by")
def _formula_label(item: dict, ctx: Any) -> Optional[str]:
    """Formula: its surfacing column's name, else its own name."""
    return _single_use(item).get("label") or (item.get("obj") or {}).get("name")


@register("formula_hidden", uses=(),
          label="the formula is hidden (its column is hidden, or no column shows it)")
def _formula_hidden(item: dict, ctx: Any) -> bool:
    """Formula: its surfacing column is hidden, or no column surfaces it."""
    return bool(_single_use(item).get("hidden"))


@register("formula_user_count", uses=(),
          label="the number of formulas that use the formula")
def _formula_user_count(item: dict, ctx: Any) -> int:
    """Formula: how many other formulas reference it."""
    return int(_single_use(item).get("user_count") or 0)


@register("sole_formula_user", uses=(),
          label="the one formula that uses the formula")
def _sole_formula_user(item: dict, ctx: Any) -> Optional[str]:
    """Formula: the name people search the one formula that uses it by; None unless
    exactly one formula does."""
    return _single_use(item).get("sole_user")


@register("sole_user_reference_count", uses=(),
          label="how many times the one formula that uses it references it")
def _sole_user_reference_count(item: dict, ctx: Any) -> int:
    """Formula used by exactly one formula: how many times that formula references it
    (0 otherwise)."""
    return int(_single_use(item).get("user_refs") or 0)


@register("formula_column_named", uses=(),
          label="a Model filter or currency setting names the formula's column")
def _formula_column_named(item: dict, ctx: Any) -> bool:
    """Formula: a Model `filters[]` entry, or a column's `currency_type.column`, names
    its column (or the formula)."""
    return bool(_single_use(item).get("named"))


@register("formula_cycles_with_user", uses=(),
          label="the formula and the one formula that uses it form a cycle")
def _formula_cycles_with_user(item: dict, ctx: Any) -> bool:
    """Formula used by exactly one formula: it reaches that formula through what it
    uses, or references itself."""
    return bool(_single_use(item).get("cyclic"))


@register("paste_blocked", uses=(),
          label="pasting the formula in would be invalid or pointless")
def _paste_blocked(item: dict, ctx: Any) -> bool:
    """Formula: another formula shares its name; or the one formula that uses it is
    hidden and unused itself; or pasting it there would put an aggregate inside an
    aggregate, group or window call, or anything inside a group call, which
    ThoughtSpot rejects."""
    return bool(_single_use(item).get("blocked"))


@register("inlined_length", uses=(),
          label="the length of the formula that uses it, with this formula pasted in")
def _inlined_length_field(item: dict, ctx: Any) -> Optional[int]:
    """Formula used by exactly one formula: that formula's expression length with this
    one pasted in, in parentheses (this helper only: pasting several helpers into one
    formula adds up); None otherwise, or when either expression is not text."""
    return _single_use(item).get("inlined_length")
