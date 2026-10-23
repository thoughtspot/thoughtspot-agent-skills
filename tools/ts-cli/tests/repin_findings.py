"""Re-pin entries of the pinned audit findings from the CURRENT catalog.

    PYTHONPATH=tools/ts-cli python tools/ts-cli/tests/repin_findings.py --rule P8
    PYTHONPATH=tools/ts-cli python tools/ts-cli/tests/repin_findings.py --rule D11 \\
        --input data_fanout_many_to_many_dimension
    PYTHONPATH=tools/ts-cli python tools/ts-cli/tests/repin_findings.py --input sec_names_none
    ... --dry-run                 print the before/after, write nothing
    ... --drop-rule D3            take a rule out of the pin (prints every entry removed)
    ... --drop-input <name>       take a no-longer-committed input out (prints its entries)

`tests/audit_rule_fixtures/legacy_findings.json.gz` pins what the 51 legacy rules
reported over every committed input (test_audit_pinned_findings.py). When one of
those rules is changed ON PURPOSE — a threshold, a severity, a message, a defect fixed,
its `status` (at base or under a profile) — or an input builder changes, the pin must
move with it. `--rule` / `--input` rewrite only the named entries from the current
catalog: every input for `--rule` (both profiles), every pinned rule for `--input`, or
the one (rule, input) pair for both. A rule that is not active under a profile pins
to [] for that profile. Naming a committed input the pin does not have yet adds it.

Nothing else changes, and nothing leaves the pin silently: a rule leaves the frozen set
only through `--drop-rule` (refused while the rule is active under any profile: retire
it first), an input only through `--drop-input`, and each prints every
entry it removes. The file is rewritten deterministically (canonical order, gzip
mtime 0), and the write refuses any entry outside the file's own frozen sets.

It prints a readable before/after for each entry it changes — the findings that
appear, disappear, or change a field — because the gzip shows only as "Binary files
differ" in a PR. Paste that output into the PR description: it is the review artefact
for the regression net moving. It exits 1 without writing when a name is unknown, or
when `--rule` names a rule outside the frozen set (a rule added after the pin is held to
its own catalog examples, not to this file).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_pinned as ap  # noqa: E402
from ts_cli.audit.equivalence import compare_findings, finding_key  # noqa: E402


def _summary(value: ap.Entry) -> str:
    return value if value == ap.RAISES else f"{len(value)} finding(s)"


def _describe(old: ap.Entry, new: ap.Entry) -> list:
    """Readable lines for one changed entry."""
    if ap.RAISES in (old, new):
        return [f"    before: {_summary(old)}", f"    after:  {_summary(new)}"]
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


def _validate(args, doc: dict, inputs: dict) -> list:
    pinned_inputs, rules = set(doc["inputs"]), set(doc["rules"])
    errors = [f"unknown input '{n}'" for n in (args.input or []) if n not in inputs]
    errors += [f"rule '{r}' is not in the pin's frozen rule set; a rule added after "
               "the pin is held to its catalog examples"
               for r in (args.rule or []) if r not in rules]
    errors += [f"--drop-rule '{r}' is not pinned" for r in (args.drop_rule or [])
               if r not in rules]
    errors += _still_active(args.drop_rule or [], rules)
    errors += [f"--drop-input '{n}' is not pinned" for n in (args.drop_input or [])
               if n not in pinned_inputs]
    errors += [f"--drop-input '{n}' is still a committed input: remove its builder first"
               for n in (args.drop_input or []) if n in inputs]
    if not (args.rule or args.input or args.drop_rule or args.drop_input):
        errors.append("name at least one --rule, --input, --drop-rule or --drop-input")
    return errors


def _still_active(drop_rules: list, pinned: set) -> list:
    """A pinned rule may leave the pin only once it is active under no profile: every
    legitimate change to an active rule is a re-pin, and a retired rule pins to [] at
    no cost — so dropping an active one would only take it out of the regression net."""
    from audit_run_rule import catalog
    from ts_cli.audit.engine.run import selected_rules
    out = []
    for rule_id in (r for r in drop_rules if r in pinned):
        rule = catalog().rules.get(rule_id)
        profiles = [p for p in ap.PROFILES if rule is not None and any(
            r.id == rule_id for r in selected_rules(catalog(), rule.categories, p))]
        if profiles:
            out.append(f"--drop-rule: {rule_id} is still active under {', '.join(profiles)}: "
                       "retire it first (status: retired, at base or per profile)")
    return out


def _drop(doc: dict, args) -> int:
    """Remove the named rules and inputs, printing every entry removed."""
    drop_rules, drop_inputs = set(args.drop_rule or []), set(args.drop_input or [])
    removed = 0
    for name in list(doc["findings"]):
        for profile in list(doc["findings"][name]):
            for rule_id in list(doc["findings"][name][profile]):
                if rule_id in drop_rules or name in drop_inputs:
                    value = doc["findings"][name][profile][rule_id]
                    print(f"{rule_id} / {name} / {profile}: REMOVED ({_summary(value)})")
                    _set(doc, name, profile, rule_id, [])
                    removed += 1
    for rule_id in drop_rules:
        print(f"rule {rule_id}: REMOVED from the pinned rule set")
    for name in drop_inputs:
        print(f"input {name}: REMOVED from the pinned inputs")
    doc["rules"] = [r for r in doc["rules"] if r not in drop_rules]
    doc["inputs"] = [n for n in doc["inputs"] if n not in drop_inputs]
    return removed


def _repin(doc: dict, args, inputs: dict) -> int:
    rules = args.rule or list(doc["rules"])
    names = args.input or [n for n in inputs if n in set(doc["inputs"])]
    for name in names:
        if name not in doc["inputs"]:
            print(f"input {name}: ADDED to the pinned inputs")
            doc["inputs"] = sorted(doc["inputs"] + [name])
    changed = 0
    for name in names:
        for rule_id in rules:
            for profile in ap.PROFILES:
                old = ap.entry(doc, name, profile, rule_id)
                new = ap.current(inputs[name], rule_id, profile)
                if _same(old, new):
                    continue
                changed += 1
                print(f"{rule_id} / {name} / {profile}:")
                print("\n".join(_describe(old, new)))
                _set(doc, name, profile, rule_id, new)
    return changed


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--rule", action="append", help="rule id (repeatable)")
    p.add_argument("--input", action="append", help="committed input name (repeatable)")
    p.add_argument("--drop-rule", action="append", help="remove a rule from the pin")
    p.add_argument("--drop-input", action="append", help="remove a stale input from the pin")
    p.add_argument("--dry-run", action="store_true", help="print the diff, write nothing")
    args = p.parse_args(argv)
    doc = ap.load()
    inputs = ap.committed_inputs()
    errors = _validate(args, doc, inputs)
    if errors:
        for e in errors:
            print(f"repin: {e}", file=sys.stderr)
        return 1
    sets_before = (list(doc["rules"]), list(doc["inputs"]))
    changed = _drop(doc, args)
    if args.rule or args.input:
        changed += _repin(doc, args, inputs)
    sets_changed = sets_before != (doc["rules"], doc["inputs"])
    verb = "would change" if args.dry_run else "changed"
    plural = "y" if changed == 1 else "ies"
    print(f"repin: {verb} {changed} (input, profile, rule) entr{plural}"
          + ("; the pinned rule or input set changed" if sets_changed else ""))
    if (changed or sets_changed) and not args.dry_run:
        ap.write(doc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
