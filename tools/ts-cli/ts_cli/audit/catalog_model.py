"""Audit rule catalog — the data model and loader.

`ts audit`'s checks are data: YAML under `ts_cli/audit/catalog/`.

    catalog/categories.yaml   [{id, label, order, description, angle_key}] — report tabs
    catalog/profiles.yaml     [{id, label, default, description}]          — assessment profiles
    catalog/rules/*.yaml      [rule, ...]                        — one entry per rule

A rule entry (every key but `id`, `title`, `categories`, `scope` is optional):

    - id: A6                        # stable; never reused, a retired rule keeps it
      title: ...
      description: ...
      status: active                # active | retired
      categories: [A]               # the first one's angle_key is the finding's `angle`
      requires: [model_tml]         # data the rule reads; an object lacking it is skipped
      uses: [ai_instructions]       # conditional data it reads WITHOUT skipping an object
                                    # lacking it: fetched, never gates (catalog_uses.py)
      implementation: declarative   # or code:<name>
      scope: model                  # the object a finding is about
      aggregate: {mode: ratio, over: model.column, where: {...}, match: {...}}
      bands: {direction: higher_is_better, unit: percent,
              levels: [{op: lt, value: 40, severity: HIGH}, ...]}   # worst first
      severity: HIGH                # fixed severity, or a mapping, for presence rules
      profiles: {general: {bands: ...}}   # per-profile overrides (overridable keys only)
      message: "{matched}/{total} ..."   # or {by_severity: {SEVERITY: template}}
      legacy_threshold: {...}       # reproduction of the pre-catalog `threshold` dict
                                    # (or {by_severity: {SEVERITY: {...}}}; catalog_forms.py)
      remediation: ...
      examples: {fires: {fixture, profile, severity}, silent: {fixture, profile}}
      views: [cleanup]              # report views the rule feeds (duplicates | cleanup)

The loader turns YAML into dataclasses and raises `CatalogError(file, rule_id,
message)` only for problems that stop it building them (unreadable YAML, a file that is
not a list, an entry that is not a mapping or has no id, a list-valued key given a
scalar). Everything else — unknown keys, vocabulary, ordering, duplicates — is the
validator's job (`catalog_validate.py`), which collects every problem at once.

Kept importable on Python 3.9 with only PyYAML: tools/validate/check_audit_catalog.py
loads this module without the rest of ts_cli.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml

CATALOG_DIR = Path(__file__).resolve().parent / "catalog"
CATEGORIES_FILE = "categories.yaml"
PROFILES_FILE = "profiles.yaml"
RULES_DIR = "rules"


class CatalogError(Exception):
    """A catalog file the loader cannot turn into dataclasses."""

    def __init__(self, file: str, rule_id: Optional[str], message: str):
        self.file = file
        self.rule_id = rule_id
        self.message = message
        super().__init__(f"{file}: {rule_id or '-'}: {message}")


@dataclass
class Band:
    op: str
    value: float
    severity: str


@dataclass
class Bands:
    direction: str
    unit: str
    levels: List[Band]


@dataclass
class Rule:
    id: str
    title: str
    description: str = ""
    status: str = "active"
    categories: List[str] = field(default_factory=list)
    requires: List[str] = field(default_factory=list)
    uses: List[str] = field(default_factory=list)
    implementation: str = "declarative"
    scope: str = ""
    aggregate: Dict[str, Any] = field(default_factory=dict)
    bands: Optional[Bands] = None
    severity: Union[Dict[str, Any], str, None] = None
    profiles: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    message: Union[str, Dict[str, Any]] = ""   # a template, or {by_severity: {...}}
    legacy_threshold: Optional[Dict[str, Any]] = None
    remediation: str = ""
    examples: Dict[str, Any] = field(default_factory=dict)
    views: List[str] = field(default_factory=list)
    source_file: str = ""


@dataclass
class Category:
    id: str
    label: str
    order: int
    description: str = ""
    # The legacy `Finding.angle` value ("ai", "data_modeling", ...) a rule whose first
    # category this is emits. The letter `id` is the selector; findings keep `angle`.
    angle_key: str = ""


@dataclass
class Profile:
    id: str
    label: str
    default: bool = False
    description: str = ""


@dataclass
class Catalog:
    categories: Dict[str, Category]
    profiles: Dict[str, Profile]
    rules: Dict[str, Rule]

    def default_profile(self) -> Optional[str]:
        """Id of the profile marked `default: true` (first one if several)."""
        return next((p.id for p in self.profiles.values() if p.default), None)


def profile_override(rule: Rule, pid: str) -> Dict[str, Any]:
    """The profile's overrides as the engine applies them: a null value is skipped
    (bands.effective — it removes nothing), so it is dropped here too. The one reading
    every validator check that asks "what holds under this profile" uses."""
    override = rule.profiles.get(pid)
    return {k: v for k, v in override.items() if v is not None} \
        if isinstance(override, dict) else {}


# ── raw YAML ────────────────────────────────────────────────────────────────

def _read_list(path: Path, rel: str) -> List[Dict[str, Any]]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CatalogError(rel, None, f"cannot read: {exc}") from exc
    except yaml.YAMLError as exc:
        raise CatalogError(rel, None, f"invalid YAML: {exc}") from exc
    if data is None:
        data = []
    if not isinstance(data, list):
        raise CatalogError(rel, None, f"must be a YAML list, got {type(data).__name__}")
    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise CatalogError(rel, None, f"entry #{i + 1} must be a mapping")
        if not entry.get("id"):
            raise CatalogError(rel, None, f"entry #{i + 1} has no id")
    return data


def load_raw(root: Optional[Path] = None) -> Dict[str, List[Dict[str, Any]]]:
    """Every catalog file as parsed YAML, keyed by path relative to `root`.

    Keys: `categories.yaml`, `profiles.yaml`, then `rules/<name>.yaml` in name order.
    The validator needs this view for what dataclasses cannot hold: unknown keys and
    ids repeated across files.
    """
    root = Path(root) if root is not None else CATALOG_DIR
    if not root.is_dir():
        raise CatalogError(str(root), None, "catalog directory not found")
    raw = {}
    for rel in (CATEGORIES_FILE, PROFILES_FILE):
        raw[rel] = _read_list(root / rel, rel)
    for path in _rule_files(root / RULES_DIR):
        rel = f"{RULES_DIR}/{path.name}"
        raw[rel] = _read_list(path, rel)
    return raw


def _rule_files(rules_dir: Path) -> List[Path]:
    """Every `*.yaml` in rules/. Anything else there is an error, not silently skipped:
    a `rules/ai.yml` would otherwise drop its rules and still PASS. Dotfiles (editor and
    Finder litter such as .DS_Store) are ignored."""
    if not rules_dir.is_dir():
        raise CatalogError(RULES_DIR, None, "rules directory not found")
    paths = sorted(p for p in rules_dir.iterdir() if not p.name.startswith("."))
    for path in paths:
        if not path.is_file() or path.suffix != ".yaml":
            raise CatalogError(f"{RULES_DIR}/{path.name}", None,
                               "only .yaml rule files belong in rules/ (rename or remove it)")
    return paths


# ── dataclasses ─────────────────────────────────────────────────────────────

def _expect(value: Any, kind: Any, default: Any, file: str, rid: str, key: str) -> Any:
    """`value` if it is a `kind` (a type or tuple of types), `default` if absent."""
    if value is None:
        return default
    if not isinstance(value, kind):
        kinds = kind if isinstance(kind, tuple) else (kind,)
        wanted = " or ".join(k.__name__ for k in kinds)
        raise CatalogError(file, rid, f"'{key}' must be a {wanted}, "
                                      f"got {type(value).__name__}")
    return value


def parse_bands(raw: Any, file: str, rid: str, key: str = "bands") -> Optional[Bands]:
    """`{direction, unit, levels: [{op, value, severity}]}` → Bands (None stays None)."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise CatalogError(file, rid, f"'{key}' must be a mapping")
    levels = raw.get("levels")
    if not isinstance(levels, list) or not all(isinstance(lv, dict) for lv in levels):
        raise CatalogError(file, rid, f"'{key}.levels' must be a list of mappings")
    return Bands(str(raw.get("direction", "")), str(raw.get("unit", "")),
                 [_parse_band(lv, file, rid, key) for lv in levels])


