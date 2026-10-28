"""checks.py — the validators CI's full-repo step runs on every pull request.

Before this file that list existed twice, by hand: CI's "Run validators
(full-repo mode)" step in `.github/workflows/validate.yml` and the `run_check`
calls in `scripts/pre-commit.sh`. Nothing compared them, so a validator could be
added to one and not the other, or run with different arguments, and nothing
would say so. A contributor checking locally before opening a PR had no list at
all to run.

It is not every check a PR must pass. `check_ci_gate_coverage.py` and
`check_audit_workflow_permissions.py` also run on every PR, each in its own CI
step, and are outside `CHECKS`; so are the PR-only steps below.

This module is data only. Each `Check` records:

- `ci_args` — the args CI runs the script with (`run_checks.py --context ci`
  passes them as-is; nothing else in the repo records them);
- `local_args` — the same with `origin/main` replaced by `{base}`, which a local
  runner substitutes with whatever upstream ref it resolved (a fork's `origin`
  is not upstream, so the ref cannot be hardcoded);
- `precommit_label` / `precommit_args` — the matching `run_check` in pre-commit,
  if there is one.

CI's full-repo and smoke steps run this list through `run_checks.py`;
`tools/validate/tests/test_checks_parity.py` pins each step to exactly that
call, and reads the committed pre-commit hook and fails on any line this list
does not account for. Where pre-commit deliberately differs from CI (usually
`--staged`, or no `--base` because the hook has no reliable `origin/main`), the
difference is declared in `KNOWN_DRIFT`;
`run_check` calls that are not CI full-repo checks are in `PRECOMMIT_ONLY`, and
validators the hook runs outside `run_check` are in `PRECOMMIT_UNMANAGED`. All
three carry a one-line reason, and the parity test rejects entries that have
gone stale.

PR-only CI steps (open-items, changelog, dependency-types, PR-range customer
references, PR size, the scoped quality-gates hard gate) are not listed here:
they need a PR's base ref and diff, so they are run explicitly where that exists.

Must import on Python 3.9 (the system interpreter): no runtime `X | Y` types.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class Check:
    id: str                      # stable slug, e.g. "version-sync"
    script: str                  # path under tools/validate/, e.g. "check_version_sync.py"
    ci_args: Tuple[str, ...]     # exactly as CI's full-repo step passes them
    local_args: Tuple[str, ...]  # what pr-ready passes; "{base}" is substituted
    hard: bool = True            # False only for soft checks such as the quality-gates catalog in CI
    optional_prereq: Optional[str] = None  # id understood by run_checks.prereq_present(); None = always required
    precommit_label: Optional[str] = None  # the run_check label in scripts/pre-commit.sh, if it runs there
    precommit_args: Optional[Tuple[str, ...]] = None


def _check(
    id: str,
    script: str,
    ci_args: Tuple[str, ...],
    precommit: Optional[Tuple[str, Tuple[str, ...]]] = None,
    *,
    hard: bool = True,
    optional_prereq: Optional[str] = None,
) -> Check:
    """Build a Check, deriving `local_args` from `ci_args` so the two cannot disagree
    except in the base ref."""
    label, pc_args = precommit if precommit else (None, None)
    return Check(
        id=id,
        script=script,
        ci_args=ci_args,
        local_args=tuple(a.replace("origin/main", "{base}") for a in ci_args),
        hard=hard,
        optional_prereq=optional_prereq,
        precommit_label=label,
        precommit_args=pc_args,
    )


_ROOT = ("--root", ".")
_STAGED = ("--root", ".", "--staged")
_BASE = ("--root", ".", "--base", "origin/main")

# The order run_checks.py runs them in, CI and locally alike.
CHECKS: Tuple[Check, ...] = (
    _check("secrets", "check_secrets.py", ("--root", ".", "--all"), ("secrets", _ROOT)),
    _check("customer-references", "check_customer_references.py", ("--root", ".", "--all"),
           ("customer references", _ROOT)),
    _check("references", "check_references.py", _ROOT, ("reference paths", _ROOT)),
    _check("patterns", "check_patterns.py", _ROOT, ("anti-patterns", _STAGED)),
    _check("version-sync", "check_version_sync.py", _BASE, ("version sync", _ROOT)),
    _check("module-health", "check_module_health.py", _ROOT, ("module health", _STAGED)),
    _check("python-redefinitions", "check_python_redefinitions.py", _ROOT,
           ("py redefinitions", _STAGED)),
    _check("file-size", "check_file_size.py", _ROOT, ("file size", _STAGED)),
    _check("yaml", "check_yaml.py", _ROOT, ("YAML blocks", _STAGED)),
    _check("sv-yaml", "check_sv_yaml.py", _ROOT, ("SV YAML structure", _STAGED)),
    _check("tml", "check_tml.py", _ROOT, ("TML structure", _STAGED)),
    _check("consistency", "check_consistency.py", _ROOT, ("consistency", _STAGED)),
    _check("skill-versions", "check_skill_versions.py", _ROOT, ("skill versions", _ROOT)),
    _check("smoke-tests", "check_smoke_tests.py", _ROOT, ("smoke tests", _STAGED)),
    _check("skill-naming", "check_skill_naming.py", _ROOT, ("skill naming", _ROOT)),
    _check("skill-context-cost", "check_skill_context_cost.py", _ROOT,
           ("skill context cost", _STAGED)),
    _check("runtime-coverage", "check_runtime_coverage.py", _ROOT, ("runtime coverage", _ROOT)),
    _check("open-items", "check_open_items.py", ("--root", ".", "--warn"),
           ("open items", ("--root", ".", "--warn"))),
    _check("coverage-matrix", "check_coverage_matrix.py", _BASE, ("coverage matrix", _ROOT)),
    _check("formula-catalog", "check_formula_catalog.py", _ROOT, ("formula catalog", _ROOT)),
    _check("converter-parity", "check_converter_parity.py", _ROOT, ("converter parity", _ROOT)),
    _check("mapping-code-sync", "check_mapping_code_sync.py", _ROOT, ("mapping/code sync", _ROOT)),
    _check("harness-routing", "check_harness_routing.py", _ROOT, ("harness routing", _ROOT)),
    _check("no-v1-endpoints", "check_no_v1_endpoints.py", _ROOT, ("no v1 endpoints", _ROOT)),
    _check("lint-invariant-list", "check_lint_invariant_list.py", _BASE,
           ("lint invariant list", _ROOT)),
    _check("no-inline-tml-gate", "check_no_inline_tml_gate.py", _ROOT, ("no inline tml gate", _ROOT)),
    _check("i7-gate", "check_i7_gate.py", _ROOT, ("i7 gate", _ROOT)),
    _check("open-item-citations", "check_open_item_citations.py", _ROOT,
           ("open-item citations", _ROOT)),
    _check("skill-cli-usage", "check_skill_cli_usage.py", _ROOT, ("no inline tml assembly", _ROOT)),
    _check("no-inline-requests", "check_no_inline_requests.py", _ROOT, ("no inline requests", _ROOT)),
    _check("pagination-convention", "check_pagination_convention.py", _ROOT,
           ("pagination convention", _ROOT)),
    _check("slash-command-refs", "check_slash_command_refs.py", _ROOT, ("slash-command refs", _ROOT)),
    _check("orphan-references", "check_orphan_references.py", _ROOT, ("orphan refs", _ROOT)),
    _check("skill-flag-usage", "check_skill_flag_usage.py", _ROOT, ("flag cross-check", _ROOT)),
    # Pre-commit runs this too, but outside run_check, as a soft `--staged || true`
    # staleness nudge; CI's `--check` is the hard presence gate.
    _check("mapping-currency", "check_mapping_currency.py", ("--root", ".", "--check")),
    # Cross-repo: needs an apache/ossie checkout. CI has none and the script reports
    # "skipping"; locally it is NOT RUN when the checkout is absent, never FAIL.
    _check("ossie-mapping-sync", "check_ossie_mapping_sync.py", ("--root", ".", "--check"),
           optional_prereq="ossie-checkout"),
    _check("open-items-index", "generate_open_items_index.py", ("--root", ".", "--check"),
           ("open items index", ("--root", ".", "--check"))),
    _check("agentql-offline", "generate_agentql_offline.py", ("--root", ".", "--check"),
           ("agentql offline bundle", ("--root", ".", "--check"))),
    _check("agentql-quest", "check_agentql_quest.py", _ROOT, ("agentql quest", _ROOT)),
    _check("mirror-sync", "check_mirror_sync.py", (), ("mirror sync", ())),
    _check("parity", "generate_parity.py", ("--check",), ("parity matrix", ("--check",))),
    _check("internal-imports", "check_internal_imports.py", _ROOT, ("internal imports", _ROOT)),
    _check("audit-catalog", "check_audit_catalog.py", _BASE,
           ("audit catalog", ("--root", ".", "--merge-base-with", "origin/main"))),
    _check("repo-hygiene", "check_repo_hygiene.py", _ROOT, ("repo hygiene", _ROOT)),
    _check("backlog-integrity", "check_backlog_integrity.py", _BASE, ("backlog integrity", _ROOT)),
    # Soft (`hard=False`: the runner prints WARN and the step still passes): the
    # catalog embeds git-log dates that move whenever any validator is touched. CI's
    # PR-only step makes it hard for PRs that touch its sources.
    _check("quality-gates", "generate_quality_gates.py", ("--root", ".", "--check"),
           ("quality gates catalog", ("--root", ".", "--check")), hard=False),
)

# The suites CI's "Run credential-free smoke suites" step runs: no credentials needed.
CI_SMOKES: Tuple[str, ...] = (
    "smoke_ts_publish_orgs",
    "smoke_ts_security_columns",
    "smoke_ts_setup_tenancy",
    "smoke_ts_migrate_orgs",
    "smoke_ts_object_model_alias",
    "smoke_ts_convert_from_dbt",
    "smoke_ts_convert_to_dbt",
)

# run_check calls in pre-commit.sh that are not CI full-repo checks: (label, reason).
PRECOMMIT_ONLY: Tuple[Tuple[str, str], ...] = (
    ("audit workflow perms", "CI runs it in its own step, not the full-repo step"),
    ("CI gate coverage", "CI runs it in its own step, not the full-repo step"),
    ("repo changelog", "CI runs it in the PR-only changelog gate step, against the PR's base"),
)

# Validators pre-commit invokes directly, not through run_check, so they get no
# PASS/FAIL line and mostly never block: (script, reason).
PRECOMMIT_UNMANAGED: Tuple[Tuple[str, str], ...] = (
    ("suggest_skill_version.py", "interactive SKILL.md version-bump suggester, not a check"),
    ("check_mapping_currency.py",
     "drift: pre-commit runs a soft `--staged || true` staleness nudge; CI runs `--check` as a hard presence gate"),
    ("suggest_dependency_types.py",
     "soft co-change nudge; CI runs `--check` in the PR-only dependency-types gate step"),
    ("suggest_repo_changelog.py",
     "interactive entry suggester; the gate is the `repo changelog` run_check (`--check`)"),
    ("check_audit_freshness.py", "soft nudge that an audit sweep is due; never blocks and CI does not run it"),
)

# Where pre-commit passes different args from CI, on purpose: (check id or pytest, reason).
_STAGED_ONLY = "pre-commit scopes to staged files; CI checks the whole tree"
_NO_BASE = "pre-commit has no reliable origin/main, so it skips the --base novelty rule CI applies"
KNOWN_DRIFT: Tuple[Tuple[str, str], ...] = (
    ("secrets", "pre-commit scans staged files; CI passes --all to scan every tracked file"),
    ("customer-references", "pre-commit scans staged content; CI passes --all to scan every tracked file"),
    ("patterns", _STAGED_ONLY),
    ("module-health", _STAGED_ONLY),
    ("python-redefinitions", _STAGED_ONLY),
    ("file-size", _STAGED_ONLY),
    ("yaml", _STAGED_ONLY),
    ("sv-yaml", _STAGED_ONLY),
    ("tml", _STAGED_ONLY),
    ("consistency", _STAGED_ONLY),
    ("smoke-tests", _STAGED_ONLY),
    ("skill-context-cost", _STAGED_ONLY),
    ("version-sync", _NO_BASE),
    ("coverage-matrix", _NO_BASE),
    ("lint-invariant-list", _NO_BASE),
    ("backlog-integrity", _NO_BASE),
    ("audit-catalog", "pre-commit uses --merge-base-with origin/main (offline, skipped if absent); CI uses --base origin/main"),
    ("pytest", "pre-commit's first pytest invocation omits tools/ossie-roundtrip/tests/, which CI runs"),
)
