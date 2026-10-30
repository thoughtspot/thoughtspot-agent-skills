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
                     "bands"          graded by the rule's `bands`
                     "severity"       the catalog `severity`, a name or a mapping (D10,
                                      H2, H10)
                     "severity_name"  the catalog `severity`, a plain name only (D12:
                                      its findings are not about one item, so it has
                                      nothing to look a mapping up on)
                     {"HIGH", ...}    fixed in the function: these severities (P6, whose
                                      one join can yield two findings)
                   It fixes which severities the rule can emit (a by-severity message
                   must word each, and only those) and which of `bands` / `severity`
                   the entry must — and must not — carry.
    own_threshold  True when it sets each finding's legacy threshold itself (D1); the
                   entry must then carry no `legacy_threshold`
    band_shape     the `(op, severity)` levels, worst first, its message or threshold
                   assumes (D1 words ">{yellow} HIGH, >{green} MEDIUM"): every
                   profile's bands must be exactly these, values free
    parameters     the names of the tuning numbers it reads from `rule.parameters`
                   (H2's `min_chars`, H10's `quote_chars`). The entry must carry
                   exactly these, each a number; a profile may replace the map whole.
                   A number a reader might want to tune belongs here, not in a
                   module constant
    label          (required) how the grading reads to an audit reader — generated
                   text shows it, never `code:<name>`: "graded per join, on its key
                   types and key count"
    uses           (required) the conditional data (catalog_expr.CONDITIONAL_DATA) it
                   reads from the context, through a derived field included — `()` for
                   none. The gate fails an entry whose `requires`/`uses` do not cover
                   it (catalog_uses.py)