def _parse_band(raw: Dict[str, Any], file: str, rid: str, key: str) -> Band:
    value = raw.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CatalogError(file, rid, f"'{key}.levels' value must be a number, got {value!r}")
    return Band(str(raw.get("op", "")), float(value), str(raw.get("severity", "")))


def _rule_from_dict(d: Dict[str, Any], file: str) -> Rule:
    rid = str(d["id"])

    def get(key: str, kind: type, default: Any) -> Any:
        return _expect(d.get(key), kind, default, file, rid, key)

    return Rule(
        id=rid,
        title=get("title", str, ""),
        description=get("description", str, ""),
        status=get("status", str, "active"),
        categories=list(get("categories", list, [])),
        requires=list(get("requires", list, [])),
        uses=list(get("uses", list, [])),
        implementation=get("implementation", str, "declarative"),
        scope=get("scope", str, ""),
        aggregate=dict(get("aggregate", dict, {})),
        bands=parse_bands(d.get("bands"), file, rid),
        severity=_expect(d.get("severity"), (str, dict), None, file, rid, "severity"),
        profiles=dict(get("profiles", dict, {})),
        message=_expect(d.get("message"), (str, dict), "", file, rid, "message"),
        legacy_threshold=get("legacy_threshold", dict, None),
        remediation=get("remediation", str, ""),
        examples=dict(get("examples", dict, {})),
        views=list(get("views", list, [])),
        source_file=file,
    )


def _categories(rows: List[Dict[str, Any]]) -> Dict[str, Category]:
    cats = [Category(str(r["id"]), str(r.get("label", "")),
                     int(_expect(r.get("order"), int, 0, CATEGORIES_FILE, str(r["id"]), "order")),
                     str(r.get("description", "")),
                     str(_expect(r.get("angle_key"), str, "", CATEGORIES_FILE, str(r["id"]),
                                 "angle_key")))
            for r in rows]
    return {c.id: c for c in sorted(cats, key=lambda c: c.order)}


def _profiles(rows: List[Dict[str, Any]]) -> Dict[str, Profile]:
    return {str(r["id"]): Profile(str(r["id"]), str(r.get("label", "")),
                                  bool(r.get("default", False)),
                                  str(r.get("description", "")))
            for r in rows}


def build_catalog(raw: Dict[str, List[Dict[str, Any]]]) -> Catalog:
    """Dataclasses from `load_raw` output. A repeated rule id keeps its first entry —
    the validator, given the same `raw`, reports the repeat."""
    rules: Dict[str, Rule] = {}
    for file, entries in raw.items():
        if not file.startswith(f"{RULES_DIR}/"):
            continue
        for entry in entries:
            rule = _rule_from_dict(entry, file)
            rules.setdefault(rule.id, rule)
    return Catalog(_categories(raw.get(CATEGORIES_FILE, [])),
                   _profiles(raw.get(PROFILES_FILE, [])), rules)


def load_catalog(root: Optional[Path] = None) -> Catalog:
    """Load the catalog at `root` (default: the package's own `catalog/`)."""
    return build_catalog(load_raw(root))
