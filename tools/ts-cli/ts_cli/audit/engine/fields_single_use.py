"""Derived fields for H16, a hidden formula used by exactly one other formula.

Registered into the same registry as engine/fields.py, which imports this module at
its end (as it does fields_data and fields_human). Reads the report's formula tree
(ts_cli/audit/formula_tree.py, inside each function: it imports the engine package),
so the audit and the Formulas view read uses the same way. H16's findings also mark
the helpers the view tags and pastes in (report.py `_pasteable`).

Same import constraint as fields.py: Python 3.9, no third-party imports at module level.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from ts_cli.audit.engine import tml
from ts_cli.audit.engine.fields import (_IF_CALL, AGGREGATE_FUNCS, _aggregate_formula_names,
                                        _formula_names_by_id, _model_of, register)
from ts_cli.audit.engine.memo import cached
from ts_cli.formula_translate.refs import _QUOTED as _LITERAL
from ts_cli.spotql_ops import is_bare_window


# ── H16: hidden formulas used by exactly one other formula ──────────────────

#: What wraps a helper's expression when it is pasted into the formula that uses it.
_INLINE_WRAP = len("(  )")


def _named_columns(model: dict) -> set:
    """The column names a Model filter (`filters[].column`, a list or a scalar) or a
    column's currency setting (`properties.currency_type.column`) names. Not read:
    `joins_with[].on` and `date_range_condition` columns (BL-575, item 3). Case-folded:
    whether ThoughtSpot matches these names case-insensitively is not recorded, so
    either way counts."""
    out = set()
    for f in model.get("filters") or []:
        col = f.get("column") if isinstance(f, dict) else None
        out.update(_spelling(c) for c in (col if isinstance(col, (list, tuple)) else [col])
                   if c is not None)
    for c in model.get("columns") or []:
        currency = tml.mapping(c, "properties").get("currency_type") if isinstance(c, dict) else None
        if isinstance(currency, dict) and currency.get("column") is not None:
            out.add(_spelling(currency["column"]))
    return out


def _text(segments: Any) -> Optional[str]:
    """An expression rebuilt from its formula-tree segments, as written; None when the
    TML gave none, or none that is text."""
    if not isinstance(segments, list) or not segments:
        return None
    return "".join(s if isinstance(s, str) else str(s.get("ref") or "") for s in segments)


def _refs_to(segments: Any, name: str) -> int:
    return sum(1 for s in segments or [] if isinstance(s, dict) and s.get("formula") == name)


#: A call (`unique count` is the one two-word name, as in formula_translate.refs) or a
#: bare bracket.
_CALL_OR_PAREN = re.compile(r"(unique\s+count|[A-Za-z_]\w*)\s*\(|\(|\)", re.IGNORECASE)
_SQL_AGGREGATE_CALL = re.compile(r"(?i)sql_\w+_aggregate_op\Z")
#: Aggregates that take row-level input and return one value per group: not group,
#: window, rank or first/last value functions, nor SQL pass-through.
_NOT_PLAIN = re.compile(r"(?i)(group_\w+|moving_\w+|cumulative_\w+|rank\w*|(first|last)_value\w*)\Z")


def _tokens(segments: Any):
    """`("call", name)`, `("close", "")` and `("ref", segment)` in order, read off an
    expression's tree segments: calls and brackets from the text segments only, quoted
    literals left out with the shared grammar (formula_translate.refs), so a
    reference's name is never read as code (BL-369)."""
    for seg in segments if isinstance(segments, list) else []:
        if isinstance(seg, dict):
            yield "ref", seg
            continue
        for m in _CALL_OR_PAREN.finditer(_LITERAL.sub(" ", seg)):
            if m.group(0) == ")":
                yield "close", ""
            else:
                yield "call", " ".join((m.group(1) or "").lower().split())


def _calls_around(user: dict, name: str) -> List[str]:
    """The calls (function names, lower-case) that enclose `user`'s first reference to
    formula `name`, outermost first; a bare bracket recorded as ""."""
    stack: List[str] = []
    for kind, value in _tokens(user["expr"]):
        if kind == "ref":
            if value.get("formula") == name:
                return stack
        elif kind == "close":
            if stack:
                stack.pop()
        else:
            stack.append(value)
    return stack


