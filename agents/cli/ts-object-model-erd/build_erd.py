"""CLI: discover Model + Table TMLs, parse, assemble, render an ERD HTML file."""
import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(_HERE)),
                                "shared", "erd"))
import parser as erd_parser  # noqa: E402
import erd_data              # noqa: E402
import render                # noqa: E402


def _discover(src_paths):
    models, tables = [], []
    for p in src_paths:
        if os.path.isdir(p):
            for root, _dirs, files in os.walk(p):
                for f in files:
                    fp = os.path.join(root, f)
                    if f.endswith(".model.tml"):
                        models.append(fp)
                    elif f.endswith(".table.tml"):
                        tables.append(fp)
        elif p.endswith(".model.tml"):
            models.append(p)
        elif p.endswith(".table.tml"):
            tables.append(p)
    return models, tables


def _table_index(table_paths):
    by_guid, by_name = {}, {}
    for tp in table_paths:
        t = erd_parser.load_tml(tp)
        guid = t.get("guid")
        name = t.get("table", {}).get("name")
        if guid:
            by_guid[guid] = t
        if name:
            by_name[name] = t
    return by_guid, by_name


def build(src_paths, out_path, *, max_models=25, redact_rls=False, log=print):
    model_paths, table_paths = _discover(src_paths)
    by_guid, by_name = _table_index(table_paths)
    parsed = []
    for mp in model_paths:
        mtml = erd_parser.load_tml(mp)
        needed = {}
        for mt in mtml.get("model", {}).get("model_tables", []):
            t = by_guid.get(mt.get("fqn")) or by_name.get(mt.get("name"))
            if t:
                needed[mt["name"]] = t
        parsed.append(erd_parser.parse_model(mtml, needed, log=log))
    bundle = erd_data.assemble(parsed, max_models=max_models,
                               redact_rls=redact_rls, log=log)
    return render.write_html(bundle, out_path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Render ThoughtSpot Model TML to an ERD HTML.")
    ap.add_argument("src", nargs="+", help="TML files or directories")
    ap.add_argument("--out", default="model_erd.html")
    ap.add_argument("--max-models", type=int, default=25)
    ap.add_argument("--redact-rls", action="store_true")
    args = ap.parse_args(argv)
    out = build(args.src, args.out, max_models=args.max_models, redact_rls=args.redact_rls)
    print("Wrote %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
