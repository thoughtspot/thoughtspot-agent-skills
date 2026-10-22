"""`uses:` and the data-read declarations (audit rule catalog).

`uses:` names conditional data a rule reads but must not be skipped for lacking — it is
fetched, never gates. Derived fields, code rules and scopes declare in their registries
which conditional data they read; the catalog gate fails a rule whose `requires ∪ uses`
does not cover what its scope, fields and code read. A recording context then checks
the registries themselves against what each rule actually touches.
"""
import copy

import pytest

import audit_rule_fixtures as fx
from ts_cli.audit.catalog_expr import CONDITIONAL_DATA
from ts_cli.audit.catalog_model import build_catalog, load_catalog, load_raw
from ts_cli.audit.catalog_uses import data_reads
from ts_cli.audit.catalog_validate import validate_catalog
from ts_cli.audit.engine import code_rules, fields, scopes
from ts_cli.audit.engine.run import run_rule


def _shipped_with(edit):
    raw = copy.deepcopy(load_raw())
    by_id = {r["id"]: r for f, rules in raw.items() if f.startswith("rules/") for r in rules}
    edit(by_id)
    return validate_catalog(build_catalog(raw), raw)


def test_shipped_catalog_is_valid_and_a5_declares_its_use():
    assert _shipped_with(lambda rules: None) == []
    assert load_catalog().rules["A5"].uses == ["ai_instructions"]


# ── the gate: requires ∪ uses must cover what a rule reads ──────────────────

def test_gate_fires_for_a5_without_uses():
    problems = _shipped_with(lambda rules: rules["A5"].pop("uses"))
    [p] = problems
    assert "A5" in p and "ai_instructions" in p and "code:spotter_readiness" in p


def test_gate_fires_for_a_derived_field_read_undeclared():
    """A3 reads @is_coached; dropping its `requires: ai_instructions` leaves it uncovered."""
    problems = _shipped_with(lambda rules: rules["A3"].update(requires=["model_tml"]))
    [p] = problems
    assert "A3" in p and "ai_instructions" in p and "@is_coached" in p


def test_gate_fires_for_a_scope_read_undeclared():
    problems = _shipped_with(lambda rules: rules["H7"].update(requires=[]))
    assert any("H7" in p and "answers" in p and "scope answer" in p for p in problems)


def test_gate_fires_for_h4_without_dependents():
    problems = _shipped_with(lambda rules: rules["H4"].update(requires=["model_tml"]))
    assert any("H4" in p and "dependents" in p and "@dependent_count" in p for p in problems)


def test_uses_covers_a_read_as_well_as_requires():
    def h4_uses_dependents(rules):
        rules["H4"].update(requires=["model_tml"], uses=["dependents", "sets"])
    assert _shipped_with(h4_uses_dependents) == []


def test_data_reads_names_each_source():
    reads = data_reads(load_catalog().rules["A5"])
    assert reads == {"ai_instructions": ["code:spotter_readiness"]}
    assert data_reads(load_catalog().rules["H5"]) == {
        "dependents": ["scope set", "@set_consumers"], "sets": ["scope set", "@set_consumers"]}


# ── the `uses` key itself ───────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["model_tml", "table_tml", "metadata"])
def test_uses_rejects_unconditional_data_and_says_why(value):
    problems = _shipped_with(lambda rules: rules["A5"].update(uses=["ai_instructions", value]))
    [p] = problems
    assert f"'{value}'" in p
    assert "fetched for every audit, so they are never declared in uses (uses takes:" in p


def test_uses_rejects_an_unknown_value():
    [p] = _shipped_with(lambda rules: rules["A5"].update(uses=["ai_instructions", "answer"]))
    assert "unknown uses value 'answer'" in p


def test_uses_rejects_what_requires_already_declares():
    [p] = _shipped_with(lambda rules: rules["A3"].update(uses=["ai_instructions"]))
    assert "A3" in p and "already in requires" in p


def test_a_profile_cannot_override_uses():
    problems = _shipped_with(
        lambda rules: rules["A5"].setdefault("profiles", {}).update(spotter={"uses": []}))
    assert any("profiles.spotter.uses is not overridable" in p for p in problems)


def test_uses_never_gates_an_item():
    """A5 still judges a Model with no ai/instructions entry (scored uncoached)."""
    from ts_cli.audit.context import make_context
    ctx = make_context(models=[{"guid": "m1", "model": {"name": "S", "columns": []}}])
    assert ctx.ai_instructions == {}
    rule = load_catalog().rules["A5"]
    assert [i["guid"] for i in scopes.available(ctx, rule)] == ["m1"]
    assert [f.object_guid for f in run_rule(ctx, load_catalog(), "A5", "general")] == ["m1"]