def _aggregate_family(call: str) -> bool:
    """Any aggregate, group, window, rank or first/last value call, or SQL pass-through
    aggregation."""
    return bool(call) and bool(AGGREGATE_FUNCS.match(call + " (") or _SQL_AGGREGATE_CALL.match(call))


def _paste_allowed(user: dict, name: str, aggregating: bool, user_aggregates: bool) -> bool:
    """Pasting formula `name` into `user` reads the way referencing it does, in the
    plainest cases only (fail safe: anything else is not suggested, whatever
    ThoughtSpot might accept). An aggregating helper: when no aggregate-family call
    encloses its reference, so the pasted aggregate stands where the reference stood.
    A row-level helper: when every aggregate-family call around it is a plain
    aggregate (sum, average, count and the like), which takes any row-level
    expression, and, when `user_aggregates` (the formula using it aggregates), at least
    one does: a bare row-level expression beside an aggregate may roll up differently
    from the reference. A group, window, rank or first/last value call around a
    helper is never suggested: which argument the reference fills, and what that
    argument takes, is more than the formula reference settles."""
    family = [c for c in _calls_around(user, name) if _aggregate_family(c)]
    if aggregating:
        return not family
    if user_aggregates and not family:
        return False
    return all(not _NOT_PLAIN.match(c) and not _SQL_AGGREGATE_CALL.match(c) for c in family)


def _bare_window(segments: Any) -> bool:
    """spotql_ops.is_bare_window on the expression with its literals emptied, each
    reference a placeholder and redundant enclosing brackets dropped, so neither a
    bracket inside a name or a literal nor `( group_sum ( ... ) )` hides the call."""
    if not isinstance(segments, list):
        return False
    text = "".join(_LITERAL.sub("''", s) if isinstance(s, str) else "[r]" for s in segments).strip()
    while text.startswith("(") and _closes_at_end(text):
        text = text[1:-1].strip()
    return is_bare_window(text)


