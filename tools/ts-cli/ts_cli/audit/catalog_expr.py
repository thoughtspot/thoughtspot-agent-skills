"""Audit rule catalog — what a rule's `aggregate`, predicates and messages may say.

Split out of `catalog_validate.py` (which re-exports everything here): the vocabulary
of scopes, modes and operators, and the checks over the parts of a rule the engine
*interprets* — `where`/`match` expressions, the per-mode `aggregate` keys, field paths,
message placeholders. The engine (`ts_cli/audit/engine/`) reads the same constants, so
the validator and the runtime cannot disagree about what a key means.

Field paths (`field:`, `measure:`, `key:`, `value:`, `member:`, `set:`, components):
a dotted path into the item (`properties.column_type`; a numeric step indexes a list,
any other step on a list maps over it), optionally prefixed `parent.` (repeatable) to
read the enclosing item; or a derived field `@name` registered in `engine/fields.py`,
which is always the WHOLE path after any `parent.` — never a step inside one.

An expression mapping takes exactly ONE form — anything else is rejected, never
half-evaluated:
  {all: [expr, ...]}  {any: [expr, ...]}  {not: expr}      a combinator, alone
  {field: <path>, <op>: <operand>, ...}                    one or more operators, ANDed
  {count: <scope>, [where: expr], <op>: <operand>, ...}    how many `scope` items pass
            `where`; `scope` must be a child of the item's scope or of a scope enclosing
            it, and at least one comparison is required
To combine a combinator with anything else, wrap both in `all`.

Operand semantics, checked here and implemented in `engine/predicates.py`:
  eq        scalar equality (string, number, true/false or null). A boolean never
            equals a number (YAML `true` is not `1`); an absent field equals null.
  in        the value equals (as `eq`) one of a list of scalars.
  contains  substring when the value is a string; membership when it is a list.
            The operand is one scalar. Any other value type never contains anything.
  regex / not_regex   `re.search` on string values (flags inline, e.g. `(?i)`);
            regex is false and not_regex true for a non-string value.
  exists / nonblank / truthy   take true or false.
  gt gte lt lte       numeric comparison; false for a non-number (booleans included).
  len_gt len_lt       length of a string/list/mapping; an absent value has length 0.

Kept importable on Python 3.9 with only PyYAML (see catalog_model.py). The one engine
import, `known_derived_fields`, is lazy and pulls in only `engine/fields.py` and
`audit/rules.py`, which hold to the same constraint.
"""
from __future__ import annotations

import re
import string
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

# ── vocabulary ──────────────────────────────────────────────────────────────

SCOPES = [
    "model", "model.column", "model.formula", "model.filter", "model.table",
    "join", "table", "table.rls_rule", "rls_column_ref",
    "answer", "answer.table_ref", "answer.formula", "set", "metadata",
]
# Child scope -> the scope its items belong to. Scopes not listed are top level.
PARENT_SCOPE = {
    "model.column": "model", "model.formula": "model", "model.filter": "model",
    "model.table": "model", "join": "model",
    "table.rls_rule": "table", "rls_column_ref": "table",
    "answer.table_ref": "answer", "answer.formula": "answer",
}
MODES = ["each", "ratio", "count", "group", "pairwise", "composite"]
OPERATORS = [
    "eq", "in", "regex", "not_regex", "exists", "nonblank", "truthy",
    "gt", "gte", "lt", "lte", "len_gt", "len_lt", "contains",
    "all", "any", "not", "count",
]
_COMBINATORS = {"all", "any", "not", "count"}
LEAF_OPERATORS = [op for op in OPERATORS if op not in _COMBINATORS]

