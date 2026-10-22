"""Tests for check_audit_catalog.py — the pre-commit/CI gate over the audit rule catalog.

Run as a subprocess: the gate imports the catalog modules without executing the
`ts_cli` package __init__ (which needs typer/requests), and doing that in-process
would leave stand-in `ts_cli` modules in sys.modules for the ts-cli tests that share
this pytest invocation in pre-commit.
"""
from __future__ import annotations

import copy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

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


# What the gate may import: the catalog modules, the engine's derived-field registry
# (catalog_expr.known_derived_fields) and code-rule registry
# (catalog_code.known_code_rules), and the modules those need. Nothing that pulls
# in typer or requests — a code rule importing more must do so inside its function.
GATE_MODULES = ("catalog_model.py", "catalog_validate.py", "catalog_expr.py",
                "catalog_code.py", "catalog_forms.py", "catalog_uses.py", "catalog_reads.py",
                "catalog_consistency.py", "engine/tml.py",
                "findings.py", "engine/__init__.py", "engine/fields.py",
                "engine/fields_data.py", "engine/fields_human.py",
                "engine/code_rules.py", "engine/code_rules_human.py", "engine/bands.py", "engine/scopes.py",
                "engine/predicates.py", "engine/messages.py", "engine/memo.py",
                "generate.py", "catalog_history.py",
                # Read as SOURCE, never imported (it needs typer): the read check follows
                # the engine's function-local imports of it (catalog_reads.load_module).
                "context.py")


def _copy_repo(tmp_path: Path, clear_rules: bool = False) -> Path:
    """GATE_MODULES and the shipped catalog — nothing else of ts_cli. With
    `clear_rules`, every shipped rule file is emptied, so a test counts only the
    rules it writes."""
    root = tmp_path / "repo"
    dst = root / AUDIT_REL
    (dst / "engine").mkdir(parents=True)
    for name in GATE_MODULES:
        shutil.copy(REPO / AUDIT_REL / name, dst / name)
    shutil.copytree(REPO / AUDIT_REL / "catalog", dst / "catalog")
    if clear_rules:
        for path in (dst / "catalog" / "rules").glob("*.yaml"):
            path.write_text("[]\n")
    return root


def _shipped_rule_count() -> int:
    rules_dir = REPO / AUDIT_REL / "catalog" / "rules"
    return sum(len(yaml.safe_load(p.read_text()) or []) for p in rules_dir.glob("*.yaml"))


def _shipped_category_count() -> int:
    return len(yaml.safe_load((REPO / AUDIT_REL / "catalog" / "categories.yaml").read_text()))


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
    assert f"{_shipped_rule_count()} rule(s), {_shipped_category_count()} categories" \
        in res.stdout


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


DOC_REL = Path("agents/cli/ts-audit/references/check-catalog.md")


def _with_doc(root: Path) -> Path:
    (root / DOC_REL).parent.mkdir(parents=True)
    shutil.copy(REPO / DOC_REL, root / DOC_REL)
    return root


def test_generated_doc_checked_under_the_gates_python(tmp_path):
    """The gate runs `generate --check` (catalog-only copies, with no skill dir, skip it)."""
    root = _with_doc(_copy_repo(tmp_path))
    res = _run(root)
    assert res.returncode == 0, res.stdout + res.stderr
    rules = root / AUDIT_REL / "catalog" / "rules" / "perf.yaml"
    rules.write_text(rules.read_text().replace("title: Column sprawl (>75 columns)",
                                               "title: Column sprawl (wide)"))
    res = _run(root)
    assert res.returncode == 1 and "check-catalog.md is stale" in res.stdout, res.stdout
    assert "Traceback" not in res.stderr


def test_missing_doc_fails_where_the_skill_exists(tmp_path):
    root = _with_doc(_copy_repo(tmp_path))
    (root / DOC_REL).unlink()
    res = _run(root)
    assert res.returncode == 1 and "check-catalog.md" in res.stdout, res.stdout


