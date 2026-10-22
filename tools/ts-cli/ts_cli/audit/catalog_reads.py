"""Static check: each derived field, code rule and scope reads only the conditional data
it registers (`uses=` / `SCOPE_USES`).

The catalog gate trusts the registrations (catalog_uses.data_reads): a rule's
`requires ∪ uses` must cover what its scope, fields and code REGISTER. This module checks
the registrations against the code, without running it, so a read on a branch no example
reaches is still seen.

What counts as a read — detection, concretely:

  * The compiled code of the registered function, and of everything it reaches, is
    scanned for the attribute names below (`co_names`: every `x.<attr>` load, method or
    not). Compiled code rather than source text: lambdas (the child-scope iterators),
    comprehensions and nested functions come for free (nested code objects are walked),
    and the gate's Python 3.9 needs no source re-parsed for a loaded module.
  * "Reaches" — each is followed and scanned the same way:
      - a name the code loads that resolves in the function's module globals to a
        function, or a class's member, of the same module or of `ts_cli.audit`
        (`rules.*`), or an attribute loaded off such a module (`fields.get`);
      - a FUNCTION-LOCAL import (`from ts_cli.audit.context import helper` inside the
        function — the engine's required style for modules the gate cannot import).
        The module is taken from `sys.modules` when really loaded, else its source is
        compiled WITHOUT executing it (`load_module`): context.py needs typer, which
        the gate's Python lacks, so the gate reads it this way. A local import that
        cannot be resolved — a module that cannot be found, a name not defined at its
        top level, a relative or star import, or a module of `ts_cli` outside
        `ts_cli.audit` — FAILS the gate. Stdlib and third-party local imports are not
        followed (they cannot touch the context's conditional attributes by name);
      - wrappers unwrapped: staticmethod/classmethod (`__func__`), the `__wrapped__`
        chain (`functools.wraps`, `lru_cache`) and `functools.partial` (`.func`) —
        wrapper and wrapped; and the function objects in a function's closure (a
        decorator without `functools.wraps` registers its inner function, which runs
        the decorated one only through its closure);
      - a derived field named by a string constant `"@name"`
        (`fields.get(item, "@is_coached", ctx)`);
      - a scope named to `iterate` by a string literal or a module-level string
        constant — its iterator and, for a child scope, its parent's. Any other scope
        argument (`iterate(ctx, rule.aggregate["over"])`) FAILS the gate outside
        engine/scopes.py itself; rule-driven scopes are the rule-level check's
        (catalog_uses), which holds a rule's scope to SCOPE_USES;
      - methods of the context class (`ts_cli.audit.context.AuditContext`) whose name
        the code loads (`ctx.column_types(...)`), by name, since `ctx` is a parameter.
  * `getattr(..., "<attr>")`: a string constant equal to an attribute below, in code
    that loads `getattr`, counts as that read.
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

Evasions — what this still does NOT see (each checked by a probe; the dynamic second
layer may catch an executed one):

  * A name computed at run time: `getattr(ctx, name)` with a non-literal `name`,
    `vars(ctx)` / `ctx.__dict__[...]`, `operator.attrgetter`, `eval`/`exec`.
  * A function reached only through a data structure — a dict or list of functions
    (`scopes.AVAILABILITY`, reached only for declared `requires`), a callable passed in
    as an argument or returned by another call.
  * Context methods reached other than by their own name on a context-class method
    (a subclass of the context, a method of another object holding the context).
  * In a module the gate can only compile (not import): a module-level name bound by
    anything but `def`/`class`/`import` (`helper = lru_cache()(impl)`) is not followed;
    a decorated `def` there is still seen (its body is scanned, the decorator is not).
    A name defined by more than one top-level `def` (under `if`/`else`, or redefined)
    has every one scanned, since the scan cannot know which the module binds.
  * A module imported by computed name — `importlib.import_module("ts_cli.audit.x")`,
    `__import__` — and anything reached through it: only `import` statements are read.
  * Code outside `ts_cli.audit` reached through a module-level (not function-local)
    import, e.g. `ts_cli.sets` from context.py.
  * It over-approximates: an `.answers` attribute on something other than the context,
    or a class member of the same name, counts as a read. A false positive fails loudly
    and is fixed by declaring.

The dynamic second layer (tests/test_audit_catalog_uses.py) runs every rule's examples
through a recording context; it sees only executed reads of context attributes and so
never `sets` on its own.

Kept importable on Python 3.9 with only the standard library; the registries are
imported lazily, as in catalog_uses.
"""
from __future__ import annotations