# The keys an `aggregate` block may carry, per mode. Anything else is a typo and fails
# validation (a mistyped `wher:` would otherwise filter nothing). Tasks that need a
# mode to do more extend its entry here and in engine/modes.py together.
#   each       one finding per scope item passing `where`; `measure` is a field whose
#              value is the metric and what `bands` grade
#   ratio      share of the item's `over` children passing `where` that also `match`
#   count      number of the item's `over` children passing `where`
#   group      scope items passing `where`, grouped by `key` (a path, or a list of
#              paths for a composite key); `kind: duplicates` fires on a group of 2+,
#              `kind: divergence` on 2+ distinct `value`s. `member` labels the members
#              (default: their names), `name` templates the finding's object name
#              (default "{key}"), `guid` is the first member's (`first`) or empty (`none`)
#   pairwise   every unordered pair of scope items passing `where`, by the Jaccard
#              similarity of the collections at `set`
#   composite  sum of `weights[n] * components[n]` per scope item
AGGREGATE_KEYS: Dict[str, Set[str]] = {
    "each": {"mode", "where", "measure"},
    "ratio": {"mode", "over", "where", "match"},
    "count": {"mode", "over", "where"},
    "group": {"mode", "where", "key", "kind", "value", "member", "name", "guid"},
    "pairwise": {"mode", "where", "set"},
    "composite": {"mode", "where", "components", "weights"},
}
REQUIRED_AGGREGATE_KEYS: Dict[str, Tuple[str, ...]] = {
    "ratio": ("over", "match"),
    "count": ("over",),
    "group": ("key", "kind"),
    "pairwise": ("set",),
    "composite": ("components", "weights"),
}
GROUP_KINDS = ["duplicates", "divergence"]
GROUP_GUIDS = ["first", "none"]
# Modes that grade a measured value, so need `bands` (a fixed `severity` means nothing).
MODES_NEEDING_BANDS = {"ratio", "count", "pairwise", "composite"}
_FIELD_KEYS = ("measure", "value", "member", "set")

# Placeholders a message may use, per mode — supplied by engine/modes.py (a parity test
# holds the two together). `composite` adds one per component name. `each` also reads
# the item: `{obj.<path>}` is a field of the object itself, `{@name}` a derived field.
# In every mode `{name}` is the FINDING's object name, which is not always the object's
# own (an RLS rule reports its Table, a model table its alias): use `{obj.name}` for that.
MODE_PLACEHOLDERS: Dict[str, Set[str]] = {
    "each": {"name", "value", "obj"},
    "ratio": {"name", "value", "matched", "total", "pct", "unmatched_names", "matched_names"},
    "count": {"name", "value", "count", "total"},
    "group": {"name", "value", "key", "size", "members", "values"},
    "pairwise": {"name", "value", "a", "b", "similarity", "shared", "union"},
    "composite": {"name", "value", "score"},
}
LEGACY_THRESHOLD_PLACEHOLDERS = {"profile_label"}
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def known_derived_fields() -> Set[str]:
    """Names usable as `field: '@name'` — the engine's derived-field registry.

    Imported lazily so the catalog gate (tools/validate/check_audit_catalog.py) loads
    only `engine/fields.py` and `audit/rules.py`, never typer or requests.
    """
    from ts_cli.audit.engine.fields import FIELDS
    return set(FIELDS)


def _known(values) -> str:
    return ", ".join(values)


# ── field paths ─────────────────────────────────────────────────────────────

def field_path_problems(value: Any, path: str) -> List[str]:
    """`[parent.]*` then a dotted path, or a registered `@derived` name."""
    if not isinstance(value, str) or not value.strip("@"):
        return [f"{path}: must be a dotted path or '@derived' name"]
    rest = value
    while rest.startswith("parent."):
        rest = rest[len("parent."):]
    if not rest:
        return [f"{path}: '{value}' names no field after 'parent.'"]
    if any(step.startswith("@") for step in rest.split(".")[1:]):
        return [f"{path}: '{value}' — a derived '@name' must be the whole path "
                "(after any 'parent.'), not a step inside one"]
    if rest.startswith("@"):
        return derived_name_problems(rest, path)
    return []


def derived_name_problems(name: str, path: str) -> List[str]:
    """`@name` must be registered in engine/fields.py."""
    derived = known_derived_fields()
    if name[1:] in derived:
        return []
    return [f"{path}: unknown derived field '{name}' "
            f"(known: {_known(sorted('@' + d for d in derived))})"]


# ── predicate expressions (`where` / `match`) ───────────────────────────────

def _list_problems(value: Any, path: str, scope: Optional[str]) -> List[str]:
    if not isinstance(value, list) or not value:
        return [f"{path}: must be a non-empty list of expressions"]
    out: List[str] = []
    for i, sub in enumerate(value):
        out += expr_problems(sub, f"{path}[{i}]", scope)
    return out


