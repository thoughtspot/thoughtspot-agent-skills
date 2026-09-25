#!/usr/bin/env python3
"""Round-trip real ThoughtSpot Models through the Apache Ossie converter.

The converter lives in apache/ossie, where CI has no ThoughtSpot cluster. This is
the check that cannot live there: it converts REAL exported Models and measures
what survived. Four defects were found this way that a 940-test suite, Apache's
own validator and five rounds of code review all missed, because every one of
them is invisible to document-level validation.

Two modes:

  export   pull TML from a live cluster into a corpus directory (needs `ts`)
  check    convert an existing corpus and report (no cluster needed)

`check` is the rerunnable half. Once a corpus exists, it works offline and on any
converter revision, which is what makes it useful as a regression gate.

Usage:
    roundtrip.py export --profile se-thoughtspot --corpus ./corpus [--limit 30]
    roundtrip.py check  --corpus ./corpus --converter ~/src/ossie/converters/thoughtspot
    roundtrip.py check  --corpus ./corpus --converter ... --baseline prev.json

Exits non-zero if any model loses structure, fails Apache's validator, or (with
--baseline) regresses against a previous run.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import re
import subprocess
import sys

DIALECT_PORTABLE = "ANSI_SQL"
DIALECT_VENDOR = "THOUGHTSPOT"
#: `dataset.column` inside an expression. Used to check that a portable
#: reference names something the document actually declares -- the defect behind
#: apache/ossie#459, which Apache's validator cannot see because the expression
#: is valid SQL regardless.
#: Either half may be a double-quoted identifier: a display name carrying a space
#: or colon is quoted on emission, and those are exactly the names most likely to
#: differ from a field name. A bare-identifier-only pattern undercounted by 23 of
#: 348 on the corpus -- silently, and in the conservative direction, which is the
#: kind of undercount that reads as reassurance.
_IDENT = r'(?:"[^"]*"|[A-Za-z_]\w*)'
_QUALIFIED_REF = re.compile(rf"(?<![\w.]){_IDENT}\.{_IDENT}")


def _split_ref(text: str) -> tuple[str, str]:
    """`ORDERS."Net Amount"` -> `("ORDERS", "Net Amount")`, quotes stripped."""
    if text.startswith('"'):
        closing = text.index('"', 1)
        return text[1:closing], text[closing + 2:].strip('"')
    dataset, _, column = text.partition(".")
    return dataset, column.strip('"')


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def converter_env(converter: pathlib.Path) -> dict:
    """Environment that forces the CLI to import THIS converter's source.

    A converter's `.venv` records an absolute path to the source tree it was
    created from, so a copied or relocated checkout silently keeps importing the
    original -- the run reports on code you are not testing, and reports it as a
    pass. (`tests/conftest.py` prepends the local `src/`, so pytest is immune and
    only the CLI path is exposed, which is the path this harness uses.) Setting
    PYTHONPATH puts the intended source first regardless.
    """
    return {**os.environ, "PYTHONPATH": str((converter / "src").resolve())}


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

def export_corpus(profile: str, corpus: pathlib.Path, limit: int) -> int:
    """Pull `limit` Models and their associated Tables into `corpus/<guid>/tml/`."""
    import yaml

    found = run(["ts", "metadata", "search", "--subtype", "WORKSHEET",
                 "--profile", profile, "--limit", str(limit)])
    if found.returncode != 0:
        print(f"metadata search failed: {found.stderr.strip()[:300]}", file=sys.stderr)
        return 1
    try:
        models = json.loads(found.stdout)
    except json.JSONDecodeError as exc:
        print(f"metadata search did not return JSON: {exc}", file=sys.stderr)
        return 1

    corpus.mkdir(parents=True, exist_ok=True)
    written = 0
    for entry in models[:limit]:
        guid = entry.get("id") or (entry.get("metadata_header") or {}).get("id")
        if not guid:
            continue
        into = corpus / guid[:8] / "tml"
        into.mkdir(parents=True, exist_ok=True)
        got = run(["ts", "tml", "export", guid, "--profile", profile,
                   "--fqn", "--associated", "--parse", "--no-guid"])
        if got.returncode != 0:
            print(f"  {guid[:8]}: export failed -- {got.stderr.strip()[:160]}")
            continue
        try:
            documents = json.loads(got.stdout)
        except json.JSONDecodeError:
            print(f"  {guid[:8]}: export was not JSON")
            continue
        for index, item in enumerate(documents):
            body = item.get("tml") or {}
            kind = next((k for k in ("model", "table", "sql_view", "worksheet", "view")
                         if k in body), None)
            if kind is None:
                continue
            name = (body[kind].get("name") or f"doc{index}").replace("/", "_").replace(" ", "_")
            suffix = {"worksheet": "model", "view": "sql_view"}.get(kind, kind)
            path, counter = into / f"{name}.{suffix}.tml", 1
            while path.exists():
                counter += 1
                path = into / f"{name}-{counter}.{suffix}.tml"
            path.write_text(yaml.safe_dump(body, sort_keys=False, allow_unicode=True),
                            encoding="utf-8")
        written += 1
        print(f"  {guid[:8]}: exported")
    print(f"\n{written} model(s) written to {corpus}")
    return 0 if written else 1


# ---------------------------------------------------------------------------
# measurement
# ---------------------------------------------------------------------------

def model_column_names(paths) -> set[str]:
    """Every `columns[].name` in the Model document.

    Counts cannot see a rename: tables, columns, formulas and joins are all
    unchanged while a user-visible column comes back called something else. It
    happened on 5 of 31 real models, and one of them (`58435d2b`, `date` ->
    `Date2`) carries `lesson_plan_string` entries still naming the old column,
    so the saved questions break against the returned Model. This harness
    reported "losing structure 0" for that run.
    """
    import yaml
    names: set[str] = set()
    for path in paths:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        model = doc.get("model") or doc.get("worksheet")
        if model:
            names.update(
                c["name"] for c in model.get("columns") or [] if isinstance(c, dict) and "name" in c
            )
    return names


def tml_shape(paths) -> dict:
    """Structural census of a TML document set, for in-vs-out comparison."""
    import yaml
    total = {"tables": 0, "columns": 0, "formulas": 0, "joins": 0}
    for path in paths:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for kind in ("table", "sql_view"):
            if kind in doc:
                total["tables"] += 1
                total["columns"] += len(doc[kind].get("columns")
                                        or doc[kind].get("sql_view_columns") or [])
        model = doc.get("model") or doc.get("worksheet")
        if model:
            total["formulas"] += len(model.get("formulas") or [])
            for entry in model.get("model_tables") or []:
                total["joins"] += len(entry.get("joins") or [])
    return total


def portability(ossie_path: pathlib.Path) -> dict:
    """What a CROSS-VENDOR consumer would actually be able to use.

    Neither measure is visible to Apache's validator, and both correspond to a
    real defect: unresolvable references are apache/ossie#459, and metrics with
    no portable dialect are dropped outright by every vendor converter.
    """
    import yaml
    doc = yaml.safe_load(ossie_path.read_text(encoding="utf-8")) or {}
    fields_by_dataset = {
        ds.get("name"): {f.get("name", "").casefold() for f in ds.get("fields") or []}
        for ds in doc.get("datasets") or []
    }

    def scan(expression: str | None) -> tuple[int, int]:
        seen = bad = 0
        for match in _QUALIFIED_REF.finditer(expression or ""):
            dataset_name, column = _split_ref(match.group(0))
            if dataset_name not in fields_by_dataset:
                continue
            seen += 1
            if column.casefold() not in fields_by_dataset[dataset_name]:
                bad += 1
        return seen, bad

    def portable_expressions(holder: dict):
        for entry in (holder.get("expression") or {}).get("dialects") or []:
            if entry.get("dialect") == DIALECT_PORTABLE:
                yield entry.get("expression")

    # BOTH fields and metrics. Scanning fields only reported 0/0 while every one
    # of 348 metric references named a column no field declares -- the harness
    # was blind to a defect of exactly the kind it exists to catch, in output it
    # had just called clean. Found by an independent review, not by this tool.
    refs = unresolvable = 0
    holders = [f for ds in doc.get("datasets") or [] for f in ds.get("fields") or []]
    metrics = doc.get("metrics") or []
    for holder in holders + list(metrics):
        for expression in portable_expressions(holder):
            seen, bad = scan(expression)
            refs += seen
            unresolvable += bad

    portable_metrics = sum(
        1 for m in metrics
        if any(e.get("dialect") != DIALECT_VENDOR
               for e in (m.get("expression") or {}).get("dialects") or [])
    )
    return {
        "qualified_refs": refs,
        "unresolvable_refs": unresolvable,
        "metrics": len(metrics),
        "portable_metrics": portable_metrics,
    }



#: Apache's validator degrades silently when an optional parser is absent: it
#: prints this warning and then "Validation PASSED", so a run that checked no
#: SQL at all is indistinguishable from a clean one by exit status or by the
#: PASSED line. Every "31/31 passed" measured while building this harness came
#: from that path; with sqlglot present the real figure at the time was 29
#: passed, 2 failed, 7 [SQL] findings.
_SKIPPED_CHECK = re.compile(r"\[SQL\][^\n]*skipping SQL validation", re.I)


def validator_verdict(stdout: str) -> str:
    """PASSED, FAILED, or SKIPPED — three states, not two.

    "A check did not run" is not "a check passed". Treating them as the same
    thing is what let invalid SQL sit in this converter's output unnoticed, so
    the skip is surfaced as its own verdict and `report` fails the run on it.
    """
    if _SKIPPED_CHECK.search(stdout):
        return "SKIPPED"
    return "PASSED" if "Validation PASSED" in stdout else "FAILED"

def issue_codes(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"UNPARSEABLE": 1}
    return dict(collections.Counter(f"{e['severity'][0]}:{e['code']}" for e in entries))


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------

def check_corpus(corpus: pathlib.Path, converter: pathlib.Path, work: pathlib.Path,
                 baseline: pathlib.Path | None, validator: pathlib.Path | None) -> int:
    python = converter / ".venv/bin/python"
    if not python.exists():
        print(f"no converter venv at {python}\n"
              f"  run: cd {converter} && uv sync", file=sys.stderr)
        return 2
    # Apache's validator normally sits two levels up, at <ossie>/validation. A
    # relocated or copied converter breaks that assumption, and an earlier
    # revision then recorded "validator FAILED" for every model when the file
    # was simply absent -- a false failure that looks exactly like a real one.
    # Refuse to guess instead.
    if validator is None:
        validator = converter.parent.parent / "validation/validate.py"
    if not validator.exists():
        print(f"Apache's validator not found at {validator}\n"
              f"  pass --validator <path to ossie>/validation/validate.py",
              file=sys.stderr)
        return 2
    ossie_root = validator.parent.parent
    env = converter_env(converter)
    work.mkdir(parents=True, exist_ok=True)

    results, codes = [], collections.Counter()
    totals = collections.Counter()
    for model_dir in sorted(p for p in corpus.iterdir() if p.is_dir()):
        sources = sorted((model_dir / "tml").glob("*.tml"))
        if not sources:
            continue
        name = model_dir.name
        out = work / name
        out.mkdir(parents=True, exist_ok=True)
        ossie = out / "model.ossie.yaml"
        row = {"model": name, "source": tml_shape(sources)}
        source_columns = model_column_names(sources)

        forward = run([str(python), "-m", "ossie_thoughtspot.cli", "to-ossie",
                       *[str(p) for p in sources], "-o", str(ossie),
                       "--issues", str(out / "forward.json"), "--force"],
                      cwd=converter, env=env)
        if not ossie.exists():
            row["failed"] = f"to-ossie: {forward.stderr.strip()[:200]}"
            results.append(row)
            continue

        checked = run([str(python), str(validator), str(ossie)], cwd=ossie_root, env=env)
        row["validator"] = validator_verdict(checked.stdout)
        row["portability"] = portability(ossie)

        back = out / "back"
        run([str(python), "-m", "ossie_thoughtspot.cli", "to-tml", str(ossie),
             "-o", str(back), "--issues", str(out / "reverse.json"), "--force"],
            cwd=converter, env=env)
        if back.exists():
            returned_paths = sorted(back.glob("*.tml"))
            row["returned"] = tml_shape(returned_paths)
            lost_names = sorted(source_columns - model_column_names(returned_paths))
            if lost_names:
                row["renamed_columns"] = lost_names
        else:
            row["failed"] = "to-tml produced nothing"

        for which in ("forward.json", "reverse.json"):
            codes.update(issue_codes(out / which))
        for key, value in row["portability"].items():
            totals[key] += value
        results.append(row)

    return report(results, codes, totals, work, baseline)


def report(results, codes, totals, work, baseline) -> int:
    lost = [
        r["model"] for r in results
        if "returned" in r and any(r["returned"][k] < r["source"][k] for k in r["source"])
    ]
    failed = [r["model"] for r in results if "failed" in r]
    invalid = [r["model"] for r in results if r.get("validator") == "FAILED"]
    skipped = [r["model"] for r in results if r.get("validator") == "SKIPPED"]
    renamed = [(r["model"], r["renamed_columns"]) for r in results if r.get("renamed_columns")]

    print(f"\nmodels checked            {len(results)}")
    print(f"Apache validator passed   {sum(1 for r in results if r.get('validator') == 'PASSED')}"
          f"/{len(results)}")
    if skipped:
        print(f"validator SKIPPED a check on {len(skipped)}/{len(results)} — see below")
    print(f"losing structure          {len(lost)}  {lost or ''}")
    print(f"renaming Model columns    {len(renamed)}"
          + ("".join(f"\n    {m}: {', '.join(n)}" for m, n in renamed) if renamed else ""))
    print(f"failed to convert         {len(failed)}  {failed or ''}")
    print("\ncross-vendor portability (invisible to the validator):")
    refs, bad = totals["qualified_refs"], totals["unresolvable_refs"]
    metrics, portable = totals["metrics"], totals["portable_metrics"]
    print(f"  qualified refs naming no declared field   {bad}/{refs}")
    print(f"  metrics with a portable dialect           {portable}/{metrics}")

    print("\nissue codes (errors and warnings):")
    for code in sorted(k for k in codes if k.startswith(("E:", "W:"))):
        print(f"  {code:52} {codes[code]}")

    summary = {
        "models": len(results), "lost_structure": lost, "failed": failed,
        "invalid": invalid, "skipped_checks": skipped,
        "renamed_columns": {m: n for m, n in renamed}, "portability": dict(totals),
        "codes": {k: v for k, v in sorted(codes.items())},
    }
    (work / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (work / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nwritten: {work / 'summary.json'}")

    status = 0
    if skipped:
        # Loud, and fatal. A quiet "some checks did not run" is the shape of
        # defect this harness exists to catch, so it must not be one itself.
        print(
            f"\nFAIL: Apache's validator SKIPPED its SQL checks on {len(skipped)} "
            f"model(s), so this run does NOT show them as valid.\n"
            f"  The validator needs its optional parser. Install into the\n"
            f"  interpreter that runs it:  sqlglot, pyyaml, jsonschema\n"
            f"  e.g.  cd <converter> && uv add --dev sqlglot\n"
            f"  Without it validate.py prints a warning and then 'Validation\n"
            f"  PASSED' anyway, which is why this is failed rather than warned."
        )
        status = 1
    if lost or failed or invalid or renamed:
        print("\nFAIL: structure lost, a column was renamed, conversion failed, or the "
              "validator rejected a document")
        status = 1
    if baseline and baseline.exists():
        status = max(status, compare(json.loads(baseline.read_text(encoding="utf-8")), summary))
    return status


def compare(before: dict, now: dict) -> int:
    """Regression against a previous summary. Improvements are reported, not failed."""
    print("\nagainst baseline:")
    status = 0
    for key, higher_is_better in (("unresolvable_refs", False), ("portable_metrics", True)):
        was, is_now = before["portability"].get(key, 0), now["portability"].get(key, 0)
        if was == is_now:
            continue
        better = (is_now > was) if higher_is_better else (is_now < was)
        print(f"  {key}: {was} -> {is_now}  {'better' if better else 'WORSE'}")
        if not better:
            status = 1
    new_codes = {k for k in now["codes"] if k.startswith("E:")} - set(before["codes"])
    if new_codes:
        print(f"  new ERROR codes: {sorted(new_codes)}")
        status = 1
    if status == 0:
        print("  no regression")
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)

    exporter = sub.add_parser("export", help="pull TML from a live cluster")
    exporter.add_argument("--profile", required=True)
    exporter.add_argument("--corpus", type=pathlib.Path, required=True)
    exporter.add_argument("--limit", type=int, default=30)

    checker = sub.add_parser("check", help="convert an existing corpus and report")
    checker.add_argument("--corpus", type=pathlib.Path, required=True)
    checker.add_argument("--converter", type=pathlib.Path, required=True,
                         help="path to apache/ossie converters/thoughtspot")
    checker.add_argument("--work", type=pathlib.Path, default=pathlib.Path("./roundtrip-out"))
    checker.add_argument("--baseline", type=pathlib.Path,
                         help="a previous summary.json to compare against")
    checker.add_argument("--validator", type=pathlib.Path,
                         help="path to apache/ossie validation/validate.py "
                              "(default: two levels up from --converter)")

    args = parser.parse_args()
    if args.mode == "export":
        return export_corpus(args.profile, args.corpus, args.limit)
    return check_corpus(args.corpus, args.converter.expanduser(), args.work,
                        args.baseline,
                        args.validator.expanduser() if args.validator else None)


if __name__ == "__main__":
    sys.exit(main())
