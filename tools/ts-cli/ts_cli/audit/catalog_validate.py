"""Audit rule catalog — vocabulary and validator.

`validate_catalog` collects every problem in one pass (empty list = valid). Each
message starts `<file>: <id>:` — the file relative to the catalog root and the rule,
category or profile it is about — so a failing gate points at the line to fix.

What it rejects: unknown keys; unknown scopes, modes, operators, data requirements,
categories, profiles, views, band ops/directions/units, severities; ids repeated across
files; a profile override of a key that defines what a rule *means* (anything outside
OVERRIDABLE); band levels not ordered worst first, in the catalog's bands and in every
profile's replacement bands; an active rule without a `fires` and a `silent` example.

The vocabulary below is the engine's contract (plan Task 4). Two registries do not exist
yet and are hooks returning None ("not checked"): derived field names (`@name`, Task 4)
and code-rule names (`implementation: code:<name>`, Task 5).

Kept importable on Python 3.9 with only PyYAML (see catalog_model.py).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from ts_cli.audit.catalog_model import (
    CATEGORIES_FILE,
    PROFILES_FILE,
    RULES_DIR,
    Bands,
    Catalog,
    CatalogError,
    Rule,
    build_catalog,
    load_raw,
    parse_bands,
)

# ── vocabulary ──────────────────────────────────────────────────────────────

SCOPES = [
    "model", "model.column", "model.formula", "model.filter", "model.table",
    "join", "table", "table.rls_rule", "rls_column_ref",
    "answer", "answer.table_ref", "answer.formula", "set", "metadata",
]
MODES = ["each", "ratio", "count", "group", "pairwise", "composite"]
OPERATORS = [
    "eq", "in", "regex", "not_regex", "exists", "nonblank", "truthy",
    "gt", "gte", "lt", "lte", "len_gt", "len_lt", "contains",
    "all", "any", "not", "count",
]
REQUIRES = ["model_tml", "table_tml", "metadata", "dependents", "ai_instructions",
            "answers", "sets"]
SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
OVERRIDABLE = {"status", "bands", "severity", "message", "remediation"}
# Accepted in a profile block but not a general override: it reproduces the legacy
# per-profile `threshold` dict (A1/A2/A6) and goes when the legacy dict does.
PROFILE_ONLY = {"legacy_threshold"}
STATUSES = ["active", "retired"]
BAND_OPS = ["lt", "lte", "gt", "gte", "eq"]
DIRECTIONS = ["higher_is_better", "lower_is_better"]
UNITS = ["percent", "count", "depth", "ratio", "score"]
VIEWS = ["duplicates", "cleanup"]

RULE_KEYS = {
    "id", "title", "description", "status", "categories", "requires", "implementation",
    "scope", "aggregate", "bands", "severity", "profiles", "message", "legacy_threshold",
    "remediation", "examples", "views",
}
CATEGORY_KEYS = {"id", "label", "order", "description"}
PROFILE_KEYS = {"id", "label", "default"}
BANDS_KEYS = {"direction", "unit", "levels"}
LEVEL_KEYS = {"op", "value", "severity"}
EXAMPLE_KINDS = ("fires", "silent")
EXAMPLE_KEYS = {"fixture", "profile", "severity"}

_COMBINATORS = {"all", "any", "not", "count"}
LEAF_OPERATORS = [op for op in OPERATORS if op not in _COMBINATORS]
_BAND_OPS_FOR = {"higher_is_better": {"lt", "lte", "eq"},
                 "lower_is_better": {"gt", "gte", "eq"}}
_CODE_IMPL = re.compile(r"^code:([a-z_][a-z0-9_]*)$")


def known_derived_fields() -> Optional[Set[str]]:
    """Names usable as `field: '@name'`. None = not checked yet (registry is Task 4)."""
    return None


def known_code_rules() -> Optional[Set[str]]:
    """Names usable as `implementation: code:<name>`. None = not checked yet (Task 5)."""
    return None


def _known(values: Iterable[str]) -> str:
    return ", ".join(values)


def _is_id_in(value: Any, ids: Dict[str, Any]) -> bool:
    """`value in ids`, false (not TypeError) when YAML gave a list or mapping."""
    return isinstance(value, str) and value in ids


# ── predicate expressions (`where` / `match`) ───────────────────────────────

def _field_problems(expr: dict, value: Any, path: str) -> List[str]:
    if not isinstance(value, str) or not value.strip("@"):
        return [f"{path}: must be a dotted path or '@derived' name"]
    derived = known_derived_fields()
    if value.startswith("@") and derived is not None and value[1:] not in derived:
        return [f"{path}: unknown derived field '{value}'"]
    return []


def _list_problems(expr: dict, value: Any, path: str) -> List[str]:
    if not isinstance(value, list) or not value:
        return [f"{path}: must be a non-empty list of expressions"]
    out: List[str] = []
    for i, sub in enumerate(value):
        out += expr_problems(sub, f"{path}[{i}]")
    return out


def _not_problems(expr: dict, value: Any, path: str) -> List[str]:
    return expr_problems(value, path)


def _count_problems(expr: dict, value: Any, path: str) -> List[str]:
    if value not in SCOPES:
        return [f"{path}: unknown scope '{value}' (known: {_known(SCOPES)})"]
    return []


def _where_problems(expr: dict, value: Any, path: str) -> List[str]:
    if "count" not in expr:
        return [f"{path}: 'where' inside an expression is only valid beside 'count'"]
    return expr_problems(value, path)


_EXPR_KEYS: Dict[str, Callable[[dict, Any, str], List[str]]] = {
    "field": _field_problems,
    "all": _list_problems,
    "any": _list_problems,
    "not": _not_problems,
    "count": _count_problems,
    "where": _where_problems,
}


def _pairing_problems(expr: dict, path: str, unknown: List[str]) -> List[str]:
    """A comparison needs something to compare, and a field needs a comparison."""
    leaves = [k for k in expr if k in LEAF_OPERATORS]
    if leaves and "field" not in expr and "count" not in expr:
        return [f"{path}: '{leaves[0]}' needs a 'field' (or 'count') to compare"]
    if "field" in expr and not leaves and not unknown:
        return [f"{path}: 'field' given with no operator"]
    return []


def expr_problems(expr: Any, path: str) -> List[str]:
    """Problems in one `where`/`match` expression, recursing through all/any/not/count."""
    if not isinstance(expr, dict) or not expr:
        return [f"{path}: expected a non-empty mapping"]
    unknown = [k for k in expr if k not in _EXPR_KEYS and k not in LEAF_OPERATORS]
    out = [f"{path}: unknown operator '{k}' (known: {_known(OPERATORS)})" for k in unknown]
    for key, value in expr.items():
        handler = _EXPR_KEYS.get(key)
        if handler is not None:
            out += handler(expr, value, f"{path}.{key}")
    return out + _pairing_problems(expr, path, unknown)


def scan_expressions(obj: Any, path: str) -> List[str]:
    """Validate every `where` / `match` value found anywhere inside `obj`."""
    out: List[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            sub = f"{path}.{key}" if path else str(key)
            out += expr_problems(value, sub) if key in ("where", "match") \
                else scan_expressions(value, sub)
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            out += scan_expressions(value, f"{path}[{i}]")
    return out


# ── bands ───────────────────────────────────────────────────────────────────

def _bands_key_problems(raw: Any, key: str) -> List[str]:
    """Unknown keys in a raw bands mapping and its levels."""
    if not isinstance(raw, dict):
        return []
    out = [f"{key}: unknown key '{k}'" for k in sorted(set(raw) - BANDS_KEYS)]
    for i, level in enumerate(raw.get("levels") or []):
        if isinstance(level, dict):
            out += [f"{key}.levels[{i}]: unknown key '{k}'"
                    for k in sorted(set(level) - LEVEL_KEYS)]
    return out


def _level_problems(bands: Bands, key: str) -> List[str]:
    out: List[str] = []
    fits = _BAND_OPS_FOR.get(bands.direction, set(BAND_OPS))
    for i, level in enumerate(bands.levels):
        where = f"{key}.levels[{i}]"
        if level.op not in BAND_OPS:
            out.append(f"{where}: unknown band op '{level.op}' (known: {_known(BAND_OPS)})")
        elif level.op not in fits:
            out.append(f"{where}: op '{level.op}' does not fit direction {bands.direction} "
                       f"(use {_known(sorted(fits))})")
        if level.severity not in SEVERITIES:
            out.append(f"{where}: unknown severity '{level.severity}'")
    return out


def _out_of_order(bands: Bands) -> bool:
    """Worst first: higher_is_better thresholds ascend, lower_is_better descend.

    Equal neighbouring values are allowed only with different ops (`lt 40` then
    `lte 40`); otherwise the second level could never be reached.
    """
    sign = {"higher_is_better": 1, "lower_is_better": -1}.get(bands.direction)
    if sign is None:
        return False
    pairs = zip(bands.levels, bands.levels[1:])
    return any((b.value - a.value) * sign < 0 or (a.value == b.value and a.op == b.op)
               for a, b in pairs)


def bands_problems(bands: Optional[Bands], key: str) -> List[str]:
    """Problems in one (catalog or profile-replacement) bands block."""
    if bands is None:
        return []
    out: List[str] = []
    if bands.direction not in DIRECTIONS:
        out.append(f"{key}.direction: unknown direction '{bands.direction}' "
                   f"(known: {_known(DIRECTIONS)})")
    if bands.unit not in UNITS:
        out.append(f"{key}.unit: unknown unit '{bands.unit}' (known: {_known(UNITS)})")
    if not bands.levels:
        out.append(f"{key}.levels: at least one level is required")
    out += _level_problems(bands, key)
    if _out_of_order(bands):
        hint = "ascending" if bands.direction == "higher_is_better" else "descending"
        out.append(f"{key}: levels must be ordered worst first "
                   f"({hint} thresholds for {bands.direction})")
    return out


def _severity_problems(value: Any, key: str) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [] if value in SEVERITIES else \
            [f"{key}: unknown severity '{value}' (known: {_known(SEVERITIES)})"]
    if isinstance(value, dict):
        return scan_expressions(value, key)
    return [f"{key}: must be a severity name or a mapping"]


# ── one rule ────────────────────────────────────────────────────────────────

def _basic_problems(rule: Rule, cat: Catalog) -> List[str]:
    out: List[str] = []
    if not rule.title.strip():
        out.append("title is required")
    if rule.status not in STATUSES:
        out.append(f"status: unknown status '{rule.status}' (known: {_known(STATUSES)})")
    if not rule.scope:
        out.append("scope is required")
    elif rule.scope not in SCOPES:
        out.append(f"scope: unknown scope '{rule.scope}' (known: {_known(SCOPES)})")
    if not rule.categories:
        out.append("categories: at least one category is required")
    out += [f"categories: unknown category '{c}' (known: {_known(cat.categories)})"
            for c in rule.categories if not _is_id_in(c, cat.categories)]
    out += [f"requires: unknown requires value '{r}' (known: {_known(REQUIRES)})"
            for r in rule.requires if r not in REQUIRES]
    out += [f"views: unknown view '{v}' (known: {_known(VIEWS)})"
            for v in rule.views if v not in VIEWS]
    return out


def _implementation_problems(rule: Rule) -> List[str]:
    if rule.implementation == "declarative":
        return []
    m = _CODE_IMPL.match(rule.implementation)
    if not m:
        return [f"implementation: '{rule.implementation}' must be 'declarative' "
                "or 'code:<name>'"]
    registered = known_code_rules()
    if registered is not None and m.group(1) not in registered:
        return [f"implementation: unknown code rule '{m.group(1)}'"]
    return []


def _aggregate_problems(rule: Rule) -> List[str]:
    agg = rule.aggregate
    out: List[str] = []
    mode = agg.get("mode")
    if mode is None:
        if rule.implementation == "declarative":
            out.append("aggregate.mode is required for a declarative rule")
    elif mode not in MODES:
        out.append(f"aggregate.mode: unknown mode '{mode}' (known: {_known(MODES)})")
    over = agg.get("over")
    if over is not None and over not in SCOPES:
        out.append(f"aggregate.over: unknown scope '{over}' (known: {_known(SCOPES)})")
    return out + scan_expressions(agg, "aggregate")


def _override_value_problems(key: str, value: Any, path: str, rule: Rule) -> List[str]:
    if key == "status":
        return [] if value in STATUSES else [f"{path}: unknown status '{value}'"]
    if key == "severity":
        return _severity_problems(value, path)
    if key == "bands":
        try:
            parsed = parse_bands(value, rule.source_file, rule.id, path)
        except CatalogError as exc:
            return [exc.message]
        return _bands_key_problems(value, path) + bands_problems(parsed, path)
    if key == "legacy_threshold":
        return [] if isinstance(value, dict) else [f"{path}: must be a mapping"]
    return [] if isinstance(value, str) else [f"{path}: must be a string"]


def _profile_override_problems(rule: Rule, cat: Catalog) -> List[str]:
    out: List[str] = []
    allowed = OVERRIDABLE | PROFILE_ONLY
    for pid, override in rule.profiles.items():
        path = f"profiles.{pid}"
        if pid not in cat.profiles:
            out.append(f"{path}: unknown profile '{pid}' (known: {_known(cat.profiles)})")
        if not isinstance(override, dict):
            out.append(f"{path}: must be a mapping of overrides")
            continue
        for key, value in override.items():
            if key not in allowed:
                out.append(f"{path}.{key} is not overridable "
                           f"(a profile may set: {_known(sorted(allowed))})")
            else:
                out += _override_value_problems(key, value, f"{path}.{key}", rule)
    return out


def _example_problems(kind: str, ex: Any, cat: Catalog) -> List[str]:
    path = f"examples.{kind}"
    if not isinstance(ex, dict):
        return [f"{path}: must be a mapping {{fixture, profile, severity}}"]
    out = [f"{path}: unknown key '{k}'" for k in sorted(set(ex) - EXAMPLE_KEYS)]
    if not isinstance(ex.get("fixture"), str) or not ex["fixture"].strip():
        out.append(f"{path}.fixture: a fixture function name is required")
    if "profile" in ex and not _is_id_in(ex["profile"], cat.profiles):
        out.append(f"{path}.profile: unknown profile '{ex['profile']}'")
    if kind == "fires" and ex.get("severity") not in SEVERITIES:
        out.append(f"{path}.severity: the expected severity is required "
                   f"(one of {_known(SEVERITIES)})")
    if kind == "silent" and "severity" in ex:
        out.append(f"{path}.severity: a silent example produces no finding")
    return out


def _examples_problems(rule: Rule, cat: Catalog) -> List[str]:
    out = [f"examples: unknown example kind '{k}' (known: {_known(EXAMPLE_KINDS)})"
           for k in rule.examples if k not in EXAMPLE_KINDS]
    for kind in EXAMPLE_KINDS:
        if kind in rule.examples:
            out += _example_problems(kind, rule.examples[kind], cat)
        elif rule.status == "active":
            out.append(f"examples.{kind}: an active rule needs a '{kind}' example")
    return out


def rule_problems(rule: Rule, cat: Catalog) -> List[str]:
    """Every problem in one rule, each prefixed `<file>: <id>:`."""
    msgs = (_basic_problems(rule, cat) + _implementation_problems(rule)
            + _aggregate_problems(rule) + bands_problems(rule.bands, "bands")
            + _severity_problems(rule.severity, "severity")
            + _profile_override_problems(rule, cat) + _examples_problems(rule, cat))
    return [f"{rule.source_file}: {rule.id}: {m}" for m in msgs]


# ── categories, profiles, raw files ─────────────────────────────────────────

def _category_problems(cat: Catalog) -> List[str]:
    out: List[str] = []
    if not cat.categories:
        out.append(f"{CATEGORIES_FILE}: -: at least one category is required")
    seen: Dict[int, str] = {}
    for c in cat.categories.values():
        if not c.label.strip():
            out.append(f"{CATEGORIES_FILE}: {c.id}: label is required")
        if c.order in seen:
            out.append(f"{CATEGORIES_FILE}: {c.id}: order {c.order} repeats {seen[c.order]}")
        seen.setdefault(c.order, c.id)
    return out


def _profile_problems(cat: Catalog) -> List[str]:
    out = [f"{PROFILES_FILE}: {p.id}: label is required"
           for p in cat.profiles.values() if not p.label.strip()]
    defaults = [p.id for p in cat.profiles.values() if p.default]
    if len(defaults) != 1:
        out.append(f"{PROFILES_FILE}: -: exactly one profile must be default: true "
                   f"(found {len(defaults)})")
    return out


def _allowed_keys(file: str) -> Set[str]:
    return {CATEGORIES_FILE: CATEGORY_KEYS, PROFILES_FILE: PROFILE_KEYS}.get(file, RULE_KEYS)


def _id_space(file: str) -> str:
    return "rules" if file.startswith(f"{RULES_DIR}/") else file


def _raw_problems(raw: Dict[str, List[Dict[str, Any]]]) -> List[str]:
    """What the dataclasses cannot show: unknown keys and repeated ids."""
    out: List[str] = []
    first: Dict[Tuple[str, str], str] = {}
    for file, entries in raw.items():
        for entry in entries:
            rid = str(entry.get("id"))
            prefix = f"{file}: {rid}: "
            out += [f"{prefix}unknown key '{k}'"
                    for k in sorted(set(entry) - _allowed_keys(file))]
            if file.startswith(f"{RULES_DIR}/"):
                out += [prefix + m for m in _bands_key_problems(entry.get("bands"), "bands")]
            slot = (_id_space(file), rid)
            if slot in first:
                out.append(f"{prefix}duplicate id (first defined in {first[slot]})")
            first.setdefault(slot, file)
    return out


def validate_catalog(cat: Catalog, raw: Optional[Dict[str, List[Dict[str, Any]]]] = None
                     ) -> List[str]:
    """Every problem in the catalog; empty means valid.

    Pass `raw` (from `load_raw`) to also catch unknown keys and repeated ids, which the
    dataclasses cannot carry; `check_catalog` does this for you.
    """
    problems = _category_problems(cat) + _profile_problems(cat)
    if raw is not None:
        problems += _raw_problems(raw)
    for rule in cat.rules.values():
        problems += rule_problems(rule, cat)
    return problems


def check_catalog(root: Optional[Path] = None) -> Tuple[Optional[Catalog], List[str]]:
    """Load and validate the catalog at `root`. A loader error is the one problem."""
    try:
        raw = load_raw(root)
        cat = build_catalog(raw)
    except CatalogError as exc:
        return None, [str(exc)]
    return cat, validate_catalog(cat, raw)
