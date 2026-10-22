"""Tests for check_audit_catalog.py — the pre-commit/CI gate over the audit rule catalog.

Run as a subprocess: the gate imports the catalog modules without executing the
`ts_cli` package __init__ (which needs typer/requests), and doing that in-process
would leave stand-in `ts_cli` modules in sys.modules for the ts-cli tests that share
this pytest invocation in pre-commit.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "tools" / "validate" / "check_audit_catalog.py"
AUDIT_REL = Path("tools/ts-cli/ts_cli/audit")

BAD_RULE = """\
- id: A99
  title: A rule with a typo
  status: active
  categories: [A]
  scope: model.colum
  aggregate: {mode: ratio}
  examples:
    fires: {fixture: x, severity: HIGH}
    silent: {fixture: y}
"""


def _run(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), "--root", str(root)],
                          capture_output=True, text=True)


# What the gate may import: the catalog modules, and the engine's derived-field
# registry (catalog_expr.known_derived_fields) with the one module it needs. Nothing
# that pulls in typer or requests.
GATE_MODULES = ("catalog_model.py", "catalog_validate.py", "catalog_expr.py", "rules.py",
                "engine/__init__.py", "engine/fields.py")


def _copy_repo(tmp_path: Path) -> Path:
    """GATE_MODULES and the shipped catalog — nothing else of ts_cli."""
    root = tmp_path / "repo"
    dst = root / AUDIT_REL
    (dst / "engine").mkdir(parents=True)
    for name in GATE_MODULES:
        shutil.copy(REPO / AUDIT_REL / name, dst / name)
    shutil.copytree(REPO / AUDIT_REL / "catalog", dst / "catalog")
    return root


def test_real_repo_passes():
    res = _run(REPO)
    assert res.returncode == 0, res.stdout + res.stderr
    assert res.stdout.startswith("PASS  audit catalog:")
    assert "categories" in res.stdout


def test_bad_rule_fails_and_names_it(tmp_path):
    root = _copy_repo(tmp_path)
    (root / AUDIT_REL / "catalog" / "rules" / "ai.yaml").write_text(BAD_RULE)
    res = _run(root)
    assert res.returncode == 1
    assert res.stdout.startswith("FAIL")
    assert "rules/ai.yaml: A99:" in res.stdout and "model.colum" in res.stdout


def test_needs_only_the_catalog_modules(tmp_path):
    # No ts_cli/__init__.py, no other modules: the gate must still load the catalog.
    res = _run(_copy_repo(tmp_path))
    assert res.returncode == 0, res.stdout + res.stderr
    assert "0 rule(s), 5 categories" in res.stdout


GOOD_EACH_RULE = """\
- id: A99
  title: An indexed column
  categories: [A]
  scope: model.column
  aggregate: {mode: each, where: {field: "@is_indexed", truthy: true}}
  severity: LOW
  examples:
    fires: {fixture: x, severity: LOW}
    silent: {fixture: y}
"""


def test_derived_fields_checked_in_isolation(tmp_path):
    # The gate learns derived-field names from engine/fields.py without the rest of
    # ts_cli: a registered name passes, an unknown one fails by name.
    root = _copy_repo(tmp_path)
    rules = root / AUDIT_REL / "catalog" / "rules" / "ai.yaml"
    rules.write_text(GOOD_EACH_RULE)
    res = _run(root)
    assert res.returncode == 0, res.stdout + res.stderr
    rules.write_text(GOOD_EACH_RULE.replace("@is_indexed", "@is_indexd"))
    res = _run(root)
    assert res.returncode == 1 and "unknown derived field '@is_indexd'" in res.stdout
    assert "Traceback" not in res.stderr


def test_shape_error_is_a_fail_not_a_traceback(tmp_path):
    root = _copy_repo(tmp_path)
    (root / AUDIT_REL / "catalog" / "rules" / "ai.yaml").write_text("id: A1\n")
    res = _run(root)
    assert res.returncode == 1
    assert "Traceback" not in res.stderr
    assert "rules/ai.yaml" in res.stdout


def test_missing_catalog_fails(tmp_path):
    res = _run(tmp_path)
    assert res.returncode == 1
    assert "FAIL" in res.stdout