The contract (`run.run_rules` dispatches; `check_findings` enforces it):

    rule      the EFFECTIVE rule — the profile's overrides (bands, severity, message,
              remediation, parameters) already applied. Grade with `bands.classify(value,
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
messages, bands}, and the stdlib-only shared modules the gate test copies
(GATE_SHARED_MODULES: tml_join_graph, tml_rls_graph, spotql_ops) — and
code_rules_human / code_rules_security, imported at the end of this module, hold to
the same list. Anything else (context, commands) is imported
inside the rule function. tools/validate/tests/test_check_audit_catalog.py copies
only the permitted modules and fails if this one needs more.
"""
from __future__ import annotations

import re
from typing import (TYPE_CHECKING, Any, Callable, Dict, FrozenSet, Iterable, List, Set,
                    Tuple)

from ts_cli.audit.engine import tml
from ts_cli.audit.catalog_validate import CODE_IMPL, SEVERITIES
from ts_cli.audit.engine import bands, fields, fields_human, scopes
from ts_cli.audit.engine.messages import NameList, render, template
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
CODE_PARAMETERS: Dict[str, FrozenSet[str]] = {}   # the `parameters` names it reads
BAND_SHAPES: Dict[str, Tuple[Tuple[str, str], ...]] = {}  # the (op, severity) levels it words
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
              uses: Any = None, own_threshold: bool = False, label: Any = None,
              parameters: Iterable[str] = (),
              band_shape: Iterable[Tuple[str, str]] = ()) -> Callable[[CodeRule], CodeRule]:
    """Register the decorated function as `implementation: code:<name>`, rendering its
    message with `placeholders`, its severity from `severity`, reading the conditional
    data `uses` from the context (itself or through a derived field), and — with
    `own_threshold` — setting each finding's legacy threshold itself; `label` is how its
    grading reads to an audit reader; `parameters` the `rule.parameters` names it reads;
    `band_shape` the `(op, severity)` levels, worst first, its wording assumes."""
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
        CODE_PARAMETERS[name] = frozenset(parameters)
        if band_shape:
            BAND_SHAPES[name] = tuple(tuple(level) for level in band_shape)
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
    """The legacy text test: `(value or "").strip()` is non-empty; a non-string (a
    YAML-typed `description: 7`) is blank rather than a crash."""
    return isinstance(value, str) and bool(value.strip())


#: The Spotter readiness score's levels (A5's bands until it stopped being a finding,
#: 2026-10): at or above READY a Model is ready, at or above NEEDS_WORK it needs work.
READINESS_READY = 80
READINESS_NEEDS_WORK = 50


def readiness_level(score: float) -> str:
    """`ready`, `needs_work` or `not_ready` for a readiness score."""
    if score >= READINESS_READY:
        return "ready"
    return "needs_work" if score >= READINESS_NEEDS_WORK else "not_ready"


def readiness_score(item: dict, ctx: Any) -> float:
    """The Spotter readiness score of one model item, 0-100, shown in the report (no
    longer a finding: A5 was retired 2026-10): descriptions 30%, coaching 25%,
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
    # A present-but-null name is not a poor name, and a null or YAML-typed (numeric) one
    # must not raise (BL-406 #7)
    anti = sum(1 for c in cols if fields_human.is_poor_name(c.get("name")))
    name_quality = ((total - anti) / total) * 100 if total else 100
    return (desc_pct * 0.30
            + (100 if has_ai else 0) * 0.25
            + syn_pct * 0.15
            + (100 if has_desc else 0) * 0.15
            + name_quality * 0.15)


# ── D: Data Modeling ────────────────────────────────────────────────────────

def _d_finding(rule: "Rule", item: dict, severity: str, values: Dict[str, Any], **kw) -> Finding:
    """A finding about `item` (its object type, name and guid unless `kw` says
    otherwise), worded by the rule's template for `severity`."""
    fields_ = {"object_type": item["object_type"], "object_name": item["name"],
               "object_guid": item["guid"], **kw}
    return Finding(check_id=rule.id, angle="", severity=severity,
                   detail=render(template(rule, severity), values), **fields_)


def _join_count(model: dict) -> int:
    return tml.join_count(model.get("model_tables"))


#: D1's size measures: (name, value of a Model). Each is graded by the rule's `bands`
#: (rules/data.yaml: MEDIUM above 30, HIGH above 50 — lines set 2026-10-23 from
#: production call-home data, 268k Models: tables p99 35, 0.18% above 40; profile-
#: overridable since 2026-10). Columns are P8's and join depth P7's.
D1_MEASURES = (
    ("tables", lambda m: len(m.get("model_tables") or [])),
    ("joins", _join_count),
    ("formulas", lambda m: len(m.get("formulas") or [])),
)


def _whole(value: float) -> Any:
    """A band value as D1 has always worded and recorded it: 30, not 30.0."""
    return int(value) if float(value).is_integer() else value


@code_rule("model_complexity", placeholders={"value", "measure", "green", "yellow"},
           severity="bands", uses=(), own_threshold=True,
           band_shape=(("gt", "HIGH"), ("gt", "MEDIUM")),
           label="graded per size measure (tables, joins, formulas), each against "
                 "the rule's bands")
def model_complexity(rule: "Rule", ctx: Any, profile: str) -> List[Finding]:
    """D1 — up to three findings per Model, one per measure its bands grade. A finding's
    legacy threshold is `{green: <the MEDIUM line>, yellow: <the HIGH line>}`."""
    lines = {lv.severity: _whole(lv.value) for lv in rule.bands.levels}
    green, yellow = lines.get("MEDIUM"), lines.get("HIGH")
    out: List[Finding] = []
    for item in scopes.available(ctx, rule):
        for measure, value_of in D1_MEASURES:
            value = value_of(item["obj"])
            severity = bands.classify(value, rule.bands)
            if severity is None:
                continue
            values = {"value": value, "measure": measure, "green": green, "yellow": yellow}
            out.append(_d_finding(rule, item, severity, values, metric=value,
                                  threshold={"green": green, "yellow": yellow}))
    return out


@code_rule("join_keys", placeholders={"varchar_keys", "key_pairs"},
           severity={"LOW", "INFO"}, uses=(),
           label="graded per join: LOW for string-typed keys, INFO for more than "
                 "one key pair")
def join_keys(rule: "Rule", ctx: Any, profile: str) -> List[Finding]:
    """P6 (D2 merged into it, 2026-10) — per join, up to two findings: LOW for
    string-typed keys (@varchar_join_keys), INFO for a composite key (more than one
    operand pair)."""
    from ts_cli.audit.context import join_key_ids  # not gate-safe: import on use
    out: List[Finding] = []
    for item in scopes.available(ctx, rule):
        varchar = fields.get(item, "@varchar_join_keys", ctx)
        keys = join_key_ids(item["obj"]["on"])
        values = {"varchar_keys": varchar, "key_pairs": len(keys) // 2}
        if varchar:
            out.append(_d_finding(rule, item, "LOW", values, metric=len(varchar)))
        if len(keys) > 2:
            out.append(_d_finding(rule, item, "INFO", values, metric=len(keys) // 2))
    return out


#: The one-sided outer join types D3 rolls up into one finding per Model.
ONE_SIDED_OUTER = ("LEFT_OUTER", "RIGHT_OUTER")


@code_rule("join_types", placeholders={"count", "joins"}, severity={"HIGH", "INFO"},
           uses=(),
           label="HIGH per full outer join; LEFT/RIGHT outer joins rolled up into one "
                 "INFO per Model")
def join_types(rule: "Rule", ctx: Any, profile: str) -> List[Finding]:
    """D3 — per Model, in join order: a HIGH finding on each full outer join
    (ThoughtSpot's `OUTER`), then one INFO finding on the Model listing its LEFT/RIGHT
    outer joins, if it has any. Until 2026-10 each one-sided outer join was its own INFO
    finding — about a third of all findings on the SE demo sample, for an ordinary
    modelling choice."""
    out: List[Finding] = []
    for model in scopes.available(ctx, rule):
        one_sided = NameList()
        for join in scopes.iterate(ctx, "join", parent=model):
            jtype = fields.get(join, "@join_type", ctx)
            if jtype == "OUTER":
                out.append(_d_finding(rule, join, "HIGH", {"count": 1, "joins": NameList()}))
            elif jtype in ONE_SIDED_OUTER:
                one_sided.append(f"{join['name']} ({jtype})")
        if one_sided:
            out.append(_d_finding(rule, model, "INFO",
                                  {"count": len(one_sided), "joins": one_sided},
                                  metric=len(one_sided)))
    return out


@code_rule("model_overlap", placeholders={"name", "a", "b", "similarity", "shared",
                                         "union"},
           severity="bands", uses=(),
           label="graded per pair of Models on the share of tables they have in "
                 "common; a partial overlap only when a table they share is a fact "
                 "table in either")
def model_overlap(rule: "Rule", ctx: Any, profile: str) -> List[Finding]:
    """D7 — every unordered pair of Models sharing a table (@table_set), graded on the
    Jaccard similarity of their table sets by the rule's bands, as the pairwise mode
    grades. Below identical (a partial overlap), a pair is reported only when a table
    both contain reads as a fact in either Model (@fact_table_set) — "either", because
    the fact test counts physical measures only, so the same fact table can read as a
    dimension in a Model that measures it through formulas. Two Models that merely
    reuse the same dimensions are not duplicates. Reported once per pair, on the
    first Model."""
    from itertools import combinations
    models = [(i, fields.as_set(fields.get(i, "@table_set", ctx)),
               fields.as_set(fields.get(i, "@fact_table_set", ctx)))
              for i in scopes.available(ctx, rule)]
    out: List[Finding] = []
    for (a, ta, fa), (b, tb, fb) in combinations(models, 2):
        shared = ta & tb
        if not shared:
            continue
        union = ta | tb
        similarity = len(shared) / len(union)
        if similarity < 1 and not (shared & (fa | fb)):
            continue
        severity = bands.classify(similarity, rule.bands)
        if severity is None:
            continue
        name = f"{a['name']} / {b['name']}"
        values = {"name": name, "a": a["name"], "b": b["name"], "similarity": similarity,
                  "shared": len(shared), "union": len(union)}
        out.append(_d_finding(rule, a, severity, values, metric=round(similarity, 2),
                              object_name=name))
    return out


@code_rule("zero_column_tables", placeholders={"name", "role"}, severity="severity",
           uses=(), label="graded on the table's place in the joins")
def zero_column_tables(rule: "Rule", ctx: Any, profile: str) -> List[Finding]:
    """D10 — a model table no model column comes from, named by its key (alias, else
    name: an aliased table is reported by the alias that tells its roles apart)."""
    out: List[Finding] = []
    for item in scopes.available(ctx, rule):
        role = fields.get(item, "@zero_column_role", ctx)
        if role is None:
            continue
        name = tml.table_key(item["obj"])
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
from ts_cli.audit.engine import code_rules_security  # noqa: E402,F401
