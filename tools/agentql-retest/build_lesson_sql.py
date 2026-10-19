#!/usr/bin/env python3
"""Build `references/lesson-sql.md` from a captured retest run.

The Learn AgentQL course teaches by reading the *generated warehouse SQL* for each lesson.
Offline mode has no cluster, so it cannot run `generate-sql` — it needs that SQL stored.
This script turns a live capture into the committed reference offline mode reads.

Two steps (both live for the capture, offline for the build):

    python3 tools/agentql-retest/run.py --profile <p> --suite lessons guards \\
        --out /tmp/lesson-capture.json
    python3 tools/agentql-retest/build_lesson_sql.py --from /tmp/lesson-capture.json

The capture JSON is keyed by case id and carries, per case, the `sql` sent and the `gen`
response (`status`, `executable_sql`, `errors`). We emit one section per id: the AgentQL, and
either the real `executable_sql` (SUCCESS) or the real status + error (a "break it" lesson).
`fetch` rows are ignored — this file is about the SQL ThoughtSpot compiled, not the numbers.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import re
import sys

# Per-run noise that would churn the file on every recapture: incident ids and internal guids.
_INCIDENT = re.compile(r"\s*Incident Id:\s*[0-9a-f-]+", re.I)
_GUID = re.compile(r'guid:\s*"[0-9a-f-]+"', re.I)


def _clean_message(raw: str) -> str:
    """The CLI puts the error list in a JSON-encoded string; unwrap it and drop per-run ids."""
    msg = raw
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            msg = "; ".join(str(x) for x in parsed)
    except (json.JSONDecodeError, TypeError):
        pass
    msg = _INCIDENT.sub("", msg)
    msg = _GUID.sub('guid: "…"', msg)
    return " ".join(msg.split())

DEFAULT_OUT = (
    pathlib.Path(__file__).resolve().parents[2]
    / "agents/cli/ts-object-model-agentql-query/references/lesson-sql.md"
)

HEADER = """<!-- GENERATED FILE — do not edit by hand.
     Regenerate (needs a live cluster for the capture, then offline for the build):
       python3 tools/agentql-retest/run.py --profile <profile> --suite lessons guards --out /tmp/cap.json
       python3 tools/agentql-retest/build_lesson_sql.py --from /tmp/cap.json
-->
# Captured warehouse SQL — Learn AgentQL lessons

The exact warehouse SQL ThoughtSpot compiled (`executable_sql`) for every course lesson,
captured live on the sample Model **`(Sample) Retail - Apparel`** (the SE demo cluster) on
{date}. **Offline mode shows these verbatim in section 3** — a lesson should never reconstruct
the SQL by hand. Each entry is keyed by the lesson's **Guarded by** id. A *break it* lesson
(one whose point is a rejection) shows the real `status` and error instead of SQL.

Keep this in step with the lessons: the ids come straight from `tools/agentql-retest`
(`--suite lessons guards`), so re-run the two commands above whenever a lesson's AgentQL
changes.
"""


def _fmt(case_id: str, entry: dict) -> str:
    sql = (entry.get("sql") or "").strip()
    gen = entry.get("gen") or {}
    status = gen.get("status")
    parts = [f"## {case_id}", ""]
    row = (entry.get("row") or "").strip()
    if row:
        parts += [f"*{row}*", ""]
    parts += ["**AgentQL**", "", "```sql", sql, "```", ""]
    if status == "SUCCESS":
        exe = (gen.get("executable_sql") or "").strip()
        parts += ["**Generated SQL** (`status: SUCCESS`)", "", "```sql", exe, "```", ""]
    else:
        msg = ""
        errs = gen.get("errors") or []
        if errs and isinstance(errs[0], dict):
            msg = _clean_message((errs[0].get("message") or "").strip())
        if len(msg) > 400:
            msg = msg[:400] + " …"
        line = f"**Rejected — `status: {status}`**"
        if msg:
            line += f" — {msg}"
        parts += [line, ""]
    return "\n".join(parts)


def build(capture: dict, date: str) -> str:
    body = [HEADER.format(date=date), ""]
    for case_id, entry in capture.items():
        body.append(_fmt(case_id, entry))
        body.append("---\n")
    text = "\n".join(body).rstrip() + "\n"
    return text


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="src", required=True, help="capture JSON from run.py --out")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="output markdown (default: references/lesson-sql.md)")
    ap.add_argument("--date", default=_dt.date.today().isoformat(), help="capture date (default: today)")
    args = ap.parse_args()

    capture = json.loads(pathlib.Path(args.src).read_text())
    if not isinstance(capture, dict) or not capture:
        print("capture JSON is empty or not an object", file=sys.stderr)
        return 2
    out = pathlib.Path(args.out)
    out.write_text(build(capture, args.date))
    n_sql = sum(1 for e in capture.values() if (e.get("gen") or {}).get("status") == "SUCCESS")
    print(f"wrote {out} — {len(capture)} lessons ({n_sql} with SQL, {len(capture) - n_sql} rejected)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