def _scope_chain(scope: Optional[str]) -> List[str]:
    """`scope` and every scope enclosing it."""
    chain: List[str] = []
    while scope:
        chain.append(scope)
        scope = PARENT_SCOPE.get(scope)
    return chain


def _count_problems(value: Any, path: str, scope: Optional[str]) -> List[str]:
    """A counted scope must belong to the item (or an item enclosing it): counting a
    top-level or unrelated scope would silently count the whole context."""
    if value not in SCOPES:
        return [f"{path}: unknown scope '{value}' (known: {_known(SCOPES)})"]
    owner = PARENT_SCOPE.get(value)
    if owner is None:
        return [f"{path}: '{value}' is a top-level scope; count needs a child scope of the item"]
    if scope is not None and owner not in _scope_chain(scope):
        return [f"{path}: '{value}' items are not children of '{scope}' "
                "or of a scope enclosing it"]
    return []


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _compiles(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        re.compile(value)
    except re.error:
        return False
    return True


_NUMERIC_OPS = ("gt", "gte", "lt", "lte", "len_gt", "len_lt")
_BOOL_OPS = ("exists", "nonblank", "truthy")
_OPERAND_CHECKS: Dict[str, Tuple[Callable[[Any], bool], str]] = {
    "eq": (_is_scalar, "needs a single value (string, number, true/false or null)"),
    "in": (lambda v: isinstance(v, list) and all(_is_scalar(x) for x in v),
           "needs a list of single values"),
    "contains": (lambda v: v is not None and _is_scalar(v),
                 "needs a single string, number or true/false"),
    "regex": (_compiles, "does not compile as a regular expression"),
    "not_regex": (_compiles, "does not compile as a regular expression"),
    **{op: (_is_number, "needs a number") for op in _NUMERIC_OPS},
    **{op: (lambda v: isinstance(v, bool), "needs true or false") for op in _BOOL_OPS},
}


def _operand_problems(expr: dict, path: str) -> List[str]:
    out: List[str] = []
    for key, value in expr.items():
        check = _OPERAND_CHECKS.get(key)
        if check is not None and not check[0](value):
            out.append(f"{path}: '{key}' {check[1]} (got {value!r})")
    return out


_COMBINATOR_FORMS = ("all", "any", "not")


def _combinator_problems(expr: dict, path: str, scope: Optional[str]) -> List[str]:
    key = next(k for k in _COMBINATOR_FORMS if k in expr)
    others = sorted(map(str, set(expr) - {key}))
    if others:
        return [f"{path}: '{key}' must stand alone in its mapping (also found: "
                f"{_known(others)}) — wrap the siblings together in 'all'"]
    if key == "not":
        return expr_problems(expr[key], f"{path}.not", scope)
    return _list_problems(expr[key], f"{path}.{key}", scope)


def _stray_problems(expr: dict, path: str, subject: Optional[str]) -> List[str]:
    """Keys that do not belong in a `{field, ...}` / `{count, ...}` mapping."""
    allowed = set(LEAF_OPERATORS) | ({"count", "where"} if subject == "count" else {"field"})
    out: List[str] = []
    for k in expr:
        if k in allowed:
            continue
        if k in OPERATORS or k in ("field", "where"):
            out.append(f"{path}: '{k}' cannot be combined with '{subject or k}' in one mapping")
        else:
            out.append(f"{path}: unknown operator '{k}' (known: {_known(OPERATORS)})")
    return out


def _count_subject_problems(expr: dict, path: str, scope: Optional[str]) -> List[str]:
    out = _count_problems(expr["count"], f"{path}.count", scope)
    if "where" in expr:
        counted = expr["count"] if expr["count"] in SCOPES else None
        out += expr_problems(expr["where"], f"{path}.where", counted)
    return out


def _subject_problems(expr: dict, path: str, scope: Optional[str]) -> List[str]:
    """`{field, op...}` or `{count, [where], op...}`: one subject, at least one op."""
    subject = "count" if "count" in expr else "field" if "field" in expr else None
    out = _stray_problems(expr, path, subject)
    leaves = [k for k in expr if k in LEAF_OPERATORS]
    if subject is None:
        return out + ([f"{path}: '{leaves[0]}' needs a 'field' (or 'count') to compare"]
                      if leaves else [])
    if not leaves:
        out.append(f"{path}: '{subject}' given with no comparison operator")
    if subject == "field":
        out += field_path_problems(expr["field"], f"{path}.field")
    else:
        out += _count_subject_problems(expr, path, scope)
    return out + _operand_problems(expr, path)


def expr_problems(expr: Any, path: str, scope: Optional[str] = None) -> List[str]:
    """Problems in one `where`/`match` expression evaluated against items of `scope`
    (None = unknown, e.g. a code rule's block: the count-scope relation is unchecked)."""
    if not isinstance(expr, dict) or not expr:
        return [f"{path}: expected a non-empty mapping"]
    if any(k in expr for k in _COMBINATOR_FORMS):
        return _combinator_problems(expr, path, scope)
    return _subject_problems(expr, path, scope)


# ── aggregate ───────────────────────────────────────────────────────────────

def aggregate_problems(agg: dict, scope: str, implementation: str) -> List[str]:
    """Mode, the mode's allowed and required keys, and each key's value."""
    mode = agg.get("mode")
    out: List[str] = []
    if mode is None:
        if implementation == "declarative":
            out.append("aggregate.mode is required for a declarative rule")
    elif mode not in MODES:
        out.append(f"aggregate.mode: unknown mode '{mode}' (known: {_known(MODES)})")
    out += _key_problems(agg, mode)
    out += _over_problems(agg.get("over"), scope)
    out += _mode_value_problems(agg)
    item_scope = agg.get("over") if mode in ("ratio", "count") else scope
    item_scope = item_scope if item_scope in SCOPES else None
    for key in ("where", "match"):
        if key in agg:
            out += expr_problems(agg[key], f"aggregate.{key}", item_scope)
    return out


def _key_problems(agg: dict, mode: Any) -> List[str]:
    if mode in AGGREGATE_KEYS:
        allowed, label = AGGREGATE_KEYS[mode], f" for mode {mode}"
    else:  # a code rule's free-form block, or an unknown mode (already reported)
        allowed, label = set().union(*AGGREGATE_KEYS.values()), ""
    out = [f"aggregate: unknown key '{k}'{label} (known: {_known(sorted(allowed))})"
           for k in sorted(map(str, set(agg) - allowed))]
    for key in REQUIRED_AGGREGATE_KEYS.get(mode, ()):
        if key not in agg:
            hint = " (the children it measures)" if key == "over" else ""
            out.append(f"aggregate.{key} is required for mode {mode}{hint}")
    if mode == "group" and agg.get("kind") == "divergence" and "value" not in agg:
        out.append("aggregate.value is required for a divergence group")
    if mode == "group" and agg.get("kind") == "duplicates" and "value" in agg:
        out.append("aggregate.value is only used by kind divergence")
    return out


def _over_problems(over: Any, scope: str) -> List[str]:
    if over is None:
        return []
    if over not in SCOPES:
        return [f"aggregate.over: unknown scope '{over}' (known: {_known(SCOPES)})"]
    if scope in SCOPES and PARENT_SCOPE.get(over) != scope:
        return [f"aggregate.over: '{over}' items are not children of scope '{scope}'"]
    return []


def _mode_value_problems(agg: dict) -> List[str]:
    out: List[str] = []
    for key in _FIELD_KEYS:
        if key in agg:
            out += field_path_problems(agg[key], f"aggregate.{key}")
    if "key" in agg:
        out += _group_key_problems(agg["key"])
    if "kind" in agg and agg["kind"] not in GROUP_KINDS:
        out.append(f"aggregate.kind: unknown kind '{agg['kind']}' "
                   f"(known: {_known(GROUP_KINDS)})")
    if "guid" in agg and agg["guid"] not in GROUP_GUIDS:
        out.append(f"aggregate.guid: must be one of {_known(GROUP_GUIDS)}")
    if "name" in agg:
        out += placeholder_problems(agg["name"], MODE_PLACEHOLDERS["group"] - {"name"},
                                    "aggregate.name")
    return out + _composite_problems(agg)


def _group_key_problems(key: Any) -> List[str]:
    if isinstance(key, list):
        if not key:
            return ["aggregate.key: a composite key needs at least one path"]
        out: List[str] = []
        for i, part in enumerate(key):
            out += field_path_problems(part, f"aggregate.key[{i}]")
        return out
    return field_path_problems(key, "aggregate.key")


def _composite_problems(agg: dict) -> List[str]:
    if "components" not in agg and "weights" not in agg:
        return []
    comps, weights = agg.get("components"), agg.get("weights")
    if not isinstance(comps, dict) or not comps:
        return ["aggregate.components: must be a non-empty mapping of name -> field path"]
    out: List[str] = []
    for name, path in comps.items():
        if not isinstance(name, str) or not _IDENTIFIER.match(name) \
                or name in MODE_PLACEHOLDERS["composite"]:
            out.append(f"aggregate.components: '{name}' must be a placeholder-safe name "
                       f"other than {_known(sorted(MODE_PLACEHOLDERS['composite']))}")
        out += field_path_problems(path, f"aggregate.components.{name}")
    if not isinstance(weights, dict) or set(weights) != set(comps):
        return out + ["aggregate.weights: must give one number per component "
                      f"({_known(map(str, comps))})"]
    return out + [f"aggregate.weights.{n}: needs a number (got {w!r})"
                  for n, w in weights.items() if not _is_number(w)]


# ── messages and severity source ────────────────────────────────────────────

def placeholder_problems(template: Any, allowed: Optional[Set[str]], path: str,
                         derived: bool = False) -> List[str]:
    """`{name}` placeholders in a template: well-formed, and in `allowed` (None = any);
    with `derived`, `{@name}` placeholders naming a registered derived field too."""
    if not isinstance(template, str):
        return []
    try:
        parsed = list(string.Formatter().parse(template))
    except ValueError as exc:
        return [f"{path}: malformed template ({exc})"]
    out: List[str] = []
    for _text, fname, _spec, _conv in parsed:
        if fname is None:
            continue
        head = re.match(r"[^.\[]*", fname).group(0)
        if not head:
            out.append(f"{path}: placeholders must be named ('{{}}' is positional)")
        elif head.startswith("@") and derived:
            out += derived_name_problems(head, path)
        elif allowed is not None and head not in allowed:
            out.append(f"{path}: unknown placeholder '{head}' "
                       f"(known: {_known(sorted(allowed))})")
    return out


def message_placeholders(agg: dict) -> Optional[Set[str]]:
    """The placeholders a message under this aggregate may use (None = any)."""
    mode = agg.get("mode")
    if mode not in MODE_PLACEHOLDERS:
        return None
    allowed = set(MODE_PLACEHOLDERS[mode])
    if mode == "composite" and isinstance(agg.get("components"), dict):
        allowed |= {str(n) for n in agg["components"]}
    return allowed


def message_problems(template: Any, agg: dict, path: str) -> List[str]:
    """A rule message under this aggregate (an `each` message may name derived fields)."""
    return placeholder_problems(template, message_placeholders(agg), path,
                                derived=agg.get("mode") == "each")


def legacy_threshold_problems(value: Any, path: str) -> List[str]:
    """String values of a legacy threshold dict may use only `{profile_label}`."""
    if not isinstance(value, dict):
        return []
    out: List[str] = []
    for key, item in value.items():
        out += placeholder_problems(item, LEGACY_THRESHOLD_PLACEHOLDERS, f"{path}.{key}")
    return out


def severity_source_problems(agg: dict, has_bands: bool, has_severity: bool) -> List[str]:
    """Where a finding's severity comes from must exist for the mode.

    `has_bands` counts bands from the catalog or any profile.
    """
    mode = agg.get("mode")
    if mode in MODES_NEEDING_BANDS and not has_bands:
        return [f"bands are required for mode {mode} (it grades a measured value)"]
    if mode == "each" and has_bands and "measure" not in agg:
        return ["bands need aggregate.measure in mode each (the value they grade)"]
    if mode in ("each", "group") and not has_bands and not has_severity:
        return [f"mode {mode} needs a severity (or bands)"]
    return []