import dis
import functools
import importlib.util
import sys
import types
from typing import Any, Dict, FrozenSet, Iterable, Iterator, List, Optional, Set, Tuple

ATTR_DATA: Dict[str, FrozenSet[str]] = {
    "ai_instructions": frozenset({"ai_instructions"}),
    "answers": frozenset({"answers"}),
    "dependents": frozenset({"dependents", "sets"}),
}
_PACKAGE = "ts_cli.audit"
_SCOPES_MODULE = "ts_cli.audit.engine.scopes"
_CONTEXT = ("ts_cli.audit.context", "AuditContext")
_STORES = {"STORE_FAST", "STORE_NAME", "STORE_GLOBAL", "STORE_DEREF"}
_IS_FUNCTION = 0x2  # CO_NEWLOCALS: a def/lambda body, not a class body
# How an import's `level` and `fromlist` are loaded: LOAD_CONST through 3.13; 3.14
# loads a small int (the level) with LOAD_SMALL_INT.
_CONST_LOADS = {"LOAD_CONST", "LOAD_SMALL_INT"}
# Instructions that may sit inside one import statement (3.9 to 3.14 spellings).
_IMPORT_GLUE = {"POP_TOP", "ROT_TWO", "SWAP", "CACHE", "RESUME"} | _CONST_LOADS


def _in_package(module_name: Any) -> bool:
    return isinstance(module_name, str) and (
        module_name == _PACKAGE or module_name.startswith(_PACKAGE + "."))


# ── what a code object imports (function body or module top level) ─────────

class _ImportState:
    """One import statement being read instruction by instruction."""

    def __init__(self) -> None:
        self.consts: List[Any] = []
        self.current: Optional[Tuple[str, int, Any]] = None   # (module, level, fromlist)
        self.pending: Optional[str] = None

    def start(self, module: str) -> None:
        consts = self.consts
        level = consts[0] if len(consts) == 2 and isinstance(consts[0], int) else 0
        self.current = (module, level, consts[1] if len(consts) == 2 else None)
        self.pending = None

    def store(self, bound: str) -> Tuple[str, int, Optional[str], str]:
        module, level, fromlist = self.current  # type: ignore[misc]
        found = (module, level, self.pending if fromlist is not None else None, bound)
        self.pending = None
        if fromlist is None:  # `import a.b [as m]` binds once
            self.current = None
        return found


def _imports(code: types.CodeType) -> Iterator[Tuple[str, int, Optional[str], str]]:
    """(module, level, imported name — None when the module itself is bound, as by
    `import a.b` or `import a.b as m` — bound name), from the code's own instructions."""
    return imports_in(dis.get_instructions(code))


def imports_in(instructions: Iterable[Any]) -> Iterator[Tuple[str, int, Optional[str], str]]:
    """`_imports` over any instruction stream (anything with `opname` and `argval`), so
    a test can feed it the bytecode shape of an interpreter it is not running on."""
    st = _ImportState()
    for ins in instructions:
        op = ins.opname
        if op == "IMPORT_NAME":
            st.start(ins.argval)
        elif st.current is not None and op == "IMPORT_FROM":
            st.pending = ins.argval
        elif st.current is not None and op == "IMPORT_STAR":
            yield st.current[0], st.current[1], "*", "*"
            st.current = None
        elif st.current is not None and op in _STORES:
            yield st.store(ins.argval)
        elif op not in _IMPORT_GLUE:
            st.current = None
        st.consts = (st.consts + [ins.argval])[-2:] if op in _CONST_LOADS else []


class _Compiled:
    """A module's top level compiled from source WITHOUT executing it — how the scan
    reads a module the gate cannot import (context.py needs typer)."""

    def __init__(self, name: str, code: types.CodeType):
        self.name = name
        # Every top-level def of a name (one per `if` branch, or redefined): which the
        # module binds is decided at run time, so the scan reads them all.
        self.defs: Dict[str, List[types.CodeType]] = {}
        self.classes: Dict[str, types.CodeType] = {}
        for c in code.co_consts:
            if not isinstance(c, types.CodeType):
                continue
            if c.co_flags & _IS_FUNCTION:
                self.defs.setdefault(c.co_name, []).append(c)
            else:
                self.classes[c.co_name] = c
        self.imports = {bound: (mod, lvl, frm) for mod, lvl, frm, bound in _imports(code)}
        self.strings: Dict[str, str] = {}
        self.assigned: Set[str] = set()
        prev = None
        for ins in dis.get_instructions(code):
            if ins.opname == "STORE_NAME":
                self.assigned.add(ins.argval)
                if prev is not None and prev.opname == "LOAD_CONST" and isinstance(prev.argval, str):
                    self.strings[ins.argval] = prev.argval
            prev = ins

    def has(self, name: str) -> bool:
        return name in self.defs or name in self.classes or name in self.assigned


