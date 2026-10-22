"""The pinned audit findings: where they live, which rules they cover, and how the
catalog's current answer for one (input, profile, rule) is computed.

Shared by `test_audit_pinned_findings.py` (which compares) and `repin_findings.py`
(which rewrites named entries from the current catalog). See the test module's
docstring for the workflow.
"""
from __future__ import annotations

import gzip
import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Union

import audit_rule_fixtures as fx
from audit_run_rule import active_rule_ids, catalog, findings_by_rule
from ts_cli.audit.engine.run import run_rule as engine_run_rule
from ts_cli.audit.engine.run import selected_rules

PINNED = Path(__file__).resolve().parent / "audit_rule_fixtures" / "legacy_findings.json.gz"
PROFILES = ["spotter", "general"]
OWN_INPUTS = {"A": fx.AI_INPUTS, "D": fx.D_INPUTS, "H": fx.H_INPUTS, "P": fx.P_INPUTS,
              "S": fx.S_INPUTS}
RAISES = "RAISES"

#: The rule ids the pinned file covers: the 51 the legacy check functions ran when
#: they were pinned (1ddb3185). FROZEN. The source of truth is the pin file's own
#: `rules` list; this mirror must equal it (test_audit_pinned_findings.py fails
#: otherwise), so the set cannot shrink or grow by editing one side. A rule added to the
#: catalog later is not pinned; its `fires`/`silent` examples are its net. A pinned rule
#: is re-pinned with `repin_findings.py --rule`; it leaves the set only through
#: `repin_findings.py --drop-rule`, which prints every entry it removes.
PINNED_RULE_IDS = (
    "A1", "A2", "A3", "A4", "A5", "A6",
    "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9", "D10", "D11", "D12",
    "H1", "H2", "H3", "H4", "H5", "H7", "H8", "H9", "H10",
    "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P11", "P13", "P14", "P15",
    "P16", "P17", "P18",
    "S1", "S2", "S3", "S4", "S5", "S8", "S9", "S10",
)

Entry = Union[str, List[dict]]


def committed_inputs() -> dict:
    """Every committed input builder by name, each once (a name listed in two
    categories' inputs is the same builder), in the order the pin was written:
    AI, P, S, D, H inputs."""
    inputs: dict = {}
    for named in (fx.AI_INPUTS, fx.P_INPUTS, fx.S_INPUTS, fx.D_INPUTS, fx.H_INPUTS):
        for name, build in named.items():
            inputs.setdefault(name, build)
    return inputs


def load() -> dict:
    with gzip.open(PINNED, "rt", encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def pinned() -> dict:
    """The pinned document, read once per process (never mutate it)."""
    return load()


def strays(doc: dict) -> List[str]:
    """Entries outside the document's own frozen sets — a rule not in `doc["rules"]`, a
    profile not in PROFILES, an input not in `doc["inputs"]`. `write` refuses them:
    nothing leaves the pin, or enters it, without the re-pin helper naming it."""
    rules, inputs = set(doc["rules"]), set(doc["inputs"])
    out = []
    for name, profiles in doc["findings"].items():
        if name not in inputs:
            out.append(f"input {name}")
        for profile, found in profiles.items():
            if profile not in PROFILES:
                out.append(f"profile {profile} ({name})")
            out += [f"rule {r} ({name}/{profile})" for r in found if r not in rules]
    return out


def _canonical(doc: dict) -> dict:
    """Entries in one fixed order — inputs as `committed_inputs()` lists them, then any
    other pinned input in `doc["inputs"]` order; profiles as PROFILES; rules as
    `doc["rules"]` — the order the original pin was written in, so a re-pin never
    reorders what it did not change. Never drops an entry: `write` has already
    refused anything outside the frozen sets."""
    findings = doc["findings"]
    names = [n for n in committed_inputs() if n in findings]
    names += [n for n in doc["inputs"] if n in findings and n not in names]
    return {n: {p: {r: findings[n][p][r] for r in doc["rules"] if r in findings[n][p]}
                for p in PROFILES if p in findings[n]}
            for n in names}


def write(doc: dict) -> None:
    """Write `doc` exactly as the original pin was written: compact JSON in canonical
    entry order, gzip with mtime 0 and no file name — the same content always gives the
    same bytes. ValueError, and nothing written, when an entry lies outside the
    document's frozen sets (see `strays`)."""
    bad = strays(doc)
    if bad:
        raise ValueError(f"pin entries outside its frozen sets: {', '.join(bad[:10])}")
    canonical = _canonical(doc)
    assert sum(len(r) for p in canonical.values() for r in p.values()) == \
        sum(len(r) for p in doc["findings"].values() for r in p.values())
    doc = {**doc, "findings": canonical}
    text = json.dumps(doc, separators=(",", ":"))
    with PINNED.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", filename="",
                                                 mtime=0) as fh:
        fh.write(text.encode("utf-8"))


def entry(doc: dict, name: str, profile: str, rule_id: str) -> Entry:
    """The pinned findings ([] when none were pinned), or "RAISES"."""
    return doc["findings"].get(name, {}).get(profile, {}).get(rule_id, [])


def pinned_rules(category: str, doc: dict = None) -> List[str]:
    """Every pinned rule of the category, WHATEVER its status: a rule retired at base,
    or under a profile, reports nothing there, so its pin must say [] — retiring a
    pinned rule fails the comparison until it is re-pinned."""
    doc = doc or pinned()
    return [r for r in doc["rules"] if category in catalog().rules[r].categories]


def active_pinned_rules(category: str, profile: str, doc: dict = None) -> List[str]:
    """The pinned rules of the category that are ACTIVE under `profile` — effective
    status, the profile's `status` override applied — in catalog order: the ones
    that must fire somewhere in their category's inputs."""
    rules = set((doc or pinned())["rules"])
    return [r.id for r in selected_rules(catalog(), [category], profile) if r.id in rules]


def catalog_by_rule(build, category: str, profile: str):
    """The catalog's findings by rule for one input (as dicts), and the rules that
    raised. The whole category runs first, as in an audit; only if that raises does
    each rule run alone, so one raising rule cannot hide what the others report."""
    try:
        got = findings_by_rule(build(), category, profile)
        return {r: [f.to_dict() for f in fs] for r, fs in got.items()}, set()
    except Exception:  # noqa: BLE001 - narrowed rule by rule below
        pass
    got: Dict[str, List[dict]] = {}
    raised = set()
    for rule_id in active_rule_ids(category):
        try:
            found = engine_run_rule(build(), catalog(), rule_id, profile)
        except Exception:  # noqa: BLE001 - the caller decides whether a raise is allowed
            raised.add(rule_id)
            continue
        if found:
            got[rule_id] = [f.to_dict() for f in found]
    return got, raised


#: The finding fields added by the catalog, which the pin does not compare
#: (`compare_findings` ignores them), stored as the legacy Finding left them so every
#: entry has one shape and a re-pin of an unchanged rule is byte-identical.
UNCOMPARED_AS_PINNED = {"categories": [], "bands": None}


def _as_pinned(finding: dict) -> dict:
    return {k: (UNCOMPARED_AS_PINNED[k] if k in UNCOMPARED_AS_PINNED else v)
            for k, v in finding.items()}


def current(build, rule_id: str, profile: str) -> Entry:
    """What the catalog reports today for one rule over one input, in the pin's shape:
    its findings, or "RAISES" when the rule raises on it."""
    category = catalog().rules[rule_id].categories[0]
    got, raised = catalog_by_rule(build, category, profile)
    if rule_id in raised:
        return RAISES
    return [_as_pinned(f) for f in got.get(rule_id, [])]
