"""Static check: each derived field, code rule and scope reads only the conditional data
it registers (`uses=` / `SCOPE_USES`).

The catalog gate trusts the registrations (catalog_uses.data_reads): a rule's
`requires ∪ uses` must cover what its scope, fields and code REGISTER. This module checks
the registrations against the code, without running it, so a read on a branch no example
reaches is still seen.

What counts as a read — detection, concretely:

  * The compiled code of the registered function, and of every function it reaches, is
    scanned for the attribute names below (`co_names`: every `x.<attr>` load, method or
    not). Compiled code rather than source text: lambdas (the child-scope iterators),
    comprehensions and nested functions come for free (nested code objects are walked),
    and no source has to be re-parsed under the gate's Python 3.9.
  * "Reaches": a name the code loads that resolves, in the function's module globals, to
    a function of the same module (its module-local helpers) or one defined in
    `ts_cli.audit` (e.g. `rules.*`); an
    attribute it loads off a `ts_cli.audit` module it references (`fields.get`,
    `scopes.iterate`); a derived field named by a string constant `"@name"` (how code
    reads one: `fields.get(item, "@is_coached", ctx)`); and a scope named by a string
    constant when the code also loads `iterate` (`scopes.iterate(ctx, "model.column")`)
    — its iterator and, for a child scope, its parent scope's.
  * Attribute -> data:
        ai_instructions -> ai_instructions
        answers         -> answers
        dependents      -> dependents AND sets
    Set discovery writes into `ctx.dependents` — SET rows under each Model's guid and
    each Set's consumer list under the Set's guid — so the content of any `dependents`
    read depends on whether `sets` was fetched. Whether a reader filters SET rows out
    (H4's `@dependent_count`) cannot be proven statically, so every reader declares
    both. Over-declaring costs at most a Set discovery a selection would otherwise skip;
    under-declaring is the silent failure this gate exists for.

Limits — what this does NOT see:

  * A read through `getattr(ctx, "answers")`, `vars(ctx)`, or any dynamic name.
  * A read inside a method of the context object (`ctx.column_types(...)`): `ctx` is a
    parameter, not a global, so its methods are not followed. Today none reads
    conditional data (AuditContext's methods read only Table TML); a new one that does
    is invisible here.
  * A function outside `ts_cli.audit`, or one reached only through a data structure (a
    dict of functions such as `scopes.AVAILABILITY`, which is reached only for declared
    `requires`).
  * It over-approximates: an `.answers` attribute on something other than the context
    counts as a read. A false positive fails loudly and is fixed by declaring.

The dynamic second layer (tests/test_audit_catalog_uses.py) runs every rule's examples
through a recording context; it sees only executed reads of context attributes and so
never `sets` on its own.

Kept importable on Python 3.9 with only the standard library; the registries are
imported lazily, as in catalog_uses.
"""
from __future__ import annotations

import types
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Set

ATTR_DATA: Dict[str, FrozenSet[str]] = {
    "ai_instructions": frozenset({"ai_instructions"}),
    "answers": frozenset({"answers"}),
    "dependents": frozenset({"dependents", "sets"}),
}
_PACKAGE = "ts_cli.audit"


def _in_package(obj: Any) -> bool:
    return (getattr(obj, "__module__", None) or getattr(obj, "__name__", "")).startswith(_PACKAGE)