_MODULES: Dict[str, Any] = {}


def load_module(name: str) -> Any:
    """The runtime module if it is really loaded, else its source compiled (cached);
    None when it cannot be found."""
    mod = sys.modules.get(name)
    if mod is not None and getattr(mod, "__file__", None):
        return mod
    if name not in _MODULES:
        _MODULES[name] = _compile(name)
    return _MODULES[name]


def _compile(name: str) -> Optional[_Compiled]:
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError):
        return None
    if spec is None or not spec.origin or not spec.origin.endswith(".py"):
        return None
    with open(spec.origin, encoding="utf-8") as fh:
        return _Compiled(name, compile(fh.read(), spec.origin, "exec"))


# ── the walk ────────────────────────────────────────────────────────────────

def _unwrapped(obj: Any) -> List[Any]:
    """`obj` and what it wraps: staticmethod/classmethod, then the `__wrapped__` chain
    (functools.wraps, lru_cache)."""
    out: List[Any] = []
    while obj is not None and len(out) < 20:
        if isinstance(obj, (staticmethod, classmethod)):
            obj = obj.__func__
        out.append(obj)
        obj = obj.func if isinstance(obj, functools.partial) else \
            getattr(obj, "__wrapped__", None)
    return out


def _closure_functions(fn: types.FunctionType) -> List[Any]:
    """Function-like objects held in `fn`'s closure cells (an empty cell is skipped)."""
    out: List[Any] = []
    for cell in fn.__closure__ or ():
        try:
            value = cell.cell_contents
        except ValueError:
            continue
        if _callable_like(value):
            out.append(value)
    return out


def _owner_module(obj: Any) -> Any:
    """The module whose code `obj` runs: a wrapper's (a `partial` reports
    'functools') is its wrapped function's."""
    for o in _unwrapped(obj):
        if isinstance(o, types.FunctionType):
            return o.__module__
    return getattr(obj, "__module__", None)


def _callable_like(obj: Any) -> bool:
    return any(isinstance(o, types.FunctionType) for o in _unwrapped(obj))


