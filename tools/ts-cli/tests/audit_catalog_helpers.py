"""Shared helpers for the audit rule catalog tests (test_audit_catalog.py and
test_audit_catalog_forms_shipped.py): a rule that validates clean and a temp catalog
holding given rule files."""
from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from ts_cli.audit.catalog_model import load_catalog, load_raw
from ts_cli.audit.catalog_validate import validate_catalog

PKG_CATALOG = Path(__file__).resolve().parents[1] / "ts_cli" / "audit" / "catalog"


def _good_rule(**overrides) -> dict:
    """An A6-shaped rule (the plan's worked example) that validates clean."""
    rule = {
        "id": "A6",
        "title": "Measure AI context coverage below threshold",
        "description": "Visible measures should carry structured AI context.",
        "status": "active",
        "categories": ["A"],
        "requires": ["model_tml"],
        "implementation": "declarative",
        "scope": "model",
        "aggregate": {
            "mode": "ratio",
            "over": "model.column",
            "where": {"all": [
                {"field": "properties.column_type", "eq": "MEASURE"},
                {"not": {"field": "properties.is_hidden", "truthy": True}},
            ]},
            "match": {"field": "properties.ai_context", "nonblank": True},
        },
        "bands": {
            "direction": "higher_is_better",
            "unit": "percent",
            "levels": [
                {"op": "lt", "value": 40, "severity": "HIGH"},
                {"op": "lt", "value": 80, "severity": "MEDIUM"},
            ],
        },
        "profiles": {
            "general": {
                "bands": {"direction": "higher_is_better", "unit": "percent",
                          "levels": [{"op": "lt", "value": 80, "severity": "LOW"}]},
                "legacy_threshold": {"green": 80, "assessment": "{profile_label}"},
            },
        },
        "message": "{matched}/{total} measures have AI context ({pct:.0f}%)",
        "legacy_threshold": {"green": 80, "yellow": 40.0, "assessment": "{profile_label}"},
        "remediation": "Add ai_context to each measure — run /ts-object-model-coach.",
        "examples": {
            "fires": {"fixture": "model_measures_no_ai_context", "profile": "spotter",
                      "severity": "HIGH"},
            "silent": {"fixture": "model_measures_with_ai_context", "profile": "spotter"},
        },
    }
    rule.update(overrides)
    return rule


def _catalog_dir(tmp_path: Path, rules_by_file: dict[str, list]) -> Path:
    """A temp catalog: the shipped categories/profiles plus the given rule files."""
    root = tmp_path / "catalog"
    (root / "rules").mkdir(parents=True)
    for name in ("categories.yaml", "profiles.yaml"):
        shutil.copy(PKG_CATALOG / name, root / name)
    for stem, rules in rules_by_file.items():
        (root / "rules" / f"{stem}.yaml").write_text(yaml.safe_dump(rules, sort_keys=False))
    return root


def _problems(tmp_path: Path, rules_by_file: dict[str, list]) -> list[str]:
    root = _catalog_dir(tmp_path, rules_by_file)
    return validate_catalog(load_catalog(root), load_raw(root))