# ── the registries ──────────────────────────────────────────────────────────

def test_every_registered_field_and_code_rule_declares_its_uses():
    assert set(fields.FIELD_USES) == set(fields.FIELDS)
    assert set(code_rules.CODE_USES) == set(code_rules.REGISTRY)
    for declared in list(fields.FIELD_USES.values()) + list(code_rules.CODE_USES.values()):
        assert set(declared) <= set(CONDITIONAL_DATA)
    assert set(scopes.SCOPE_USES) == set(scopes.ITERATORS)


def test_register_requires_a_uses_declaration():
    with pytest.raises(ValueError, match="uses is required"):
        fields.register("t11_no_uses")
    with pytest.raises(ValueError, match="uses is required"):
        code_rules.code_rule("t11_no_uses", severity="bands")


def test_register_rejects_unconditional_or_unknown_uses():
    with pytest.raises(ValueError, match="uses"):
        fields.register("t11_bad", uses={"table_tml"})
    with pytest.raises(ValueError, match="uses"):
        code_rules.code_rule("t11_bad", severity="bands", uses={"answer"})
    assert "t11_bad" not in fields.FIELDS and "t11_bad" not in code_rules.REGISTRY


class _Recording:
    """An AuditContext stand-in that records which attributes are read."""

    def __init__(self, inner):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "read", set())

    def __getattr__(self, name):
        self.read.add(name)
        return getattr(self._inner, name)


def _examples():
    cat = load_catalog()
    for rule in cat.rules.values():
        if rule.status != "active":
            continue
        for kind, ex in rule.examples.items():
            yield pytest.param(rule.id, ex, id=f"{rule.id}-{kind}")


@pytest.mark.parametrize("rule_id,example", list(_examples()))
def test_a_rule_touches_no_conditional_data_it_does_not_declare(rule_id, example):
    """Second layer behind the static check (catalog_reads.py): the context attributes
    a rule's examples actually read when run must be within its `requires ∪ uses` and
    within what its registrations declare. It sees only the paths those two examples
    execute, and only context attributes — never `sets`, which lives inside
    `dependents` — so a branch-only or Set-only read is the static check's to catch."""
    cat = load_catalog()
    rule = cat.rules[rule_id]
    ctx = _Recording(getattr(fx, example["fixture"])())
    run_rule(ctx, cat, rule_id, example.get("profile") or "general")
    touched = ctx.read & set(CONDITIONAL_DATA)
    assert touched <= set(rule.requires) | set(rule.uses), (rule_id, touched)
    assert touched <= set(data_reads(rule)), (rule_id, touched, data_reads(rule))


# ── the static check of the registrations (catalog_reads.py) ────────────────

from types import SimpleNamespace

from ts_cli.audit.catalog_reads import registry_read_problems, static_reads


def test_shipped_registrations_declare_every_static_read():
    assert registry_read_problems() == []


def _branch_only(item, ctx):
    if item.get("never"):
        return len(ctx.answers)
    return 0


def _helper(ctx):
    return [d for rows in ctx.dependents.values() for d in rows]


def _via_helper(item, ctx):
    return _helper(ctx)


def _via_field_name(item, ctx):
    return fields.get(item, "@is_coached", ctx)


def _via_scope_name(item, ctx):
    return list(scopes.iterate(ctx, "answer.formula", parent=item))


@pytest.mark.parametrize("fn,expected", [
    (_branch_only, {"answers"}),
    (_via_helper, {"dependents", "sets"}),          # dependents always implies sets
    (_via_field_name, {"ai_instructions"}),
    (_via_scope_name, {"answers"}),
    (lambda item, ctx: item, set()),
])
def test_static_reads_follow_branches_helpers_fields_and_scopes(fn, expected):
    assert set(static_reads([fn])) == expected


def test_a_field_reading_undeclared_data_fails_the_gate(monkeypatch):
    monkeypatch.setitem(fields.FIELDS, "t11_reads", _branch_only)
    monkeypatch.setitem(fields.FIELD_USES, "t11_reads", frozenset())
    problems = registry_read_problems()
    assert problems == ["engine: derived field '@t11_reads' reads 'answers' (ctx.answers in "
                        "_branch_only) but does not register it — add it to its uses"]


def test_a_dependents_reader_must_declare_sets(monkeypatch):
    monkeypatch.setitem(code_rules.REGISTRY, "t11_deps", _via_helper)
    monkeypatch.setitem(code_rules.CODE_USES, "t11_deps", frozenset({"dependents"}))
    [p] = registry_read_problems()
    assert "code rule 't11_deps' reads 'sets'" in p