class _Walker:
    def __init__(self, fields: Dict[str, Any], iterators: Dict[str, Any],
                 parents: Dict[str, str]):
        self.fields, self.iterators, self.parents = fields, iterators, parents
        self.seen: Set[int] = set()
        self.reads: Dict[str, str] = {}   # data -> "ctx.<attr> in <function>"

    def function(self, fn: Any) -> None:
        code = getattr(fn, "__code__", None)
        if code is not None and id(code) not in self.seen:
            self.seen.add(id(code))
            self.code(code, fn.__globals__, fn.__qualname__)

    def code(self, code: types.CodeType, globs: Dict[str, Any], where: str) -> None:
        names = set(code.co_names)
        for attr in names & set(ATTR_DATA):
            for data in ATTR_DATA[attr]:
                self.reads.setdefault(data, f"ctx.{attr} in {where}")
        for const in code.co_consts:
            if isinstance(const, types.CodeType):
                self.code(const, globs, where)
            elif isinstance(const, str):
                self._named(const, names)
        for name in names:
            self._reached(globs.get(name), names, globs)

    def _named(self, const: str, names: Set[str]) -> None:
        if const.startswith("@") and const[1:] in self.fields:
            self.function(self.fields[const[1:]])
        elif "iterate" in names and const in self.iterators:
            # A child scope iterated without a parent iterates its parent scope first.
            self.function(self.iterators[const])
            if const in self.parents:
                self.function(self.iterators[self.parents[const]])

    def _reached(self, obj: Any, names: Set[str], globs: Dict[str, Any]) -> None:
        if isinstance(obj, types.FunctionType) and (_in_package(obj) or obj.__globals__ is globs):
            self.function(obj)
        elif isinstance(obj, types.ModuleType) and _in_package(obj):
            for name in names:
                attr = getattr(obj, name, None)
                if isinstance(attr, types.FunctionType) and _in_package(attr):
                    self.function(attr)


def static_reads(fns: Iterable[Any]) -> Dict[str, str]:
    """Conditional data the functions `fns` (and what they reach) read -> where."""
    from ts_cli.audit.catalog_expr import PARENT_SCOPE
    from ts_cli.audit.engine.fields import FIELDS
    from ts_cli.audit.engine.scopes import ITERATORS
    walker = _Walker(FIELDS, ITERATORS, PARENT_SCOPE)
    for fn in fns:
        walker.function(fn)
    return walker.reads


def _undeclared(what: str, reads: Dict[str, str], declared: Iterable[str]) -> List[str]:
    return [f"{what} reads '{data}' ({where}) but does not register it — add it to "
            f"its uses" for data, where in sorted(reads.items()) if data not in set(declared)]


def _scope_problems(scope_uses: Dict[str, Any], iterators: Dict[str, Any],
                    parents: Dict[str, str]) -> List[str]:
    out = [f"engine/scopes.py: scope '{s}' is not in SCOPE_USES — register the "
           "conditional data it reads (frozenset() for none)"
           for s in sorted(set(iterators) - set(scope_uses))]
    for scope in sorted(set(iterators) & set(scope_uses)):
        reads = static_reads([iterators[scope]])
        parent: Optional[str] = parents.get(scope)
        if parent:  # a child's items come from iterating its parent scope
            reads.update({d: f"its parent scope '{parent}'"
                          for d in scope_uses.get(parent, ()) if d not in reads})
        out += _undeclared(f"engine/scopes.py: scope '{scope}'", reads, scope_uses[scope])
    return out


def registry_read_problems() -> List[str]:
    """Every registered field, code rule and scope whose code reads conditional data
    its registration does not declare (see the module docstring for what is seen)."""
    from ts_cli.audit.catalog_expr import PARENT_SCOPE
    from ts_cli.audit.engine.code_rules import CODE_USES, REGISTRY
    from ts_cli.audit.engine.fields import FIELD_USES, FIELDS
    from ts_cli.audit.engine.scopes import ITERATORS, SCOPE_USES
    out: List[str] = []
    for name in sorted(FIELDS):
        out += _undeclared(f"engine: derived field '@{name}'", static_reads([FIELDS[name]]),
                           FIELD_USES.get(name, ()))
    for name in sorted(REGISTRY):
        out += _undeclared(f"engine: code rule '{name}'", static_reads([REGISTRY[name]]),
                           CODE_USES.get(name, ()))
    return out + _scope_problems(SCOPE_USES, ITERATORS, PARENT_SCOPE)
