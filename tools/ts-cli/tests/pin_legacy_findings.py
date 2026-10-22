"""Pin the legacy check findings for every committed audit input — run once, before
Task 12b deleted ``ts_cli/audit/checks_*.py``.

    PYTHONPATH=tools/ts-cli python tools/ts-cli/tests/pin_legacy_findings.py

writes ``tests/audit_rule_fixtures/legacy_findings.json.gz``: for every input in
``AI_INPUTS``, ``P_INPUTS``, ``S_INPUTS``, ``D_INPUTS`` and ``H_INPUTS``, under each
profile, each legacy check run ALONE on its own deep copy of the context with
``ctx.assessment`` set to the profile (as the equivalence gate's legacy side ran it).
An entry holds the check's findings (``Finding.to_dict()``), or ``"RAISES"`` when the
check raised; a check that found nothing has no entry.

Before writing, it proves two things, and refuses to write otherwise:

- running a category's checks one by one gives the same findings as running them in
  sequence on one shared copy (the equivalence tests' form), wherever the category ran;
- the JSON round trip is exact under ``compare_findings`` (types, ``None`` vs ``""``,
  ``-0.0``, key order).

This script needs the legacy modules, so it cannot run after Task 12b; the commit that
deletes them deletes it too. ``test_audit_pinned_findings.py`` is what keeps checking
the catalog against the pinned answers.
"""
from __future__ import annotations

import copy
import gzip
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import audit_rule_fixtures as fx  # noqa: E402
from ts_cli.audit.equivalence import ANGLE_MODULES, compare_findings  # noqa: E402

OUT = HERE / "audit_rule_fixtures" / "legacy_findings.json.gz"
PROFILES = ("spotter", "general")


def committed_inputs() -> dict:
    inputs: dict = {}
    for named in (fx.AI_INPUTS, fx.P_INPUTS, fx.S_INPUTS, fx.D_INPUTS, fx.H_INPUTS):
        for name, build in named.items():
            if name in inputs:
                assert inputs[name] is build, f"input name {name} names two builders"
                continue
            inputs[name] = build
    return inputs


def _rule_id(check) -> str:
    return check.__name__.replace("check_", "").upper()


def _one_by_one(ctx, profile: str, checks) -> dict:
    out = {}
    for check in checks:
        c = copy.deepcopy(ctx)
        c.assessment = profile
        try:
            out[_rule_id(check)] = [f.to_dict() for f in check(c)]
        except Exception:  # noqa: BLE001 - recorded as RAISES
            out[_rule_id(check)] = "RAISES"
    return out


def _shared_copy_agrees(ctx, profile: str, checks, per_rule: dict) -> bool:
    shared = copy.deepcopy(ctx)
    shared.assessment = profile
    try:
        together = [f.to_dict() for check in checks for f in check(shared)]
    except Exception:  # noqa: BLE001 - the category did not run; nothing to compare
        return True
    if "RAISES" in per_rule.values():
        return False
    return compare_findings(together, [f for v in per_rule.values() for f in v])["identical"]


def pin() -> dict:
    findings: dict = {}
    for name, build in committed_inputs().items():
        for profile in PROFILES:
            for category, module in ANGLE_MODULES.items():
                ctx = build()
                per_rule = _one_by_one(ctx, profile, module.ALL_CHECKS)
                if not _shared_copy_agrees(ctx, profile, module.ALL_CHECKS, per_rule):
                    raise SystemExit(f"{name}/{profile}/{category}: one-by-one differs "
                                     "from the shared-copy run")
                for rule_id, found in per_rule.items():
                    if found:
                        findings.setdefault(name, {}).setdefault(profile, {})[rule_id] = found
    return findings


def _round_trip_exact(findings: dict, back: dict) -> bool:
    for name, profiles in findings.items():
        for profile, rules in profiles.items():
            for rule_id, found in rules.items():
                got = back[name][profile][rule_id]
                same = got == found if found == "RAISES" else \
                    compare_findings(found, got)["identical"]
                if not same:
                    return False
    return True


def main() -> int:
    findings = pin()
    doc = {
        "about": "Legacy ts-audit findings (ts_cli/audit/checks_*.py, deleted in Task "
                 "12b) for every committed input in tests/audit_rule_fixtures, per "
                 "profile and rule; written by tests/pin_legacy_findings.py from "
                 "commit 11388ab7. An absent (input, profile, rule) entry: the "
                 "legacy check found nothing. \"RAISES\": it raised. Synthetic data only.",
        "profiles": list(PROFILES),
        "inputs": sorted(committed_inputs()),
        "findings": findings,
    }
    text = json.dumps(doc, separators=(",", ":"))
    if not _round_trip_exact(findings, json.loads(text)["findings"]):
        raise SystemExit("the JSON round trip is not exact")
    with OUT.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", filename="",
                                              mtime=0) as fh:
        fh.write(text.encode("utf-8"))
    n = sum(len(v) for p in findings.values() for r in p.values() for v in r.values()
            if v != "RAISES")
    print(f"wrote {OUT.name}: {len(doc['inputs'])} inputs, {n} findings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