def _closes_at_end(text: str) -> bool:
    """The bracket opening `text` is the one closing it."""
    depth = 0
    for i, ch in enumerate(text):
        depth += {"(": 1, ")": -1}.get(ch, 0)
        if depth == 0:
            return i == len(text) - 1
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
    columns = model["columns"].get(name, set()) | {node["label"], name}
    entry = {"label": node["label"], "hidden": node["hidden"], "user_count": len(users),
             "sole_user": nodes[sole]["label"] if sole else None,
             "named": bool({_spelling(c) for c in columns} & model["named"]),
             "cyclic": False, "user_refs": 0, "inlined_length": None,
             "blocked": bool(model["shared"] or model["ambiguous"])}
    if sole is None:
        return entry
    user = nodes[sole]
    entry["user_refs"] = _refs_to(user["expr"], name)
    entry["cyclic"] = _refs_to(node["expr"], name) > 0 or sole in _reachable([name], nodes)
    entry["blocked"] = (entry["blocked"] or sole not in model["live"]
                        or name in model["kept_aggregation"]
                        or _bare_window(node["expr"])
                        or not isinstance(user["expr"], list)
                        or not _paste_allowed(user, name, name in model["aggregating"],
                                              sole in model["aggregating"]))
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
    it, that user's length with it pasted in, and whether pasting is blocked: the
    Model has two formulas of one name (the tree keeps one of them, so its uses, and
    "used only by", may be wrong), no visible formula sits above its user (remove the
    chain instead), a column shows it with an aggregation other than SUM, it is a bare
    window or group call (_bare_window), the Model spells a formula ambiguously
    (_ambiguous_spellings), or the paste is not
    one of the plain cases _paste_allowed suggests."""
    from ts_cli.audit.formula_tree import formula_tree
    nodes = {n["name"]: n for n in formula_tree(model)["nodes"]}
    users: Dict[str, List[str]] = {n: [] for n in nodes}
    for user, node in nodes.items():
        for use in node["uses"]:
            if "formula" in use:
                users[use["formula"]].append(user)
    facts = _model_facts(model, nodes)
    entries = {name: _helper_entry(name, node, users[name], nodes, facts)
               for name, node in nodes.items()}
    _measure_together(entries, nodes, users)
    return entries


def _model_facts(model: dict, nodes: Dict[str, dict]) -> dict:
    """What _helper_entry reads about the whole Model (see _build_single_use)."""
    from collections import Counter
    from ts_cli.audit.formula_tree import _reachable
    counts = Counter(f.get("name") for f in model.get("formulas") or []
                     if isinstance(f, dict) and isinstance(f.get("name"), str))
    visible = [n for n, node in nodes.items() if not node["hidden"]]
    return {"named": _named_columns(model),
            "columns": _surfacing_names(model),
            "shared": {n for n, c in counts.items() if c > 1},
            "aggregating": cached("aggregate_formula_names", model,
                                  _aggregate_formula_names, model),
            "kept_aggregation": _kept_aggregation(model),
            "ambiguous": _ambiguous_spellings(model, nodes),
            "live": _reachable(visible, nodes)}


def _spelling(value: Any) -> str:
    """A name as compared here: text, edges trimmed (as tml.expr_parts trims a
    reference), case aside."""
    return str(value).strip().casefold()


def _ambiguous_spellings(model: dict, nodes: Dict[str, dict]) -> bool:
    """The Model spells a formula in a way the shared reference index (exact match,
    first surfacing column only, last formula of a spelling wins, formulas before
    columns and parameters) may read differently from ThoughtSpot (BL-578): a formula
    has no name; one spelling, trimmed and case aside, names two formulas (an id, a
    name or any surfacing column's name), or a formula and a physical column or
    parameter; or a reference the tree read as a column matches a formula's spelling.
    Then "used only by" and the aggregate reading H16 shares with P2 can be wrong
    anywhere in the Model. Fail safe: H16 reports nothing there."""
    owner = _formula_spellings(model)
    if owner is None:
        return True
    if any(_spelling(o) in owner for o in _non_formula_names(model)):
        return True
    refs = {_spelling(seg["column"]) for node in nodes.values() for seg in node["expr"] or []
            if isinstance(seg, dict) and "column" in seg}
    return bool(refs & set(owner))


def _formula_spellings(model: dict) -> Optional[Dict[str, str]]:
    """Each formula's spellings (name, id, every surfacing column's name) to its name;
    None when a formula has no name or two formulas share a spelling."""
    owner: Dict[str, str] = {}
    surfacing = _surfacing_names(model)
    for f in model.get("formulas") or []:
        name = f.get("name") if isinstance(f, dict) else None
        if not isinstance(name, str) or not name.strip():
            return None
        ident = f.get("id")
        spellings = {name} | surfacing.get(name, set()) | ({ident} if isinstance(ident, str) else set())
        if any(sp and owner.setdefault(_spelling(sp), name) != name for sp in spellings):
            return None
    return owner


def _non_formula_names(model: dict) -> List[Any]:
    """The names of the Model's physical columns and parameters."""
    names = [c.get("name") for c in model.get("columns") or []
             if isinstance(c, dict) and not c.get("formula_id")]
    names += [p.get("name") for p in model.get("parameters") or [] if isinstance(p, dict)]
    return [n for n in names if n is not None]


def _kept_aggregation(model: dict) -> set:
    """Formulas a column surfaces with an aggregation other than SUM (the default):
    pasting the expression drops that column, and with it the aggregation, which
    thoughtspot-model-tml.md calls load-bearing on some formulas."""
    ids = _formula_names_by_id(model)
    out = set()
    for c in model.get("columns") or []:
        fid = c.get("formula_id") if isinstance(c, dict) else None
        name = ids.get(fid) if isinstance(fid, str) else None
        agg = str(tml.mapping(c, "properties").get("aggregation") or "SUM").upper()
        if isinstance(name, str) and agg != "SUM":
            out.add(name)
    return out


def _surfacing_names(model: dict) -> Dict[str, set]:
    """Per formula name, the names of every column that surfaces it (a formula can have
    more than one), so a filter on any of them counts."""
    ids = _formula_names_by_id(model)
    out: Dict[str, set] = {}
    for c in model.get("columns") or []:
        fid = c.get("formula_id") if isinstance(c, dict) else None
        name = ids.get(fid) if isinstance(fid, str) else None
        if isinstance(name, str) and c.get("name") is not None:
            out.setdefault(name, set()).add(str(c["name"]))  # a YAML number too
    return out


def _pasteable_entry(entry: dict) -> bool:
    """Everything H16 asks of a helper but the length: hidden, one user referencing it
    once, nothing naming its column, no cycle, nothing blocking the paste, and text."""
    return bool(entry["hidden"] and entry["user_count"] == 1 and entry["user_refs"] == 1
                and not entry["named"] and not entry["cyclic"] and not entry["blocked"]
                and entry["inlined_length"] is not None)