def test_missing_catalog_fails(tmp_path):
    res = _run(tmp_path)
    assert res.returncode == 1
    assert "FAIL" in res.stdout


CODE_RULE = """\
- id: D99
  title: A code rule
  categories: [D]
  scope: model
  implementation: code:{name}
  severity: LOW
  examples:
    fires: {{fixture: x, severity: LOW}}
    silent: {{fixture: y}}
"""

# Uses every module a code rule may import at module level (code_rules.py docstring),
# so a permitted module that stops being gate-safe fails here, under the gate's Python.
DEMO_REGISTRATION = """
from ts_cli.audit.engine import bands, fields, messages, predicates, scopes  # noqa


@code_rule("demo_rule", severity="severity", uses=(), label="graded in a demo")
def _demo_rule(rule, ctx, profile):
    return []
"""


def test_code_rule_names_checked_in_isolation(tmp_path):
    # The gate learns code-rule names from engine/code_rules.py without the rest of
    # ts_cli: an unregistered name fails by name, a registered one passes.
    root = _copy_repo(tmp_path, clear_rules=True)
    rules = root / AUDIT_REL / "catalog" / "rules" / "data.yaml"
    rules.write_text(CODE_RULE.format(name="demo_rule"))
    res = _run(root)
    assert res.returncode == 1 and "unknown code rule 'demo_rule'" in res.stdout
    assert "Traceback" not in res.stderr
    with (root / AUDIT_REL / "engine" / "code_rules.py").open("a") as fh:
        fh.write(DEMO_REGISTRATION)
    res = _run(root)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "1 rule(s)" in res.stdout


def test_shipped_code_rule_message_typo_fails(tmp_path):
    # The gate holds a code rule's message to the placeholders its function declares
    # (A5 renders only {score}); a typo there has no mode to catch it otherwise.
    root = _copy_repo(tmp_path)
    ai = root / AUDIT_REL / "catalog" / "rules" / "ai.yaml"
    text = ai.read_text()
    assert "{score:.0f}" in text
    ai.write_text(text.replace("{score:.0f}", "{scroe:.0f}"))
    res = _run(root)
    assert res.returncode == 1, res.stdout
    assert "A5: message: unknown placeholder 'scroe' (known: score)" in res.stdout
    assert "Traceback" not in res.stderr


def test_undeclared_conditional_read_fails(tmp_path):
    # The gate holds a rule's requires/uses to what its code reads, from the registries'
    # declarations: A5 reads ai_instructions (via @is_coached) and declares it in uses.
    root = _copy_repo(tmp_path)
    ai = root / AUDIT_REL / "catalog" / "rules" / "ai.yaml"
    text = ai.read_text()
    assert text.count("  uses: [ai_instructions]\n") == 1
    ai.write_text(text.replace("  uses: [ai_instructions]\n", ""))
    res = _run(root)
    assert res.returncode == 1, res.stdout
    assert "A5: reads 'ai_instructions' (via code:spotter_readiness)" in res.stdout
    assert "Traceback" not in res.stderr


# The fix-round-2 mutations: each must FAIL the gate (the static read check), not just a
# behaviour test. (a) a field reading Set rows only on a branch no example reaches;
# (b) H4's field counting every dependents row, declared {dependents} only; (c) a scope
# missing from SCOPE_USES.
@pytest.mark.parametrize("rel,old,new,expect", [
    ("engine/fields.py",
     "        table = ctx.tables.get(mt.get(\"fqn\", \"\"))\n        if not table:\n",
     "        table = ctx.tables.get(mt.get(\"fqn\", \"\"))\n        if not table:\n"
     "            _ = [d for d in ctx.dependents.get(item.get(\"guid\"), [])"
     " if d.get(\"type\") == \"SET\"]\n",
     "derived field '@owning_table_has_rls' reads 'dependents'"),
    ("engine/fields_human.py",
     "@register(\"dependent_count\", uses={\"dependents\", \"sets\"},",
     "@register(\"dependent_count\", uses={\"dependents\"},",
     "derived field '@dependent_count' reads 'sets'"),
    ("engine/scopes.py",
     "    \"set\": frozenset({\"dependents\", \"sets\"}),\n", "",
     "scope 'set' is not in SCOPE_USES"),
])
def test_read_declaration_mutations_fail_the_gate(tmp_path, rel, old, new, expect):
    root = _copy_repo(tmp_path)
    path = root / AUDIT_REL / rel
    text = path.read_text()
    assert text.count(old) == 1, old
    path.write_text(text.replace(old, new))
    res = _run(root)
    assert res.returncode == 1, res.stdout
    assert expect in res.stdout, res.stdout
    assert "Traceback" not in res.stderr