def test_an_unregistered_scope_fails_closed(monkeypatch):
    monkeypatch.delitem(scopes.SCOPE_USES, "set")
    assert any("scope 'set' is not in SCOPE_USES" in p for p in registry_read_problems())
    problems = _shipped_with(lambda rules: None)
    assert any("H5" in p and "scope 'set' is not registered" in p for p in problems)


def test_a_scope_reading_undeclared_data_fails(monkeypatch):
    monkeypatch.setitem(scopes.SCOPE_USES, "answer", frozenset())
    problems = registry_read_problems()
    assert any("scope 'answer' reads 'answers'" in p for p in problems)


# ── what the scan follows, and where it fails closed ───────────

import functools

from ts_cli.audit import catalog_reads
from ts_cli.audit.context import AuditContext


def _scan(fn):
    walker = catalog_reads._scan([fn])
    return set(walker.reads), walker.problems


@functools.lru_cache(maxsize=None)
def _cached_reader(ctx):
    return ctx.answers


def _deco(fn):
    @functools.wraps(fn)
    def inner(*a):
        return fn(*a)
    return inner


@_deco
def _wrapped_reader(ctx):
    return ctx.answers


class _Holder:
    @staticmethod
    def read(ctx):
        return ctx.answers

    @classmethod
    def read_cls(cls, ctx):
        return ctx.ai_instructions


_SCOPE_CONSTANT = "answer"


def _local_import_ok(item, ctx):
    from ts_cli.audit.context import nl_instructions
    return nl_instructions({})


def _local_import_missing(item, ctx):
    from ts_cli.audit.context import _no_such_helper  # noqa: F401


def _local_import_outside(item, ctx):
    from ts_cli.sets.discover import discover_sets  # noqa: F401


def _local_import_stdlib(item, ctx):
    import json  # noqa: F401
    return 0


@pytest.mark.parametrize("fn,expected", [
    (lambda item, ctx: _cached_reader(ctx), {"answers"}),           # lru_cache
    (lambda item, ctx: _wrapped_reader(ctx), {"answers"}),          # functools.wraps
    (lambda item, ctx: _Holder.read(ctx), {"answers"}),             # staticmethod
    (lambda item, ctx: _Holder.read_cls(ctx), {"ai_instructions"}),  # classmethod
    (lambda item, ctx: getattr(ctx, "dependents"), {"dependents", "sets"}),
    (lambda item, ctx: list(scopes.iterate(ctx, _SCOPE_CONSTANT)), {"answers"}),
    (_local_import_ok, set()),
    (_local_import_stdlib, set()),
])
def test_scan_follows_wrappers_members_getattr_constants_and_local_imports(fn, expected):
    reads, problems = _scan(fn)
    assert (reads, problems) == (expected, [])


@pytest.mark.parametrize("fn,message", [
    (_local_import_missing, "imports '_no_such_helper' from 'ts_cli.audit.context' inside "
                            "the function, which the scan cannot resolve"),
    (_local_import_outside, "imports 'discover_sets' from 'ts_cli.sets.discover' inside the "
                            "function, which the scan cannot follow"),
    (lambda item, ctx: list(scopes.iterate(ctx, item["scope"])),
     "calls iterate with a scope the scan cannot read"),
])
def test_scan_fails_closed_on_what_it_cannot_follow(fn, message):
    _, problems = _scan(fn)
    assert len(problems) == 1 and message in problems[0], problems


# ── the import reader across interpreter bytecode shapes ────────────────────
# Python 3.14 loads an import's `level` with LOAD_SMALL_INT where 3.9-3.13 use
# LOAD_CONST. Reading only LOAD_CONST made `from .context import helper` look absolute
# (so it was skipped as stdlib instead of failing the gate) and kept only the first name
# of `from m import a, b as o`. Both shapes are fed in here, so every interpreter checks
# both, whichever one runs the suite.

class _Ins:
    def __init__(self, opname, argval=None):
        self.opname, self.argval = opname, argval


def _body(level_load):
    """`from .context import helper; from m import a, b as o; import x.y as z`"""
    return [
        _Ins("RESUME", 0),
        _Ins(level_load, 1), _Ins("LOAD_CONST", ("helper",)), _Ins("IMPORT_NAME", "context"),
        _Ins("IMPORT_FROM", "helper"), _Ins("STORE_FAST", "helper"), _Ins("POP_TOP"),
        _Ins(level_load, 0), _Ins("LOAD_CONST", ("a", "b")), _Ins("IMPORT_NAME", "m"),
        _Ins("IMPORT_FROM", "a"), _Ins("STORE_FAST", "a"),
        _Ins("IMPORT_FROM", "b"), _Ins("STORE_FAST", "o"), _Ins("POP_TOP"),
        _Ins(level_load, 0), _Ins("LOAD_CONST", None), _Ins("IMPORT_NAME", "x.y"),
        _Ins("IMPORT_FROM", "y"), _Ins("STORE_FAST", "z"),
        _Ins("LOAD_CONST", None), _Ins("RETURN_VALUE"),
    ]


