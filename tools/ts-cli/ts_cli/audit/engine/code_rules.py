"""Code rules — catalog rules whose logic is Python rather than data.

A rule that no mode, operator or derived field can express (one that needs real logic,
not a clever expression) keeps its full catalog entry — id, categories, requires,
message, remediation, bands where they apply, legacy_threshold, examples — and names a
function here with `implementation: code:<name>`:

    @code_rule("model_width")
    def model_width(rule: Rule, ctx: AuditContext, profile: str) -> List[Finding]:
        ...

The contract (`run.run_rules` dispatches; `check_findings` enforces it):

    rule      the EFFECTIVE rule — the profile's overrides (bands, severity, message,
              remediation) already applied. Grade with `bands.classify(value,
              rule.bands)`, word with `rule.message`; never read the profile's block.
    ctx       the AuditContext. The runner does not apply `rule.requires` for a code
              rule (it never sees the items): skip an object whose required data the
              context lacks, as the modes do — `scopes.iterate(ctx, rule.scope)` and
              `all(scopes.has_data(item, ctx, r) for r in rule.requires)`.
    profile   the profile id. It is the profile — never read `ctx.assessment`, which a
              replayed snapshot carries from its capture.
    returns   a list of Finding, each with `check_id == rule.id` and a known severity.
              Leave `angle`, `categories`, `bands` and `threshold` at their defaults
              (`angle=""`): the runner stamps them exactly as it does for a declarative
              rule, so the two are indistinguishable in shape.

A rule that breaks the contract raises ValueError at run time; nothing is dropped.

Every registered rule is exercised by its catalog examples
(tests/test_audit_rule_examples.py), and the catalog gate rejects a `code:<name>`
that is not registered here.

Imports — read before adding one. The catalog gate (tools/validate/check_audit_catalog.py)
imports this module to learn the registered names, under the system Python 3.9 with
only PyYAML, without executing the `ts_cli` package __init__ (typer, requests). So a
module-level import here must stay within: catalog_model, catalog_validate,
catalog_expr, rules, findings, and engine.{fields, scopes, predicates, messages,
bands}. Anything else (context, commands, the legacy checks_* modules) is imported
inside the rule function. tools/validate/tests/test_check_audit_catalog.py copies
only the permitted modules and fails if this one needs more.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict, List

from ts_cli.audit.catalog_validate import CODE_IMPL, SEVERITIES
from ts_cli.audit.findings import Finding

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from ts_cli.audit.catalog_model import Rule

CodeRule = Callable[["Rule", Any, str], List[Finding]]

REGISTRY: Dict[str, CodeRule] = {}


def code_rule(name: str) -> Callable[[CodeRule], CodeRule]:
    """Register the decorated function as `implementation: code:<name>`."""
    if not isinstance(name, str) or not CODE_IMPL.match(f"code:{name}"):
        raise ValueError(f"'{name}' is not a valid code rule name "
                         "(lower case letters, digits and '_', not starting with a digit)")

    def register(fn: CodeRule) -> CodeRule:
        if name in REGISTRY:
            raise ValueError(f"code rule '{name}' is already registered "
                             f"({REGISTRY[name].__module__}.{REGISTRY[name].__qualname__})")
        REGISTRY[name] = fn
        return fn

    return register


def code_rule_name(implementation: str) -> str:
    """`code:<name>` -> `<name>`."""
    m = CODE_IMPL.match(implementation)
    if not m:
        raise ValueError(f"'{implementation}' is not 'code:<name>'")
    return m.group(1)


def run_code_rule(rule: "Rule", ctx: Any, profile: str) -> List[Finding]:
    """Call the rule's registered function and check what it returned."""
    name = code_rule_name(rule.implementation)
    fn = REGISTRY.get(name)
    if fn is None:
        raise KeyError(f"{rule.id}: no code rule registered as '{name}' "
                       f"(registered: {', '.join(sorted(REGISTRY)) or 'none'})")
    return check_findings(rule, fn(rule, ctx, profile))


def check_findings(rule: "Rule", found: Any) -> List[Finding]:
    """`found`, if it keeps the code-rule contract; ValueError naming the breach if not."""
    where = f"{rule.id} ({rule.implementation})"
    if not isinstance(found, list) or not all(isinstance(f, Finding) for f in found):
        raise ValueError(f"{where}: must return a list of Finding, got {found!r:.200}")
    for f in found:
        if f.check_id != rule.id:
            raise ValueError(f"{where}: returned a finding for '{f.check_id}'; "
                             f"a code rule reports only its own id")
        if f.severity not in SEVERITIES:
            raise ValueError(f"{where}: unknown severity '{f.severity}' "
                             f"(known: {', '.join(SEVERITIES)})")
    return found