# Fix round 3: the re-review's round-2 probes, each a mutation that read conditional
# data past the scan. Every one must FAIL the gate, under the gate's own Python — which
# cannot import context.py and so reads it from source.
_IDX = ('@register("is_indexed", uses=(), values=(False, True),\n'
        '          label="the column is indexed for search")\n')
_IDX_BODY = '    """Column: text-search indexed (absent `index_type` means indexed by default)."""\n'
_D1 = '@code_rule("model_complexity"'
_D1_BODY = ('    """D1 — up to five findings per Model, one per measure over its MEDIUM line."""\n'
            '    out: List[Finding] = []\n    for item in scopes.available(ctx, rule):\n')


@pytest.mark.parametrize("edits,expect", [
    ([("context.py", None, "\n\ndef _probe_answers(ctx):\n    return ctx.answers\n"),
      ("engine/fields.py", _IDX_BODY, _IDX_BODY + "    from ts_cli.audit.context import "
                                                  "_probe_answers\n    _probe_answers(ctx)\n")],
     "'@is_indexed' reads 'answers' (ctx.answers in ts_cli.audit.context._probe_answers)"),
    ([("engine/fields.py", _IDX_BODY, _IDX_BODY + "    from ts_cli.audit.context import _nope\n")],
     "imports '_nope' from 'ts_cli.audit.context' inside the function, which the scan "
     "cannot resolve"),
    ([("engine/fields.py", _IDX, "import functools\n\n@functools.lru_cache(maxsize=None)\n"
       "def _probe(ctx):\n    return ctx.answers\n\n\n" + _IDX),
      ("engine/fields.py", _IDX_BODY, _IDX_BODY + "    _probe(ctx)\n")],
     "'@is_indexed' reads 'answers' (ctx.answers in _probe)"),
    ([("engine/fields.py", _IDX, "import functools\n\ndef _deco(fn):\n"
       "    @functools.wraps(fn)\n    def inner(*a):\n        return fn(*a)\n    return inner\n\n"
       "@_deco\ndef _probe(ctx):\n    return ctx.answers\n\n\n" + _IDX),
      ("engine/fields.py", _IDX_BODY, _IDX_BODY + "    _probe(ctx)\n")],
     "'@is_indexed' reads 'answers' (ctx.answers in _probe)"),
    ([("engine/fields.py", _IDX, "class _Probe:\n    @staticmethod\n    def read(ctx):\n"
       "        return ctx.answers\n\n\n" + _IDX),
      ("engine/fields.py", _IDX_BODY, _IDX_BODY + "    _Probe.read(ctx)\n")],
     "'@is_indexed' reads 'answers' (ctx.answers in _Probe.read)"),
    ([("engine/code_rules.py", _D1, "_PROBE_SCOPE = \"answer\"\n\n\n" + _D1),
      ("engine/code_rules.py", _D1_BODY, _D1_BODY.replace(
          "    for item", "    list(scopes.iterate(ctx, _PROBE_SCOPE))\n    for item", 1))],
     "code rule 'model_complexity' reads 'answers'"),
    ([("engine/code_rules.py", _D1_BODY, _D1_BODY.replace(
        "    for item", "    list(scopes.iterate(ctx, rule.id))\n    for item", 1))],
     "calls iterate with a scope the scan cannot read"),
    ([("engine/fields.py", _IDX_BODY, _IDX_BODY + "    getattr(ctx, \"answers\")\n")],
     "(getattr(ctx, 'answers') in _is_indexed)"),
    ([("context.py", "    def tables_for_model(self, model: dict) -> list:\n",
       "    def probe(self):\n        return self.answers\n\n"
       "    def tables_for_model(self, model: dict) -> list:\n"),
      ("engine/fields.py", _IDX_BODY, _IDX_BODY + "    ctx.probe()\n")],
     "(ctx.answers in AuditContext.probe)"),
    # task 12a: a decorator without functools.wraps, and functools.partial
    ([("engine/fields.py", _IDX, "def _deco(fn):\n    def inner(*a):\n"
       "        return fn(*a)\n    return inner\n\n"
       "@_deco\ndef _probe(ctx):\n    return ctx.answers\n\n\n" + _IDX),
      ("engine/fields.py", _IDX_BODY, _IDX_BODY + "    _probe(ctx)\n")],
     "'@is_indexed' reads 'answers' (ctx.answers in _probe)"),
    ([("engine/fields.py", _IDX, "import functools\n\ndef _impl(ctx, x):\n"
       "    return ctx.answers\n\n_probe = functools.partial(_impl, x=1)\n\n\n" + _IDX),
      ("engine/fields.py", _IDX_BODY, _IDX_BODY + "    _probe(ctx)\n")],
     "'@is_indexed' reads 'answers' (ctx.answers in _impl)"),
], ids=["local_import", "local_import_unresolvable", "lru_cache", "wraps", "staticmethod",
        "scope_constant", "scope_dynamic", "getattr", "context_method", "closure_no_wraps",
        "partial"])
