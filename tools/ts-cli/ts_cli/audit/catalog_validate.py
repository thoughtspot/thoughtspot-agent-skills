"""Audit rule catalog — vocabulary and validator.

`validate_catalog` collects every problem in one pass (empty list = valid). Each
message starts `<file>: <id>:` — the file relative to the catalog root and the rule,
category or profile it is about — so a failing gate points at the line to fix.

What it rejects: unknown keys (rule, aggregate — per mode —, bands, severity mapping,
examples, categories, profiles); operand values of the wrong type (`eq` not a single
value, `in` not a list of them, `contains` not one scalar, a regex that does not
compile, a non-numeric comparison, a non-boolean exists/nonblank/truthy); a mode
without its required aggregate keys (`over` for ratio/count, which must be a child
scope of the rule's scope; `key`/`kind` for group; `set` for pairwise;
`components`/`weights` for composite); a severity the mode cannot produce (no bands
on a grading mode, neither severity nor bands on each/group, bands on an each rule with
no `measure`; a `severity` that bands override, catalog or profile); an expression
mapping that mixes forms or lacks a comparison; a `count:` over a scope that is not
the item's (or an enclosing item's) child; unknown scopes, modes, operators, derived
fields (`@name`, also as a step inside a path), code-rule names (`code:<name>`
not registered), an `aggregate` block on a code rule (the function owns its logic),
message placeholders (a code rule's: those its function declares), data requirements,
`uses` values, undeclared reads by a rule or a registration (catalog_uses/_reads.py),
categories, profiles, views, band ops/directions/units, severities; ids repeated across files; a category without a unique
`angle_key`; a profile override of a key that defines what a rule *means* (anything
outside OVERRIDABLE); band levels not ordered worst first, in the catalog's bands and
in every profile's replacement bands; an active rule without a `fires` and a `silent`
example (a retired rule may also carry no logic at all — no aggregate, no
implementation — when no profile revives it); a `{by_severity: ...}` message or legacy threshold with an unknown severity, a
non-template value, a severity nothing uses it for (a profile's own entry: one that
profile never emits; a catalog-level entry: one no profile using it emits), or (a
message) no template for one the rule can emit under a profile; a code rule's entry that does not carry exactly the
severity source its function declares it reads (bands, a severity — a plain name where
required — or neither), or a `legacy_threshold` beside a function that sets its own;
prose (title, description, remediation, message text) that shows an engine identifier,
or a `legacy_threshold` number that is not one of the rule's band values
(catalog_consistency.py).

Expression, aggregate and message checks — and the scope/mode/operator vocabulary —
live in `catalog_expr.py` and are re-exported here; the code-rule checks live in
`catalog_code.py`, and those of the per-severity forms of `message` and
`legacy_threshold` in `catalog_forms.py`. Two names come from engine
registries, each imported lazily so the gate stays free of typer/requests: derived
fields (`engine/fields.py` and the `engine/fields_data.py` / `engine/fields_human.py`
it imports, via `known_derived_fields`) and code rules (`implementation: code:<name>`,
`engine/code_rules.py` and the `engine/code_rules_human.py` it imports, via
`known_code_rules`).

Kept importable on Python 3.9 with only PyYAML (see catalog_model.py).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from ts_cli.audit.catalog_expr import (  # noqa: F401  (re-exported vocabulary)
    AGGREGATE_KEYS,
    LEAF_OPERATORS,
    MODE_PLACEHOLDERS,
    MODES,
    OPERATORS,
    PARENT_SCOPE,
    SCOPES,
    SEVERITIES,
    aggregate_problems,
    expr_problems,
    field_path_problems,
    known_derived_fields,
    known_field_values,
    legacy_threshold_problems,
    message_placeholders,
    message_problems,
    placeholder_problems,
    severity_source_problems,
)
from ts_cli.audit.catalog_code import (  # noqa: F401  (re-exported)
    CODE_IMPL,
    code_rule_aggregate_problems,
    code_rule_problems,
    implementation_problems,
    known_code_rules,
    rule_message_problems,
)
from ts_cli.audit.catalog_uses import data_declaration_problems, registry_read_problems
from ts_cli.audit.catalog_consistency import (
    category_prose_problems, rule_consistency_problems,
)
from ts_cli.audit.catalog_forms import (  # noqa: F401  (re-exported)
    BY_SEVERITY,
    form_coverage_problems,
    legacy_threshold_form_problems,
    message_problems_any,
)
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
    profile_override,
)

# ── vocabulary ──────────────────────────────────────────────────────────────

REQUIRES = ["model_tml", "table_tml", "metadata", "dependents", "ai_instructions",
            "answers", "sets"]
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
    "id", "title", "description", "status", "categories", "requires", "uses", "implementation",
    "scope", "aggregate", "bands", "severity", "profiles", "message", "legacy_threshold",
    "remediation", "examples", "views",
}
CATEGORY_KEYS = {"id", "label", "order", "description", "angle_key"}
PROFILE_KEYS = {"id", "label", "default"}
BANDS_KEYS = {"direction", "unit", "levels"}
LEVEL_KEYS = {"op", "value", "severity"}
EXAMPLE_KINDS = ("fires", "silent")
EXAMPLE_KEYS = {"fixture", "profile", "severity"}
# A mapping-valued severity: chosen from an item field, e.g.
#   {field: join_type, map: {OUTER: HIGH, LEFT_OUTER: INFO}, default: MEDIUM}
# The engine looks the field's value up in `map` (exact, type-sensitive: YAML `true`
# is a boolean key) and falls back to `default`.
SEVERITY_MAP_KEYS = {"field", "map", "default"}

_BAND_OPS_FOR = {"higher_is_better": {"lt", "lte", "eq"},
                 "lower_is_better": {"gt", "gte", "eq"}}
def _known(values: Iterable[str]) -> str:
    return ", ".join(values)


def _is_id_in(value: Any, ids: Dict[str, Any]) -> bool:
    """`value in ids`, false (not TypeError) when YAML gave a list or mapping."""
    return isinstance(value, str) and value in ids


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
        return _severity_map_problems(value, key)
    return [f"{key}: must be a severity name or a mapping"]


def _severity_name_problems(value: Any, key: str) -> List[str]:
    if isinstance(value, str) and value in SEVERITIES:
        return []
    return [f"{key}: unknown severity '{value}' (known: {_known(SEVERITIES)})"]


def _severity_map_problems(sev: dict, key: str) -> List[str]:
    """`{field: <path>, map: {<value>: <SEVERITY>}, default: <SEVERITY>}`."""
    out = [f"{key}: unknown key '{k}' (known: {_known(sorted(SEVERITY_MAP_KEYS))})"
           for k in sorted(map(str, set(sev) - SEVERITY_MAP_KEYS))]
    out += [f"{key}.{k}: required" for k in sorted(SEVERITY_MAP_KEYS - set(sev))]
    if "field" in sev:
        out += field_path_problems(sev["field"], f"{key}.field")
    mapping = sev.get("map")
    if "map" in sev and (not isinstance(mapping, dict) or not mapping):
        out.append(f"{key}.map: must be a non-empty mapping of value -> severity")
    elif isinstance(mapping, dict):
        for value, name in mapping.items():
            out += _severity_name_problems(name, f"{key}.map.{value}")
        out += _severity_map_key_problems(sev.get("field"), mapping, key)
    if "default" in sev:
        out += _severity_name_problems(sev["default"], f"{key}.default")
    return out


def _severity_map_key_problems(field: Any, mapping: dict, key: str) -> List[str]:
    """A severity map keyed on a derived field: every key is a value the field can
    return (engine/fields.py FIELD_VALUES), compared as the engine compares them
    (predicates.equals — a boolean never equals a number or a string). A key nothing
    equals never maps: a typo (`tokn`), or YAML `"true"` for a boolean field. A
    derived field that declares no values fails closed; a plain path has no declared
    vocabulary and is not checked."""
    if not (isinstance(field, str) and field.startswith("@")
            and field[1:] in known_derived_fields()):
        return []
    from ts_cli.audit.engine.predicates import equals
    values = known_field_values(field[1:])
    if values is None:
        return [f"{key}.map: derived field '{field}' declares no values "
                "(register(..., values=...)), so its map keys cannot be checked"]
    return [f"{key}.map: map key '{k}' is not a value {field} can return "
            f"(its values: {', '.join(repr(v) for v in values)}) — it would never match"
            for k in mapping if not any(equals(k, v) for v in values)]


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
    out += data_declaration_problems(rule, REQUIRES)
    out += [f"views: unknown view '{v}' (known: {_known(VIEWS)})"
            for v in rule.views if v not in VIEWS]
    return out


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
        return legacy_threshold_form_problems(value, path) if isinstance(value, dict) \
            else [f"{path}: must be a mapping"]
    if key == "message":
        return message_problems_any(rule, value, path)
    if not isinstance(value, str):
        return [f"{path}: must be a string"]
    return []


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
            elif value is None:
                # The engine skips a null override ("removes nothing"), so accepting one
                # would silently drop it — and mislead the per-profile checks below.
                out.append(f"{path}.{key}: null removes nothing — omit the key, "
                           "or give the replacement value")
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


def has_no_logic(rule: Rule) -> bool:
    """A declarative rule with no `aggregate`: nothing the engine could run. Allowed
    only for a retired rule that keeps an id allocated (H6, deferred)."""
    return rule.implementation == "declarative" and not rule.aggregate


def _revival_problems(rule: Rule) -> List[str]:
    """A retired rule with no logic must stay retired under every profile."""
    return [f"profiles.{pid}.status: a retired rule with no logic (no aggregate, no "
            "implementation) cannot be revived — give it its logic first"
            for pid, override in rule.profiles.items()
            if isinstance(override, dict) and override.get("status") == "active"]


def _engine_problems(rule: Rule, cat: Catalog) -> List[str]:
    """What the engine interprets: the aggregate block, the message's placeholders,
    the legacy threshold's placeholders, and where severity comes from. A retired rule
    with no logic has none of these; it may only never be revived."""
    if rule.status == "retired" and has_no_logic(rule):
        return _revival_problems(rule)
    out = code_rule_aggregate_problems(rule) if CODE_IMPL.match(rule.implementation) \
        else aggregate_problems(rule.aggregate, rule.scope, rule.implementation)
    out += message_problems_any(rule, rule.message, "message")
    out += legacy_threshold_form_problems(rule.legacy_threshold, "legacy_threshold")
    profiles = list(cat.profiles) or [""]
    if CODE_IMPL.match(rule.implementation):
        out += code_rule_problems(rule, profiles)
    elif rule.implementation == "declarative":
        out += _severity_source_by_profile(rule, cat) + _shadowed_severity_problems(rule, cat)
    else:
        return out
    return out + form_coverage_problems(rule, profiles)


def _severity_source_by_profile(rule: Rule, cat: Catalog) -> List[str]:
    """The mode's severity source must exist under EVERY profile — a profile block
    replaces bands/severity but cannot supply them for the others."""
    by_problem: Dict[str, List[str]] = {}
    for pid in cat.profiles or [""]:
        override = profile_override(rule, pid)
        has_bands = override.get("bands", rule.bands) is not None
        has_severity = override.get("severity", rule.severity) is not None
        for problem in severity_source_problems(rule.aggregate, has_bands, has_severity):
            by_problem.setdefault(problem, []).append(pid)
    return [f"{problem} (profile: {_known(pids)})" if pids != [""] else problem
            for problem, pids in by_problem.items()]


def _shadowed_severity_problems(rule: Rule, cat: Catalog) -> List[str]:
    """A `severity` that bands override would be silently dropped: where bands are in
    force, they alone set the severity. A catalog `severity` is legitimate while at least
    one profile runs without bands; a profile's `severity` only where it does."""
    out: List[str] = []
    banded_everywhere = bool(cat.profiles)
    for pid in cat.profiles:
        override = profile_override(rule, pid)
        banded = override.get("bands", rule.bands) is not None
        banded_everywhere = banded_everywhere and banded
        if banded and "severity" in override:
            out.append(f"profiles.{pid}.severity has no effect: bands set the severity "
                       f"under profile {pid}")
    if rule.severity is not None and banded_everywhere:
        out.append("severity has no effect: bands set the severity under every profile")
    return out


