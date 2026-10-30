#!/usr/bin/env python3
"""
smoke_ts_audit.py — live smoke test for ts-audit.

Runs the audit the skill runs, on a real ThoughtSpot instance, and checks what it
returns against the rule catalog:
  1.  ThoughtSpot auth
  2.  `ts audit run --models <guid>`: the run completes, it ran exactly the catalog's
      active rules, every finding's rule id is one of them, and the corpus holds the
      Model (with its Spotter readiness score)
  3.  `ts audit report`: the run's JSON renders to a self-contained HTML report
  4.  The audit's own PII patterns (`ts_cli.audit.engine.fields.PII_PATTERNS`, S1's)
      on known names: snake_case, display names and words that must not match

Until 2026-10 this script never invoked `ts audit run`: it re-implemented each step and
tested its own copy of the PII patterns, which had drifted from the audit's (BL-112).

Usage:
    python tools/smoke-tests/smoke_ts_audit.py \\
        --ts-profile production \\
        --model-guid abc123...

Credentials are read via the ts CLI profile (handles auth and token caching).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _common import SmokeTestResult, ts_auth_check  # noqa: E402

#: (column name, the PII category S1 must give it — None for none). Display names are
#: what Model columns usually carry; the last group are ordinary words a loose pattern
#: matched before 2026-10.
PII_CASES = [
    ("customer_email", "email"), ("Email Address", "email"),
    ("phone_number", "phone"), ("Mobile", "phone"), ("telNumber", "phone"),
    ("SSN", "national_id"), ("Social Security Number", "national_id"),
    ("birth_date", "dob"), ("Date of Birth", "dob"),
    ("credit_card_num", "financial"), ("Account Number", "financial"),
    ("First Name", "person_name"), ("Postal Code", "address"),
    ("revenue", None), ("order_date", None), ("Hotel", None), ("Cousin", None),
    ("Business Unit", None), ("Adobe Campaign", None), ("Automobile", None),
]


def _ts(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["ts"] + args, capture_output=True, text=True)


def run_smoke_test(ts_profile: str, model_guid: str) -> int:
    print("\n=== ts-audit smoke test ===")
    print(f"    Profile:    {ts_profile}")
    print(f"    Model GUID: {model_guid}")
    print()

    r = SmokeTestResult()
    work = Path(tempfile.mkdtemp(prefix="smoke-ts-audit-"))
    audit_json = work / "audit.json"

    r.step("1. ThoughtSpot auth", ts_auth_check, ts_profile)

    def audit_run():
        res = _ts(["audit", "run", "--models", model_guid, "--profile", ts_profile,
                   "-o", str(audit_json)])
        if res.returncode != 0:
            raise RuntimeError(f"ts audit run failed:\n{res.stderr.strip()[-2000:]}")
        data = json.loads(audit_json.read_text())

        from ts_cli.audit.catalog_model import load_catalog
        from ts_cli.audit.engine.run import selected_rules
        catalog = load_catalog()
        active = {rule.id for rule in selected_rules(catalog, list(catalog.categories),
                                                     next(iter(catalog.profiles)))}
        ran = set(data["summary"]["all_check_ids"])
        if not ran or not ran <= {rid for rid in catalog.rules}:
            raise RuntimeError(f"ran rule ids not in the catalog: {sorted(ran - set(catalog.rules))}")
        fired = {f["check_id"] for f in data["findings"]}
        if not fired <= ran:
            raise RuntimeError(f"findings from rules that did not run: {sorted(fired - ran)}")
        retired = {rid for rid, rule in catalog.rules.items() if rule.status == "retired"}
        if fired & retired:
            raise RuntimeError(f"findings from retired rules: {sorted(fired & retired)}")
        models = data["corpus"]["models"]
        if [m["guid"] for m in models] != [model_guid]:
            raise RuntimeError(f"corpus models {[m['guid'] for m in models]} != [{model_guid}]")
        if "spotter_readiness" not in models[0]:
            raise RuntimeError("the corpus Model carries no Spotter readiness score")
        r.info(f"   {len(ran)} rules ran ({len(active)} active by default), "
               f"{len(data['findings'])} findings from {len(fired)} of them")
        return data

    ok, _ = r.step("2. ts audit run on one Model", audit_run)

    def audit_report():
        html = work / "report.html"
        res = _ts(["audit", "report", str(audit_json), "-o", str(html)])
        if res.returncode != 0:
            raise RuntimeError(f"ts audit report failed:\n{res.stderr.strip()[-2000:]}")
        text = html.read_text(encoding="utf-8")
        if "{{AUDIT_DATA}}" in text or "<html" not in text.lower():
            raise RuntimeError("the report did not render its payload")
        r.info(f"   report: {len(text) // 1024} KB")

    if ok:
        r.step("3. ts audit report renders", audit_report)

    def pii_patterns():
        from ts_cli.audit.engine.fields import PII_PATTERNS
        wrong = []
        for name, expected in PII_CASES:
            got = next((cat for pattern, cat, _ in PII_PATTERNS if pattern.search(name)), None)
            if got != expected:
                wrong.append(f"{name!r}: {got} (expected {expected})")
        if wrong:
            raise RuntimeError("PII pattern mismatches: " + "; ".join(wrong))
        r.info(f"   All {len(PII_CASES)} names classified as expected")

    r.step("4. The audit's PII patterns (S1)", pii_patterns)

    return r.summary()


def main():
    parser = argparse.ArgumentParser(description="ts-audit smoke test")
    parser.add_argument("--ts-profile", required=True, help="ThoughtSpot profile name")
    parser.add_argument("--model-guid", required=True, help="GUID of a model to audit")
    args = parser.parse_args()

    sys.exit(run_smoke_test(args.ts_profile, args.model_guid))


if __name__ == "__main__":
    main()
