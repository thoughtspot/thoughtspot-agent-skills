"""Unit tests for check_module_health — the complexity ratchet.

Builds a tiny throwaway tree, points the check's INCLUDE_ROOTS / BASELINE_PATH at
it, and exercises: clean pass, new-violation fail, baseline grandfathering, and
worsening fail. radon is a hard dependency of this check, so skip if unavailable.
"""
import json

import pytest

import check_module_health as mh

pytest.importorskip("radon")


def _complex_fn(name, branches):
    """Return source for a function whose cyclomatic complexity ~= branches+1."""
    lines = ["def %s(x):" % name]
    for i in range(branches):
        lines.append("    if x == %d:" % i)
        lines.append("        return %d" % i)
    lines.append("    return -1")
    return "\n".join(lines) + "\n"


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    pkg = tmp_path / "agents"
    pkg.mkdir()
    monkeypatch.setattr(mh, "INCLUDE_ROOTS", ["agents"])
    monkeypatch.setattr(mh, "BASELINE_PATH", str(tmp_path / "baseline.json"))
    monkeypatch.setattr(mh, "CAP", 5)  # low cap so small fixtures trip it
    return tmp_path, pkg


def _write_baseline(tmp_path, mapping):
    (tmp_path / "baseline.json").write_text(json.dumps(mapping))


def test_simple_code_passes(sandbox):
    tmp_path, pkg = sandbox
    (pkg / "a.py").write_text("def f(x):\n    return x + 1\n")
    assert mh.main(["--root", str(tmp_path)]) == 0


def test_new_complex_function_fails(sandbox):
    tmp_path, pkg = sandbox
    (pkg / "a.py").write_text(_complex_fn("big", 10))  # cc ~11 > CAP 5, not baselined
    assert mh.main(["--root", str(tmp_path)]) == 1


def test_baselined_function_is_grandfathered(sandbox):
    tmp_path, pkg = sandbox
    (pkg / "a.py").write_text(_complex_fn("big", 10))
    # discover its actual cc and baseline it
    key, cc = next(iter(mh._functions(str(tmp_path))))
    _write_baseline(tmp_path, {key: cc})
    assert mh.main(["--root", str(tmp_path)]) == 0


def test_worsened_baselined_function_fails(sandbox):
    tmp_path, pkg = sandbox
    (pkg / "a.py").write_text(_complex_fn("big", 10))
    key, cc = next(iter(mh._functions(str(tmp_path))))
    _write_baseline(tmp_path, {key: cc - 1})  # baseline recorded a lower cc → worsened
    assert mh.main(["--root", str(tmp_path)]) == 1


def test_update_baseline_roundtrips(sandbox):
    tmp_path, pkg = sandbox
    (pkg / "a.py").write_text(_complex_fn("big", 10))
    assert mh.main(["--root", str(tmp_path), "--update-baseline"]) == 0
    assert mh.main(["--root", str(tmp_path)]) == 0  # now grandfathered
