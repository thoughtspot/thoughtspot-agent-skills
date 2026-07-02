"""CLI: discover Model + Table TMLs, parse, assemble, render an ERD HTML file.

Sources may be, in any mix:
  * a `ts tml export ... [--associated]` JSON dump — either the raw response
    (a list of ``{"edoc": "<tml string>", ...}`` objects) or its ``--parse``
    form (a list of already-parsed TML dicts). This is what the SKILL.md flow
    produces, so the builder ingests it directly — no manual split step.
  * individual ``.tml`` / ``.yaml`` files, or a directory of them.

Model vs. table is decided by TML **content** (the ``model:`` / ``table:`` key),
never by filename, so loosely-named dumps work too.
"""
import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(_HERE)),
                                "shared", "erd"))
import parser as erd_parser  # noqa: E402
import erd_data              # noqa: E402
import render                # noqa: E402

import yaml  # noqa: E402  (bundled with erd_parser's deps)

_TML_EXTS = (".tml", ".yaml", ".yml")


def _coerce_tml(obj):
    """Return a parsed TML dict from a value that may be a dict or a TML string.

    Accepts both the raw `ts tml export` shape (``{"edoc": "<tml>"}``) and the
    ``--parse`` shape (``{"edoc": {...}}`` or a bare TML dict). Returns None for
    anything that isn't a recognisable Model or Table TML.
    """
    if isinstance(obj, str):
        try:
            obj = yaml.safe_load(obj)
        except yaml.YAMLError:
            return None
    if not isinstance(obj, dict):
        return None
    # `ts tml export` wraps each TML under `edoc` (string when raw, dict when --parse).
    if "edoc" in obj and not ("model" in obj or "table" in obj):
        return _coerce_tml(obj["edoc"])
    if "model" in obj or "table" in obj:
        return obj
    return None


def _load_source_file(path):
    """Yield parsed TML dicts from one file (a JSON export dump or a single TML)."""
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    # Try JSON first — a `ts tml export` dump is a JSON list (or single object).
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = yaml.safe_load(raw)
    items = data if isinstance(data, list) else [data]
    for item in items:
        tml = _coerce_tml(item)
        if tml is not None:
            yield tml


def _discover(src_paths):
    """Collect (model_tmls, table_tmls) as parsed dicts from files/dirs/dumps."""
    files = []
    for p in src_paths:
        if os.path.isdir(p):
            for root, _dirs, names in os.walk(p):
                for n in names:
                    if n.endswith(_TML_EXTS) or n.endswith(".json"):
                        files.append(os.path.join(root, n))
        else:
            files.append(p)
    models, tables = [], []
    for fp in files:
        try:
            for tml in _load_source_file(fp):
                (models if "model" in tml else tables).append(tml)
        except (OSError, yaml.YAMLError) as exc:
            print("Skipping unreadable source %s: %s" % (fp, exc), file=sys.stderr)
    return models, tables


def _table_index(table_tmls):
    by_guid, by_name = {}, {}
    for t in table_tmls:
        guid = t.get("guid")
        name = t.get("table", {}).get("name")
        if guid:
            by_guid[guid] = t
        if name:
            by_name[name] = t
    return by_guid, by_name


def _apply_ai_analysis(parsed, ai_map, log=print):
    """Attach an agent-synthesised corpus to matching models (by guid, then name).

    ai_map: {model_guid_or_name: {ai_analysis: {domain, objectives, personas,
    questions}, ai_instructions: [...]}}. Read-only enrichment of the ERD — never
    written back to the source model.
    """
    for m in parsed:
        info = m["model"]
        entry = ai_map.get(info.get("guid")) or ai_map.get(info.get("name"))
        if not entry:
            continue
        if entry.get("ai_analysis"):
            info["ai_analysis"] = entry["ai_analysis"]
        if entry.get("ai_instructions"):
            info["ai_instructions"] = entry["ai_instructions"]
        log("Applied AI-analysis corpus to model '%s'." % info.get("name", ""))


def build(src_paths, out_path, *, max_models=25, redact_rls=False,
          ai_analysis_path=None, log=print):
    model_tmls, table_tmls = _discover(src_paths)
    if not model_tmls:
        raise SystemExit(
            "No Model TML found in the given source(s). Expected a `ts tml export "
            "--associated` JSON dump or .tml file(s) containing a `model:` block. "
            "Found %d table TML(s) but 0 models — nothing to diagram." % len(table_tmls)
        )
    by_guid, by_name = _table_index(table_tmls)
    parsed = []
    for mtml in model_tmls:
        needed = {}
        for mt in mtml.get("model", {}).get("model_tables", []):
            t = by_guid.get(mt.get("fqn")) or by_name.get(mt.get("name"))
            if t:
                needed[mt["name"]] = t
        parsed.append(erd_parser.parse_model(mtml, needed, log=log))
    if ai_analysis_path:
        with open(ai_analysis_path, "r", encoding="utf-8") as fh:
            _apply_ai_analysis(parsed, json.load(fh), log=log)
    bundle = erd_data.assemble(parsed, max_models=max_models,
                               redact_rls=redact_rls, log=log)
    return render.write_html(bundle, out_path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Render ThoughtSpot Model TML to an ERD HTML.")
    ap.add_argument("src", nargs="+",
                    help="`ts tml export` JSON dump(s), .tml/.yaml file(s), or a "
                         "directory of them. Model vs. table is detected by content.")
    ap.add_argument("--out", default="model_erd.html")
    ap.add_argument("--max-models", type=int, default=25)
    ap.add_argument("--redact-rls", action="store_true")
    ap.add_argument("--ai-analysis", default=None,
                    help="Path to a JSON corpus (domain/objectives/personas/questions/"
                         "ai_instructions) keyed by model guid or name, synthesised from "
                         "the model definition. Enriches the ERD only; never written back.")
    args = ap.parse_args(argv)
    out = build(args.src, args.out, max_models=args.max_models,
                redact_rls=args.redact_rls, ai_analysis_path=args.ai_analysis)
    print("Wrote %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