@pytest.mark.parametrize("level_load", ["LOAD_CONST", "LOAD_SMALL_INT"])
def test_imports_read_level_and_fromlist_on_every_bytecode_shape(level_load):
    from ts_cli.audit.catalog_reads import imports_in
    assert list(imports_in(_body(level_load))) == [
        ("context", 1, "helper", "helper"),
        ("m", 0, "a", "a"),
        ("m", 0, "b", "o"),
        ("x.y", 0, None, "z"),
    ]


def test_running_interpreter_reads_a_relative_local_import_as_relative():
    """The real bytecode of whatever interpreter runs the suite, not a synthesised one."""
    from ts_cli.audit.catalog_reads import _imports
    src = "def f():\n    from .context import helper\n    from m import a, b as o\n"
    fn = next(c for c in compile(src, "<probe>", "exec").co_consts if hasattr(c, "co_code"))
    assert list(_imports(fn)) == [("context", 1, "helper", "helper"),
                                  ("m", 0, "a", "a"), ("m", 0, "b", "o")]


# ── closures, partials, same-named defs ───────────────────────────

def _no_wraps(fn):
    """A decorator without functools.wraps: the registered function is `inner`, and
    what it runs is only in its closure."""
    def inner(*a):
        return fn(*a)
    return inner


@_no_wraps
def _closure_reader(ctx):
    return ctx.answers


def _partial_impl(ctx, attr):
    return ctx.ai_instructions


_partial_reader = functools.partial(_partial_impl, attr="x")


@pytest.mark.parametrize("fn,expected", [
    (_closure_reader, {"answers"}),                                  # closure, no wraps
    (lambda item, ctx: _closure_reader(ctx), {"answers"}),           # reached by name
    (_partial_reader, {"ai_instructions"}),                          # partial itself
    (lambda item, ctx: _partial_reader(ctx), {"ai_instructions"}),   # partial by name
])
def test_scan_follows_closures_and_partials(fn, expected):
    reads, problems = _scan(fn)
    assert (reads, problems) == (expected, [])


def test_compiled_view_keeps_every_same_named_top_level_def(tmp_path, monkeypatch):
    """`def f` twice at top level (one under `if`, say): the module runs whichever was
    bound last, which the scan cannot know — so it scans both."""
    pkg = tmp_path / "ts_cli" / "audit"
    pkg.mkdir(parents=True)
    (pkg / "t12_twice.py").write_text(
        "import sys\n"
        "if sys.version_info >= (3,):\n"
        "    def helper(ctx):\n"
        "        return ctx.answers\n"
        "else:\n"
        "    def helper(ctx):\n"
        "        return ctx.ai_instructions\n"
        "def helper2(ctx):\n"
        "    return ctx.answers\n"
        "def helper2(ctx):\n"
        "    return ctx.ai_instructions\n")
    import ts_cli.audit as audit_pkg
    monkeypatch.setattr(audit_pkg, "__path__", list(audit_pkg.__path__) + [str(pkg)])
    monkeypatch.setattr(catalog_reads, "_MODULES", {})
    compiled = catalog_reads._compile("ts_cli.audit.t12_twice")
    assert len(compiled.defs["helper2"]) == 2

    def reader(item, ctx):
        from ts_cli.audit.t12_twice import helper2
        return helper2(ctx)
    reads, problems = _scan(reader)
    assert (reads, problems) == ({"answers", "ai_instructions"}, [])


def test_importlib_is_a_documented_evasion():
    assert "importlib.import_module" in catalog_reads.__doc__


def test_context_methods_are_followed_by_name(monkeypatch):
    monkeypatch.setattr(AuditContext, "t11_probe", lambda self: self.answers, raising=False)
    reads, _ = _scan(lambda item, ctx: ctx.t11_probe())
    assert reads == {"answers"}


def test_a_module_the_gate_cannot_import_is_read_from_source():
    """context.py needs typer, so the gate compiles it without executing it. The
    compiled view must see what the runtime module defines."""
    import ts_cli.audit.context as runtime
    compiled = catalog_reads._compile("ts_cli.audit.context")
    assert {"nl_instructions", "join_key_ids", "build_context"} <= set(compiled.defs)
    assert "AuditContext" in compiled.classes
    assert {name for name, obj in vars(runtime).items()
            if getattr(obj, "__module__", None) == runtime.__name__
            and callable(obj) and not isinstance(obj, type)} <= set(compiled.defs)
    assert compiled.imports["parse_edoc"][0] == "ts_cli.commands.tml"
