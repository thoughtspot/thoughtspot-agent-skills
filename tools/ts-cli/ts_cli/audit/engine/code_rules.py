"""Code rules — catalog rules whose logic is Python rather than data.

A rule that no mode, operator or derived field can express (one that needs real logic,
not a clever expression) keeps its full catalog entry — id, categories, requires,
message, remediation, bands where they apply, legacy_threshold, examples — and names a
function here with `implementation: code:<name>`:

    @code_rule("model_width", placeholders={"count"}, severity="bands", uses=(),
               label="graded on the Model's column count")
    def model_width(rule: Rule, ctx: AuditContext, profile: str) -> List[Finding]:
        ...

The registration declares what the function reads from its catalog entry and emits, so
the catalog gate can hold the entry to it exactly as it holds a declarative rule to its
mode (catalog_code.code_rule_problems; a catalog mistake fails the gate, not the run):

    placeholders   the names it renders `rule.message` with — the rule's message and
                   every profile's are held to them
    severity       where a finding's severity comes from (required):
                     "bands"          graded by the rule's `bands` (A5)
                     "severity"       the catalog `severity`, a name or a mapping (D10)
                     "severity_name"  the catalog `severity`, a plain name only (D12:
                                      its findings are not about one item, so it has
                                      nothing to look a mapping up on)
                     {"HIGH", ...}    fixed in the function: these severities (D1, D2)
                   It fixes which severities the rule can emit (a by-severity message
                   must word each, and only those) and which of `bands` / `severity`
                   the entry must — and must not — carry.
    own_threshold  True when it sets each finding's legacy threshold itself (D1); the
                   entry must then carry no `legacy_threshold`
    label          (required) how the grading reads to an audit reader — generated
                   text shows it, never `code:<name>`: "graded per join, on its key
                   types and key count"
    uses           (required) the conditional data (catalog_expr.CONDITIONAL_DATA) it
                   reads from the context, through a derived field included — `()` for
                   none. The gate fails an entry whose `requires`/`uses` do not cover
                   it (catalog_uses.py): A5 reads `ai_instructions` via `@is_coached`

The contract (`run.run_rules` dispatches; `check_findings` enforces it):

    rule      the EFFECTIVE rule — the profile's overrides (bands, severity, message,
              remediation) already applied. Grade with `bands.classify(value,
              rule.bands)`, word with `rule.message`; never read the profile's block.
    ctx       the AuditContext. The runner does not apply `rule.requires` for a code
              rule (it never sees the items): iterate with `scopes.available(ctx,
              rule)`, which yields only the scope's objects whose required data the
              context holds — the same filter the modes use.
    profile   the profile id. It is the profile — never read `ctx.assessment`, which a
              replayed snapshot carries from its capture.
    returns   a list of Finding, each with `check_id == rule.id` and a known severity.
              Word it with `messages.template(rule, severity)` — the rule's message,
              or its `by_severity` entry for that finding. Leave `angle`,
              `categories`, `bands` and `threshold` at their defaults (`angle=""`):
              the runner stamps them exactly as it does for a declarative rule, so the
              two are indistinguishable in shape. One exception: a rule whose legacy
              threshold varies per finding in a way the catalog cannot say (D1's, one
              per measure) declares `own_threshold=True` and sets `threshold` itself;
              its catalog entry then has no `legacy_threshold` (the gate rejects
              both, and so does the runner).

A rule that breaks the contract raises ValueError at run time; nothing is dropped.

Every registered rule is exercised by its catalog examples
(tests/test_audit_rule_examples.py), and the catalog gate rejects a `code:<name>`
that is not registered here.

Imports — read before adding one. The catalog gate (tools/validate/check_audit_catalog.py)
imports this module to learn the registered names, under the system Python 3.9 with
only PyYAML, without executing the `ts_cli` package __init__ (typer, requests). So a
module-level import here must stay within: catalog_model, catalog_validate (and
catalog_expr, catalog_code, catalog_forms, catalog_uses, catalog_reads,
catalog_consistency, which it
imports), findings, and
engine.{tml, fields (and fields_data / fields_human, which it imports), scopes, predicates,
messages, bands} — and code_rules_human, imported at the end of this module, holds to
the same list. Anything else (context, commands) is imported
inside the rule function. tools/validate/tests/test_check_audit_catalog.py copies
only the permitted modules and fails if this one needs more.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Callable, Dict, FrozenSet, Iterable, List, Set

from ts_cli.audit.engine import tml
from ts_cli.audit.catalog_validate import CODE_IMPL, SEVERITIES
from ts_cli.audit.engine import bands, fields, scopes
from ts_cli.audit.engine.messages import render, template
from ts_cli.audit.findings import Finding

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from ts_cli.audit.catalog_model import Rule

CodeRule = Callable[["Rule", Any, str], List[Finding]]

REGISTRY: Dict[str, CodeRule] = {}
# name -> what the function declared at registration (see the module docstring).
PLACEHOLDERS: Dict[str, FrozenSet[str]] = {}
SEVERITY_SOURCES: Dict[str, Any] = {}   # "bands" | "severity" | "severity_name" | frozenset
OWN_THRESHOLD: Set[str] = set()
CODE_USES: Dict[str, FrozenSet[str]] = {}   # conditional data it reads (catalog_uses.py)
CODE_LABELS: Dict[str, str] = {}   # how its grading reads in generated text
CATALOG_SEVERITY_SOURCES = ("bands", "severity", "severity_name")
_PLACEHOLDER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _severity_source(name: str, severity: Any) -> Any:
    """The declared severity source, checked: a catalog source, or a fixed set."""
    if isinstance(severity, str):
        if severity in CATALOG_SEVERITY_SOURCES:
            return severity
    elif severity is not None:
        fixed = frozenset(severity)
        if fixed and fixed <= set(SEVERITIES):
            return fixed
    raise ValueError(f"code rule '{name}': severity must be one of "
                     f"{', '.join(CATALOG_SEVERITY_SOURCES)} or a collection of severities "
                     f"({', '.join(SEVERITIES)}), got {severity!r}")


def code_rule(name: str, placeholders: Iterable[str] = (), *, severity: Any = None,
              uses: Any = None, own_threshold: bool = False, label: Any = None
              ) -> Callable[[CodeRule], CodeRule]:
    """Register the decorated function as `implementation: code:<name>`, rendering its
    message with `placeholders`, its severity from `severity`, reading the conditional
    data `uses` from the context (itself or through a derived field), and — with
    `own_threshold` — setting each finding's legacy threshold itself; `label` is how its
    grading reads to an audit reader."""
    if not isinstance(name, str) or not CODE_IMPL.match(f"code:{name}"):
        raise ValueError(f"'{name}' is not a valid code rule name "
                         "(lower case letters, digits and '_', not starting with a digit)")
    if isinstance(placeholders, str) or \
            not all(isinstance(p, str) and _PLACEHOLDER.match(p) for p in placeholders):
        raise ValueError(f"code rule '{name}': placeholders must be a collection of "
                         f"names, got {placeholders!r}")
    if not isinstance(own_threshold, bool):
        raise ValueError(f"code rule '{name}': own_threshold must be true or false")
    declared = frozenset(placeholders)
    source = _severity_source(name, severity)
    data = fields._declared_uses(f"code rule '{name}'", uses)
    text = fields.human_label(f"code rule '{name}'", label)

    def register(fn: CodeRule) -> CodeRule:
        if name in REGISTRY:
            raise ValueError(f"code rule '{name}' is already registered "
                             f"({REGISTRY[name].__module__}.{REGISTRY[name].__qualname__})")
        REGISTRY[name] = fn
        PLACEHOLDERS[name] = declared
        SEVERITY_SOURCES[name] = source
        CODE_USES[name] = data
        CODE_LABELS[name] = text
        if own_threshold:
            OWN_THRESHOLD.add(name)
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
        _check_declared(rule, f, where)
    return found


def _check_declared(rule: "Rule", f: Finding, where: str) -> None:
    """Run-time backstop for what the registration declared (the gate checks the
    catalog side): a fixed severity outside the set, an undeclared own threshold."""
    name = code_rule_name(rule.implementation)
    source = SEVERITY_SOURCES.get(name)
    if isinstance(source, frozenset) and f.severity not in source:
        raise ValueError(f"{where}: emitted {f.severity}, outside its declared "
                         f"severities ({', '.join(sorted(source))})")
    if f.threshold is not None and name not in OWN_THRESHOLD:
        raise ValueError(f"{where}: set a finding's threshold without declaring "
                         "own_threshold=True")
    if f.threshold is not None and _declares_legacy_threshold(rule):
        raise ValueError(f"{where}: set a finding's threshold although the catalog "
                         "entry declares legacy_threshold — one source, not both")


def _declares_legacy_threshold(rule: "Rule") -> bool:
    return rule.legacy_threshold is not None or any(
        isinstance(p, dict) and p.get("legacy_threshold") is not None
        for p in rule.profiles.values())


# ── the code rules ──────────────────────────────────────────────────────────

def _nonblank(value: Any) -> bool:
    """The legacy text test: `(value or "").strip()` is non-empty."""
    return bool((value or "").strip())


# A5: column names a person would not search for (col1, field_2, val, tmp_x, 9lives)
# and SHOUTING_SNAKE warehouse names.
_NAME_ANTI = re.compile(r"^col\d+$|^field[-_]?\d+$|^val\d*$|^tmp[-_]|^\d", re.IGNORECASE)
_NAME_ANTI_UPPER = re.compile(r"^[A-Z][A-Z0-9]*_[A-Z0-9_]+$")


def _poor_name(name: str) -> bool:
    return bool(_NAME_ANTI.match(name) or _NAME_ANTI_UPPER.match(name))


def readiness_score(item: dict, ctx: Any) -> float:
    """A5's weighted score for one model item, 0-100: descriptions 30%, coaching 25%,
    synonyms 15%, model description 15%, column-name quality 15%. Every column share
    is over ALL columns, and a model without columns counts as one, so its score is
    defined (its shares are 0% and its name quality 100%)."""
    model = item["obj"]
    cols = model.get("columns") or []
    total = len(cols) if cols else 1
    desc_pct = (sum(1 for c in cols if _nonblank(c.get("description"))) / total) * 100
    syn_pct = (sum(1 for c in scopes.iterate(ctx, "model.column", parent=item)
                   if fields.get(c, "@has_synonyms", ctx)) / total) * 100
    has_ai = bool(fields.get(item, "@is_coached", ctx))
    has_desc = _nonblank(model.get("description"))
    anti = sum(1 for c in cols if _poor_name(c.get("name", "")))
    name_quality = ((total - anti) / total) * 100 if total else 100
    return (desc_pct * 0.30
            + (100 if has_ai else 0) * 0.25
            + syn_pct * 0.15
            + (100 if has_desc else 0) * 0.15
            + name_quality * 0.15)


@code_rule("spotter_readiness", placeholders={"score"}, severity="bands",
           uses={"ai_instructions"},  # readiness_score -> @is_coached
           label="graded on a weighted readiness score")
def spotter_readiness(rule: "Rule", ctx: Any, profile: str) -> List[Finding]:
    """A5 — one finding per model whose readiness score the bands grade."""
    out: List[Finding] = []
    for item in scopes.available(ctx, rule):
        score = readiness_score(item, ctx)
        severity = bands.classify(score, rule.bands)
        if severity is None:
            continue
        out.append(Finding(check_id=rule.id, angle="", severity=severity,
                           object_type=item["object_type"], object_name=item["name"],
                           object_guid=item["guid"],
                           detail=render(template(rule, severity), {"score": score}),
                           metric=round(score, 1)))
    return out


# ── D: Data Modeling ────────────────────────────────────────────────────────

def _d_finding(rule: "Rule", item: dict, severity: str, values: Dict[str, Any], **kw) -> Finding:
    """A finding about `item` (its object type, name and guid unless `kw` says
    otherwise), worded by the rule's template for `severity`."""
    fields_ = {"object_type": item["object_type"], "object_name": item["name"],
               "object_guid": item["guid"], **kw}
    return Finding(check_id=rule.id, angle="", severity=severity,
                   detail=render(template(rule, severity), values), **fields_)


