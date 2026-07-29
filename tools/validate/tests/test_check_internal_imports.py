"""Unit tests for check_internal_imports.py — the static `from ts_cli.X import Y`
resolver (audit finding 4.2 / 17.1).

Covers the pure resolution helpers directly against synthetic package trees (no need
for the real tools/ts-cli/ts_cli/ tree), plus a couple of subprocess-level main() tests
for exit-code wiring and the dated ALLOWLIST carve-out.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import check_internal_imports as cii

VALIDATE = Path(__file__).resolve().parents[1]


def _write(pkg_root: Path, rel: str, content: str) -> Path:
    f = pkg_root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
    return f


# --- resolve_module_file ----------------------------------------------------------

def test_resolve_module_file_package_root(tmp_path):
    pkg_root = tmp_path / "ts_cli"
    _write(pkg_root, "__init__.py", "")
    assert cii.resolve_module_file(pkg_root, "ts_cli") == pkg_root / "__init__.py"


def test_resolve_module_file_plain_module(tmp_path):
    pkg_root = tmp_path / "ts_cli"
    _write(pkg_root, "client.py", "X = 1\n")
    assert cii.resolve_module_file(pkg_root, "ts_cli.client") == pkg_root / "client.py"


def test_resolve_module_file_package(tmp_path):
    pkg_root = tmp_path / "ts_cli"
    _write(pkg_root, "migrate/__init__.py", "")
    assert (
        cii.resolve_module_file(pkg_root, "ts_cli.migrate")
        == pkg_root / "migrate" / "__init__.py"
    )


def test_resolve_module_file_nested(tmp_path):
    pkg_root = tmp_path / "ts_cli"
    _write(pkg_root, "migrate/apply_plan.py", "X = 1\n")
    assert (
        cii.resolve_module_file(pkg_root, "ts_cli.migrate.apply_plan")
        == pkg_root / "migrate" / "apply_plan.py"
    )


def test_resolve_module_file_missing(tmp_path):
    pkg_root = tmp_path / "ts_cli"
    pkg_root.mkdir()
    assert cii.resolve_module_file(pkg_root, "ts_cli.nope") is None


# --- submodule_exists --------------------------------------------------------------

def test_submodule_exists_as_file(tmp_path):
    pkg_root = tmp_path / "ts_cli"
    _write(pkg_root, "migrate/__init__.py", "")
    _write(pkg_root, "migrate/discover.py", "def f(): pass\n")
    assert cii.submodule_exists(pkg_root, "ts_cli.migrate", "discover")


def test_submodule_exists_as_subpackage(tmp_path):
    pkg_root = tmp_path / "ts_cli"
    _write(pkg_root, "migrate/__init__.py", "")
    _write(pkg_root, "migrate/sub/__init__.py", "")
    assert cii.submodule_exists(pkg_root, "ts_cli.migrate", "sub")


def test_submodule_exists_false_for_plain_module_target(tmp_path):
    # ts_cli.client is a plain .py file, not a package — no submodule concept applies.
    pkg_root = tmp_path / "ts_cli"
    _write(pkg_root, "client.py", "X = 1\n")
    assert not cii.submodule_exists(pkg_root, "ts_cli.client", "anything")


def test_submodule_exists_false_when_absent(tmp_path):
    pkg_root = tmp_path / "ts_cli"
    _write(pkg_root, "migrate/__init__.py", "")
    assert not cii.submodule_exists(pkg_root, "ts_cli.migrate", "nope")


# --- collect_bound_names -----------------------------------------------------------

def _names(src: str):
    import ast
    return cii.collect_bound_names(ast.parse(src).body)


def test_collect_bound_names_def_and_class():
    assert _names("def f():\n    pass\nclass C:\n    pass\n") == {"f", "C"}


def test_collect_bound_names_assignment_and_tuple_unpack():
    assert _names("X = 1\nY, Z = 2, 3\n") == {"X", "Y", "Z"}


def test_collect_bound_names_ann_assign_and_aug_assign():
    assert _names("X: int = 1\nX += 1\n") == {"X"}


def test_collect_bound_names_import_and_import_from():
    assert _names("import os\nimport os.path as osp\nfrom foo import bar, baz as qux\n") == {
        "os", "osp", "bar", "qux",
    }


def test_collect_bound_names_star_import_returns_none():
    assert _names("from foo import *\nX = 1\n") is None


def test_collect_bound_names_recurses_into_if_try():
    src = (
        "if True:\n"
        "    from a import b\n"
        "else:\n"
        "    b = 1\n"
        "try:\n"
        "    import c\n"
        "except ImportError:\n"
        "    c = None\n"
        "finally:\n"
        "    d = 1\n"
    )
    assert _names(src) == {"b", "c", "d"}


def test_collect_bound_names_does_not_enter_function_scope():
    # A name assigned INSIDE a function body is local to that function, not
    # module-level — must not leak into the module's bound-name set.
    src = "def f():\n    leaked = 1\n    return leaked\n"
    assert _names(src) == {"f"}


# --- _has_module_dunder_getattr -----------------------------------------------------

def _has_getattr(src: str) -> bool:
    import ast
    return cii._has_module_dunder_getattr(ast.parse(src).body)


def test_has_module_dunder_getattr_true():
    src = "def __getattr__(name):\n    raise AttributeError(name)\n"
    assert _has_getattr(src)


def test_has_module_dunder_getattr_false_when_absent():
    assert not _has_getattr("def f():\n    pass\n")


def test_has_module_dunder_getattr_inside_try():
    src = (
        "try:\n"
        "    def __getattr__(name):\n"
        "        raise AttributeError(name)\n"
        "except Exception:\n"
        "    pass\n"
    )
    assert _has_getattr(src)


def test_has_module_dunder_getattr_not_from_nested_function():
    # A __getattr__ defined INSIDE another function is a local, not the module's
    # PEP 562 hook — must not trigger the dynamic-namespace carve-out.
    src = "def outer():\n    def __getattr__(name):\n        return 1\n"
    assert not _has_getattr(src)


# --- scan_file (integration of the above) ------------------------------------------

def _mk_pkg(tmp_path) -> Path:
    pkg_root = tmp_path / "ts_cli"
    pkg_root.mkdir()
    (pkg_root / "__init__.py").write_text("", encoding="utf-8")
    return pkg_root


def test_scan_file_valid_direct_name(tmp_path):
    pkg_root = _mk_pkg(tmp_path)
    _write(pkg_root, "target.py", "def real_func():\n    pass\n")
    caller = _write(pkg_root, "caller.py", "from ts_cli.target import real_func\n")
    assert cii.scan_file(caller, pkg_root, {}) == []


def test_scan_file_valid_reexported_name(tmp_path):
    pkg_root = _mk_pkg(tmp_path)
    _write(pkg_root, "inner.py", "def helper():\n    pass\n")
    _write(pkg_root, "outer.py", "from ts_cli.inner import helper\n")
    caller = _write(pkg_root, "caller.py", "from ts_cli.outer import helper\n")
    assert cii.scan_file(caller, pkg_root, {}) == []


def test_scan_file_valid_submodule_import(tmp_path):
    pkg_root = _mk_pkg(tmp_path)
    _write(pkg_root, "migrate/__init__.py", "")
    _write(pkg_root, "migrate/discover.py", "def f():\n    pass\n")
    caller = _write(pkg_root, "caller.py", "from ts_cli.migrate import discover\n")
    assert cii.scan_file(caller, pkg_root, {}) == []


def test_scan_file_flags_missing_name(tmp_path):
    pkg_root = _mk_pkg(tmp_path)
    _write(pkg_root, "target.py", "def real_func():\n    pass\n")
    caller = _write(
        pkg_root, "caller.py", "from ts_cli.target import made_up_name\n"
    )
    hits = cii.scan_file(caller, pkg_root, {})
    assert len(hits) == 1
    assert hits[0].reason == "name-not-found"
    assert hits[0].name == "made_up_name"


def test_scan_file_flags_missing_module(tmp_path):
    pkg_root = _mk_pkg(tmp_path)
    caller = _write(pkg_root, "caller.py", "from ts_cli.nonexistent import x\n")
    hits = cii.scan_file(caller, pkg_root, {})
    assert len(hits) == 1
    assert hits[0].reason == "module-not-found"


def test_scan_file_catches_function_local_import(tmp_path):
    # The exact shape of the 17.1 bug: the broken import is buried inside a function
    # body (never executes at module load, so a runtime import-check would miss it).
    # scan_file uses ast.walk over the CALLER, which recurses into function bodies —
    # unlike collect_bound_names over the TARGET module, which deliberately does not.
    pkg_root = _mk_pkg(tmp_path)
    _write(pkg_root, "target.py", "REAL_CONST = 1\n")
    caller = _write(
        pkg_root, "caller.py",
        "def some_command():\n"
        "    from ts_cli.target import REAL_CONST, MADE_UP_CONST\n"
        "    return REAL_CONST\n",
    )
    hits = cii.scan_file(caller, pkg_root, {})
    assert len(hits) == 1
    assert hits[0].name == "MADE_UP_CONST"


def test_scan_file_ignores_relative_import(tmp_path):
    pkg_root = _mk_pkg(tmp_path)
    caller = _write(pkg_root, "caller.py", "from .sibling import whatever\n")
    assert cii.scan_file(caller, pkg_root, {}) == []


def test_scan_file_lenient_on_star_import_target(tmp_path):
    pkg_root = _mk_pkg(tmp_path)
    _write(pkg_root, "wild.py", "from os import *\n")
    caller = _write(pkg_root, "caller.py", "from ts_cli.wild import anything_at_all\n")
    assert cii.scan_file(caller, pkg_root, {}) == []


def test_scan_file_lenient_on_dunder_getattr_target(tmp_path):
    # Mirrors the real model_builder.py / build_blend_plan pattern.
    pkg_root = _mk_pkg(tmp_path)
    _write(
        pkg_root, "lazy.py",
        "def real_thing():\n    pass\n\n"
        "def __getattr__(name):\n"
        "    if name == 'synthesized':\n"
        "        return 1\n"
        "    raise AttributeError(name)\n",
    )
    caller = _write(pkg_root, "caller.py", "from ts_cli.lazy import synthesized\n")
    assert cii.scan_file(caller, pkg_root, {}) == []
    # A genuinely-defined name in the same module is unaffected — direct binding
    # is already in the collected set even though it's discarded for None below;
    # the point of this test is just that we don't false-flag EITHER name.
    caller2 = _write(pkg_root, "caller2.py", "from ts_cli.lazy import real_thing\n")
    assert cii.scan_file(caller2, pkg_root, {}) == []


def test_scan_file_ignores_star_alias_in_caller(tmp_path):
    pkg_root = _mk_pkg(tmp_path)
    _write(pkg_root, "target.py", "X = 1\n")
    caller = _write(pkg_root, "caller.py", "from ts_cli.target import *\n")
    assert cii.scan_file(caller, pkg_root, {}) == []


def test_scan_file_cache_is_reused_across_calls(tmp_path):
    pkg_root = _mk_pkg(tmp_path)
    _write(pkg_root, "target.py", "def real_func():\n    pass\n")
    caller_a = _write(pkg_root, "caller_a.py", "from ts_cli.target import real_func\n")
    caller_b = _write(pkg_root, "caller_b.py", "from ts_cli.target import real_func\n")
    cache: dict = {}
    assert cii.scan_file(caller_a, pkg_root, cache) == []
    assert "ts_cli.target" in cache
    assert cii.scan_file(caller_b, pkg_root, cache) == []


# --- main() end-to-end (exit codes + the dated ALLOWLIST carve-out) ----------------

def _run(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATE / "check_internal_imports.py"), "--root", str(root)],
        capture_output=True, text=True,
    )


def test_main_passes_on_clean_tree(tmp_path):
    pkg_root = tmp_path / "tools" / "ts-cli" / "ts_cli"
    _write(pkg_root, "__init__.py", "")
    _write(pkg_root, "target.py", "def real_func():\n    pass\n")
    _write(pkg_root, "caller.py", "from ts_cli.target import real_func\n")

    res = _run(tmp_path)
    assert res.returncode == 0, res.stdout + res.stderr


def test_main_fails_on_broken_import(tmp_path):
    pkg_root = tmp_path / "tools" / "ts-cli" / "ts_cli"
    _write(pkg_root, "__init__.py", "")
    _write(pkg_root, "target.py", "def real_func():\n    pass\n")
    _write(pkg_root, "caller.py", "from ts_cli.target import made_up\n")

    res = _run(tmp_path)
    assert res.returncode != 0, res.stdout + res.stderr
    assert "made_up" in res.stdout


def test_main_missing_scan_root_is_a_clean_pass(tmp_path):
    # No tools/ts-cli/ts_cli/ at all — nothing to check, not a failure.
    res = _run(tmp_path)
    assert res.returncode == 0, res.stdout + res.stderr


def test_the_retired_migrate_allowlist_entry_no_longer_suppresses(tmp_path):
    # Reconstructs the exact real-world shape the (since-removed) dated ALLOWLIST entry
    # targeted: tools/ts-cli/ts_cli/commands/migrate.py importing STEP_LIFT_CONTENT /
    # STEP_LIFT_SCAFFOLDING from ts_cli.migrate.apply_plan at line 496. The rollback
    # rework (audit 17.1, PR #404) fixed the real import, and the allowlist entry was
    # removed with it — so this exact shape must now be REPORTED. If someone re-adds
    # the entry, this fails and demands a fresh dated justification.
    pkg_root = tmp_path / "tools" / "ts-cli" / "ts_cli"
    _write(pkg_root, "__init__.py", "")
    _write(pkg_root, "migrate/__init__.py", "")
    _write(pkg_root, "migrate/apply_plan.py", "STEP_BACKUP = 'backup'\n")
    padding = "\n" * 495
    _write(
        pkg_root, "commands/migrate.py",
        padding + "from ts_cli.migrate.apply_plan import STEP_LIFT_CONTENT, STEP_LIFT_SCAFFOLDING\n",
    )

    res = _run(tmp_path)
    assert res.returncode == 1, res.stdout + res.stderr
    assert "STEP_LIFT_CONTENT" in res.stdout
