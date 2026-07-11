"""Unit tests for the pure plan-builder helpers in
tools/smoke-tests/smoke_ts_dependency_manager.py (audit finding 6.1).

`_build_remove_plan` and `_build_apply_change_plan` construct the plan JSON piped on
stdin to `ts dependency backup` / `apply-change` respectively. They are pure (no I/O,
no network) so they can be verified without a live ThoughtSpot instance — the smoke
test itself must not be run destructively outside an authorized live session.

The smoke test script lives in tools/smoke-tests/, not inside the `ts_cli` package
(smoke tests are standalone scripts — see `.claude/rules/ts-cli.md`), so this test
reaches outside `ts_cli/` for its subject the same way `test_vendor_mv_lib.py` reaches
into `agents/databricks/` and `test_worked_examples.py` reaches into `tools/validate/`.
"""
from __future__ import annotations

import sys
from pathlib import Path

_TS_CLI_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _TS_CLI_ROOT.parents[1]
sys.path.insert(0, str(_REPO_ROOT / "tools" / "smoke-tests"))

from smoke_ts_dependency_manager import (  # noqa: E402
    _build_apply_change_plan,
    _build_remove_plan,
)


class TestBuildRemovePlan:
    def test_defaults_are_empty_fix_delete_and_tmp_out_dir(self):
        source = {"guid": "src-1", "type": "MODEL", "name": "Orders Model"}
        plan = _build_remove_plan(source)
        assert plan == {
            "operation": "REMOVE",
            "source": source,
            "fix": [],
            "delete": [],
            "out_dir": "/tmp",
        }

    def test_includes_fix_and_delete_and_custom_out_dir_when_given(self):
        source = {"guid": "src-1", "type": "MODEL", "name": "Orders Model"}
        fix = [{"guid": "fix-1", "type": "ANSWER", "name": "Revenue by Region"}]
        delete = [{"guid": "del-1", "type": "LIVEBOARD", "name": "Old Board"}]
        plan = _build_remove_plan(source, fix=fix, delete=delete, out_dir="/custom/dir")
        assert plan["fix"] == fix
        assert plan["delete"] == delete
        assert plan["out_dir"] == "/custom/dir"

    def test_operation_is_always_remove(self):
        plan = _build_remove_plan({"guid": "g", "type": "MODEL", "name": "n"})
        assert plan["operation"] == "REMOVE"

    def test_fix_and_delete_lists_are_copied_not_aliased(self):
        fix = [{"guid": "fix-1", "type": "ANSWER", "name": "n"}]
        plan = _build_remove_plan({"guid": "g", "type": "MODEL", "name": "n"}, fix=fix)
        fix.append({"guid": "fix-2", "type": "ANSWER", "name": "n2"})
        assert len(plan["fix"]) == 1


class TestBuildApplyChangePlan:
    def test_shape_matches_apply_change_requirements(self):
        source = {"guid": "src-1", "type": "MODEL", "name": "Orders Model"}
        plan = _build_apply_change_plan(
            source=source,
            backup_dir="/tmp/ts_dep_backup_20260711_000000",
            columns_to_remove=["Legacy Column"],
        )
        assert plan["operation"] == "REMOVE"
        assert plan["backup_dir"] == "/tmp/ts_dep_backup_20260711_000000"
        assert plan["source"] == source
        assert plan["columns_to_remove"] == ["Legacy Column"]
        assert plan["fix"] == []
        assert plan["delete"] == []

    def test_columns_to_remove_is_a_list_copy(self):
        cols = ["A", "B"]
        plan = _build_apply_change_plan(
            source={"guid": "g", "type": "MODEL", "name": "n"},
            backup_dir="/tmp/x",
            columns_to_remove=cols,
        )
        cols.append("C")
        assert plan["columns_to_remove"] == ["A", "B"]

    def test_includes_fix_and_delete_when_given(self):
        fix = [{"guid": "fix-1", "type": "ANSWER", "name": "n"}]
        delete = [{"guid": "del-1", "type": "LIVEBOARD", "name": "n2"}]
        plan = _build_apply_change_plan(
            source={"guid": "g", "type": "MODEL", "name": "n"},
            backup_dir="/tmp/x",
            columns_to_remove=["Col"],
            fix=fix,
            delete=delete,
        )
        assert plan["fix"] == fix
        assert plan["delete"] == delete