class _Walker:
    def __init__(self, fields: Dict[str, Any], iterators: Dict[str, Any],
                 parents: Dict[str, str]):
        self.fields, self.iterators, self.parents = fields, iterators, parents
        self.seen: Set[int] = set()
        self.seen_functions: Set[int] = set()
        self.reads: Dict[str, str] = {}   # data -> "ctx.<attr> in <function>"
        self.problems: List[str] = []
        self.ctx_methods: Optional[Dict[str, Any]] = None

    # entry points
    def function(self, fn: Any) -> None:
        for obj in _unwrapped(fn):
            if not isinstance(obj, types.FunctionType) or id(obj) in self.seen_functions:
                continue
            self.seen_functions.add(id(obj))
            self.code(obj.__code__, _Runtime(obj.__globals__), obj.__qualname__)
            for inner in _closure_functions(obj):
                self.function(inner)

    def code(self, code: types.CodeType, where_: "Any", where: str) -> None:
        if id(code) in self.seen:
            return
        self.seen.add(id(code))
        names = set(code.co_names)
        self._attrs(code, names, where)
        named_scope = self._consts(code, names, where_, where)
        for module, level, frm, _ in _imports(code):
            self._local_import(module, level, frm, names, where)
        for name in sorted(names):
            for target in where_.targets(name, names):
                self._follow(target, where)
            named_scope |= self._scope_constant(where_.string(name), names)
        self._ctx_methods(names)
        if "iterate" in names and not named_scope and where_.module != _SCOPES_MODULE:
            self.problems.append(f"{where} calls iterate with a scope the scan cannot read "
                                 "(not a string literal or module constant)")

    # pieces
    def _attrs(self, code: types.CodeType, names: Set[str], where: str) -> None:
        for attr in names & set(ATTR_DATA):
            for data in ATTR_DATA[attr]:
                self.reads.setdefault(data, f"ctx.{attr} in {where}")
        if "getattr" in names:
            for const in code.co_consts:
                for data in ATTR_DATA.get(const, ()) if isinstance(const, str) else ():
                    self.reads.setdefault(data, f"getattr(ctx, '{const}') in {where}")

    def _consts(self, code: types.CodeType, names: Set[str], scope: Any, where: str) -> bool:
        named_scope = False
        for const in code.co_consts:
            if isinstance(const, types.CodeType):
                self.code(const, scope, where)
            elif isinstance(const, str):
                if const.startswith("@") and const[1:] in self.fields:
                    self.function(self.fields[const[1:]])
                named_scope |= self._scope_constant(const, names)
        return named_scope

    def _scope_constant(self, value: Optional[str], names: Set[str]) -> bool:
        if "iterate" not in names or value not in self.iterators:
            return False
        # A child scope iterated without a parent iterates its parent scope first.
        self.function(self.iterators[value])
        if value in self.parents:
            self.function(self.iterators[self.parents[value]])
        return True

    def _follow(self, target: Any, where: str) -> None:
        if isinstance(target, tuple):  # (code, scope, qualname) from a compiled module
            self.code(target[0], target[1], target[2])
        else:
            self.function(target)

    def _local_import(self, module: str, level: int, frm: Optional[str], names: Set[str],
                      where: str) -> None:
        if level == 0 and not module.startswith("ts_cli"):
            return  # stdlib / third party: outside the scan, like any non-package global
        what = f"{where} imports {frm or module!r} from {module!r}"
        if level or frm == "*" or not _in_package(module):
            self.problems.append(f"{what} inside the function, which the scan cannot "
                                 "follow (relative, star, or outside ts_cli.audit)")
            return
        loaded = load_module(module)
        targets = _module_targets(loaded, frm, names) if loaded is not None else None
        if targets is None:
            self.problems.append(f"{what} inside the function, which the scan cannot "
                                 "resolve")
            return
        for target in targets:
            self._follow(target, where)

    def _ctx_methods(self, names: Set[str]) -> None:
        """Methods of the context class named in the code (`ctx.column_types(...)`),
        by name — `ctx` is a parameter, so nothing else would lead to them."""
        if self.ctx_methods is None:
            loaded = load_module(_CONTEXT[0])
            self.ctx_methods = _class_members(loaded, _CONTEXT[1]) if loaded is not None else {}
            if loaded is None:
                self.problems.append(f"{_CONTEXT[0]} cannot be read, so methods of "
                                     f"{_CONTEXT[1]} cannot be scanned")
        for name in sorted(names & set(self.ctx_methods)):
            self._follow(self.ctx_methods[name], f"{_CONTEXT[1]}.{name}")


# ── resolving names to what they run ───────────────────────────────────────

class _Runtime:
    """Names resolved through a loaded module's globals."""

    def __init__(self, globs: Dict[str, Any]):
        self.globs = globs
        self.module = globs.get("__name__", "")

    def string(self, name: str) -> Optional[str]:
        value = self.globs.get(name)
        return value if isinstance(value, str) else None

    def targets(self, name: str, names: Set[str]) -> List[Any]:
        return _runtime_targets(self.globs.get(name), names, self.module)


def _runtime_targets(obj: Any, names: Set[str], module: str) -> List[Any]:
    owner = _owner_module(obj)
    if isinstance(obj, types.ModuleType):
        if not _in_package(obj.__name__):
            return []
        return [t for n in sorted(names) for t in
                _runtime_targets(getattr(obj, n, None), set(), obj.__name__)]
    if not (_in_package(owner) or owner == module):
        return []
    if isinstance(obj, type):
        return [m for n in sorted(names) for m in [vars(obj).get(n)] if _callable_like(m)]
    return [obj] if _callable_like(obj) else []


class _CompiledScope:
    """Names resolved through a module compiled from source (never executed)."""

    def __init__(self, mod: _Compiled):
        self.mod, self.module = mod, mod.name

    def string(self, name: str) -> Optional[str]:
        return self.mod.strings.get(name)

    def targets(self, name: str, names: Set[str]) -> List[Any]:
        return _compiled_targets(self.mod, name, names) or []


