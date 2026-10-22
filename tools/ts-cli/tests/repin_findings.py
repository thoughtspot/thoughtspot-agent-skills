"""Re-pin entries of the pinned audit findings from the CURRENT catalog.

    PYTHONPATH=tools/ts-cli python tools/ts-cli/tests/repin_findings.py --rule P8
    PYTHONPATH=tools/ts-cli python tools/ts-cli/tests/repin_findings.py --rule D11 \\
        --input data_fanout_many_to_many_dimension
    PYTHONPATH=tools/ts-cli python tools/ts-cli/tests/repin_findings.py --input sec_names_none
    ... --dry-run     print the before/after, write nothing

`tests/audit_rule_fixtures/legacy_findings.json.gz` pins what the 51 legacy rules
reported over every committed input (test_audit_pinned_findings.py). When one of
those rules is changed ON PURPOSE — a threshold, a severity, a message, a defect fixed
— or an input builder changes, the pin must move with it. This rewrites only the
named entries: every input for `--rule` (both profiles), every pinned rule for
`--input`, or the one (rule, input) pair for both. Everything else is left byte-for-byte
as it was, and the file is rewritten deterministically (gzip mtime 0).

It prints a readable before/after for each entry it changes — the findings that
appear, disappear, or change a field — because the gzip shows only as "Binary files
differ" in a PR. Paste that output into the PR description: it is the review artefact
for the regression net moving. It exits 1 without writing when a name is unknown, or
when `--rule` names a rule outside the frozen pinned set (a rule added after the pin is
held to its own catalog examples, not to this file).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_pinned as ap  # noqa: E402
from ts_cli.audit.equivalence import compare_findings, finding_key  # noqa: E402


def _describe(old: ap.Entry, new: ap.Entry) -> list:
    """Readable lines for one changed entry."""
    if ap.RAISES in (old, new):
        return [f"    before: {old if old == ap.RAISES else f'{len(old)} finding(s)'}",
                f"    after:  {new if new == ap.RAISES else f'{len(new)} finding(s)'}"]
    res = compare_findings(old, new)
    lines = [f"    - {finding_key(f)} {f.get('severity')} metric={f.get('metric')!r}"
             for f in res["only_old"]]
    lines += [f"    + {finding_key(f)} {f.get('severity')} metric={f.get('metric')!r}"
              for f in res["only_new"]]
    lines += [f"    ~ {c['key']} {c['field']}: {c['old']!r} -> {c['new']!r}"
              for c in res["changed"]]
    return lines


def _same(old: ap.Entry, new: ap.Entry) -> bool:
    if ap.RAISES in (old, new):
        return old == new
    return compare_findings(old, new)["identical"]   # as the test compares: a multiset


def _targets(args, inputs: dict) -> list:
    rules = args.rule or list(ap.PINNED_RULE_IDS)
    names = args.input or list(inputs)
    return [(n, r) for n in names for r in rules]


def _set(doc: dict, name: str, profile: str, rule_id: str, value: ap.Entry) -> None:
    profiles = doc["findings"].setdefault(name, {})
    rules = profiles.setdefault(profile, {})
    if value:
        rules[rule_id] = value
    else:
        rules.pop(rule_id, None)
    if not rules:
        profiles.pop(profile)
    if not profiles:
        doc["findings"].pop(name)


def _validate(args, inputs: dict) -> list:
    errors = [f"unknown input '{n}'" for n in (args.input or []) if n not in inputs]
    errors += [f"rule '{r}' is not in the frozen pinned set (PINNED_RULE_IDS); a rule "
               "added after the pin is held to its catalog examples" for r in (args.rule or [])
               if r not in ap.PINNED_RULE_IDS]
    if not (args.rule or args.input):
        errors.append("name at least one --rule or --input")
    return errors


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--rule", action="append", help="rule id (repeatable)")
    p.add_argument("--input", action="append", help="committed input name (repeatable)")
    p.add_argument("--dry-run", action="store_true", help="print the diff, write nothing")
    args = p.parse_args(argv)
    inputs = ap.committed_inputs()
    errors = _validate(args, inputs)
    if errors:
        for e in errors:
            print(f"repin: {e}", file=sys.stderr)
        return 1
    doc = ap.load()
    if sorted(inputs) != doc["inputs"]:
        doc["inputs"] = sorted(inputs)   # an input added or removed on purpose
    changed = 0
    for name, rule_id in _targets(args, inputs):
        for profile in ap.PROFILES:
            old = ap.entry(doc, name, profile, rule_id)
            new = ap.current(inputs[name], rule_id, profile)
            if _same(old, new):
                continue
            changed += 1
            print(f"{rule_id} / {name} / {profile}:")
            print("\n".join(_describe(old, new)))
            _set(doc, name, profile, rule_id, new)
    verb = "would change" if args.dry_run else "changed"
    print(f"repin: {verb} {changed} (input, profile, rule) entr{'y' if changed == 1 else 'ies'}")
    if changed and not args.dry_run:
        ap.write(doc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