def test_scan_evasion_probes_fail_the_gate(tmp_path, edits, expect):
    root = _copy_repo(tmp_path)
    for rel, old, new in edits:
        path = root / AUDIT_REL / rel
        text = path.read_text()
        if old is None:
            text += new
        else:
            assert text.count(old) == 1, old
            text = text.replace(old, new)
        path.write_text(text)
    res = _run(root)
    assert res.returncode == 1, res.stdout
    assert expect in res.stdout, res.stdout
    assert "Traceback" not in res.stderr


# ── rule-id history (--base <ref>) ──────────────────────────────────────────

def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                          text=True).stdout


def _git_repo(tmp_path: Path) -> Path:
    """A catalog-only repo copy with one commit, so HEAD is the base."""
    root = _copy_repo(tmp_path)
    _git(root, "init", "-q")
    _git(root, "-c", "user.email=t@example.com", "-c", "user.name=t", "add", ".")
    _git(root, "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-q", "-m", "base")
    return root


def _run_base(root: Path, ref: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), "--root", str(root), "--base", ref],
                          capture_output=True, text=True)


def _edit_rules(root: Path, name: str, edit) -> None:
    path = root / AUDIT_REL / "catalog" / "rules" / name
    rules = yaml.safe_load(path.read_text())
    path.write_text(yaml.safe_dump(edit(rules), sort_keys=False, allow_unicode=True))


def test_history_unchanged_catalog_passes(tmp_path):
    root = _git_repo(tmp_path)
    res = _run_base(root, "HEAD")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "rule ids vs HEAD" in res.stdout


def test_history_fails_when_a_rule_id_is_removed(tmp_path):
    root = _git_repo(tmp_path)
    _edit_rules(root, "perf.yaml", lambda rules: [r for r in rules if r["id"] != "P18"])
    res = _run_base(root, "HEAD")
    assert res.returncode == 1, res.stdout
    assert "P18: removed since HEAD" in res.stdout and "status: retired" in res.stdout


def test_history_allows_retiring_a_rule(tmp_path):
    root = _git_repo(tmp_path)

    def retire(rules):
        for r in rules:
            if r["id"] == "P18":
                r["status"] = "retired"
        return rules
    _edit_rules(root, "perf.yaml", retire)
    res = _run_base(root, "HEAD")
    assert res.returncode == 0 and "P18" not in res.stdout, res.stdout