def _join_count(model: dict) -> int:
    return sum(len(t.get("joins") or []) for t in model.get("model_tables") or [])


#: D1's grading table, in the legacy order: (measure, value of a Model, above this is
#: MEDIUM, above this HIGH). The columns and join-depth lines are the ceilings P8 and
#: P7 report on (engine/tml.py, BL-304).
D1_MEASURES = (
    ("tables", lambda m: len(m.get("model_tables") or []), 10, 15),
    ("columns", lambda m: len(m.get("columns") or []), 50, tml.MAX_MODEL_COLUMNS),
    ("joins", _join_count, 8, 12),
    ("join depth", lambda m: tml.join_depth(m.get("model_tables") or []),
     tml.JOIN_DEPTH_GREEN, tml.JOIN_DEPTH_YELLOW),
    ("formulas", lambda m: len(m.get("formulas") or []), 30, 50),
)


@code_rule("model_complexity", placeholders={"value", "measure", "green", "yellow"},
           severity={"HIGH", "MEDIUM"}, uses=(), own_threshold=True,
           label="graded per size measure (tables, columns, joins, join depth, "
                 "formulas), each against its own lines")
def model_complexity(rule: "Rule", ctx: Any, profile: str) -> List[Finding]:
    """D1 — up to five findings per Model, one per measure over its MEDIUM line."""
    out: List[Finding] = []
    for item in scopes.available(ctx, rule):
        for measure, value_of, green, yellow in D1_MEASURES:
            value = value_of(item["obj"])
            if value <= green:
                continue
            severity = "HIGH" if value > yellow else "MEDIUM"
            values = {"value": value, "measure": measure, "green": green, "yellow": yellow}
            out.append(_d_finding(rule, item, severity, values, metric=value,
                                  threshold={"green": green, "yellow": yellow}))
    return out