def _measure_together(entries: Dict[str, dict], nodes: Dict[str, dict],
                      users: Dict[str, List[str]]) -> None:
    """Replace each pasteable helper's length with that of the formula it ends up in
    (`target`: up through users that are pasteable themselves) once EVERY pasteable
    helper under that formula is pasted in, all the way down: the result the Formulas
    view shows, and what the 250 limit is on (the product owner, 2026-11-14), so
    findings that each pass cannot add up past it."""
    paste = {n for n, e in entries.items() if _pasteable_entry(e)}
    measured: Dict[str, Tuple[Any, Any]] = {}
    for name in paste:
        target, seen = users[name][0], {name}
        while target in paste and target not in seen:
            seen.add(target)
            target = users[target][0]
        entries[name]["target"] = nodes[target]["label"]
        if target not in measured:
            try:
                measured[target] = (_expanded(target, nodes, paste, set())
                                    if isinstance(nodes[target]["expr"], list) else (None, None))
            except RecursionError:  # a chain of ~1,000 helpers: no finding, never a crash
                measured[target] = (None, None)
        length, ifs = measured[target]
        entries[name]["inlined_length"], entries[name]["inlined_ifs"] = length, ifs


def _expanded(name: str, nodes: Dict[str, dict], paste: set, open_: set) -> Tuple[int, int]:
    """The length of formula `name` with every pasteable helper it references pasted
    in, in parentheses, recursively, and how many `if (` calls the result makes (as P16
    counts them); a helper already open (never, after the cycle exclusion, but cheap to
    guard) counts as written."""
    length = ifs = 0
    open_ = open_ | {name}
    for seg in nodes[name]["expr"]:
        if isinstance(seg, str):
            length += len(seg)
            ifs += len(_IF_CALL.findall(seg))
        elif seg.get("formula") in paste and seg["formula"] not in open_:
            inner = _expanded(seg["formula"], nodes, paste, open_)
            length += inner[0] + _INLINE_WRAP
            ifs += inner[1]
        else:
            written = str(seg.get("ref") or "")
            length += len(written)
            ifs += len(_IF_CALL.findall(written))  # P16 counts the raw text, names included
    return length, ifs


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
          label="the formula is hidden (no visible column shows it)")
def _formula_hidden(item: dict, ctx: Any) -> bool:
    """Formula: no visible column surfaces it (formula_tree prefers a visible one)."""
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
          label="pasting the formula in is not one of the plain, safe cases, or is pointless")
def _paste_blocked(item: dict, ctx: Any) -> bool:
    """Formula: the Model has two formulas of one name; no visible formula sits above
    the one formula that uses it; a column shows it with an aggregation other than
    SUM; it is a bare window or group call; the Model spells a formula ambiguously
    (two formulas share a spelling case aside, or a reference read as a column matches
    one); or pasting it there is not one of the plain cases
    _paste_allowed suggests."""
    return bool(_single_use(item).get("blocked"))


@register("paste_target", uses=(),
          label="the formula the helper ends up in once every such helper is pasted in")
def _paste_target(item: dict, ctx: Any) -> Optional[str]:
    """Formula H16 could report: the formula it ends up in, by label — its one user, or,
    when that user is a helper pasted in too, the formula above it; None otherwise."""
    return _single_use(item).get("target")


@register("inlined_if_count", uses=(),
          label="the number of IF calls in the formula it ends up in, with every such helper pasted in")
def _inlined_if_count(item: dict, ctx: Any) -> Optional[int]:
    """Formula H16 could report: how many `if (` calls the formula it ends up in makes
    with every such helper pasted in (as P16 counts them); None otherwise."""
    return _single_use(item).get("inlined_ifs")


@register("inlined_length", uses=(),
          label="the length of the formula it ends up in, with every such helper pasted in")
def _inlined_length_field(item: dict, ctx: Any) -> Optional[int]:
    """Formula used by exactly one formula: the length of the formula it ends up in
    (@paste_target) with every helper H16 could report under it pasted in, in
    parentheses, all the way down; for any other helper, its one user's length with it
    alone pasted in. None when no one formula uses it, or an expression is not text."""
    return _single_use(item).get("inlined_length")