def _compiled_targets(mod: _Compiled, name: str, names: Set[str]) -> Optional[List[Any]]:
    """What `name` at `mod`'s top level runs; None if it is not defined there."""
    scope = _CompiledScope(mod)
    if name in mod.defs:
        return [(c, scope, f"{mod.name}.{name}") for c in mod.defs[name]]
    if name in mod.classes:
        return [(c, scope, f"{mod.name}.{name}.{c.co_name}")
                for c in mod.classes[name].co_consts
                if isinstance(c, types.CodeType) and c.co_name in names | {name}]
    if name in mod.imports:
        module, level, frm = mod.imports[name]
        if level or not _in_package(module):
            return []  # like a non-package global: not followed
        loaded = load_module(module)
        return (_module_targets(loaded, frm, names) or []) if loaded is not None else []
    return [] if name in mod.assigned else None


def _module_targets(loaded: Any, frm: Optional[str], names: Set[str]) -> Optional[List[Any]]:
    """What importing `frm` (None: the module itself) from `loaded` brings in that the
    code then runs; None when `frm` is not in the module."""
    if isinstance(loaded, _Compiled):
        if frm is None:
            return [t for n in sorted(names) for t in _compiled_targets(loaded, n, names) or []]
        return _compiled_targets(loaded, frm, names)
    if frm is None:
        return _runtime_targets(loaded, names, loaded.__name__)
    if not hasattr(loaded, frm):
        return None
    return _runtime_targets(getattr(loaded, frm), names | {frm}, loaded.__name__)


def _class_members(loaded: Any, cls: str) -> Dict[str, Any]:
    if isinstance(loaded, _Compiled):
        body = loaded.classes.get(cls)
        scope = _CompiledScope(loaded)
        return {c.co_name: (c, scope, f"{cls}.{c.co_name}") for c in
                (body.co_consts if body else ()) if isinstance(c, types.CodeType)}
    klass = getattr(loaded, cls, None)
    return {n: m for n, m in vars(klass).items() if _callable_like(m)} if klass else {}


# ── the checks ──────────────────────────────────────────────────────────────

def _scan(fns: Iterable[Any]) -> _Walker:
    from ts_cli.audit.catalog_expr import PARENT_SCOPE
    from ts_cli.audit.engine.fields import FIELDS
    from ts_cli.audit.engine.scopes import ITERATORS
    walker = _Walker(FIELDS, ITERATORS, PARENT_SCOPE)
    for fn in fns:
        walker.function(fn)
    return walker


def static_reads(fns: Iterable[Any]) -> Dict[str, str]:
    """Conditional data the functions `fns` (and what they reach) read -> where."""
    return _scan(fns).reads


def _registration_problems(what: str, fn: Any, declared: Iterable[str]) -> List[str]:
    walker = _scan([fn])
    out = [f"{what} reads '{data}' ({where}) but does not register it — add it to its "
           "uses" for data, where in sorted(walker.reads.items()) if data not in set(declared)]
    return out + [f"{what}: {p}" for p in walker.problems]


def _scope_problems(scope_uses: Dict[str, Any], iterators: Dict[str, Any],
                    parents: Dict[str, str]) -> List[str]:
    out = [f"engine/scopes.py: scope '{s}' is not in SCOPE_USES — register the "
           "conditional data it reads (frozenset() for none)"
           for s in sorted(set(iterators) - set(scope_uses))]
    for scope in sorted(set(iterators) & set(scope_uses)):
        parent: Optional[str] = parents.get(scope)
        missing = set(scope_uses.get(parent, ())) - set(scope_uses[scope]) if parent else set()
        out += [f"engine/scopes.py: scope '{scope}' reads '{d}' (its parent scope "
                f"'{parent}') but does not register it" for d in sorted(missing)]
        out += _registration_problems(f"engine/scopes.py: scope '{scope}'", iterators[scope],
                                      scope_uses[scope])
    return out


def registry_read_problems() -> List[str]:
    """Every registered field, code rule and scope whose code reads conditional data
    its registration does not declare, or that the scan cannot follow (see the module
    docstring for what is seen)."""
    from ts_cli.audit.catalog_expr import PARENT_SCOPE
    from ts_cli.audit.engine.code_rules import CODE_USES, REGISTRY
    from ts_cli.audit.engine.fields import FIELD_USES, FIELDS
    from ts_cli.audit.engine.scopes import ITERATORS, SCOPE_USES
    out: List[str] = []
    for name in sorted(FIELDS):
        out += _registration_problems(f"engine: derived field '@{name}'", FIELDS[name],
                                      FIELD_USES.get(name, ()))
    for name in sorted(REGISTRY):
        out += _registration_problems(f"engine: code rule '{name}'", REGISTRY[name],
                                      CODE_USES.get(name, ()))
    return out + _scope_problems(SCOPE_USES, ITERATORS, PARENT_SCOPE)