def rule_problems(rule: Rule, cat: Catalog) -> List[str]:
    """Every problem in one rule, each prefixed `<file>: <id>:`."""
    msgs = (_basic_problems(rule, cat) + implementation_problems(rule)
            + _engine_problems(rule, cat) + bands_problems(rule.bands, "bands")
            + _severity_problems(rule.severity, "severity")
            + _profile_override_problems(rule, cat) + _examples_problems(rule, cat)
            + rule_consistency_problems(rule, cat))
    return [f"{rule.source_file}: {rule.id}: {m}" for m in msgs]


# ── categories, profiles, raw files ─────────────────────────────────────────

def _category_problems(cat: Catalog) -> List[str]:
    out: List[str] = []
    if not cat.categories:
        out.append(f"{CATEGORIES_FILE}: -: at least one category is required")
    seen: Dict[int, str] = {}
    angles: Dict[str, str] = {}
    for c in cat.categories.values():
        if not c.label.strip():
            out.append(f"{CATEGORIES_FILE}: {c.id}: label is required")
        if c.order in seen:
            out.append(f"{CATEGORIES_FILE}: {c.id}: order {c.order} repeats {seen[c.order]}")
        seen.setdefault(c.order, c.id)
        out += _angle_key_problems(c.id, c.angle_key, angles)
    return out + category_prose_problems(cat, CATEGORIES_FILE)


def _angle_key_problems(cid: str, angle_key: str, seen: Dict[str, str]) -> List[str]:
    """`angle_key` is the legacy `Finding.angle` value a rule in this category emits
    (its first category's); two categories sharing one would merge in `by_angle`."""
    if not angle_key.strip():
        return [f"{CATEGORIES_FILE}: {cid}: angle_key is required "
                "(the legacy Finding.angle value, e.g. data_modeling)"]
    if angle_key in seen:
        return [f"{CATEGORIES_FILE}: {cid}: angle_key '{angle_key}' repeats {seen[angle_key]}"]
    seen[angle_key] = cid
    return []


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
    problems = _category_problems(cat) + _profile_problems(cat) + registry_read_problems()
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