@code_rule("join_keys", placeholders={"varchar_keys", "key_pairs"},
           severity={"HIGH", "MEDIUM"}, uses=(),
           label="graded per join: HIGH for string-typed keys, MEDIUM for more than "
                 "one key pair")
def join_keys(rule: "Rule", ctx: Any, profile: str) -> List[Finding]:
    """D2 — per join, up to two findings: HIGH for string-typed keys (P6's test,
    @varchar_join_keys), MEDIUM for a composite key (more than one operand pair)."""
    from ts_cli.audit.context import join_key_ids  # not gate-safe: import on use
    out: List[Finding] = []
    for item in scopes.available(ctx, rule):
        varchar = fields.get(item, "@varchar_join_keys", ctx)
        keys = join_key_ids(item["obj"]["on"])
        values = {"varchar_keys": varchar, "key_pairs": len(keys) // 2}
        if varchar:
            out.append(_d_finding(rule, item, "HIGH", values, metric=len(varchar)))
        if len(keys) > 2:
            out.append(_d_finding(rule, item, "MEDIUM", values, metric=len(keys) // 2))
    return out


@code_rule("zero_column_tables", placeholders={"name", "role"}, severity="severity",
           uses=(), label="graded on the table's place in the joins")
def zero_column_tables(rule: "Rule", ctx: Any, profile: str) -> List[Finding]:
    """D10 — a model table no model column comes from, named by its `name`."""
    out: List[Finding] = []
    for item in scopes.available(ctx, rule):
        role = fields.get(item, "@zero_column_role", ctx)
        if role is None:
            continue
        name = item["obj"].get("name", "")
        severity = bands.fixed_severity(rule, item, ctx)
        out.append(_d_finding(rule, item, severity, {"name": name, "role": role},
                              object_name=name))
    return out


def _column_types_by_db_name(models: List[dict]) -> Dict[Any, Dict[Any, Any]]:
    """db column name -> {Model name: column type}, as legacy D12 collects it: a later
    column (or Model of the same name) overwrites an earlier one's type in place."""
    col_types: Dict[Any, Dict[Any, Any]] = {}
    for item in models:
        for c in item["obj"].get("columns") or []:
            db_name = c.get("db_column_name") or c.get("name", "")
            ctype = (c.get("properties") or {}).get("column_type", "")
            if ctype:
                col_types.setdefault(db_name, {})[item["name"]] = ctype
    return col_types


def _named_severity(rule: "Rule") -> str:
    """The rule's severity when it must be a plain name (a finding not about one scope
    item has nothing to look a severity mapping up on)."""
    if not isinstance(rule.severity, str):
        raise ValueError(f"{rule.id} ({rule.implementation}): needs a severity name, "
                         f"got {rule.severity!r}")
    return rule.severity


@code_rule("column_type_divergence", placeholders={"name", "models"},
           severity="severity_name", uses=(),
           label="one finding per column whose type differs between Models")
def column_type_divergence(rule: "Rule", ctx: Any, profile: str) -> List[Finding]:
    """D12 — a db column name classified differently across Models. Like legacy D12,
    it reads no column at all unless the context holds two Models or more (one Model
    cannot diverge from itself, and a malformed column must not stop the audit there)."""
    out: List[Finding] = []
    if len(ctx.models) < 2:
        return out
    col_types = _column_types_by_db_name(list(scopes.available(ctx, rule)))
    for db_name, by_model in col_types.items():
        if len(set(by_model.values())) <= 1:
            continue
        listed = ", ".join(f"{mn}={ct}" for mn, ct in by_model.items())
        severity = _named_severity(rule)
        out.append(Finding(check_id=rule.id, angle="", severity=severity,
                           object_type="column", object_name=db_name, object_guid="",
                           detail=render(template(rule, severity),
                                         {"name": db_name, "models": listed})))
    return out


# The H (Human Readiness) code rules live in their own module; importing it here
# registers them wherever REGISTRY is read (the engine, and the catalog gate).
from ts_cli.audit.engine import code_rules_human  # noqa: E402,F401