def test_history_fails_when_a_retired_id_reappears_as_a_rule(tmp_path):
    root = _git_repo(tmp_path)

    def reuse_h6(rules):
        for r in rules:
            if r["id"] == "H6":
                r.update(status="active", title="Sets nobody can see")
        return rules
    _edit_rules(root, "human.yaml", reuse_h6)
    res = _run_base(root, "HEAD")
    assert res.returncode == 1, res.stdout
    assert "H6: retired at HEAD and active again under spotter, general (was 'Duplicate " \
           "sets', now 'Sets nobody can see')" in res.stdout


def test_history_moving_a_rule_between_files_is_not_a_removal(tmp_path):
    root = _git_repo(tmp_path)
    moved = {}

    def take(rules):
        moved["P18"] = next(r for r in rules if r["id"] == "P18")
        return [r for r in rules if r["id"] != "P18"]
    _edit_rules(root, "perf.yaml", take)
    _edit_rules(root, "security.yaml", lambda rules: rules + [moved["P18"]])
    res = _run_base(root, "HEAD")
    assert res.returncode == 0 and "removed since" not in res.stdout, res.stdout


def test_history_base_without_a_catalog_passes_with_a_note(tmp_path):
    root = _git_repo(tmp_path)
    (root / "README").write_text("x\n")
    _git(root, "-c", "user.email=t@example.com", "-c", "user.name=t", "add", "README")
    _git(root, "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-q", "-m", "second")
    empty_tree = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"  # git's well-known empty tree
    orphan = _git(root, "-c", "user.email=t@example.com", "-c", "user.name=t",
                  "commit-tree", empty_tree, "-m", "empty").strip()
    res = _run_base(root, orphan)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "no rule catalog at" in res.stdout


def test_history_unknown_ref_fails(tmp_path):
    root = _git_repo(tmp_path)
    res = _run_base(root, "no-such-ref")
    assert res.returncode == 1 and "cannot read" in res.stdout, res.stdout
    assert "Traceback" not in res.stderr


# ── review fix round 1: effective status per profile; merge-base base ───────

def _set_rule(root: Path, rid: str, **changes) -> None:
    def edit(rules):
        for r in rules:
            if r["id"] == rid:
                for k, v in changes.items():
                    if v is None:
                        r.pop(k, None)
                    else:
                        r[k] = v
        return rules
    _edit_rules(root, "perf.yaml", edit)


def _commit(root: Path, msg: str) -> str:
    _git(root, "-c", "user.email=t@example.com", "-c", "user.name=t", "add", "-A")
    _git(root, "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-q", "-m", msg)
    return _git(root, "rev-parse", "HEAD").strip()


def test_history_retired_rule_revived_through_profile_overrides_fails(tmp_path):
    """P18 retired (logic kept); then given a new title and revived under every profile
    through `profiles.<p>.status` — it runs again, so it is a reuse."""
    root = _git_repo(tmp_path)
    _set_rule(root, "P18", status="retired")
    _commit(root, "retire P18")
    _set_rule(root, "P18", title="Something else entirely",
              profiles={"general": {"status": "active"}, "spotter": {"status": "active"}})
    res = _run_base(root, "HEAD")
    assert res.returncode == 1, res.stdout
    assert "P18: retired at HEAD and active again under spotter, general" in res.stdout


def test_history_revival_under_one_profile_only_fails(tmp_path):
    root = _git_repo(tmp_path)
    _set_rule(root, "P18", status="retired")
    _commit(root, "retire P18")
    _set_rule(root, "P18", profiles={"spotter": {"status": "active"}})
    res = _run_base(root, "HEAD")
    assert res.returncode == 1 and "active again under spotter" in res.stdout, res.stdout


def test_history_promoting_a_profile_only_rule_is_not_a_reuse(tmp_path):
    """Base P18: retired in the catalog but active under spotter — it never stopped
    running. Making it active everywhere is a promotion, not a reuse."""
    root = _git_repo(tmp_path)
    _set_rule(root, "P18", status="retired", profiles={"spotter": {"status": "active"}})
    _commit(root, "P18 spotter-only")
    _set_rule(root, "P18", status="active", profiles=None)
    res = _run_base(root, "HEAD")
    assert "P18" not in res.stdout, res.stdout


def test_merge_base_lets_a_branch_drop_an_id_it_added(tmp_path):
    """An id added only on the branch never shipped: dropping it is fine against the
    merge base with origin/main (where HEAD would wrongly call it removed)."""
    root = _git_repo(tmp_path)
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    def add_p19(rules):
        p19 = copy.deepcopy(next(r for r in rules if r["id"] == "P18"))
        p19["id"] = "P19"
        return rules + [p19]
    _edit_rules(root, "perf.yaml", add_p19)
    _commit(root, "branch adds P19")
    _edit_rules(root, "perf.yaml", lambda rules: [r for r in rules if r["id"] != "P19"])
    assert _run_base(root, "HEAD").returncode == 1  # what the old pre-commit did
    res = subprocess.run([sys.executable, str(SCRIPT), "--root", str(root),
                          "--merge-base-with", "origin/main"], capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "rule ids vs" in res.stdout
    # an id that IS on origin/main still may not go
    _edit_rules(root, "perf.yaml", lambda rules: [r for r in rules if r["id"] != "P18"])
    res = subprocess.run([sys.executable, str(SCRIPT), "--root", str(root),
                          "--merge-base-with", "origin/main"], capture_output=True, text=True)
    assert res.returncode == 1 and "P18: removed since" in res.stdout, res.stdout


def test_merge_base_without_a_local_origin_main_skips_with_a_notice(tmp_path):
    root = _git_repo(tmp_path)
    _edit_rules(root, "perf.yaml", lambda rules: [r for r in rules if r["id"] != "P18"])
    res = subprocess.run([sys.executable, str(SCRIPT), "--root", str(root),
                          "--merge-base-with", "origin/main"], capture_output=True, text=True)
    assert res.returncode == 0, res.stdout
    assert "NOTE  audit catalog: rule-id history not checked — origin/main does not " \
           "exist locally" in res.stdout


def test_unreadable_ref_message_keeps_gits_error(tmp_path):
    root = _git_repo(tmp_path)
    res = _run_base(root, "no-such-ref")
    assert res.returncode == 1
    assert "['" not in res.stdout and "fatal" in res.stdout.lower(), res.stdout


# ── final review I3: a description left quoting a changed band value ────────

def _raise_a1_general(description=None):
    def edit(rules):
        for r in rules:
            if r["id"] == "A1":
                r.setdefault("profiles", {})["general"] = {
                    "bands": {"direction": "higher_is_better", "unit": "percent",
                              "levels": [{"op": "lt", "value": 30, "severity": "HIGH"},
                                         {"op": "lt", "value": 60, "severity": "MEDIUM"}]},
                    "legacy_threshold": {"green": 60, "assessment": "{profile_label}",
                                         "yellow": 30}}
                if description:
                    r["description"] = description
        return rules
    return edit


def test_history_fails_a_description_still_quoting_a_changed_band_value(tmp_path):
    """The review's walkthrough: A1 General 50 -> 60, legacy_threshold moved with it,
    the description still saying "General 50%"."""
    root = _git_repo(tmp_path)
    _edit_rules(root, "ai.yaml", _raise_a1_general())
    res = _run_base(root, "HEAD")
    assert res.returncode == 1, res.stdout
    assert "A1: its bands changed since HEAD, but its description still quotes 50" \
        in res.stdout, res.stdout


def test_history_passes_once_the_description_moves_with_the_bands(tmp_path):
    root = _git_repo(tmp_path)
    _edit_rules(root, "ai.yaml", _raise_a1_general(
        "Share of a Model's columns with a non-blank description, against the profile's "
        "pass mark (Spotter-ready 95%, General 60%)."))
    res = _run_base(root, "HEAD")
    assert res.returncode == 0, res.stdout + res.stderr
